"""
routes/cron.py — Internal cron endpoints for Cloud Scheduler.

Authentication: every request must include the header
  X-Cron-Secret: <value of CRON_SECRET env var>

Endpoints:
  POST /cron/daily   — fetch FX rates + stock prices for all active lots
  POST /cron/friday  — generate AI portfolio review for all approved users
  GET  /cron/health  — simple health check (no secret required)
"""
import os
import json
from datetime import datetime
from flask import Blueprint, request, jsonify
from db import get_db, ph, is_pg, fx_set, fx_get_all, upsert_snapshot_sql
from services.gemini import fetch_prices, fetch_fx_rates
from services import agents as _agents
from services.secrets import get_gemini_key

bp = Blueprint("cron", __name__)

CRON_SECRET = os.environ.get("CRON_SECRET", "")


# ── Auth helper ───────────────────────────────────────────────────────────────

def _check_secret():
    """Return True if the request has the correct cron secret."""
    if not CRON_SECRET:
        # If no secret set, only allow requests from Cloud Run internal network
        # (identified by the X-Cloudscheduler-Jobname header)
        return bool(request.headers.get("X-Cloudscheduler-Jobname"))
    incoming = request.headers.get("X-Cron-Secret", "")
    return incoming == CRON_SECRET


def _today():
    return datetime.today().strftime("%Y-%m-%d")


# ── Helpers (no user session needed) ─────────────────────────────────────────

def _get_api_key():
    """Get Gemini API key from Secret Manager (no user needed)."""
    key = get_gemini_key(None)
    if not key:
        # Fallback: check if any admin user has stored a key in config
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("""SELECT value FROM config
                WHERE key='gemini_api_key'
                ORDER BY user_id LIMIT 1""")
            row = cur.fetchone()
            if row:
                key = row["value"] if is_pg() else row[0]
        finally:
            conn.close()
    return key


def _fetchall(conn, sql, params=()):
    from datetime import date
    from decimal import Decimal
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = []
    for r in cur.fetchall():
        d = dict(r)
        for k, v in d.items():
            if isinstance(v, (date, datetime)):
                d[k] = v.isoformat()[:10]
            elif isinstance(v, Decimal):
                d[k] = float(v)
        rows.append(d)
    return rows


def _fetchone(conn, sql, params=()):
    from datetime import date
    from decimal import Decimal
    cur = conn.cursor()
    cur.execute(sql, params)
    r = cur.fetchone()
    if not r:
        return None
    d = dict(r)
    for k, v in d.items():
        if isinstance(v, (date, datetime)):
            d[k] = v.isoformat()[:10]
        elif isinstance(v, Decimal):
            d[k] = float(v)
    return d


def _exec(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur


EXCUR = {
    "NSE": "KES", "NYSE": "USD", "NASDAQ": "USD", "LSE": "GBP",
    "JSE": "ZAR", "EURONEXT": "EUR", "HKEX": "HKD", "CRYPTO": "USD",
}


# ── Health check (no auth needed — for uptime monitoring) ─────────────────────

@bp.route("/cron/health")
def health():
    return jsonify({"ok": True, "time": _today()})


# ── Daily: fetch FX + prices ──────────────────────────────────────────────────

@bp.route("/cron/daily", methods=["POST"])
def cron_daily():
    """
    1. Fetch FX rates (USD/GBP/EUR/ZAR → KES) via Gemini
    2. Fetch end-of-day prices for all active lots across all users
    3. Save snapshots for all users
    """
    if not _check_secret():
        return jsonify({"error": "Forbidden"}), 403

    api_key = _get_api_key()
    if not api_key:
        return jsonify({"error": "No Gemini API key configured"}), 500

    today  = _today()
    result = {"date": today, "fx": {}, "prices": [], "skipped": [], "errors": []}

    # ── Step 1: FX rates ──────────────────────────────────────────────────────
    try:
        rates = fetch_fx_rates(api_key)
        for currency, rate in rates.items():
            if currency != "KES":
                fx_set(currency, rate, today)
        result["fx"] = rates
        print(f"[cron/daily] FX rates updated: {rates}", flush=True)
    except Exception as e:
        msg = f"FX fetch failed: {e}"
        result["errors"].append(msg)
        print(f"[cron/daily] {msg}", flush=True)
        # Use cached rates for price conversion
        rates = fx_get_all()

    # ── Step 2: Stock prices ──────────────────────────────────────────────────
    conn = get_db()
    try:
        # Get all distinct tickers across ALL users
        all_positions = _fetchall(conn, """
            SELECT DISTINCT ticker, COALESCE(exchange,'NSE') as exchange
            FROM stock_lots WHERE shares > 0
        """)

        if not all_positions:
            result["message"] = "No active positions found"
            return jsonify(result)

        # Only fetch tickers not already in global_prices today
        already_today = set()
        existing = _fetchall(conn, f"""
            SELECT DISTINCT ticker, exchange FROM global_prices WHERE date={ph()}
        """, (today,))
        for e in existing:
            already_today.add((e["ticker"], e["exchange"]))

        to_fetch = [t for t in all_positions
                    if (t["ticker"], t["exchange"]) not in already_today]
        skipped  = [t["ticker"] for t in all_positions
                    if (t["ticker"], t["exchange"]) in already_today]
        result["skipped"] = skipped

        if not to_fetch:
            result["message"] = f"All {len(skipped)} tickers already updated today"
            print(f"[cron/daily] {result['message']}", flush=True)
            return jsonify(result)
    finally:
        conn.close()

    # Fetch prices from Gemini
    try:
        prices = fetch_prices(api_key, to_fetch)
        print(f"[cron/daily] Gemini returned {len(prices)} prices", flush=True)
    except Exception as e:
        msg = f"Price fetch failed: {e}"
        result["errors"].append(msg)
        print(f"[cron/daily] {msg}", flush=True)
        return jsonify(result), 500

    # Save to global_prices
    conn = get_db()
    try:
        for tkr, price in prices.items():
            row = _fetchone(conn, f"""
                SELECT COALESCE(exchange,'NSE') as exchange, currency
                FROM stock_lots WHERE UPPER(ticker)={ph()} LIMIT 1
            """, (tkr,))
            exch = row["exchange"] if row else "NSE"
            cur  = (row.get("currency") or EXCUR.get(exch, "KES")) if row else "KES"

            if is_pg():
                _exec(conn, """
                    INSERT INTO global_prices (ticker,exchange,price,currency,date,note)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(ticker,exchange,date) DO UPDATE SET
                        price=EXCLUDED.price, note=EXCLUDED.note
                """, (tkr, exch, price, cur, today, "cron auto-fetch"))
            else:
                _exec(conn, """
                    INSERT OR REPLACE INTO global_prices
                        (ticker,exchange,price,currency,date,note)
                    VALUES (?,?,?,?,?,?)
                """, (tkr, exch, price, cur, today, "cron auto-fetch"))

            result["prices"].append({"ticker": tkr, "exchange": exch, "price": price})

        conn.commit()
        print(f"[cron/daily] Saved {len(result['prices'])} prices", flush=True)
    finally:
        conn.close()

    # ── Step 3: Update snapshots for all approved users ───────────────────────
    conn = get_db()
    try:
        users = _fetchall(conn, """
            SELECT id FROM users WHERE role IN ('user','admin')
        """)
    finally:
        conn.close()

    snapshot_errors = []
    for user in users:
        try:
            _save_user_snapshot(user["id"], rates)
        except Exception as e:
            snapshot_errors.append(f"User {user['id']}: {e}")

    if snapshot_errors:
        result["errors"].extend(snapshot_errors)

    result["message"] = (
        f"Updated {len(result['prices'])} price(s)"
        + (f", skipped {len(skipped)} already done" if skipped else "")
        + f", snapshots for {len(users)} user(s)"
    )
    print(f"[cron/daily] Done — {result['message']}", flush=True)
    return jsonify(result)


def _save_user_snapshot(user_id, fx_rates):
    """Save today's portfolio snapshot for a specific user."""
    from datetime import date
    conn = get_db()
    try:
        # Build portfolio for this user
        lots   = _fetchall(conn,
            f"SELECT * FROM stock_lots WHERE user_id={ph()} AND shares > 0", (user_id,))
        prices = _fetchall(conn, "SELECT * FROM global_prices ORDER BY date DESC")
        savings = _fetchall(conn,
            f"SELECT * FROM savings WHERE user_id={ph()}", (user_id,))

        # Latest price per ticker
        latest = {}
        for p in prices:
            k = (p["ticker"], p.get("exchange","NSE"))
            if k not in latest:
                latest[k] = float(p["price"])

        def to_kes(amount, currency):
            if currency == "KES" or not currency:
                return float(amount)
            return float(amount) * fx_rates.get(currency, 1.0)

        stock_value = 0.0
        total_cost  = 0.0
        for lot in lots:
            exch = lot.get("exchange","NSE")
            cur  = lot.get("currency") or EXCUR.get(exch, "KES")
            k    = (lot["ticker"], exch)
            cost = float(lot["shares"]) * float(lot["purchase_price"])
            total_cost += to_kes(cost, cur)
            price = latest.get(k)
            if price:
                mkt = float(lot["shares"]) * price
                stock_value += to_kes(mkt, cur)
            else:
                stock_value += to_kes(cost, cur)

        other_value = sum(
            float(r["amount"]) if r["type"]=="deposit" else -float(r["amount"])
            for r in savings)

        total       = round(stock_value + other_value, 2)
        stock_value = round(stock_value, 2)
        other_value = round(other_value, 2)
        total_cost  = round(total_cost, 2)
        gain        = round(total - total_cost, 2)
        today       = _today()

        _exec(conn, upsert_snapshot_sql(),
              (user_id, today, total, stock_value, other_value, total_cost, gain))
        conn.commit()
    finally:
        conn.close()


# ── Friday: generate portfolio review for all approved users ──────────────────

@bp.route("/cron/friday", methods=["POST"])
def cron_friday():
    """
    Run the full 9-agent AI portfolio review for every approved user.
    Runs SYNCHRONOUSLY — keeps the HTTP connection open until all pipelines complete.
    Cloud Run timeout is 600s which covers the ~5-8 min pipeline runtime.
    """
    if not _check_secret():
        return jsonify({"error": "Forbidden"}), 403

    api_key = _get_api_key()
    if not api_key:
        return jsonify({"error": "No Gemini API key configured"}), 500

    today  = _today()
    result = {"date": today, "reviews": [], "errors": []}

    conn = get_db()
    try:
        users = _fetchall(conn,
            "SELECT id, name FROM users WHERE role IN ('user','admin')")
    finally:
        conn.close()

    if not users:
        return jsonify({"message": "No approved users", **result})

    import threading, uuid

    def run_for_user(user):
        uid  = user["id"]
        name = user["name"]
        try:
            portfolio = _build_user_portfolio(uid)
            sav       = _get_user_savings(uid)
            job_id    = str(uuid.uuid4())

            print(f"[cron/friday] Starting 9-agent pipeline for {name} (job {job_id})", flush=True)

            # Run pipeline SYNCHRONOUSLY — blocks until all 9 agents complete
            _agents.run_pipeline(job_id, uid, api_key, portfolio, sav)

            print(f"[cron/friday] Pipeline complete for {name}", flush=True)
            return {"user_id": uid, "name": name, "ok": True, "job_id": job_id}
        except Exception as e:
            msg = f"User {uid} ({name}): {e}"
            print(f"[cron/friday] ERROR — {msg}", flush=True)
            return {"user_id": uid, "name": name, "ok": False, "error": str(e)}

    # Run pipelines for all users sequentially (one user = one person anyway)
    for user in users:
        res = run_for_user(user)
        if res["ok"]:
            result["reviews"].append(res)
        else:
            result["errors"].append(res["error"])

    result["message"] = (
        f"9-agent review complete for {len(result['reviews'])} user(s)"
        + (f", {len(result['errors'])} error(s)" if result["errors"] else "")
    )
    print(f"[cron/friday] Done — {result['message']}", flush=True)
    return jsonify(result)


def _build_user_portfolio(user_id):
    """Build portfolio dict for a specific user (used by cron)."""
    from db import fx_get_all
    conn = get_db()
    try:
        lots    = _fetchall(conn,
            f"SELECT * FROM stock_lots WHERE user_id={ph()} AND shares > 0", (user_id,))
        prices  = _fetchall(conn, "SELECT * FROM global_prices ORDER BY date DESC")
        sales   = _fetchall(conn,
            f"SELECT * FROM stock_sales WHERE user_id={ph()}", (user_id,))
    finally:
        conn.close()

    fx_rates = fx_get_all()
    latest = {}
    for p in prices:
        k = (p["ticker"], p.get("exchange","NSE"))
        if k not in latest: latest[k] = float(p["price"])

    tickers = {}
    for lot in lots:
        exch = lot.get("exchange","NSE")
        cur  = lot.get("currency") or EXCUR.get(exch,"KES")
        k    = (lot["ticker"], exch)
        if k not in tickers:
            tickers[k] = {"ticker":lot["ticker"],"exchange":exch,"currency":cur,
                          "total_shares":0,"total_cost":0}
        tickers[k]["total_shares"] += float(lot["shares"])
        tickers[k]["total_cost"]   += float(lot["shares"]) * float(lot["purchase_price"])

    holdings = []
    total_cost = total_market = 0
    for k, h in tickers.items():
        h["avg_cost"] = round(h["total_cost"]/h["total_shares"],4) if h["total_shares"] else 0
        price = latest.get(k)
        if price:
            mkt = h["total_shares"] * price
            h["market_price"] = price
            h["pct_return"]   = round((mkt-h["total_cost"])/h["total_cost"]*100,2) if h["total_cost"] else 0
            def to_kes(a,c): return float(a)*fx_rates.get(c or "KES",1.0)
            total_market += to_kes(mkt, h["currency"])
        else:
            h["market_price"] = None; h["pct_return"] = None
        def to_kes(a,c): return float(a)*fx_rates.get(c or "KES",1.0)
        total_cost += to_kes(h["total_cost"], h["currency"])
        holdings.append(h)

    realized = sum((float(s["sale_price"])-float(s["purchase_price"]))*float(s["shares"]) for s in sales)
    return {
        "holdings": holdings,
        "total_cost": round(total_cost,2),
        "total_market": round(total_market,2),
        "total_gain": round(total_market-total_cost,2),
        "portfolio_pct": round((total_market-total_cost)/total_cost*100,2) if total_cost else 0,
        "total_realized": round(realized,2),
        "fx_rates": fx_rates,
    }

def _get_user_savings(user_id):
    """Returns rich savings dict matching gen_review format: {totals, entries}."""
    from db import fx_get_all
    conn = get_db()
    try:
        rows = _fetchall(conn,
            f"SELECT label,asset_class,type,amount,currency,date,note "
            f"FROM savings WHERE user_id={ph()} ORDER BY asset_class,date",
            (user_id,))
    finally:
        conn.close()

    fx_rates  = fx_get_all()
    sav_totals, sav_entries = {}, []
    for r in rows:
        cur  = r.get("currency") or "KES"
        sign = 1 if r["type"] in ("deposit","interest") else -1
        rate = fx_rates.get(cur, 1.0)
        v    = float(r["amount"]) * rate * sign
        cls  = r["asset_class"]
        sav_totals[cls] = sav_totals.get(cls, 0) + v
        sav_entries.append({
            "label":       r["label"] or "",
            "asset_class": cls,
            "type":        r["type"],
            "amount":      float(r["amount"]),
            "currency":    cur,
            "amount_kes":  round(v, 2),
            "date":        str(r.get("date","")) if r.get("date") else "",
            "note":        r.get("note","") or "",
        })
    return {"totals": sav_totals, "entries": sav_entries}
