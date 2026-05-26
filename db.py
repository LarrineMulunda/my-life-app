"""
db.py — database connection and schema
Supports both PostgreSQL (production) and SQLite (development).
Set DATABASE_URL env var for PostgreSQL; leave unset for SQLite.
"""
import os, sqlite3

# ── Connection ────────────────────────────────────────────────────────────────

DATABASE_URL = os.environ.get("DATABASE_URL")       # PostgreSQL in prod
DB_PATH      = os.environ.get("DATABASE_PATH",
                os.path.join(os.path.dirname(__file__), "life.db"))

def get_db():
    if DATABASE_URL:
        import psycopg2, psycopg2.extras
        conn = psycopg2.connect(DATABASE_URL)
        conn.cursor_factory = psycopg2.extras.RealDictCursor
        conn.autocommit = False
        return conn
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

def is_pg():
    return bool(DATABASE_URL)

def ph():
    """SQL placeholder — %s for PostgreSQL, ? for SQLite."""
    return "%s" if is_pg() else "?"

def upsert_snapshot_sql():
    """ON CONFLICT upsert differs between PG and SQLite."""
    if is_pg():
        return """
            INSERT INTO portfolio_snapshots
                (date,total_value,stock_value,other_value,total_cost,total_gain)
            VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT(date) DO UPDATE SET
                total_value=EXCLUDED.total_value,
                stock_value=EXCLUDED.stock_value,
                other_value=EXCLUDED.other_value,
                total_cost=EXCLUDED.total_cost,
                total_gain=EXCLUDED.total_gain
        """
    return """
        INSERT INTO portfolio_snapshots
            (date,total_value,stock_value,other_value,total_cost,total_gain)
        VALUES (?,?,?,?,?,?)
        ON CONFLICT(date) DO UPDATE SET
            total_value=excluded.total_value,
            stock_value=excluded.stock_value,
            other_value=excluded.other_value,
            total_cost=excluded.total_cost,
            total_gain=excluded.total_gain
    """

# ── Schema ────────────────────────────────────────────────────────────────────

_PG_SCHEMA = """
    CREATE TABLE IF NOT EXISTS savings (
        id          SERIAL PRIMARY KEY,
        label       TEXT    NOT NULL,
        asset_class TEXT    NOT NULL,
        amount      NUMERIC(15,4) NOT NULL,
        type        TEXT    NOT NULL CHECK(type IN ('deposit','withdrawal')),
        note        TEXT    DEFAULT '',
        date        DATE    NOT NULL
    );
    CREATE TABLE IF NOT EXISTS stock_lots (
        id             SERIAL PRIMARY KEY,
        ticker         TEXT    NOT NULL,
        exchange       TEXT    NOT NULL DEFAULT 'NSE',
        shares         NUMERIC(15,6) NOT NULL CHECK(shares >= 0),
        original_shares NUMERIC(15,6),
        purchase_price NUMERIC(15,4) NOT NULL CHECK(purchase_price > 0),
        date           DATE    NOT NULL,
        broker         TEXT    DEFAULT '',
        note           TEXT    DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS stock_prices (
        id       SERIAL PRIMARY KEY,
        ticker   TEXT    NOT NULL,
        exchange TEXT    NOT NULL DEFAULT 'NSE',
        price    NUMERIC(15,4) NOT NULL CHECK(price > 0),
        date     DATE    NOT NULL,
        note     TEXT    DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS stock_sales (
        id             SERIAL PRIMARY KEY,
        lot_id         INTEGER REFERENCES stock_lots(id),
        ticker         TEXT    NOT NULL,
        exchange       TEXT    NOT NULL DEFAULT 'NSE',
        shares         NUMERIC(15,6) NOT NULL CHECK(shares > 0),
        purchase_price NUMERIC(15,4) NOT NULL CHECK(purchase_price > 0),
        sale_price     NUMERIC(15,4) NOT NULL CHECK(sale_price > 0),
        date           DATE    NOT NULL,
        broker         TEXT    DEFAULT '',
        note           TEXT    DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS portfolio_snapshots (
        id          SERIAL PRIMARY KEY,
        date        DATE    NOT NULL UNIQUE,
        total_value NUMERIC(18,2) NOT NULL,
        stock_value NUMERIC(18,2) NOT NULL,
        other_value NUMERIC(18,2) NOT NULL,
        total_cost  NUMERIC(18,2) NOT NULL,
        total_gain  NUMERIC(18,2) NOT NULL
    );
    CREATE TABLE IF NOT EXISTS subscriptions (
        id           SERIAL PRIMARY KEY,
        name         TEXT    NOT NULL,
        category     TEXT    NOT NULL,
        sub_type     TEXT    NOT NULL CHECK(sub_type IN ('classes','duration')),
        note         TEXT    DEFAULT '',
        active       BOOLEAN NOT NULL DEFAULT TRUE,
        created_date DATE    NOT NULL
    );
    CREATE TABLE IF NOT EXISTS sub_payments (
        id             SERIAL PRIMARY KEY,
        sub_id         INTEGER NOT NULL REFERENCES subscriptions(id),
        amount         NUMERIC(15,4) NOT NULL CHECK(amount > 0),
        classes_bought INTEGER,
        start_date     DATE,
        end_date       DATE,
        note           TEXT    DEFAULT '',
        date           DATE    NOT NULL
    );
    CREATE TABLE IF NOT EXISTS sub_classes (
        id             SERIAL PRIMARY KEY,
        payment_id     INTEGER REFERENCES sub_payments(id),
        sub_id         INTEGER NOT NULL REFERENCES subscriptions(id),
        scheduled_date DATE,
        attended       BOOLEAN NOT NULL DEFAULT FALSE,
        note           TEXT    DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS tickers (
        id        SERIAL PRIMARY KEY,
        symbol    TEXT    NOT NULL,
        name      TEXT    NOT NULL,
        exchange  TEXT    NOT NULL,
        type      TEXT    NOT NULL DEFAULT 'stock',
        currency  TEXT    NOT NULL DEFAULT 'KES',
        sector    TEXT    DEFAULT '',
        active    BOOLEAN NOT NULL DEFAULT TRUE,
        UNIQUE(symbol, exchange)
    );
    CREATE TABLE IF NOT EXISTS config (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
"""

_SQLITE_SCHEMA = """
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
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker          TEXT    NOT NULL,
        exchange        TEXT    NOT NULL DEFAULT 'NSE',
        shares          REAL    NOT NULL CHECK(shares >= 0),
        original_shares REAL,
        purchase_price  REAL    NOT NULL CHECK(purchase_price > 0),
        date            TEXT    NOT NULL,
        broker          TEXT    DEFAULT '',
        note            TEXT    DEFAULT ''
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
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        lot_id         INTEGER REFERENCES stock_lots(id),
        ticker         TEXT    NOT NULL,
        exchange       TEXT    NOT NULL DEFAULT 'NSE',
        shares         REAL    NOT NULL CHECK(shares > 0),
        purchase_price REAL    NOT NULL CHECK(purchase_price > 0),
        sale_price     REAL    NOT NULL CHECK(sale_price > 0),
        date           TEXT    NOT NULL,
        broker         TEXT    DEFAULT '',
        note           TEXT    DEFAULT ''
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
    CREATE TABLE IF NOT EXISTS tickers (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol   TEXT NOT NULL,
        name     TEXT NOT NULL,
        exchange TEXT NOT NULL,
        type     TEXT NOT NULL DEFAULT 'stock',
        currency TEXT NOT NULL DEFAULT 'KES',
        sector   TEXT DEFAULT '',
        active   INTEGER NOT NULL DEFAULT 1,
        UNIQUE(symbol, exchange)
    );
    CREATE TABLE IF NOT EXISTS config (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
"""

def init_db():
    conn = get_db()
    try:
        cur = conn.cursor()
        if is_pg():
            for stmt in [s.strip() for s in _PG_SCHEMA.split(";") if s.strip()]:
                cur.execute(stmt)
        else:
            conn.executescript(_SQLITE_SCHEMA)
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()

def _migrate(conn):
    """Safe schema migrations for existing databases."""
    p = ph()
    migrations = [
        ("stock_lots",  "original_shares REAL"),
        ("stock_lots",  f"exchange TEXT NOT NULL DEFAULT 'NSE'"),
        ("stock_prices",f"exchange TEXT NOT NULL DEFAULT 'NSE'"),
        ("stock_sales", f"lot_id INTEGER"),
    ]
    cur = conn.cursor()
    for table, col_def in migrations:
        col_name = col_def.split()[0]
        try:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")
        except Exception:
            pass  # column already exists
    # Backfill original_shares where NULL
    try:
        cur.execute("UPDATE stock_lots SET original_shares = shares WHERE original_shares IS NULL")
    except Exception:
        pass
    conn.commit()

# ── Config helpers ────────────────────────────────────────────────────────────

def cfg_get(key, default=None):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT value FROM config WHERE key={ph()}", (key,))
        r = cur.fetchone()
        return (r["value"] if is_pg() else r[0]) if r else default
    finally:
        conn.close()

def cfg_set(key, value):
    conn = get_db()
    try:
        cur = conn.cursor()
        if is_pg():
            cur.execute("""
                INSERT INTO config (key,value) VALUES (%s,%s)
                ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value
            """, (key, value))
        else:
            cur.execute("INSERT OR REPLACE INTO config (key,value) VALUES (?,?)", (key, value))
        conn.commit()
    finally:
        conn.close()
