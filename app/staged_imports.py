import csv
import re
from collections import Counter
from datetime import datetime
from io import BytesIO, StringIO
from pathlib import Path

from pypdf import PdfReader

from .db import get_db
from .importer import parse_adjustedcostbase_csv_text

SUPPORTED_IMPORT_TYPES = {"activities_csv", "tax_pdf", "acb_csv"}


def _parse_number(value, default=0.0):
    if value is None:
        return default
    cleaned = str(value).strip().replace(",", "")
    if cleaned == "":
        return default
    return float(cleaned)


def _normalize_date(raw):
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("Missing date")

    for fmt in ("%Y-%m-%d", "%Y-%b-%d"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    raise ValueError(f"Unsupported date format: {raw}")


def parse_activities_csv_text(csv_text):
    reader = csv.DictReader(StringIO(csv_text))
    rows = []

    for item in reader:
        activity_type = (item.get("activity_type") or "").strip()
        symbol = (item.get("symbol") or "").strip().upper()
        if not activity_type:
            continue

        mapped_type = None
        amount = 0.0
        shares = 0.0

        if activity_type == "Trade":
            sub_type = (item.get("activity_sub_type") or "").strip().upper()
            quantity = _parse_number(item.get("quantity"), 0.0)
            net_cash = _parse_number(item.get("net_cash_amount"), 0.0)
            commission = _parse_number(item.get("commission"), 0.0)

            if sub_type == "BUY":
                mapped_type = "Buy"
                shares = abs(quantity)
                amount = abs(net_cash)
            elif sub_type == "SELL":
                mapped_type = "Sell"
                shares = abs(quantity)
                amount = abs(net_cash)
            else:
                continue
        elif activity_type == "ReturnOfCapital":
            mapped_type = "Return of Capital"
            amount = abs(_parse_number(item.get("net_cash_amount"), 0.0))
            shares = 0.0
            commission = 0.0
        else:
            continue

        if not symbol:
            continue

        trade_date = _normalize_date(item.get("transaction_date", ""))
        amount_per_share = amount / shares if shares else 0.0
        commission = _parse_number(item.get("commission"), 0.0)

        rows.append(
            {
                "security": symbol,
                "trade_date": trade_date,
                "transaction_type": mapped_type,
                "amount": amount,
                "shares": shares,
                "amount_per_share": amount_per_share,
                "commission": commission,
                "source": "activities_csv",
            }
        )

    return rows


def _extract_security_from_filename(filename):
    stem = Path(filename or "").stem.upper()
    match = re.match(r"([A-Z][A-Z0-9.\-]{0,9})", stem)
    if match:
        return match.group(1)
    return ""


def _extract_tax_year(text):
    years = [int(y) for y in re.findall(r"\b(20\d{2})\b", text)]
    years = [y for y in years if 2000 <= y <= 2100]
    if not years:
        return datetime.now().year
    common = Counter(years).most_common(1)[0][0]
    return common


def _extract_first_amount(text, patterns):
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            value = match.group(1)
            return abs(_parse_number(value, 0.0))
    return 0.0


def _extract_distribution_blocks(text):
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    date_indexes = []
    for idx, line in enumerate(lines):
        if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", line):
            date_indexes.append(idx)

    blocks = []
    for i in range(len(date_indexes) - 1):
        record_idx = date_indexes[i]
        payment_idx = date_indexes[i + 1]

        if payment_idx - record_idx > 6:
            continue

        # Use the record date as the trade date so that Q4 distributions
        # (whose payment date can fall in January of the next year) are
        # attributed to the correct T3 tax year.
        record_date = lines[record_idx]

        if i + 2 < len(date_indexes):
            next_date_idx = date_indexes[i + 2]
            # Each distribution block in the PDF prints a short summary of
            # values (e.g. "Total Distribution") *before* its own record date.
            # These pre-date lines appear between the previous block's payment
            # date and this record date, so they contaminate the current
            # block's value window.  Scan backwards from the next record date
            # to identify and exclude those trailing numeric lines, capped at
            # 2 (the number of pre-date summary rows seen in T3/RL-16 PDFs).
            j = next_date_idx - 1
            pre_date_numeric = 0
            while (
                j > payment_idx
                and pre_date_numeric < 2
                and re.fullmatch(r"[\d,]+(?:\.\d+)?", lines[j])
            ):
                pre_date_numeric += 1
                j -= 1
            stop_idx = next_date_idx - pre_date_numeric
        else:
            next_date_idx = len(lines)
            stop_idx = next_date_idx

        value_lines = lines[payment_idx + 1 : stop_idx]

        values = []
        for value_line in value_lines:
            if re.fullmatch(r"[\d,]+(?:\.\d+)?", value_line):
                values.append(_parse_number(value_line, 0.0))
            else:
                # Stop once table section appears to end.
                if values:
                    break

        if not values:
            continue

        blocks.append(
            {
                "record_date": record_date,
                "payment_date": lines[payment_idx],
                "values": values,
            }
        )

    return blocks


def _guess_roc_from_values(values):
    """Return the Return of Capital per-unit value from an extracted value list.

    T3/RL-16 PDFs expose two distinct tail patterns after stripping the
    trailing Total Income Allocation echo:

      Case 1 — [... ROC, Non-Reportable]
        Non-Reportable is 1–50 % larger than ROC (ratio 1.0–1.5×).
        Seen in XEQT Q1-Q3 blocks.

      Case 2 — [... ROC, FX-tax-paid]
        FX-tax is much larger than ROC (ratio >> 1.5×, typically ~100–300×).
        ROC is confirmed by also being much smaller (< 50 %) than the value
        immediately before it (the last income row, e.g. FX Non-Business Income).
        Seen in VFV and XEQT Q4 blocks.
    """
    if not values:
        return 0.0

    total_cash = values[0]

    # Strip trailing Income-Allocation values that equal Total Cash.
    meaningful = list(values)
    while meaningful and abs(meaningful[-1] - total_cash) < 0.0001:
        meaningful.pop()

    if len(meaningful) < 2:
        return 0.0

    roc_candidate = meaningful[-2]
    next_val = meaningful[-1]

    if roc_candidate < 0.00001:
        return 0.0

    ratio = next_val / roc_candidate if roc_candidate > 0 else 0.0

    # Case 1: [ROC, Non-Reportable] — very close in magnitude.
    if 1.0 < ratio <= 1.5:
        return roc_candidate

    # Case 2: [ROC, FX-tax-paid] — FX-tax is much larger than ROC.
    # Confirm by checking the ROC candidate is also much smaller than the
    # income value that precedes it (e.g. FX Non-Business Income).
    if ratio > 1.5 and len(meaningful) >= 3:
        prev_val = meaningful[-3]
        if prev_val > 0 and roc_candidate < prev_val * 0.5:
            return roc_candidate

    return 0.0


def _extract_non_cash_mentions(text):
    mentions = []
    for match in re.finditer(
        r"non[-\s]?cash\s+distribution[^$\d]*\$\s*([\d,]+(?:\.\d+)?)",
        text,
        flags=re.IGNORECASE,
    ):
        mentions.append(abs(_parse_number(match.group(1), 0.0)))
    return mentions


def _guess_non_cash_from_values(values, non_cash_mentions):
    positive = [v for v in values if v > 0.0]
    if not positive:
        return 0.0

    # Prefer explicit values referenced in text (e.g. "$0.32215" in explanatory notes).
    for mention in non_cash_mentions:
        for value in positive:
            if abs(value - mention) <= 0.0002:
                return value

    # Conservative fallback by row ordering near payment date:
    # first value is typically cash, second is non-cash, third is total distribution/income.
    if len(positive) >= 3:
        cash = positive[0]
        non_cash = positive[1]
        total = positive[2]
        if abs((cash + non_cash) - total) <= 0.002:
            return non_cash

    return 0.0


def parse_tax_pdf_bytes(pdf_bytes, filename):
    reader = PdfReader(BytesIO(pdf_bytes))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)

    security = _extract_security_from_filename(filename)
    tax_year = _extract_tax_year(text)
    trade_date = f"{tax_year}-12-31"

    roc_amount = _extract_first_amount(
        text,
        [
            r"return\s+of\s+capital[^\d\-]*([\d,]*\.\d+)",
            r"roc[^\d\-]*([\d,]*\.\d+)",
        ],
    )
    rcg_amount = _extract_first_amount(
        text,
        [
            r"reinvested\s+capital\s+gains?(?:\s+distribution)?[^\d\-]*([\d,]*\.\d+)",
            r"capital\s+gains?\s+distribution[^\d\-]*([\d,]*\.\d+)",
        ],
    )

    rows = []

    distribution_blocks = _extract_distribution_blocks(text)
    non_cash_mentions = _extract_non_cash_mentions(text)
    for block in distribution_blocks:
        guessed_roc = _guess_roc_from_values(block["values"])
        if guessed_roc <= 0:
            guessed_roc = 0.0

        guessed_non_cash = _guess_non_cash_from_values(block["values"], non_cash_mentions)

        if guessed_roc > 0:
            rows.append(
                {
                    "security": security,
                    "trade_date": block["record_date"],
                    "transaction_type": "Return of Capital",
                    "amount": guessed_roc,
                    "shares": 0.0,
                    "amount_per_share": 0.0,
                    "commission": 0.0,
                    "source": "tax_pdf",
                }
            )

        if guessed_non_cash > 0:
            rows.append(
                {
                    "security": security,
                    "trade_date": block["record_date"],
                    "transaction_type": "Reinvested Capital Gains Distribution",
                    "amount": guessed_non_cash,
                    "shares": 0.0,
                    "amount_per_share": 0.0,
                    "commission": 0.0,
                    "source": "tax_pdf",
                }
            )

    if not rows and roc_amount > 0:
        rows.append(
            {
                "security": security,
                "trade_date": trade_date,
                "transaction_type": "Return of Capital",
                "amount": roc_amount,
                "shares": 0.0,
                "amount_per_share": 0.0,
                "commission": 0.0,
                "source": "tax_pdf",
            }
        )

    has_rcg = any(r["transaction_type"] == "Reinvested Capital Gains Distribution" for r in rows)
    if rcg_amount > 0 and not has_rcg:
        rows.append(
            {
                "security": security,
                "trade_date": trade_date,
                "transaction_type": "Reinvested Capital Gains Distribution",
                "amount": rcg_amount,
                "shares": 0.0,
                "amount_per_share": 0.0,
                "commission": 0.0,
                "source": "tax_pdf",
            }
        )

    return rows


def parse_upload(import_type, filename, file_bytes):
    if import_type == "activities_csv":
        text = file_bytes.decode("utf-8-sig")
        return parse_activities_csv_text(text)

    if import_type == "acb_csv":
        text = file_bytes.decode("utf-8-sig")
        parsed = parse_adjustedcostbase_csv_text(text)
        for item in parsed:
            item["source"] = "acb_csv"
        return parsed

    if import_type == "tax_pdf":
        return parse_tax_pdf_bytes(file_bytes, filename)

    raise ValueError("Unsupported import type")


def create_import_batch(source_type, source_filename, rows):
    db = get_db()
    cursor = db.execute(
        """
        INSERT INTO import_batches (source_type, source_filename, status)
        VALUES (?, ?, 'staged')
        """,
        (source_type, source_filename),
    )
    batch_id = cursor.lastrowid

    for idx, row in enumerate(rows, start=1):
        db.execute(
            """
            INSERT INTO import_batch_rows
            (batch_id, row_order, security, trade_date, transaction_type, amount, shares, amount_per_share, commission, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                idx,
                row["security"],
                row["trade_date"],
                row["transaction_type"],
                row["amount"],
                row["shares"],
                row.get("amount_per_share", 0.0),
                row.get("commission", 0.0),
                row.get("source", source_type),
            ),
        )

    db.commit()
    return batch_id


def get_batch(batch_id):
    db = get_db()
    batch = db.execute("SELECT * FROM import_batches WHERE id = ?", (batch_id,)).fetchone()
    if not batch:
        return None

    rows = db.execute(
        """
        SELECT *
        FROM import_batch_rows
        WHERE batch_id = ?
        ORDER BY row_order, id
        """,
        (batch_id,),
    ).fetchall()

    return {
        "batch": dict(batch),
        "rows": [dict(r) for r in rows],
    }


def update_batch_row(batch_id, row_id, payload):
    db = get_db()
    cursor = db.execute(
        "SELECT id FROM import_batch_rows WHERE id = ? AND batch_id = ?",
        (row_id, batch_id),
    )
    if not cursor.fetchone():
        return False

    security = str(payload.get("security") or "").strip().upper()
    trade_date = _normalize_date(str(payload.get("trade_date") or ""))
    transaction_type = str(payload.get("transaction_type") or "").strip()
    amount = float(payload.get("amount") or 0)
    shares = float(payload.get("shares") or 0)
    commission = float(payload.get("commission") or 0)
    amount_per_share = amount / shares if shares else 0.0

    db.execute(
        """
        UPDATE import_batch_rows
        SET security = ?,
            trade_date = ?,
            transaction_type = ?,
            amount = ?,
            shares = ?,
            amount_per_share = ?,
            commission = ?
        WHERE id = ? AND batch_id = ?
        """,
        (
            security,
            trade_date,
            transaction_type,
            amount,
            shares,
            amount_per_share,
            commission,
            row_id,
            batch_id,
        ),
    )
    db.commit()
    return True


def delete_batch_row(batch_id, row_id):
    db = get_db()
    cursor = db.execute(
        "DELETE FROM import_batch_rows WHERE id = ? AND batch_id = ?",
        (row_id, batch_id),
    )
    db.commit()
    return cursor.rowcount > 0


def commit_batch(batch_id):
    from .importer import import_transactions_rows

    db = get_db()
    batch = db.execute("SELECT * FROM import_batches WHERE id = ?", (batch_id,)).fetchone()
    if not batch:
        return None

    if batch["status"] == "committed":
        return {"inserted": 0, "parsed": 0, "already_committed": True}

    rows = db.execute(
        """
        SELECT security, trade_date, transaction_type, amount, shares, amount_per_share, commission, source
        FROM import_batch_rows
        WHERE batch_id = ?
        ORDER BY row_order, id
        """,
        (batch_id,),
    ).fetchall()

    parsed_rows = []
    for row in rows:
        parsed_rows.append(
            {
                "security": row["security"],
                "trade_date": row["trade_date"],
                "transaction_type": row["transaction_type"],
                "amount": row["amount"],
                "shares": row["shares"],
                "amount_per_share": row["amount_per_share"],
                "commission": row["commission"],
                "source": row["source"],
            }
        )

    summary = import_transactions_rows(parsed_rows)

    db.execute(
        """
        UPDATE import_batches
        SET status = 'committed',
            committed_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (batch_id,),
    )
    db.commit()

    return summary
