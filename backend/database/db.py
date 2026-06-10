import sqlite3
import threading
from contextlib import contextmanager
from config import DATABASE_URL

_local = threading.local()


def get_connection() -> sqlite3.Connection:
    if not hasattr(_local, "connection") or _local.connection is None:
        _local.connection = sqlite3.connect(DATABASE_URL, check_same_thread=False)
        _local.connection.row_factory = sqlite3.Row
        _local.connection.execute("PRAGMA journal_mode=WAL")
        _local.connection.execute("PRAGMA foreign_keys=ON")
    return _local.connection


@contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT DEFAULT 'user',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS mt5_credentials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                server TEXT NOT NULL,
                login TEXT NOT NULL,
                password_encrypted TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS trade_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                action TEXT NOT NULL,
                lot_size REAL NOT NULL,
                entry_price REAL,
                stop_loss REAL,
                take_profit REAL,
                ticket INTEGER,
                status TEXT DEFAULT 'PENDING',
                profit REAL DEFAULT 0,
                h1_bias TEXT,
                ai_decision TEXT,
                m5_zone TEXT,
                opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                closed_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS ai_decision_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                h1_bias TEXT,
                ai_decision TEXT,
                m5_zone_valid INTEGER,
                rsi REAL,
                macd_line REAL,
                macd_signal REAL,
                atr REAL,
                ema8 REAL,
                ema21 REAL,
                confidence REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS error_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                module TEXT,
                error_type TEXT,
                message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS performance_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                total_trades INTEGER DEFAULT 0,
                winning_trades INTEGER DEFAULT 0,
                losing_trades INTEGER DEFAULT 0,
                total_profit REAL DEFAULT 0,
                max_drawdown REAL DEFAULT 0,
                win_rate REAL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT,
                PRIMARY KEY (user_id, key),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
        """)
        # Migrate: add role column if not exists
        try:
            conn.execute("SELECT role FROM users LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'")
            conn.commit()
