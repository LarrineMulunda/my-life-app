"""Gemini AI service — price fetch and portfolio review."""
import json, re
from datetime import datetime

try:
    import requests as _req
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

GEMINI_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
              "gemini-2.0-flash:generateContent")

def _call(api_key, prompt, timeout=50):
    if not HAS_REQUESTS:
        raise RuntimeError("requests library not installed")
    resp = _req.post(
        f"{GEMINI_URL}?key={api_key}",
        json={"contents": [{"parts": [{"text": prompt}]}],
              "tools": [{"google_search": {}}]},
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
    """Robustly extract first JSON object/array — handles nesting (fixes v4 regex bug)."""
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
                    return json.loads(text[start:i+1])
    raise ValueError(f"No JSON found in: {text[:300]}")

def fetch_prices(api_key, tickers):
    today = datetime.today().strftime("%Y-%m-%d")
    s = ", ".join(f"{t['ticker']} on {t['exchange']}" for t in tickers)
    prompt = (
        f"Get the latest end-of-day closing stock prices for: {s}. Today is {today}. "
        "Return ONLY raw JSON, no markdown, no fences. "
        'Format: {"TICKER": price_number}. '
        "NSE→KES, NYSE/NASDAQ→USD, LSE→GBP, JSE→ZAR, EURONEXT→EUR."
    )
    text = _call(api_key, prompt)
    prices = _extract_json(text)
    return {k.upper().strip(): v for k, v in prices.items()
            if isinstance(v, (int, float)) and v > 0}

def generate_review(api_key, portfolio, savings):
    today = datetime.today().strftime("%Y-%m-%d")
    holds = "\n".join(
        f"  {h['ticker']} ({h['exchange']}): {h['total_shares']} shares, "
        f"avg {h['currency']} {h['avg_cost']:.2f}"
        + (f", mkt {h['currency']} {h['market_price']}, {h['pct_return']}% return"
           if h.get('market_price') else "")
        for h in portfolio.get("holdings", [])
    ) or "  None"
    savs = "\n".join(f"  {k}: KES {v:,.0f}" for k, v in savings.items()) or "  None"
    prompt = (
        f"Financial advisor, Friday portfolio review, today {today}.\n"
        f"STOCKS:\n{holds}\n"
        f"OTHER ASSETS:\n{savs}\n"
        f"Stock cost {portfolio.get('total_cost',0):,.0f}, "
        f"market {portfolio.get('total_market',0):,.0f}, "
        f"return {portfolio.get('portfolio_pct',0)}%\n\n"
        "Return ONLY JSON (no markdown):\n"
        '{"week_summary":"headline","overall_rating":"STRONG|GOOD|NEUTRAL|CAUTION|REVIEW",'
        '"performance_summary":"2-3 sentences",'
        '"stock_analysis":[{"ticker":"","exchange":"","signal":"BUY|HOLD|TRIM|SELL","reasoning":""}],'
        '"dividend_calendar":[{"ticker":"","exchange":"","expected_date":"","estimated_yield":"","amount_hint":"","notes":""}],'
        '"add_recommendations":[{"asset":"","reason":"","action":"","priority":"HIGH|MEDIUM|LOW"}],'
        '"trim_recommendations":[{"asset":"","reason":"","action":"","priority":"HIGH|MEDIUM|LOW"}],'
        '"watchlist":[{"ticker":"","exchange":"","reason":"","entry_range":"","thesis":""}]}'
    )
    text = _call(api_key, prompt, timeout=60)
    return _extract_json(text)
