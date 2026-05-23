import sqlite3, os

DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(os.path.dirname(__file__), "life.db"))

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS savings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                label       TEXT    NOT NULL,
                asset_class TEXT    NOT NULL,
                amount      REAL    NOT NULL,
                type        TEXT    NOT NULL CHECK(type IN ('deposit','withdrawal')),
                note        TEXT    DEFAULT '',
                date        TEXT    NOT NULL
            );
            CREATE TABLE IF NOT EXISTS stock_lots (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker         TEXT    NOT NULL,
                exchange       TEXT    NOT NULL DEFAULT 'NSE',
                shares         REAL    NOT NULL CHECK(shares > 0),
                purchase_price REAL    NOT NULL CHECK(purchase_price > 0),
                date           TEXT    NOT NULL,
                broker         TEXT    DEFAULT '',
                note           TEXT    DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS stock_prices (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker   TEXT    NOT NULL,
                exchange TEXT    NOT NULL DEFAULT 'NSE',
                price    REAL    NOT NULL CHECK(price > 0),
                date     TEXT    NOT NULL,
                note     TEXT    DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS stock_sales (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker        TEXT    NOT NULL,
                exchange      TEXT    NOT NULL DEFAULT 'NSE',
                shares        REAL    NOT NULL CHECK(shares > 0),
                purchase_price REAL   NOT NULL CHECK(purchase_price > 0),
                sale_price    REAL    NOT NULL CHECK(sale_price > 0),
                date          TEXT    NOT NULL,
                broker        TEXT    DEFAULT '',
                note          TEXT    DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                date        TEXT    NOT NULL UNIQUE,
                total_value REAL    NOT NULL,
                stock_value REAL    NOT NULL,
                other_value REAL    NOT NULL,
                total_cost  REAL    NOT NULL,
                total_gain  REAL    NOT NULL
            );
            CREATE TABLE IF NOT EXISTS subscriptions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                name         TEXT    NOT NULL,
                category     TEXT    NOT NULL,
                sub_type     TEXT    NOT NULL CHECK(sub_type IN ('classes','duration')),
                note         TEXT    DEFAULT '',
                active       INTEGER NOT NULL DEFAULT 1,
                created_date TEXT    NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sub_payments (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                sub_id         INTEGER NOT NULL REFERENCES subscriptions(id),
                amount         REAL    NOT NULL CHECK(amount > 0),
                classes_bought INTEGER,
                start_date     TEXT,
                end_date       TEXT,
                note           TEXT    DEFAULT '',
                date           TEXT    NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sub_classes (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                payment_id     INTEGER REFERENCES sub_payments(id),
                sub_id         INTEGER NOT NULL REFERENCES subscriptions(id),
                scheduled_date TEXT,
                attended       INTEGER NOT NULL DEFAULT 0,
                note           TEXT    DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS config (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        # Safe migrations for existing databases
        _migrate(db)

def _migrate(db):
    for stmt in [
        "ALTER TABLE stock_lots ADD COLUMN exchange TEXT NOT NULL DEFAULT 'NSE'",
        "ALTER TABLE stock_prices ADD COLUMN exchange TEXT NOT NULL DEFAULT 'NSE'",
    ]:
        try: db.execute(stmt)
        except: pass

def cfg_get(key, default=None):
    with get_db() as db:
        r = db.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default

def cfg_set(key, value):
    with get_db() as db:
        db.execute("INSERT OR REPLACE INTO config (key,value) VALUES (?,?)", (key, value))
