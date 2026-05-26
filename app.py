import os
import sys
import traceback
from flask import Flask, render_template, redirect, url_for
from flask_login import current_user
from db import init_db, get_db
from routes.auth import bp as auth_bp, login_mgr, approved_required
from routes.investments import bp as inv_bp, ASSET_CLASSES, EXCHANGES, EXCUR
from routes.subscriptions import bp as sub_bp
from services.tickers import seed_tickers, CURRENCIES

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-in-production")

# Auth
login_mgr.init_app(app)

# Blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(inv_bp)
app.register_blueprint(sub_bp)

# ── Initialise database with explicit error logging ──────────────────────────
print(">>> Starting database initialisation...", flush=True)
print(f">>> DATABASE_URL set: {bool(os.environ.get('DATABASE_URL'))}", flush=True)

try:
    init_db()
    print(">>> init_db() completed successfully", flush=True)
except Exception as e:
    print(f">>> init_db() FAILED: {type(e).__name__}: {e}", flush=True)
    traceback.print_exc()
    raise

# Seed ticker database
try:
    conn = get_db()
    try:
        seed_tickers(conn)
        print(">>> Tickers seeded successfully", flush=True)
    finally:
        conn.close()
except Exception as e:
    print(f">>> Ticker seeding FAILED: {type(e).__name__}: {e}", flush=True)
    traceback.print_exc()
    # Don't crash — app can still run without tickers

SUB_CATEGORIES = ["Dance", "Gym", "Music", "Language", "Sports",
                  "Streaming", "Software", "Education", "Health", "Other"]

# ── Pages ────────────────────────────────────────────────────────────────────
from flask import Blueprint
main_bp = Blueprint("main", __name__)

@main_bp.route("/")
def index():
    if current_user.is_authenticated and current_user.is_approved:
        return redirect(url_for("main.investments_page"))
    return redirect(url_for("auth.login"))

@main_bp.route("/investments")
@approved_required
def investments_page():
    return render_template("investments.html",
                           asset_classes=ASSET_CLASSES,
                           exchanges=EXCHANGES,
                           exchange_currency=EXCUR,
                           currencies=CURRENCIES)

@main_bp.route("/subscriptions")
@approved_required
def subscriptions_page():
    return render_template("subscriptions.html", categories=SUB_CATEGORIES)

app.register_blueprint(main_bp)

if __name__ == "__main__":
    app.run(debug=True, port=5000)