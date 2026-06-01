import os
from flask import Flask, render_template, redirect, url_for, request
from flask_login import current_user
from db import init_db, get_db
from routes.auth import bp as auth_bp, login_mgr, approved_required
from routes.investments import bp as inv_bp, ASSET_CLASSES, EXCHANGES, EXCUR
from routes.upload_lots import bp as upload_bp
from routes.subscriptions import bp as sub_bp
from routes.habits import bp as habits_bp
from routes.cron import bp as cron_bp
from routes.goals import bp as goals_bp, GOAL_CATEGORIES, GOAL_ICONS
from services.tickers import seed_tickers, CURRENCIES

app = Flask(__name__)

@app.after_request
def set_cache_headers(response):
    # Cache static assets for 7 days — they only change on deploy
    if request.path.startswith('/static/'):
        response.cache_control.max_age = 604800   # 7 days
        response.cache_control.public  = True
    # Never cache HTML pages or API responses
    elif not request.path.startswith('/api/'):
        response.cache_control.no_cache = True
    return response
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
app.register_blueprint(goals_bp)

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

def _extract_page_content(full_html):
    """Extract content+scripts from rendered page for SPA swap."""
    import re
    mc = re.search("<main[^>]*>(.*?)</main>", full_html, re.DOTALL)
    if not mc:
        mc = re.search('(<div class="page-h[^"]*">.*?)</main>', full_html, re.DOTALL)
    all_scripts = re.findall("<script>(.*?)</script>", full_html, re.DOTALL)
    scripts = all_scripts[-1].strip() if all_scripts else ""
    return {
        "content": mc.group(1) if mc else "",
        "scripts": scripts,
    }

@main_bp.route("/")
def index():
    if current_user.is_authenticated and current_user.is_approved:
        return redirect(url_for("main.investments_page"))
    return redirect(url_for("auth.login"))

@main_bp.route("/investments")
@approved_required
def investments_page():
    from flask import jsonify
    if request.args.get("partial"):
        from flask import render_template as rt
        import re
        html = rt("investments.html", asset_classes=ASSET_CLASSES,
                  exchanges=EXCHANGES, exchange_currency=EXCUR, currencies=CURRENCIES)
        content = _extract_page_content(html)
        return jsonify(content)
    return render_template("investments.html",
                           asset_classes=ASSET_CLASSES,
                           exchanges=EXCHANGES,
                           exchange_currency=EXCUR,
                           currencies=CURRENCIES)

@main_bp.route("/subscriptions")
@approved_required
def subscriptions_page():
    from flask import jsonify
    if request.args.get("partial"):
        html = render_template("subscriptions.html", categories=SUB_CATEGORIES)
        return jsonify(_extract_page_content(html))
    return render_template("subscriptions.html", categories=SUB_CATEGORIES)

HABIT_CATEGORIES = ["Health","Fitness","Mind","Learning","Productivity",
                    "Finance","Social","Creative","Other"]
HABIT_ICONS = ["✓","🏃","💪","📖","🧘","💧","🍎","😴","✍️","🎯","🎸","💰","☀️","🌙"]

@main_bp.route("/habits")
@approved_required
def habits_page():
    from flask import jsonify
    if request.args.get("partial"):
        html = render_template("habits.html", categories=HABIT_CATEGORIES, icons=HABIT_ICONS)
        return jsonify(_extract_page_content(html))
    return render_template("habits.html",
                           categories=HABIT_CATEGORIES,
                           icons=HABIT_ICONS)

@main_bp.route("/goals")
@approved_required
def goals_page():
    from flask import jsonify
    from routes.goals import GOAL_CATEGORIES, GOAL_ICONS
    currencies = ["KES","USD","GBP","EUR","ZAR","TZS","UGX","GHS","HKD","Other"]
    if request.args.get("partial"):
        html = render_template("goals.html", categories=GOAL_CATEGORIES,
                               icons=GOAL_ICONS, currencies=currencies)
        return jsonify(_extract_page_content(html))
    return render_template("goals.html",
                           categories=GOAL_CATEGORIES,
                           icons=GOAL_ICONS,
                           currencies=currencies)

app.register_blueprint(main_bp)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
