from datetime import datetime


def is_user_tfsa_opening_balance_configured(db, user_id):
    row = db.execute(
        "SELECT 1 FROM app_settings WHERE user_id = ? AND key = 'tfsa_opening_balance' LIMIT 1",
        (user_id,),
    ).fetchone()
    return row is not None


def get_user_tfsa_opening_balance(db, user_id):
    """Get user's total TFSA opening balance (room they had when tracking started)"""
    result = db.execute(
        "SELECT value FROM app_settings WHERE user_id = ? AND key = 'tfsa_opening_balance'",
        (user_id,),
    ).fetchone()

    if result:
        return float(result["value"])
    return 0


def get_user_tfsa_opening_balance_base_year(db, user_id):
    result = db.execute(
        "SELECT value FROM app_settings WHERE user_id = ? AND key = 'tfsa_opening_balance_base_year'",
        (user_id,),
    ).fetchone()

    if not result:
        return None

    try:
        return int(str(result["value"]))
    except (TypeError, ValueError):
        return None


def _set_user_tfsa_opening_balance_base_year(db, user_id, year):
    db.execute(
        """
        INSERT INTO app_settings (user_id, key, value)
        VALUES (?, 'tfsa_opening_balance_base_year', ?)
        ON CONFLICT(user_id, key) DO UPDATE SET
            value = excluded.value,
            updated_at = CURRENT_TIMESTAMP
        """,
        (user_id, str(year)),
    )


def set_user_tfsa_opening_balance_base_year(db, user_id, year):
    normalized_year = int(year)
    _set_user_tfsa_opening_balance_base_year(db, user_id, normalized_year)
    db.commit()


def set_user_tfsa_opening_balance(db, user_id, balance):
    """Set user's total TFSA opening balance"""
    db.execute(
        """
        INSERT INTO app_settings (user_id, key, value)
        VALUES (?, 'tfsa_opening_balance', ?)
        ON CONFLICT(user_id, key) DO UPDATE SET
            value = excluded.value,
            updated_at = CURRENT_TIMESTAMP
        """,
        (user_id, str(balance)),
    )

    existing_base_year = get_user_tfsa_opening_balance_base_year(db, user_id)
    if existing_base_year is None:
        _set_user_tfsa_opening_balance_base_year(db, user_id, datetime.now().year)

    db.commit()


def ensure_tfsa_setup_from_import(db, user_id, inferred_base_year):
    normalized_base_year = int(inferred_base_year)
    normalized_base_year = max(2009, min(2100, normalized_base_year))

    if not is_user_tfsa_opening_balance_configured(db, user_id):
        db.execute(
            """
            INSERT INTO app_settings (user_id, key, value)
            VALUES (?, 'tfsa_opening_balance', '0')
            ON CONFLICT(user_id, key) DO NOTHING
            """,
            (user_id,),
        )

    current_base_year = get_user_tfsa_opening_balance_base_year(db, user_id)
    if current_base_year is None or normalized_base_year < int(current_base_year):
        _set_user_tfsa_opening_balance_base_year(db, user_id, normalized_base_year)

    db.commit()


def list_user_tfsa_annual_limits(db, user_id):
    rows = db.execute(
        """
        SELECT year, annual_limit
        FROM tfsa_annual_limits
        WHERE user_id = ?
        ORDER BY year DESC
        """,
        (user_id,),
    ).fetchall()

    return [
        {
            "year": int(row["year"]),
            "annual_limit": float(row["annual_limit"]),
        }
        for row in rows
    ]


def upsert_user_tfsa_annual_limit(db, user_id, year, annual_limit):
    db.execute(
        """
        INSERT INTO tfsa_annual_limits (user_id, year, annual_limit)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, year) DO UPDATE SET
            annual_limit = excluded.annual_limit,
            updated_at = CURRENT_TIMESTAMP
        """,
        (user_id, year, annual_limit),
    )
    db.commit()


def delete_user_tfsa_annual_limit(db, user_id, year):
    cursor = db.execute(
        "DELETE FROM tfsa_annual_limits WHERE user_id = ? AND year = ?",
        (user_id, year),
    )
    db.commit()
    return cursor.rowcount > 0


def reset_user_tfsa_data(db, user_id):
    db.execute(
        "DELETE FROM tfsa_contributions WHERE user_id = ?",
        (user_id,),
    )
    db.execute(
        "DELETE FROM tfsa_accounts WHERE user_id = ?",
        (user_id,),
    )
    db.execute(
        "DELETE FROM tfsa_annual_limits WHERE user_id = ?",
        (user_id,),
    )
    db.execute(
        """
        DELETE FROM app_settings
        WHERE user_id = ?
          AND key IN ('tfsa_opening_balance', 'tfsa_opening_balance_base_year')
        """,
        (user_id,),
    )
    db.commit()


def create_tfsa_transfer(
    db,
    user_id,
    from_tfsa_account_id,
    to_tfsa_account_id,
    transfer_date,
    amount,
    memo,
):
    if from_tfsa_account_id == to_tfsa_account_id:
        raise ValueError("Source and destination accounts must be different")

    if amount <= 0:
        raise ValueError("amount must be > 0")

    if not transfer_date:
        raise ValueError("transfer_date required")

    from_account = db.execute(
        "SELECT id, account_name, user_id FROM tfsa_accounts WHERE id = ?",
        (from_tfsa_account_id,),
    ).fetchone()
    to_account = db.execute(
        "SELECT id, account_name, user_id FROM tfsa_accounts WHERE id = ?",
        (to_tfsa_account_id,),
    ).fetchone()

    if not from_account or from_account["user_id"] != user_id:
        raise ValueError("Source account not found")
    if not to_account or to_account["user_id"] != user_id:
        raise ValueError("Destination account not found")

    user_memo = str(memo or "").strip()
    from_memo = f"[Transfer to {to_account['account_name']}]"
    to_memo = f"[Transfer from {from_account['account_name']}]"
    if user_memo:
        from_memo = f"{from_memo} {user_memo}"
        to_memo = f"{to_memo} {user_memo}"

    db.execute(
        """
        INSERT INTO tfsa_contributions
        (user_id, tfsa_account_id, contribution_date, amount, contribution_type, memo)
        VALUES (?, ?, ?, ?, 'Withdrawal', ?)
        """,
        (user_id, from_tfsa_account_id, transfer_date, amount, from_memo),
    )
    db.execute(
        """
        INSERT INTO tfsa_contributions
        (user_id, tfsa_account_id, contribution_date, amount, contribution_type, memo)
        VALUES (?, ?, ?, ?, 'Deposit', ?)
        """,
        (user_id, to_tfsa_account_id, transfer_date, amount, to_memo),
    )
    db.commit()


def calculate_total_room_remaining(db, user_id):
    """
    Calculate remaining TFSA room across ALL accounts for a user:
    opening_balance - (sum of all deposits across all accounts) + (sum of all withdrawals)
    """
    opening_balance = get_user_tfsa_opening_balance(db, user_id)

    current_year = datetime.now().year

    # Sum room-impacting deposits and withdrawals (transfers excluded via memo prefix)
    # Withdrawals only restore room in years after the withdrawal year.
    contributions = db.execute(
        """
        SELECT
            contribution_date,
            contribution_type,
            SUM(amount) as total
        FROM tfsa_contributions
        WHERE user_id = ?
          AND (
            memo IS NULL
            OR (memo NOT LIKE '[Transfer %' AND memo NOT LIKE '[Transfer to %' AND memo NOT LIKE '[Transfer from %')
          )
        GROUP BY contribution_date, contribution_type
        """,
        (user_id,),
    ).fetchall()

    deposits = 0
    eligible_withdrawals = 0

    for contrib in contributions:
        try:
            contribution_year = int(str(contrib["contribution_date"])[:4])
        except (TypeError, ValueError):
            contribution_year = current_year

        if contrib["contribution_type"] == "Deposit":
            deposits += contrib["total"]
        elif contrib["contribution_type"] == "Withdrawal" and contribution_year < current_year:
            eligible_withdrawals += contrib["total"]

    remaining = opening_balance - deposits + eligible_withdrawals
    return max(0, remaining)


def get_tfsa_summary(db, user_id):
    """Get all TFSA accounts and combined room remaining across all accounts"""
    accounts = db.execute(
        """
        SELECT id, account_name
        FROM tfsa_accounts
        WHERE user_id = ?
        ORDER BY created_at DESC
        """,
        (user_id,),
    ).fetchall()

    opening_balance = get_user_tfsa_opening_balance(db, user_id)
    opening_balance_base_year = get_user_tfsa_opening_balance_base_year(db, user_id)
    opening_balance_configured = is_user_tfsa_opening_balance_configured(db, user_id)
    annual_limits = list_user_tfsa_annual_limits(db, user_id)
    current_year = datetime.now().year

    minimum_annual_year = (
        int(opening_balance_base_year) + 1
        if opening_balance_base_year is not None
        else None
    )

    candidate_annual_limits = annual_limits
    if minimum_annual_year is not None:
        candidate_annual_limits = [
            limit for limit in annual_limits if int(limit["year"]) >= minimum_annual_year
        ]

    available_annual_limits = [
        limit for limit in candidate_annual_limits if int(limit["year"]) <= current_year
    ]
    future_annual_limits = [
        limit for limit in candidate_annual_limits if int(limit["year"]) > current_year
    ]
    total_annual_room = sum(limit["annual_limit"] for limit in available_annual_limits)
    total_future_annual_room = sum(limit["annual_limit"] for limit in future_annual_limits)
    total_available_room = opening_balance + total_annual_room

    # Get contributions by account (activity view; includes transfers)
    account_contributions = db.execute(
        """
        SELECT tfsa_account_id, contribution_type, SUM(amount) as total
        FROM tfsa_contributions
        WHERE tfsa_account_id IN (SELECT id FROM tfsa_accounts WHERE user_id = ?)
        GROUP BY tfsa_account_id, contribution_type
        """,
        (user_id,),
    ).fetchall()

    # Calculate room-impact contributions with CRA timing rules:
    # - Deposits reduce room immediately.
    # - Withdrawals restore room only in later years.
    # - Internal transfers do not affect room.
    room_contributions = db.execute(
        """
        SELECT contribution_date, contribution_type, amount, memo
        FROM tfsa_contributions
        WHERE user_id = ?
        ORDER BY contribution_date, id
        """,
        (user_id,),
    ).fetchall()

    # Build map of account contributions
    contrib_map = {}
    total_deposits = 0
    total_withdrawals = 0

    for contrib in account_contributions:
        account_id = contrib["tfsa_account_id"]
        if account_id not in contrib_map:
            contrib_map[account_id] = {"deposits": 0, "withdrawals": 0}

        if contrib["contribution_type"] == "Deposit":
            contrib_map[account_id]["deposits"] += contrib["total"]
            total_deposits += contrib["total"]
        elif contrib["contribution_type"] == "Withdrawal":
            contrib_map[account_id]["withdrawals"] += contrib["total"]
            total_withdrawals += contrib["total"]

    # Build account details
    summary = []
    for acc in accounts:
        contrib = contrib_map.get(acc["id"], {"deposits": 0, "withdrawals": 0})
        account_used = contrib["deposits"] - contrib["withdrawals"]

        summary.append({
            "id": acc["id"],
            "account_name": acc["account_name"],
            "deposits": contrib["deposits"],
            "withdrawals": contrib["withdrawals"],
            "used": account_used,
        })

    room_deposits = 0
    room_withdrawals_eligible = 0
    room_withdrawals_pending = 0

    for row in room_contributions:
        memo = str(row["memo"] or "")
        if memo.startswith("[Transfer ") or memo.startswith("[Transfer to ") or memo.startswith("[Transfer from "):
            continue

        contribution_type = str(row["contribution_type"] or "")
        amount = float(row["amount"] or 0)
        try:
            contribution_year = int(str(row["contribution_date"] or "")[:4])
        except (TypeError, ValueError):
            contribution_year = current_year

        if contribution_type == "Deposit":
            room_deposits += amount
        elif contribution_type == "Withdrawal":
            if contribution_year < current_year:
                room_withdrawals_eligible += amount
            else:
                room_withdrawals_pending += amount

    # Activity net (for account flow display)
    total_used = total_deposits - total_withdrawals

    # Room-impact net (for contribution room)
    room_used = room_deposits - room_withdrawals_eligible
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
        "room_withdrawals_eligible": room_withdrawals_eligible,
        "room_withdrawals_pending": room_withdrawals_pending,
        "room_used": room_used,
        "total_remaining": max(0, total_remaining),
    }
