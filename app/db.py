import sqlite3
from pathlib import Path
from flask import g

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "acb.sqlite3"


def get_db():
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
        """
    )
    connection.commit()
    connection.close()
