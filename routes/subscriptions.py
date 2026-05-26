"""Subscription routes — PostgreSQL/SQLite dual, per-user, with auth."""
from datetime import date, datetime
from decimal import Decimal
from flask import Blueprint, request, jsonify
from flask_login import current_user
from db import get_db, ph, is_pg
from routes.auth import approved_required

bp = Blueprint("subscriptions", __name__)

def _today(): return datetime.today().strftime("%Y-%m-%d")
def uid():    return current_user.id
def p():      return ph()

def _clean(d):
    """Convert PostgreSQL date/Decimal to JSON-safe types."""
    for k, v in d.items():
        if isinstance(v, (date, datetime)):
            d[k] = v.isoformat()[:10]
        elif isinstance(v, Decimal):
            d[k] = float(v)
    return d

def _require(d, *keys):
    missing = [k for k in keys if not d.get(k) and d.get(k) != 0]
    if missing:
        raise ValueError(f"Missing: {', '.join(missing)}")

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

def _streak(classes):
    """Compute current and best streak of consecutive attended sessions."""
    attended = [bool(c["attended"]) for c in classes]
    if not attended:
        return 0, 0
    best = cur_run = 0
    for a in attended:
        cur_run = cur_run + 1 if a else 0
        best = max(best, cur_run)
    current = 0
    for a in reversed(attended):
        if a:
            current += 1
        else:
            break
    return current, best

def _enrich(conn, s):
    """Add payments, classes, streak and extra stats to a subscription dict."""
    sid      = s["id"]
    payments = _fetchall(conn,
        f"SELECT * FROM sub_payments WHERE sub_id={p()} ORDER BY date DESC", (sid,))
    s["payments"]   = payments
    s["total_paid"] = sum(float(pay["amount"]) for pay in payments)

    if s["sub_type"] == "classes":
        classes = _fetchall(conn,
            f"SELECT * FROM sub_classes WHERE sub_id={p()} ORDER BY id", (sid,))
        s["classes"]        = classes
        s["total_approved"] = len(classes)
        s["attended"]       = sum(1 for c in classes if c["attended"])
        s["remaining"]      = s["total_approved"] - s["attended"]
        s["current_streak"], s["best_streak"] = _streak(classes)
        s["active_period"]  = None
    else:
        today    = _today()
        active_p = next(
            (pay for pay in payments
             if pay.get("end_date") and str(pay["end_date"]) >= today),
            None)
        s["active_period"]  = active_p
        s["classes"]        = []
        s["current_streak"] = 0
        s["best_streak"]    = 0
    return s

# ── Subscription CRUD ─────────────────────────────────────────────────────────

@bp.route("/api/subscriptions")
@approved_required
def get_subscriptions():
    conn = get_db()
    try:
        subs = _fetchall(conn,
            f"""SELECT * FROM subscriptions
                WHERE user_id={p()}
                ORDER BY active DESC, name""",
            (uid(),))
        subs = [_enrich(conn, s) for s in subs]
    finally:
        conn.close()
    return jsonify({"subscriptions": subs})

@bp.route("/api/subscriptions/expiring")
@approved_required
def expiring():
    days  = int(request.args.get("days", 7))
    today = _today()
    conn  = get_db()
    try:
        if is_pg():
            sql  = f"""
                SELECT s.id, s.name, s.category, p.end_date,
                       (p.end_date - CURRENT_DATE) as days_left
                FROM subscriptions s
                JOIN sub_payments p ON p.sub_id = s.id
                WHERE s.user_id = {p()}
                  AND s.sub_type = 'duration'
                  AND p.end_date >= CURRENT_DATE
                  AND (p.end_date - CURRENT_DATE) <= {p()}
                ORDER BY p.end_date ASC
            """
            rows = _fetchall(conn, sql, (uid(), days))
        else:
            sql  = """
                SELECT s.id, s.name, s.category, p.end_date,
                       julianday(p.end_date) - julianday(?) as days_left
                FROM subscriptions s
                JOIN sub_payments p ON p.sub_id = s.id
                WHERE s.user_id = ?
                  AND s.sub_type = 'duration'
                  AND p.end_date >= ?
                  AND julianday(p.end_date) - julianday(?) <= ?
                ORDER BY p.end_date ASC
            """
            rows = _fetchall(conn, sql, (today, uid(), today, today, days))
    finally:
        conn.close()
    return jsonify({"expiring": rows})

@bp.route("/api/subscriptions/monthly-spend")
@approved_required
def monthly_spend():
    conn = get_db()
    try:
        if is_pg():
            sql  = f"""
                SELECT TO_CHAR(p.date, 'YYYY-MM') as month,
                       SUM(p.amount) as total, s.category
                FROM sub_payments p
                JOIN subscriptions s ON s.id = p.sub_id
                WHERE s.user_id = {p()}
                GROUP BY month, s.category
                ORDER BY month DESC
            """
            by_month = _fetchall(conn, sql, (uid(),))
        else:
            sql  = """
                SELECT strftime('%Y-%m', p.date) as month,
                       SUM(p.amount) as total, s.category
                FROM sub_payments p
                JOIN subscriptions s ON s.id = p.sub_id
                WHERE s.user_id = ?
                GROUP BY month, s.category
                ORDER BY month DESC
            """
            by_month = _fetchall(conn, sql, (uid(),))
    finally:
        conn.close()

    months = {}
    for r in by_month:
        m = r["month"]
        if m not in months:
            months[m] = {"month": m, "total": 0, "categories": {}}
        months[m]["total"] = round(months[m]["total"] + float(r["total"]), 2)
        months[m]["categories"][r["category"]] = round(
            months[m]["categories"].get(r["category"], 0) + float(r["total"]), 2)
    return jsonify({
        "monthly": sorted(months.values(), key=lambda x: x["month"], reverse=True)
    })

@bp.route("/api/subscriptions", methods=["POST"])
@approved_required
def add_subscription():
    d = request.json or {}
    try:
        _require(d, "name","category","sub_type")
        if d["sub_type"] not in ("classes","duration"):
            raise ValueError("sub_type must be classes or duration")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    conn         = get_db()
    active_val   = True if is_pg() else 1
    try:
        _exec(conn,
            f"""INSERT INTO subscriptions
                (user_id, name, category, sub_type, note, active, created_date)
                VALUES ({p()},{p()},{p()},{p()},{p()},{p()},{p()})""",
            (uid(), d["name"], d["category"], d["sub_type"],
             d.get("note",""), active_val, _today()))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})

@bp.route("/api/subscriptions/<int:sid>", methods=["PUT"])
@approved_required
def edit_subscription(sid):
    d = request.json or {}
    try:
        _require(d, "name","category")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    conn = get_db()
    try:
        _exec(conn,
            f"""UPDATE subscriptions
                SET name={p()}, category={p()}, note={p()}
                WHERE id={p()} AND user_id={p()}""",
            (d["name"], d["category"], d.get("note",""), sid, uid()))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})

@bp.route("/api/subscriptions/<int:sid>", methods=["DELETE"])
@approved_required
def delete_subscription(sid):
    conn = get_db()
    try:
        owner = _fetchone(conn,
            f"SELECT user_id FROM subscriptions WHERE id={p()}", (sid,))
        if not owner or owner["user_id"] != uid():
            return jsonify({"error": "Not found"}), 404
        _exec(conn, f"DELETE FROM sub_classes  WHERE sub_id={p()}", (sid,))
        _exec(conn, f"DELETE FROM sub_payments WHERE sub_id={p()}", (sid,))
        _exec(conn, f"DELETE FROM subscriptions WHERE id={p()}", (sid,))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})

# ── Payments ──────────────────────────────────────────────────────────────────

@bp.route("/api/subscriptions/<int:sid>/payment", methods=["POST"])
@approved_required
def add_payment(sid):
    d = request.json or {}
    try:
        _require(d, "amount","date")
        float(d["amount"])
    except (ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400

    conn = get_db()
    try:
        sub = _fetchone(conn,
            f"SELECT sub_type, user_id FROM subscriptions WHERE id={p()}", (sid,))
        if not sub or sub["user_id"] != uid():
            return jsonify({"error": "Subscription not found"}), 404
        if sub["sub_type"] == "classes" and not d.get("classes_bought"):
            return jsonify({"error": "classes_bought required for session subscriptions"}), 400
        if sub["sub_type"] == "duration" and not (d.get("start_date") and d.get("end_date")):
            return jsonify({"error": "start_date and end_date required for duration subscriptions"}), 400

        _exec(conn,
            f"""INSERT INTO sub_payments
                (sub_id, amount, classes_bought, start_date, end_date, note, date)
                VALUES ({p()},{p()},{p()},{p()},{p()},{p()},{p()})""",
            (sid, float(d["amount"]),
             int(d["classes_bought"]) if sub["sub_type"]=="classes" else None,
             d.get("start_date") or None,
             d.get("end_date") or None,
             d.get("note",""), d["date"]))

        # Get new payment ID
        if is_pg():
            pid = _fetchone(conn, "SELECT lastval() as id")["id"]
        else:
            cur = conn.cursor()
            cur.execute("SELECT last_insert_rowid()")
            pid = cur.fetchone()[0]

        if sub["sub_type"] == "classes":
            for _ in range(int(d["classes_bought"])):
                _exec(conn,
                    f"INSERT INTO sub_classes (payment_id, sub_id) VALUES ({p()},{p()})",
                    (pid, sid))

        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})

# ── Class attendance ──────────────────────────────────────────────────────────

@bp.route("/api/subscriptions/class/<int:cid>/attend", methods=["PUT"])
@approved_required
def attend_class(cid):
    d             = request.json or {}
    attended_val  = True  if is_pg() else 1
    skipped_val   = False if is_pg() else 0
    conn = get_db()
    try:
        _exec(conn,
            f"""UPDATE sub_classes
                SET attended={p()}, scheduled_date={p()}, note={p()}
                WHERE id={p()}""",
            (attended_val if d.get("attended") else skipped_val,
             d.get("scheduled_date") or None,
             d.get("note",""), cid))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})

@bp.route("/api/subscriptions/class/<int:cid>", methods=["DELETE"])
@approved_required
def delete_class(cid):
    conn = get_db()
    try:
        _exec(conn, f"DELETE FROM sub_classes WHERE id={p()}", (cid,))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})