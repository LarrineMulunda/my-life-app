"""
services/price_agents.py — 3-Agent Price Fetching Pipeline.

Agent 1 — Price Fetcher
  One Gemini call with all tickers. Returns raw prices.

Agent 2 — Anomaly Checker
  Compares each price to the last known price from global_prices.
  Flags anything outside configured thresholds.

Agent 3 — Reviewer
  For each flagged price, makes a targeted Gemini re-check.
  Confirms, corrects, or marks for manual review.
  Writes confirmed/corrected prices to DB.
  Writes all anomalies to price_anomalies table for user inspection.

Same 3-agent flow runs for FX rates.
"""
import json
import re
from datetime import datetime, date

try:
    import requests as _req
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

GEMINI_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
              "gemini-2.0-flash:generateContent")

# ── Anomaly thresholds ────────────────────────────────────────────────────────
THRESHOLDS = {
    "stock": {
        "flag": 0.35,   # 0–35% abs change → write directly; >35% → Agent 3 review
    },
    "fx": {
        "flag": 0.35,   # same rule for FX rates
    },
}


# ── Gemini helpers ────────────────────────────────────────────────────────────

def _gemini(api_key, prompt, timeout=90):
    if not HAS_REQUESTS:
        raise RuntimeError("requests not installed")
    resp = _req.post(
        f"{GEMINI_URL}?key={api_key}",
        json={
            "contents":         [{"parts": [{"text": prompt}]}],
            "tools":            [{"google_search": {}}],
            "generationConfig": {"temperature": 0.1},
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    return "".join(
        p.get("text", "")
        for p in data.get("candidates", [{}])[0]
                     .get("content", {}).get("parts", [])
    )


def _extract_json(text):
    text = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
    for s, e in [('{', '}'), ('[', ']')]:
        start = text.find(s)
        if start == -1:
            continue
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == s:   depth += 1
            elif ch == e:
                depth -= 1
                if depth == 0:
                    return json.loads(text[start:i + 1])
    raise ValueError(f"No JSON found: {text[:300]}")


# ── DB helpers ────────────────────────────────────────────────────────────────

def _get_previous_prices(conn):
    """Return {(ticker, exchange): last_price} from global_prices."""
    from db import is_pg
    cur = conn.cursor()
    if is_pg():
        cur.execute("""
            SELECT DISTINCT ON (ticker, exchange) ticker, exchange, price
            FROM global_prices
            ORDER BY ticker, exchange, date DESC
        """)
    else:
        cur.execute("""
            SELECT gp.ticker, gp.exchange, gp.price
            FROM global_prices gp
            INNER JOIN (
                SELECT ticker, exchange, MAX(date) as max_date
                FROM global_prices GROUP BY ticker, exchange
            ) latest ON gp.ticker=latest.ticker
                AND gp.exchange=latest.exchange
                AND gp.date=latest.max_date
        """)
    result = {}
    for r in cur.fetchall():
        if is_pg():
            result[(r["ticker"], r["exchange"])] = float(r["price"])
        else:
            result[(r[0], r[1])] = float(r[2])
    return result


def _get_previous_fx(conn):
    """Return {currency: kes_rate} from global_fx."""
    from db import is_pg
    cur = conn.cursor()
    cur.execute("SELECT currency, kes_rate FROM global_fx")
    result = {}
    for r in cur.fetchall():
        if is_pg():
            result[r["currency"]] = float(r["kes_rate"])
        else:
            result[r[0]] = float(r[1])
    return result


def _save_anomaly(conn, type_, ticker, exchange, currency,
                  fetched, previous, pct, status, reviewed, note):
    from db import ph, is_pg
    now = datetime.utcnow().isoformat()
    resolved = now if status in ("confirmed", "corrected") else None
    cur = conn.cursor()
    if is_pg():
        cur.execute("""
            INSERT INTO price_anomalies
                (type,ticker,exchange,currency,fetched_value,previous_value,
                 pct_change,status,reviewed_value,review_note,created_at,resolved_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (type_, ticker, exchange, currency, fetched, previous,
              pct, status, reviewed, note, now, resolved))
    else:
        cur.execute("""
            INSERT INTO price_anomalies
                (type,ticker,exchange,currency,fetched_value,previous_value,
                 pct_change,status,reviewed_value,review_note,created_at,resolved_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (type_, ticker, exchange, currency, fetched, previous,
              pct, status, reviewed, note, now, resolved))


def _upsert_global_price(conn, ticker, exchange, price, currency, today):
    from db import is_pg
    cur = conn.cursor()
    if is_pg():
        cur.execute("""
            INSERT INTO global_prices (ticker,exchange,price,currency,date,note)
            VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT(ticker,exchange,date) DO UPDATE SET
                price=EXCLUDED.price, note=EXCLUDED.note
        """, (ticker, exchange, price, currency, today, "agentic-fetch"))
    else:
        cur.execute("""
            INSERT OR REPLACE INTO global_prices
                (ticker,exchange,price,currency,date,note)
            VALUES (?,?,?,?,?,?)
        """, (ticker, exchange, price, currency, today, "agentic-fetch"))


def _upsert_global_fx(conn, currency, rate, today):
    from db import is_pg
    cur = conn.cursor()
    if is_pg():
        cur.execute("""
            INSERT INTO global_fx (currency,kes_rate,updated_date)
            VALUES (%s,%s,%s)
            ON CONFLICT(currency) DO UPDATE SET
                kes_rate=EXCLUDED.kes_rate, updated_date=EXCLUDED.updated_date
        """, (currency, rate, today))
    else:
        cur.execute("""
            INSERT OR REPLACE INTO global_fx (currency,kes_rate,updated_date)
            VALUES (?,?,?)
        """, (currency, rate, today))


# ═══════════════════════════════════════════════════════════════════════════════
#  AGENT 1 — PRICE FETCHER
# ═══════════════════════════════════════════════════════════════════════════════

def agent_fetch_prices(api_key, tickers):
    """
    One Gemini call for all tickers.
    tickers: [{ticker, exchange}]
    Returns {TICKER: price_float}
    """
    if not tickers:
        return {}

    today = datetime.today().strftime("%Y-%m-%d")
    ticker_list = ", ".join(f"{t['ticker']} on {t['exchange']}" for t in tickers)

    prompt = (
        f"Fetch the latest end-of-day closing prices for ALL of the following: {ticker_list}.\n"
        f"Today is {today}. Use Google Search for real-time data.\n"
        "Return ONLY raw JSON — no markdown, no explanation:\n"
        '{"TICKER": price_as_number}\n'
        "NSE prices in KES, NYSE/NASDAQ in USD, LSE in GBP, JSE in ZAR, "
        "EURONEXT in EUR, HKEX in HKD, CRYPTO in USD. "
        "Use most recent available price for each. Include every ticker."
    )
    text   = _gemini(api_key, prompt)
    raw    = _extract_json(text)
    result = {}
    for k, v in raw.items():
        try:
            f = float(v)
            if f > 0:
                result[k.upper().strip()] = f
        except (TypeError, ValueError):
            pass
    return result


def agent_fetch_fx(api_key):
    """
    One Gemini call for all FX rates to KES.
    Returns {currency: kes_rate}
    """
    today = datetime.today().strftime("%Y-%m-%d")
    prompt = (
        f"Get current exchange rates to KES as of {today}. Use Google Search.\n"
        "Return ONLY raw JSON:\n"
        '{"USD": rate, "GBP": rate, "EUR": rate, "ZAR": rate, '
        '"TZS": rate, "UGX": rate, "GHS": rate, "HKD": rate, "XOF": rate}\n'
        "Each rate = how many KES per 1 unit of that currency."
    )
    text = _gemini(api_key, prompt)
    raw  = _extract_json(text)
    result = {}
    for k, v in raw.items():
        try:
            r = float(v)
            if r > 0:
                result[k.upper().strip()] = r
        except (TypeError, ValueError):
            pass
    result["KES"] = 1.0
    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  AGENT 2 — ANOMALY CHECKER
# ═══════════════════════════════════════════════════════════════════════════════

def agent_check_anomalies(new_prices, previous_prices, tickers_meta, mode="stock"):
    """
    Compare new prices/rates to previous values.

    new_prices:      {TICKER: float}  or  {CURRENCY: float}
    previous_prices: {(ticker, exchange): float}  or  {currency: float}
    tickers_meta:    [{ticker, exchange}]  (only used for stock mode)
    mode:            "stock" or "fx"

    Returns:
      clean:   {key: price}   — passed checks, ready to write
      flagged: [{...}]        — need Agent 3 review
      missing: [ticker/cur]   — Gemini didn't return a price for these
    """
    flag_pct = THRESHOLDS.get(mode, THRESHOLDS["stock"])["flag"]

    clean   = {}
    flagged = []

    if mode == "stock":
        # Build case-insensitive lookup: UPPER(ticker) -> exchange
        ticker_to_exch = {t["ticker"].upper(): t["exchange"] for t in tickers_meta}

        for ticker_raw, price in new_prices.items():
            ticker = ticker_raw.upper().strip()
            exch   = ticker_to_exch.get(ticker, "NSE")
            prev = previous_prices.get((ticker, exch))

            if price <= 0:
                # Always flag zero or negative — clearly wrong
                flagged.append({
                    "type":       "price",
                    "ticker":     ticker,
                    "exchange":   exch,
                    "new_price":  price,
                    "prev_price": prev,
                    "pct_change": None,
                    "reason":     "ZERO_OR_NEGATIVE",
                    "severity":   "HIGH",
                })
                continue

            if prev is None or prev <= 0:
                # No prior price → accept without comparison
                clean[(ticker, exch)] = price
                continue

            pct     = (price - prev) / prev
            abs_pct = abs(pct)

            if abs_pct > flag_pct:
                # > 35% abs change → flag for Agent 3 re-check
                flagged.append({
                    "type":       "price",
                    "ticker":     ticker,
                    "exchange":   exch,
                    "new_price":  price,
                    "prev_price": prev,
                    "pct_change": round(pct * 100, 2),
                    "reason":     "LARGE_CHANGE",
                    "severity":   "HIGH" if abs_pct > 1.0 else "MEDIUM",
                })
            else:
                # 0–35% abs change (positive or negative) → write directly
                clean[(ticker, exch)] = price

        new_upper = {k.upper().strip() for k in new_prices.keys()}
        missing = [t["ticker"] for t in tickers_meta
                   if t["ticker"].upper() not in new_upper]

    else:  # FX mode — same single-threshold rule
        for currency, rate in new_prices.items():
            if currency == "KES":
                continue
            prev = previous_prices.get(currency)
            if prev is None or prev <= 0:
                clean[currency] = rate
                continue

            pct     = (rate - prev) / prev
            abs_pct = abs(pct)

            if abs_pct > flag_pct:
                flagged.append({
                    "type":       "fx",
                    "ticker":     currency,
                    "exchange":   "FX",
                    "currency":   currency,
                    "new_price":  rate,
                    "prev_price": prev,
                    "pct_change": round(pct * 100, 2),
                    "reason":     "LARGE_FX_CHANGE",
                    "severity":   "HIGH" if abs_pct > 1.0 else "MEDIUM",
                })
            else:
                clean[currency] = rate

        missing = []

    return {"clean": clean, "flagged": flagged, "missing": missing}


# ═══════════════════════════════════════════════════════════════════════════════
#  AGENT 3 — REVIEWER
# ═══════════════════════════════════════════════════════════════════════════════

def agent_review_anomalies(api_key, flagged_items):
    """
    For each flagged price, do a targeted Gemini re-check.
    Returns list of reviewed items with status:
      confirmed       — Gemini agrees with new price
      corrected       — Gemini found a different price
      manual_review   — Gemini couldn't verify, needs human
    """
    if not flagged_items:
        return []

    today   = datetime.today().strftime("%Y-%m-%d")
    reviewed = []

    for item in flagged_items:
        is_fx   = item.get("type") == "fx"
        ticker  = item["ticker"]
        exch    = item.get("exchange", "FX")
        new_p   = item["new_price"]
        prev_p  = item.get("prev_price")
        pct     = item.get("pct_change")
        reason  = item.get("reason", "")

        if is_fx:
            prompt = (
                f"Verify the current exchange rate for {ticker} to KES.\n"
                f"Today is {today}. Use Google Search for the live rate.\n"
                f"Previous known rate: 1 {ticker} = {prev_p} KES\n"
                f"Fetched rate: 1 {ticker} = {new_p} KES  ({pct:+.1f}% change)\n\n"
                f"Is the fetched rate correct? If not, what is the right rate?\n"
                "Return ONLY raw JSON:\n"
                '{"verdict":"CONFIRMED|CORRECTED|UNVERIFIABLE",'
                '"correct_rate":number_or_null,"confidence":"HIGH|MEDIUM|LOW","note":""}'
            )
        else:
            prompt = (
                f"Verify the current price of {ticker} on {exch}.\n"
                f"Today is {today}. Use Google Search for the latest price.\n"
                f"Previous known price: {prev_p}\n"
                f"Fetched price: {new_p}  ({pct:+.1f}% change)\n"
                f"Reason flagged: {reason}\n\n"
                "Check if this price is correct. "
                "Could be: stock split, dividend ex-date, major news, or data error.\n"
                "Return ONLY raw JSON:\n"
                '{"verdict":"CONFIRMED|CORRECTED|UNVERIFIABLE",'
                '"correct_price":number_or_null,'
                '"confidence":"HIGH|MEDIUM|LOW",'
                '"explanation":"","event":""}'
            )

        try:
            text   = _gemini(api_key, prompt, timeout=60)
            result = _extract_json(text)
            verdict    = result.get("verdict", "UNVERIFIABLE")
            confidence = result.get("confidence", "LOW")

            if verdict == "CONFIRMED":
                reviewed.append({**item,
                    "status":         "confirmed",
                    "reviewed_value": new_p,
                    "note":           result.get("explanation") or result.get("note",""),
                    "confidence":     confidence,
                })
            elif verdict == "CORRECTED":
                corrected = result.get("correct_price") or result.get("correct_rate")
                if corrected and float(corrected) > 0:
                    reviewed.append({**item,
                        "status":         "corrected",
                        "reviewed_value": float(corrected),
                        "note":           result.get("explanation") or result.get("note",""),
                        "confidence":     confidence,
                    })
                else:
                    reviewed.append({**item,
                        "status":         "manual_review",
                        "reviewed_value": None,
                        "note":           "Correction returned invalid price",
                        "confidence":     "LOW",
                    })
            else:
                reviewed.append({**item,
                    "status":         "manual_review",
                    "reviewed_value": None,
                    "note":           result.get("explanation") or result.get("note", "Unverifiable"),
                    "confidence":     confidence,
                })

        except Exception as e:
            reviewed.append({**item,
                "status":         "manual_review",
                "reviewed_value": None,
                "note":           f"Review error: {e}",
                "confidence":     "LOW",
            })

    return reviewed


# ═══════════════════════════════════════════════════════════════════════════════
#  PIPELINE ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════════

def run_price_pipeline(api_key, tickers_meta, conn):
    """
    Full 3-agent price pipeline.

    tickers_meta: [{ticker, exchange, currency}]
    conn:         DB connection (stays open for the duration)

    Returns result dict with full status report.
    """
    today = datetime.today().strftime("%Y-%m-%d")
    result = {
        "date":          today,
        "agent1":        {"status": "pending", "prices_fetched": 0},
        "agent2":        {"status": "pending", "clean": 0, "flagged": 0, "missing": 0},
        "agent3":        {"status": "pending", "confirmed": 0, "corrected": 0, "manual_review": 0},
        "written":       0,
        "anomalies":     [],
        "manual_review": [],
        "errors":        [],
    }

    # ── Agent 1: Fetch prices ─────────────────────────────────────────────────
    result["agent1"]["status"] = "running"
    try:
        new_prices = agent_fetch_prices(api_key, tickers_meta)
        result["agent1"]["status"]        = "done"
        result["agent1"]["prices_fetched"] = len(new_prices)
        result["agent1"]["prices"]        = new_prices
    except Exception as e:
        result["agent1"]["status"] = "error"
        result["agent1"]["error"]  = str(e)
        result["errors"].append(f"Agent1 (fetch): {e}")
        return result

    # ── Agent 2: Check anomalies ──────────────────────────────────────────────
    result["agent2"]["status"] = "running"
    try:
        prev_prices = _get_previous_prices(conn)
        check = agent_check_anomalies(
            new_prices, prev_prices, tickers_meta, mode="stock")
        result["agent2"]["status"]  = "done"
        result["agent2"]["clean"]   = len(check["clean"])
        result["agent2"]["flagged"] = len(check["flagged"])
        result["agent2"]["missing"] = len(check["missing"])
        if check["missing"]:
            result["agent2"]["missing_tickers"] = check["missing"]
    except Exception as e:
        result["agent2"]["status"] = "error"
        result["agent2"]["error"]  = str(e)
        result["errors"].append(f"Agent2 (anomaly): {e}")
        return result

    # ── Write clean prices ────────────────────────────────────────────────────
    # Build both normal and uppercase maps for resilient lookup
    ticker_cur_map  = {}
    ticker_exch_map = {}
    for t in tickers_meta:
        ticker_cur_map[t["ticker"]]          = t.get("currency","KES")
        ticker_cur_map[t["ticker"].upper()]  = t.get("currency","KES")
        ticker_exch_map[t["ticker"]]         = t["exchange"]
        ticker_exch_map[t["ticker"].upper()] = t["exchange"]

    for (ticker, exch), price in check["clean"].items():
        cur = ticker_cur_map.get(ticker) or ticker_cur_map.get(ticker.upper(), "KES")
        _upsert_global_price(conn, ticker, exch, price, cur, today)
        result["written"] += 1

    # ── Agent 3: Review flagged ───────────────────────────────────────────────
    result["agent3"]["status"] = "running"
    if check["flagged"]:
        try:
            reviewed = agent_review_anomalies(api_key, check["flagged"])
            result["agent3"]["status"] = "done"

            for item in reviewed:
                # Save anomaly to DB regardless of outcome
                _save_anomaly(
                    conn,
                    type_    = item.get("type","price"),
                    ticker   = item["ticker"],
                    exchange = item.get("exchange"),
                    currency = ticker_cur_map.get(item["ticker"], "KES"),
                    fetched  = item["new_price"],
                    previous = item.get("prev_price"),
                    pct      = item.get("pct_change"),
                    status   = item["status"],
                    reviewed = item.get("reviewed_value"),
                    note     = item.get("note",""),
                )

                if item["status"] in ("confirmed", "corrected"):
                    ticker = item["ticker"]
                    exch   = item.get("exchange", ticker_exch_map.get(ticker,"NSE"))
                    price  = item["reviewed_value"]
                    cur    = ticker_cur_map.get(ticker, "KES")
                    _upsert_global_price(conn, ticker, exch, price, cur, today)
                    result["written"] += 1
                    result["agent3"]["confirmed" if item["status"]=="confirmed" else "corrected"] += 1
                    result["anomalies"].append(item)
                else:
                    result["agent3"]["manual_review"] += 1
                    result["manual_review"].append(item)

        except Exception as e:
            result["agent3"]["status"] = "error"
            result["agent3"]["error"]  = str(e)
            result["errors"].append(f"Agent3 (review): {e}")
    else:
        result["agent3"]["status"] = "done"
        result["agent3"]["note"]   = "No anomalies to review"

    conn.commit()
    return result


def run_fx_pipeline(api_key, conn):
    """
    Full 3-agent FX pipeline.
    Returns result dict.
    """
    today = datetime.today().strftime("%Y-%m-%d")
    result = {
        "date":          today,
        "agent1":        {"status": "pending"},
        "agent2":        {"status": "pending"},
        "agent3":        {"status": "pending"},
        "written":       0,
        "anomalies":     [],
        "manual_review": [],
        "errors":        [],
    }

    # Agent 1: Fetch FX
    result["agent1"]["status"] = "running"
    try:
        new_fx = agent_fetch_fx(api_key)
        result["agent1"]["status"]   = "done"
        result["agent1"]["fetched"]  = len(new_fx)
        result["agent1"]["rates"]    = new_fx
    except Exception as e:
        result["agent1"]["status"] = "error"
        result["agent1"]["error"]  = str(e)
        result["errors"].append(f"Agent1 FX: {e}")
        return result

    # Agent 2: Check FX anomalies
    result["agent2"]["status"] = "running"
    try:
        prev_fx = _get_previous_fx(conn)
        check = agent_check_anomalies(
            new_fx, prev_fx, [], mode="fx")
        result["agent2"]["status"]  = "done"
        result["agent2"]["clean"]   = len(check["clean"])
        result["agent2"]["flagged"] = len(check["flagged"])
    except Exception as e:
        result["agent2"]["status"] = "error"
        result["errors"].append(f"Agent2 FX: {e}")
        return result

    # Write clean FX rates
    for currency, rate in check["clean"].items():
        _upsert_global_fx(conn, currency, rate, today)
        result["written"] += 1

    # Agent 3: Review FX anomalies
    result["agent3"]["status"] = "running"
    if check["flagged"]:
        try:
            reviewed = agent_review_anomalies(api_key, check["flagged"])
            result["agent3"]["status"] = "done"

            for item in reviewed:
                _save_anomaly(
                    conn,
                    type_    = "fx",
                    ticker   = item["ticker"],
                    exchange = "FX",
                    currency = item["ticker"],
                    fetched  = item["new_price"],
                    previous = item.get("prev_price"),
                    pct      = item.get("pct_change"),
                    status   = item["status"],
                    reviewed = item.get("reviewed_value"),
                    note     = item.get("note",""),
                )
                if item["status"] in ("confirmed","corrected"):
                    _upsert_global_fx(conn, item["ticker"], item["reviewed_value"], today)
                    result["written"] += 1
                    result["anomalies"].append(item)
                else:
                    result["manual_review"].append(item)

        except Exception as e:
            result["agent3"]["status"] = "error"
            result["errors"].append(f"Agent3 FX: {e}")
    else:
        result["agent3"]["status"] = "done"

    conn.commit()
    return result
