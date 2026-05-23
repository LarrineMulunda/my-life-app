"""Subscription routes — classes and duration tracking with streaks and alerts."""
from datetime import datetime
from flask import Blueprint, request, jsonify
from db import get_db

bp = Blueprint("subscriptions", __name__)

def _today(): return datetime.today().strftime("%Y-%m-%d")

def _require(d, *keys):
    missing = [k for k in keys if not d.get(k) and d.get(k) != 0]
    if missing:
        raise ValueError(f"Missing: {', '.join(missing)}")

def _streak(classes):
    """Compute current and best streak of consecutive attended sessions."""
    attended = [bool(c["attended"]) for c in classes]
    if not attended:
        return 0, 0
    # Best streak
    best = cur_run = 0
    for a in attended:
        cur_run = cur_run + 1 if a else 0
        best = max(best, cur_run)
    # Current streak = trailing run of attended
    current = 0
    for a in reversed(attended):
        if a:
            current += 1
        else:
            break
    return current, best

def _enrich(db, s):
    """Add payments, classes, streak and extra stats to a subscription dict."""
    sid = s["id"]
    payments = [dict(r) for r in db.execute(
        "SELECT * FROM sub_payments WHERE sub_id=? ORDER BY date DESC", (sid,)).fetchall()]
    s["payments"]   = payments
    s["total_paid"] = sum(p["amount"] for p in payments)

    if s["sub_type"] == "classes":
        classes = [dict(r) for r in db.execute(
            "SELECT * FROM sub_classes WHERE sub_id=? ORDER BY id", (sid,)).fetchall()]
        s["classes"]       = classes
        s["total_approved"]= len(classes)
        s["attended"]      = sum(1 for c in classes if c["attended"])
        s["remaining"]     = s["total_approved"] - s["attended"]
        s["current_streak"], s["best_streak"] = _streak(classes)
        s["active_period"] = None
    else:
        today = _today()
        active_p = next((p for p in payments
                         if p.get("end_date") and p["end_date"] >= today), None)
        s["active_period"] = active_p
        s["classes"]       = []
        s["current_streak"]= 0
        s["best_streak"]   = 0
    return s

@bp.route("/api/subscriptions")
def get_subscriptions():
    with get_db() as db:
        subs = [dict(r) for r in db.execute(
            "SELECT * FROM subscriptions ORDER BY active DESC, name").fetchall()]
        subs = [_enrich(db, s) for s in subs]
    return jsonify({"subscriptions": subs})

@bp.route("/api/subscriptions/expiring")
def expiring():
    """Return duration subscriptions expiring within N days (default 7)."""
    days = int(request.args.get("days", 7))
    today = _today()
    with get_db() as db:
        rows = db.execute("""
            SELECT s.id, s.name, s.category, p.end_date,
                   julianday(p.end_date) - julianday(?) as days_left
            FROM subscriptions s
            JOIN sub_payments p ON p.sub_id = s.id
            WHERE s.sub_type = 'duration'
              AND p.end_date >= ?
              AND julianday(p.end_date) - julianday(?) <= ?
            ORDER BY p.end_date ASC
        """, (today, today, today, days)).fetchall()
    return jsonify({"expiring": [dict(r) for r in rows]})

@bp.route("/api/subscriptions/monthly-spend")
def monthly_spend():
    """Total spend per month across all subscriptions, plus per-category breakdown."""
    with get_db() as db:
        by_month = [dict(r) for r in db.execute("""
            SELECT strftime('%Y-%m', p.date) as month,
                   SUM(p.amount) as total,
                   s.category
            FROM sub_payments p
            JOIN subscriptions s ON s.id = p.sub_id
            GROUP BY month, s.category
            ORDER BY month DESC
        """).fetchall()]
    # Pivot into {month: {total, categories: {cat: amount}}}
    months = {}
    for r in by_month:
        m = r["month"]
        if m not in months:
            months[m] = {"month": m, "total": 0, "categories": {}}
        months[m]["total"]                    = round(months[m]["total"] + r["total"], 2)
        months[m]["categories"][r["category"]]= round(
            months[m]["categories"].get(r["category"],0) + r["total"], 2)
    return jsonify({"monthly": sorted(months.values(), key=lambda x: x["month"], reverse=True)})

@bp.route("/api/subscriptions", methods=["POST"])
def add_subscription():
    d = request.json or {}
    try:
        _require(d, "name","category","sub_type")
        if d["sub_type"] not in ("classes","duration"):
            raise ValueError("sub_type must be classes or duration")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    with get_db() as db:
        db.execute("INSERT INTO subscriptions (name,category,sub_type,note,active,created_date) VALUES (?,?,?,?,1,?)",
                   (d["name"],d["category"],d["sub_type"],d.get("note",""),_today()))
    return jsonify({"ok": True})

@bp.route("/api/subscriptions/<int:sid>", methods=["PUT"])
def edit_subscription(sid):
    d = request.json or {}
    try:
        _require(d, "name","category")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    with get_db() as db:
        db.execute("UPDATE subscriptions SET name=?,category=?,note=? WHERE id=?",
                   (d["name"],d["category"],d.get("note",""),sid))
    return jsonify({"ok": True})

@bp.route("/api/subscriptions/<int:sid>", methods=["DELETE"])
def delete_subscription(sid):
    with get_db() as db:
        db.execute("DELETE FROM sub_classes  WHERE sub_id=?", (sid,))
        db.execute("DELETE FROM sub_payments WHERE sub_id=?", (sid,))
        db.execute("DELETE FROM subscriptions WHERE id=?", (sid,))
    return jsonify({"ok": True})

@bp.route("/api/subscriptions/<int:sid>/payment", methods=["POST"])
def add_payment(sid):
    d = request.json or {}
    try:
        _require(d, "amount","date")
        float(d["amount"])
    except (ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    with get_db() as db:
        sub = db.execute("SELECT sub_type FROM subscriptions WHERE id=?", (sid,)).fetchone()
        if not sub:
            return jsonify({"error": "Subscription not found"}), 404
        if sub["sub_type"] == "classes" and not d.get("classes_bought"):
            return jsonify({"error": "classes_bought is required for session subscriptions"}), 400
        if sub["sub_type"] == "duration" and not (d.get("start_date") and d.get("end_date")):
            return jsonify({"error": "start_date and end_date are required for duration subscriptions"}), 400
        cur = db.execute("""
            INSERT INTO sub_payments (sub_id,amount,classes_bought,start_date,end_date,note,date)
            VALUES (?,?,?,?,?,?,?)""",
            (sid, float(d["amount"]),
             int(d["classes_bought"]) if sub["sub_type"]=="classes" else None,
             d.get("start_date"), d.get("end_date"),
             d.get("note",""), d["date"]))
        pid = cur.lastrowid
        if sub["sub_type"] == "classes":
            for _ in range(int(d["classes_bought"])):
                db.execute("INSERT INTO sub_classes (payment_id,sub_id) VALUES (?,?)", (pid,sid))
    return jsonify({"ok": True})

@bp.route("/api/subscriptions/class/<int:cid>/attend", methods=["PUT"])
def attend_class(cid):
    d = request.json or {}
    with get_db() as db:
        db.execute("UPDATE sub_classes SET attended=?,scheduled_date=?,note=? WHERE id=?",
                   (1 if d.get("attended") else 0,
                    d.get("scheduled_date",""), d.get("note",""), cid))
    return jsonify({"ok": True})

@bp.route("/api/subscriptions/class/<int:cid>", methods=["DELETE"])
def delete_class(cid):
    with get_db() as db:
        db.execute("DELETE FROM sub_classes WHERE id=?", (cid,))
    return jsonify({"ok": True})
