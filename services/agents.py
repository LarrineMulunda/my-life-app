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
        "desc": "Tracks dividends, earnings, splits and other actions",
    },
    {
        "id":   "verifier",
        "num":  6,
        "name": "Fact Verifier",
        "icon": "✅",
        "desc": "Cross-checks all agent findings for accuracy",
    },
    {
        "id":   "summary",
        "num":  7,
        "name": "Executive Summary",
        "icon": "✦",
        "desc": "Synthesises all insights into actionable recommendations",
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
    return f"""You are an expert portfolio performance analyst. Today is {datetime.today().strftime('%Y-%m-%d')}.
Analyse the following Kenyan investor's portfolio and provide a data-driven performance summary.

{ctx}

Use Google Search to verify current prices and market context.

Return ONLY valid JSON (no markdown, no code fences):
{{
  "week_summary": "one punchy headline",
  "overall_rating": "STRONG|GOOD|NEUTRAL|CAUTION|REVIEW",
  "portfolio_health": "2-3 sentence overall assessment",
  "top_performers": [{{"ticker":"","exchange":"","return_pct":0,"note":""}}],
  "underperformers": [{{"ticker":"","exchange":"","return_pct":0,"note":""}}],
  "sector_breakdown": [{{"sector":"","allocation_pct":0,"comment":""}}],
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
    {{"priority":"HIGH|MEDIUM|LOW","action":"BUY|SELL|TRIM|ADD","ticker":"","exchange":"",
     "rationale":"","suggested_amount_pct":0}}
  ],
  "ideal_allocation": [{{"category":"","target_pct":0,"current_pct":0}}],
  "rebalancing_summary": "2-3 sentence actionable summary"
}}"""


def _prompt_analyst(tickers_str):
    return f"""You are a senior equity research analyst. Today is {datetime.today().strftime('%Y-%m-%d')}.

For the following stocks and ETFs: {tickers_str}

Use Google Search to find the LATEST (within 30 days):
1. Analyst consensus ratings and price targets
2. Recent upgrades or downgrades
3. Top 3 high-conviction stock ideas from major banks/analysts right now
4. Any stocks on analyst "best ideas" or "top picks" lists

Return ONLY valid JSON (no markdown, no code fences):
{{
  "analyst_views": [
    {{"ticker":"","exchange":"","consensus":"BUY|HOLD|SELL|MIXED",
      "avg_price_target":"","upside_pct":0,
      "recent_changes":[{{"analyst":"","action":"UPGRADE|DOWNGRADE|INITIATE","date":"","target":""}}],
      "key_thesis":""}}
  ],
  "hot_picks": [
    {{"ticker":"","exchange":"","source":"","rating":"","price_target":"","thesis":"","catalyst":""}}
  ],
  "sector_sentiment": [{{"sector":"","sentiment":"BULLISH|NEUTRAL|BEARISH","note":""}}],
  "market_context": "2-3 sentences on current market environment relevant to this portfolio"
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
      "instruments": [
        {{"ticker":"","exchange":"","type":"stock|etf","why":"","entry_note":""}}
      ]
    }}
  ],
  "africa_specific": [
    {{"opportunity":"","rationale":"","instruments":[{{"ticker":"","exchange":"","note":""}}]}}
  ],
  "gaps_in_portfolio": ["list gaps vs megatrend exposure"],
  "thematic_summary": "2-3 sentence forward-looking outlook"
}}"""


def _prompt_corporate(tickers_str):
    return f"""You are a corporate actions specialist. Today is {datetime.today().strftime('%Y-%m-%d')}.

For the following tickers: {tickers_str}

Use Google Search to find ALL of the following within the next 60 days or recently announced:
1. Dividend declarations, ex-dividend dates, payment dates
2. Upcoming earnings dates
3. Stock splits or consolidations
4. Rights issues or new share offerings
5. M&A activity, delistings, or major corporate announcements

Return ONLY valid JSON (no markdown, no code fences):
{{
  "dividends": [
    {{"ticker":"","exchange":"","declared_amount":"","currency":"","ex_date":"","payment_date":"","type":"interim|final|special","yield_pct":0}}
  ],
  "earnings": [
    {{"ticker":"","exchange":"","expected_date":"","period":"","consensus_eps":"","note":""}}
  ],
  "corporate_actions": [
    {{"ticker":"","exchange":"","action_type":"split|rights|merger|delisting|other","details":"","date":"","impact":""}}
  ],
  "nse_specific": [
    {{"ticker":"","action":"","date":"","details":""}}
  ],
  "key_dates_next_30_days": [{{"date":"","ticker":"","event":"","importance":"HIGH|MEDIUM|LOW"}}]
}}"""


def _prompt_verifier(agent_results):
    results_str = json.dumps(agent_results, indent=2)
    return f"""You are a meticulous fact-checker and investment compliance reviewer. Today is {datetime.today().strftime('%Y-%m-%d')}.

Review the following outputs from 5 portfolio analysis agents and verify their accuracy.
Use Google Search to spot-check key claims: prices, dates, analyst ratings, corporate actions.

AGENT OUTPUTS:
{results_str}

Check for:
1. Factual errors (wrong prices, incorrect dates, made-up analyst ratings)
2. Contradictions between agents
3. Outdated information presented as current
4. Unrealistic projections or figures

Return ONLY valid JSON (no markdown, no code fences):
{{
  "overall_confidence": "HIGH|MEDIUM|LOW",
  "verified_items": [
    {{"agent":"","claim":"","status":"VERIFIED|UNVERIFIED|INCORRECT","note":""}}
  ],
  "corrections": [
    {{"agent":"","field":"","original":"","corrected":"","source":""}}
  ],
  "flagged_risks": ["list anything that seems off or unverified"],
  "reliability_scores": {{
    "performance": "HIGH|MEDIUM|LOW",
    "rebalancing": "HIGH|MEDIUM|LOW",
    "analyst": "HIGH|MEDIUM|LOW",
    "thematic": "HIGH|MEDIUM|LOW",
    "corporate": "HIGH|MEDIUM|LOW"
  }},
  "verifier_note": "2-3 sentence overall assessment of information quality"
}}"""


def _prompt_summary(agent_results, verifier_result):
    all_str = json.dumps({**agent_results, "verifier": verifier_result}, indent=2)
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

    def run_agent(agent_id, prompt_fn, *args):
        state[agent_id]["status"] = "running"
        state[agent_id]["started"] = datetime.utcnow().isoformat()
        _save_job(job_id, user_id, state)
        try:
            prompt = prompt_fn(*args)
            text   = _gemini(api_key, prompt, timeout=90)
            result = _extract_json(text)
            state[agent_id]["status"] = "done"
            state[agent_id]["result"] = result
        except Exception as e:
            state[agent_id]["status"] = "error"
            state[agent_id]["error"]  = str(e)
        state[agent_id]["finished"] = datetime.utcnow().isoformat()
        _save_job(job_id, user_id, state)

    # ── Agents 1-5 in parallel ────────────────────────────────────────────────
    threads = [
        threading.Thread(target=run_agent, args=("performance", _prompt_performance, ctx)),
        threading.Thread(target=run_agent, args=("rebalancing", _prompt_rebalancing, ctx)),
        threading.Thread(target=run_agent, args=("analyst",     _prompt_analyst,     tickers_str)),
        threading.Thread(target=run_agent, args=("thematic",    _prompt_thematic,    ctx)),
        threading.Thread(target=run_agent, args=("corporate",   _prompt_corporate,   tickers_str)),
    ]
    for t in threads:
        t.daemon = True
        t.start()
    for t in threads:
        t.join(timeout=120)  # wait up to 120s per agent

    # ── Agent 6: Verifier (waits for 1-5) ────────────────────────────────────
    agent_results = {
        aid: state[aid].get("result", {})
        for aid in ("performance","rebalancing","analyst","thematic","corporate")
    }
    run_agent("verifier", _prompt_verifier, agent_results)

    # ── Agent 7: Summary (waits for verifier) ────────────────────────────────
    run_agent("summary", _prompt_summary,
              agent_results, state["verifier"].get("result", {}))

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
