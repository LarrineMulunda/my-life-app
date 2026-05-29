import os
from flask import Flask, render_template, redirect, url_for
from flask_login import current_user
from db import init_db, get_db
from routes.auth import bp as auth_bp, login_mgr, approved_required
from routes.investments import bp as inv_bp, ASSET_CLASSES, EXCHANGES, EXCUR
from routes.upload_lots import bp as upload_bp
from routes.subscriptions import bp as sub_bp
from routes.habits import bp as habits_bp
from routes.cron import bp as cron_bp
from services.tickers import seed_tickers, CURRENCIES

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-in-production")

# Auth
login_mgr.init_app(app)

# Blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(inv_bp)
app.register_blueprint(sub_bp)
app.register_blueprint(upload_bp)
app.register_blueprint(habits_bp)
app.register_blueprint(cron_bp)

# Init DB + seed tickers
init_db()
conn = get_db()
try:
    seed_tickers(conn)
finally:
    conn.close()

SUB_CATEGORIES = ["Dance","Gym","Music","Language","Sports",
                  "Streaming","Software","Education","Health","Other"]

# ── Pages (all require approved login) ───────────────────────────────────────
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

HABIT_CATEGORIES = ["Health","Fitness","Mind","Learning","Productivity",
                    "Finance","Social","Creative","Other"]
HABIT_ICONS = ["✓","🏃","💪","📖","🧘","💧","🍎","😴","✍️","🎯","🎸","💰","☀️","🌙"]

@main_bp.route("/habits")
@approved_required
def habits_page():
    return render_template("habits.html",
                           categories=HABIT_CATEGORIES,
                           icons=HABIT_ICONS)

app.register_blueprint(main_bp)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
