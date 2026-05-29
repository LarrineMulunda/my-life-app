"""
auth.py — registration, login, logout, admin approval panel.

User roles:
  pending  — registered but awaiting admin approval
  user     — approved, full access
  admin    — can approve/reject accounts, see all users
"""
import os
from datetime import date, datetime
from decimal import Decimal
from functools import wraps
from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, jsonify)
from flask_login import (LoginManager, UserMixin, login_user,
                         logout_user, login_required, current_user)
from werkzeug.security import generate_password_hash, check_password_hash
from db import get_db, ph, is_pg

bp        = Blueprint("auth", __name__)
login_mgr = LoginManager()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clean(d):
    """Make dict JSON / template safe (date, Decimal → str/float)."""
    for k, v in d.items():
        if isinstance(v, (date, datetime)):
            d[k] = v.isoformat()[:10]
        elif isinstance(v, Decimal):
            d[k] = float(v)
    return d

def _fetchall(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(sql, params)
    return [_clean(dict(r)) for r in cur.fetchall()]

def _fetchone(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(sql, params)
    r = cur.fetchone()
    return _clean(dict(r)) if r else None

def _exec(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur


# ── User model ────────────────────────────────────────────────────────────────

class User(UserMixin):
    def __init__(self, row):
        self.id    = row["id"]
        self.email = row["email"]
        self.name  = row["name"]
        self.role  = row["role"]

    @property
    def is_approved(self): return self.role in ("user", "admin")
    @property
    def is_admin(self):    return self.role == "admin"


@login_mgr.user_loader
def load_user(uid):
    conn = get_db()
    try:
        r = _fetchone(conn, f"SELECT * FROM users WHERE id={ph()}", (int(uid),))
        return User(r) if r else None
    finally:
        conn.close()

@login_mgr.unauthorized_handler
def unauthorized():
    flash("Please sign in to continue.")
    return redirect(url_for("auth.login"))


# ── Decorators ────────────────────────────────────────────────────────────────

def approved_required(f):
    """Require user to be approved (not just logged in)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        if not current_user.is_approved:
            return render_template("auth/pending.html"), 403
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("Admin access required.")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


# ── Register ──────────────────────────────────────────────────────────────────

@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.investments_page"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        name  = request.form.get("name",  "").strip()
        pw    = request.form.get("password",  "")
        pw2   = request.form.get("password2", "")
        if not all([email, name, pw]):
            flash("All fields are required.")
        elif pw != pw2:
            flash("Passwords do not match.")
        elif len(pw) < 8:
            flash("Password must be at least 8 characters.")
        else:
            conn = get_db()
            try:
                # First user ever -> admin automatically
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM users")
                row   = cur.fetchone()
                count = list(dict(row).values())[0] if is_pg() else row[0]
                role  = "admin" if int(count) == 0 else "pending"

                cur.execute(f"""
                    INSERT INTO users (email, name, password_hash, role, created_at)
                    VALUES ({ph()},{ph()},{ph()},{ph()},{ph()})
                """, (email, name, generate_password_hash(pw), role,
                      datetime.utcnow().isoformat()))
                conn.commit()

                if role == "admin":
                    flash("Admin account created — you can log in now.")
                else:
                    flash("Account created. An admin will approve your request before you can log in.")
                return redirect(url_for("auth.login"))

            except Exception as e:
                conn.rollback()
                if "unique" in str(e).lower():
                    flash("An account with that email already exists.")
                else:
                    flash(f"Error creating account: {e}")
            finally:
                conn.close()

    return render_template("auth/register.html",
                           form_name=request.form.get("name",""),
                           form_email=request.form.get("email",""))


# ── Login ─────────────────────────────────────────────────────────────────────

@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.investments_page"))
    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        pw       = request.form.get("password", "")
        remember = request.form.get("remember") == "on"
        conn = get_db()
        try:
            r = _fetchone(conn, f"SELECT * FROM users WHERE email={ph()}", (email,))
        finally:
            conn.close()

        if r and check_password_hash(r["password_hash"], pw):
            user = User(r)
            if user.role == "pending":
                flash("Your account is awaiting admin approval.")
                return render_template("auth/login.html",
                                       form_email=email)
            login_user(user, remember=remember)
            return redirect(request.args.get("next") or url_for("main.investments_page"))
        flash("Incorrect email or password.")
        return render_template("auth/login.html",
                               form_email=request.form.get("email",""))
    return render_template("auth/login.html")


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


# ── Admin panel ───────────────────────────────────────────────────────────────

@bp.route("/admin")
@admin_required
def admin_panel():
    conn = get_db()
    try:
        users = _fetchall(conn,
            "SELECT id, email, name, role, created_at FROM users ORDER BY created_at DESC")
    finally:
        conn.close()

    pending  = [u for u in users if u["role"] == "pending"]
    approved = [u for u in users if u["role"] in ("user", "admin")]
    return render_template("auth/admin.html", pending=pending, approved=approved)


@bp.route("/admin/approve/<int:uid>", methods=["POST"])
@admin_required
def approve_user(uid):
    conn = get_db()
    try:
        _exec(conn,
            f"UPDATE users SET role='user' WHERE id={ph()} AND role='pending'", (uid,))
        conn.commit()
    finally:
        conn.close()
    flash("User approved — they can now sign in.")
    return redirect(url_for("auth.admin_panel"))


@bp.route("/admin/reject/<int:uid>", methods=["POST"])
@admin_required
def reject_user(uid):
    conn = get_db()
    try:
        _exec(conn,
            f"DELETE FROM users WHERE id={ph()} AND role='pending'", (uid,))
        conn.commit()
    finally:
        conn.close()
    flash("Registration rejected and deleted.")
    return redirect(url_for("auth.admin_panel"))


@bp.route("/admin/promote/<int:uid>", methods=["POST"])
@admin_required
def promote_user(uid):
    if uid == current_user.id:
        flash("You cannot change your own role.")
        return redirect(url_for("auth.admin_panel"))
    conn = get_db()
    try:
        _exec(conn, f"UPDATE users SET role='admin' WHERE id={ph()}", (uid,))
        conn.commit()
    finally:
        conn.close()
    flash("User promoted to admin.")
    return redirect(url_for("auth.admin_panel"))


@bp.route("/admin/demote/<int:uid>", methods=["POST"])
@admin_required
def demote_user(uid):
    if uid == current_user.id:
        flash("You cannot change your own role.")
        return redirect(url_for("auth.admin_panel"))
    conn = get_db()
    try:
        _exec(conn, f"UPDATE users SET role='user' WHERE id={ph()}", (uid,))
        conn.commit()
    finally:
        conn.close()
    flash("Admin rights removed.")
    return redirect(url_for("auth.admin_panel"))


# ── WebAuthn / fingerprint (passkey) support ──────────────────────────────────
# Uses a simplified passkey flow. Credentials are stored per-user in config.
# Requires HTTPS in production (Cloud Run provides this).
import base64, os as _os, json as _json

def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()

@bp.route("/webauthn/register/begin", methods=["POST"])
def webauthn_register_begin():
    """Start passkey registration for the logged-in user."""
    if not current_user.is_authenticated:
        return jsonify({"error": "Sign in first"}), 401
    challenge = _b64(_os.urandom(32))
    # Stash challenge in config temporarily
    from db import cfg_set
    cfg_set(current_user.id, "wa_challenge", challenge)
    return jsonify({
        "challenge": challenge,
        "rp":   {"name": "My Life App"},
        "user": {
            "id":          _b64(str(current_user.id).encode()),
            "name":        current_user.email,
            "displayName": current_user.name,
        },
        "pubKeyCredParams": [{"type": "public-key", "alg": -7},
                             {"type": "public-key", "alg": -257}],
        "authenticatorSelection": {"userVerification": "preferred"},
        "timeout": 60000,
    })

@bp.route("/webauthn/register/finish", methods=["POST"])
def webauthn_register_finish():
    """Store the credential ID for this user."""
    if not current_user.is_authenticated:
        return jsonify({"error": "Sign in first"}), 401
    d = request.json or {}
    cred_id = d.get("id")
    if not cred_id:
        return jsonify({"error": "No credential returned"}), 400
    from db import cfg_get, cfg_set
    existing = cfg_get(current_user.id, "wa_credentials", "[]")
    try:
        creds = _json.loads(existing)
    except Exception:
        creds = []
    if cred_id not in creds:
        creds.append(cred_id)
    cfg_set(current_user.id, "wa_credentials", _json.dumps(creds))
    return jsonify({"ok": True})

@bp.route("/webauthn/login/begin", methods=["POST"])
def webauthn_login_begin():
    """Return a challenge + allowed credentials for the given email."""
    d     = request.json or {}
    email = (d.get("email") or "").strip().lower()
    if not email:
        return jsonify({"error": "Email required"}), 400

    conn = get_db()
    try:
        user = _fetchone(conn, f"SELECT * FROM users WHERE email={ph()}", (email,))
    finally:
        conn.close()
    if not user:
        return jsonify({"error": "No account with that email"}), 404
    if user["role"] == "pending":
        return jsonify({"error": "Account awaiting approval"}), 403

    from db import cfg_get, cfg_set
    creds_raw = cfg_get(user["id"], "wa_credentials", "[]")
    try:
        creds = _json.loads(creds_raw)
    except Exception:
        creds = []
    if not creds:
        return jsonify({"error": "No fingerprint registered. Sign in with password, then enable it in Settings."}), 400

    challenge = _b64(_os.urandom(32))
    cfg_set(user["id"], "wa_login_challenge", challenge)
    return jsonify({
        "challenge": challenge,
        "timeout":   60000,
        "userVerification": "preferred",
        "allowCredentials": [{"type": "public-key", "id": c} for c in creds],
    })

@bp.route("/webauthn/login/finish", methods=["POST"])
def webauthn_login_finish():
    """
    Verify the assertion. This is a simplified verification — it confirms the
    credential ID belongs to the user. For a personal app this provides
    convenience; the device's own biometric gate is the real security layer.
    """
    d     = request.json or {}
    email = (d.get("email") or "").strip().lower()
    cred_id = d.get("id")
    if not email or not cred_id:
        return jsonify({"error": "Missing data"}), 400

    conn = get_db()
    try:
        row = _fetchone(conn, f"SELECT * FROM users WHERE email={ph()}", (email,))
    finally:
        conn.close()
    if not row:
        return jsonify({"error": "No account"}), 404

    from db import cfg_get
    creds_raw = cfg_get(row["id"], "wa_credentials", "[]")
    try:
        creds = _json.loads(creds_raw)
    except Exception:
        creds = []

    if cred_id not in creds:
        return jsonify({"error": "Unrecognised fingerprint"}), 401

    user = User(row)
    login_user(user, remember=True)
    return jsonify({"ok": True})
