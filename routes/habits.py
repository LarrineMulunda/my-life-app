"""
routes/habits.py — Habit tracker module.
Create habits, mark days done, set weekly targets, track streaks and insights.
"""
from datetime import datetime, date, timedelta
from decimal import Decimal
from flask import Blueprint, request, jsonify
from flask_login import current_user
from db import get_db, ph, is_pg
from routes.auth import approved_required

bp = Blueprint("habits", __name__)

def _today(): return datetime.today().strftime("%Y-%m-%d")
def uid():    return current_user.id
def p():      return ph()

def _clean(d):
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


# ── Streak + insight calculation ──────────────────────────────────────────────

def _calc_stats(log_dates, target_per_week, created_date):
    """
    log_dates: sorted list of 'YYYY-MM-DD' strings where habit was done.
    Returns dict of stats: current_streak, best_streak, this_week, last_7,
    completion_rate, total_done.
    """
    done = set(log_dates)
    today = date.today()

    # Current streak — consecutive days ending today or yesterday
    current = 0
    d = today
    # allow streak to count if today not yet done but yesterday was
    if today.isoformat() not in done and (today - timedelta(days=1)).isoformat() in done:
        d = today - timedelta(days=1)
    while d.isoformat() in done:
        current += 1
        d -= timedelta(days=1)

    # Best streak ever
    best = 0
    if done:
        sorted_dates = sorted(date.fromisoformat(x) for x in done)
        run = 1
        best = 1
        for i in range(1, len(sorted_dates)):
            if (sorted_dates[i] - sorted_dates[i-1]).days == 1:
                run += 1
                best = max(best, run)
            else:
                run = 1

    # This week (Mon–Sun)
    week_start = today - timedelta(days=today.weekday())
    this_week = sum(1 for x in done
                    if week_start <= date.fromisoformat(x) <= today)

    # Last 7 days
    last_7 = sum(1 for x in done
                 if (today - date.fromisoformat(x)).days < 7
                 and date.fromisoformat(x) <= today)

    # Completion rate since created
    try:
        start = date.fromisoformat(str(created_date)[:10])
    except Exception:
        start = today
    total_days = max(1, (today - start).days + 1)
    weeks = max(1, total_days / 7)
    expected = weeks * (target_per_week or 7)
    completion_rate = round(min(100, len(done) / expected * 100), 1) if expected else 0

    return {
        "current_streak":  current,
        "best_streak":     best,
        "this_week":       this_week,
        "last_7":          last_7,
        "total_done":      len(done),
        "target_per_week": target_per_week,
        "week_progress":   round(this_week / target_per_week * 100, 0) if target_per_week else 0,
        "completion_rate": completion_rate,
        "on_track":        this_week >= target_per_week,
    }


# ── Habits CRUD ───────────────────────────────────────────────────────────────

@bp.route("/api/habits")
@approved_required
def get_habits():
    """Return all habits with their logs and computed stats."""
    conn = get_db()
    try:
        active_val = "TRUE" if is_pg() else "1"
        habits = _fetchall(conn,
            f"""SELECT * FROM habits
                WHERE user_id={p()} AND active={active_val}
                ORDER BY created_date""",
            (uid(),))
        for h in habits:
            logs = _fetchall(conn,
                f"""SELECT date FROM habit_logs
                    WHERE habit_id={p()} AND done={active_val}
                    ORDER BY date""",
                (h["id"],))
            log_dates       = [str(l["date"]) for l in logs]
            h["log_dates"]  = log_dates
            h["stats"]      = _calc_stats(
                log_dates, h.get("target_per_week", 7), h.get("created_date"))
    finally:
        conn.close()
    return jsonify({"habits": habits})

@bp.route("/api/habits", methods=["POST"])
@approved_required
def add_habit():
    d = request.json or {}
    try:
        _require(d, "name")
        target = int(d.get("target_per_week", 7))
        if not (1 <= target <= 7):
            raise ValueError("target_per_week must be between 1 and 7")
    except (ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    conn = get_db()
    try:
        active_val = True if is_pg() else 1
        _exec(conn,
            f"""INSERT INTO habits
                (user_id,name,icon,color,target_per_week,category,note,active,created_date)
                VALUES ({p()},{p()},{p()},{p()},{p()},{p()},{p()},{p()},{p()})""",
            (uid(), d["name"], d.get("icon", "✓"), d.get("color", "#C9A84C"),
             target, d.get("category", "General"), d.get("note", ""),
             active_val, _today()))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})

@bp.route("/api/habits/<int:hid>", methods=["PUT"])
@approved_required
def edit_habit(hid):
    d = request.json or {}
    try:
        _require(d, "name")
        target = int(d.get("target_per_week", 7))
    except (ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    conn = get_db()
    try:
        _exec(conn,
            f"""UPDATE habits
                SET name={p()},icon={p()},color={p()},target_per_week={p()},
                    category={p()},note={p()}
                WHERE id={p()} AND user_id={p()}""",
            (d["name"], d.get("icon", "✓"), d.get("color", "#C9A84C"),
             target, d.get("category", "General"), d.get("note", ""),
             hid, uid()))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})

@bp.route("/api/habits/<int:hid>", methods=["DELETE"])
@approved_required
def delete_habit(hid):
    conn = get_db()
    try:
        owner = _fetchone(conn,
            f"SELECT user_id FROM habits WHERE id={p()}", (hid,))
        if not owner or owner["user_id"] != uid():
            return jsonify({"error": "Not found"}), 404
        _exec(conn, f"DELETE FROM habit_logs WHERE habit_id={p()}", (hid,))
        _exec(conn, f"DELETE FROM habits WHERE id={p()}", (hid,))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})


# ── Toggle a day done / not done ──────────────────────────────────────────────

@bp.route("/api/habits/<int:hid>/toggle", methods=["POST"])
@approved_required
def toggle_day(hid):
    d   = request.json or {}
    day = d.get("date", _today())
    conn = get_db()
    try:
        # Verify ownership
        habit = _fetchone(conn,
            f"SELECT user_id FROM habits WHERE id={p()}", (hid,))
        if not habit or habit["user_id"] != uid():
            return jsonify({"error": "Habit not found"}), 404

        existing = _fetchone(conn,
            f"SELECT id FROM habit_logs WHERE habit_id={p()} AND date={p()}",
            (hid, day))

        if existing:
            # Toggle off — remove the log
            _exec(conn, f"DELETE FROM habit_logs WHERE id={p()}", (existing["id"],))
            state = False
        else:
            # Toggle on — add the log
            done_val = True if is_pg() else 1
            _exec(conn,
                f"""INSERT INTO habit_logs (habit_id,user_id,date,done)
                    VALUES ({p()},{p()},{p()},{p()})""",
                (hid, uid(), day, done_val))
            state = True
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True, "date": day, "done": state})


# ── Insights across all habits ────────────────────────────────────────────────

@bp.route("/api/habits/insights")
@approved_required
def habit_insights():
    conn = get_db()
    try:
        active_val = "TRUE" if is_pg() else "1"
        habits = _fetchall(conn,
            f"SELECT * FROM habits WHERE user_id={p()} AND active={active_val}",
            (uid(),))
        all_stats = []
        for h in habits:
            logs = _fetchall(conn,
                f"SELECT date FROM habit_logs WHERE habit_id={p()} AND done={active_val}",
                (h["id"],))
            log_dates = [str(l["date"]) for l in logs]
            stats = _calc_stats(
                log_dates, h.get("target_per_week", 7), h.get("created_date"))
            all_stats.append({"name": h["name"], "icon": h.get("icon", "✓"), **stats})
    finally:
        conn.close()

    total_habits      = len(all_stats)
    on_track          = sum(1 for s in all_stats if s["on_track"])
    best_streak       = max((s["best_streak"] for s in all_stats), default=0)
    longest_current   = max((s["current_streak"] for s in all_stats), default=0)
    avg_completion    = round(
        sum(s["completion_rate"] for s in all_stats) / total_habits, 1
    ) if total_habits else 0

    # Build a 7-day completion heatmap across all habits
    today = date.today()
    week_data = []
    conn = get_db()
    try:
        active_val = "TRUE" if is_pg() else "1"
        for i in range(6, -1, -1):
            day = (today - timedelta(days=i)).isoformat()
            cur = conn.cursor()
            cur.execute(
                f"""SELECT COUNT(*) as c FROM habit_logs
                    WHERE user_id={p()} AND date={p()} AND done={active_val}""",
                (uid(), day))
            row = cur.fetchone()
            count = (row["c"] if is_pg() else row[0]) if row else 0
            week_data.append({"date": day, "count": int(count)})
    finally:
        conn.close()

    return jsonify({
        "total_habits":     total_habits,
        "on_track":         on_track,
        "best_streak":      best_streak,
        "longest_current":  longest_current,
        "avg_completion":   avg_completion,
        "week_heatmap":     week_data,
        "per_habit":        all_stats,
    })
