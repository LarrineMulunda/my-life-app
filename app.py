import os
from flask import Flask, render_template
from db import init_db
from routes.investments import bp as inv_bp, ASSET_CLASSES, EXCHANGES, EXCUR
from routes.subscriptions import bp as sub_bp

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-in-production")

app.register_blueprint(inv_bp)
app.register_blueprint(sub_bp)

init_db()

SUB_CATEGORIES = ["Dance","Gym","Music","Language","Sports",
                  "Streaming","Software","Education","Health","Other"]

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/investments")
def investments_page():
    return render_template("investments.html",
                           asset_classes=ASSET_CLASSES,
                           exchanges=EXCHANGES,
                           exchange_currency=EXCUR)

@app.route("/subscriptions")
def subscriptions_page():
    return render_template("subscriptions.html", categories=SUB_CATEGORIES)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
