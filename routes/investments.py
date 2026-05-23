"""Investment routes: savings, stock lots, prices, sales, overview, snapshots, export."""
import csv, io, json
from datetime import datetime
from flask import Blueprint, request, jsonify, Response
from db import get_db, cfg_get, cfg_set
from services.gemini import fetch_prices, generate_review

bp = Blueprint("investments", __name__)

ASSET_CLASSES = ["Cash","SACCO / Chama","Bonds / T-Bills","Pension / NSSF",
                 "Real Estate","Crypto","Unit Trust / MMF","Foreign Currency","Other"]
EXCHANGES     = ["NSE","NYSE","NASDAQ","LSE","JSE","EURONEXT","HKEX","Other"]
EXCUR         = {"NSE":"KES","NYSE":"USD","NASDAQ":"USD","LSE":"GBP",
                 "JSE":"ZAR","EURONEXT":"EUR","HKEX":"HKD","Other":"—"}

def _today(): return datetime.today().strftime("%Y-%m-%d")

def _require(d, *keys):
    """Raise ValueError with a clear message if any key is missing or blank."""
    missing = [k for k in keys if not d.get(k) and d.get(k) != 0]
    if missing:
        raise ValueError(f"Missing required field(s): {', '.join(missing)}")

# ── Savings ───────────────────────────────────────────────────────────────────

@bp.route("/api/savings")
def get_savings():
    with get_db() as db:
        rows = [dict(r) for r in db.execute(
            "SELECT * FROM savings ORDER BY date DESC").fetchall()]
    totals, net = {}, 0
    for e in rows:
        v = e["amount"] if e["type"] == "deposit" else -e["amount"]
        totals[e["asset_class"]] = totals.get(e["asset_class"], 0) + v
        net += v
    return jsonify({"entries": rows, "totals_by_class": totals, "net_total": net})

@bp.route("/api/savings", methods=["POST"])
def add_saving():
    d = request.json or {}
    try:
        _require(d, "label", "asset_class", "amount", "type", "date")
        if d["type"] not in ("deposit","withdrawal"):
            raise ValueError("type must be deposit or withdrawal")
        float(d["amount"])
    except (ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    with get_db() as db:
        db.execute("INSERT INTO savings (label,asset_class,amount,type,note,date) VALUES (?,?,?,?,?,?)",
                   (d["label"], d["asset_class"], float(d["amount"]), d["type"],
                    d.get("note",""), d["date"]))
    return jsonify({"ok": True})

@bp.route("/api/savings/<int:sid>", methods=["PUT"])
def edit_saving(sid):
    d = request.json or {}
    try:
        _require(d, "label", "asset_class", "amount", "type", "date")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    with get_db() as db:
        db.execute("UPDATE savings SET label=?,asset_class=?,amount=?,type=?,note=?,date=? WHERE id=?",
                   (d["label"], d["asset_class"], float(d["amount"]), d["type"],
                    d.get("note",""), d["date"], sid))
    return jsonify({"ok": True})

@bp.route("/api/savings/<int:sid>", methods=["DELETE"])
def delete_saving(sid):
    with get_db() as db:
        db.execute("DELETE FROM savings WHERE id=?", (sid,))
    return jsonify({"ok": True})

# ── Portfolio helper ──────────────────────────────────────────────────────────

def _build_portfolio(db):
    lots   = [dict(r) for r in db.execute("SELECT * FROM stock_lots ORDER BY date DESC").fetchall()]
    prices = [dict(r) for r in db.execute("SELECT * FROM stock_prices ORDER BY date DESC").fetchall()]
    sales  = [dict(r) for r in db.execute("SELECT * FROM stock_sales ORDER BY date DESC").fetchall()]

    latest_price = {}
    for p in prices:
        k = (p["ticker"], p.get("exchange","NSE"))
        if k not in latest_price:
            latest_price[k] = p

    # Price history per ticker for sparklines (last 60 days, asc)
    price_hist = {}
    for p in reversed(prices):
        k = (p["ticker"], p.get("exchange","NSE"))
        price_hist.setdefault(k, []).append({"date": p["date"], "price": p["price"]})

    tickers = {}
    for lot in lots:
        exch = lot.get("exchange","NSE")
        k = (lot["ticker"], exch)
        if k not in tickers:
            tickers[k] = {"ticker": lot["ticker"], "exchange": exch,
                          "currency": EXCUR.get(exch,"—"),
                          "lots": [], "total_shares": 0, "total_cost": 0}
        tickers[k]["lots"].append(lot)
        tickers[k]["total_shares"] += lot["shares"]
        tickers[k]["total_cost"]   += lot["shares"] * lot["purchase_price"]

    # Realized gains per ticker
    realized = {}
    for s in sales:
        k = (s["ticker"], s.get("exchange","NSE"))
        gain = (s["sale_price"] - s["purchase_price"]) * s["shares"]
        realized.setdefault(k, {"realized_gain":0,"sold_shares":0,"sales":[]})
        realized[k]["realized_gain"] += gain
        realized[k]["sold_shares"]   += s["shares"]
        realized[k]["sales"].append(s)

    holdings, total_cost, total_mkt = [], 0, 0
    for k, h in tickers.items():
        h["avg_cost"] = round(h["total_cost"]/h["total_shares"],4) if h["total_shares"] else 0
        lp = latest_price.get(k)
        if lp:
            mkt  = h["total_shares"] * lp["price"]
            gain = mkt - h["total_cost"]
            pct  = round(gain/h["total_cost"]*100,2) if h["total_cost"] else 0
            h.update({"market_price": lp["price"], "market_value": round(mkt,2),
                      "gain_loss": round(gain,2), "pct_return": pct, "price_date": lp["date"]})
            total_mkt += mkt
        else:
            h.update({"market_price":None,"market_value":None,
                      "gain_loss":None,"pct_return":None,"price_date":None})
        h["realized"] = realized.get(k, {"realized_gain":0,"sold_shares":0,"sales":[]})
        h["price_history"] = price_hist.get(k, [])[-30:]  # last 30 data points
        total_cost += h["total_cost"]
        holdings.append(h)

    total_realized = sum(r["realized_gain"] for r in realized.values())
    gain = total_mkt - total_cost
    return {
        "holdings": holdings,
        "lots": lots,
        "sales": sales,
        "price_history": [dict(r) for r in db.execute(
            "SELECT * FROM stock_prices ORDER BY date DESC").fetchall()],
        "total_cost":      round(total_cost,2),
        "total_market":    round(total_mkt,2),
        "total_gain":      round(gain,2),
        "total_realized":  round(total_realized,2),
        "portfolio_pct":   round(gain/total_cost*100,2) if total_cost else 0,
    }

# ── Stocks ─────────────────────────────────────────────────────────────────────

@bp.route("/api/stocks")
def get_stocks():
    with get_db() as db:
        return jsonify(_build_portfolio(db))

@bp.route("/api/stocks/lot", methods=["POST"])
def add_lot():
    d = request.json or {}
    try:
        _require(d, "ticker","exchange","shares","purchase_price","date")
        if float(d["shares"]) <= 0 or float(d["purchase_price"]) <= 0:
            raise ValueError("shares and purchase_price must be positive")
    except (ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    with get_db() as db:
        db.execute("INSERT INTO stock_lots (ticker,exchange,shares,purchase_price,date,broker,note) VALUES (?,?,?,?,?,?,?)",
                   (d["ticker"].upper().strip(), d["exchange"],
                    float(d["shares"]), float(d["purchase_price"]),
                    d["date"], d.get("broker",""), d.get("note","")))
    return jsonify({"ok": True})

@bp.route("/api/stocks/lot/<int:lid>", methods=["PUT"])
def edit_lot(lid):
    d = request.json or {}
    try:
        _require(d, "ticker","exchange","shares","purchase_price","date")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    with get_db() as db:
        db.execute("UPDATE stock_lots SET ticker=?,exchange=?,shares=?,purchase_price=?,date=?,broker=?,note=? WHERE id=?",
                   (d["ticker"].upper().strip(), d["exchange"],
                    float(d["shares"]), float(d["purchase_price"]),
                    d["date"], d.get("broker",""), d.get("note",""), lid))
    return jsonify({"ok": True})

@bp.route("/api/stocks/lot/<int:lid>", methods=["DELETE"])
def delete_lot(lid):
    with get_db() as db:
        db.execute("DELETE FROM stock_lots WHERE id=?", (lid,))
    return jsonify({"ok": True})

@bp.route("/api/stocks/price", methods=["POST"])
def add_price():
    d = request.json or {}
    try:
        _require(d, "ticker","exchange","price","date")
        if float(d["price"]) <= 0:
            raise ValueError("price must be positive")
    except (ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    with get_db() as db:
        db.execute("INSERT INTO stock_prices (ticker,exchange,price,date,note) VALUES (?,?,?,?,?)",
                   (d["ticker"].upper().strip(), d["exchange"],
                    float(d["price"]), d["date"], d.get("note","")))
    return jsonify({"ok": True})

@bp.route("/api/stocks/price/<int:pid>", methods=["DELETE"])
def delete_price(pid):
    with get_db() as db:
        db.execute("DELETE FROM stock_prices WHERE id=?", (pid,))
    return jsonify({"ok": True})

# ── Realized gains (sales) ────────────────────────────────────────────────────

@bp.route("/api/stocks/sale", methods=["POST"])
def record_sale():
    d = request.json or {}
    try:
        _require(d, "ticker","exchange","shares","purchase_price","sale_price","date")
        if any(float(d[k]) <= 0 for k in ("shares","purchase_price","sale_price")):
            raise ValueError("shares, purchase_price and sale_price must be positive")
    except (ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    with get_db() as db:
        db.execute("INSERT INTO stock_sales (ticker,exchange,shares,purchase_price,sale_price,date,broker,note) VALUES (?,?,?,?,?,?,?,?)",
                   (d["ticker"].upper().strip(), d["exchange"],
                    float(d["shares"]), float(d["purchase_price"]),
                    float(d["sale_price"]), d["date"],
                    d.get("broker",""), d.get("note","")))
    return jsonify({"ok": True})

@bp.route("/api/stocks/sale/<int:sid>", methods=["DELETE"])
def delete_sale(sid):
    with get_db() as db:
        db.execute("DELETE FROM stock_sales WHERE id=?", (sid,))
    return jsonify({"ok": True})

# ── Gemini price fetch ────────────────────────────────────────────────────────

@bp.route("/api/stocks/fetch-prices", methods=["POST"])
def fetch_prices_ai():
    d = request.json or {}
    api_key = d.get("api_key") or cfg_get("gemini_api_key")
    if d.get("api_key"):
        cfg_set("gemini_api_key", d["api_key"])
    if not api_key:
        return jsonify({"error": "No Gemini API key — add it in Settings"}), 400

    with get_db() as db:
        tickers = [dict(r) for r in db.execute(
            "SELECT DISTINCT ticker, COALESCE(exchange,'NSE') as exchange FROM stock_lots"
        ).fetchall()]
    if not tickers:
        return jsonify({"error": "No tickers in portfolio"}), 400

    try:
        prices = fetch_prices(api_key, tickers)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    today = _today()
    saved = []
    with get_db() as db:
        for tkr, price in prices.items():
            row = db.execute(
                "SELECT COALESCE(exchange,'NSE') as exchange FROM stock_lots WHERE UPPER(ticker)=? LIMIT 1",
                (tkr,)).fetchone()
            exch = row["exchange"] if row else "NSE"
            db.execute("INSERT INTO stock_prices (ticker,exchange,price,date,note) VALUES (?,?,?,?,?)",
                       (tkr, exch, price, today, "Auto-fetched via Gemini AI"))
            saved.append({"ticker": tkr, "exchange": exch, "price": price})

    # Auto-save portfolio snapshot
    _save_snapshot()
    return jsonify({"ok": True, "saved": saved, "date": today})

# ── Portfolio snapshots ───────────────────────────────────────────────────────

def _save_snapshot():
    """Compute current total portfolio value and upsert into portfolio_snapshots."""
    with get_db() as db:
        port = _build_portfolio(db)
        rows = [dict(r) for r in db.execute("SELECT * FROM savings").fetchall()]
    other = sum(r["amount"] if r["type"]=="deposit" else -r["amount"] for r in rows)
    stock = port["total_market"]
    total = stock + other
    today = _today()
    with get_db() as db:
        db.execute("""INSERT INTO portfolio_snapshots (date,total_value,stock_value,other_value,total_cost,total_gain)
                      VALUES (?,?,?,?,?,?)
                      ON CONFLICT(date) DO UPDATE SET
                        total_value=excluded.total_value,
                        stock_value=excluded.stock_value,
                        other_value=excluded.other_value,
                        total_cost=excluded.total_cost,
                        total_gain=excluded.total_gain""",
                   (today, round(total,2), round(stock,2), round(other,2),
                    round(port["total_cost"],2), round(port["total_gain"],2)))

@bp.route("/api/portfolio/snapshot", methods=["POST"])
def manual_snapshot():
    try:
        _save_snapshot()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route("/api/portfolio/snapshots")
def get_snapshots():
    with get_db() as db:
        rows = [dict(r) for r in db.execute(
            "SELECT * FROM portfolio_snapshots ORDER BY date ASC").fetchall()]
    return jsonify({"snapshots": rows})

# ── Investment overview ───────────────────────────────────────────────────────

@bp.route("/api/investments/overview")
def investment_overview():
    with get_db() as db:
        port = _build_portfolio(db)
        sav_rows = [dict(r) for r in db.execute("SELECT * FROM savings").fetchall()]

    sav_by_class = {}
    for r in sav_rows:
        v = r["amount"] if r["type"]=="deposit" else -r["amount"]
        sav_by_class[r["asset_class"]] = sav_by_class.get(r["asset_class"],0) + v

    # Broker breakdown
    broker_totals = {}
    for lot in port["lots"]:
        b = lot.get("broker","Unknown") or "Unknown"
        broker_totals[b] = broker_totals.get(b,0) + lot["shares"]*lot["purchase_price"]

    stock_by_exch = {}
    for h in port["holdings"]:
        cls = f"Stocks ({h['exchange']})"
        cur = EXCUR.get(h["exchange"],"—")
        if cls not in stock_by_exch:
            stock_by_exch[cls] = {"value":0,"cost":0,"currency":cur,"type":"stocks","exchange":h["exchange"]}
        val = h["market_value"] if h["market_value"] is not None else h["total_cost"]
        stock_by_exch[cls]["value"] += val
        stock_by_exch[cls]["cost"]  += h["total_cost"]

    asset_summary = {**{cls:d for cls,d in stock_by_exch.items()},
                     **{cls:{"value":v,"cost":v,"currency":"KES","type":"savings"}
                        for cls,v in sav_by_class.items()}}

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
        "broker_totals":  {k: round(v,2) for k,v in sorted(broker_totals.items(), key=lambda x:-x[1])},
        "stock_summary":  {
            "total_cost":   port["total_cost"],
            "total_market": port["total_market"],
            "total_gain":   port["total_gain"],
            "pct":          port["portfolio_pct"],
        },
        "savings_net": round(sum(sav_by_class.values()),2),
        # Currency note: non-KES stocks are in their own currency
        "currency_note": any(v.get("currency") not in ("KES","—") for v in asset_summary.values()),
    })

# ── Portfolio review ──────────────────────────────────────────────────────────

@bp.route("/api/portfolio/review", methods=["POST"])
def gen_review():
    api_key = cfg_get("gemini_api_key")
    if not api_key:
        return jsonify({"error": "No Gemini API key — add it in Settings"}), 400
    with get_db() as db:
        port = _build_portfolio(db)
        sav = {r["asset_class"]: 0 for r in db.execute("SELECT DISTINCT asset_class FROM savings").fetchall()}
        for r in db.execute("SELECT asset_class, SUM(CASE WHEN type='deposit' THEN amount ELSE -amount END) as v FROM savings GROUP BY asset_class").fetchall():
            sav[r["asset_class"]] = r["v"]
    try:
        review = generate_review(api_key, port, sav)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    # Store review
    with get_db() as db:
        db.execute("""INSERT OR REPLACE INTO config (key,value) VALUES ('last_review',?)""",
                   (json.dumps({"date": _today(), **review}),))
    return jsonify({"ok": True, "review": review})

@bp.route("/api/portfolio/review")
def get_review():
    raw = cfg_get("last_review")
    if not raw:
        return jsonify({"review": None})
    try:
        return jsonify({"review": json.loads(raw)})
    except Exception:
        return jsonify({"review": None})

# ── Config ────────────────────────────────────────────────────────────────────

@bp.route("/api/config")
def get_config():
    key = cfg_get("gemini_api_key","")
    masked = ("*"*max(0,len(key)-4)+key[-4:]) if len(key)>4 else "*"*len(key)
    return jsonify({"gemini_key_set": bool(key), "gemini_key_masked": masked})

@bp.route("/api/config", methods=["POST"])
def set_config():
    d = request.json or {}
    if d.get("gemini_api_key"):
        cfg_set("gemini_api_key", d["gemini_api_key"])
    return jsonify({"ok": True})

# ── CSV Export ────────────────────────────────────────────────────────────────

@bp.route("/api/export/lots.csv")
def export_lots():
    with get_db() as db:
        rows = db.execute("SELECT * FROM stock_lots ORDER BY ticker,date").fetchall()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Date","Ticker","Exchange","Shares","Purchase Price","Lot Value","Broker","Note"])
    for r in rows:
        w.writerow([r["date"],r["ticker"],r["exchange"],r["shares"],
                    r["purchase_price"],round(r["shares"]*r["purchase_price"],2),
                    r["broker"],r["note"]])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment;filename=stock_lots.csv"})

@bp.route("/api/export/savings.csv")
def export_savings():
    with get_db() as db:
        rows = db.execute("SELECT * FROM savings ORDER BY date DESC").fetchall()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Date","Label","Asset Class","Type","Amount","Note"])
    for r in rows:
        w.writerow([r["date"],r["label"],r["asset_class"],r["type"],r["amount"],r["note"]])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment;filename=savings.csv"})

@bp.route("/api/export/sales.csv")
def export_sales():
    with get_db() as db:
        rows = db.execute("SELECT * FROM stock_sales ORDER BY date DESC").fetchall()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Date","Ticker","Exchange","Shares","Purchase Price","Sale Price","Gain/Loss","Broker","Note"])
    for r in rows:
        gain = round((r["sale_price"]-r["purchase_price"])*r["shares"],2)
        w.writerow([r["date"],r["ticker"],r["exchange"],r["shares"],
                    r["purchase_price"],r["sale_price"],gain,r["broker"],r["note"]])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment;filename=sales.csv"})
