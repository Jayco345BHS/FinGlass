import csv
from io import StringIO

from .fhsa_service import (
    FHSA_FIRST_YEAR,
    FHSA_MAX_OPEN_YEARS,
    FHSA_TRACKED_OPENING_ROOM_CAP,
    create_fhsa_transfer,
)


def _normalize_header(value):
    return str(value or "").strip().lower().replace(" ", "_")


def _normalize_type(value):
    normalized = str(value or "").strip().lower()
    if normalized in {"deposit", "contribution", "add"}:
        return "Deposit"
    if normalized in {"withdrawal", "withdraw", "remove"}:
        return "Withdrawal"
    if normalized in {"transfer", "xfer"}:
        return "Transfer"
    if normalized in {
        "openingbalance",
        "opening_balance",
        "opening",
        "startingroom",
        "starting_room",
        "openingfhsaroom",
        "opening_fhsa_room",
    }:
        return "OpeningBalance"
    return ""


def _parse_float(raw_value, *, row_index, field_name):
    try:
        amount = float(str(raw_value or "0").replace(",", ""))
    except ValueError as exc:
        raise ValueError(f"Row {row_index}: invalid {field_name} '{raw_value}'") from exc
    return amount


def _parse_bool(raw_value):
    if isinstance(raw_value, bool):
        return raw_value
    return str(raw_value or "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_year(raw_value):
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    if not text:
        return None

    candidate = text[:4]
    try:
        year = int(candidate)
    except ValueError:
        return None

    if 2023 <= year <= 2100:
        return year
    return None


def parse_fhsa_import_csv_text(csv_text):
    reader = csv.DictReader(StringIO(csv_text))
    transactions = []
    opening_balance = None
    opening_balance_base_year = None

    for index, raw in enumerate(reader, start=2):
        row = {
            _normalize_header(key): (value or "").strip()
            for key, value in (raw or {}).items()
            if key is not None
        }

        contribution_date = row.get("date") or row.get("contribution_date")
        account_name = row.get("account") or row.get("account_name")
        contribution_type = _normalize_type(row.get("type") or row.get("contribution_type"))
        amount_raw = row.get("amount")
        memo = row.get("memo") or ""
        destination_account_name = row.get("destination_account") or row.get("to_account") or ""
        is_qualifying_withdrawal = _parse_bool(
            row.get("is_qualifying_withdrawal")
            or row.get("qualifying_withdrawal")
            or row.get("qualifying")
        )
        explicit_year = row.get("year") or row.get("base_year")

        if not any(
            [
                contribution_date,
                account_name,
                contribution_type,
                amount_raw,
                memo,
                destination_account_name,
                explicit_year,
            ]
        ):
            continue

        if contribution_type == "OpeningBalance":
            amount = _parse_float(amount_raw, row_index=index, field_name="amount")
            if amount < 0:
                raise ValueError(f"Row {index}: opening balance must be >= 0")
            if amount > FHSA_TRACKED_OPENING_ROOM_CAP:
                raise ValueError(
                    f"Row {index}: opening balance must be <= {int(FHSA_TRACKED_OPENING_ROOM_CAP)}"
                )

            row_base_year = _parse_year(explicit_year) or _parse_year(contribution_date)
            opening_balance = amount
            if row_base_year is not None:
                opening_balance_base_year = row_base_year
            continue

        if not contribution_date:
            raise ValueError(f"Row {index}: date is required")

        if not account_name:
            raise ValueError(f"Row {index}: account is required")

        if contribution_type not in {"Deposit", "Withdrawal", "Transfer"}:
            raise ValueError(
                f"Row {index}: type must be Deposit, Withdrawal, Transfer, or OpeningBalance"
            )

        amount = _parse_float(amount_raw, row_index=index, field_name="amount")
        if amount <= 0:
            raise ValueError(f"Row {index}: amount must be > 0")

        if contribution_type == "Transfer" and not destination_account_name:
            raise ValueError(f"Row {index}: destination_account is required for Transfer")

        transactions.append(
            {
                "contribution_date": contribution_date,
                "account_name": account_name,
                "contribution_type": contribution_type,
                "amount": amount,
                "memo": memo,
                "is_qualifying_withdrawal": bool(is_qualifying_withdrawal),
                "destination_account_name": destination_account_name,
            }
        )

    return {
        "transactions": transactions,
        "opening_balance": opening_balance,
        "opening_balance_base_year": opening_balance_base_year,
    }


def validate_fhsa_import_rows(parsed_rows, *, opening_base_year=None):
    inferred_open_year = opening_base_year
    if inferred_open_year is None:
        years = []
        for row in parsed_rows:
            try:
                years.append(int(str(row.get("contribution_date") or "")[:4]))
            except (TypeError, ValueError):
                continue
        if years:
            inferred_open_year = min(years)

    if inferred_open_year is not None:
        normalized_open_year = max(FHSA_FIRST_YEAR, min(2100, int(inferred_open_year)))
        last_active_year = normalized_open_year + FHSA_MAX_OPEN_YEARS - 1
        for row in parsed_rows:
            row_type = str(row.get("contribution_type") or "")
            if row_type not in {"Deposit", "Transfer"}:
                continue
            try:
                row_year = int(str(row.get("contribution_date") or "")[:4])
            except (TypeError, ValueError):
                continue
            if row_year > last_active_year:
                raise ValueError(
                    "FHSA import has contribution activity outside the 15-year account window. "
                    f"First opened year: {normalized_open_year}; last contribution year: {last_active_year}; "
                    f"invalid row year: {row_year}; row type: {row_type}."
                )

    qualifying_dates = []
    for row in parsed_rows:
        if row.get("contribution_type") == "Withdrawal" and bool(row.get("is_qualifying_withdrawal")):
            qualifying_dates.append(str(row.get("contribution_date") or "").strip())

    if not qualifying_dates:
        return

    first_qualifying_date = min(qualifying_dates)

    for row in parsed_rows:
        row_date = str(row.get("contribution_date") or "").strip()
        row_type = str(row.get("contribution_type") or "")
        if row_date > first_qualifying_date and row_type in {"Deposit", "Transfer"}:
            raise ValueError(
                "FHSA import contains contribution activity after a qualifying withdrawal date. "
                f"First qualifying withdrawal: {first_qualifying_date}; invalid row date: {row_date}; "
                f"row type: {row_type}."
            )


def import_fhsa_transactions_rows(db, user_id, parsed_rows):
    account_map = {
        row["account_name"]: int(row["id"])
        for row in db.execute(
            "SELECT id, account_name FROM fhsa_accounts WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    }

    def get_or_create_account_id(account_name):
        normalized = str(account_name or "").strip()
        if not normalized:
            raise ValueError("account_name is required")

        if normalized in account_map:
            return account_map[normalized]

        cursor = db.execute(
            "INSERT INTO fhsa_accounts (user_id, account_name, opening_balance) VALUES (?, ?, 0)",
            (user_id, normalized),
        )
        account_id = int(cursor.lastrowid)
        account_map[normalized] = account_id
        return account_id

    inserted = 0
    skipped = 0
    transfers = 0
    inferred_base_year = None

    for row in parsed_rows:
        try:
            row_year = int(str(row["contribution_date"])[:4])
            if 2023 <= row_year <= 2100:
                inferred_base_year = row_year if inferred_base_year is None else min(inferred_base_year, row_year)
        except (TypeError, ValueError):
            pass

        source_account_id = get_or_create_account_id(row["account_name"])

        if row["contribution_type"] == "Transfer":
            destination_account_id = get_or_create_account_id(row["destination_account_name"])

            user_memo = str(row["memo"] or "").strip()
            source_memo = f"[Transfer to {row['destination_account_name']}]"
            destination_memo = f"[Transfer from {row['account_name']}]"
            if user_memo:
                source_memo = f"{source_memo} {user_memo}"
                destination_memo = f"{destination_memo} {user_memo}"

            source_existing = db.execute(
                """
                SELECT 1
                FROM fhsa_contributions
                WHERE user_id = ?
                  AND fhsa_account_id = ?
                  AND contribution_date = ?
                  AND contribution_type = 'Withdrawal'
                  AND ABS(amount - ?) < 0.000001
                  AND COALESCE(memo, '') = COALESCE(?, '')
                LIMIT 1
                """,
                (
                    user_id,
                    source_account_id,
                    row["contribution_date"],
                    row["amount"],
                    source_memo,
                ),
            ).fetchone()
            destination_existing = db.execute(
                """
                SELECT 1
                FROM fhsa_contributions
                WHERE user_id = ?
                  AND fhsa_account_id = ?
                  AND contribution_date = ?
                  AND contribution_type = 'Deposit'
                  AND ABS(amount - ?) < 0.000001
                  AND COALESCE(memo, '') = COALESCE(?, '')
                LIMIT 1
                """,
                (
                    user_id,
                    destination_account_id,
                    row["contribution_date"],
                    row["amount"],
                    destination_memo,
                ),
            ).fetchone()

            if source_existing and destination_existing:
                skipped += 1
                continue

            create_fhsa_transfer(
                db=db,
                user_id=user_id,
                from_fhsa_account_id=source_account_id,
                to_fhsa_account_id=destination_account_id,
                transfer_date=row["contribution_date"],
                amount=row["amount"],
                memo=row["memo"],
            )
            transfers += 1
            continue

        existing = db.execute(
            """
            SELECT 1
            FROM fhsa_contributions
            WHERE user_id = ?
              AND fhsa_account_id = ?
              AND contribution_date = ?
              AND contribution_type = ?
              AND is_qualifying_withdrawal = ?
              AND ABS(amount - ?) < 0.000001
              AND COALESCE(memo, '') = COALESCE(?, '')
            LIMIT 1
            """,
            (
                user_id,
                source_account_id,
                row["contribution_date"],
                row["contribution_type"],
                1 if bool(row.get("is_qualifying_withdrawal")) else 0,
                row["amount"],
                row["memo"],
            ),
        ).fetchone()

        if existing:
            skipped += 1
            continue

        db.execute(
            """
            INSERT INTO fhsa_contributions
            (user_id, fhsa_account_id, contribution_date, amount, contribution_type, is_qualifying_withdrawal, memo)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                source_account_id,
                row["contribution_date"],
                row["amount"],
                row["contribution_type"],
                1 if (row["contribution_type"] == "Withdrawal" and bool(row.get("is_qualifying_withdrawal"))) else 0,
                row["memo"],
            ),
        )
        inserted += 1

    db.commit()

    return {
        "parsed": len(parsed_rows),
        "inserted": inserted,
        "skipped": skipped,
        "transfers": transfers,
        "inferred_base_year": inferred_base_year,
    }
