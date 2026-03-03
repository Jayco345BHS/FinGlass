import csv
from decimal import Decimal
from io import StringIO

from django.db import transaction

from core.models import TfsaAccount, TfsaContribution
from core.services.tfsa_service import create_tfsa_transfer


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
    if normalized in {"openingbalance", "opening_balance", "opening", "startingroom", "starting_room"}:
        return "OpeningBalance"
    if normalized in {"annuallimit", "annual_limit", "limit", "roomlimit", "room_limit"}:
        return "AnnualLimit"
    return ""


def _parse_float(raw_value, *, row_index, field_name):
    try:
        amount = float(str(raw_value or "0").replace(",", ""))
    except ValueError as exc:
        raise ValueError(f"Row {row_index}: invalid {field_name} '{raw_value}'") from exc
    return amount


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

    if 2009 <= year <= 2100:
        return year
    return None


def parse_tfsa_import_csv_text(csv_text):
    reader = csv.DictReader(StringIO(csv_text))
    transactions = []
    opening_balance = None
    opening_balance_base_year = None
    annual_limit_by_year = {}

    for index, raw in enumerate(reader, start=2):
        row = {_normalize_header(key): (value or "").strip() for key, value in (raw or {}).items() if key is not None}

        contribution_date = row.get("date") or row.get("contribution_date")
        account_name = row.get("account") or row.get("account_name")
        contribution_type = _normalize_type(row.get("type") or row.get("contribution_type"))
        amount_raw = row.get("amount")
        memo = row.get("memo") or ""
        destination_account_name = row.get("destination_account") or row.get("to_account") or ""
        explicit_year = row.get("year") or row.get("annual_limit_year") or row.get("base_year")

        if not any([contribution_date, account_name, contribution_type, amount_raw, memo, destination_account_name, explicit_year]):
            continue

        if contribution_type == "OpeningBalance":
            amount = _parse_float(amount_raw, row_index=index, field_name="amount")
            if amount < 0:
                raise ValueError(f"Row {index}: opening balance must be >= 0")

            row_base_year = _parse_year(explicit_year) or _parse_year(contribution_date)

            opening_balance = amount
            if row_base_year is not None:
                opening_balance_base_year = row_base_year
            continue

        if contribution_type == "AnnualLimit":
            year = _parse_year(explicit_year) or _parse_year(contribution_date)
            if year is None:
                raise ValueError(f"Row {index}: annual limit requires year (use year column or date)")

            amount = _parse_float(amount_raw, row_index=index, field_name="amount")
            if amount < 0:
                raise ValueError(f"Row {index}: annual limit must be >= 0")

            annual_limit_by_year[year] = amount
            continue

        if not contribution_date:
            raise ValueError(f"Row {index}: date is required")

        if not account_name:
            raise ValueError(f"Row {index}: account is required")

        if contribution_type not in {"Deposit", "Withdrawal", "Transfer"}:
            raise ValueError(
                f"Row {index}: type must be Deposit, Withdrawal, Transfer, OpeningBalance, or AnnualLimit"
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
                "destination_account_name": destination_account_name,
            }
        )

    annual_limits = [{"year": year, "annual_limit": annual_limit_by_year[year]} for year in sorted(annual_limit_by_year.keys())]

    return {
        "transactions": transactions,
        "opening_balance": opening_balance,
        "opening_balance_base_year": opening_balance_base_year,
        "annual_limits": annual_limits,
    }


def parse_tfsa_transactions_csv_text(csv_text):
    parsed = parse_tfsa_import_csv_text(csv_text)
    return parsed["transactions"]


def import_tfsa_transactions_rows(user_id, parsed_rows):
    account_map = {
        row["account_name"]: int(row["id"])
        for row in TfsaAccount.objects.filter(user_id=user_id).values("id", "account_name")
    }

    def get_or_create_account_id(account_name):
        normalized = str(account_name or "").strip()
        if not normalized:
            raise ValueError("account_name is required")

        if normalized in account_map:
            return account_map[normalized]

        account = TfsaAccount.objects.create(user_id=user_id, account_name=normalized, opening_balance=0)
        account_map[normalized] = int(account.id)
        return int(account.id)

    inserted = 0
    skipped = 0
    transfers = 0
    inferred_base_year = None
    tolerance = Decimal("0.000001")

    with transaction.atomic():
        for row in parsed_rows:
            try:
                row_year = int(str(row["contribution_date"])[:4])
                if 2009 <= row_year <= 2100:
                    inferred_base_year = row_year if inferred_base_year is None else min(inferred_base_year, row_year)
            except (TypeError, ValueError):
                pass

            source_account_id = get_or_create_account_id(row["account_name"])
            amount_decimal = Decimal(str(row["amount"]))
            amount_min = amount_decimal - tolerance
            amount_max = amount_decimal + tolerance

            if row["contribution_type"] == "Transfer":
                destination_account_id = get_or_create_account_id(row["destination_account_name"])

                user_memo = str(row["memo"] or "").strip()
                source_memo = f"[Transfer to {row['destination_account_name']}]"
                destination_memo = f"[Transfer from {row['account_name']}]"
                if user_memo:
                    source_memo = f"{source_memo} {user_memo}"
                    destination_memo = f"{destination_memo} {user_memo}"

                source_existing = TfsaContribution.objects.filter(
                    user_id=user_id,
                    tfsa_account_id=source_account_id,
                    contribution_date=row["contribution_date"],
                    contribution_type="Withdrawal",
                    amount__gte=amount_min,
                    amount__lte=amount_max,
                    memo=(source_memo or ""),
                ).exists()
                destination_existing = TfsaContribution.objects.filter(
                    user_id=user_id,
                    tfsa_account_id=destination_account_id,
                    contribution_date=row["contribution_date"],
                    contribution_type="Deposit",
                    amount__gte=amount_min,
                    amount__lte=amount_max,
                    memo=(destination_memo or ""),
                ).exists()

                if source_existing and destination_existing:
                    skipped += 1
                    continue

                create_tfsa_transfer(
                    user_id=user_id,
                    from_tfsa_account_id=source_account_id,
                    to_tfsa_account_id=destination_account_id,
                    transfer_date=row["contribution_date"],
                    amount=amount_decimal,
                    memo=row["memo"],
                )
                transfers += 1
                continue

            existing = TfsaContribution.objects.filter(
                user_id=user_id,
                tfsa_account_id=source_account_id,
                contribution_date=row["contribution_date"],
                contribution_type=row["contribution_type"],
                amount__gte=amount_min,
                amount__lte=amount_max,
                memo=(row["memo"] or ""),
            ).exists()

            if existing:
                skipped += 1
                continue

            TfsaContribution.objects.create(
                user_id=user_id,
                tfsa_account_id=source_account_id,
                contribution_date=row["contribution_date"],
                amount=amount_decimal,
                contribution_type=row["contribution_type"],
                memo=row["memo"],
            )
            inserted += 1

    return {
        "parsed": len(parsed_rows),
        "inserted": inserted,
        "skipped": skipped,
        "transfers": transfers,
        "inferred_base_year": inferred_base_year,
    }