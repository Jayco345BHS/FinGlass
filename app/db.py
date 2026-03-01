import sqlite3
from pathlib import Path
from flask import g

from .credit_card_categories import normalize_credit_card_category

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "finglass.sqlite3"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    auth_provider TEXT NOT NULL DEFAULT 'local',
    external_subject TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (auth_provider, external_subject)
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 0,
    security TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    transaction_type TEXT NOT NULL,
    amount REAL NOT NULL DEFAULT 0,
    shares REAL NOT NULL DEFAULT 0,
    amount_per_share REAL,
    commission REAL NOT NULL DEFAULT 0,
    memo TEXT,
    source TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_transactions_security_date
    ON transactions (security, trade_date, id);

CREATE TABLE IF NOT EXISTS import_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 0,
    source_type TEXT NOT NULL,
    source_filename TEXT,
    status TEXT NOT NULL DEFAULT 'staged',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    committed_at TEXT
);

CREATE TABLE IF NOT EXISTS import_batch_rows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL,
    row_order INTEGER NOT NULL,
    security TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    transaction_type TEXT NOT NULL,
    amount REAL NOT NULL DEFAULT 0,
    shares REAL NOT NULL DEFAULT 0,
    amount_per_share REAL,
    commission REAL NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'import_review',
    FOREIGN KEY (batch_id) REFERENCES import_batches (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_import_batch_rows_batch
    ON import_batch_rows (batch_id, row_order, id);

CREATE TABLE IF NOT EXISTS holdings_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 0,
    as_of TEXT NOT NULL,
    account_name TEXT NOT NULL,
    account_type TEXT,
    account_classification TEXT,
    account_number TEXT NOT NULL,
    symbol TEXT NOT NULL,
    exchange TEXT,
    mic TEXT,
    security_name TEXT,
    security_type TEXT,
    quantity REAL NOT NULL DEFAULT 0,
    market_price REAL NOT NULL DEFAULT 0,
    market_price_currency TEXT,
    book_value_cad REAL NOT NULL DEFAULT 0,
    market_value REAL NOT NULL DEFAULT 0,
    market_value_currency TEXT,
    unrealized_return REAL NOT NULL DEFAULT 0,
    source_filename TEXT,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, as_of, account_number, symbol)
);

CREATE INDEX IF NOT EXISTS idx_holdings_as_of_account
    ON holdings_snapshots (as_of, account_number, symbol);

CREATE TABLE IF NOT EXISTS net_worth_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 0,
    entry_date TEXT NOT NULL,
    amount REAL NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, entry_date)
);

CREATE INDEX IF NOT EXISTS idx_net_worth_entry_date
    ON net_worth_history (entry_date);

CREATE TABLE IF NOT EXISTS credit_card_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 0,
    provider TEXT NOT NULL,
    transaction_date TEXT NOT NULL,
    posted_date TEXT,
    reference_number TEXT NOT NULL DEFAULT '',
    activity_type TEXT,
    status TEXT,
    card_last4 TEXT,
    merchant_category TEXT,
    merchant_name TEXT,
    merchant_city TEXT,
    merchant_region TEXT,
    merchant_country TEXT,
    merchant_postal TEXT,
    amount REAL NOT NULL,
    rewards REAL NOT NULL DEFAULT 0,
    is_hidden INTEGER NOT NULL DEFAULT 0,
    cardholder_name TEXT,
    source_filename TEXT,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_cc_provider_date
    ON credit_card_transactions (provider, transaction_date, id);

CREATE INDEX IF NOT EXISTS idx_cc_provider_category
    ON credit_card_transactions (provider, merchant_category);

CREATE TABLE IF NOT EXISTS app_settings (
    user_id INTEGER NOT NULL DEFAULT 0,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, key)
);
"""


def _table_exists(cursor, table_name):
    row = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _has_column(cursor, table_name, column_name):
    if not _table_exists(cursor, table_name):
        return False
    rows = cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row[1] == column_name for row in rows)


def _apply_schema(cursor):
    cursor.executescript(SCHEMA_SQL)


def _apply_migrations(cursor):
    if not _has_column(cursor, "transactions", "user_id"):
        cursor.execute("ALTER TABLE transactions ADD COLUMN user_id INTEGER NOT NULL DEFAULT 0")

    if not _has_column(cursor, "import_batches", "user_id"):
        cursor.execute("ALTER TABLE import_batches ADD COLUMN user_id INTEGER NOT NULL DEFAULT 0")

    if _table_exists(cursor, "holdings_snapshots") and not _has_column(cursor, "holdings_snapshots", "user_id"):
        cursor.executescript(
            """
            ALTER TABLE holdings_snapshots RENAME TO holdings_snapshots_old;

            CREATE TABLE holdings_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
                as_of TEXT NOT NULL,
                account_name TEXT NOT NULL,
                account_type TEXT,
                account_classification TEXT,
                account_number TEXT NOT NULL,
                symbol TEXT NOT NULL,
                exchange TEXT,
                mic TEXT,
                security_name TEXT,
                security_type TEXT,
                quantity REAL NOT NULL DEFAULT 0,
                market_price REAL NOT NULL DEFAULT 0,
                market_price_currency TEXT,
                book_value_cad REAL NOT NULL DEFAULT 0,
                market_value REAL NOT NULL DEFAULT 0,
                market_value_currency TEXT,
                unrealized_return REAL NOT NULL DEFAULT 0,
                source_filename TEXT,
                imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (user_id, as_of, account_number, symbol)
            );

            INSERT INTO holdings_snapshots (
                id,
                user_id,
                as_of,
                account_name,
                account_type,
                account_classification,
                account_number,
                symbol,
                exchange,
                mic,
                security_name,
                security_type,
                quantity,
                market_price,
                market_price_currency,
                book_value_cad,
                market_value,
                market_value_currency,
                unrealized_return,
                source_filename,
                imported_at
            )
            SELECT
                id,
                0,
                as_of,
                account_name,
                account_type,
                account_classification,
                account_number,
                symbol,
                exchange,
                mic,
                security_name,
                security_type,
                quantity,
                market_price,
                market_price_currency,
                book_value_cad,
                market_value,
                market_value_currency,
                unrealized_return,
                source_filename,
                imported_at
            FROM holdings_snapshots_old;

            DROP TABLE holdings_snapshots_old;
            """
        )

    if _table_exists(cursor, "net_worth_history") and not _has_column(cursor, "net_worth_history", "user_id"):
        cursor.executescript(
            """
            ALTER TABLE net_worth_history RENAME TO net_worth_history_old;

            CREATE TABLE net_worth_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
                entry_date TEXT NOT NULL,
                amount REAL NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (user_id, entry_date)
            );

            INSERT INTO net_worth_history (
                id,
                user_id,
                entry_date,
                amount,
                note,
                created_at,
                updated_at
            )
            SELECT
                id,
                0,
                entry_date,
                amount,
                note,
                created_at,
                updated_at
            FROM net_worth_history_old;

            DROP TABLE net_worth_history_old;
            """
        )

    if not _has_column(cursor, "credit_card_transactions", "user_id"):
        cursor.execute("ALTER TABLE credit_card_transactions ADD COLUMN user_id INTEGER NOT NULL DEFAULT 0")

    if _table_exists(cursor, "app_settings") and not _has_column(cursor, "app_settings", "user_id"):
        cursor.executescript(
            """
            ALTER TABLE app_settings RENAME TO app_settings_old;

            CREATE TABLE app_settings (
                user_id INTEGER NOT NULL DEFAULT 0,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, key)
            );

            INSERT INTO app_settings (user_id, key, value, updated_at)
            SELECT 0, key, value, updated_at
            FROM app_settings_old;

            DROP TABLE app_settings_old;
            """
        )

    if _table_exists(cursor, "users") and not _has_column(cursor, "users", "auth_provider"):
        cursor.execute(
            "ALTER TABLE users ADD COLUMN auth_provider TEXT NOT NULL DEFAULT 'local'"
        )
    if _table_exists(cursor, "users") and not _has_column(cursor, "users", "external_subject"):
        cursor.execute("ALTER TABLE users ADD COLUMN external_subject TEXT")

    if _has_column(cursor, "transactions", "user_id"):
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_transactions_user_security_date
            ON transactions (user_id, security, trade_date, id)
            """
        )

    if _has_column(cursor, "holdings_snapshots", "user_id"):
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_holdings_user_as_of_account
            ON holdings_snapshots (user_id, as_of, account_number, symbol)
            """
        )

    if _has_column(cursor, "net_worth_history", "user_id"):
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_net_worth_user_entry_date
            ON net_worth_history (user_id, entry_date)
            """
        )

    if _has_column(cursor, "credit_card_transactions", "user_id"):
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_cc_user_provider_date
            ON credit_card_transactions (user_id, provider, transaction_date, id)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_cc_user_provider_category
            ON credit_card_transactions (user_id, provider, merchant_category)
            """
        )

    existing_columns = {
        row[1] for row in cursor.execute("PRAGMA table_info(credit_card_transactions)").fetchall()
    }
    if "is_hidden" not in existing_columns:
        cursor.execute(
            "ALTER TABLE credit_card_transactions ADD COLUMN is_hidden INTEGER NOT NULL DEFAULT 0"
        )


def _normalize_credit_categories(cursor):
    category_rows = cursor.execute(
        "SELECT id, merchant_category FROM credit_card_transactions"
    ).fetchall()
    for row in category_rows:
        current_value = row[1] or ""
        normalized_value = normalize_credit_card_category(current_value)
        if normalized_value != current_value:
            cursor.execute(
                "UPDATE credit_card_transactions SET merchant_category = ? WHERE id = ?",
                (normalized_value, row[0]),
            )


def get_db():
    # Defensive initialization: guarantees required tables exist even if
    # process startup did not run schema initialization (e.g. worker restarts).
    init_db()
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(_=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    cursor = connection.cursor()
    cursor.execute("PRAGMA foreign_keys = OFF")

    _apply_schema(cursor)
    _apply_migrations(cursor)
    _normalize_credit_categories(cursor)

    connection.commit()
    connection.close()
