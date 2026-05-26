"""Investment routes — per-user data, lot-based selling, ticker search, currency support."""
import csv, io, json
from datetime import datetime, date
from decimal import Decimal
from flask import Blueprint, request, jsonify, Response
from flask_login import login_required, current_user
from db import get_db, cfg_get, cfg_set, ph, is_pg, upsert_snapshot_sql
from services.gemini import fetch_prices, generate_review
from services.secrets import get_gemini_key, save_gemini_key_to_secret
from routes.auth import approved_required

bp = Blueprint("investments", __name__)

ASSET_CLASSES = ["Cash","SACCO / Chama","Bonds / T-Bills","Pension / NSSF",
                 "Real Estate","Crypto","Unit Trust / MMF","Foreign Currency","Other"]
EXCHANGES     = ["NSE","NYSE","NASDAQ","LSE","JSE","EURONEXT","HKEX","Other"]
EXCUR         = {"NSE":"KES","NYSE":"USD","NASDAQ":"USD","LSE":"GBP",
                 "JSE":"ZAR","EURONEXT":"EUR","HKEX":"HKD","Other":"—"}

def _today():   return datetime.today().strftime("%Y-%m-%d")
def p():        return ph()
def uid():      return current_user.id

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

# ── Tickers API ───────────────────────────────────────────────────────────────

@bp.route("/api/tickers")
@approved_required
def get_tickers():
    q        = request.args.get("q","").strip().upper()
    exchange = request.args.get("exchange","").strip().upper()
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
        rows = _fetchall(conn,
            f"SELECT * FROM savings WHERE user_id={p()} ORDER BY date DESC", (uid(),))
    finally:
        conn.close()
    totals, net = {}, 0
    for e in rows:
        v = float(e["amount"]) if e["type"]=="deposit" else -float(e["amount"])
        totals[e["asset_class"]] = totals.get(e["asset_class"], 0) + v
        net += v
    return jsonify({"entries": rows, "totals_by_class": totals, "net_total": net})

@bp.route("/api/savings", methods=["POST"])
@approved_required
def add_saving():
    d = request.json or {}
    try:
        _require(d, "label","asset_class","amount","type","date")
        if d["type"] not in ("deposit","withdrawal"):
            raise ValueError("type must be deposit or withdrawal")
    except (ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    conn = get_db()
    try:
        _exec(conn,
            f"""INSERT INTO savings
                (user_id,label,asset_class,amount,type,currency,note,date)
                VALUES ({p()},{p()},{p()},{p()},{p()},{p()},{p()},{p()})""",
            (uid(), d["label"], d["asset_class"], float(d["amount"]),
             d["type"], d.get("currency","KES"), d.get("note",""), d["date"]))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})

@bp.route("/api/savings/<int:sid>", methods=["PUT"])
@approved_required
def edit_saving(sid):
    d = request.json or {}
    try:
        _require(d, "label","asset_class","amount","type","date")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    conn = get_db()
    try:
        _exec(conn,
            f"""UPDATE savings
                SET label={p()},asset_class={p()},amount={p()},type={p()},note={p()},date={p()}
                WHERE id={p()} AND user_id={p()}""",
            (d["label"], d["asset_class"], float(d["amount"]), d["type"],
             d.get("note",""), d["date"], sid, uid()))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})

@bp.route("/api/savings/<int:sid>", methods=["DELETE"])
@approved_required
def delete_saving(sid):
    conn = get_db()
    try:
        _exec(conn, f"DELETE FROM savings WHERE id={p()} AND user_id={p()}", (sid, uid()))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})

# ── Portfolio helper ──────────────────────────────────────────────────────────

def _build_portfolio(conn):
    u      = uid()
    lots   = _fetchall(conn,
        f"SELECT * FROM stock_lots WHERE user_id={ph()} AND shares > 0 ORDER BY date DESC", (u,))
    all_lots = _fetchall(conn,
        f"SELECT * FROM stock_lots WHERE user_id={ph()} ORDER BY date DESC", (u,))
    prices = _fetchall(conn,
        f"SELECT * FROM stock_prices WHERE user_id={ph()} ORDER BY date DESC", (u,))
    sales  = _fetchall(conn,
        f"SELECT * FROM stock_sales WHERE user_id={ph()} ORDER BY date DESC", (u,))

    latest_price, price_hist = {}, {}
    for p_ in prices:
        k = (p_["ticker"], p_.get("exchange","NSE"))
        if k not in latest_price:
            latest_price[k] = p_
    for p_ in reversed(prices):
        k = (p_["ticker"], p_.get("exchange","NSE"))
        price_hist.setdefault(k, []).append({
            "date": str(p_["date"]), "price": float(p_["price"])})

    tickers = {}
    for lot in lots:
        exch = lot.get("exchange","NSE")
        k    = (lot["ticker"], exch)
        if k not in tickers:
            tickers[k] = {"ticker": lot["ticker"], "exchange": exch,
                          "currency": lot.get("currency") or EXCUR.get(exch,"—"),
                          "lots": [], "total_shares": 0, "total_cost": 0}
        tickers[k]["lots"].append(lot)
        tickers[k]["total_shares"] += float(lot["shares"])
        tickers[k]["total_cost"]   += float(lot["shares"]) * float(lot["purchase_price"])

    realized = {}
    for s in sales:
        k    = (s["ticker"], s.get("exchange","NSE"))
        gain = (float(s["sale_price"]) - float(s["purchase_price"])) * float(s["shares"])
        realized.setdefault(k, {"realized_gain":0,"sold_shares":0,"sales":[]})
        realized[k]["realized_gain"] += gain
        realized[k]["sold_shares"]   += float(s["shares"])
        realized[k]["sales"].append(s)

    holdings, total_cost, total_mkt = [], 0, 0
    for k, h in tickers.items():
        h["avg_cost"] = round(h["total_cost"]/h["total_shares"],4) if h["total_shares"] else 0
        lp = latest_price.get(k)
        if lp:
            mkt  = h["total_shares"] * float(lp["price"])
            gain = mkt - h["total_cost"]
            pct  = round(gain/h["total_cost"]*100,2) if h["total_cost"] else 0
            h.update({
                "market_price": float(lp["price"]),
                "market_value": round(mkt,2),
                "gain_loss":    round(gain,2),
                "pct_return":   pct,
                "price_date":   str(lp["date"])
            })
            total_mkt += mkt
        else:
            h.update({"market_price":None,"market_value":None,
                      "gain_loss":None,"pct_return":None,"price_date":None})
        h["realized"]      = realized.get(k,{"realized_gain":0,"sold_shares":0,"sales":[]})
        h["price_history"] = price_hist.get(k,[])[-30:]
        total_cost += h["total_cost"]
        holdings.append(h)

    total_realized = sum(r["realized_gain"] for r in realized.values())
    gain = total_mkt - total_cost
    return {
        "holdings":       holdings,
        "lots":           all_lots,
        "active_lots":    lots,
        "sales":          sales,
        "price_history":  _fetchall(conn,
            f"SELECT * FROM stock_prices WHERE user_id={ph()} ORDER BY date DESC", (u,)),
        "total_cost":     round(total_cost,2),
        "total_market":   round(total_mkt,2),
        "total_gain":     round(gain,2),
        "total_realized": round(total_realized,2),
        "portfolio_pct":  round(gain/total_cost*100,2) if total_cost else 0,
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
    finally:
        conn.close()
    for r in rows:
        r["shares"]          = float(r["shares"])
        r["original_shares"] = float(r["original_shares"]) if r["original_shares"] else float(r["shares"])
        r["purchase_price"]  = float(r["purchase_price"])
        r["lot_value"]       = float(r["lot_value"])
        r["date"]            = str(r["date"])
    return jsonify({"lots": rows})

@bp.route("/api/stocks/lot", methods=["POST"])
@approved_required
def add_lot():
    d = request.json or {}
    try:
        _require(d, "ticker","exchange","shares","purchase_price","date")
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
                (user_id,ticker,exchange,shares,original_shares,purchase_price,currency,date,broker,note)
            VALUES ({p()},{p()},{p()},{p()},{p()},{p()},{p()},{p()},{p()},{p()})
        """, (uid(), d["ticker"].upper().strip(), d["exchange"],
              shares, shares,
              price, d.get("currency", EXCUR.get(d.get("exchange","NSE"),"KES")),
              d["date"], d.get("broker",""), d.get("note","")))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})

@bp.route("/api/stocks/lot/<int:lid>", methods=["PUT"])
@approved_required
def edit_lot(lid):
    d = request.json or {}
    try:
        _require(d, "ticker","exchange","shares","purchase_price","date")
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
              d["date"], d.get("broker",""), d.get("note",""), lid, uid()))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})

@bp.route("/api/stocks/lot/<int:lid>", methods=["DELETE"])
@approved_required
def delete_lot(lid):
    conn = get_db()
    try:
        _exec(conn, f"DELETE FROM stock_lots WHERE id={p()} AND user_id={p()}", (lid, uid()))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})

@bp.route("/api/stocks/price", methods=["POST"])
@approved_required
def add_price():
    d = request.json or {}
    try:
        _require(d, "ticker","exchange","price","date")
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
             d.get("currency", EXCUR.get(d.get("exchange","NSE"),"KES")),
             d["date"], d.get("note","")))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})

@bp.route("/api/stocks/price/<int:pid>", methods=["DELETE"])
@approved_required
def delete_price(pid):
    conn = get_db()
    try:
        _exec(conn, f"DELETE FROM stock_prices WHERE id={p()} AND user_id={p()}", (pid, uid()))
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
        _require(d, "lot_id","shares_to_sell","sale_price","date")
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
                "error": f"Cannot sell {shares_to_sell} — only {available} available in this lot"
            }), 400

        _exec(conn, f"""
            INSERT INTO stock_sales
                (user_id,lot_id,ticker,exchange,shares,purchase_price,sale_price,currency,date,broker,note)
            VALUES ({p()},{p()},{p()},{p()},{p()},{p()},{p()},{p()},{p()},{p()},{p()})
        """, (uid(), lot["id"], lot["ticker"], lot["exchange"],
              shares_to_sell, float(lot["purchase_price"]),
              sale_price,
              lot.get("currency") or EXCUR.get(lot.get("exchange","NSE"),"KES"),
              d["date"],
              d.get("broker", lot.get("broker","")),
              d.get("note","")))

        remaining = available - shares_to_sell
        if remaining <= 0.000001:
            _exec(conn, f"UPDATE stock_lots SET shares=0 WHERE id={p()}", (lot["id"],))
        else:
            _exec(conn, f"UPDATE stock_lots SET shares={p()} WHERE id={p()}", (remaining, lot["id"]))

        conn.commit()
        gain = round((sale_price - float(lot["purchase_price"])) * shares_to_sell, 2)
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

# ── Gemini price fetch ────────────────────────────────────────────────────────

@bp.route("/api/stocks/fetch-prices", methods=["POST"])
@approved_required
def fetch_prices_ai():
    d = request.json or {}
    api_key = d.get("api_key") or get_gemini_key(uid())
    if d.get("api_key"):
        cfg_set(uid(), "gemini_api_key", d["api_key"])
    if not api_key:
        return jsonify({"error": "No Gemini API key — add it in Settings"}), 400

    conn = get_db()
    try:
        tickers = _fetchall(conn,
            f"""SELECT DISTINCT ticker, COALESCE(exchange,'NSE') as exchange
                FROM stock_lots WHERE shares > 0 AND user_id={p()}""",
            (uid(),))
    finally:
        conn.close()

    if not tickers:
        return jsonify({"error": "No active positions in portfolio"}), 400

    try:
        prices = fetch_prices(api_key, tickers)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    today = _today()
    saved = []
    conn  = get_db()
    try:
        for tkr, price in prices.items():
            row = _fetchone(conn,
                f"""SELECT COALESCE(exchange,'NSE') as exchange, currency
                    FROM stock_lots
                    WHERE UPPER(ticker)={p()} AND user_id={p()} LIMIT 1""",
                (tkr, uid()))
            exch = row["exchange"] if row else "NSE"
            cur  = (row.get("currency") or EXCUR.get(exch,"KES")) if row else "KES"
            _exec(conn,
                f"""INSERT INTO stock_prices
                    (user_id,ticker,exchange,price,currency,date,note)
                    VALUES ({p()},{p()},{p()},{p()},{p()},{p()},{p()})""",
                (uid(), tkr, exch, price, cur, today, "Auto-fetched via Gemini AI"))
            saved.append({"ticker": tkr, "exchange": exch, "price": price})
        conn.commit()
    finally:
        conn.close()

    _save_snapshot()
    return jsonify({"ok": True, "saved": saved, "date": today})

# ── Portfolio snapshots ───────────────────────────────────────────────────────

def _save_snapshot():
    conn = get_db()
    try:
        port  = _build_portfolio(conn)
        rows  = _fetchall(conn,
            f"SELECT * FROM savings WHERE user_id={ph()}", (uid(),))
        other = sum(
            float(r["amount"]) if r["type"]=="deposit" else -float(r["amount"])
            for r in rows)
        stock = port["total_market"]
        total = stock + other
        today = _today()
        # BUG FIX: uid() must be FIRST parameter — matches upsert_snapshot_sql()
        _exec(conn, upsert_snapshot_sql(),
              (uid(), today,
               round(total,2), round(stock,2), round(other,2),
               round(port["total_cost"],2), round(port["total_gain"],2)))
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
    finally:
        conn.close()

    sav_by_class, broker_totals = {}, {}
    for r in sav_rows:
        v = float(r["amount"]) if r["type"]=="deposit" else -float(r["amount"])
        sav_by_class[r["asset_class"]] = sav_by_class.get(r["asset_class"],0) + v
    for lot in port["lots"]:
        b = lot.get("broker","Unknown") or "Unknown"
        broker_totals[b] = broker_totals.get(b,0) + float(lot["shares"])*float(lot["purchase_price"])

    stock_by_exch = {}
    for h in port["holdings"]:
        cls = f"Stocks ({h['exchange']})"
        cur = h.get("currency") or EXCUR.get(h["exchange"],"—")
        if cls not in stock_by_exch:
            stock_by_exch[cls] = {"value":0,"cost":0,"currency":cur,
                                   "type":"stocks","exchange":h["exchange"]}
        val = h["market_value"] if h["market_value"] is not None else h["total_cost"]
        stock_by_exch[cls]["value"] += val
        stock_by_exch[cls]["cost"]  += h["total_cost"]

    asset_summary = {
        **{cls:d for cls,d in stock_by_exch.items()},
        **{cls:{"value":v,"cost":v,"currency":"KES","type":"savings"}
           for cls,v in sav_by_class.items()}
    }
    total_all = sum(v["value"] for v in asset_summary.values())
    for d in asset_summary.values():
        gain = d["value"] - d["cost"]
        d.update({
            "gain":      round(gain,2),
            "gain_pct":  round(gain/d["cost"]*100,2) if d["cost"] else 0,
            "value":     round(d["value"],2),
            "cost":      round(d["cost"],2),
            "pct_total": round(d["value"]/total_all*100,1) if total_all else 0,
        })

    return jsonify({
        "asset_summary":  asset_summary,
        "total_value":    round(total_all,2),
        "total_cost":     round(sum(v["cost"] for v in asset_summary.values()),2),
        "total_gain":     round(sum(v["gain"] for v in asset_summary.values()),2),
        "total_realized": port["total_realized"],
        "broker_totals":  {k: round(v,2) for k,v in
                           sorted(broker_totals.items(), key=lambda x:-x[1])},
        "stock_summary":  {
            "total_cost":   port["total_cost"],
            "total_market": port["total_market"],
            "total_gain":   port["total_gain"],
            "pct":          port["portfolio_pct"],
        },
        "savings_net":   round(sum(sav_by_class.values()),2),
        "currency_note": any(v.get("currency") not in ("KES","—")
                             for v in asset_summary.values()),
    })

# ── Portfolio review ──────────────────────────────────────────────────────────

@bp.route("/api/portfolio/review", methods=["POST"])
@approved_required
def gen_review():
    api_key = get_gemini_key(uid())
    if not api_key:
        return jsonify({"error": "No Gemini API key — add it in Settings"}), 400
    conn = get_db()
    try:
        port = _build_portfolio(conn)
        sav  = {}
        for r in _fetchall(conn,
            f"""SELECT asset_class,
                       SUM(CASE WHEN type='deposit' THEN amount ELSE -amount END) as v
                FROM savings WHERE user_id={ph()}
                GROUP BY asset_class""", (uid(),)):
            sav[r["asset_class"]] = float(r["v"])
    finally:
        conn.close()
    try:
        review = generate_review(api_key, port, sav)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    cfg_set(uid(), "last_review", json.dumps({"date": _today(), **review}))
    return jsonify({"ok": True, "review": review})

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

@bp.route("/api/config")
@approved_required
def get_config():
    import os
    using_secret_mgr = bool(os.environ.get("GEMINI_SECRET_NAME"))
    key    = get_gemini_key(uid()) or ""
    masked = ("*"*max(0,len(key)-4)+key[-4:]) if len(key)>4 else "*"*len(key)
    return jsonify({
        "gemini_key_set":       bool(key),
        "gemini_key_masked":    masked,
        "using_secret_manager": using_secret_mgr,
    })

@bp.route("/api/config", methods=["POST"])
@approved_required
def set_config():
    d = request.json or {}
    key = d.get("gemini_api_key","").strip()
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
            f"SELECT * FROM stock_lots WHERE user_id={p()} ORDER BY ticker,date", (uid(),))
    finally:
        conn.close()
    out = io.StringIO()
    w   = csv.writer(out)
    w.writerow(["Date","Ticker","Exchange","Shares Remaining","Original Shares",
                "Purchase Price","Currency","Current Value","Broker","Note"])
    for r in rows:
        w.writerow([r["date"], r["ticker"], r["exchange"], r["shares"],
                    r.get("original_shares",""), r["purchase_price"],
                    r.get("currency","KES"),
                    round(float(r["shares"])*float(r["purchase_price"]),2),
                    r["broker"], r["note"]])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition":"attachment;filename=stock_lots.csv"})

@bp.route("/api/export/savings.csv")
@approved_required
def export_savings():
    conn = get_db()
    try:
        rows = _fetchall(conn,
            f"SELECT * FROM savings WHERE user_id={p()} ORDER BY date DESC", (uid(),))
    finally:
        conn.close()
    out = io.StringIO()
    w   = csv.writer(out)
    w.writerow(["Date","Label","Asset Class","Type","Amount","Currency","Note"])
    for r in rows:
        w.writerow([r["date"], r["label"], r["asset_class"], r["type"],
                    r["amount"], r.get("currency","KES"), r["note"]])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition":"attachment;filename=savings.csv"})

@bp.route("/api/export/sales.csv")
@approved_required
def export_sales():
    conn = get_db()
    try:
        rows = _fetchall(conn,
            f"SELECT * FROM stock_sales WHERE user_id={p()} ORDER BY date DESC", (uid(),))
    finally:
        conn.close()
    out = io.StringIO()
    w   = csv.writer(out)
    w.writerow(["Date","Ticker","Exchange","Shares","Buy Price",
                "Sale Price","Gain/Loss","Currency","Broker","Note"])
    for r in rows:
        gain = round((float(r["sale_price"])-float(r["purchase_price"]))*float(r["shares"]),2)
        w.writerow([r["date"], r["ticker"], r["exchange"], r["shares"],
                    r["purchase_price"], r["sale_price"], gain,
                    r.get("currency","KES"), r["broker"], r["note"]])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition":"attachment;filename=sales.csv"})
