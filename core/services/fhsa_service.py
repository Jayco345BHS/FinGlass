from datetime import datetime

from django.db import transaction

from core.models import AppSetting, FhsaAccount, FhsaContribution

FHSA_ANNUAL_LIMIT = 8000.0
FHSA_LIFETIME_LIMIT = 40000.0
FHSA_CARRY_FORWARD_CAP = 8000.0
FHSA_MAX_YEARLY_ROOM = FHSA_ANNUAL_LIMIT + FHSA_CARRY_FORWARD_CAP
FHSA_FIRST_YEAR = 2023
FHSA_TRACKED_OPENING_ROOM_CAP = 16000.0
FHSA_MAX_OPEN_YEARS = 15


def is_user_fhsa_opening_balance_configured(user_id):
    return AppSetting.objects.filter(user_id=user_id, key="fhsa_opening_balance").exists()


def get_user_fhsa_opening_balance(user_id):
    row = AppSetting.objects.filter(user_id=user_id, key="fhsa_opening_balance").values("value").first()
    if not row:
        return 0.0
    try:
        return max(0.0, min(FHSA_TRACKED_OPENING_ROOM_CAP, float(row["value"])))
    except (TypeError, ValueError):
        return 0.0


def get_user_fhsa_opening_balance_base_year(user_id):
    row = AppSetting.objects.filter(user_id=user_id, key="fhsa_opening_balance_base_year").values("value").first()
    if not row:
        return None
    try:
        return int(str(row["value"]))
    except (TypeError, ValueError):
        return None


def _set_user_fhsa_opening_balance_base_year(user_id, year):
    AppSetting.objects.update_or_create(
        user_id=user_id,
        key="fhsa_opening_balance_base_year",
        defaults={"value": str(year)},
    )


def set_user_fhsa_opening_balance_base_year(user_id, year):
    normalized_year = max(FHSA_FIRST_YEAR, min(2100, int(year)))
    _set_user_fhsa_opening_balance_base_year(user_id, normalized_year)


def set_user_fhsa_opening_balance(user_id, balance):
    normalized_balance = max(0.0, min(FHSA_TRACKED_OPENING_ROOM_CAP, float(balance)))
    AppSetting.objects.update_or_create(
        user_id=user_id,
        key="fhsa_opening_balance",
        defaults={"value": str(normalized_balance)},
    )

    existing_base_year = get_user_fhsa_opening_balance_base_year(user_id)
    if existing_base_year is None:
        _set_user_fhsa_opening_balance_base_year(user_id, datetime.now().year)


def ensure_fhsa_setup_from_import(user_id, inferred_base_year):
    normalized_base_year = max(FHSA_FIRST_YEAR, min(2100, int(inferred_base_year)))

    if not is_user_fhsa_opening_balance_configured(user_id):
        AppSetting.objects.get_or_create(
            user_id=user_id,
            key="fhsa_opening_balance",
            defaults={"value": "0"},
        )

    current_base_year = get_user_fhsa_opening_balance_base_year(user_id)
    if current_base_year is None or normalized_base_year < int(current_base_year):
        _set_user_fhsa_opening_balance_base_year(user_id, normalized_base_year)


def reset_user_fhsa_data(user_id):
    with transaction.atomic():
        FhsaContribution.objects.filter(user_id=user_id).delete()
        FhsaAccount.objects.filter(user_id=user_id).delete()
        AppSetting.objects.filter(
            user_id=user_id,
            key__in=["fhsa_opening_balance", "fhsa_opening_balance_base_year"],
        ).delete()


def create_fhsa_transfer(
    user_id,
    from_fhsa_account_id,
    to_fhsa_account_id,
    transfer_date,
    amount,
    memo,
):
    if from_fhsa_account_id == to_fhsa_account_id:
        raise ValueError("Source and destination accounts must be different")
    if amount <= 0:
        raise ValueError("amount must be > 0")
    if not transfer_date:
        raise ValueError("transfer_date required")

    from_account = FhsaAccount.objects.filter(id=from_fhsa_account_id, user_id=user_id).first()
    to_account = FhsaAccount.objects.filter(id=to_fhsa_account_id, user_id=user_id).first()

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
        FhsaContribution.objects.create(
            user_id=user_id,
            fhsa_account_id=from_fhsa_account_id,
            contribution_date=transfer_date,
            amount=amount,
            contribution_type="Withdrawal",
            is_qualifying_withdrawal=False,
            memo=from_memo,
        )
        FhsaContribution.objects.create(
            user_id=user_id,
            fhsa_account_id=to_fhsa_account_id,
            contribution_date=transfer_date,
            amount=amount,
            contribution_type="Deposit",
            is_qualifying_withdrawal=False,
            memo=to_memo,
        )


def _is_transfer_memo(memo):
    normalized = str(memo or "")
    return (
        normalized.startswith("[Transfer ")
        or normalized.startswith("[Transfer to ")
        or normalized.startswith("[Transfer from ")
    )


def _build_deposit_totals_by_year(rows):
    deposits_by_year = {}
    deposits_total = 0.0
    qualifying_withdrawals = 0.0
    non_qualifying_withdrawals = 0.0

    for row in rows:
        memo = str(row["memo"] or "")
        if _is_transfer_memo(memo):
            continue

        contribution_type = str(row["contribution_type"] or "")
        amount = float(row["amount"] or 0)
        if amount <= 0:
            continue

        try:
            contribution_year = int(str(row["contribution_date"] or "")[:4])
        except (TypeError, ValueError):
            contribution_year = datetime.now().year

        if contribution_type == "Deposit":
            deposits_by_year[contribution_year] = deposits_by_year.get(contribution_year, 0.0) + amount
            deposits_total += amount
        elif contribution_type == "Withdrawal":
            if bool(row["is_qualifying_withdrawal"]):
                qualifying_withdrawals += amount
            else:
                non_qualifying_withdrawals += amount

    return deposits_by_year, deposits_total, qualifying_withdrawals, non_qualifying_withdrawals


def _simulate_fhsa_room(opening_balance, base_year, current_year, deposits_by_year):
    room = max(0.0, min(FHSA_LIFETIME_LIMIT, float(opening_balance or 0)))
    annual_room_added = 0.0

    normalized_base_year = max(FHSA_FIRST_YEAR, min(2100, int(base_year)))
    last_active_year = normalized_base_year + FHSA_MAX_OPEN_YEARS - 1
    effective_year = min(current_year, last_active_year)

    if normalized_base_year > effective_year:
        return {
            "room_before_current_year_deposits": room,
            "room_after_current_year_deposits": room,
            "annual_room_added": 0.0,
            "open_year": normalized_base_year,
            "last_active_year": last_active_year,
            "effective_year": effective_year,
            "is_age_expired": current_year > last_active_year,
        }

    for year in range(normalized_base_year, effective_year):
        year_deposits = max(0.0, float(deposits_by_year.get(year, 0.0)))
        room = max(0.0, room - year_deposits)

        room_after_annual_addition = min(FHSA_MAX_YEARLY_ROOM, room + FHSA_ANNUAL_LIMIT)
        annual_room_added += max(0.0, room_after_annual_addition - room)
        room = room_after_annual_addition

    room_before_current_year_deposits = room
    current_year_deposits = max(0.0, float(deposits_by_year.get(effective_year, 0.0)))
    room_after_current_year_deposits = max(0.0, room_before_current_year_deposits - current_year_deposits)

    return {
        "room_before_current_year_deposits": room_before_current_year_deposits,
        "room_after_current_year_deposits": room_after_current_year_deposits,
        "annual_room_added": annual_room_added,
        "open_year": normalized_base_year,
        "last_active_year": last_active_year,
        "effective_year": effective_year,
        "is_age_expired": current_year > last_active_year,
    }


def get_first_qualifying_withdrawal_info(user_id):
    row = (
        FhsaContribution.objects.filter(
            user_id=user_id,
            contribution_type="Withdrawal",
            is_qualifying_withdrawal=True,
        )
        .exclude(memo__startswith="[Transfer ")
        .exclude(memo__startswith="[Transfer to ")
        .exclude(memo__startswith="[Transfer from ")
        .order_by("contribution_date", "id")
        .values("contribution_date")
        .first()
    )

    if not row:
        return {
            "has_qualifying_withdrawal": False,
            "first_qualifying_withdrawal_date": None,
            "first_qualifying_withdrawal_year": None,
            "closure_deadline_date": None,
            "closure_deadline_year_end": None,
            "contributions_locked": False,
        }

    qualifying_date = str(row["contribution_date"] or "").strip()
    try:
        qualifying_year = int(qualifying_date[:4])
    except (TypeError, ValueError):
        qualifying_year = datetime.now().year

    closing_year = qualifying_year + 1
    return {
        "has_qualifying_withdrawal": True,
        "first_qualifying_withdrawal_date": qualifying_date,
        "first_qualifying_withdrawal_year": qualifying_year,
        "closure_deadline_date": f"{closing_year}-10-01",
        "closure_deadline_year_end": f"{closing_year}-12-31",
        "contributions_locked": True,
    }


def can_accept_new_fhsa_contributions(user_id):
    current_year = datetime.now().year
    opening_year = get_user_fhsa_opening_balance_base_year(user_id)
    if opening_year is None:
        return False, {
            "reason": "missing_open_year",
            "message": "Set first FHSA opened year first.",
            "contributions_locked": True,
        }

    last_active_year = int(opening_year) + FHSA_MAX_OPEN_YEARS - 1
    if current_year > last_active_year:
        return False, {
            "reason": "age_limit_reached",
            "message": (
                "This FHSA has reached the 15-year maximum age window. "
                f"Opened year: {opening_year}; last contribution year: {last_active_year}."
            ),
            "contributions_locked": True,
            "open_year": int(opening_year),
            "last_active_year": int(last_active_year),
        }

    info = get_first_qualifying_withdrawal_info(user_id)
    if bool(info["contributions_locked"]):
        return False, {
            **info,
            "reason": "qualifying_withdrawal",
            "message": (
                "No new FHSA contributions are allowed after your first qualifying withdrawal. "
                f"First qualifying withdrawal date: {info['first_qualifying_withdrawal_date']}."
            ),
            "open_year": int(opening_year),
            "last_active_year": int(last_active_year),
        }

    return True, {
        **info,
        "reason": None,
        "message": "Contributions allowed.",
        "contributions_locked": False,
        "open_year": int(opening_year),
        "last_active_year": int(last_active_year),
    }


def get_fhsa_summary(user_id):
    accounts = list(
        FhsaAccount.objects.filter(user_id=user_id)
        .order_by("-created_at")
        .values("id", "account_name")
    )

    opening_balance = get_user_fhsa_opening_balance(user_id)
    opening_balance_base_year = get_user_fhsa_opening_balance_base_year(user_id)
    opening_balance_configured = is_user_fhsa_opening_balance_configured(user_id)
    current_year = datetime.now().year

    account_contributions = FhsaContribution.objects.filter(user_id=user_id).values(
        "fhsa_account_id", "contribution_type", "amount"
    )

    room_contributions = FhsaContribution.objects.filter(user_id=user_id).order_by("contribution_date", "id").values(
        "contribution_date", "contribution_type", "amount", "is_qualifying_withdrawal", "memo"
    )

    deposits_by_year, room_deposits, qualifying_withdrawals, non_qualifying_withdrawals = _build_deposit_totals_by_year(room_contributions)

    contrib_map = {}
    total_deposits = 0.0
    total_withdrawals = 0.0
    for contrib in account_contributions:
        account_id = contrib["fhsa_account_id"]
        if account_id not in contrib_map:
            contrib_map[account_id] = {"deposits": 0.0, "withdrawals": 0.0}

        amount = float(contrib["amount"] or 0)
        if contrib["contribution_type"] == "Deposit":
            contrib_map[account_id]["deposits"] += amount
            total_deposits += amount
        elif contrib["contribution_type"] == "Withdrawal":
            contrib_map[account_id]["withdrawals"] += amount
            total_withdrawals += amount

    summary = []
    for acc in accounts:
        contrib = contrib_map.get(acc["id"], {"deposits": 0.0, "withdrawals": 0.0})
        summary.append(
            {
                "id": acc["id"],
                "account_name": acc["account_name"],
                "deposits": contrib["deposits"],
                "withdrawals": contrib["withdrawals"],
                "used": contrib["deposits"] - contrib["withdrawals"],
            }
        )

    base_year = opening_balance_base_year if opening_balance_base_year is not None else current_year
    simulation = _simulate_fhsa_room(opening_balance, base_year, current_year, deposits_by_year)

    total_remaining = simulation["room_after_current_year_deposits"]
    total_available_room = simulation["room_before_current_year_deposits"]
    lifetime_contribution_remaining = max(0.0, FHSA_LIFETIME_LIMIT - room_deposits)
    qualifying_info = get_first_qualifying_withdrawal_info(user_id)
    age_expired = bool(simulation["is_age_expired"])
    contributions_locked = bool(qualifying_info["contributions_locked"]) or age_expired
    if bool(qualifying_info["contributions_locked"]):
        lock_reason = "qualifying_withdrawal"
    elif age_expired:
        lock_reason = "age_limit_reached"
    else:
        lock_reason = None

    age_years = max(0, int(current_year) - int(simulation["open_year"]) + 1)
    years_remaining = max(0, int(simulation["last_active_year"]) - int(current_year) + 1)

    fifteen_year_end_year = int(simulation["last_active_year"])
    qualifying_withdrawal_end_year = None
    if qualifying_info["first_qualifying_withdrawal_year"] is not None:
        qualifying_withdrawal_end_year = int(qualifying_info["first_qualifying_withdrawal_year"]) + 1

    participation_end_year = fifteen_year_end_year
    if qualifying_withdrawal_end_year is not None:
        participation_end_year = min(participation_end_year, qualifying_withdrawal_end_year)

    should_close_account = int(current_year) >= int(participation_end_year)

    return {
        "accounts": summary,
        "opening_balance": opening_balance,
        "opening_balance_base_year": opening_balance_base_year,
        "opening_balance_configured": opening_balance_configured,
        "current_year": current_year,
        "minimum_base_year": FHSA_FIRST_YEAR,
        "max_open_years": FHSA_MAX_OPEN_YEARS,
        "annual_limit": FHSA_ANNUAL_LIMIT,
        "lifetime_limit": FHSA_LIFETIME_LIMIT,
        "carry_forward_cap": FHSA_CARRY_FORWARD_CAP,
        "max_yearly_room": FHSA_MAX_YEARLY_ROOM,
        "open_year": simulation["open_year"],
        "last_active_year": simulation["last_active_year"],
        "effective_tracking_year": simulation["effective_year"],
        "account_age_years": age_years,
        "account_years_remaining": years_remaining,
        "is_age_expired": age_expired,
        "fifteen_year_end_year": fifteen_year_end_year,
        "qualifying_withdrawal_end_year": qualifying_withdrawal_end_year,
        "participation_end_year": participation_end_year,
        "should_close_account": should_close_account,
        "annual_room_added_since_base": simulation["annual_room_added"],
        "total_available_room": total_available_room,
        "total_deposits": total_deposits,
        "total_withdrawals": total_withdrawals,
        "total_used": total_deposits - total_withdrawals,
        "room_deposits": room_deposits,
        "qualifying_withdrawals": qualifying_withdrawals,
        "non_qualifying_withdrawals": non_qualifying_withdrawals,
        "lifetime_contribution_remaining": lifetime_contribution_remaining,
        "room_used": room_deposits,
        "total_remaining": total_remaining,
        "has_qualifying_withdrawal": qualifying_info["has_qualifying_withdrawal"],
        "first_qualifying_withdrawal_date": qualifying_info["first_qualifying_withdrawal_date"],
        "first_qualifying_withdrawal_year": qualifying_info["first_qualifying_withdrawal_year"],
        "closure_deadline_date": qualifying_info["closure_deadline_date"],
        "closure_deadline_year_end": qualifying_info["closure_deadline_year_end"],
        "contributions_locked": contributions_locked,
        "contributions_locked_reason": lock_reason,
    }