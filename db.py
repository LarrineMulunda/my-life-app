"""
db.py — database connection, schema, migrations.
PostgreSQL (prod) or SQLite (dev) — set DATABASE_URL for Postgres.
"""
import os, sqlite3

DATABASE_URL = os.environ.get("DATABASE_URL")
DB_PATH      = os.environ.get("DATABASE_PATH",
               os.path.join(os.path.dirname(__file__), "life.db"))

def get_db():
    if DATABASE_URL:
        import psycopg2, psycopg2.extras
        conn = psycopg2.connect(DATABASE_URL)
        conn.cursor_factory = psycopg2.extras.RealDictCursor
        conn.autocommit = False
        return conn
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def is_pg(): return bool(DATABASE_URL)
def ph():    return "%s" if is_pg() else "?"

def upsert_snapshot_sql():
    if is_pg():
        return """INSERT INTO portfolio_snapshots
            (user_id,date,total_value,stock_value,other_value,total_cost,total_gain)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(user_id,date) DO UPDATE SET
              total_value=EXCLUDED.total_value, stock_value=EXCLUDED.stock_value,
              other_value=EXCLUDED.other_value, total_cost=EXCLUDED.total_cost,
              total_gain=EXCLUDED.total_gain"""
    return """INSERT INTO portfolio_snapshots
        (user_id,date,total_value,stock_value,other_value,total_cost,total_gain)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(user_id,date) DO UPDATE SET
          total_value=excluded.total_value, stock_value=excluded.stock_value,
          other_value=excluded.other_value, total_cost=excluded.total_cost,
          total_gain=excluded.total_gain"""

_PG = """
CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    email         TEXT    NOT NULL UNIQUE,
    name          TEXT    NOT NULL,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'pending',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS savings (
    id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    label TEXT NOT NULL, asset_class TEXT NOT NULL,
    amount NUMERIC(15,4) NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('deposit','withdrawal')),
    currency TEXT NOT NULL DEFAULT 'KES',
    note TEXT DEFAULT '', date DATE NOT NULL
);
CREATE TABLE IF NOT EXISTS stock_lots (
    id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    ticker TEXT NOT NULL, exchange TEXT NOT NULL DEFAULT 'NSE',
    shares NUMERIC(15,6) NOT NULL CHECK(shares >= 0),
    original_shares NUMERIC(15,6),
    purchase_price NUMERIC(15,4) NOT NULL CHECK(purchase_price > 0),
    currency TEXT NOT NULL DEFAULT 'KES',
    date DATE NOT NULL, broker TEXT DEFAULT '', note TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS stock_prices (
    id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    ticker TEXT NOT NULL, exchange TEXT NOT NULL DEFAULT 'NSE',
    price NUMERIC(15,4) NOT NULL CHECK(price > 0),
    currency TEXT NOT NULL DEFAULT 'KES',
    date DATE NOT NULL, note TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS stock_sales (
    id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    lot_id INTEGER REFERENCES stock_lots(id),
    ticker TEXT NOT NULL, exchange TEXT NOT NULL DEFAULT 'NSE',
    shares NUMERIC(15,6) NOT NULL CHECK(shares > 0),
    purchase_price NUMERIC(15,4) NOT NULL,
    sale_price NUMERIC(15,4) NOT NULL,
    currency TEXT NOT NULL DEFAULT 'KES',
    date DATE NOT NULL, broker TEXT DEFAULT '', note TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    date DATE NOT NULL, total_value NUMERIC(18,2) NOT NULL,
    stock_value NUMERIC(18,2) NOT NULL, other_value NUMERIC(18,2) NOT NULL,
    total_cost NUMERIC(18,2) NOT NULL, total_gain NUMERIC(18,2) NOT NULL,
    UNIQUE(user_id, date)
);
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL, category TEXT NOT NULL,
    sub_type TEXT NOT NULL CHECK(sub_type IN ('classes','duration')),
    note TEXT DEFAULT '', active BOOLEAN NOT NULL DEFAULT TRUE,
    created_date DATE NOT NULL
);
CREATE TABLE IF NOT EXISTS sub_payments (
    id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    sub_id INTEGER NOT NULL REFERENCES subscriptions(id),
    amount NUMERIC(15,4) NOT NULL CHECK(amount > 0),
    classes_bought INTEGER, start_date DATE, end_date DATE,
    note TEXT DEFAULT '', date DATE NOT NULL
);
CREATE TABLE IF NOT EXISTS sub_classes (
    id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    payment_id INTEGER REFERENCES sub_payments(id),
    sub_id INTEGER NOT NULL REFERENCES subscriptions(id),
    scheduled_date DATE, attended BOOLEAN NOT NULL DEFAULT FALSE,
    note TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS tickers (
    id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    symbol TEXT NOT NULL, name TEXT NOT NULL, exchange TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'stock', currency TEXT NOT NULL DEFAULT 'KES',
    sector TEXT DEFAULT '', active BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE(symbol, exchange)
);
CREATE TABLE IF NOT EXISTS config (
    user_id INTEGER NOT NULL REFERENCES users(id),
    key TEXT NOT NULL, value TEXT NOT NULL,
    PRIMARY KEY(user_id, key)
);
CREATE TABLE IF NOT EXISTS global_prices (
    id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    ticker TEXT NOT NULL, exchange TEXT NOT NULL DEFAULT 'NSE',
    price NUMERIC(15,4) NOT NULL CHECK(price > 0),
    currency TEXT NOT NULL DEFAULT 'KES',
    date DATE NOT NULL, note TEXT DEFAULT '',
    UNIQUE(ticker, exchange, date)
);
CREATE TABLE IF NOT EXISTS global_fx (
    currency TEXT PRIMARY KEY,
    kes_rate NUMERIC(15,6) NOT NULL,
    updated_date DATE NOT NULL
);
CREATE TABLE IF NOT EXISTS price_anomalies (
    id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    type TEXT NOT NULL DEFAULT 'price',
    ticker TEXT, exchange TEXT, currency TEXT,
    fetched_value NUMERIC(15,6) NOT NULL,
    previous_value NUMERIC(15,6), pct_change NUMERIC(8,2),
    status TEXT NOT NULL DEFAULT 'flagged',
    reviewed_value NUMERIC(15,6),
    review_note TEXT DEFAULT '',
    created_at TIMESTAMP NOT NULL, resolved_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS habits (
    id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    icon TEXT DEFAULT '✓',
    color TEXT DEFAULT '#C9A84C',
    target_per_week INTEGER NOT NULL DEFAULT 7,
    category TEXT DEFAULT 'General',
    note TEXT DEFAULT '',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_date DATE NOT NULL
);
CREATE TABLE IF NOT EXISTS habit_logs (
    id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    habit_id INTEGER NOT NULL REFERENCES habits(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    date DATE NOT NULL,
    done BOOLEAN NOT NULL DEFAULT TRUE,
    note TEXT DEFAULT '',
    UNIQUE(habit_id, date)
);
CREATE TABLE IF NOT EXISTS review_jobs (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'running',
    started_at TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    agents JSONB
);
CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    icon TEXT DEFAULT '🎯',
    color TEXT DEFAULT '#C9A84C',
    category TEXT DEFAULT 'General',
    target_amount NUMERIC(15,2) NOT NULL,
    target_currency TEXT NOT NULL DEFAULT 'KES',
    target_date DATE,
    note TEXT DEFAULT '',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_date DATE NOT NULL,
    link_type TEXT DEFAULT NULL,
    link_label TEXT DEFAULT NULL
);
CREATE TABLE IF NOT EXISTS goal_contributions (
    id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    goal_id INTEGER NOT NULL REFERENCES goals(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    amount NUMERIC(15,2) NOT NULL,
    currency TEXT NOT NULL DEFAULT 'KES',
    date DATE NOT NULL,
    note TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS portfolio_targets (
    id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    target_amount NUMERIC(18,2) NOT NULL,
    target_currency TEXT NOT NULL DEFAULT 'KES',
    target_date DATE NOT NULL,
    note TEXT DEFAULT '',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_date DATE NOT NULL
);
"""

_SQLITE = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT    NOT NULL UNIQUE,
    name          TEXT    NOT NULL,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'pending',
    created_at    TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS savings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    label TEXT NOT NULL, asset_class TEXT NOT NULL,
    amount REAL NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('deposit','withdrawal')),
    currency TEXT NOT NULL DEFAULT 'KES',
    note TEXT DEFAULT '', date TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stock_lots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    ticker TEXT NOT NULL, exchange TEXT NOT NULL DEFAULT 'NSE',
    shares REAL NOT NULL CHECK(shares >= 0),
    original_shares REAL,
    purchase_price REAL NOT NULL CHECK(purchase_price > 0),
    currency TEXT NOT NULL DEFAULT 'KES',
    date TEXT NOT NULL, broker TEXT DEFAULT '', note TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS stock_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    ticker TEXT NOT NULL, exchange TEXT NOT NULL DEFAULT 'NSE',
    price REAL NOT NULL CHECK(price > 0),
    currency TEXT NOT NULL DEFAULT 'KES',
    date TEXT NOT NULL, note TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS stock_sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    lot_id INTEGER REFERENCES stock_lots(id),
    ticker TEXT NOT NULL, exchange TEXT NOT NULL DEFAULT 'NSE',
    shares REAL NOT NULL CHECK(shares > 0),
    purchase_price REAL NOT NULL,
    sale_price REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'KES',
    date TEXT NOT NULL, broker TEXT DEFAULT '', note TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    date TEXT NOT NULL, total_value REAL NOT NULL,
    stock_value REAL NOT NULL, other_value REAL NOT NULL,
    total_cost REAL NOT NULL, total_gain REAL NOT NULL,
    UNIQUE(user_id, date)
);
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL, category TEXT NOT NULL,
    sub_type TEXT NOT NULL CHECK(sub_type IN ('classes','duration')),
    note TEXT DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
    created_date TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sub_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sub_id INTEGER NOT NULL REFERENCES subscriptions(id),
    amount REAL NOT NULL CHECK(amount > 0),
    classes_bought INTEGER, start_date TEXT, end_date TEXT,
    note TEXT DEFAULT '', date TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sub_classes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id INTEGER REFERENCES sub_payments(id),
    sub_id INTEGER NOT NULL REFERENCES subscriptions(id),
    scheduled_date TEXT, attended INTEGER NOT NULL DEFAULT 0,
    note TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS tickers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL, name TEXT NOT NULL, exchange TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'stock', currency TEXT NOT NULL DEFAULT 'KES',
    sector TEXT DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
    UNIQUE(symbol, exchange)
);
CREATE TABLE IF NOT EXISTS config (
    user_id INTEGER NOT NULL REFERENCES users(id),
    key TEXT NOT NULL, value TEXT NOT NULL,
    PRIMARY KEY(user_id, key)
);
CREATE TABLE IF NOT EXISTS global_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL, exchange TEXT NOT NULL DEFAULT 'NSE',
    price REAL NOT NULL CHECK(price > 0),
    currency TEXT NOT NULL DEFAULT 'KES',
    date TEXT NOT NULL, note TEXT DEFAULT '',
    UNIQUE(ticker, exchange, date)
);
CREATE TABLE IF NOT EXISTS global_fx (
    currency TEXT PRIMARY KEY,
    kes_rate REAL NOT NULL,
    updated_date TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS price_anomalies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL DEFAULT 'price',
    ticker TEXT, exchange TEXT, currency TEXT,
    fetched_value REAL NOT NULL,
    previous_value REAL, pct_change REAL,
    status TEXT NOT NULL DEFAULT 'flagged',
    reviewed_value REAL,
    review_note TEXT DEFAULT '',
    created_at TEXT NOT NULL, resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS habits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    icon TEXT DEFAULT '✓',
    color TEXT DEFAULT '#C9A84C',
    target_per_week INTEGER NOT NULL DEFAULT 7,
    category TEXT DEFAULT 'General',
    note TEXT DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_date TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS habit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    habit_id INTEGER NOT NULL REFERENCES habits(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    date TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 1,
    note TEXT DEFAULT '',
    UNIQUE(habit_id, date)
);
CREATE TABLE IF NOT EXISTS review_jobs (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    started_at TEXT NOT NULL,
    finished_at TEXT,
    agents TEXT
);
CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    icon TEXT DEFAULT '🎯',
    color TEXT DEFAULT '#C9A84C',
    category TEXT DEFAULT 'General',
    target_amount REAL NOT NULL,
    target_currency TEXT NOT NULL DEFAULT 'KES',
    target_date TEXT,
    note TEXT DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_date TEXT NOT NULL,
    link_type TEXT DEFAULT NULL,
    link_label TEXT DEFAULT NULL
);
CREATE TABLE IF NOT EXISTS goal_contributions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER NOT NULL REFERENCES goals(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    amount REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'KES',
    date TEXT NOT NULL,
    note TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS portfolio_targets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    target_amount REAL NOT NULL,
    target_currency TEXT NOT NULL DEFAULT 'KES',
    target_date TEXT NOT NULL,
    note TEXT DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_date TEXT NOT NULL
);
"""

def init_db():
    conn = get_db()
    try:
        if is_pg():
            # autocommit so a failed statement doesn't poison the whole transaction
            conn.autocommit = True
            cur = conn.cursor()
            for s in [x.strip() for x in _PG.split(";") if x.strip()]:
                try:
                    cur.execute(s)
                except Exception as e:
                    print(f"  schema stmt skipped: {str(e)[:70]}", flush=True)
            _migrate(conn)
        else:
            conn.executescript(_SQLITE)
            _migrate(conn)
            conn.commit()
    finally:
        conn.close()

def _migrate(conn):
    """Add columns to existing tables. Autocommit (PG) or committed (SQLite)."""
    migrations = [
        ("savings",    "currency TEXT NOT NULL DEFAULT 'KES'"),
        ("stock_lots", "currency TEXT NOT NULL DEFAULT 'KES'"),
        ("stock_lots", "original_shares REAL"),
        ("stock_lots", "lot_id INTEGER"),
        ("stock_prices","currency TEXT NOT NULL DEFAULT 'KES'"),
        ("stock_sales", "currency TEXT NOT NULL DEFAULT 'KES'"),
        ("stock_sales", "lot_id INTEGER"),
        ("habits",     "icon TEXT DEFAULT '✓'"),
        ("goals",      "link_type TEXT DEFAULT NULL"),
        ("goals",      "link_label TEXT DEFAULT NULL"),
        ("habits",     "color TEXT DEFAULT '#C9A84C'"),
        ("habits",     "category TEXT DEFAULT 'General'"),
    ]
    for table, col in migrations:
        try:
            conn.cursor().execute(f"ALTER TABLE {table} ADD COLUMN {col}")
            if not is_pg():
                conn.commit()
        except Exception:
            if not is_pg():
                try: conn.rollback()
                except: pass
    try:
        conn.cursor().execute(
            "UPDATE stock_lots SET original_shares=shares WHERE original_shares IS NULL")
        if not is_pg():
            conn.commit()
    except Exception:
        pass

# ── Config helpers (per-user) ─────────────────────────────────────────────────
def cfg_get(user_id, key, default=None):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT value FROM config WHERE user_id={ph()} AND key={ph()}",
                    (user_id, key))
        r = cur.fetchone()
        return (r["value"] if is_pg() else r[0]) if r else default
    finally:
        conn.close()

def cfg_set(user_id, key, value):
    conn = get_db()
    try:
        cur = conn.cursor()
        if is_pg():
            cur.execute("""INSERT INTO config (user_id,key,value) VALUES (%s,%s,%s)
                ON CONFLICT(user_id,key) DO UPDATE SET value=EXCLUDED.value""",
                (user_id, key, value))
        else:
            cur.execute("INSERT OR REPLACE INTO config (user_id,key,value) VALUES (?,?,?)",
                        (user_id, key, value))
        conn.commit()
    finally:
        conn.close()

# ── Global FX helpers (shared by all users) ───────────────────────────────────
def fx_get_all():
    """Return {currency: kes_rate} from the global table."""
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT currency, kes_rate FROM global_fx")
        rows = cur.fetchall()
        out = {"KES": 1.0}
        for r in rows:
            cur_code = r["currency"] if is_pg() else r[0]
            rate     = r["kes_rate"] if is_pg() else r[1]
            out[cur_code] = float(rate)
        return out
    finally:
        conn.close()

def fx_set(currency, kes_rate, date):
    conn = get_db()
    try:
        cur = conn.cursor()
        if is_pg():
            cur.execute("""INSERT INTO global_fx (currency,kes_rate,updated_date)
                VALUES (%s,%s,%s)
                ON CONFLICT(currency) DO UPDATE SET
                  kes_rate=EXCLUDED.kes_rate, updated_date=EXCLUDED.updated_date""",
                (currency, kes_rate, date))
        else:
            cur.execute("""INSERT OR REPLACE INTO global_fx
                (currency,kes_rate,updated_date) VALUES (?,?,?)""",
                (currency, kes_rate, date))
        conn.commit()
    finally:
        conn.close()
