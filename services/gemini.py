"""
gemini.py — Gemini AI service.
- fetch_prices: get end-of-day prices for a list of tickers
- fetch_fx_rates: get current USD/GBP/EUR → KES exchange rates
- generate_review: weekly portfolio review with AI analysis
"""
import json
import os
import re
from datetime import datetime

try:
    import requests as _req
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash-001")
GEMINI_URL   = ("https://generativelanguage.googleapis.com/v1beta/models/"
                f"{GEMINI_MODEL}:generateContent")

# Exchange → default currency
_EXCUR = {
    "NSE": "KES", "NYSE": "USD", "NASDAQ": "USD",
    "LSE": "GBP", "JSE": "ZAR", "EURONEXT": "EUR",
    "HKEX": "HKD", "CRYPTO": "USD",
}


def _call(api_key, prompt, timeout=58):
    if not HAS_REQUESTS:
        raise RuntimeError("requests library not installed")
    resp = _req.post(
        f"{GEMINI_URL}?key={api_key}",
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "tools":    [{"google_search": {}}],
        },
        timeout=timeout
    )
    resp.raise_for_status()
    data = resp.json()
    return "".join(
        p.get("text", "")
        for p in data.get("candidates", [{}])[0]
                     .get("content", {}).get("parts", [])
    )


def _extract_json(text):
    """Robustly extract first JSON object/array — handles markdown fences."""
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


def _safe_currency(holding):
    """Get currency from holding with safe fallback."""
    cur = holding.get("currency")
    if cur and cur not in ("—", "", None):
        return cur
    return _EXCUR.get(holding.get("exchange", "NSE"), "KES")


# ── Price fetch ───────────────────────────────────────────────────────────────

def fetch_prices(api_key, tickers):
    """
    Fetch latest closing prices for a list of tickers.
    tickers: list of dicts with keys ticker, exchange
    Returns: {TICKER: price_float}
    """
    if not tickers:
        raise ValueError("No tickers provided")

    today  = datetime.today().strftime("%Y-%m-%d")
    ticker_list = ", ".join(
        f"{t['ticker']} on {t['exchange']}" for t in tickers)

    prompt = (
        f"Get the latest end-of-day closing stock prices for: {ticker_list}. "
        f"Today is {today}. Use Google Search for real-time data. "
        "Return ONLY raw JSON, no markdown, no code fences, no explanation. "
        'Format: {"TICKER": price_as_number}. '
        "NSE prices in KES, NYSE/NASDAQ in USD, LSE in GBP, JSE in ZAR, "
        "EURONEXT in EUR, CRYPTO in USD. Use the most recent available price."
    )
    text   = _call(api_key, prompt)
    prices = _extract_json(text)
    return {
        k.upper().strip(): float(v)
        for k, v in prices.items()
        if isinstance(v, (int, float)) and float(v) > 0
    }


# ── FX rate fetch ─────────────────────────────────────────────────────────────

def fetch_fx_rates(api_key):
    """
    Fetch current exchange rates to KES for major currencies.
    Returns: {"USD": 129.5, "GBP": 164.2, "EUR": 140.1, "ZAR": 7.1, ...}
    """
    today  = datetime.today().strftime("%Y-%m-%d")
    prompt = (
        f"Get the current exchange rates to Kenyan Shillings (KES) as of {today}. "
        "Use Google Search for live forex data. "
        "Return ONLY raw JSON, no markdown, no code fences, no explanation. "
        'Format: {"USD": rate, "GBP": rate, "EUR": rate, "ZAR": rate, '
        '"TZS": rate, "UGX": rate, "GHS": rate, "HKD": rate} '
        "where each rate is how many KES you get for 1 unit of that currency."
    )
    text  = _call(api_key, prompt)
    rates = _extract_json(text)
    result = {}
    for currency, rate in rates.items():
        try:
            r = float(rate)
            if r > 0:
                result[currency.upper()] = r
        except (ValueError, TypeError):
            pass
    result["KES"] = 1.0  # KES to KES is always 1
    return result


# ── Portfolio review ──────────────────────────────────────────────────────────

def generate_review(api_key, portfolio, savings):
    today = datetime.today().strftime("%Y-%m-%d")

    holds = "\n".join(
        "  {ticker} ({exchange}): {shares} shares, avg {cur} {avg:.2f}{market}".format(
            ticker   = h["ticker"],
            exchange = h["exchange"],
            shares   = h.get("total_shares", 0),
            cur      = _safe_currency(h),
            avg      = float(h.get("avg_cost", 0) or 0),
            market   = (
                f", mkt {_safe_currency(h)} {h['market_price']}, "
                f"{h['pct_return']}% return"
                if h.get("market_price") else ""
            ),
        )
        for h in portfolio.get("holdings", [])
    ) or "  No holdings"

    savs = "\n".join(
        f"  {k}: KES {v:,.0f}"
        for k, v in (savings or {}).items()
    ) or "  None"

    total_cost   = float(portfolio.get("total_cost",    0) or 0)
    total_market = float(portfolio.get("total_market",  0) or 0)
    pct          = float(portfolio.get("portfolio_pct", 0) or 0)

    prompt = (
        f"You are a financial advisor. Today is {today} (Friday).\n"
        f"Conduct a weekly portfolio review for this investor.\n\n"
        f"STOCK HOLDINGS:\n{holds}\n\n"
        f"OTHER ASSETS:\n{savs}\n\n"
        f"Stock cost basis: {total_cost:,.0f}, "
        f"market value: {total_market:,.0f}, "
        f"return: {pct:.1f}%\n\n"
        "Use Google Search for current market data, news, and prices.\n"
        "Return ONLY a JSON object — no markdown, no code fences:\n"
        '{"week_summary":"one punchy headline",'
        '"overall_rating":"STRONG|GOOD|NEUTRAL|CAUTION|REVIEW",'
        '"performance_summary":"2-3 sentences on portfolio health",'
        '"stock_analysis":[{"ticker":"","exchange":"","signal":"BUY|HOLD|TRIM|SELL",'
        '"reasoning":""}],'
        '"dividend_calendar":[{"ticker":"","exchange":"","expected_date":"",'
        '"estimated_yield":"","notes":""}],'
        '"add_recommendations":[{"asset":"","reason":"","action":"",'
        '"priority":"HIGH|MEDIUM|LOW"}],'
        '"trim_recommendations":[{"asset":"","reason":"","action":"",'
        '"priority":"HIGH|MEDIUM|LOW"}],'
        '"watchlist":[{"ticker":"","exchange":"","reason":"","entry_range":"",'
        '"thesis":""}],'
        '"fx_note":"brief comment on USD/KES and impact on non-KES holdings"}'
    )
    text = _call(api_key, prompt, timeout=58)
    return _extract_json(text)
