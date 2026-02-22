import csv
from datetime import datetime
from io import StringIO
from pathlib import Path

from .db import get_db


def _parse_number(value, default=0.0):
    if value is None:
        return default
    cleaned = str(value).strip().replace(",", "")
    if cleaned == "":
        return default
    return float(cleaned)


def _normalize_date(value):
    raw = (value or "").strip()
    if not raw:
        raise ValueError("Missing trade date")

    for fmt in ("%Y-%b-%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    raise ValueError(f"Unsupported date format: {raw}")


def _parse_adjustedcostbase_csv_rows(reader):
    rows = []
    in_transactions_section = False
    header = []

    for raw in reader:
        row = [cell.strip() for cell in raw]

        if not any(row):
            continue

        if row and row[0] == "Security" and "Transaction" in row:
            in_transactions_section = True
            header = row
            continue

        if not in_transactions_section:
            continue

        if row[0] == "Grand Total":
            break

        mapped = {header[i]: row[i] if i < len(row) else "" for i in range(len(header))}
        transaction_type = mapped.get("Transaction", "").strip()
        if not transaction_type:
            continue

        rows.append(
            {
                "security": mapped.get("Security", "").strip(),
                "trade_date": _normalize_date(mapped.get("Date", "")),
                "transaction_type": transaction_type,
                "amount": _parse_number(mapped.get("Amount", "0"), 0.0),
                "shares": _parse_number(mapped.get("Shares", "0"), 0.0),
                "amount_per_share": _parse_number(mapped.get("Amount/Share", "0"), 0.0),
                "commission": _parse_number(mapped.get("Commission", "0"), 0.0),
                "memo": mapped.get("Memo", "").strip(),
                "source": "csv_import",
            }
        )

    return rows


def parse_adjustedcostbase_csv(file_path):
    file_path = Path(file_path)
    with file_path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        return _parse_adjustedcostbase_csv_rows(reader)


def parse_adjustedcostbase_csv_text(csv_text):
    stream = StringIO(csv_text)
    reader = csv.reader(stream)
    return _parse_adjustedcostbase_csv_rows(reader)


def import_transactions_rows(parsed_rows):
    db = get_db()

    inserted = 0
    for tx in parsed_rows:
        cursor = db.execute(
            """
            SELECT 1
            FROM transactions
            WHERE security = ?
              AND trade_date = ?
              AND transaction_type = ?
              AND ABS(amount - ?) < 0.000001
              AND ABS(shares - ?) < 0.000001
              AND ABS(commission - ?) < 0.000001
                            AND COALESCE(memo, '') = COALESCE(?, '')
            LIMIT 1
            """,
            (
                tx["security"],
                tx["trade_date"],
                tx["transaction_type"],
                tx["amount"],
                tx["shares"],
                tx["commission"],
                tx.get("memo", ""),
            ),
        )
        if cursor.fetchone():
            continue

        db.execute(
            """
            INSERT INTO transactions
            (security, trade_date, transaction_type, amount, shares, amount_per_share, commission, memo, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tx["security"],
                tx["trade_date"],
                tx["transaction_type"],
                tx["amount"],
                tx["shares"],
                tx["amount_per_share"],
                tx["commission"],
                tx.get("memo", ""),
                tx["source"],
            ),
        )
        inserted += 1

    db.commit()
    return {"parsed": len(parsed_rows), "inserted": inserted}


def import_transactions(file_path):
    parsed_rows = parse_adjustedcostbase_csv(file_path)
    return import_transactions_rows(parsed_rows)
