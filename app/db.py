import sqlite3
from pathlib import Path
from flask import g

from .credit_card_categories import normalize_credit_card_category

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "finglass.sqlite3"


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
    cursor.executescript(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            UNIQUE (as_of, account_number, symbol)
        );

        CREATE INDEX IF NOT EXISTS idx_holdings_as_of_account
            ON holdings_snapshots (as_of, account_number, symbol);

        CREATE TABLE IF NOT EXISTS net_worth_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_date TEXT NOT NULL UNIQUE,
            amount REAL NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_net_worth_entry_date
            ON net_worth_history (entry_date);

        CREATE TABLE IF NOT EXISTS credit_card_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    existing_columns = {
        row[1] for row in cursor.execute("PRAGMA table_info(credit_card_transactions)").fetchall()
    }
    if "is_hidden" not in existing_columns:
        cursor.execute(
            "ALTER TABLE credit_card_transactions ADD COLUMN is_hidden INTEGER NOT NULL DEFAULT 0"
        )

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

    connection.commit()
    connection.close()
