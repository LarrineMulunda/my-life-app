"""
services/agents.py — 7-Agent Agentic Portfolio Review Pipeline.

Agents run with individual Gemini calls (Google Search grounded).
Agents 1-5 run in parallel threads. Agent 6 (Verifier) waits for all.
Agent 7 (Summary) runs last.

Job progress is written to the review_jobs DB table so the UI can poll it live.
"""
import json
import uuid
import threading
from datetime import datetime

try:
    import requests as _req
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

GEMINI_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
              "gemini-2.0-flash:generateContent")

AGENTS = [
    {
        "id":   "performance",
        "num":  1,
        "name": "Performance Analyst",
        "icon": "📊",
        "desc": "Analyses portfolio metrics, returns, winners and losers",
    },
    {
        "id":   "rebalancing",
        "num":  2,
        "name": "Rebalancing Advisor",
        "icon": "⚖️",
        "desc": "Reviews allocation and recommends rebalancing actions",
    },
    {
        "id":   "analyst",
        "num":  3,
        "name": "Analyst Intelligence",
        "icon": "🔍",
        "desc": "Fetches latest analyst ratings, price targets and hot picks",
    },
    {
        "id":   "thematic",
        "num":  4,
        "name": "Thematic Researcher",
        "icon": "🌐",
        "desc": "Identifies 10–30 year megatrends and thematic opportunities",
    },
    {
        "id":   "corporate",
        "num":  5,
        "name": "Corporate Actions",
        "icon": "📅",
        "desc": "Upcoming dividends, earnings, splits — future-dated only",
    },
    {
        "id":   "dividend",
        "num":  6,
        "name": "Dividend Intelligence",
        "icon": "💰",
        "desc": "YTD dividends received + full-year income projection",
    },
    {
        "id":   "health",
        "num":  7,
        "name": "Portfolio Health",
        "icon": "🏥",
        "desc": "Sharpe ratio, stress tests, risk metrics across all asset classes",
    },
    {
        "id":   "verifier",
        "num":  8,
        "name": "Fact Verifier",
        "icon": "✅",
        "desc": "Cross-checks all findings for accuracy — HIGH confidence only",
    },
    {
        "id":   "summary",
        "num":  9,
        "name": "Executive Summary",
        "icon": "✦",
        "desc": "Synthesises all insights into badges, actions, watchlist",
    },
]


# ── Gemini call ───────────────────────────────────────────────────────────────

def _gemini(api_key, prompt, timeout=90, retries=3):
    """Call Gemini with exponential back-off retry on rate-limit / server errors."""
    import time
    if not HAS_REQUESTS:
        raise RuntimeError("requests not installed")
    last_err = None
    for attempt in range(retries):
        try:
            resp = _req.post(
                f"{GEMINI_URL}?key={api_key}",
                json={
                    "contents":         [{"parts": [{"text": prompt}]}],
                    "tools":            [{"google_search": {}}],
                    "generationConfig": {"temperature": 0.3},
                },
                timeout=timeout,
            )
            # 429 = rate limit, 500/503 = server error → retry
            if resp.status_code in (429, 500, 503):
                wait = 2 ** attempt * 5  # 5s, 10s, 20s
                time.sleep(wait)
                last_err = f"HTTP {resp.status_code}"
                continue
            resp.raise_for_status()
            data = resp.json()
            return "".join(
                p.get("text", "")
                for p in data.get("candidates", [{}])[0]
                             .get("content", {}).get("parts", [])
            )
        except Exception as e:
            last_err = str(e)
            if attempt < retries - 1:
                time.sleep(2 ** attempt * 3)  # 3s, 6s
    raise RuntimeError(f"Gemini failed after {retries} attempts: {last_err}")

def _extract_json(text):
    import re
    text = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
    for s, e in [('{', '}'), ('[', ']')]:
        start = text.find(s)
        if start == -1:
            continue
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == s: depth += 1
            elif ch == e:
                depth -= 1
                if depth == 0:
                    return json.loads(text[start:i + 1])
    raise ValueError(f"No JSON in response: {text[:300]}")


# ── Portfolio context builder ─────────────────────────────────────────────────

def _portfolio_context(portfolio, savings):
    today = datetime.today().strftime("%Y-%m-%d")
    holds = []
    for h in portfolio.get("holdings", []):
        cur = h.get("currency", "KES")
        has_price = h.get("market_price") is not None
        holds.append(
            f"  {h['ticker']} ({h['exchange']}/{cur}): "
            f"{h.get('total_shares',0)} shares, "
            f"avg cost {cur} {h.get('avg_cost',0):.2f}"
            + (f", mkt price {cur} {h['market_price']:.2f}, "
               f"return {h.get('pct_return',0):.1f}%" if has_price else ", no price data")
        )

    # Support both old {class:val} format and new {totals, entries} format
    if isinstance(savings, dict) and "totals" in savings:
        sav_totals  = savings.get("totals", {})
        sav_entries = savings.get("entries", [])
    else:
        sav_totals  = savings or {}
        sav_entries = []

    sav_lines = [f"  {k}: KES {v:,.0f}" for k, v in sav_totals.items()]

    # Build detailed other-assets section grouped by class
    detail_lines = []
    grouped = {}
    for e in sav_entries:
        grouped.setdefault(e["asset_class"], []).append(e)
    for cls, entries in grouped.items():
        net = sum(e["amount_kes"] for e in entries)
        labels = list({e["label"] for e in entries if e["label"]})
        detail_lines.append(f"  {cls}: KES {net:,.0f}" +
                           (f" ({', '.join(labels)})" if labels else ""))

    return (
        f"Today: {today}\n"
        f"Stock portfolio cost:  KES {portfolio.get('total_cost',0):,.0f}\n"
        f"Stock market value:    KES {portfolio.get('total_market',0):,.0f}\n"
        f"Unrealised gain/loss:  KES {portfolio.get('total_gain',0):,.0f} "
        f"({portfolio.get('portfolio_pct',0):.1f}%)\n"
        f"Realised gains:        KES {portfolio.get('total_realized',0):,.0f}\n\n"
        f"STOCK HOLDINGS ({len(holds)}):\n" + "\n".join(holds) + "\n\n"
        f"OTHER ASSETS (bonds, MMF, farming etc):\n" +
        ("\n".join(detail_lines) or "  None")
    )


# ── Agent prompt builders ─────────────────────────────────────────────────────

def _prompt_performance(ctx):
    today = datetime.today().strftime("%Y-%m-%d")
    return f"""You are an expert portfolio performance analyst. Today is {today}.
Analyse this Kenyan investor's portfolio and provide a comprehensive performance summary with health scoring.

{ctx}

Use Google Search to verify current prices and market context.

Portfolio Health Score: Rate 0-100 based on:
- Diversification (20pts): spread across sectors/geographies
- Return quality (20pts): risk-adjusted returns
- Momentum (20pts): recent price trends
- Income (20pts): dividend yield and coverage
- Risk (20pts): concentration risk, volatility

Return ONLY valid JSON (no markdown, no code fences):
{{
  "week_summary": "one punchy headline",
  "overall_rating": "STRONG|GOOD|NEUTRAL|CAUTION|REVIEW",
  "health_score": 0,
  "health_breakdown": {{
    "diversification": 0,
    "return_quality": 0,
    "momentum": 0,
    "income": 0,
    "risk": 0
  }},
  "health_commentary": "2 sentence plain-English explanation of the score",
  "portfolio_health": "2-3 sentence overall assessment",
  "top_performers": [{{"ticker":"","exchange":"","return_pct":0,"note":""}}],
  "underperformers": [{{"ticker":"","exchange":"","return_pct":0,"note":""}}],
  "sector_breakdown": [{{"sector":"","allocation_pct":0,"comment":""}}],
  "dividend_intelligence": {{
    "annual_income_estimate_kes": 0,
    "portfolio_yield_pct": 0,
    "next_dividends": [
      {{"ticker":"","exchange":"","ex_date":"YYYY-MM-DD","payment_date":"YYYY-MM-DD",
        "estimated_amount":"","currency":"","yield_pct":0,"confidence":"HIGH|MEDIUM|LOW"}}
    ],
    "commentary": "1-2 sentences on income outlook"
  }},
  "key_metrics": {{
    "total_return_pct": 0,
    "best_single_position": "",
    "worst_single_position": "",
    "largest_position": "",
    "diversification_score": "LOW|MEDIUM|HIGH"
  }},
  "performance_commentary": "detailed 3-5 sentence commentary"
}}"""


def _prompt_rebalancing(ctx):
    return f"""You are an expert portfolio strategist specialising in rebalancing for Kenyan and African investors.
Today is {datetime.today().strftime('%Y-%m-%d')}.

Analyse this portfolio for concentration risk, over/under-weight positions, and asset class balance.
Consider the investor's context: Kenyan-based, holdings across NSE, NYSE, NASDAQ, LSE, CRYPTO.

{ctx}

Return ONLY valid JSON (no markdown, no code fences):
{{
  "overall_balance": "WELL_BALANCED|SLIGHTLY_CONCENTRATED|CONCENTRATED|HIGHLY_CONCENTRATED",
  "concentration_risks": [{{"ticker":"","exchange":"","issue":"","severity":"HIGH|MEDIUM|LOW"}}],
  "overweight_positions": [{{"ticker":"","exchange":"","current_pct":0,"suggested_pct":0,"action":""}}],
  "underweight_areas": [{{"asset_class_or_sector":"","rationale":"","suggestion":""}}],
  "rebalancing_actions": [
    {{
      "priority": "HIGH|MEDIUM|LOW",
      "action": "BUY|SELL|TRIM|ADD",
      "ticker": "",
      "exchange": "",
      "rationale": "",
      "suggested_amount_pct": 0,
      "trim_pct": 0,
      "trim_shares_approx": 0,
      "trim_value_kes_approx": 0,
      "notes": ""
    }}
  ],
  "ideal_allocation": [{{"category":"","target_pct":0,"current_pct":0}}],
  "rebalancing_summary": "2-3 sentence actionable summary"
}}"""


def _prompt_analyst(tickers_str):
    today = datetime.today().strftime("%Y-%m-%d")
    return f"""You are a senior equity research analyst. Today is {today}.

For the following stocks and ETFs: {tickers_str}

Use Google Search to query MULTIPLE independent sources — include at least:
Goldman Sachs, Morgan Stanley, JPMorgan, Bank of America, Citi, UBS, Barclays,
and independent platforms like TipRanks, Seeking Alpha, MarketBeat, Zacks, Reuters.

Find for each held ticker:
1. Analyst consensus ratings from at least 3 different firms
2. Price targets from different analysts (show the range, not just average)
3. Recent upgrades or downgrades (last 30 days)

ONLY include a ticker in analyst_views if it has BOTH a clear consensus AND a key thesis.
ONLY include hot_picks that have a clear thesis — maximum 4 picks total from DIFFERENT sources.

Return ONLY valid JSON (no markdown, no code fences):
{{
  "analyst_views": [
    {{
      "ticker":"","exchange":"","consensus":"BUY|HOLD|SELL|MIXED",
      "num_analysts":0,
      "avg_price_target":"","target_range":"low-high",
      "upside_pct":0,
      "sources":["firm1","firm2","firm3"],
      "recent_changes":[{{"analyst":"","firm":"","action":"UPGRADE|DOWNGRADE|INITIATE","date":"","target":""}}],
      "key_thesis":"must be present - skip ticker if no clear thesis"
    }}
  ],
  "hot_picks": [
    {{
      "ticker":"","exchange":"","source":"name of analyst/publication",
      "rating":"","price_target":"",
      "thesis":"must be specific and detailed - omit if vague",
      "catalyst":"near-term catalyst",
      "alternative_view":"what bears say"
    }}
  ],
  "sector_sentiment": [{{"sector":"","sentiment":"BULLISH|NEUTRAL|BEARISH","note":"","sources":[""]}}],
  "market_context": "2-3 sentences on current market relevant to this portfolio"
}}"""


def _prompt_thematic(ctx):
    return f"""You are a forward-looking thematic investment researcher. Today is {datetime.today().strftime('%Y-%m-%d')}.

This Kenyan investor's current portfolio:
{ctx}

Use Google Search to identify the most compelling investment MEGATRENDS over the next 10-30 years.
Consider: AI, energy transition, water scarcity, Africa growth story, demographics, 
defence, space, genomics, infrastructure, de-dollarisation, climate adaptation.

Focus on instruments accessible to a Kenyan investor (NYSE, NASDAQ, LSE ETFs/stocks, NSE).

Return ONLY valid JSON (no markdown, no code fences):
{{
  "megatrends": [
    {{
      "theme": "",
      "horizon": "10yr|20yr|30yr",
      "conviction": "HIGH|MEDIUM|LOW",
      "rationale": "",
      "current_exposure": "NONE|LOW|ADEQUATE|HIGH",
      "current_exposure_pct": 0,
      "current_holdings_in_theme": ["ticker1","ticker2"],
      "exposure_commentary": "1 sentence on current vs ideal exposure",
      "target_allocation_pct": 0,
      "instruments": [
        {{"ticker":"","exchange":"","type":"stock|etf","why":"","entry_note":""}}
      ],
      "recommended_etfs": [
        {{
          "ticker":   "",
          "exchange": "NYSE|NASDAQ|LSE|JSE",
          "name":     "Full ETF name",
          "ter_pct":  0,
          "aum_usd_bn":0,
          "why":      "why this ETF gives best exposure to this theme",
          "kenya_accessible": true
        }}
      ]
    }}
  ],
  "africa_specific": [
    {{
      "opportunity":"",
      "rationale":"",
      "current_exposure":"NONE|LOW|ADEQUATE|HIGH",
      "instruments":[{{"ticker":"","exchange":"","note":""}}],
      "recommended_etfs":[{{"ticker":"","exchange":"","name":"","why":""}}]
    }}
  ],
  "exposure_radar": [
    {{"theme":"","current_pct":0,"target_pct":0,"status":"OVERWEIGHT|ON_TARGET|UNDERWEIGHT|MISSING"}}
  ],
  "gaps_in_portfolio": ["list gaps vs megatrend exposure"],
  "thematic_summary": "2-3 sentence forward-looking outlook"
}}"""


def _prompt_corporate(tickers_str):
    today = datetime.today().strftime("%Y-%m-%d")
    return f"""You are a corporate actions specialist. Today is {today}.

For the following tickers: {tickers_str}

Use Google Search to find FUTURE events only (today or later — exclude past events):
1. Upcoming ex-dividend dates and payment dates (FUTURE only, not past)
2. Upcoming earnings release dates (FUTURE only)
3. Announced stock splits or rights issues (FUTURE settlement dates)
4. M&A activity, delistings, or major announcements with future effective dates
5. NSE-specific: upcoming AGMs, dividend declarations, rights offers

CRITICAL: Only include items with dates >= {today}. Remove any past events.

Return ONLY valid JSON (no markdown, no code fences):
{{
  "dividends": [
    {{
      "ticker":"","exchange":"","declared_amount":"","currency":"",
      "ex_date":"YYYY-MM-DD — must be >= {today}",
      "payment_date":"YYYY-MM-DD — must be >= {today}",
      "type":"interim|final|special","yield_pct":0
    }}
  ],
  "earnings": [
    {{
      "ticker":"","exchange":"",
      "expected_date":"YYYY-MM-DD — must be >= {today}",
      "period":"","consensus_eps":"","note":""
    }}
  ],
  "corporate_actions": [
    {{
      "ticker":"","exchange":"","action_type":"split|rights|merger|delisting|other",
      "details":"","date":"YYYY-MM-DD — must be >= {today}","impact":""
    }}
  ],
  "nse_specific": [
    {{"ticker":"","action":"","date":"YYYY-MM-DD — must be >= {today}","details":""}}
  ],
  "key_dates_next_30_days": [
    {{"date":"YYYY-MM-DD","ticker":"","event":"","importance":"HIGH|MEDIUM|LOW"}}
  ]
}}"""



def _prompt_dividend(ctx, portfolio, savings=None):
    """Dividend intelligence: earned YTD, expected this year, yield analysis."""
    today = datetime.today().strftime("%Y-%m-%d")
    year  = datetime.today().year
    # Build dividend-relevant holding summary
    holds = []
    for h in portfolio.get("holdings", []):
        if h.get("total_shares", 0) > 0:
            holds.append(
                f"  {h['ticker']} ({h['exchange']}): "
                f"{h['total_shares']} shares @ {h.get('market_price','?')} {h.get('currency','KES')}"
            )
    holdings_str = "\n".join(holds) or "  No holdings"

    # Include MMF/bond income from savings
    if isinstance(savings, dict) and "totals" in savings:
        sav_totals  = savings.get("totals", {})
        sav_entries = savings.get("entries", [])
    else:
        sav_totals  = savings or {}
        sav_entries = []

    mmf_detail  = [e for e in sav_entries if "mmf" in e.get("asset_class","").lower() or "trust" in e.get("asset_class","").lower()]
    bond_detail = [e for e in sav_entries if "bond" in e.get("asset_class","").lower() or "bill" in e.get("asset_class","").lower()]

    sep = chr(10)
    mmf_str  = sep.join(f"  {e['label']}: KES {e['amount_kes']:,.0f}" for e in mmf_detail) or "  None"
    bond_str = sep.join(f"  {e['label']}: KES {e['amount_kes']:,.0f}" for e in bond_detail) or "  None"


    return f"""You are a dividend and income analyst. Today is {today}.

This investor holds the following stock positions:
{holdings_str}

MMF / Unit Trusts (generate daily interest):
{mmf_str}

Bonds / T-Bills (generate coupon/interest income):
{bond_str}

Portfolio total market value: KES {portfolio.get('total_market', 0):,.0f}

Use Google Search to research:
1. Dividend history for each stock holding
2. Current MMF rates in Kenya for each MMF held
3. T-bill/bond coupon rates

Calculate:
1. Dividends actually RECEIVED so far in {year} (based on ex-dates already passed)
2. Expected dividends remaining in {year} (ex-dates still ahead)
3. Total projected annual income for {year}

NSE dividends in KES, NYSE/NASDAQ in USD (then convert to KES at current rates).

Return ONLY valid JSON (no markdown, no code fences):
{{
  "ytd_received": [
    {{
      "ticker": "",
      "exchange": "",
      "currency": "",
      "amount_per_share": 0,
      "shares_held": 0,
      "total_received": 0,
      "total_kes": 0,
      "ex_date": "YYYY-MM-DD",
      "pay_date": "YYYY-MM-DD",
      "type": "interim|final|special"
    }}
  ],
  "expected_remaining": [
    {{
      "ticker": "",
      "exchange": "",
      "currency": "",
      "estimated_per_share": 0,
      "shares_held": 0,
      "total_expected": 0,
      "total_kes_expected": 0,
      "expected_ex_date": "YYYY-MM-DD",
      "confidence": "HIGH|MEDIUM|LOW"
    }}
  ],
  "summary": {{
    "ytd_income_kes": 0,
    "expected_remaining_kes": 0,
    "projected_annual_kes": 0,
    "portfolio_yield_pct": 0,
    "top_income_ticker": "",
    "dividend_growth_trend": "GROWING|STABLE|DECLINING|MIXED",
    "income_commentary": "2-3 sentences on dividend income outlook"
  }},
  "non_dividend_holdings": ["list tickers that pay no dividend"]
}}"""


def _prompt_health(ctx, portfolio, savings=None):
    """Portfolio health: real computed metrics + Gemini interpretation."""
    today = datetime.today().strftime("%Y-%m-%d")

    # Support both old and new savings format
    if isinstance(savings, dict) and "totals" in savings:
        sav_totals  = savings.get("totals", {})
        sav_entries = savings.get("entries", [])
    else:
        sav_totals  = savings or {}
        sav_entries = []

    # ── Compute real metrics from actual portfolio data ───────────────────
    holdings = portfolio.get("holdings", [])
    total_stock_kes = portfolio.get("total_market", 0) or 0
    total_sav_kes   = sum(sav_totals.values())
    total_all_kes   = total_stock_kes + total_sav_kes

    # Asset class allocation (real %)
    alloc = {}
    if total_all_kes > 0:
        # Stocks by exchange
        exch_vals = {}
        for h in holdings:
            exch = h.get("exchange","NSE")
            exch_vals[exch] = exch_vals.get(exch, 0) + (h.get("market_value_kes") or h.get("total_cost_kes", 0))
        for exch, val in exch_vals.items():
            alloc[f"Stocks ({exch})"] = round(val / total_all_kes * 100, 1)
        # Other assets
        for cls, val in sav_totals.items():
            if val > 0:
                alloc[cls] = round(val / total_all_kes * 100, 1)

    # Largest single position (concentration risk)
    max_pos_pct = 0
    max_pos_ticker = ""
    for h in holdings:
        if total_all_kes > 0:
            pct = (h.get("market_value_kes") or h.get("total_cost_kes", 0)) / total_all_kes * 100
            if pct > max_pos_pct:
                max_pos_pct = pct
                max_pos_ticker = h["ticker"]

    # Currency exposure
    ccy_split = {}
    for h in holdings:
        ccy = h.get("currency","KES")
        ccy_split[ccy] = ccy_split.get(ccy, 0) + (h.get("market_value_kes") or h.get("total_cost_kes", 0))
    for e in sav_entries:
        ccy = e.get("currency","KES")
        ccy_split[ccy] = ccy_split.get(ccy, 0) + max(0, e.get("amount_kes", 0))
    ccy_pct = {k: round(v/total_all_kes*100,1) for k,v in ccy_split.items()} if total_all_kes else {}

    # Actual portfolio return (weighted, where price data available)
    total_cost  = portfolio.get("total_cost", 0) or 1
    total_gain  = portfolio.get("total_gain", 0) or 0
    actual_return_pct = round(total_gain / total_cost * 100, 1) if total_cost else 0

    # Exchanges and geography
    exchanges = list({h.get("exchange","NSE") for h in holdings})

    # Asset-specific details for health agent
    mmf_kes    = sum(v for cls,v in sav_totals.items() if "mmf" in cls.lower() or "trust" in cls.lower() or "unit" in cls.lower())
    bonds_kes  = sum(v for cls,v in sav_totals.items() if "bond" in cls.lower() or "bill" in cls.lower() or "fixed" in cls.lower())
    farming_kes= sum(v for cls,v in sav_totals.items() if "farm" in cls.lower() or "agri" in cls.lower())
    sacco_kes  = sum(v for cls,v in sav_totals.items() if "sacco" in cls.lower() or "chama" in cls.lower())
    crypto_kes = sum((h.get("market_value_kes") or h.get("total_cost_kes",0)) for h in holdings if h.get("exchange")=="CRYPTO")

    # MMF/bond label details
    mmf_labels = [e["label"] for e in sav_entries if "mmf" in e.get("asset_class","").lower() or "trust" in e.get("asset_class","").lower()]
    bond_labels= [e["label"] for e in sav_entries if "bond" in e.get("asset_class","").lower() or "bill" in e.get("asset_class","").lower()]
    farm_labels= [e["label"] for e in sav_entries if "farm" in e.get("asset_class","").lower() or "agri" in e.get("asset_class","").lower()]

    # Build the computed metrics block
    computed = (
        "COMPUTED METRICS (from actual portfolio data):\n"
        f"  Total portfolio value: KES {total_all_kes:,.0f}\n"
        f"  Stock market value:    KES {total_stock_kes:,.0f} ({round(total_stock_kes/total_all_kes*100,1) if total_all_kes else 0}%)\n"
        f"  MMF / Unit Trusts:     KES {mmf_kes:,.0f}" + (f" ({", ".join(mmf_labels[:3])})" if mmf_labels else "") + "\n"
        f"  Bonds / T-Bills:       KES {bonds_kes:,.0f}" + (f" ({", ".join(bond_labels[:3])})" if bond_labels else "") + "\n"
        f"  Farming / Agri:        KES {farming_kes:,.0f}" + (f" ({", ".join(farm_labels[:3])})" if farm_labels else "") + "\n"
        f"  SACCO / Chama:         KES {sacco_kes:,.0f}\n"
        f"  Crypto:                KES {crypto_kes:,.0f}\n"
        f"  Actual stock return:   {actual_return_pct}% (unrealised, on cost basis)\n"
        f"  Largest single pos:    {max_pos_ticker} at {round(max_pos_pct,1)}% of total portfolio\n"
        f"  Exchanges held:        {", ".join(exchanges)}\n"
        f"  Currency exposure:     {", ".join(f"{c}: {p}%" for c,p in sorted(ccy_pct.items(), key=lambda x:-x[1]))}\n"
        "  Asset allocation:\n" + "".join(f"    {k}: {v}%\n" for k,v in sorted(alloc.items(), key=lambda x:-x[1]))
    )

    return f"""You are a portfolio risk analyst. Today is {today}.

{ctx}

{computed}

Use Google Search to find:
1. Kenya 91-day T-bill rate (risk-free rate)
2. Current MMF rates in Kenya (CIC, Sanlam, NCBA, etc)
3. NSE All Share Index YTD return (benchmark)
4. USD/KES trend this year

This portfolio has FOUR asset groups requiring different analysis:

STOCKS/ETFs/CRYPTO: Standard equity risk analysis. Note NSE stocks have lower liquidity than NYSE/NASDAQ.

MMF / UNIT TRUSTS: Low-risk liquid savings earning daily interest. Risk = CBK rate cuts reduce yield.
Stress test: If CBK cuts 200bps, MMF yield drops ~2%. Estimate impact on annual income.

BONDS / T-BILLS: Fixed income. Risk = interest rate rises cause capital loss if sold early.
If held to maturity, principal is safe. Stress test: rising rates scenario.

FARMING / AGRICULTURE: Illiquid, long-cycle, weather-dependent. Not marked to market.
Risk = drought, commodity price swings, payment delays. Strength = inflation hedge.
Stress test: crop failure or 30% commodity price drop.

SACCO / CHAMA: Semi-liquid. Locked savings with member dividend. Risk = governance, liquidity.

Score the portfolio 0-100 across FOUR dimensions (25 pts each):

1. DIVERSIFICATION (25pts):
   - Asset class breadth: stocks+bonds+MMF+farming+crypto = full marks
   - Geographic spread: NSE-only = low, NSE+global = high
   - Single-stock concentration: if largest position >30% of total = penalty

2. RESILIENCE (25pts):
   - Defensive assets (MMF+bonds) as % of total: >20% = resilient
   - Currency hedge: some USD exposure good for KES depreciation protection
   - Illiquid assets (farming, SACCO): cap at 20% or penalise

3. RETURN QUALITY (25pts):
   - Sharpe-like quality: stock return vs Kenya T-bill rate
   - MMF/bond yield vs inflation
   - Whether growth assets (stocks, crypto) are outperforming

4. INCOME (25pts):
   - Dividend-paying stocks
   - MMF interest income
   - Bond/T-bill coupon
   - SACCO dividends
   - Farming revenue

Return ONLY valid JSON:
{{
  "health_score": 0,
  "health_breakdown": {{
    "diversification": 0,
    "resilience":      0,
    "return_quality":  0,
    "income":          0
  }},
  "health_commentary": "2-sentence summary",
  "risk_metrics": {{
    "sharpe_ratio":          0,
    "risk_free_rate_pct":    0,
    "estimated_volatility":  "LOW|MEDIUM|HIGH|VERY_HIGH",
    "beta_to_global":        0,
    "concentration_risk":    "LOW|MEDIUM|HIGH",
    "currency_risk":         "LOW|MEDIUM|HIGH",
    "liquidity_risk":        "LOW|MEDIUM|HIGH",
    "largest_position_ticker": "",
    "largest_position_pct": 0
  }},
  "asset_class_health": [
    {{
      "class":         "",
      "value_kes":     0,
      "allocation_pct":0,
      "health":        "STRONG|GOOD|NEUTRAL|WEAK",
      "risk_note":     "specific risk for this asset class",
      "income_note":   "income contribution",
      "comment":       "1-sentence assessment"
    }}
  ],
  "stress_tests": [
    {{
      "scenario":           "",
      "description":        "",
      "asset_classes_affected": [],
      "estimated_loss_pct": 0,
      "estimated_loss_kes": 0,
      "most_affected":      [],
      "defensive_assets":   ["what protects this portfolio specifically"],
      "resilient_assets":   ["which holdings hold up well"]
    }}
  ],
  "portfolio_badges": [
    {{
      "badge":       "",
      "icon":        "",
      "description": "",
      "awarded":     true
    }}
  ],
  "investor_profile": {{
    "type":         "",
    "sub_type":     "",
    "description":  "",
    "risk_appetite":"CONSERVATIVE|MODERATE|AGGRESSIVE",
    "time_horizon": "",
    "primary_goal": "",
    "strengths":    [],
    "gaps":         []
  }},
  "improvement_suggestions": []
}}

STRESS TEST SCENARIOS (must include all 5):
1. Kenya shilling depreciation (-20% KES vs USD) — affects USD holdings and imported goods
2. NSE liquidity crisis (-30% NSE stocks) — affects KCB, SCOM, ABSA etc
3. CBK rate hike (+300bps) — hurts bond prices, boosts MMF yields, slows NSE
4. Global market crash (-40% equities) — affects NASDAQ/NYSE holdings
5. Kenya-specific: drought + commodity shock — affects farming income, food inflation

BADGE CRITERIA:
- "Diversification Master" 🌍 : stocks + bonds + MMF + one more = 4 asset classes
- "Dividend Investor" 💰 : 3+ dividend-paying stocks
- "Africa First" 🌍 : 40%+ in NSE/African markets
- "Fixed Income Builder" 📊 : bonds+MMF > 15% of portfolio
- "Inflation Fighter" 🌱 : farming + real assets > 5% of portfolio
- "Tech Forward" 💻 : 30%+ in tech stocks/ETFs
- "Risk Manager" 🛡️ : Sharpe > 1 AND defensive assets > 20%
- "Long Term Thinker" ⏳ : avg stock holding > 1 year
- "Global Citizen" 🌐 : holdings in 3+ currencies
- "Income Builder" 📈 : total income yield > 4% (dividends + MMF + bonds)
"""


def _prompt_analyst_batch(tickers_batch):
    """Batch analyst prompt - analyses up to 5 tickers in one Gemini call.
    Returns an array of analysis objects, one per ticker.
    This reduces API calls from N to N/5 for large portfolios.
    """
    today = datetime.today().strftime("%Y-%m-%d")
    ticker_list = chr(10).join(
        f"  - {t['ticker']} ({t['exchange']})" for t in tickers_batch
    )
    n = len(tickers_batch)
    return (
        "You are a senior equity analyst. Today is " + today + "." + chr(10) +
        chr(10) +
        "Analyse ALL " + str(n) + " tickers below using MULTIPLE sources." + chr(10) +
        "Sources: Goldman Sachs, Morgan Stanley, JPMorgan, UBS, Citi, BofA, Morningstar, CFRA, Bloomberg." + chr(10) +
        "For African stocks also check: Rand Merchant Bank, Stanbic, AIB-AXYS, CBA Securities." + chr(10) +
        chr(10) +
        "TICKERS TO ANALYSE:" + chr(10) +
        ticker_list + chr(10) +
        chr(10) +
        "Return ONLY valid JSON array (no markdown, no code fences):" + chr(10) +
        '[' + chr(10) +
        '  {' + chr(10) +
        '    "ticker": "",' + chr(10) +
        '    "exchange": "",' + chr(10) +
        '    "consensus": "BUY|HOLD|SELL|MIXED",' + chr(10) +
        '    "sources_count": 0,' + chr(10) +
        '    "sources_list": [],' + chr(10) +
        '    "avg_price_target": "",' + chr(10) +
        '    "upside_pct": 0,' + chr(10) +
        '    "key_thesis": "specific investment thesis — required",' + chr(10) +
        '    "bull_case": "",' + chr(10) +
        '    "bear_case": "",' + chr(10) +
        '    "recent_changes": [{"analyst":"","institution":"","action":"UPGRADE|DOWNGRADE|INITIATE","date":"","target":""}],' + chr(10) +
        '    "data_freshness": "e.g. 3 days ago",' + chr(10) +
        '    "skip": false' + chr(10) +
        '  }' + chr(10) +
        ']' + chr(10) +
        'Return EXACTLY ' + str(n) + ' objects in the array, one per ticker, in the same order.' + chr(10) +
        'Set skip=true for any ticker where you cannot find coverage from at least 2 sources.'
    )


# ── Specialist sub-verifier prompts (one per agent domain) ──────────────────

_SUB_VERIFIER_SPECS = {
    "performance": {
        "role":   "a quantitative portfolio performance analyst and auditor",
        "checks": (
            "1. Are return percentages mathematically consistent with stated prices?\n"
            "2. Does the health score align with the 5 breakdown dimensions?\n"
            "3. Are top performers / underperformers plausible given current market conditions?\n"
            "4. Use Google Search to confirm recent performance of major NSE / NYSE indices."
        ),
    },
    "rebalancing": {
        "role":   "a portfolio construction and asset allocation specialist",
        "checks": (
            "1. Are trim percentages realistic (flag anything >80% without clear justification)?\n"
            "2. Does rebalancing advice align with the performance findings?\n"
            "3. Are suggested buy amounts consistent with available capital?\n"
            "4. Do suggested new tickers / ETFs actually exist on the stated exchanges?"
        ),
    },
    "analyst": {
        "role":   "a senior equity research compliance reviewer",
        "checks": (
            "1. Use Google Search: do the cited institutions (Goldman, Morgan Stanley etc) "
            "actually cover these tickers?\n"
            "2. Are consensus ratings consistent with current market data?\n"
            "3. Are price targets within a realistic range (not >500% upside)?\n"
            "4. Are recent upgrade/downgrade actions verifiable and dated correctly?"
        ),
    },
    "thematic": {
        "role":   "a thematic investment research specialist",
        "checks": (
            "1. Are stated exposure percentages consistent with the portfolio holdings provided?\n"
            "2. Do the recommended ETFs actually exist on stated exchanges?\n"
            "3. Use Google Search to verify TER and AUM for cited ETFs.\n"
            "4. Are the ETFs accessible to Kenyan investors via local brokers?"
        ),
    },
    "corporate": {
        "role":   "a corporate actions and dividend calendar specialist",
        "checks": (
            "1. Are all stated ex-dates and payment dates in the FUTURE?\n"
            "2. Use Google Search: verify upcoming NSE dividend dates (SCOM, KCB, ABSA etc).\n"
            "3. Are stated dividend amounts per share realistic?\n"
            "4. Are earnings dates and splits verifiable?"
        ),
    },
    "dividend": {
        "role":   "a dividend income and yield analysis specialist",
        "checks": (
            "1. Are YTD dividend amounts plausible for the stated holdings and share counts?\n"
            "2. Are projected annual yields realistic (flag anything >20%)?\n"
            "3. Do stated ex-dates match known dividend calendars for NSE / NYSE?\n"
            "4. Are MMF interest rates cited consistent with current Kenya market rates?"
        ),
    },
    "health": {
        "role":   "a quantitative risk analyst and portfolio health specialist",
        "checks": (
            "1. Is the Sharpe ratio plausible given stated return and volatility?\n"
            "2. Use Google Search: what is the current Kenya 91-day T-bill rate?\n"
            "3. Are stress test loss estimates realistic for this portfolio composition?\n"
            "4. Are asset class allocation percentages consistent with the rebalancing agent?"
        ),
    },
}


def _prompt_sub_verifier(agent_id, agent_result, note=""):
    """Specialist sub-verifier prompt for one specific agent."""
    today = datetime.today().strftime("%Y-%m-%d")
    spec  = _SUB_VERIFIER_SPECS.get(agent_id, {
        "role":   "a financial data quality reviewer",
        "checks": "1. Check factual accuracy.\n2. Flag inconsistencies.",
    })
    data_str = json.dumps(agent_result, indent=2)
    if len(data_str) > 15000:
        data_str = data_str[:15000] + "... [truncated]"
    pass_note = (note + chr(10) + chr(10)) if note else ""
    sep = chr(10)
    return sep.join([
        "You are " + spec["role"] + ". Today is " + today + ".",
        pass_note,
        "Verify the output from the " + agent_id.upper() + " agent below.",
        "Use Google Search to fact-check specific claims.",
        "",
        "VERIFICATION CRITERIA:",
        spec["checks"],
        "",
        "CONFIDENCE RULES:",
        "- HIGH: confirmed from external source",
        "- MEDIUM: plausible, unconfirmed but no contradicting evidence",
        "- LOW: unverifiable, suspicious, or contradicted",
        "",
        "AGENT OUTPUT:",
        data_str,
        "",
        "Return ONLY valid JSON (no markdown):",
        "{",
        '  "agent": "' + agent_id + '",',
        '  "confidence": "HIGH|MEDIUM|LOW",',
        '  "needs_revision": false,',
        '  "verified_claims": [{"claim":"","status":"VERIFIED|NEEDS_REVISION|INCORRECT","source":""}],',
        '  "issues": ["specific issue 1"],',
        '  "feedback": "specific actionable feedback for the agent",',
        '  "reliability_score": "HIGH|MEDIUM|LOW"',
        "}",
    ])


def _prompt_meta_verifier(agent_results, sub_verifier_results, note=""):
    """Meta-verifier: cross-agent coherence after all sub-verifiers run."""
    today    = datetime.today().strftime("%Y-%m-%d")
    pass_note = (note + chr(10) + chr(10)) if note else ""
    sub_summary = {
        aid: {
            "confidence":     r.get("confidence", "MEDIUM"),
            "needs_revision": r.get("needs_revision", False),
            "issues":         (r.get("issues") or [])[:3],
        }
        for aid, r in sub_verifier_results.items()
    }
    slim = {}
    for aid in ("performance", "rebalancing", "thematic", "health"):
        r = agent_results.get(aid, {})
        slim[aid] = {k: v for k, v in r.items()
                     if k in ("overall_rating", "health_score", "rebalancing_actions",
                               "exposure_radar", "risk_metrics")}
    slim_str = json.dumps(slim, indent=2)
    if len(slim_str) > 12000:
        slim_str = slim_str[:12000] + "...}"
    sep = chr(10)
    return sep.join([
        "You are a chief investment officer reviewing a multi-agent portfolio analysis. Today is " + today + ".",
        pass_note,
        "Sub-verifiers checked each agent individually. Your job: CROSS-AGENT COHERENCE.",
        "",
        "SUB-VERIFIER FINDINGS:",
        json.dumps(sub_summary, indent=2),
        "",
        "KEY AGENT OUTPUTS:",
        slim_str,
        "",
        "CHECK:",
        "1. Does rebalancing advice align with performance findings?",
        "2. Does health risk score align with rebalancing urgency?",
        "3. Does thematic exposure match analyst sector views?",
        "4. Any contradictions — e.g., one agent says BUY, another says TRIM same ticker?",
        "5. Is this a coherent, actionable portfolio review?",
        "",
        "Return ONLY valid JSON (no markdown):",
        "{",
        '  "overall_confidence": "HIGH|MEDIUM|LOW",',
        '  "coherence_score": 0,',
        '  "contradictions": [{"agents":[],"description":"","resolution":""}],',
        '  "agent_revisions_needed": {',
        '    "performance":{"needs_revision":false,"items":[],"feedback":""},',
        '    "rebalancing":{"needs_revision":false,"items":[],"feedback":""},',
        '    "analyst":{"needs_revision":false,"items":[],"feedback":""},',
        '    "thematic":{"needs_revision":false,"items":[],"feedback":""},',
        '    "corporate":{"needs_revision":false,"items":[],"feedback":""},',
        '    "dividend":{"needs_revision":false,"items":[],"feedback":""},',
        '    "health":{"needs_revision":false,"items":[],"feedback":""}',
        "  },",
        '  "reliability_scores":{',
        '    "performance":"HIGH","rebalancing":"HIGH","analyst":"MEDIUM",',
        '    "thematic":"MEDIUM","corporate":"HIGH","dividend":"MEDIUM","health":"HIGH"',
        "  },",
        '  "high_confidence_only":{',
        '    "analyst_views":["tickers with HIGH confidence"],"dividends":[],"corporate_actions":[],"hot_picks":[]',
        "  },",
        '  "verifier_note": "2-3 sentence overall quality and coherence assessment"',
        "}",
    ])


def _prompt_verifier(agent_results, note=""):
    """Legacy single-pass verifier kept as fallback."""
    today = datetime.today().strftime("%Y-%m-%d")
    results_str = json.dumps(agent_results, indent=2)
    if len(results_str) > 40000:
        results_str = results_str[:40000] + "...}"
    pass_header = (note + chr(10) + chr(10)) if note else ""
    sep = chr(10)
    return sep.join([
        "You are a meticulous fact-checker. Today is " + today + ".",
        pass_header,
        "Review these portfolio analysis agent outputs for accuracy.",
        "Use Google Search to verify key claims.",
        "",
        "AGENT OUTPUTS:",
        results_str,
        "",
        "Return ONLY valid JSON:",
        "{",
        '  "overall_confidence": "HIGH|MEDIUM|LOW",',
        '  "agent_revisions_needed": {',
        '    "performance":{"needs_revision":false,"items":[],"feedback":""},',
        '    "rebalancing":{"needs_revision":false,"items":[],"feedback":""},',
        '    "analyst":{"needs_revision":false,"items":[],"feedback":""},',
        '    "thematic":{"needs_revision":false,"items":[],"feedback":""},',
        '    "corporate":{"needs_revision":false,"items":[],"feedback":""},',
        '    "dividend":{"needs_revision":false,"items":[],"feedback":""},',
        '    "health":{"needs_revision":false,"items":[],"feedback":""}',
        "  },",
        '  "reliability_scores":{"performance":"HIGH","rebalancing":"HIGH","analyst":"MEDIUM","thematic":"MEDIUM","corporate":"HIGH","dividend":"MEDIUM","health":"HIGH"},',
        '  "verifier_note":"Overall assessment"',
        "}",
    ])


def _prompt_summary(agent_results, verifier_result):
    # Limit context size to avoid token overflow
    slim = {k: v for k, v in agent_results.items()}
    all_str = json.dumps({**slim, "verifier": verifier_result}, indent=2)
    # Truncate if too large
    if len(all_str) > 60000:
        all_str = all_str[:60000] + "...}"
    return f"""You are a senior wealth manager preparing a comprehensive weekly review for a Kenyan investor.
Today is {datetime.today().strftime('%Y-%m-%d')}.

Based on the analysis from 6 specialist agents (performance, rebalancing, analyst views, 
thematic research, corporate actions, and verification), create a concise executive summary.

FULL ANALYSIS:
{all_str}

Return ONLY valid JSON (no markdown, no code fences):
{{
  "headline": "one compelling weekly headline",
  "overall_rating": "STRONG|GOOD|NEUTRAL|CAUTION|REVIEW",
  "executive_summary": "4-6 sentence overview of portfolio state and key takeaways",
  "top_3_actions": [
    {{"priority":1,"action":"","rationale":"","urgency":"NOW|THIS_WEEK|THIS_MONTH"}}
  ],
  "watchlist": [
    {{"ticker":"","exchange":"","reason":"","entry_range":"","time_horizon":""}}
  ],
  "risks_to_watch": ["list top 3 portfolio risks right now"],
  "opportunities": ["list top 3 opportunities"],
  "kes_impact_note": "how currency movements are affecting the KES value of foreign holdings",
  "income_summary": {{
    "ytd_income_kes": 0,
    "projected_annual_kes": 0,
    "yield_pct": 0
  }},
  "portfolio_badges": [
    {{"badge":"","icon":"","description":""}}
  ],
  "investor_profile": {{
    "type": "",
    "sub_type": "",
    "description": "",
    "risk_appetite": "CONSERVATIVE|MODERATE|AGGRESSIVE",
    "time_horizon": "",
    "primary_goal": ""
  }},
  "next_review_focus": "what to focus on in the next weekly review"
}}"""


# ── Job management ────────────────────────────────────────────────────────────

def _save_job(job_id, user_id, agents_state):
    from db import get_db, ph, is_pg
    conn = get_db()
    try:
        agents_json = json.dumps(agents_state)
        finished    = agents_state.get("_finished_at")
        status      = "completed" if finished else "running"
        if any(a.get("status") == "error" for k, a in agents_state.items()
               if not k.startswith("_")):
            # don't mark as error if some agents failed — partial is still useful
            pass
        cur = conn.cursor()
        if is_pg():
            # Use TEXT cast not ::jsonb to avoid failures on large/special payloads
            cur.execute("""
                INSERT INTO review_jobs (id,user_id,status,started_at,finished_at,agents)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT(id) DO UPDATE SET
                  status=EXCLUDED.status,
                  finished_at=EXCLUDED.finished_at,
                  agents=EXCLUDED.agents
            """, (job_id, user_id, status,
                  agents_state.get("_started_at",""), finished, agents_json))
        else:
            cur.execute("""
                INSERT OR REPLACE INTO review_jobs
                    (id,user_id,status,started_at,finished_at,agents)
                VALUES (?,?,?,?,?,?)
            """, (job_id, user_id, status,
                  agents_state.get("_started_at",""), finished, agents_json))
        conn.commit()
    except Exception as e:
        # Log the error but don't crash the pipeline
        print(f"[_save_job] ERROR saving job {job_id}: {e}", flush=True)
        try: conn.rollback()
        except: pass
    finally:
        conn.close()

def get_job(job_id, user_id):
    from db import get_db, ph, is_pg
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT * FROM review_jobs WHERE id={ph()} AND user_id={ph()}",
            (job_id, user_id))
        r = cur.fetchone()
        if not r:
            return None
        d = dict(r)
        # agents can be TEXT or JSONB — normalize to dict
        if d.get("agents"):
            agents_val = d["agents"]
            if isinstance(agents_val, str):
                try:
                    d["agents"] = json.loads(agents_val)
                except Exception:
                    d["agents"] = {}
            elif isinstance(agents_val, dict):
                pass  # already parsed (JSONB column)
        # Normalize timestamps
        for k in ("started_at","finished_at"):
            if d.get(k): d[k] = str(d[k])[:19]
        return d
    finally:
        conn.close()

def list_jobs(user_id, limit=10):
    from db import get_db, ph, is_pg
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT id,status,started_at,finished_at FROM review_jobs "
            f"WHERE user_id={ph()} ORDER BY started_at DESC LIMIT {ph()}",
            (user_id, limit))
        rows = [dict(r) for r in cur.fetchall()]
        # Ensure id is always a string (never None)
        for r in rows:
            r["id"] = str(r.get("id") or "")
            for k in ("started_at","finished_at"):
                if r.get(k): r[k] = str(r[k])[:19]
        return rows
    except Exception:
        return []
    finally:
        conn.close()


# ── Pipeline runner ───────────────────────────────────────────────────────────

def _make_revision_prompt(agent_id, original_result, feedback_str):
    """Return a prompt function that asks an agent to revise its output."""
    today = datetime.today().strftime("%Y-%m-%d")
    original_str = json.dumps(original_result, indent=2)

    def prompt_fn():
        return (
            f"You are revising your previous analysis based on verifier feedback. Today is {today}.\n\n"
            f"YOUR PREVIOUS OUTPUT:\n{original_str}\n\n"
            f"VERIFIER FEEDBACK (items needing correction):\n{feedback_str}\n\n"
            f"Use Google Search to verify and fix the flagged items.\n"
            f"Return the COMPLETE corrected output in the same JSON format as before.\n"
            f"Only fix what was flagged. Return ONLY valid JSON, no markdown."
        )
    return prompt_fn


def run_pipeline(job_id, user_id, api_key, portfolio, savings):
    """
    Run all 7 agents. Called in a background thread.
    Writes progress to review_jobs after each agent completes.
    """
    now    = datetime.utcnow().isoformat()
    ctx    = _portfolio_context(portfolio, savings)
    tickers_str = ", ".join(
        f"{h['ticker']} ({h['exchange']})"
        for h in portfolio.get("holdings", [])
    ) or "No active holdings"

    state = {
        "_started_at": now,
        "_job_id":     job_id,
    }
    for a in AGENTS:
        state[a["id"]] = {"status": "waiting", "num": a["num"],
                          "name": a["name"], "icon": a["icon"]}
    _save_job(job_id, user_id, state)

    def run_agent(agent_id, prompt_fn=None, *args, **kwargs):
        state[agent_id]["status"]  = "running"
        state[agent_id]["started"] = datetime.utcnow().isoformat()
        _save_job(job_id, user_id, state)
        try:
            actual_fn = kwargs.pop("prompt_fn", prompt_fn)
            prompt    = actual_fn(*args, **kwargs)
            text      = _gemini(api_key, prompt, timeout=90)
            result    = _extract_json(text)
            state[agent_id]["status"] = "done"
            state[agent_id]["result"] = result
        except Exception as e:
            state[agent_id]["status"] = "error"
            state[agent_id]["error"]  = str(e)
        state[agent_id]["finished"] = datetime.utcnow().isoformat()
        _save_job(job_id, user_id, state)

    # ── Batched dividend runner (handles 30+ tickers via chunking) ──────────
    BATCH_SIZE = 10  # Gemini handles ~10 tickers well per call

    def _run_dividend_batched():
        """Run dividend agent in batches of BATCH_SIZE tickers, merge results."""
        holdings = portfolio.get("holdings", [])
        active   = [h for h in holdings if (h.get("total_shares") or 0) > 0]

        if not active:
            state["dividend"]["status"] = "done"
            state["dividend"]["result"] = {
                "ytd_received": [], "expected_remaining": [],
                "non_dividend_holdings": [],
                "summary": {"ytd_income_kes":0,"expected_remaining_kes":0,
                            "projected_annual_kes":0,"portfolio_yield_pct":0,
                            "income_commentary":"No active holdings."}
            }
            _save_job(job_id, user_id, state)
            return

        state["dividend"]["status"]  = "running"
        state["dividend"]["started"] = datetime.utcnow().isoformat()
        _save_job(job_id, user_id, state)

        # Split into batches
        batches = [active[i:i+BATCH_SIZE] for i in range(0, len(active), BATCH_SIZE)]

        all_ytd, all_expected, all_non_div = [], [], []
        merged_summary = {
            "ytd_income_kes":0,"expected_remaining_kes":0,
            "projected_annual_kes":0,"portfolio_yield_pct":0,
            "top_income_ticker":"","dividend_growth_trend":"MIXED",
            "income_commentary":""
        }

        batch_sem = threading.Semaphore(4)  # max 4 concurrent batch calls

        results  = [None] * len(batches)
        errors   = []

        def fetch_batch(i, batch):
            with batch_sem:
                # Build a mini-portfolio for this batch
                mini_port = {**portfolio, "holdings": batch}
                try:
                    prompt = _prompt_dividend(ctx, mini_port, savings)
                    text   = _gemini(api_key, prompt, timeout=90)
                    result = _extract_json(text)
                    results[i] = result
                except Exception as e:
                    errors.append(f"batch {i}: {e}")

        batch_threads = [
            threading.Thread(target=fetch_batch, args=(i, batch), daemon=True)
            for i, batch in enumerate(batches)
        ]
        for t in batch_threads: t.start()
        for t in batch_threads: t.join(timeout=120)

        # Merge all batch results
        for r in results:
            if not r: continue
            all_ytd.extend(r.get("ytd_received") or [])
            all_expected.extend(r.get("expected_remaining") or [])
            all_non_div.extend(r.get("non_dividend_holdings") or [])
            s = r.get("summary") or {}
            merged_summary["ytd_income_kes"]       += s.get("ytd_income_kes",0) or 0
            merged_summary["expected_remaining_kes"]+= s.get("expected_remaining_kes",0) or 0
            merged_summary["projected_annual_kes"] += s.get("projected_annual_kes",0) or 0
            if s.get("income_commentary"):
                merged_summary["income_commentary"] = s["income_commentary"]
            if s.get("top_income_ticker"):
                merged_summary["top_income_ticker"] = s["top_income_ticker"]

        # Calculate yield from merged totals
        total_mkt = portfolio.get("total_market",0) or 1
        merged_summary["portfolio_yield_pct"] = round(
            merged_summary["projected_annual_kes"] / total_mkt * 100, 2)
        if not merged_summary["income_commentary"]:
            merged_summary["income_commentary"] = (
                f"Analysed {len(active)} tickers in {len(batches)} batch(es). "
                f"Projected annual income: KES {merged_summary['projected_annual_kes']:,.0f}.")

        state["dividend"]["status"]  = "done"
        state["dividend"]["result"]  = {
            "ytd_received":          all_ytd,
            "expected_remaining":    all_expected,
            "non_dividend_holdings": list(set(all_non_div)),
            "summary":               merged_summary,
        }
        state["dividend"]["finished"] = datetime.utcnow().isoformat()
        _save_job(job_id, user_id, state)

    # ── Thematic: compute REAL exposure from held tickers before prompting ───
    # Maps tickers to theme categories so Gemini gets accurate starting data
    THEME_MAP = {
        # AI & Technology
        "QQQ":["AI & Automation","Technology"], "VOO":["Technology","S&P500"],
        "VGT":["Technology"], "SOXX":["Semiconductors"], "ARKK":["Disruptive Tech"],
        "NVDA":["AI & Automation","Semiconductors"], "MSFT":["AI & Automation","Technology"],
        "GOOGL":["AI & Automation","Technology"], "META":["AI & Automation","Technology"],
        "AAPL":["Technology"], "AMZN":["Technology","E-Commerce"],
        # Clean Energy
        "ICLN":["Clean Energy","Climate"], "TAN":["Clean Energy"],
        "ENPH":["Clean Energy","Solar"], "NEE":["Clean Energy"],
        "PLUG":["Hydrogen","Clean Energy"], "FSLR":["Clean Energy","Solar"],
        # Healthcare
        "XLV":["Healthcare"], "VHT":["Healthcare"], "IBB":["Biotech"],
        "LLY":["Healthcare","Biotech"], "JNJ":["Healthcare"],
        # Africa & Emerging Markets
        "EWZ":["Emerging Markets"], "EEM":["Emerging Markets"],
        "AFK":["Africa"], "NGE":["Africa","Nigeria"],
        "SCOM":["Africa","Kenya","Telecom"], "KCB":["Africa","Kenya","Banking"],
        "ABSA":["Africa","Kenya","Banking"], "EQTY":["Africa","Kenya","Banking"],
        "BAMB":["Africa","Kenya","Manufacturing"],
        # Commodities & Inflation hedge
        "GLD":["Gold","Commodities"], "SLV":["Silver","Commodities"],
        "PDBC":["Commodities"], "DJP":["Commodities"],
        "BTC":["Crypto","Digital Assets"], "ETH":["Crypto","Digital Assets"],
        # Infrastructure & Real Estate
        "VNQ":["Real Estate","REITs"], "REET":["Real Estate","REITs"],
        "PAVE":["Infrastructure"],
        # Defence & Geopolitics
        "ITA":["Defence"], "XAR":["Defence"], "LMT":["Defence"],
        # Bonds/Fixed Income
        "BND":["Bonds","Fixed Income"], "AGG":["Bonds","Fixed Income"],
        "TLT":["Long-Duration Bonds"],
    }

    def _compute_thematic_exposure():
        """Compute real % exposure per theme from actual portfolio holdings."""
        holdings    = portfolio.get("holdings", [])
        total_value = portfolio.get("total_market") or portfolio.get("total_cost") or 1
        if not total_value or total_value == 0: total_value = 1

        theme_exposure = {}  # theme → KES value
        unclassified   = []

        for h in holdings:
            ticker  = h["ticker"].upper()
            mkt_val = h.get("market_value_kes") or h.get("total_cost_kes") or 0
            themes  = THEME_MAP.get(ticker, [])
            if themes:
                for theme in themes:
                    theme_exposure[theme] = theme_exposure.get(theme, 0) + mkt_val
            else:
                # Classify by exchange as a fallback
                exch = h.get("exchange","")
                if exch == "NSE":
                    for th in ["Africa","Kenya"]:
                        theme_exposure[th] = theme_exposure.get(th, 0) + mkt_val
                elif exch == "CRYPTO":
                    for th in ["Crypto","Digital Assets"]:
                        theme_exposure[th] = theme_exposure.get(th, 0) + mkt_val
                else:
                    unclassified.append(ticker)

        # Convert to %
        return {
            theme: round(val / total_value * 100, 1)
            for theme, val in theme_exposure.items()
        }, unclassified

    def _run_thematic_with_exposure():
        """Thematic agent with real computed exposure injected into prompt."""
        state["thematic"]["status"]  = "running"
        state["thematic"]["started"] = datetime.utcnow().isoformat()
        _save_job(job_id, user_id, state)
        try:
            real_exposure, unclassified = _compute_thematic_exposure()
            # Build exposure summary string
            exp_lines = sorted(real_exposure.items(), key=lambda x:-x[1])
            exp_str   = chr(10).join(
                f"  {theme}: {pct}% of portfolio" for theme, pct in exp_lines
            ) or "  No mapped exposure yet"
            uncl_str  = ", ".join(unclassified) or "none"

            # Build enhanced context
            exposure_context = (
                ctx + chr(10) + chr(10) +
                "COMPUTED THEMATIC EXPOSURE (from actual holdings, use these EXACT percentages):" + chr(10) +
                exp_str + chr(10) +
                "Unclassified tickers (no theme mapping): " + uncl_str + chr(10) +
                "IMPORTANT: Use the computed percentages above as current_exposure_pct values." + chr(10) +
                "Do NOT invent or estimate exposure percentages — use the ones provided."
            )
            prompt = _prompt_thematic(exposure_context)
            text   = _gemini(api_key, prompt, timeout=90)
            result = _extract_json(text)
            # Inject real percentages into result (override any Gemini invention)
            for trend in result.get("megatrends", []):
                theme_key = trend.get("theme","")
                # Find closest matching theme in real_exposure
                matched_pct = 0
                for exp_theme, pct in real_exposure.items():
                    if exp_theme.lower() in theme_key.lower() or theme_key.lower() in exp_theme.lower():
                        matched_pct = max(matched_pct, pct)
                if matched_pct:
                    trend["current_exposure_pct"] = matched_pct
                    trend["current_exposure"] = (
                        "ADEQUATE" if matched_pct >= (trend.get("target_allocation_pct") or 10) * 0.8
                        else "LOW" if matched_pct > 0
                        else "NONE"
                    )
            # Also fix radar
            for r in result.get("exposure_radar", []):
                theme_key = r.get("theme","")
                for exp_theme, pct in real_exposure.items():
                    if exp_theme.lower() in theme_key.lower() or theme_key.lower() in exp_theme.lower():
                        r["current_pct"] = max(r.get("current_pct",0), pct)
                        break
            state["thematic"]["status"] = "done"
            state["thematic"]["result"] = result
        except Exception as e:
            state["thematic"]["status"] = "error"
            state["thematic"]["error"]  = str(e)
        state["thematic"]["finished"] = datetime.utcnow().isoformat()
        _save_job(job_id, user_id, state)

    # ── Agents 1-7 in parallel ────────────────────────────────────────────────
    # Analyst runs per-ticker in sub-threads (multithreaded)
    def run_analyst_multithreaded():
        """Batch analyst: 5 tickers per Gemini call, parallel batch threads.
        30 tickers = 6 calls (vs 30 before). Respects 15 RPM rate limit."""
        holdings = portfolio.get("holdings", [])
        if not holdings:
            state["analyst"]["status"] = "done"
            state["analyst"]["result"] = {
                "analyst_views":[],"hot_picks":[],
                "sector_sentiment":[],"market_context":"No holdings."}
            _save_job(job_id, user_id, state)
            return

        state["analyst"]["status"] = "running"
        _save_job(job_id, user_id, state)

        ANALYST_BATCH = 5         # tickers per Gemini call
        MAX_CONCURRENT = 4        # max concurrent batch calls (rate limit guard)

        # Deduplicate holdings by ticker+exchange
        seen = set()
        unique_holdings = []
        for h in holdings:
            k = (h["ticker"], h.get("exchange","NSE"))
            if k not in seen:
                seen.add(k); unique_holdings.append(h)

        batches = [
            unique_holdings[i:i+ANALYST_BATCH]
            for i in range(0, len(unique_holdings), ANALYST_BATCH)
        ]

        per_ticker_results = {}
        lock    = threading.Lock()
        bat_sem = threading.Semaphore(MAX_CONCURRENT)

        def fetch_batch(batch):
            with bat_sem:
                try:
                    prompt  = _prompt_analyst_batch(batch)
                    text    = _gemini(api_key, prompt, timeout=90)
                    # Response is a JSON array
                    raw     = _extract_json(text)
                    results = raw if isinstance(raw, list) else raw.get("results", [raw])
                    for r in results:
                        if isinstance(r, dict) and not r.get("skip") and r.get("key_thesis"):
                            ticker = (r.get("ticker") or "").upper()
                            if ticker:
                                with lock:
                                    per_ticker_results[ticker] = r
                except Exception:
                    pass  # Skip failed batches; remaining batches still run

        batch_threads = [
            threading.Thread(target=fetch_batch, args=(b,), daemon=True)
            for b in batches
        ]
        for t in batch_threads: t.start()
        for t in batch_threads: t.join(timeout=120)

        # Include ALL held tickers — covered ones have full data, others marked N/A
        analyst_views = []
        for h in unique_holdings:
            ticker = h["ticker"].upper()
            if ticker in per_ticker_results:
                analyst_views.append(per_ticker_results[ticker])
            else:
                # Placeholder for tickers with no analyst coverage found
                analyst_views.append({
                    "ticker":          ticker,
                    "exchange":        h.get("exchange",""),
                    "consensus":       "N/A",
                    "sources_count":   0,
                    "sources_list":    [],
                    "avg_price_target":"",
                    "upside_pct":      0,
                    "key_thesis":      "No analyst coverage found",
                    "bull_case":       "",
                    "bear_case":       "",
                    "recent_changes":  [],
                    "data_freshness":  "",
                    "skip":            True,
                    "no_coverage":     True,
                })
        # Also run a single call for hot picks
        hot_picks = []
        try:
            _td = datetime.today().strftime("%Y-%m-%d")
            picks_prompt = (
                "You are an equity analyst. Today is " + _td + ". "
                "Based on current market conditions, give the top 4 highest-conviction stock picks "
                "from multiple sources (Goldman Sachs, Morgan Stanley, JPMorgan, Morningstar, Bloomberg). "
                "Each pick MUST have a specific thesis AND a named near-term catalyst. "
                "Max 4 picks from DIFFERENT sources. "
                'Return ONLY JSON: {"hot_picks":[{"ticker":"","exchange":"","source":"",'
                '"source_type":"","rating":"","price_target":"",'
                '"thesis":"specific thesis required","catalyst":"specific catalyst",'
                '"time_horizon":""}]}'
            )
            picks_text = _gemini(api_key, picks_prompt, timeout=60)
            picks_data = _extract_json(picks_text)
            hot_picks  = (picks_data.get("hot_picks") or [])[:4]
        except Exception:
            pass

        state["analyst"]["status"] = "done"
        state["analyst"]["result"] = {
            "analyst_views":   analyst_views,
            "hot_picks":       hot_picks,
            "sector_sentiment":[],
            "market_context":  f"Multi-source analysis of {len(analyst_views)} holdings.",
        }
        _save_job(job_id, user_id, state)

    threads = [
        threading.Thread(target=run_agent,                 args=("performance", _prompt_performance, ctx)),
        threading.Thread(target=run_agent,                 args=("rebalancing", _prompt_rebalancing, ctx)),
        threading.Thread(target=run_analyst_multithreaded, args=()),
        threading.Thread(target=_run_thematic_with_exposure, args=()),
        threading.Thread(target=run_agent,                 args=("corporate",   _prompt_corporate, tickers_str)),
        threading.Thread(target=_run_dividend_batched,      args=()),
        threading.Thread(target=run_agent,                 args=("health",      _prompt_health,      ctx, portfolio, savings)),
    ]
    for t in threads: t.daemon = True; t.start()
    for t in threads: t.join(timeout=150)

    # ── Agent 6: Verifier (waits for 1-5) ────────────────────────────────────
    agent_results = {
        aid: state[aid].get("result", {})
        for aid in ("performance","rebalancing","analyst","thematic","corporate","dividend","health")
    }
    # ── Agent 8: Parallel sub-verifiers + meta-verifier ─────────────────────
    state["verifier"]["status"] = "running"
    state["verifier"]["pass"]   = 1
    _save_job(job_id, user_id, state)

    sub_results = {}
    sub_lock    = threading.Lock()
    sub_sem     = threading.Semaphore(6)  # max 6 concurrent

    def _run_sub_verifier(aid):
        with sub_sem:
            try:
                p = _prompt_sub_verifier(aid, agent_results.get(aid, {}))
                t = _gemini(api_key, p, timeout=90)
                r = _extract_json(t)
                with sub_lock:
                    sub_results[aid] = r
            except Exception as e:
                with sub_lock:
                    sub_results[aid] = {
                        "agent": aid, "confidence": "MEDIUM",
                        "needs_revision": False, "feedback": str(e),
                        "reliability_score": "MEDIUM", "issues": [],
                    }

    sub_threads = [
        threading.Thread(target=_run_sub_verifier, args=(aid,), daemon=True)
        for aid in ALL_REVISIONABLE
    ]
    for t in sub_threads: t.start()
    for t in sub_threads: t.join(timeout=120)

    # Meta-verifier: cross-agent coherence
    try:
        meta_prompt  = _prompt_meta_verifier(agent_results, sub_results)
        meta_text    = _gemini(api_key, meta_prompt, timeout=90)
        meta_result  = _extract_json(meta_text)
    except Exception as e:
        meta_result = {
            "overall_confidence": "MEDIUM",
            "agent_revisions_needed": {
                aid: {
                    "needs_revision": sub_results.get(aid, {}).get("needs_revision", False),
                    "items":    sub_results.get(aid, {}).get("issues", []),
                    "feedback": sub_results.get(aid, {}).get("feedback", ""),
                }
                for aid in ALL_REVISIONABLE
            },
            "reliability_scores": {
                aid: sub_results.get(aid, {}).get("reliability_score", "MEDIUM")
                for aid in ALL_REVISIONABLE
            },
            "verifier_note": "Meta-verification failed (" + str(e) + "); sub-verifier results used.",
            "coherence_score": 0,
        }

    # Merge sub results into meta
    meta_result["sub_verifier_results"] = {
        aid: {
            "confidence":     sub_results.get(aid, {}).get("confidence", "MEDIUM"),
            "issues":         (sub_results.get(aid, {}).get("issues") or [])[:3],
            "needs_revision": sub_results.get(aid, {}).get("needs_revision", False),
        }
        for aid in ALL_REVISIONABLE
    }
    # Propagate sub-verifier revision flags not caught by meta
    meta_rev = meta_result.get("agent_revisions_needed", {})
    for aid in ALL_REVISIONABLE:
        sr = sub_results.get(aid, {})
        if sr.get("needs_revision") and not meta_rev.get(aid, {}).get("needs_revision"):
            meta_rev.setdefault(aid, {})["needs_revision"] = True
            meta_rev[aid]["feedback"] = (
                meta_rev.get(aid, {}).get("feedback", "") + " " +
                sr.get("feedback", "")
            ).strip()
            meta_rev[aid]["items"] = list({
                *(meta_rev.get(aid, {}).get("items") or []),
                *(sr.get("issues") or []),
            })[:5]
    meta_result["agent_revisions_needed"] = meta_rev

    state["verifier"]["status"] = "done"
    state["verifier"]["result"] = meta_result
    _save_job(job_id, user_id, state)

    # ── Verifier: resend flagged items to agents in PARALLEL threads ─────────
    verifier_result = state["verifier"].get("result", {})
    revisions       = verifier_result.get("agent_revisions_needed", {})

    ALL_REVISIONABLE = (
        "performance", "rebalancing", "analyst",
        "thematic", "corporate", "dividend", "health",
    )
    BASE_ARGS = {
        "performance": lambda: (ctx,),
        "rebalancing": lambda: (ctx,),
        "analyst":     lambda: (tickers_str,),
        "thematic":    lambda: (ctx,),
        "corporate":   lambda: (tickers_str,),
        "dividend":    lambda: (ctx, portfolio),
        "health":      lambda: (ctx, portfolio),
    }
    PROMPT_MAP = {
        "performance": _prompt_performance,
        "rebalancing": _prompt_rebalancing,
        "thematic":    _prompt_thematic,
        "corporate":   _prompt_corporate,
        "dividend":    _prompt_dividend,
        "health":      _prompt_health,
    }

    def _revise_agent(agent_id, feedback, items):
        """Revision worker - runs in its own thread, parallel to siblings."""
        orig_result = json.dumps(state[agent_id].get("result", {}))
        orig_prompt = PROMPT_MAP.get(agent_id, lambda *a: "")(*BASE_ARGS.get(agent_id, lambda: ())())
        sep = chr(10)
        revision_txt = sep.join([
            "REVISION REQUEST - Verifier flagged issues in your previous output.",
            "",
            "VERIFIER FEEDBACK: " + str(feedback),
            "SPECIFIC ISSUES: " + json.dumps(items),
            "",
            "YOUR PREVIOUS OUTPUT:",
            orig_result,
            "",
            "Provide a fully corrected version in the same JSON format as before.",
            "",
            orig_prompt,
        ])
        state[agent_id]["status"] = "revising"
        _save_job(job_id, user_id, state)
        try:
            text   = _gemini(api_key, revision_txt, timeout=90)
            result = _extract_json(text)
            state[agent_id]["status"]  = "done"
            state[agent_id]["result"]  = result
            state[agent_id]["revised"] = True
            agent_results[agent_id]    = result
        except Exception as e:
            state[agent_id]["status"]         = "done"   # keep original on error
            state[agent_id]["revision_error"] = str(e)
        _save_job(job_id, user_id, state)

    # ── Iterative verify → revise loop (max 3 retries per agent) ────────────
    MAX_RETRIES  = 3
    retry_counts = {aid: 0 for aid in ALL_REVISIONABLE}  # track per-agent retries
    pass_number  = 1

    # Start with first-pass verifier result
    verifier_result = state["verifier"].get("result", {})
    all_revised_aids = []

    while True:
        # Check which agents still need revision and haven't hit max retries
        revisions = verifier_result.get("agent_revisions_needed", {})
        to_revise = []
        for aid in ALL_REVISIONABLE:
            rev = revisions.get(aid, {})
            if rev.get("needs_revision") and (rev.get("feedback") or rev.get("items")):
                if retry_counts[aid] < MAX_RETRIES:
                    to_revise.append((aid, rev.get("feedback",""), rev.get("items",[])))

        if not to_revise:
            break  # All agents pass or hit max retries

        # Spawn parallel revision threads for all agents that need it this pass
        rev_threads = []
        for aid, feedback, items in to_revise:
            retry_counts[aid] += 1
            state[aid]["retry_count"] = retry_counts[aid]
            t = threading.Thread(
                target=_revise_agent,
                args=(aid, feedback, items),
                daemon=True,
            )
            rev_threads.append(t)
            t.start()
            all_revised_aids.append(aid)

        for t in rev_threads:
            t.join(timeout=120)

        # Refresh agent_results with latest revisions
        agent_results = {
            aid: state[aid].get("result", {})
            for aid in ALL_REVISIONABLE
        }

        # Run verifier again on revised outputs
        pass_number += 1
        state["verifier"]["status"] = "running"
        state["verifier"]["pass"]   = pass_number
        _save_job(job_id, user_id, state)

        revised_this_pass = [aid for aid, _, _ in to_revise]
        retry_note = (
            "VERIFICATION PASS " + str(pass_number) + ". "
            "Agents revised this pass: " + ", ".join(revised_this_pass) + ". "
            "Retry counts: " + ", ".join(f"{a}={retry_counts[a]}" for a in revised_this_pass) + ". "
            "Only flag agents still failing. Agents at max retries (" + str(MAX_RETRIES) + ") must be accepted as-is."
        )
        try:
            v_prompt = _prompt_verifier(agent_results, note=retry_note)
            v_text   = _gemini(api_key, v_prompt, timeout=90)
            v_result = _extract_json(v_text)

            # Agents that hit max retries — force-clear needs_revision
            needs_rev = v_result.get("agent_revisions_needed", {})
            for aid in ALL_REVISIONABLE:
                if retry_counts[aid] >= MAX_RETRIES and needs_rev.get(aid, {}).get("needs_revision"):
                    needs_rev[aid]["needs_revision"] = False
                    needs_rev[aid]["forced_accept"]  = True
            v_result["agent_revisions_needed"] = needs_rev

            first_result = state["verifier"].get("result", {})
            state["verifier"]["result"] = {
                **v_result,
                "passes_completed":    pass_number,
                "revised_agents":      list(set(all_revised_aids)),
                "retry_counts":        {k:v for k,v in retry_counts.items() if v>0},
                "forced_accepted":     [a for a in ALL_REVISIONABLE if retry_counts[a]>=MAX_RETRIES],
                "first_pass_history":  first_result.get("agent_revisions_needed", {}),
            }
            state["verifier"]["status"] = "done"
            verifier_result = state["verifier"]["result"]
        except Exception as e:
            state["verifier"]["status"] = "done"
            state["verifier"]["loop_error"] = str(e)
            break

        _save_job(job_id, user_id, state)

    # Final agent_results for summary
    agent_results = {
        aid: state[aid].get("result", {})
        for aid in ALL_REVISIONABLE
    }
    verifier_result = state["verifier"].get("result", {})

    # ── Agent 9: Summary — uses latest agent data + verified findings ─────────
    run_agent("summary", _prompt_summary,
              agent_results, verifier_result)

    # Save final review to config FIRST (before marking complete)
    # so cfg is ready when the UI polls and sees status=completed
    from db import cfg_set
    final   = state["summary"].get("result") or {}
    agents_data = {
        aid: state[aid].get("result", {})
        for aid in ("performance","rebalancing","analyst","thematic",
                    "corporate","dividend","health","verifier","summary")
        if state.get(aid)
    }
    payload = {
        "date":    datetime.today().strftime("%Y-%m-%d"),
        "agentic": True,
        "agents":  agents_data,
        "headline":         final.get("headline", "Portfolio Review"),
        "overall_rating":   final.get("overall_rating", "NEUTRAL"),
        "executive_summary":final.get("executive_summary", ""),
        "top_3_actions":    final.get("top_3_actions", []),
        "watchlist":        final.get("watchlist", []),
        "risks_to_watch":   final.get("risks_to_watch", []),
        "opportunities":    final.get("opportunities", []),
        "portfolio_badges": final.get("portfolio_badges", []),
        "investor_profile": final.get("investor_profile", {}),
        "kes_impact_note":  final.get("kes_impact_note", ""),
        "income_summary":   final.get("income_summary", {}),
        "next_review_focus":final.get("next_review_focus", ""),
        **final,
    }
    cfg_set(user_id, "last_review", json.dumps(payload))

    # Mark job complete AFTER cfg is saved
    state["_finished_at"] = datetime.utcnow().isoformat()
    _save_job(job_id, user_id, state)


def start_pipeline(user_id, api_key, portfolio, savings):
    """Start the pipeline in a background thread. Returns job_id."""
    job_id = str(uuid.uuid4())
    t = threading.Thread(
        target=run_pipeline,
        args=(job_id, user_id, api_key, portfolio, savings),
        daemon=True,
    )
    t.start()
    return job_id
