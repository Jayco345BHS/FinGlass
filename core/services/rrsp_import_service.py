import csv
from datetime import date, datetime
from decimal import Decimal
from io import StringIO

from django.db import transaction

from core.models import RrspAccount, RrspContribution
from core.services.rrsp_service import create_rrsp_transfer


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
        "openingrrsproom",
        "opening_rrsp_room",
    }:
        return "OpeningBalance"
    if normalized in {
        "annuallimit",
        "annual_limit",
        "limit",
        "roomlimit",
        "room_limit",
        "deductionlimit",
        "deduction_limit",
        "contributionlimit",
        "contribution_limit",
    }:
        return "AnnualLimit"
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


def _parse_date(raw_value, *, row_index, field_name):
    text = str(raw_value or "").strip()
    if not text:
        raise ValueError(f"Row {row_index}: {field_name} is required")

    for date_format in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(text, date_format).date()
        except ValueError:
            continue

    raise ValueError(
        f"Row {row_index}: invalid {field_name} '{raw_value}'. Use YYYY-MM-DD or M/D/YYYY"
    )


def _parse_year(raw_value):
    if raw_value is None:
        return None
    if isinstance(raw_value, datetime):
        year = raw_value.year
        return year if 1957 <= year <= 2100 else None
    if isinstance(raw_value, date):
        year = raw_value.year
        return year if 1957 <= year <= 2100 else None
    text = str(raw_value).strip()
    if not text:
        return None

    candidate = text[:4]
    try:
        year = int(candidate)
    except ValueError:
        return None

    if 1957 <= year <= 2100:
        return year
    return None


def _parse_required_year(raw_value, *, row_index, field_name):
    year = _parse_year(raw_value)
    if year is None:
        raise ValueError(f"Row {row_index}: {field_name} must be a year between 1957 and 2100")
    return year


def parse_rrsp_import_csv_text(csv_text):
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
        is_unused = _parse_bool(row.get("is_unused") or row.get("unused"))
        deducted_tax_year_raw = row.get("deducted_tax_year") or row.get("deduction_tax_year") or row.get("tax_year_deducted")
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

        parsed_contribution_date = _parse_date(contribution_date, row_index=index, field_name="date")

        amount = _parse_float(amount_raw, row_index=index, field_name="amount")
        if amount <= 0:
            raise ValueError(f"Row {index}: amount must be > 0")

        if contribution_type == "Transfer" and not destination_account_name:
            raise ValueError(f"Row {index}: destination_account is required for Transfer")

        transactions.append(
            {
                "contribution_date": parsed_contribution_date,
                "account_name": account_name,
                "contribution_type": contribution_type,
                "amount": amount,
                "memo": memo,
                "is_unused": bool(is_unused),
                "deducted_tax_year": (
                    _parse_required_year(deducted_tax_year_raw, row_index=index, field_name="deducted_tax_year")
                    if str(deducted_tax_year_raw or "").strip()
                    else None
                ),
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


def parse_rrsp_transactions_csv_text(csv_text):
    parsed = parse_rrsp_import_csv_text(csv_text)
    return parsed["transactions"]


def import_rrsp_transactions_rows(user_id, parsed_rows):
    account_map = {
        row["account_name"]: int(row["id"])
        for row in RrspAccount.objects.filter(user_id=user_id).values("id", "account_name")
    }

    def get_or_create_account_id(account_name):
        normalized = str(account_name or "").strip()
        if not normalized:
            raise ValueError("account_name is required")

        if normalized in account_map:
            return account_map[normalized]

        account = RrspAccount.objects.create(user_id=user_id, account_name=normalized, opening_balance=0)
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
                if 1957 <= row_year <= 2100:
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

                source_existing = RrspContribution.objects.filter(
                    user_id=user_id,
                    rrsp_account_id=source_account_id,
                    contribution_date=row["contribution_date"],
                    contribution_type="Withdrawal",
                    amount__gte=amount_min,
                    amount__lte=amount_max,
                    memo=(source_memo or ""),
                ).exists()
                destination_existing = RrspContribution.objects.filter(
                    user_id=user_id,
                    rrsp_account_id=destination_account_id,
                    contribution_date=row["contribution_date"],
                    contribution_type="Deposit",
                    amount__gte=amount_min,
                    amount__lte=amount_max,
                    memo=(destination_memo or ""),
                ).exists()

                if source_existing and destination_existing:
                    skipped += 1
                    continue

                create_rrsp_transfer(
                    user_id=user_id,
                    from_rrsp_account_id=source_account_id,
                    to_rrsp_account_id=destination_account_id,
                    transfer_date=row["contribution_date"],
                    amount=amount_decimal,
                    memo=row["memo"],
                )
                transfers += 1
                continue

            existing = RrspContribution.objects.filter(
                user_id=user_id,
                rrsp_account_id=source_account_id,
                contribution_date=row["contribution_date"],
                contribution_type=row["contribution_type"],
                is_unused=bool(row.get("is_unused")),
                deducted_tax_year=row.get("deducted_tax_year"),
                amount__gte=amount_min,
                amount__lte=amount_max,
                memo=(row["memo"] or ""),
            ).exists()

            if existing:
                skipped += 1
                continue

            is_unused = bool(row.get("is_unused")) and row["contribution_type"] == "Deposit"
            deducted_tax_year = None if is_unused else row.get("deducted_tax_year")

            RrspContribution.objects.create(
                user_id=user_id,
                rrsp_account_id=source_account_id,
                contribution_date=row["contribution_date"],
                amount=amount_decimal,
                contribution_type=row["contribution_type"],
                is_unused=is_unused,
                deducted_tax_year=deducted_tax_year,
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