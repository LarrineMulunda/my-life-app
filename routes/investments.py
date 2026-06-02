"""
Investment routes — per-user data, lot-based selling, ticker search,
currency support, smart price fetch (skip already updated tickers),
FX rate tracking and USD→KES conversion.
"""
import csv, io, json
from datetime import datetime, date
from decimal import Decimal
from flask import Blueprint, request, jsonify, Response
from flask_login import current_user
from db import get_db, cfg_get, cfg_set, ph, is_pg, upsert_snapshot_sql
from services.gemini import fetch_prices, fetch_fx_rates, generate_review
from services import agents as _agents
from services import price_agents as _price_agents
from services.secrets import get_gemini_key, save_gemini_key_to_secret
from routes.auth import approved_required

bp = Blueprint("investments", __name__)

ASSET_CLASSES = ["Cash","SACCO / Chama","Bonds / T-Bills","Pension / NSSF",
                 "Real Estate","Crypto","Unit Trust / MMF","Farming / Agri",
                 "Foreign Currency","Other"]
EXCHANGES     = ["NSE","NYSE","NASDAQ","LSE","JSE","EURONEXT","HKEX",
                 "CRYPTO","DSE","USE","GSE","BRVM","Other"]
EXCUR         = {"NSE":"KES","NYSE":"USD","NASDAQ":"USD","LSE":"GBP",
                 "JSE":"ZAR","EURONEXT":"EUR","HKEX":"HKD","CRYPTO":"USD","Other":"—"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _today():  return datetime.today().strftime("%Y-%m-%d")
def p():       return ph()
def uid():     return current_user.id

def _require(d, *keys):
    missing = [k for k in keys if not d.get(k) and d.get(k) != 0]
    if missing:
        raise ValueError(f"Missing required field(s): {', '.join(missing)}")

def _clean(d):
    """Convert PostgreSQL date/Decimal objects to JSON-safe types."""
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

def _fetchall(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(sql, params)
    return [_clean(dict(r)) for r in cur.fetchall()]

def _fetchone(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(sql, params)
    r = cur.fetchone()
    return _clean(dict(r)) if r else None


# ── FX rate helpers ───────────────────────────────────────────────────────────

def _get_fx_rates(conn):
    """Get GLOBAL FX rates (shared by all users). Falls back to defaults."""
    from db import fx_get_all
    rates = fx_get_all()
    # Ensure sensible defaults exist
    defaults = {"KES": 1.0, "USD": 130.0, "GBP": 165.0, "EUR": 141.0,
                "ZAR": 7.1, "TZS": 0.05, "HKD": 16.7, "UGX": 0.035, "GHS": 9.0}
    for k, v in defaults.items():
        rates.setdefault(k, v)
    return rates

def _to_kes(amount, currency, rates):
    """Convert amount to KES. Warns if rate is missing (logs to stderr)."""
    if currency == "KES" or not currency:
        return float(amount)
    rate = rates.get(currency)
    if rate is None:
        print(f"[WARN] _to_kes: no rate for {currency}", file=__import__("sys").stderr, flush=True)
        return float(amount)
    return float(amount) * float(rate)


# ── Tickers API ───────────────────────────────────────────────────────────────


@bp.route("/api/savings/exchange", methods=["POST"])
@approved_required
def exchange_assets():
    """Record a partial or full conversion between asset classes.

    Stocks: sell N shares from a lot (partial or full).
      - Partial: reduces lot shares, records sale for N shares only.
      - Full:    zeroes lot, records sale for all shares.
    Savings: withdraw amount from label (partial always — just a new entry).
    """
    d = request.json or {}
    try:
        _require(d, "from_type", "to_type", "amount", "date")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    from_type   = d["from_type"]
    to_type     = d["to_type"]
    amount      = float(d["amount"])
    date        = d["date"]
    currency    = d.get("currency", "KES")
    note        = d.get("note", "") or f"Exchange on {date}"

    from_class  = d.get("from_class", "")
    from_label  = d.get("from_label", "")
    from_lot_id = d.get("from_lot_id")
    from_shares = d.get("from_shares")   # None = sell all; number = partial

    to_class    = d.get("to_class", "")
    to_label    = d.get("to_label", "")
    to_ticker   = d.get("to_ticker", "")
    to_exchange = d.get("to_exchange", "")

    conn = get_db()
    try:
        fx_rates     = _get_fx_rates(conn)
        rows_created = []
        source_desc  = ""

        # ── Debit the source ──────────────────────────────────────────────────
        if from_type == "savings":
            # Validate: check available balance for this label
            bal_rows = _fetchall(conn, f"""
                SELECT SUM(CASE WHEN type IN ('deposit','interest') THEN amount
                               ELSE -amount END) as bal
                FROM savings
                WHERE user_id={p()} AND label={p()}
            """, (uid(), from_label or from_class))
            bal = float((bal_rows[0]["bal"] or 0) if bal_rows else 0)
            fx  = fx_rates.get(currency, 1.0)
            amount_kes = amount * fx
            if bal > 0 and amount_kes > bal * 1.01:  # 1% tolerance for rounding
                conn.rollback()
                return jsonify({"error": f"Insufficient balance. Available: KES {bal:,.2f}"}), 400

            _exec(conn, f"""INSERT INTO savings
                (user_id, label, asset_class, amount, type, currency, date, note)
                VALUES ({p()},{p()},{p()},{p()},{p()},{p()},{p()},{p()})""",
                (uid(), from_label or from_class, from_class, amount,
                 "withdrawal", currency, date,
                 f"→ Exchange to {to_class or to_ticker}: {note}"))
            source_desc = from_label or from_class
            rows_created.append(
                f"Withdrew {currency} {amount:,.2f} from {source_desc}"
                + (f" (remaining balance: KES {max(0, bal - amount_kes):,.2f})" if bal else "")
            )

        elif from_type == "stocks" and from_lot_id:
            # FOR UPDATE locks the row for the duration of this transaction,
            # preventing concurrent partial sales from overselling the lot.
            if is_pg():
                lot = _fetchone(conn,
                    f"SELECT * FROM stock_lots WHERE id={p()} AND user_id={p()} FOR UPDATE",
                    (from_lot_id, uid()))
            else:
                lot = _fetchone(conn,
                    f"SELECT * FROM stock_lots WHERE id={p()} AND user_id={p()}",
                    (from_lot_id, uid()))
            if not lot:
                conn.rollback()
                return jsonify({"error": "Lot not found"}), 404

            lot_shares   = float(lot["shares"])
            lot_currency = lot.get("currency") or "KES"

            # Determine shares to sell
            if from_shares is not None:
                sell_shares = float(from_shares)
                if sell_shares <= 0:
                    conn.rollback()
                    return jsonify({"error": "Shares to sell must be > 0"}), 400
                if sell_shares > lot_shares + 0.000001:
                    conn.rollback()
                    return jsonify({
                        "error": f"Cannot sell {sell_shares:,.4f} shares — only {lot_shares:,.4f} in this lot"
                    }), 400
                sell_shares = min(sell_shares, lot_shares)
            else:
                sell_shares = lot_shares   # sell all

            is_partial  = sell_shares < lot_shares - 0.000001
            sale_price  = amount / sell_shares if sell_shares else 0
            rem_shares  = round(lot_shares - sell_shares, 6)

            # Record the sale
            _exec(conn, f"""INSERT INTO stock_sales
                (user_id, lot_id, ticker, exchange, shares, purchase_price,
                 sale_price, date, note)
                VALUES ({p()},{p()},{p()},{p()},{p()},{p()},{p()},{p()},{p()})""",
                (uid(), from_lot_id, lot["ticker"], lot.get("exchange","NSE"),
                 sell_shares, lot["purchase_price"], sale_price, date,
                 f"{'Partial ' if is_partial else ''}Exchange → {to_label or to_class or to_ticker}"))

            # Update lot: reduce shares (or zero out if full sale)
            _exec(conn,
                f"UPDATE stock_lots SET shares={p()} WHERE id={p()} AND user_id={p()}",
                (rem_shares, from_lot_id, uid()))

            source_desc = f"{lot['ticker']} ({lot.get('exchange','NSE')})"
            rows_created.append(
                f"Sold {sell_shares:,.4f} of {lot_shares:,.4f} shares of {source_desc}"
                f" @ {lot_currency} {sale_price:.4f} → {currency} {amount:,.2f}"
                + (f" · {rem_shares:,.4f} shares remaining" if is_partial else " · lot closed")
            )

        # ── Credit the destination ────────────────────────────────────────────
        if to_type == "savings":
            _exec(conn, f"""INSERT INTO savings
                (user_id, label, asset_class, amount, type, currency, date, note)
                VALUES ({p()},{p()},{p()},{p()},{p()},{p()},{p()},{p()})""",
                (uid(), to_label or to_class, to_class, amount,
                 "deposit", currency, date,
                 f"← Exchange from {source_desc or from_class}: {note}"))
            rows_created.append(f"Deposited {currency} {amount:,.2f} into {to_label or to_class}")

        elif to_type == "stocks" and to_ticker:
            to_shares = float(d.get("to_shares") or 0)
            price     = amount / to_shares if to_shares else 0
            _exec(conn, f"""INSERT INTO stock_lots
                (user_id, ticker, exchange, shares, purchase_price,
                 currency, date, note)
                VALUES ({p()},{p()},{p()},{p()},{p()},{p()},{p()},{p()})""",
                (uid(), to_ticker.upper(), to_exchange or "NSE", to_shares,
                 price, currency, date,
                 f"← Exchange from {source_desc or from_class}"))
            rows_created.append(f"Bought {to_shares:,.4f} {to_ticker} @ {currency} {price:.4f}")

        conn.commit()
        return jsonify({"ok": True, "actions": rows_created})

    except Exception as e:
        try: conn.rollback()
        except: pass
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@bp.route("/api/investments/all")
@approved_required
def investments_all():
    """Single endpoint returning stocks, overview, savings, FX, lots, and anomalies.
    Reduces 6 round trips to 1 on page load."""
    conn = get_db()
    try:
        port     = _build_portfolio(conn)
        sav_rows = _fetchall(conn,
            f"SELECT * FROM savings WHERE user_id={ph()}", (uid(),))
        fx_rates = _get_fx_rates(conn)
        lots     = port.get("lots", [])
        anomalies_pending = _fetchall(conn,
            "SELECT COUNT(*) as n FROM price_anomalies WHERE status='manual_review'")
    finally:
        conn.close()

    # Build overview
    sav_by_class = {}
    for r in sav_rows:
        cur  = r.get("currency") or "KES"
        sign = 1 if r["type"] in ("deposit","interest") else -1
        v_kes = _to_kes(float(r["amount"]), cur, fx_rates) * sign
        sav_by_class[r["asset_class"]] = sav_by_class.get(r["asset_class"], 0) + v_kes

    savings_net  = sum(sav_by_class.values())
    total_market = port["total_market"] + savings_net
    total_cost   = port["total_cost"]   + savings_net
    total_gain   = port["total_market"] - port["total_cost"]

    return jsonify({
        "ok": True,
        "stocks": {
            "holdings":       port["holdings"],
            "total_cost":     port["total_cost"],
            "total_market":   port["total_market"],
            "total_gain":     port["total_gain"],
            "portfolio_pct":  port["portfolio_pct"],
            "total_realized": port["total_realized"],
        },
        "overview": {
            "total_value":    round(total_market, 2),
            "total_cost":     round(total_cost, 2),
            "total_gain":     round(total_gain, 2),
            "total_realized": port["total_realized"],
            "savings_net":    round(savings_net, 2),
            "has_foreign":    any(h.get("currency","KES") != "KES" for h in port["holdings"]),
            "asset_summary":  {
                # Stocks grouped by exchange
                **{
                    f"Stocks ({h['exchange']})": {
                        "value":    round((h.get("market_value_kes") or h.get("total_cost_kes") or 0), 2),
                        "cost":     round(h.get("total_cost_kes") or 0, 2),
                        "gain":     round((h.get("gain_loss_kes") or 0), 2),
                        "gain_pct": round((h.get("pct_return") or 0), 2),
                        "currency": "KES",
                        "type":     "stocks",
                        "exchange": h["exchange"],
                    }
                    for h in port["holdings"]
                },
                # Other assets grouped by class
                **{
                    cls: {"value": v, "cost": v, "gain": 0,
                          "gain_pct": 0, "currency": "KES", "type": "savings"}
                    for cls, v in sav_by_class.items()
                },
            },
        },
        "savings":    sav_rows,
        "lots":       lots,
        "fx_rates":   fx_rates,
        "pending_anomalies": (anomalies_pending[0]["n"] if anomalies_pending else 0),
    })


@bp.route("/api/tickers")
@approved_required
def get_tickers():
    q        = request.args.get("q", "").strip().upper()
    exchange = request.args.get("exchange", "").strip().upper()
    limit    = int(request.args.get("limit", 50))

    conn = get_db()
    try:
        conditions = ["active = " + ("TRUE" if is_pg() else "1")]
        params     = []
        if q:
            conditions.append(f"(UPPER(symbol) LIKE {p()} OR UPPER(name) LIKE {p()})")
            params += [f"%{q}%", f"%{q}%"]
        if exchange:
            conditions.append(f"exchange = {p()}")
            params.append(exchange)

        where = " AND ".join(conditions)
        sql   = f"""
            SELECT id, symbol, name, exchange, type, currency, sector
            FROM tickers
            WHERE {where}
            ORDER BY
                CASE WHEN UPPER(symbol) = {p()} THEN 0
                     WHEN UPPER(symbol) LIKE {p()} THEN 1
                     ELSE 2 END,
                symbol
            LIMIT {p()}
        """
        params += [q or "", f"{q}%" if q else "", limit]
        rows = _fetchall(conn, sql, params)
    finally:
        conn.close()
    return jsonify({"tickers": rows})


# ── Savings ───────────────────────────────────────────────────────────────────


@bp.route("/api/savings")
@approved_required
def get_savings():
    conn = get_db()
    try:
        rows     = _fetchall(conn,
            f"SELECT * FROM savings WHERE user_id={p()} ORDER BY date DESC",
            (uid(),))
        fx_rates = _get_fx_rates(conn)
    finally:
        conn.close()

    totals_kes, net_kes = {}, 0.0
    for e in rows:
        cur     = e.get("currency") or "KES"
        sign    = 1 if e["type"] in ("deposit","interest") else -1
        amt_kes = _to_kes(float(e["amount"]), cur, fx_rates) * sign

        e["currency"]    = cur
        e["amount_kes"]  = round(amt_kes, 2)
        e["fx_rate_kes"] = fx_rates.get(cur, 1.0)
        e["is_foreign"]  = (cur != "KES")

        totals_kes[e["asset_class"]] = (
            totals_kes.get(e["asset_class"], 0.0) + amt_kes)
        net_kes += amt_kes

    return jsonify({
        "entries":         rows,
        "totals_by_class": {k: round(v, 2) for k, v in totals_kes.items()},
        "net_total":       round(net_kes, 2),
        "fx_rates":        fx_rates,
    })

@bp.route("/api/savings", methods=["POST"])
@approved_required
def add_saving():
    d = request.json or {}
    try:
        _require(d, "label", "asset_class", "amount", "type", "date")
        if d["type"] not in ("deposit", "withdrawal", "interest"):
            raise ValueError("type must be deposit, interest or withdrawal")
    except (ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    conn = get_db()
    try:
        _exec(conn,
            f"""INSERT INTO savings
                (user_id,label,asset_class,amount,type,currency,note,date)
                VALUES ({p()},{p()},{p()},{p()},{p()},{p()},{p()},{p()})""",
            (uid(), d["label"], d["asset_class"], float(d["amount"]),
             d["type"], d.get("currency", "KES"), d.get("note", ""), d["date"]))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})

@bp.route("/api/savings/<int:sid>", methods=["PUT"])
@approved_required
def edit_saving(sid):
    d = request.json or {}
    try:
        _require(d, "label", "asset_class", "amount", "type", "date")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    conn = get_db()
    try:
        _exec(conn,
            f"""UPDATE savings
                SET label={p()},asset_class={p()},amount={p()},type={p()},note={p()},date={p()}
                WHERE id={p()} AND user_id={p()}""",
            (d["label"], d["asset_class"], float(d["amount"]), d["type"],
             d.get("note", ""), d["date"], sid, uid()))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})

@bp.route("/api/savings/<int:sid>", methods=["DELETE"])
@approved_required
def delete_saving(sid):
    conn = get_db()
    try:
        _exec(conn,
            f"DELETE FROM savings WHERE id={p()} AND user_id={p()}",
            (sid, uid()))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})


# ── Portfolio helper ──────────────────────────────────────────────────────────

def _build_portfolio(conn):
    u        = uid()
    fx_rates = _get_fx_rates(conn)

    lots     = _fetchall(conn,
        f"SELECT * FROM stock_lots WHERE user_id={ph()} AND shares > 0 ORDER BY date DESC",
        (u,))
    all_lots_raw = _fetchall(conn,
        f"SELECT * FROM stock_lots WHERE user_id={ph()} ORDER BY date DESC",
        (u,))
    # Enrich each lot with cost in original currency AND in KES
    all_lots = []
    for lot in all_lots_raw:
        cur      = lot.get("currency") or EXCUR.get(lot.get("exchange","NSE"), "KES")
        lot_cost = float(lot["shares"]) * float(lot["purchase_price"])
        lot["currency"]          = cur
        lot["lot_cost_local"]    = round(lot_cost, 2)
        lot["lot_cost_kes"]      = round(_to_kes(lot_cost, cur, fx_rates), 2)
        lot["fx_rate_kes"]       = fx_rates.get(cur, 1.0)
        all_lots.append(lot)
    # ONE query fetches all price history — split into latest + sparklines in Python
    user_tickers = list({(l["ticker"], l.get("exchange","NSE")) for l in lots})
    if user_tickers and is_pg():
        ticker_pairs = ",".join(f"('{t}','{e}')" for t,e in user_tickers)
        all_prices = _fetchall(conn, f"""
            SELECT ticker, exchange, price, currency, date
            FROM global_prices
            WHERE (ticker, exchange) IN ({ticker_pairs})
            ORDER BY ticker, exchange, date ASC
        """)
    elif user_tickers:
        in_clause = ",".join(f"'{t}|{e}'" for t,e in user_tickers)
        all_prices = _fetchall(conn, f"""
            SELECT ticker, exchange, price, currency, date
            FROM global_prices
            WHERE (ticker || '|' || exchange) IN ({in_clause})
            ORDER BY ticker, exchange, date ASC
        """)
    else:
        all_prices = []
    sales = _fetchall(conn,
        f"SELECT * FROM stock_sales WHERE user_id={ph()} ORDER BY date DESC",
        (u,))

    # Split one query result into latest price + history (no second DB call)
    latest_price, price_hist = {}, {}
    for pr in all_prices:
        k = (pr["ticker"], pr.get("exchange", "NSE"))
        # Last entry for this ticker = latest (rows are ASC by date)
        latest_price[k] = pr
        price_hist.setdefault(k, []).append({
            "date": str(pr["date"]), "price": float(pr["price"])
        })
    price_history_rows = []  # used below — already built into price_hist

    # price_hist already built above in single-pass loop

    # Aggregate lots per ticker
    tickers_map = {}
    for lot in lots:
        exch = lot.get("exchange", "NSE")
        cur  = lot.get("currency") or EXCUR.get(exch, "KES")
        k    = (lot["ticker"], exch)
        if k not in tickers_map:
            tickers_map[k] = {
                "ticker": lot["ticker"], "exchange": exch, "currency": cur,
                "lots": [], "total_shares": 0, "total_cost": 0, "total_cost_kes": 0,
            }
        lot_cost     = float(lot["shares"]) * float(lot["purchase_price"])
        lot_cost_kes = _to_kes(lot_cost, cur, fx_rates)
        tickers_map[k]["lots"].append(lot)
        tickers_map[k]["total_shares"]   += float(lot["shares"])
        tickers_map[k]["total_cost"]     += lot_cost
        tickers_map[k]["total_cost_kes"] += lot_cost_kes

    # Realized gains per ticker
    realized = {}
    for s in sales:
        k    = (s["ticker"], s.get("exchange", "NSE"))
        cur  = s.get("currency") or EXCUR.get(s.get("exchange", "NSE"), "KES")
        gain = (float(s["sale_price"]) - float(s["purchase_price"])) * float(s["shares"])
        gain_kes = _to_kes(gain, cur, fx_rates)
        realized.setdefault(k, {
            "realized_gain": 0, "realized_gain_kes": 0,
            "sold_shares": 0, "sales": []
        })
        realized[k]["realized_gain"]     += gain
        realized[k]["realized_gain_kes"] += gain_kes
        realized[k]["sold_shares"]       += float(s["shares"])
        realized[k]["sales"].append(s)

    holdings            = []
    total_cost_kes      = 0
    total_market_kes    = 0

    for k, h in tickers_map.items():
        cur = h["currency"]
        h["avg_cost"] = round(
            h["total_cost"] / h["total_shares"], 4) if h["total_shares"] else 0

        lp = latest_price.get(k)
        if lp:
            mkt_local    = h["total_shares"] * float(lp["price"])
            mkt_kes      = _to_kes(mkt_local, cur, fx_rates)
            gain_local   = mkt_local - h["total_cost"]
            gain_kes     = mkt_kes - h["total_cost_kes"]
            pct_local    = round(gain_local / h["total_cost"] * 100, 2) if h["total_cost"] else 0
            fx_rate_now  = fx_rates.get(cur, 1.0)
            h.update({
                "market_price":     float(lp["price"]),
                "market_value":     round(mkt_local, 2),
                "market_value_kes": round(mkt_kes, 2),
                "gain_loss":        round(gain_local, 2),
                "gain_loss_kes":    round(gain_kes, 2),
                "pct_return":       pct_local,
                "fx_rate_kes":      fx_rate_now,
                "price_date":       str(lp["date"]),
            })
            total_market_kes += mkt_kes
        else:
            # No market price available — use cost basis as fallback
            # This prevents NaN in allocation % and keeps these in total portfolio
            cost_kes = h["total_cost_kes"]
            h.update({
                "market_price":     None,
                "market_value":     h["total_cost"],   # local currency cost
                "market_value_kes": cost_kes,          # KES cost as proxy
                "gain_loss":        0.0,
                "gain_loss_kes":    0.0,
                "pct_return":       0.0,
                "fx_rate_kes":      fx_rates.get(cur, 1.0),
                "price_date":       None,
                "price_source":     "cost_basis",      # signals no real price
            })
            total_market_kes += cost_kes              # include in portfolio total

        h["realized"]      = realized.get(k, {
            "realized_gain": 0, "realized_gain_kes": 0,
            "sold_shares": 0, "sales": []
        })
        h["price_history"] = price_hist.get(k, [])[-30:]
        total_cost_kes    += h["total_cost_kes"]
        holdings.append(h)

    total_gain_kes     = total_market_kes - total_cost_kes
    total_realized_kes = sum(
        r.get("realized_gain_kes", 0) for r in realized.values())

    return {
        "holdings":           holdings,
        "lots":               all_lots,
        "active_lots":        lots,
        "sales":              sales,
        "price_history":      _fetchall(conn,
            "SELECT * FROM global_prices ORDER BY date DESC"),
        "fx_rates":           fx_rates,
        "total_cost":         round(total_cost_kes, 2),    # in KES
        "total_market":       round(total_market_kes, 2),  # in KES
        "total_gain":         round(total_gain_kes, 2),    # in KES
        "total_realized":     round(total_realized_kes, 2),
        "portfolio_pct":      round(
            total_gain_kes / total_cost_kes * 100, 2) if total_cost_kes else 0,
    }


# ── Stocks ────────────────────────────────────────────────────────────────────

@bp.route("/api/stocks")
@approved_required
def get_stocks():
    conn = get_db()
    try:
        return jsonify(_build_portfolio(conn))
    finally:
        conn.close()

@bp.route("/api/stocks/lots")
@approved_required
def get_lots_for_sale():
    """Return active lots (shares > 0) for the sell-from-lot dropdown."""
    conn = get_db()
    try:
        rows = _fetchall(conn, f"""
            SELECT id, ticker, exchange, shares, original_shares,
                   purchase_price, currency, date, broker,
                   shares * purchase_price as lot_value
            FROM stock_lots
            WHERE shares > 0 AND user_id={p()}
            ORDER BY ticker, date
        """, (uid(),))
        fx = _get_fx_rates(conn)   # reuse same connection
    finally:
        conn.close()
    for r in rows:
        r["shares"]          = float(r["shares"])
        r["original_shares"] = float(r["original_shares"] or r["shares"])
        r["purchase_price"]  = float(r["purchase_price"])
        r["lot_value"]       = float(r["lot_value"])
        r["date"]            = str(r["date"])
        cur = r.get("currency") or EXCUR.get(r.get("exchange","NSE"), "KES")
        r["currency"]        = cur
        r["lot_cost_local"]  = round(r["lot_value"], 2)
        r["lot_cost_kes"]    = round(_to_kes(r["lot_value"], cur, fx), 2)
        r["fx_rate_kes"]     = fx.get(cur, 1.0)
    return jsonify({"lots": rows})

@bp.route("/api/stocks/lot", methods=["POST"])
@approved_required
def add_lot():
    d = request.json or {}
    try:
        _require(d, "ticker", "exchange", "shares", "purchase_price", "date")
        shares = float(d["shares"])
        price  = float(d["purchase_price"])
        if shares <= 0 or price <= 0:
            raise ValueError("shares and purchase_price must be positive")
    except (ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    conn = get_db()
    try:
        _exec(conn, f"""
            INSERT INTO stock_lots
                (user_id,ticker,exchange,shares,original_shares,
                 purchase_price,currency,date,broker,note)
            VALUES ({p()},{p()},{p()},{p()},{p()},{p()},{p()},{p()},{p()},{p()})
        """, (uid(), d["ticker"].upper().strip(), d["exchange"],
              shares, shares, price,
              d.get("currency", EXCUR.get(d.get("exchange", "NSE"), "KES")),
              d["date"], d.get("broker", ""), d.get("note", "")))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})

@bp.route("/api/stocks/lot/<int:lid>", methods=["PUT"])
@approved_required
def edit_lot(lid):
    d = request.json or {}
    try:
        _require(d, "ticker", "exchange", "shares", "purchase_price", "date")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    conn = get_db()
    try:
        _exec(conn, f"""
            UPDATE stock_lots
            SET ticker={p()},exchange={p()},shares={p()},purchase_price={p()},
                date={p()},broker={p()},note={p()}
            WHERE id={p()} AND user_id={p()}
        """, (d["ticker"].upper().strip(), d["exchange"],
              float(d["shares"]), float(d["purchase_price"]),
              d["date"], d.get("broker", ""), d.get("note", ""),
              lid, uid()))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})

@bp.route("/api/stocks/lot/<int:lid>", methods=["DELETE"])
@approved_required
def delete_lot(lid):
    conn = get_db()
    try:
        _exec(conn,
            f"DELETE FROM stock_lots WHERE id={p()} AND user_id={p()}",
            (lid, uid()))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})

@bp.route("/api/stocks/price", methods=["POST"])
@approved_required
def add_price():
    d = request.json or {}
    try:
        _require(d, "ticker", "exchange", "price", "date")
        if float(d["price"]) <= 0:
            raise ValueError("price must be positive")
    except (ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    conn = get_db()
    try:
        _exec(conn,
            f"""INSERT INTO stock_prices
                (user_id,ticker,exchange,price,currency,date,note)
                VALUES ({p()},{p()},{p()},{p()},{p()},{p()},{p()})""",
            (uid(), d["ticker"].upper().strip(), d["exchange"],
             float(d["price"]),
             d.get("currency", EXCUR.get(d.get("exchange", "NSE"), "KES")),
             d["date"], d.get("note", "")))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})

@bp.route("/api/stocks/price/<int:pid>", methods=["DELETE"])
@approved_required
def delete_price(pid):
    conn = get_db()
    try:
        _exec(conn,
            f"DELETE FROM stock_prices WHERE id={p()} AND user_id={p()}",
            (pid, uid()))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})


# ── Sales — lot-based ─────────────────────────────────────────────────────────

@bp.route("/api/stocks/sale", methods=["POST"])
@approved_required
def record_sale():
    d = request.json or {}
    try:
        _require(d, "lot_id", "shares_to_sell", "sale_price", "date")
        shares_to_sell = float(d["shares_to_sell"])
        sale_price     = float(d["sale_price"])
        if shares_to_sell <= 0:
            raise ValueError("shares_to_sell must be positive")
        if sale_price <= 0:
            raise ValueError("sale_price must be positive")
    except (ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400

    conn = get_db()
    try:
        lot = _fetchone(conn,
            f"SELECT * FROM stock_lots WHERE id={p()} AND user_id={p()}",
            (d["lot_id"], uid()))
        if not lot:
            return jsonify({"error": "Lot not found"}), 404

        available = float(lot["shares"])
        if shares_to_sell > available:
            return jsonify({
                "error": f"Cannot sell {shares_to_sell} — only {available} available"
            }), 400

        _exec(conn, f"""
            INSERT INTO stock_sales
                (user_id,lot_id,ticker,exchange,shares,purchase_price,
                 sale_price,currency,date,broker,note)
            VALUES ({p()},{p()},{p()},{p()},{p()},{p()},{p()},{p()},{p()},{p()},{p()})
        """, (uid(), lot["id"], lot["ticker"], lot["exchange"],
              shares_to_sell, float(lot["purchase_price"]),
              sale_price,
              lot.get("currency") or EXCUR.get(lot.get("exchange", "NSE"), "KES"),
              d["date"],
              d.get("broker", lot.get("broker", "")),
              d.get("note", "")))

        remaining = available - shares_to_sell
        _exec(conn,
            f"UPDATE stock_lots SET shares={p()} WHERE id={p()}",
            (max(0, remaining), lot["id"]))
        conn.commit()

        gain = round(
            (sale_price - float(lot["purchase_price"])) * shares_to_sell, 2)
        return jsonify({
            "ok":        True,
            "gain_loss": gain,
            "remaining": round(remaining, 6),
            "ticker":    lot["ticker"],
            "exchange":  lot["exchange"],
        })
    finally:
        conn.close()

@bp.route("/api/stocks/sale/<int:sid>", methods=["DELETE"])
@approved_required
def delete_sale(sid):
    conn = get_db()
    try:
        sale = _fetchone(conn,
            f"SELECT * FROM stock_sales WHERE id={p()} AND user_id={p()}",
            (sid, uid()))
        if not sale:
            return jsonify({"error": "Sale not found"}), 404
        if sale.get("lot_id"):
            _exec(conn,
                f"UPDATE stock_lots SET shares = shares + {p()} WHERE id={p()}",
                (float(sale["shares"]), sale["lot_id"]))
        _exec(conn, f"DELETE FROM stock_sales WHERE id={p()}", (sid,))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})


# ── Smart price fetch — only fetch tickers not yet updated today ──────────────

@bp.route("/api/stocks/fetch-prices", methods=["POST"])
@approved_required
def fetch_prices_ai():
    """3-Agent price pipeline: Fetch → Anomaly Check → Review."""
    d       = request.json or {}
    api_key = d.get("api_key") or get_gemini_key(uid())
    if d.get("api_key"):
        saved_to_sm = save_gemini_key_to_secret(d["api_key"])
        if not saved_to_sm:
            cfg_set(uid(), "gemini_api_key", d["api_key"])
    if not api_key:
        return jsonify({"error": "No Gemini API key — add it in Settings"}), 400

    today = _today()
    force = d.get("force", False)
    conn  = get_db()
    try:
        all_positions = _fetchall(conn, """
            SELECT DISTINCT ticker, COALESCE(exchange,'NSE') as exchange
            FROM stock_lots WHERE shares > 0
        """)
        if not all_positions:
            return jsonify({"error": "No active positions in any portfolio"}), 400

        if not force:
            existing = {(e["ticker"], e["exchange"])
                        for e in _fetchall(conn, f"""
                SELECT DISTINCT ticker, exchange FROM global_prices WHERE date={p()}
            """, (today,))}
            skipped       = [t for t in all_positions if (t["ticker"],t["exchange"]) in existing]
            all_positions = [t for t in all_positions if (t["ticker"],t["exchange"]) not in existing]
        else:
            skipped = []

        if not all_positions:
            return jsonify({
                "ok": True, "agents": None,
                "skipped": [t["ticker"] for t in skipped],
                "message": f"All {len(skipped)} tickers already updated today.",
                "date": today,
            })

        # Enrich positions with currency info
        enriched = []
        for t in all_positions:
            row = _fetchone(conn, f"""
                SELECT COALESCE(exchange,'NSE') as exchange, currency
                FROM stock_lots WHERE UPPER(ticker)={p()} LIMIT 1
            """, (t["ticker"],))
            enriched.append({
                "ticker":   t["ticker"],
                "exchange": t["exchange"],
                "currency": (row.get("currency") or EXCUR.get(t["exchange"],"KES")) if row else "KES",
            })

        # 3-agent pipeline — keeps conn open internally
        result = _price_agents.run_price_pipeline(api_key, enriched, conn)

    finally:
        conn.close()

    _save_snapshot()
    return jsonify({
        "ok":            True,
        "date":          today,
        "written":       result["written"],
        "skipped":       [t["ticker"] for t in skipped],
        "agents": {
            "agent1": result["agent1"],
            "agent2": result["agent2"],
            "agent3": result["agent3"],
        },
        "anomalies":     result.get("anomalies", []),
        "manual_review": result.get("manual_review", []),
        "errors":        result.get("errors", []),
        "message": (
            f"Agent pipeline: {result['written']} prices written"
            + (f", {result['agent2'].get('flagged',0)} flagged"
               if result['agent2'].get('flagged') else "")
            + (f", {result['agent3'].get('manual_review',0)} need manual review"
               if result['agent3'].get('manual_review') else "")
            + (f", {len(skipped)} already up-to-date" if skipped else "")
        ),
    })

@bp.route("/api/fx-rates/fetch", methods=["POST"])
@approved_required
def fetch_fx_rates_endpoint():
    """Fetch and store latest FX rates to KES via Gemini AI."""
    api_key = get_gemini_key(uid())
    if not api_key:
        return jsonify({"error": "No Gemini API key — add it in Settings"}), 400
    # Run 3-agent FX pipeline
    conn = get_db()
    try:
        result = _price_agents.run_fx_pipeline(api_key, conn)
    finally:
        conn.close()

    return jsonify({
        "ok":            True,
        "date":          result["date"],
        "rates":         result["agent1"].get("rates", {}),
        "written":       result["written"],
        "agents":        {
            "agent1": result["agent1"],
            "agent2": result["agent2"],
            "agent3": result["agent3"],
        },
        "anomalies":     result.get("anomalies", []),
        "manual_review": result.get("manual_review", []),
        "errors":        result.get("errors", []),
    })

@bp.route("/api/fx-rates")
@approved_required
def get_fx_rates_endpoint():
    """Return stored FX rates."""
    conn = get_db()
    try:
        rates = _get_fx_rates(conn)
        try:
            cur = conn.cursor()
            cur.execute("SELECT MAX(updated_date) as d FROM global_fx")
            row = cur.fetchone()
            fx_date = (row["d"] if is_pg() else row[0]) if row else "—"
        except Exception:
            fx_date = "—"
    finally:
        conn.close()
    return jsonify({"rates": rates, "as_of": str(fx_date) if fx_date else "—"})


@bp.route("/api/prices/anomalies")
@approved_required
def get_anomalies():
    """Return recent price anomalies for review."""
    conn = get_db()
    try:
        from datetime import date as _date
        rows = _fetchall(conn, f"""
            SELECT * FROM price_anomalies
            ORDER BY created_at DESC LIMIT 100
        """)
    finally:
        conn.close()
    # Convert timestamps
    for r in rows:
        for k in ("created_at","resolved_at"):
            if r.get(k):
                r[k] = str(r[k])[:19]
    pending  = [r for r in rows if r["status"] == "manual_review"]
    resolved = [r for r in rows if r["status"] != "manual_review"]
    return jsonify({
        "pending":  pending,
        "resolved": resolved,
        "total":    len(rows),
    })

@bp.route("/api/prices/anomalies/<int:aid>/resolve", methods=["POST"])
@approved_required
def resolve_anomaly(aid):
    """Manually resolve an anomaly — accept, correct, or dismiss."""
    d = request.json or {}
    action = d.get("action")  # "accept", "correct", "dismiss"
    if action not in ("accept","correct","dismiss"):
        return jsonify({"error":"action must be accept|correct|dismiss"}), 400

    conn = get_db()
    try:
        row = _fetchone(conn, f"SELECT * FROM price_anomalies WHERE id={p()}", (aid,))
        if not row:
            return jsonify({"error":"Not found"}), 404

        now = datetime.now().isoformat()

        if action == "dismiss":
            _exec(conn, f"""
                UPDATE price_anomalies
                SET status='dismissed', review_note={p()}, resolved_at={p()}
                WHERE id={p()}
            """, (d.get("note","Dismissed by user"), now, aid))

        elif action == "accept":
            price = float(row["fetched_value"])
            today = _today()
            if row["type"] == "fx":
                if is_pg():
                    _exec(conn, """INSERT INTO global_fx (currency,kes_rate,updated_date)
                        VALUES (%s,%s,%s) ON CONFLICT(currency) DO UPDATE SET
                        kes_rate=EXCLUDED.kes_rate,updated_date=EXCLUDED.updated_date""",
                        (row["ticker"], price, today))
                else:
                    _exec(conn, "INSERT OR REPLACE INTO global_fx (currency,kes_rate,updated_date) VALUES (?,?,?)",
                        (row["ticker"], price, today))
            else:
                exch = row.get("exchange","NSE")
                cur  = row.get("currency","KES")
                if is_pg():
                    _exec(conn, """INSERT INTO global_prices (ticker,exchange,price,currency,date,note)
                        VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(ticker,exchange,date) DO UPDATE SET
                        price=EXCLUDED.price,note=EXCLUDED.note""",
                        (row["ticker"],exch,price,cur,today,"Manually accepted anomaly"))
                else:
                    _exec(conn, "INSERT OR REPLACE INTO global_prices (ticker,exchange,price,currency,date,note) VALUES (?,?,?,?,?,?)",
                        (row["ticker"],exch,price,cur,today,"Manually accepted anomaly"))
            _exec(conn, f"UPDATE price_anomalies SET status='accepted',resolved_at={p()} WHERE id={p()}",
                  (now, aid))

        elif action == "correct":
            corrected = d.get("price")
            if not corrected:
                return jsonify({"error":"Provide corrected price"}), 400
            corrected = float(corrected)
            today = _today()
            if row["type"] == "fx":
                if is_pg():
                    _exec(conn, """INSERT INTO global_fx (currency,kes_rate,updated_date)
                        VALUES (%s,%s,%s) ON CONFLICT(currency) DO UPDATE SET
                        kes_rate=EXCLUDED.kes_rate,updated_date=EXCLUDED.updated_date""",
                        (row["ticker"], corrected, today))
                else:
                    _exec(conn, "INSERT OR REPLACE INTO global_fx (currency,kes_rate,updated_date) VALUES (?,?,?)",
                        (row["ticker"], corrected, today))
            else:
                exch = row.get("exchange","NSE")
                cur  = row.get("currency","KES")
                if is_pg():
                    _exec(conn, """INSERT INTO global_prices (ticker,exchange,price,currency,date,note)
                        VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(ticker,exchange,date) DO UPDATE SET
                        price=EXCLUDED.price,note=EXCLUDED.note""",
                        (row["ticker"],exch,corrected,cur,today,"Manually corrected anomaly"))
                else:
                    _exec(conn, "INSERT OR REPLACE INTO global_prices (ticker,exchange,price,currency,date,note) VALUES (?,?,?,?,?,?)",
                        (row["ticker"],exch,corrected,cur,today,"Manually corrected anomaly"))
            _exec(conn, f"""UPDATE price_anomalies
                SET status='corrected',reviewed_value={p()},
                    review_note={p()},resolved_at={p()}
                WHERE id={p()}""",
                (corrected, d.get("note","Manual correction"), now, aid))

        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok":True})


# ── Portfolio snapshots ───────────────────────────────────────────────────────

def _save_snapshot():
    conn = get_db()
    try:
        port     = _build_portfolio(conn)
        fx_rates = _get_fx_rates(conn)
        rows     = _fetchall(conn,
            f"SELECT * FROM savings WHERE user_id={ph()}", (uid(),))
        # Convert savings to KES using live FX rates
        other = sum(
            _to_kes(float(r["amount"]), r.get("currency","KES"), fx_rates)
            if r["type"] == "deposit"
            else -_to_kes(float(r["amount"]), r.get("currency","KES"), fx_rates)
            for r in rows)
        stock = port["total_market"]  # market value in KES (uses live prices)
        total = stock + other
        today = _today()
        _exec(conn, upsert_snapshot_sql(),
              (uid(), today,
               round(total, 2), round(stock, 2), round(other, 2),
               round(port["total_cost"], 2), round(port["total_gain"], 2)))
        conn.commit()
    finally:
        conn.close()

@bp.route("/api/portfolio/snapshot", methods=["POST"])
@approved_required
def manual_snapshot():
    try:
        _save_snapshot()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route("/api/portfolio/snapshots")
@approved_required
def get_snapshots():
    conn = get_db()
    try:
        rows = _fetchall(conn,
            f"SELECT * FROM portfolio_snapshots WHERE user_id={ph()} ORDER BY date ASC",
            (uid(),))
    finally:
        conn.close()
    for r in rows:
        r["date"] = str(r["date"])
    return jsonify({"snapshots": rows})


# ── Investment overview ───────────────────────────────────────────────────────

@bp.route("/api/investments/overview")
@approved_required
def investment_overview():
    conn = get_db()
    try:
        port     = _build_portfolio(conn)
        sav_rows = _fetchall(conn,
            f"SELECT * FROM savings WHERE user_id={ph()}", (uid(),))
        fx_rates = _get_fx_rates(conn)
    finally:
        conn.close()

    sav_by_class, broker_totals = {}, {}
    for r in sav_rows:
        cur  = r.get("currency") or "KES"
        sign = 1 if r["type"] in ("deposit","interest") else -1
        # Always convert to KES so totals are comparable cross-currency
        v_kes = _to_kes(float(r["amount"]), cur, fx_rates) * sign
        sav_by_class[r["asset_class"]] = sav_by_class.get(r["asset_class"], 0) + v_kes

    for lot in port["lots"]:
        b    = lot.get("broker", "Unknown") or "Unknown"
        cur  = lot.get("currency") or EXCUR.get(lot.get("exchange","NSE"), "KES")
        cost = float(lot["shares"]) * float(lot["purchase_price"])
        # Convert to KES for a meaningful cross-currency total
        cost_kes = _to_kes(cost, cur, port.get("fx_rates", {}))
        broker_totals[b] = broker_totals.get(b, 0) + cost_kes

    stock_by_exch = {}
    for h in port["holdings"]:
        cls = f"Stocks ({h['exchange']})"
        cur = h.get("currency") or EXCUR.get(h["exchange"], "—")
        if cls not in stock_by_exch:
            stock_by_exch[cls] = {
                "value": 0, "cost": 0, "currency": cur,
                "type": "stocks", "exchange": h["exchange"]
            }
        val = h.get("market_value_kes") if h.get("market_value_kes") is not None \
              else h["total_cost_kes"]
        stock_by_exch[cls]["value"] += val
        stock_by_exch[cls]["cost"]  += h["total_cost_kes"]

    asset_summary = {
        **{cls: d for cls, d in stock_by_exch.items()},
        **{cls: {"value": v, "cost": v, "currency": "KES", "type": "savings"}
           for cls, v in sav_by_class.items()}
    }
    total_all = sum(v["value"] for v in asset_summary.values())
    for d in asset_summary.values():
        gain = d["value"] - d["cost"]
        d.update({
            "gain":      round(gain, 2),
            "gain_pct":  round(gain / d["cost"] * 100, 2) if d["cost"] else 0,
            "value":     round(d["value"], 2),
            "cost":      round(d["cost"], 2),
            "pct_total": round(d["value"] / total_all * 100, 1) if total_all else 0,
        })

    return jsonify({
        "asset_summary":   asset_summary,
        "total_value":     round(total_all, 2),
        "total_cost":      round(sum(v["cost"] for v in asset_summary.values()), 2),
        "total_gain":      round(sum(v["gain"] for v in asset_summary.values()), 2),
        "total_realized":  port["total_realized"],
        "broker_totals":   {k: round(v, 2) for k, v in
                            sorted(broker_totals.items(), key=lambda x: -x[1])},
        "stock_summary": {
            "total_cost":   port["total_cost"],
            "total_market": port["total_market"],
            "total_gain":   port["total_gain"],
            "pct":          port["portfolio_pct"],
        },
        "savings_net":     round(sum(sav_by_class.values()), 2),
        "fx_rates":        fx_rates,
        "currency_note":   any(
            v.get("currency") not in ("KES", "—")
            for v in asset_summary.values()),
    })


# ── Portfolio review ──────────────────────────────────────────────────────────

@bp.route("/api/portfolio/review", methods=["POST"])
@approved_required
def gen_review():
    """Start the 7-agent agentic review pipeline. Returns job_id immediately."""
    api_key = get_gemini_key(uid())
    if not api_key:
        return jsonify({"error": "No Gemini API key — add it in Settings"}), 400
    conn = get_db()
    try:
        port     = _build_portfolio(conn)
        fx_rates = _get_fx_rates(conn)
        # Rich savings: individual entries with labels, amounts, types
        sav_rows = _fetchall(conn, f"""
            SELECT label, asset_class, type, amount, currency, date, note
            FROM savings WHERE user_id={ph()} ORDER BY asset_class, date
        """, (uid(),))
        # Class totals for context string
        sav_totals = {}
        sav_entries = []
        for r in sav_rows:
            cur  = r.get("currency") or "KES"
            sign = 1 if r["type"] in ("deposit","interest") else -1
            v_kes = _to_kes(float(r["amount"]), cur, fx_rates) * sign
            cls = r["asset_class"]
            sav_totals[cls] = sav_totals.get(cls, 0) + v_kes
            sav_entries.append({
                "label":       r["label"],
                "asset_class": cls,
                "type":        r["type"],
                "amount":      float(r["amount"]),
                "currency":    cur,
                "amount_kes":  round(v_kes, 2),
                "date":        str(r["date"]) if r.get("date") else "",
                "note":        r.get("note","") or "",
            })
        sav = {
            "totals":  sav_totals,      # {asset_class: total_kes}
            "entries": sav_entries,     # full detail for health agent
        }
    finally:
        conn.close()
    job_id = _agents.start_pipeline(uid(), api_key, port, sav)
    return jsonify({"ok": True, "job_id": job_id, "agents": _agents.AGENTS})

@bp.route("/api/portfolio/review")
@approved_required
def get_review():
    raw = cfg_get(uid(), "last_review")
    if not raw:
        return jsonify({"review": None})
    try:
        return jsonify({"review": json.loads(raw)})
    except Exception:
        return jsonify({"review": None})

@bp.route("/api/portfolio/review/poll/<job_id>")
@approved_required
def poll_review(job_id):
    """Poll live agent progress for an agentic review job."""
    job = _agents.get_job(job_id, uid())
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)

@bp.route("/api/portfolio/review/history")
@approved_required
def review_history():
    """List recent review jobs for this user."""
    jobs = _agents.list_jobs(uid(), limit=10)
    return jsonify({"jobs": jobs})


# ── Config / settings ─────────────────────────────────────────────────────────

@bp.route("/api/export/prices.csv")
@approved_required
def export_prices():
    conn = get_db()
    try:
        rows = _fetchall(conn,
            "SELECT * FROM global_prices ORDER BY ticker, date DESC")
    finally:
        conn.close()
    import csv, io
    out = io.StringIO()
    w   = csv.writer(out)
    w.writerow(["Date","Ticker","Exchange","Price","Currency","Note"])
    for r in rows:
        w.writerow([r["date"],r["ticker"],r["exchange"],
                    r["price"],r.get("currency","KES"),r.get("note","")])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition":"attachment;filename=price_history.csv"})

@bp.route("/api/export/snapshots.csv")
@approved_required
def export_snapshots():
    conn = get_db()
    try:
        rows = _fetchall(conn,
            f"SELECT * FROM portfolio_snapshots WHERE user_id={ph()} ORDER BY date",
            (uid(),))
    finally:
        conn.close()
    import csv, io
    out = io.StringIO()
    w   = csv.writer(out)
    w.writerow(["Date","Total Value KES","Stock Value KES","Other Value KES",
                "Total Cost KES","Total Gain KES"])
    for r in rows:
        w.writerow([r["date"],r["total_value"],r["stock_value"],r["other_value"],
                    r["total_cost"],r["total_gain"]])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition":"attachment;filename=snapshots.csv"})

@bp.route("/api/export/anomalies.csv")
@approved_required
def export_anomalies():
    conn = get_db()
    try:
        rows = _fetchall(conn,
            "SELECT * FROM price_anomalies ORDER BY created_at DESC")
    finally:
        conn.close()
    import csv, io
    out = io.StringIO()
    w   = csv.writer(out)
    w.writerow(["Created","Type","Ticker","Exchange","Fetched","Previous",
                "Pct Change","Status","Reviewed Value","Note"])
    for r in rows:
        w.writerow([str(r.get("created_at",""))[:19],r["type"],r["ticker"],
                    r.get("exchange",""),r["fetched_value"],r.get("previous_value",""),
                    r.get("pct_change",""),r["status"],
                    r.get("reviewed_value",""),r.get("review_note","")])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition":"attachment;filename=price_anomalies.csv"})

@bp.route("/api/config")
@approved_required
def get_config():
    import os
    using_sm = bool(os.environ.get("GEMINI_SECRET_NAME"))
    key      = get_gemini_key(uid()) or ""
    masked   = ("*" * max(0, len(key) - 4) + key[-4:]) if len(key) > 4 else "*" * len(key)
    return jsonify({
        "gemini_key_set":       bool(key),
        "gemini_key_masked":    masked,
        "using_secret_manager": using_sm,
    })

@bp.route("/api/config", methods=["POST"])
@approved_required
def set_config():
    d   = request.json or {}
    key = d.get("gemini_api_key", "").strip()
    if key:
        saved_to_sm = save_gemini_key_to_secret(key)
        if not saved_to_sm:
            cfg_set(uid(), "gemini_api_key", key)
    return jsonify({"ok": True})


# ── CSV exports ───────────────────────────────────────────────────────────────

@bp.route("/api/export/lots.csv")
@approved_required
def export_lots():
    conn = get_db()
    try:
        rows = _fetchall(conn,
            f"SELECT * FROM stock_lots WHERE user_id={p()} ORDER BY ticker,date",
            (uid(),))
    finally:
        conn.close()
    out = io.StringIO()
    w   = csv.writer(out)
    w.writerow(["Date","Ticker","Exchange","Shares","Original Shares",
                "Purchase Price","Currency","Value","Broker","Note"])
    for r in rows:
        w.writerow([r["date"], r["ticker"], r["exchange"], r["shares"],
                    r.get("original_shares", ""), r["purchase_price"],
                    r.get("currency", "KES"),
                    round(float(r["shares"]) * float(r["purchase_price"]), 2),
                    r["broker"], r["note"]])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment;filename=stock_lots.csv"})

@bp.route("/api/export/savings.csv")
@approved_required
def export_savings():
    conn = get_db()
    try:
        rows = _fetchall(conn,
            f"SELECT * FROM savings WHERE user_id={p()} ORDER BY date DESC",
            (uid(),))
    finally:
        conn.close()
    out = io.StringIO()
    w   = csv.writer(out)
    w.writerow(["Date","Label","Asset Class","Type","Amount","Currency","Note"])
    for r in rows:
        w.writerow([r["date"], r["label"], r["asset_class"], r["type"],
                    r["amount"], r.get("currency", "KES"), r["note"]])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment;filename=savings.csv"})

@bp.route("/api/export/sales.csv")
@approved_required
def export_sales():
    conn = get_db()
    try:
        rows = _fetchall(conn,
            f"SELECT * FROM stock_sales WHERE user_id={p()} ORDER BY date DESC",
            (uid(),))
    finally:
        conn.close()
    out = io.StringIO()
    w   = csv.writer(out)
    w.writerow(["Date","Ticker","Exchange","Shares","Buy Price",
                "Sale Price","Gain/Loss","Currency","Broker","Note"])
    for r in rows:
        gain = round(
            (float(r["sale_price"]) - float(r["purchase_price"])) * float(r["shares"]), 2)
        w.writerow([r["date"], r["ticker"], r["exchange"], r["shares"],
                    r["purchase_price"], r["sale_price"], gain,
                    r.get("currency", "KES"), r["broker"], r["note"]])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment;filename=sales.csv"})
