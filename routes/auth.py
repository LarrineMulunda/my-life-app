"""
auth.py — registration, login, logout, admin approval panel.

User roles:
  pending  — registered but awaiting admin approval
  user     — approved, full access
  admin    — can approve/reject accounts, see all users
"""
import os
from datetime import datetime
from functools import wraps
from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, jsonify)
from flask_login import (LoginManager, UserMixin, login_user,
                         logout_user, login_required, current_user)
from werkzeug.security import generate_password_hash, check_password_hash
from db import get_db, ph, is_pg

bp         = Blueprint("auth", __name__)
login_mgr  = LoginManager()

# ── User model ────────────────────────────────────────────────────────────────

class User(UserMixin):
    def __init__(self, row):
        self.id    = row["id"]
        self.email = row["email"]
        self.name  = row["name"]
        self.role  = row["role"]   # pending | user | admin

    @property
    def is_approved(self): return self.role in ("user", "admin")
    @property
    def is_admin(self):    return self.role == "admin"

@login_mgr.user_loader
def load_user(uid):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM users WHERE id={ph()}", (int(uid),))
        r = cur.fetchone()
        return User(dict(r)) if r else None
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
        email = request.form.get("email","").strip().lower()
        name  = request.form.get("name","").strip()
        pw    = request.form.get("password","")
        pw2   = request.form.get("password2","")
        if not all([email, name, pw]):
            flash("All fields are required.")
        elif pw != pw2:
            flash("Passwords do not match.")
        elif len(pw) < 8:
            flash("Password must be at least 8 characters.")
        else:
            conn = get_db()
            try:
                # First user ever becomes admin automatically
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM users")
                count = cur.fetchone()
                count = count[0] if not is_pg() else list(count.values())[0]
                role  = "admin" if count == 0 else "pending"
                cur.execute(f"""
                    INSERT INTO users (email,name,password_hash,role,created_at)
                    VALUES ({ph()},{ph()},{ph()},{ph()},{ph()})
                """, (email, name, generate_password_hash(pw), role,
                      datetime.utcnow().isoformat()))
                conn.commit()
                if role == "admin":
                    flash("Admin account created — you can log in now.")
                else:
                    flash("Account created. An admin will review your request before you can log in.")
                return redirect(url_for("auth.login"))
            except Exception as e:
                if "unique" in str(e).lower() or "UNIQUE" in str(e):
                    flash("An account with that email already exists.")
                else:
                    flash(f"Error creating account: {e}")
            finally:
                conn.close()
    return render_template("auth/register.html")

# ── Login ─────────────────────────────────────────────────────────────────────

@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.investments_page"))
    if request.method == "POST":
        email    = request.form.get("email","").strip().lower()
        pw       = request.form.get("password","")
        remember = request.form.get("remember") == "on"
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(f"SELECT * FROM users WHERE email={ph()}", (email,))
            r = cur.fetchone()
        finally:
            conn.close()
        if r and check_password_hash(dict(r)["password_hash"], pw):
            user = User(dict(r))
            if user.role == "pending":
                flash("Your account is awaiting admin approval. You will be notified once approved.")
                return render_template("auth/login.html")
            login_user(user, remember=remember)
            return redirect(request.args.get("next") or url_for("main.investments_page"))
        flash("Incorrect email or password.")
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
        users = [dict(r) for r in conn.cursor().execute(
            "SELECT id,email,name,role,created_at FROM users ORDER BY created_at DESC"
        ).fetchall()]
    finally:
        conn.close()
    pending = [u for u in users if u["role"] == "pending"]
    approved = [u for u in users if u["role"] in ("user","admin")]
    return render_template("auth/admin.html", pending=pending, approved=approved)

@bp.route("/admin/approve/<int:uid>", methods=["POST"])
@admin_required
def approve_user(uid):
    conn = get_db()
    try:
        conn.cursor().execute(
            f"UPDATE users SET role='user' WHERE id={ph()} AND role='pending'", (uid,))
        conn.commit()
    finally:
        conn.close()
    flash("User approved.")
    return redirect(url_for("auth.admin_panel"))

@bp.route("/admin/reject/<int:uid>", methods=["POST"])
@admin_required
def reject_user(uid):
    conn = get_db()
    try:
        conn.cursor().execute(
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
        conn.cursor().execute(
            f"UPDATE users SET role='admin' WHERE id={ph()}", (uid,))
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
        conn.cursor().execute(
            f"UPDATE users SET role='user' WHERE id={ph()}", (uid,))
        conn.commit()
    finally:
        conn.close()
    flash("Admin rights removed.")
    return redirect(url_for("auth.admin_panel"))
