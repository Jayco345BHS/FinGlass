import csv
import re
from datetime import datetime
from io import StringIO
from pathlib import Path

from .db import get_db


def _parse_number(value, default=0.0):
    if value is None:
        return default
    cleaned = str(value).strip().replace(",", "")
    is_negative = cleaned.startswith("(") and cleaned.endswith(")")
    cleaned = cleaned.replace("$", "").replace("(", "").replace(")", "")
    if cleaned == "":
        return default
    parsed = float(cleaned)
    return -parsed if is_negative else parsed


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


def _extract_iso_date(value):
    match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", value or "")
    return match.group(1) if match else None


def _extract_as_of_date(csv_text, filename=""):
    for line in csv_text.splitlines():
        maybe_date = _extract_iso_date(line)
        if maybe_date:
            return maybe_date

    fallback = _extract_iso_date(filename)
    if fallback:
        return fallback

    return datetime.now().strftime("%Y-%m-%d")


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


def parse_holdings_csv_text(csv_text, filename=""):
    as_of = _extract_as_of_date(csv_text, filename)
    rows = []
    reader = csv.DictReader(StringIO(csv_text))

    for item in reader:
        symbol = (item.get("Symbol") or "").strip().upper()
        account_number = (item.get("Account Number") or "").strip()
        account_name = (item.get("Account Name") or "").strip()

        if not symbol or not account_number or not account_name:
            continue

        rows.append(
            {
                "as_of": as_of,
                "account_name": account_name,
                "account_type": (item.get("Account Type") or "").strip(),
                "account_classification": (item.get("Account Classification") or "").strip(),
                "account_number": account_number,
                "symbol": symbol,
                "exchange": (item.get("Exchange") or "").strip(),
                "mic": (item.get("MIC") or "").strip(),
                "security_name": (item.get("Name") or "").strip(),
                "security_type": (item.get("Security Type") or "").strip(),
                "quantity": _parse_number(item.get("Quantity"), 0.0),
                "market_price": _parse_number(item.get("Market Price"), 0.0),
                "market_price_currency": (item.get("Market Price Currency") or "").strip(),
                "book_value_cad": _parse_number(item.get("Book Value (CAD)"), 0.0),
                "market_value": _parse_number(item.get("Market Value"), 0.0),
                "market_value_currency": (item.get("Market Value Currency") or "").strip(),
                "unrealized_return": _parse_number(item.get("Market Unrealized Returns"), 0.0),
            }
        )

    return rows


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


def import_holdings_rows(parsed_rows, source_filename=""):
    db = get_db()
    inserted = 0
    updated = 0

    for row in parsed_rows:
        existing = db.execute(
            """
            SELECT 1
            FROM holdings_snapshots
            WHERE as_of = ? AND account_number = ? AND symbol = ?
            LIMIT 1
            """,
            (row["as_of"], row["account_number"], row["symbol"]),
        ).fetchone()

        cursor = db.execute(
            """
            INSERT INTO holdings_snapshots (
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
                source_filename
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(as_of, account_number, symbol)
            DO UPDATE SET
                account_name = excluded.account_name,
                account_type = excluded.account_type,
                account_classification = excluded.account_classification,
                exchange = excluded.exchange,
                mic = excluded.mic,
                security_name = excluded.security_name,
                security_type = excluded.security_type,
                quantity = excluded.quantity,
                market_price = excluded.market_price,
                market_price_currency = excluded.market_price_currency,
                book_value_cad = excluded.book_value_cad,
                market_value = excluded.market_value,
                market_value_currency = excluded.market_value_currency,
                unrealized_return = excluded.unrealized_return,
                source_filename = excluded.source_filename,
                imported_at = CURRENT_TIMESTAMP
            """,
            (
                row["as_of"],
                row["account_name"],
                row.get("account_type", ""),
                row.get("account_classification", ""),
                row["account_number"],
                row["symbol"],
                row.get("exchange", ""),
                row.get("mic", ""),
                row.get("security_name", ""),
                row.get("security_type", ""),
                row.get("quantity", 0.0),
                row.get("market_price", 0.0),
                row.get("market_price_currency", ""),
                row.get("book_value_cad", 0.0),
                row.get("market_value", 0.0),
                row.get("market_value_currency", ""),
                row.get("unrealized_return", 0.0),
                source_filename,
            ),
        )

        if existing:
            updated += 1
        else:
            inserted += 1

    db.commit()

    unique_as_of = sorted({row["as_of"] for row in parsed_rows})
    return {
        "parsed": len(parsed_rows),
        "inserted": inserted,
        "updated": updated,
        "as_of": unique_as_of[-1] if unique_as_of else None,
    }


def parse_rogers_credit_csv_text(csv_text):
    def normalize_header(header):
        return re.sub(r"[^a-z0-9]", "", str(header or "").lower())

    def get_value(row, *candidate_headers):
        for header in candidate_headers:
            value = row.get(normalize_header(header), "")
            if value is not None and str(value).strip() != "":
                return str(value).strip()
        return ""

    rows = []
    reader = csv.DictReader(StringIO(csv_text))

    for item in reader:
        normalized_item = {
            normalize_header(key): value for key, value in (item or {}).items() if key is not None
        }

        tx_date = get_value(normalized_item, "Date", "Transaction Date")
        if not tx_date:
            continue

        amount = _parse_number(get_value(normalized_item, "Amount"), 0.0)
        card_number = get_value(normalized_item, "Transaction Card Number", "Card Number")
        card_last4 = card_number[-4:] if len(card_number) >= 4 else ""

        rows.append(
            {
                "provider": "rogers_bank",
                "transaction_date": tx_date,
                "posted_date": get_value(normalized_item, "Posted Date"),
                "reference_number": get_value(normalized_item, "Reference Number").replace('"', ""),
                "activity_type": get_value(normalized_item, "Activity Type"),
                "status": get_value(normalized_item, "Status", "Activity Status"),
                "card_last4": card_last4,
                "merchant_category": get_value(
                    normalized_item,
                    "Merchant Category",
                    "Merchant Category Description",
                ),
                "merchant_name": get_value(normalized_item, "Merchant Name"),
                "merchant_city": get_value(normalized_item, "Merchant City"),
                "merchant_region": get_value(
                    normalized_item,
                    "Merchant State/Province",
                    "Merchant State or Province",
                ),
                "merchant_country": get_value(
                    normalized_item,
                    "Merchant Country",
                    "Merchant Country Code",
                ),
                "merchant_postal": get_value(
                    normalized_item,
                    "Merchant Postal Code/Zip",
                    "Merchant Postal Code",
                ),
                "amount": amount,
                "rewards": _parse_number(get_value(normalized_item, "Rewards"), 0.0),
                "cardholder_name": get_value(normalized_item, "Name on Card"),
            }
        )

    return rows


def import_rogers_credit_rows(parsed_rows, source_filename=""):
    db = get_db()
    inserted = 0

    for row in parsed_rows:
        existing = db.execute(
            """
            SELECT 1
            FROM credit_card_transactions
            WHERE provider = ?
              AND transaction_date = ?
              AND posted_date = ?
              AND card_last4 = ?
              AND reference_number = ?
              AND ABS(amount - ?) < 0.000001
              AND COALESCE(merchant_name, '') = COALESCE(?, '')
            LIMIT 1
            """,
            (
                row["provider"],
                row["transaction_date"],
                row.get("posted_date", ""),
                row.get("card_last4", ""),
                row.get("reference_number", ""),
                row["amount"],
                row.get("merchant_name", ""),
            ),
        ).fetchone()

        if existing:
            continue

        db.execute(
            """
            INSERT INTO credit_card_transactions (
                provider,
                transaction_date,
                posted_date,
                reference_number,
                activity_type,
                status,
                card_last4,
                merchant_category,
                merchant_name,
                merchant_city,
                merchant_region,
                merchant_country,
                merchant_postal,
                amount,
                rewards,
                cardholder_name,
                source_filename
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["provider"],
                row["transaction_date"],
                row.get("posted_date", ""),
                row.get("reference_number", ""),
                row.get("activity_type", ""),
                row.get("status", ""),
                row.get("card_last4", ""),
                row.get("merchant_category", ""),
                row.get("merchant_name", ""),
                row.get("merchant_city", ""),
                row.get("merchant_region", ""),
                row.get("merchant_country", ""),
                row.get("merchant_postal", ""),
                row["amount"],
                row.get("rewards", 0.0),
                row.get("cardholder_name", ""),
                source_filename,
            ),
        )
        inserted += 1

    db.commit()
    return {"parsed": len(parsed_rows), "inserted": inserted}


def import_transactions(file_path):
    parsed_rows = parse_adjustedcostbase_csv(file_path)
    return import_transactions_rows(parsed_rows)
