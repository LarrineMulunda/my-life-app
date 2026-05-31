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

def _gemini(api_key, prompt, timeout=90):
    if not HAS_REQUESTS:
        raise RuntimeError("requests not installed")
    resp = _req.post(
        f"{GEMINI_URL}?key={api_key}",
        json={
            "contents":           [{"parts": [{"text": prompt}]}],
            "tools":              [{"google_search": {}}],
            "generationConfig":   {"temperature": 0.3},
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

    sav_lines = [f"  {k}: KES {v:,.0f}" for k, v in (savings or {}).items()]

    return (
        f"Today: {today}\n"
        f"Portfolio total cost: KES {portfolio.get('total_cost',0):,.0f}\n"
        f"Portfolio market value: KES {portfolio.get('total_market',0):,.0f}\n"
        f"Unrealised gain/loss: KES {portfolio.get('total_gain',0):,.0f} "
        f"({portfolio.get('portfolio_pct',0):.1f}%)\n"
        f"Realised gains: KES {portfolio.get('total_realized',0):,.0f}\n\n"
        f"HOLDINGS ({len(holds)}):\n" + "\n".join(holds) + "\n\n"
        f"OTHER ASSETS:\n" + ("\n".join(sav_lines) or "  None")
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
      ]
    }}
  ],
  "africa_specific": [
    {{"opportunity":"","rationale":"","current_exposure":"NONE|LOW|ADEQUATE|HIGH","instruments":[{{"ticker":"","exchange":"","note":""}}]}}
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



def _prompt_dividend(ctx, portfolio):
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

    return f"""You are a dividend income analyst. Today is {today}.

This investor holds the following positions:
{holdings_str}

Portfolio total market value: KES {portfolio.get('total_market', 0):,.0f}

Use Google Search to research dividend history and upcoming payments for EACH holding.

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


def _prompt_health(ctx, portfolio):
    """Portfolio health: Sharpe ratio, stress testing, cross-asset metrics."""
    today = datetime.today().strftime("%Y-%m-%d")

    # Categorise holdings
    stocks = [h for h in portfolio.get("holdings",[]) if h.get("exchange") not in ("CRYPTO",)]
    crypto = [h for h in portfolio.get("holdings",[]) if h.get("exchange") == "CRYPTO"]

    return f"""You are a portfolio risk analyst and quantitative strategist. Today is {today}.

{ctx}

This portfolio may include: stocks, ETFs, bonds, MMFs, crypto, farming/agriculture.

Use Google Search to research:
1. Current risk-free rate (Kenya 91-day T-bill rate)
2. Volatility of individual holdings
3. Correlation between asset classes
4. Stress scenarios (2008 crash, COVID crash, 2022 rate hikes, Kenya shilling depreciation)

Compute or estimate:
- Sharpe Ratio = (portfolio return - risk-free rate) / portfolio std deviation
- Max Drawdown: worst peak-to-trough decline scenario
- Beta to global markets
- Stress test: how much would this portfolio lose in each scenario

Return ONLY valid JSON (no markdown, no code fences):
{{
  "health_score": 0,
  "health_breakdown": {{
    "diversification": 0,
    "return_quality":  0,
    "momentum":        0,
    "income":          0,
    "risk":            0
  }},
  "health_commentary": "2-sentence plain-English summary of the score",
  "risk_metrics": {{
    "sharpe_ratio":          0,
    "risk_free_rate_pct":    0,
    "estimated_volatility":  "LOW|MEDIUM|HIGH|VERY_HIGH",
    "beta_to_global":        0,
    "concentration_risk":    "LOW|MEDIUM|HIGH",
    "currency_risk":         "LOW|MEDIUM|HIGH",
    "liquidity_risk":        "LOW|MEDIUM|HIGH"
  }},
  "stress_tests": [
    {{
      "scenario":       "",
      "description":    "",
      "estimated_loss_pct": 0,
      "estimated_loss_kes": 0,
      "most_affected":  ["ticker1","ticker2"],
      "defensive_assets": ["what would protect the portfolio"]
    }}
  ],
  "asset_class_health": [
    {{
      "class":       "",
      "allocation_pct": 0,
      "health":      "STRONG|GOOD|NEUTRAL|WEAK",
      "comment":     ""
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
  "improvement_suggestions": ["list 3 specific actions to improve portfolio health"]
}}

BADGE CRITERIA (award if portfolio qualifies):
- "Diversification Master" 🌍 : holdings across 3+ exchanges
- "Dividend Investor" 💰 : 3+ dividend-paying stocks
- "Growth Hunter" 🚀 : 50%+ in growth stocks/ETFs
- "Africa First" 🌍 : 40%+ in African markets (NSE, JSE, etc)
- "Tech Forward" 💻 : 30%+ in tech stocks/ETFs
- "Income Builder" 📈 : portfolio yield > 3%
- "Risk Manager" 🛡️ : well-diversified, Sharpe > 1
- "Long Term Thinker" ⏳ : average holding age > 1 year
- "Global Citizen" 🌐 : holdings in 4+ currencies"""


def _prompt_analyst_multithreaded(ticker, exchange, portfolio_context):
    """Per-ticker analyst prompt for multithreaded execution."""
    today = datetime.today().strftime("%Y-%m-%d")
    return f"""You are a senior equity analyst. Today is {today}.

Analyse {ticker} ({exchange}) using MULTIPLE sources to avoid bias.
Poll: Goldman Sachs, Morgan Stanley, JPMorgan, UBS, Citi, BofA, Morningstar, CFRA, Bloomberg Intelligence.
For African stocks also check: Rand Merchant Bank, Stanbic, AIB-AXYS, CBA Securities.

Return ONLY valid JSON (no markdown):
{{
  "ticker":          "{ticker}",
  "exchange":        "{exchange}",
  "consensus":       "BUY|HOLD|SELL|MIXED",
  "sources_count":   0,
  "sources_list":    [],
  "avg_price_target":"",
  "upside_pct":      0,
  "key_thesis":      "specific investment thesis or null if not found",
  "bull_case":       "",
  "bear_case":       "",
  "recent_changes":  [{{"analyst":"","institution":"","action":"UPGRADE|DOWNGRADE|INITIATE","date":"","target":""}}],
  "data_freshness":  "days since most recent note",
  "skip":            false
}}
If you cannot find substantive analyst coverage from at least 2 sources, set skip=true."""


def _prompt_verifier(agent_results):
    today = datetime.today().strftime("%Y-%m-%d")
    results_str = json.dumps(agent_results, indent=2)
    return f"""You are a meticulous fact-checker and investment compliance reviewer. Today is {today}.

Review the following outputs from 5 portfolio analysis agents and verify accuracy.
Use Google Search to spot-check: prices, analyst ratings, dividend dates, corporate actions.

AGENT OUTPUTS:
{results_str}

Check for:
1. Factual errors (wrong prices, incorrect dates, unverifiable analyst ratings)
2. Contradictions between agents
3. Past-dated corporate actions or dividends presented as future
4. Low-confidence or vague claims

CONFIDENCE RULES:
- Only mark as VERIFIED if you can confirm the claim from at least one external source
- Mark as NEEDS_REVISION if the claim is plausible but unconfirmed
- Mark as INCORRECT if you find contradicting evidence
- For each NEEDS_REVISION or INCORRECT item, provide specific feedback for that agent to fix it

Return ONLY valid JSON (no markdown, no code fences):
{{
  "overall_confidence": "HIGH|MEDIUM|LOW",
  "verified_items": [
    {{
      "agent":"performance|rebalancing|analyst|thematic|corporate",
      "claim":"specific claim being verified",
      "status":"VERIFIED|NEEDS_REVISION|INCORRECT",
      "confidence":"HIGH|MEDIUM|LOW",
      "feedback":"specific correction or improvement needed (required for NEEDS_REVISION/INCORRECT)",
      "source":"where you verified or refuted this"
    }}
  ],
  "agent_revisions_needed": {{
    "performance":  {{"needs_revision": false, "items": [], "feedback": ""}},
    "rebalancing":  {{"needs_revision": false, "items": [], "feedback": ""}},
    "analyst":      {{"needs_revision": false, "items": [], "feedback": ""}},
    "thematic":     {{"needs_revision": false, "items": [], "feedback": ""}},
    "corporate":    {{"needs_revision": false, "items": [], "feedback": ""}}
  }},
  "high_confidence_only": {{
    "analyst_views":   ["only tickers where analyst data is HIGH confidence"],
    "dividends":       ["only future dividends with HIGH confidence dates"],
    "corporate_actions":["only HIGH confidence future actions"],
    "hot_picks":       ["only HIGH confidence picks with verified thesis"]
  }},
  "reliability_scores": {{
    "performance": "HIGH|MEDIUM|LOW",
    "rebalancing": "HIGH|MEDIUM|LOW",
    "analyst": "HIGH|MEDIUM|LOW",
    "thematic": "HIGH|MEDIUM|LOW",
    "corporate": "HIGH|MEDIUM|LOW"
  }},
  "verifier_note": "2-3 sentence overall quality assessment"
}}"""


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
            cur.execute("""
                INSERT INTO review_jobs (id,user_id,status,started_at,finished_at,agents)
                VALUES (%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT(id) DO UPDATE SET
                  status=EXCLUDED.status, finished_at=EXCLUDED.finished_at,
                  agents=EXCLUDED.agents
            """, (job_id, user_id, status,
                  agents_state.get("_started_at",""), finished, agents_json))
        else:
            cur.execute("""
                INSERT OR REPLACE INTO review_jobs (id,user_id,status,started_at,finished_at,agents)
                VALUES (?,?,?,?,?,?)
            """, (job_id, user_id, status,
                  agents_state.get("_started_at",""), finished, agents_json))
        conn.commit()
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
        if d.get("agents"):
            try:
                d["agents"] = json.loads(d["agents"])
            except Exception:
                pass
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
        return [dict(r) for r in cur.fetchall()]
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

    # ── Agents 1-7 in parallel ────────────────────────────────────────────────
    # Analyst runs per-ticker in sub-threads (multithreaded)
    def run_analyst_multithreaded():
        """Run one Gemini call per holding in parallel, merge results."""
        holdings = portfolio.get("holdings", [])
        if not holdings:
            state["analyst"]["status"] = "done"
            state["analyst"]["result"] = {"analyst_views":[],"hot_picks":[],"sector_sentiment":[],"market_context":"No holdings."}
            _save_job(job_id, user_id, state)
            return

        state["analyst"]["status"] = "running"
        _save_job(job_id, user_id, state)

        per_ticker_results = {}
        lock = threading.Lock()

        def fetch_one(h):
            ticker = h["ticker"]
            exch   = h["exchange"]
            try:
                prompt = _prompt_analyst_multithreaded(ticker, exch, ctx)
                text   = _gemini(api_key, prompt, timeout=60)
                result = _extract_json(text)
                if not result.get("skip", False) and result.get("key_thesis"):
                    with lock:
                        per_ticker_results[ticker] = result
            except Exception as e:
                pass  # Skip tickers where Gemini fails

        ticker_threads = [
            threading.Thread(target=fetch_one, args=(h,), daemon=True)
            for h in holdings
        ]
        for t in ticker_threads: t.start()
        for t in ticker_threads: t.join(timeout=75)

        # Merge per-ticker results into analyst format
        analyst_views = list(per_ticker_results.values())
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
        threading.Thread(target=run_agent,                 args=("thematic",    _prompt_thematic,    ctx)),
        threading.Thread(target=run_agent,                 args=("corporate",   _prompt_corporate, tickers_str)),
        threading.Thread(target=run_agent,                 args=("dividend",    _prompt_dividend,    ctx, portfolio)),
        threading.Thread(target=run_agent,                 args=("health",      _prompt_health,      ctx, portfolio)),
    ]
    for t in threads: t.daemon = True; t.start()
    for t in threads: t.join(timeout=150)

    # ── Agent 6: Verifier (waits for 1-5) ────────────────────────────────────
    agent_results = {
        aid: state[aid].get("result", {})
        for aid in ("performance","rebalancing","analyst","thematic","corporate","dividend","health")
    }
    run_agent("verifier", _prompt_verifier, agent_results)

    # ── Verifier: re-route agents needing revision ───────────────────────────
    verifier_result = state["verifier"].get("result", {})
    revisions = verifier_result.get("agent_revisions_needed", {})

    for agent_id in ("performance","rebalancing","analyst","thematic","corporate"):
        rev = revisions.get(agent_id, {})
        if rev.get("needs_revision") and state[agent_id].get("status") == "done":
            feedback = rev.get("feedback","")
            items    = rev.get("items", [])
            if feedback or items:
                # Build a revised prompt incorporating verifier feedback
                orig_result = json.dumps(state[agent_id].get("result", {}))
                revision_prompt_map = {
                    "performance": _prompt_performance,
                    "rebalancing": _prompt_rebalancing,
                    "thematic":    _prompt_thematic,
                    "corporate":   _prompt_corporate,
                    "dividend":    _prompt_dividend,
                    "health":      _prompt_health,
                }
                base_args = {
                    "performance": (ctx,),
                    "rebalancing": (ctx,),
                    "analyst":     (tickers_str,),
                    "thematic":    (ctx,),
                    "corporate":   (tickers_str,),
                }
                # Create a revision prompt with feedback
                original_prompt = revision_prompt_map[agent_id](*base_args[agent_id])
                revision_prompt = (
                    f"REVISION REQUEST — Your previous output needs correction.\n\n"
                    f"VERIFIER FEEDBACK: {feedback}\n"
                    f"SPECIFIC ISSUES: {json.dumps(items)}\n\n"
                    f"YOUR PREVIOUS OUTPUT:\n{orig_result}\n\n"
                    f"Please provide a corrected version.\n\n"
                    + original_prompt
                )
                state[agent_id]["status"] = "revising"
                _save_job(job_id, user_id, state)
                try:
                    text   = _call(api_key, revision_prompt, timeout=90)
                    result = _extract_json(text)
                    state[agent_id]["status"]   = "done"
                    state[agent_id]["result"]   = result
                    state[agent_id]["revised"]  = True
                    agent_results[agent_id]     = result
                except Exception as e:
                    state[agent_id]["status"]         = "done"  # keep original on error
                    state[agent_id]["revision_error"] = str(e)
                _save_job(job_id, user_id, state)

    # ── Agent 7: Summary (waits for verifier + any revisions) ────────────────
    run_agent("summary", _prompt_summary,
              agent_results, verifier_result)

    # Mark job complete
    state["_finished_at"] = datetime.utcnow().isoformat()
    _save_job(job_id, user_id, state)

    # Save final review to config for the review tab
    from db import cfg_set
    final = state["summary"].get("result", {})
    if final:
        payload = {
            "date":   datetime.today().strftime("%Y-%m-%d"),
            "agentic": True,
            "agents": {
                aid: state[aid].get("result", {})
                for aid in ("performance","rebalancing","analyst",
                            "thematic","corporate","verifier","summary")
            },
            **final,
        }
        cfg_set(user_id, "last_review", json.dumps(payload))


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
