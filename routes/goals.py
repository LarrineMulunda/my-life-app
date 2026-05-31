"""
routes/goals.py — Savings Goals + Portfolio Target tracking with trajectory & probability.
"""
import random
from datetime import datetime, date, timedelta
from decimal import Decimal
from flask import Blueprint, request, jsonify
from flask_login import current_user
from db import get_db, ph, is_pg, fx_get_all
from routes.auth import approved_required

bp = Blueprint("goals", __name__)

GOAL_CATEGORIES = [
    "Emergency Fund","House / Property","Car","Education",
    "Retirement","Travel","Wedding","Business","Investment",
    "Gadget / Purchase","Other",
]
GOAL_ICONS = [
    "🎯","🏠","🚗","📚","🏦","✈️","💍","💼","📈",
    "💻","🌍","💰","🏋️","🎓","👶","🏖️","🎸","⚽",
]


# ── Shared helpers ─────────────────────────────────────────────────────────────
def uid():    return current_user.id
def p():      return ph()
def _today(): return datetime.today().strftime("%Y-%m-%d")

def _clean(d):
    for k, v in d.items():
        if isinstance(v, (date, datetime)): d[k] = v.isoformat()[:10]
        elif isinstance(v, Decimal):        d[k] = float(v)
    return d

def _fetchall(conn, sql, params=()):
    cur = conn.cursor(); cur.execute(sql, params)
    return [_clean(dict(r)) for r in cur.fetchall()]

def _fetchone(conn, sql, params=()):
    cur = conn.cursor(); cur.execute(sql, params)
    r = cur.fetchone(); return _clean(dict(r)) if r else None

def _exec(conn, sql, params=()):
    cur = conn.cursor(); cur.execute(sql, params); return cur

def _require(d, *keys):
    missing = [k for k in keys if d.get(k) is None or d.get(k) == ""]
    if missing: raise ValueError("Missing: " + ", ".join(missing))

def _to_kes(amount, currency, rates):
    if currency == "KES" or not currency: return float(amount)
    return float(amount) * float(rates.get(currency, 1.0))


# ══ SAVINGS GOAL PROGRESS ═════════════════════════════════════════════════════
def _get_linked_value(conn, link_type, link_label, user_id, fx_rates):
    """
    Get the current KES value of the linked source.
    link_type: "savings_label" | "savings_class" | "stocks" | "stocks_ticker"
    link_label: the label/class name or ticker symbol
    Returns: (value_kes, display_label)
    """
    try:
        if link_type == "savings_label":
            rows = _fetchall(conn, f"""
                SELECT amount, type, currency FROM savings
                WHERE user_id={p()} AND label={p()}
            """, (user_id, link_label))
            val = sum(
                # deposits and interest add to balance; withdrawals subtract
                _to_kes(float(r["amount"]), r.get("currency","KES"), fx_rates)
                if r["type"] in ("deposit", "interest")
                else -_to_kes(float(r["amount"]), r.get("currency","KES"), fx_rates)
                for r in rows)
            return round(val, 2), f"Other Assets: {link_label}"

        elif link_type == "savings_class":
            rows = _fetchall(conn, f"""
                SELECT amount, type, currency FROM savings
                WHERE user_id={p()} AND asset_class={p()}
            """, (user_id, link_label))
            val = sum(
                _to_kes(float(r["amount"]), r.get("currency","KES"), fx_rates)
                if r["type"] in ("deposit", "interest")
                else -_to_kes(float(r["amount"]), r.get("currency","KES"), fx_rates)
                for r in rows)
            return round(val, 2), f"Asset Class: {link_label}"

        elif link_type == "stocks":
            # Total portfolio stock market value
            lots   = _fetchall(conn,
                f"SELECT * FROM stock_lots WHERE user_id={p()} AND shares > 0", (user_id,))
            prices = _fetchall(conn, "SELECT * FROM global_prices ORDER BY date DESC")
            EXCUR  = {"NSE":"KES","NYSE":"USD","NASDAQ":"USD","LSE":"GBP",
                      "JSE":"ZAR","EURONEXT":"EUR","HKEX":"HKD","CRYPTO":"USD"}
            latest = {}
            for pr in prices:
                k = (pr["ticker"], pr.get("exchange","NSE"))
                if k not in latest: latest[k] = float(pr["price"])
            val = 0.0
            for lot in lots:
                exch = lot.get("exchange","NSE")
                cur  = lot.get("currency") or EXCUR.get(exch,"KES")
                price = latest.get((lot["ticker"], exch))
                cost  = float(lot["shares"]) * float(lot["purchase_price"])
                val  += _to_kes(float(lot["shares"]) * price if price else cost, cur, fx_rates)
            return round(val, 2), "Stock Portfolio (market value)"

        elif link_type == "stocks_ticker":
            lots   = _fetchall(conn,
                f"SELECT * FROM stock_lots WHERE user_id={p()} AND UPPER(ticker)={p()} AND shares > 0",
                (user_id, link_label.upper()))
            prices = _fetchall(conn,
                f"SELECT * FROM global_prices WHERE UPPER(ticker)={p()} ORDER BY date DESC",
                (link_label.upper(),))
            EXCUR  = {"NSE":"KES","NYSE":"USD","NASDAQ":"USD","LSE":"GBP",
                      "JSE":"ZAR","EURONEXT":"EUR","HKEX":"HKD","CRYPTO":"USD"}
            latest_price = float(prices[0]["price"]) if prices else None
            val = 0.0
            for lot in lots:
                exch = lot.get("exchange","NSE")
                cur  = lot.get("currency") or EXCUR.get(exch,"KES")
                cost = float(lot["shares"]) * float(lot["purchase_price"])
                val += _to_kes(
                    float(lot["shares"]) * latest_price if latest_price else cost,
                    cur, fx_rates)
            return round(val, 2), f"Stock: {link_label}"

    except Exception as e:
        pass
    return None, None


def _calc_progress(goal, contributions, fx_rates, auto_value_kes=None):
    """
    auto_value_kes: if goal is linked to savings label or stocks,
    pass the current auto-read KES value here to override manual contributions.
    """
    today      = date.today()
    created    = date.fromisoformat(str(goal["created_date"])[:10])
    target_kes = _to_kes(goal["target_amount"], goal["target_currency"], fx_rates)
    if auto_value_kes is not None:
        saved_kes = float(auto_value_kes)
    else:
        saved_kes = sum(_to_kes(c["amount"], c["currency"], fx_rates) for c in contributions)
    pct        = round(saved_kes / target_kes * 100, 1) if target_kes else 0
    remaining  = max(0.0, target_kes - saved_kes)
    months_el  = max(0.1, (today - created).days / 30.44)
    monthly    = saved_kes / months_el

    tdate = months_left = days_left = needed = None
    if goal.get("target_date"):
        try:
            tdate     = date.fromisoformat(str(goal["target_date"])[:10])
            days_left = (tdate - today).days
            months_left = max(0.0, days_left / 30.44)
            if months_left > 0: needed = round(remaining / months_left, 2)
        except Exception: pass

    proj_date = proj_months = None
    if monthly > 0 and remaining > 0:
        proj_months = remaining / monthly
        proj_date   = (today + timedelta(days=int(proj_months * 30.44))).isoformat()

    if pct >= 100:           status = "completed"
    elif tdate and days_left is not None:
        if days_left < 0:    status = "overdue"
        elif needed and monthly >= needed * 0.9: status = "on_track"
        elif needed and monthly >= needed * 0.5: status = "behind"
        else:                status = "at_risk"
    else:                    status = "in_progress"

    return {
        "target_kes": round(target_kes,2), "saved_kes": round(saved_kes,2),
        "remaining_kes": round(remaining,2), "pct_complete": min(100.0, pct),
        "monthly_rate": round(monthly,2), "monthly_needed": needed,
        "projected_date": proj_date,
        "projected_months": round(proj_months,1) if proj_months else None,
        "days_left": days_left, "months_left": round(months_left,1) if months_left else None,
        "status": status, "contributions_count": len(contributions),
        "last_contribution": max((c["date"] for c in contributions), default=None),
    }


# ══ PORTFOLIO TARGET HELPERS ══════════════════════════════════════════════════
EXCUR = {"NSE":"KES","NYSE":"USD","NASDAQ":"USD","LSE":"GBP",
         "JSE":"ZAR","EURONEXT":"EUR","HKEX":"HKD","CRYPTO":"USD"}

def _get_portfolio_value(user_id):
    fx = fx_get_all()
    conn = get_db()
    try:
        lots   = _fetchall(conn, f"SELECT * FROM stock_lots WHERE user_id={ph()} AND shares > 0", (user_id,))
        prices = _fetchall(conn, "SELECT * FROM global_prices ORDER BY date DESC")
        latest = {}
        for pr in prices:
            k = (pr["ticker"], pr.get("exchange","NSE"))
            if k not in latest: latest[k] = float(pr["price"])

        stock_v = stock_c = 0.0
        for lot in lots:
            exch = lot.get("exchange","NSE")
            cur  = lot.get("currency") or EXCUR.get(exch,"KES")
            cost = float(lot["shares"]) * float(lot["purchase_price"])
            stock_c += _to_kes(cost, cur, fx)
            price = latest.get((lot["ticker"], exch))
            stock_v += _to_kes(float(lot["shares"]) * price, cur, fx) if price else _to_kes(cost, cur, fx)

        savings = _fetchall(conn, f"SELECT * FROM savings WHERE user_id={ph()}", (user_id,))
        sav_v = 0.0
        for r in savings:
            cur  = r.get("currency") or "KES"
            sign = 1 if r["type"] == "deposit" else -1
            sav_v += _to_kes(float(r["amount"]), cur, fx) * sign

        return {"total": round(stock_v+sav_v,2), "stock_value": round(stock_v,2),
                "stock_cost": round(stock_c,2), "sav_value": round(sav_v,2), "fx_rates": fx}
    finally:
        conn.close()

def _get_snapshots(user_id, limit=24):
    conn = get_db()
    try:
        rows = _fetchall(conn,
            f"SELECT date, total_value FROM portfolio_snapshots WHERE user_id={ph()} ORDER BY date DESC LIMIT {ph()}",
            (user_id, limit))
        return sorted(rows, key=lambda r: str(r["date"]))
    finally:
        conn.close()

def _monthly_growth_rate(snapshots):
    DEFAULT = 0.008
    if len(snapshots) < 3: return DEFAULT
    changes = []
    for i in range(1, len(snapshots)):
        prev = float(snapshots[i-1]["total_value"])
        curr = float(snapshots[i]["total_value"])
        if prev > 0 and curr > 0: changes.append((curr-prev)/prev)
    if not changes: return DEFAULT
    changes.sort()
    trim = max(1, len(changes)//10)
    trimmed = changes[trim:-trim] if len(changes) > 2*trim else changes
    return max(-0.05, min(0.20, sum(trimmed)/len(trimmed)))

def _project_hit_date(current, target, growth_rate, monthly_contrib):
    if current >= target: return _today()
    if growth_rate <= 0 and monthly_contrib <= 0: return None
    value = current; r = growth_rate; c = monthly_contrib; today = date.today()
    for m in range(1, 601):
        value = value*(1+r)+c
        if value >= target:
            return (today + timedelta(days=int(m*30.44))).isoformat()
    return None

def _probability(current, target, months, growth_rate, monthly_contrib, required_monthly):
    if months <= 0: return 100.0 if current >= target else 0.0
    if target <= 0: return 100.0
    random.seed(42)
    hits = 0; vol = 0.03
    for _ in range(1000):
        value = current
        for _ in range(int(months)):
            r = random.gauss(growth_rate, vol)
            value = value*(1+r)+monthly_contrib
        if value >= target: hits += 1
    raw = hits / 10.0
    if required_monthly > 0 and monthly_contrib > 0:
        ratio = monthly_contrib / required_monthly
        raw = max(5.0, min(98.0, raw + (ratio-1)*15))
    return round(raw, 1)

def _prob_label(prob):
    if prob >= 85: return {"label":"HIGH",    "color":"var(--green)"}
    if prob >= 60: return {"label":"LIKELY",  "color":"var(--green)"}
    if prob >= 40: return {"label":"POSSIBLE","color":"var(--gold)"}
    if prob >= 20: return {"label":"UNLIKELY","color":"var(--red)"}
    return           {"label":"LOW",     "color":"var(--red)"}

def _scenarios(current, target, months, growth_rate, gap):
    base = max(0.0, gap/months) if months > 0 else gap
    results = []
    for label, mult, radj, desc in [
        ("Conservative", 0.5, -0.002, "50% of required savings, slightly lower returns"),
        ("Base Case",    1.0,  0.000, "Required savings rate, current growth trajectory"),
        ("Optimistic",   1.5, +0.003, "150% of required savings, slightly higher returns"),
    ]:
        c = base*mult; r = growth_rate+radj; n = months
        if n > 0 and abs(r) > 0.0001:
            fv = current*((1+r)**n) + c*(((1+r)**n-1)/r)
        elif n > 0:
            fv = current + c*n
        else:
            fv = current
        pct = round(min(100, fv/target*100), 1) if target else 100
        short = target - fv
        results.append({
            "label":label,"description":desc,"monthly_save":round(c,2),
            "final_value":round(fv,2),"pct_of_target":pct,
            "shortfall":max(0,round(short,2)),"surplus":max(0,round(-short,2)),
            "hits_target":fv>=target,
        })
    return results

def _insights(pct, prob, gap, req_monthly, curr_monthly, months_left,
              days_left, proj_value, target_kes, hit_date):
    ins = []
    if pct >= 100:
        ins.append({"type":"success","text":"🎉 Target already reached! Consider raising your goal."})
        return ins
    if days_left is not None and days_left < 0:
        ins.append({"type":"overdue","text":"⚠ Deadline has passed. Update the target date or increase contributions."})

    shortfall = target_kes - proj_value
    if shortfall > 0:
        ins.append({"type":"warning","text":
            f"At your current pace you will be KES {shortfall:,.0f} short by the deadline. "
            f"Contribute an extra KES {req_monthly:,.0f}/month to close the gap."})
    else:
        ins.append({"type":"positive","text":
            f"At your current pace your portfolio will exceed the target by KES {abs(shortfall):,.0f}. Keep it up!"})

    if req_monthly > 0:
        weekly = round(req_monthly/4.3, 0)
        ins.append({"type":"action","text":
            f"Required: KES {req_monthly:,.0f}/month (KES {weekly:,.0f}/week). "
            + ("Your estimated current rate is below this — consider automating a monthly transfer."
               if curr_monthly < req_monthly*0.9
               else "Your current contribution rate is sufficient.")})
    elif req_monthly == 0.0:
        ins.append({"type":"positive","text":
            "Portfolio growth alone should carry you to the target. No extra contributions needed."})

    if prob >= 70:
        ins.append({"type":"positive","text":f"Hit probability: {prob}% — you are on track."})
    elif prob >= 40:
        ins.append({"type":"warning","text":
            f"Hit probability: {prob}% — possible but tight. Increase contributions or extend deadline."})
    else:
        ins.append({"type":"alert","text":
            f"Hit probability: {prob}% — the gap is large relative to the timeline. "
            "Consider a longer deadline, higher contributions, or a lower target."})

    if hit_date and days_left is not None and days_left > 0:
        hit   = date.fromisoformat(hit_date)
        dline = date.today() + timedelta(days=days_left)
        diff  = (hit - dline).days
        if diff > 30:
            ins.append({"type":"warning","text":
                f"Projected to reach target {round(diff/30.44,1)} months after your deadline ({hit_date})."})
        else:
            ins.append({"type":"positive","text":f"Projected to reach target by {hit_date} — on or before deadline."})
    return ins

def _calc_target_progress(target, current_value, snapshots, fx_rates):
    today         = date.today()
    target_kes    = _to_kes(target["target_amount"], target["target_currency"], fx_rates)
    gap           = max(0.0, target_kes - current_value)
    pct           = round(min(100.0, current_value/target_kes*100), 1) if target_kes else 0

    tdate         = date.fromisoformat(str(target["target_date"])[:10])
    days_left     = (tdate - today).days
    months_left   = max(0.0, days_left/30.44)
    created       = date.fromisoformat(str(target["created_date"])[:10])
    months_el     = max(0.1, (today - created).days/30.44)

    gr = _monthly_growth_rate(snapshots)

    # Required monthly contribution
    req_monthly = 0.0
    if months_left > 0:
        n = months_left; r = gr
        if abs(r) > 0.0001:
            fv_pv = current_value*((1+r)**n)
            if fv_pv < target_kes:
                factor = ((1+r)**n-1)/r
                req_monthly = max(0.0, (target_kes-fv_pv)/factor)
        else:
            req_monthly = gap/n if n > 0 else gap

    # Estimate current monthly contribution from snapshot history
    curr_monthly = 0.0
    if len(snapshots) >= 2:
        recent = float(snapshots[-1]["total_value"])-float(snapshots[-2]["total_value"])
        mb = max(0.1, (date.fromisoformat(str(snapshots[-1]["date"])[:10]) -
                       date.fromisoformat(str(snapshots[-2]["date"])[:10])).days/30.44)
        market_g = float(snapshots[-2]["total_value"])*gr*mb
        curr_monthly = max(0.0, (recent-market_g)/mb)

    prob = _probability(current_value, target_kes, months_left, gr, curr_monthly, req_monthly)

    # Projected value at deadline at current trajectory
    n = months_left; r = gr; c = curr_monthly
    if n > 0 and abs(r) > 0.0001:
        proj_at_deadline = current_value*((1+r)**n) + c*(((1+r)**n-1)/r)
    elif n > 0:
        proj_at_deadline = current_value + c*n
    else:
        proj_at_deadline = current_value

    hit_date = _project_hit_date(current_value, target_kes, gr, curr_monthly)

    status = (
        "achieved"   if pct >= 100 else
        "overdue"    if days_left < 0 else
        "on_track"   if prob >= 70 else
        "possible"   if prob >= 40 else
        "at_risk"
    )

    return {
        "target_kes":           round(target_kes,2),
        "current_value":        round(current_value,2),
        "gap":                  round(gap,2),
        "pct_complete":         pct,
        "days_left":            days_left,
        "months_left":          round(months_left,1),
        "required_monthly":     round(req_monthly,2),
        "monthly_contrib_est":  round(curr_monthly,2),
        "monthly_growth_rate":  round(gr*100,2),
        "proj_at_deadline":     round(proj_at_deadline,2),
        "proj_vs_target":       round(proj_at_deadline-target_kes,2),
        "hit_date":             hit_date,
        "probability":          prob,
        "probability_label":    _prob_label(prob),
        "insights":             _insights(pct, prob, gap, req_monthly, curr_monthly,
                                          months_left, days_left, proj_at_deadline,
                                          target_kes, hit_date),
        "scenarios":            _scenarios(current_value, target_kes, months_left, gr, gap),
        "snapshot_count":       len(snapshots),
        "on_track":             prob >= 60,
        "status":               status,
    }


# ══ PORTFOLIO TARGET API ══════════════════════════════════════════════════════
@bp.route("/api/targets")
@approved_required
def get_targets():
    fx    = fx_get_all()
    conn  = get_db()
    try:
        av = "TRUE" if is_pg() else "1"
        targets = _fetchall(conn,
            f"SELECT * FROM portfolio_targets WHERE user_id={p()} AND active={av} ORDER BY target_date",
            (uid(),))
    finally:
        conn.close()
    portfolio = _get_portfolio_value(uid())
    snapshots = _get_snapshots(uid())
    curr      = portfolio["total"]
    for t in targets:
        t["progress"] = _calc_target_progress(t, curr, snapshots, fx)
    return jsonify({
        "targets": targets, "current_value": curr,
        "stock_value": portfolio["stock_value"],
        "sav_value": portfolio["sav_value"],
        "snapshot_count": len(snapshots),
    })

@bp.route("/api/targets", methods=["POST"])
@approved_required
def add_target():
    d = request.json or {}
    try:
        _require(d, "name","target_amount","target_date")
        amt = float(d["target_amount"])
        if amt <= 0: raise ValueError("target_amount must be positive")
        date.fromisoformat(d["target_date"])
    except (ValueError,TypeError) as e:
        return jsonify({"error":str(e)}),400
    conn = get_db()
    try:
        av = True if is_pg() else 1
        _exec(conn, f"""
            INSERT INTO portfolio_targets
                (user_id,name,target_amount,target_currency,target_date,note,active,created_date)
            VALUES ({p()},{p()},{p()},{p()},{p()},{p()},{p()},{p()})
        """, (uid(),d["name"].strip(),amt,d.get("target_currency","KES"),
              d["target_date"],d.get("note","").strip(),av,_today()))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok":True})

@bp.route("/api/targets/<int:tid>", methods=["PUT"])
@approved_required
def edit_target(tid):
    d = request.json or {}
    try:
        _require(d,"name","target_amount","target_date")
    except ValueError as e:
        return jsonify({"error":str(e)}),400
    conn = get_db()
    try:
        _exec(conn, f"""
            UPDATE portfolio_targets
            SET name={p()},target_amount={p()},target_currency={p()},target_date={p()},note={p()}
            WHERE id={p()} AND user_id={p()}
        """, (d["name"].strip(),float(d["target_amount"]),
              d.get("target_currency","KES"),d["target_date"],
              d.get("note","").strip(),tid,uid()))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok":True})

@bp.route("/api/targets/<int:tid>", methods=["DELETE"])
@approved_required
def delete_target(tid):
    conn = get_db()
    try:
        _exec(conn,
            f"DELETE FROM portfolio_targets WHERE id={p()} AND user_id={p()}",
            (tid,uid()))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok":True})


# ══ SAVINGS GOALS API ═════════════════════════════════════════════════════════
@bp.route("/api/goals")
@approved_required
def get_goals():
    fx = fx_get_all(); conn = get_db()
    try:
        av = "TRUE" if is_pg() else "1"
        goals = _fetchall(conn,
            f"SELECT * FROM goals WHERE user_id={p()} AND active={av} ORDER BY created_date DESC",
            (uid(),))
        for g in goals:
            contribs = _fetchall(conn,
                f"SELECT * FROM goal_contributions WHERE goal_id={p()} ORDER BY date",(g["id"],))
            g["contributions"] = contribs

            # If linked to a source, compute auto_value_kes from it
            g["auto_value_kes"] = None
            g["auto_value_label"] = None
            if g.get("link_type"):
                g["auto_value_kes"], g["auto_value_label"] = _get_linked_value(
                    conn, g["link_type"], g.get("link_label") or "", uid(), fx)

            g["progress"] = _calc_progress(g, contribs, fx, g["auto_value_kes"])
    finally:
        conn.close()
    return jsonify({"goals":goals,"categories":GOAL_CATEGORIES,"icons":GOAL_ICONS})

@bp.route("/api/goals", methods=["POST"])
@approved_required
def add_goal():
    d = request.json or {}
    try:
        _require(d,"name","target_amount")
        amt = float(d["target_amount"])
        if amt <= 0: raise ValueError("target_amount must be positive")
    except (ValueError,TypeError) as e:
        return jsonify({"error":str(e)}),400
    conn = get_db()
    try:
        av = True if is_pg() else 1
        _exec(conn, f"""
            INSERT INTO goals
                (user_id,name,icon,color,category,target_amount,target_currency,
                 target_date,note,active,created_date,link_type,link_label)
            VALUES ({p()},{p()},{p()},{p()},{p()},{p()},{p()},{p()},{p()},{p()},{p()},{p()},{p()})
        """, (uid(),d["name"],d.get("icon","🎯"),d.get("color","#C9A84C"),
              d.get("category","General"),amt,d.get("target_currency","KES"),
              d.get("target_date") or None,d.get("note",""),av,_today(),
              d.get("link_type") or None, d.get("link_label") or None))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok":True})

@bp.route("/api/goals/<int:gid>", methods=["PUT"])
@approved_required
def edit_goal(gid):
    d = request.json or {}
    try:
        _require(d,"name","target_amount")
    except ValueError as e:
        return jsonify({"error":str(e)}),400
    conn = get_db()
    try:
        _exec(conn, f"""
            UPDATE goals
            SET name={p()},icon={p()},color={p()},category={p()},
                target_amount={p()},target_currency={p()},target_date={p()},
                note={p()},link_type={p()},link_label={p()}
            WHERE id={p()} AND user_id={p()}
        """, (d["name"],d.get("icon","🎯"),d.get("color","#C9A84C"),
              d.get("category","General"),float(d["target_amount"]),
              d.get("target_currency","KES"),d.get("target_date") or None,
              d.get("note",""),d.get("link_type") or None,
              d.get("link_label") or None,gid,uid()))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok":True})

@bp.route("/api/goals/<int:gid>", methods=["DELETE"])
@approved_required
def delete_goal(gid):
    conn = get_db()
    try:
        _exec(conn, f"DELETE FROM goal_contributions WHERE goal_id={p()} AND user_id={p()}",(gid,uid()))
        _exec(conn, f"DELETE FROM goals WHERE id={p()} AND user_id={p()}",(gid,uid()))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok":True})

@bp.route("/api/goals/<int:gid>/archive", methods=["POST"])
@approved_required
def archive_goal(gid):
    inact = "FALSE" if is_pg() else "0"
    conn = get_db()
    try:
        _exec(conn, f"UPDATE goals SET active={inact} WHERE id={p()} AND user_id={p()}",(gid,uid()))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok":True})

@bp.route("/api/goals/<int:gid>/contribute", methods=["POST"])
@approved_required
def add_contribution(gid):
    d = request.json or {}
    try:
        _require(d,"amount","date")
        amt = float(d["amount"])
        if amt <= 0: raise ValueError("amount must be positive")
    except (ValueError,TypeError) as e:
        return jsonify({"error":str(e)}),400
    conn = get_db()
    try:
        goal = _fetchone(conn, f"SELECT user_id FROM goals WHERE id={p()}",(gid,))
        if not goal or goal["user_id"] != uid():
            return jsonify({"error":"Goal not found"}),404
        _exec(conn, f"""
            INSERT INTO goal_contributions (goal_id,user_id,amount,currency,date,note)
            VALUES ({p()},{p()},{p()},{p()},{p()},{p()})
        """, (gid,uid(),amt,d.get("currency","KES"),d["date"],d.get("note","")))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok":True})

@bp.route("/api/goals/<int:gid>/contribute/<int:cid>", methods=["DELETE"])
@approved_required
def delete_contribution(gid, cid):
    conn = get_db()
    try:
        _exec(conn,
            f"DELETE FROM goal_contributions WHERE id={p()} AND goal_id={p()} AND user_id={p()}",
            (cid,gid,uid()))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok":True})

@bp.route("/api/goals/insights")
@approved_required
def goal_insights():
    fx = fx_get_all(); conn = get_db()
    try:
        av = "TRUE" if is_pg() else "1"
        goals = _fetchall(conn,
            f"SELECT * FROM goals WHERE user_id={p()} AND active={av}",(uid(),))
        all_p = []
        for g in goals:
            contribs = _fetchall(conn,
                f"SELECT * FROM goal_contributions WHERE goal_id={p()}",(g["id"],))
            prog = _calc_progress(g, contribs, fx)
            all_p.append({"id":g["id"],"name":g["name"],"icon":g["icon"],"color":g["color"],**prog})
    finally:
        conn.close()
    total = len(all_p)
    t_t = sum(x["target_kes"] for x in all_p)
    t_s = sum(x["saved_kes"]  for x in all_p)
    return jsonify({
        "total_goals": total,
        "completed":   sum(1 for x in all_p if x["status"]=="completed"),
        "on_track":    sum(1 for x in all_p if x["status"]=="on_track"),
        "total_target":round(t_t,2), "total_saved":round(t_s,2),
        "overall_pct": round(t_s/t_t*100,1) if t_t else 0,
        "per_goal":    all_p,
    })


@bp.route("/api/savings-labels")
@approved_required
def savings_labels():
    """Return savings labels, asset classes, and stock tickers for goal linking."""
    conn = get_db()
    try:
        labels = _fetchall(conn,
            f"SELECT DISTINCT label, asset_class FROM savings WHERE user_id={p()} ORDER BY label",
            (uid(),))
        classes = _fetchall(conn,
            f"SELECT DISTINCT asset_class FROM savings WHERE user_id={p()} ORDER BY asset_class",
            (uid(),))
        tickers = _fetchall(conn,
            f"SELECT DISTINCT ticker, COALESCE(exchange,\'NSE\') as exchange FROM stock_lots WHERE user_id={p()} AND shares > 0 ORDER BY ticker",
            (uid(),))
    finally:
        conn.close()
    return jsonify({
        "labels":  labels,
        "classes": [r["asset_class"] for r in classes],
        "tickers": tickers,
    })
