from datetime import datetime

from django.db import transaction

from core.models import AppSetting, RrspAccount, RrspAnnualLimit, RrspContribution


def is_user_rrsp_opening_balance_configured(user_id):
    return AppSetting.objects.filter(user_id=user_id, key="rrsp_opening_balance").exists()


def get_user_rrsp_opening_balance(user_id):
    row = AppSetting.objects.filter(user_id=user_id, key="rrsp_opening_balance").values("value").first()
    if not row:
        return 0
    try:
        return float(row["value"])
    except (TypeError, ValueError):
        return 0


def get_user_rrsp_opening_balance_base_year(user_id):
    row = AppSetting.objects.filter(user_id=user_id, key="rrsp_opening_balance_base_year").values("value").first()
    if not row:
        return None
    try:
        return int(str(row["value"]))
    except (TypeError, ValueError):
        return None


def _set_user_rrsp_opening_balance_base_year(user_id, year):
    AppSetting.objects.update_or_create(
        user_id=user_id,
        key="rrsp_opening_balance_base_year",
        defaults={"value": str(year)},
    )


def set_user_rrsp_opening_balance_base_year(user_id, year):
    _set_user_rrsp_opening_balance_base_year(user_id, int(year))


def set_user_rrsp_opening_balance(user_id, balance):
    AppSetting.objects.update_or_create(
        user_id=user_id,
        key="rrsp_opening_balance",
        defaults={"value": str(balance)},
    )

    existing_base_year = get_user_rrsp_opening_balance_base_year(user_id)
    if existing_base_year is None:
        _set_user_rrsp_opening_balance_base_year(user_id, datetime.now().year)


def ensure_rrsp_setup_from_import(user_id, inferred_base_year):
    normalized_base_year = int(inferred_base_year)
    normalized_base_year = max(1957, min(2100, normalized_base_year))

    if not is_user_rrsp_opening_balance_configured(user_id):
        AppSetting.objects.get_or_create(
            user_id=user_id,
            key="rrsp_opening_balance",
            defaults={"value": "0"},
        )

    current_base_year = get_user_rrsp_opening_balance_base_year(user_id)
    if current_base_year is None or normalized_base_year < int(current_base_year):
        _set_user_rrsp_opening_balance_base_year(user_id, normalized_base_year)


def list_user_rrsp_annual_limits(user_id):
    rows = RrspAnnualLimit.objects.filter(user_id=user_id).order_by("-year").values("year", "annual_limit")
    return [{"year": int(row["year"]), "annual_limit": float(row["annual_limit"])} for row in rows]


def upsert_user_rrsp_annual_limit(user_id, year, annual_limit):
    RrspAnnualLimit.objects.update_or_create(
        user_id=user_id,
        year=year,
        defaults={"annual_limit": annual_limit},
    )


def delete_user_rrsp_annual_limit(user_id, year):
    deleted, _ = RrspAnnualLimit.objects.filter(user_id=user_id, year=year).delete()
    return deleted > 0


def reset_user_rrsp_data(user_id):
    with transaction.atomic():
        RrspContribution.objects.filter(user_id=user_id).delete()
        RrspAccount.objects.filter(user_id=user_id).delete()
        RrspAnnualLimit.objects.filter(user_id=user_id).delete()
        AppSetting.objects.filter(
            user_id=user_id,
            key__in=["rrsp_opening_balance", "rrsp_opening_balance_base_year"],
        ).delete()


def create_rrsp_transfer(
    user_id,
    from_rrsp_account_id,
    to_rrsp_account_id,
    transfer_date,
    amount,
    memo,
):
    if from_rrsp_account_id == to_rrsp_account_id:
        raise ValueError("Source and destination accounts must be different")
    if amount <= 0:
        raise ValueError("amount must be > 0")
    if not transfer_date:
        raise ValueError("transfer_date required")

    from_account = RrspAccount.objects.filter(id=from_rrsp_account_id, user_id=user_id).first()
    to_account = RrspAccount.objects.filter(id=to_rrsp_account_id, user_id=user_id).first()
    if not from_account:
        raise ValueError("Source account not found")
    if not to_account:
        raise ValueError("Destination account not found")

    user_memo = str(memo or "").strip()
    from_memo = f"[Transfer to {to_account.account_name}]"
    to_memo = f"[Transfer from {from_account.account_name}]"
    if user_memo:
        from_memo = f"{from_memo} {user_memo}"
        to_memo = f"{to_memo} {user_memo}"

    with transaction.atomic():
        RrspContribution.objects.create(
            user_id=user_id,
            rrsp_account_id=from_rrsp_account_id,
            contribution_date=transfer_date,
            amount=amount,
            contribution_type="Withdrawal",
            is_unused=False,
            deducted_tax_year=None,
            memo=from_memo,
        )
        RrspContribution.objects.create(
            user_id=user_id,
            rrsp_account_id=to_rrsp_account_id,
            contribution_date=transfer_date,
            amount=amount,
            contribution_type="Deposit",
            is_unused=False,
            deducted_tax_year=None,
            memo=to_memo,
        )


def get_rrsp_summary(user_id):
    accounts = list(
        RrspAccount.objects.filter(user_id=user_id)
        .order_by("-created_at")
        .values("id", "account_name")
    )

    opening_balance = get_user_rrsp_opening_balance(user_id)
    opening_balance_base_year = get_user_rrsp_opening_balance_base_year(user_id)
    opening_balance_configured = is_user_rrsp_opening_balance_configured(user_id)
    annual_limits = list_user_rrsp_annual_limits(user_id)
    current_year = datetime.now().year

    minimum_annual_year = int(opening_balance_base_year) + 1 if opening_balance_base_year is not None else None

    candidate_annual_limits = annual_limits
    if minimum_annual_year is not None:
        candidate_annual_limits = [limit for limit in annual_limits if int(limit["year"]) >= minimum_annual_year]

    available_annual_limits = [limit for limit in candidate_annual_limits if int(limit["year"]) <= current_year]
    future_annual_limits = [limit for limit in candidate_annual_limits if int(limit["year"]) > current_year]
    total_annual_room = sum(limit["annual_limit"] for limit in available_annual_limits)
    total_future_annual_room = sum(limit["annual_limit"] for limit in future_annual_limits)
    total_available_room = opening_balance + total_annual_room

    account_rows = RrspContribution.objects.filter(user_id=user_id).values("rrsp_account_id", "contribution_type", "amount")
    room_rows = RrspContribution.objects.filter(user_id=user_id).order_by("contribution_date", "id").values(
        "contribution_type", "amount", "memo", "is_unused", "deducted_tax_year"
    )

    contrib_map = {}
    total_deposits = 0
    total_withdrawals = 0

    for contrib in account_rows:
        account_id = contrib["rrsp_account_id"]
        if account_id not in contrib_map:
            contrib_map[account_id] = {"deposits": 0, "withdrawals": 0}

        amount = float(contrib["amount"] or 0)
        if contrib["contribution_type"] == "Deposit":
            contrib_map[account_id]["deposits"] += amount
            total_deposits += amount
        elif contrib["contribution_type"] == "Withdrawal":
            contrib_map[account_id]["withdrawals"] += amount
            total_withdrawals += amount

    summary = []
    for acc in accounts:
        contrib = contrib_map.get(acc["id"], {"deposits": 0, "withdrawals": 0})
        summary.append(
            {
                "id": acc["id"],
                "account_name": acc["account_name"],
                "deposits": contrib["deposits"],
                "withdrawals": contrib["withdrawals"],
                "used": contrib["deposits"] - contrib["withdrawals"],
            }
        )

    room_deposits = 0
    total_unused_contributions = 0
    total_used_carry_forward_contributions = 0
    for row in room_rows:
        memo = str(row["memo"] or "")
        if memo.startswith("[Transfer ") or memo.startswith("[Transfer to ") or memo.startswith("[Transfer from "):
            continue

        if str(row["contribution_type"] or "") == "Deposit":
            amount = float(row["amount"] or 0)
            room_deposits += amount
            if bool(row["is_unused"]):
                total_unused_contributions += amount
            elif row["deducted_tax_year"] is not None:
                total_used_carry_forward_contributions += amount

    total_used = total_deposits - total_withdrawals
    room_used = room_deposits
    total_remaining = total_available_room - room_used

    return {
        "accounts": summary,
        "opening_balance": opening_balance,
        "opening_balance_base_year": opening_balance_base_year,
        "opening_balance_configured": opening_balance_configured,
        "current_year": current_year,
        "minimum_annual_year": minimum_annual_year,
        "annual_limits": annual_limits,
        "available_annual_limits": available_annual_limits,
        "future_annual_limits": future_annual_limits,
        "total_annual_room": total_annual_room,
        "total_future_annual_room": total_future_annual_room,
        "total_available_room": total_available_room,
        "total_deposits": total_deposits,
        "total_withdrawals": total_withdrawals,
        "total_used": total_used,
        "room_deposits": room_deposits,
        "room_withdrawals_eligible": 0,
        "room_withdrawals_pending": total_withdrawals,
        "room_used": room_used,
        "total_remaining": max(0, total_remaining),
        "total_unused_contributions": total_unused_contributions,
        "total_used_carry_forward_contributions": total_used_carry_forward_contributions,
    }