"""
gemini.py — Gemini AI service.

Public API:
  fetch_prices(api_key, tickers)        → {TICKER: price_float}
  fetch_fx_rates(api_key)               → {currency: kes_rate_float}
  generate_review(api_key, portfolio, savings) → dict
"""

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

try:
    import requests as _req
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# ── Config ────────────────────────────────────────────────────────────────────

GEMINI_URL  = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.0-flash:generateContent"
)

_BATCH_SIZE  = 6    # tickers per Gemini call — sweet spot for search grounding
_MAX_WORKERS = 3    # parallel Gemini calls
_TIMEOUT     = 120   # seconds per call (main)
_RETRY_TIMEOUT = 30 # seconds per call (retry pass)

# Exchange → default currency
_EXCUR = {
    "NSE":      "KES",
    "NYSE":     "USD",
    "NASDAQ":   "USD",
    "LSE":      "GBP",
    "JSE":      "ZAR",
    "EURONEXT": "EUR",
    "HKEX":     "HKD",
    "CRYPTO":   "USD",
}

# ── Internal helpers ──────────────────────────────────────────────────────────

def _call(api_key: str, prompt: str, timeout: int = _TIMEOUT) -> str:
    """POST to Gemini with Google Search grounding. Returns raw text."""
    if not HAS_REQUESTS:
        raise RuntimeError("requests library not installed")
    resp = _req.post(
        f"{GEMINI_URL}?key={api_key}",
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "tools":    [{"google_search": {}}],
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    return "".join(
        p.get("text", "")
        for p in data.get("candidates", [{}])[0]
                     .get("content", {})
                     .get("parts", [])
    )


def _extract_json(text: str):
    """
    Robustly extract the first JSON object or array from a string.
    Handles markdown fences and nested braces/brackets.
    """
    text = re.sub(r"```(?:json)?", "", text).strip()
    for start_char, end_char in [('{', '}'), ('[', ']')]:
        start = text.find(start_char)
        if start == -1:
            continue
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == start_char:
                depth += 1
            elif ch == end_char:
                depth -= 1
                if depth == 0:
                    return json.loads(text[start:i + 1])
    raise ValueError(f"No JSON found in Gemini response: {text[:400]}")


def _safe_currency(holding: dict) -> str:
    """Return currency string from a holding dict with safe fallback."""
    cur = holding.get("currency")
    if cur and cur not in ("—", "", None):
        return cur
    return _EXCUR.get(holding.get("exchange", "NSE"), "KES")


# ── Price fetch (batched + multithreaded) ─────────────────────────────────────

def _fetch_batch(api_key: str, batch: list, today: str) -> dict:
    """
    Fetch prices for a single batch of tickers.
    Called in a thread — returns {TICKER: price_float} for the batch.
    Raises on complete failure so the caller can track missing tickers.
    """
    ticker_list = ", ".join(
        f"{t['ticker']} on {t['exchange']}" for t in batch
    )
    prompt = (
        f"Get the latest end-of-day closing stock prices for EVERY one of "
        f"these tickers: {ticker_list}. "
        f"Today is {today}. Use Google Search for real-time data. "
        "You MUST return a price for EVERY ticker listed — use the most "
        "recent available price if today's close isn't out yet. "
        "Return ONLY raw JSON — no markdown, no code fences, no explanation. "
        'Format: {"TICKER": price_as_number}. '
        "NSE prices in KES, NYSE/NASDAQ in USD, LSE in GBP, "
        "JSE in ZAR, EURONEXT in EUR, CRYPTO in USD."
    )
    text   = _call(api_key, prompt, timeout=_TIMEOUT)
    prices = _extract_json(text)
    return {
        k.upper().strip(): float(v)
        for k, v in prices.items()
        if isinstance(v, (int, float)) and float(v) > 0
    }


def _retry_single(api_key: str, ticker: dict, today: str) -> tuple[str, float | None]:
    """
    Retry a single ticker that was missed in batch pass.
    Returns (TICKER, price) or (TICKER, None) on failure.
    """
    t, ex = ticker["ticker"], ticker["exchange"]
    prompt = (
        f"What is the latest closing price of {t} listed on {ex}? "
        f"Today is {today}. Use Google Search. "
        "Return ONLY raw JSON — no markdown, no explanation. "
        f'Format: {{"{t}": price_as_number}}'
    )
    try:
        text  = _call(api_key, prompt, timeout=_RETRY_TIMEOUT)
        price = _extract_json(text)
        val   = price.get(t) or price.get(t.upper())
        if val and float(val) > 0:
            return t.upper(), float(val)
    except Exception as e:
        print(f"[gemini] Retry failed for {t}: {e}", flush=True)
    return t.upper(), None


def fetch_prices(api_key: str, tickers: list[dict]) -> dict:
    """
    Fetch latest closing prices for all provided tickers.

    Strategy:
      Pass 1 — split into batches of _BATCH_SIZE, run _MAX_WORKERS in parallel.
      Pass 2 — retry any tickers not returned in pass 1, one thread each.

    Args:
        api_key:  Gemini API key
        tickers:  list of {"ticker": "SCOM", "exchange": "NSE"} dicts

    Returns:
        {"SCOM": 131.0, "AAPL": 193.5, ...}
    """
    if not tickers:
        raise ValueError("No tickers provided")

    today   = datetime.today().strftime("%Y-%m-%d")
    results = {}                    # final merged prices
    missing = []                    # tickers not returned in pass 1
    lock    = threading.Lock()      # guard shared dicts across threads

    # ── Pass 1: parallel batch fetch ─────────────────────────────────────────
    batches = [
        tickers[i: i + _BATCH_SIZE]
        for i in range(0, len(tickers), _BATCH_SIZE)
    ]

    print(
        f"[gemini] Fetching {len(tickers)} tickers in "
        f"{len(batches)} batches × {_MAX_WORKERS} workers",
        flush=True,
    )

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
        future_to_batch = {
            executor.submit(_fetch_batch, api_key, batch, today): batch
            for batch in batches
        }

        for future in as_completed(future_to_batch):
            batch = future_to_batch[future]
            try:
                batch_result = future.result()
                with lock:
                    results.update(batch_result)

                # Detect which tickers in this batch were NOT returned
                for t in batch:
                    if t["ticker"].upper() not in batch_result:
                        with lock:
                            missing.append(t)
                        print(
                            f"[gemini] Pass-1 miss: {t['ticker']} "
                            f"(batch returned {list(batch_result.keys())})",
                            flush=True,
                        )
                    else:
                        print(
                            f"[gemini] ✓ {t['ticker']} = "
                            f"{batch_result[t['ticker'].upper()]}",
                            flush=True,
                        )

            except Exception as e:
                print(
                    f"[gemini] Batch failed "
                    f"({[t['ticker'] for t in batch]}): {e}",
                    flush=True,
                )
                with lock:
                    missing.extend(batch)

    # ── Pass 2: parallel retry for missed tickers ─────────────────────────────
    if missing:
        print(
            f"[gemini] Pass-2 retrying {len(missing)} missed tickers: "
            f"{[t['ticker'] for t in missing]}",
            flush=True,
        )
        retry_workers = min(len(missing), _MAX_WORKERS)
        with ThreadPoolExecutor(max_workers=retry_workers) as executor:
            retry_futures = {
                executor.submit(_retry_single, api_key, t, today): t
                for t in missing
            }
            for future in as_completed(retry_futures):
                ticker_sym, price = future.result()
                if price is not None:
                    results[ticker_sym] = price
                    print(
                        f"[gemini] ✓ Retry {ticker_sym} = {price}",
                        flush=True,
                    )
                else:
                    print(
                        f"[gemini] ✗ Could not fetch {ticker_sym} after retry",
                        flush=True,
                    )

    print(
        f"[gemini] Done — {len(results)}/{len(tickers)} prices fetched",
        flush=True,
    )
    return results


# ── FX rate fetch ─────────────────────────────────────────────────────────────

def fetch_fx_rates(api_key: str) -> dict:
    """
    Fetch current exchange rates to KES for major currencies.

    Returns:
        {"USD": 129.5, "GBP": 164.2, "EUR": 140.1, "ZAR": 7.1, ...}
    """
    today  = datetime.today().strftime("%Y-%m-%d")
    prompt = (
        f"Get the current exchange rates to Kenyan Shillings (KES) as of {today}. "
        "Use Google Search for live forex data. "
        "Return ONLY raw JSON — no markdown, no code fences, no explanation. "
        'Format: {"USD": rate, "GBP": rate, "EUR": rate, "ZAR": rate, '
        '"TZS": rate, "UGX": rate, "GHS": rate, "HKD": rate} '
        "where each value is how many KES you get for 1 unit of that currency."
    )
    text  = _call(api_key, prompt, timeout=_TIMEOUT)
    rates = _extract_json(text)
    return {
        k.upper().strip(): float(v)
        for k, v in rates.items()
        if isinstance(v, (int, float)) and float(v) > 0
    }


# ── Weekly portfolio review ───────────────────────────────────────────────────

def generate_review(api_key: str, portfolio: dict, savings: dict) -> dict:
    """
    Generate an AI-powered weekly portfolio review via Gemini.

    Args:
        api_key:   Gemini API key
        portfolio: dict with keys: holdings (list), total_cost, total_market,
                   portfolio_pct
        savings:   dict of {label: kes_amount}

    Returns:
        Parsed JSON dict with week_summary, overall_rating, stock_analysis, etc.
    """
    today = datetime.today().strftime("%Y-%m-%d")

    holds = "\n".join(
        f"  {h['ticker']} ({h['exchange']}): {h['total_shares']} shares, "
        f"avg {_safe_currency(h)} {h['avg_cost']:.2f}"
        + (
            f", mkt {_safe_currency(h)} {h['market_price']}, "
            f"{h['pct_return']}% return"
            if h.get("market_price")
            else ""
        )
        for h in portfolio.get("holdings", [])
    ) or "  None"

    savs = (
        "\n".join(f"  {k}: KES {v:,.0f}" for k, v in savings.items())
        or "  None"
    )

    prompt = (
        f"You are a financial advisor conducting a Friday portfolio review. "
        f"Today is {today}.\n\n"
        f"STOCK HOLDINGS:\n{holds}\n\n"
        f"OTHER ASSETS:\n{savs}\n\n"
        f"Stock cost basis: {portfolio.get('total_cost', 0):,.0f} KES, "
        f"market value: {portfolio.get('total_market', 0):,.0f} KES, "
        f"return: {portfolio.get('portfolio_pct', 0):.1f}%\n\n"
        "Use Google Search for current market data, news, and prices.\n"
        "Return ONLY a JSON object — no markdown, no code fences:\n"
        '{'
        '"week_summary": "one punchy headline",'
        '"overall_rating": "STRONG|GOOD|NEUTRAL|CAUTION|REVIEW",'
        '"performance_summary": "2-3 sentences on portfolio health",'
        '"stock_analysis": [{"ticker":"","exchange":"","signal":"BUY|HOLD|TRIM|SELL","reasoning":""}],'
        '"dividend_calendar": [{"ticker":"","exchange":"","expected_date":"","estimated_yield":"","amount_hint":"","notes":""}],'
        '"add_recommendations": [{"asset":"","reason":"","action":"","priority":"HIGH|MEDIUM|LOW"}],'
        '"trim_recommendations": [{"asset":"","reason":"","action":"","priority":"HIGH|MEDIUM|LOW"}],'
        '"watchlist": [{"ticker":"","exchange":"","reason":"","entry_range":"","thesis":""}],'
        '"fx_note": "brief comment on USD/KES rate and impact on non-KES holdings"'
        '}'
    )
    text = _call(api_key, prompt, timeout=60)
    return _extract_json(text)
