from datetime import datetime


def is_user_rrsp_opening_balance_configured(db, user_id):
    row = db.execute(
        "SELECT 1 FROM app_settings WHERE user_id = ? AND key = 'rrsp_opening_balance' LIMIT 1",
        (user_id,),
    ).fetchone()
    return row is not None


def get_user_rrsp_opening_balance(db, user_id):
    result = db.execute(
        "SELECT value FROM app_settings WHERE user_id = ? AND key = 'rrsp_opening_balance'",
        (user_id,),
    ).fetchone()
    if result:
        return float(result["value"])
    return 0


def get_user_rrsp_opening_balance_base_year(db, user_id):
    result = db.execute(
        "SELECT value FROM app_settings WHERE user_id = ? AND key = 'rrsp_opening_balance_base_year'",
        (user_id,),
    ).fetchone()

    if not result:
        return None

    try:
        return int(str(result["value"]))
    except (TypeError, ValueError):
        return None


def _set_user_rrsp_opening_balance_base_year(db, user_id, year):
    db.execute(
        """
            INSERT INTO app_settings (user_id, key, value, updated_at)
            VALUES (?, 'rrsp_opening_balance_base_year', ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id, key) DO UPDATE SET
            value = excluded.value,
            updated_at = CURRENT_TIMESTAMP
        """,
        (user_id, str(year)),
    )


def set_user_rrsp_opening_balance_base_year(db, user_id, year):
    normalized_year = int(year)
    _set_user_rrsp_opening_balance_base_year(db, user_id, normalized_year)
    db.commit()


def set_user_rrsp_opening_balance(db, user_id, balance):
    db.execute(
        """
            INSERT INTO app_settings (user_id, key, value, updated_at)
            VALUES (?, 'rrsp_opening_balance', ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id, key) DO UPDATE SET
            value = excluded.value,
            updated_at = CURRENT_TIMESTAMP
        """,
        (user_id, str(balance)),
    )

    existing_base_year = get_user_rrsp_opening_balance_base_year(db, user_id)
    if existing_base_year is None:
        _set_user_rrsp_opening_balance_base_year(db, user_id, datetime.now().year)

    db.commit()


def ensure_rrsp_setup_from_import(db, user_id, inferred_base_year):
    normalized_base_year = int(inferred_base_year)
    normalized_base_year = max(1957, min(2100, normalized_base_year))

    if not is_user_rrsp_opening_balance_configured(db, user_id):
        db.execute(
            """
                INSERT INTO app_settings (user_id, key, value, updated_at)
                VALUES (?, 'rrsp_opening_balance', '0', CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, key) DO NOTHING
            """,
            (user_id,),
        )

    current_base_year = get_user_rrsp_opening_balance_base_year(db, user_id)
    if current_base_year is None or normalized_base_year < int(current_base_year):
        _set_user_rrsp_opening_balance_base_year(db, user_id, normalized_base_year)

    db.commit()


def list_user_rrsp_annual_limits(db, user_id):
    rows = db.execute(
        """
        SELECT year, annual_limit
        FROM rrsp_annual_limits
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


def upsert_user_rrsp_annual_limit(db, user_id, year, annual_limit):
    db.execute(
        """
            INSERT INTO rrsp_annual_limits (user_id, year, annual_limit, created_at, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id, year) DO UPDATE SET
            annual_limit = excluded.annual_limit,
            updated_at = CURRENT_TIMESTAMP
        """,
        (user_id, year, annual_limit),
    )
    db.commit()


def delete_user_rrsp_annual_limit(db, user_id, year):
    cursor = db.execute(
        "DELETE FROM rrsp_annual_limits WHERE user_id = ? AND year = ?",
        (user_id, year),
    )
    db.commit()
    return cursor.rowcount > 0


def reset_user_rrsp_data(db, user_id):
    db.execute(
        "DELETE FROM rrsp_contributions WHERE user_id = ?",
        (user_id,),
    )
    db.execute(
        "DELETE FROM rrsp_accounts WHERE user_id = ?",
        (user_id,),
    )
    db.execute(
        "DELETE FROM rrsp_annual_limits WHERE user_id = ?",
        (user_id,),
    )
    db.execute(
        """
        DELETE FROM app_settings
        WHERE user_id = ?
          AND key IN ('rrsp_opening_balance', 'rrsp_opening_balance_base_year')
        """,
        (user_id,),
    )
    db.commit()


def create_rrsp_transfer(
    db,
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

    from_account = db.execute(
        "SELECT id, account_name, user_id FROM rrsp_accounts WHERE id = ?",
        (from_rrsp_account_id,),
    ).fetchone()
    to_account = db.execute(
        "SELECT id, account_name, user_id FROM rrsp_accounts WHERE id = ?",
        (to_rrsp_account_id,),
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
        INSERT INTO rrsp_contributions
        (user_id, rrsp_account_id, contribution_date, amount, contribution_type, is_unused, deducted_tax_year, memo, created_at)
        VALUES (?, ?, ?, ?, 'Withdrawal', 0, NULL, ?, CURRENT_TIMESTAMP)
        """,
        (user_id, from_rrsp_account_id, transfer_date, amount, from_memo),
    )
    db.execute(
        """
        INSERT INTO rrsp_contributions
        (user_id, rrsp_account_id, contribution_date, amount, contribution_type, is_unused, deducted_tax_year, memo, created_at)
        VALUES (?, ?, ?, ?, 'Deposit', 0, NULL, ?, CURRENT_TIMESTAMP)
        """,
        (user_id, to_rrsp_account_id, transfer_date, amount, to_memo),
    )
    db.commit()


def get_rrsp_summary(db, user_id):
    accounts = db.execute(
        """
        SELECT id, account_name
        FROM rrsp_accounts
        WHERE user_id = ?
        ORDER BY created_at DESC
        """,
        (user_id,),
    ).fetchall()

    opening_balance = get_user_rrsp_opening_balance(db, user_id)
    opening_balance_base_year = get_user_rrsp_opening_balance_base_year(db, user_id)
    opening_balance_configured = is_user_rrsp_opening_balance_configured(db, user_id)
    annual_limits = list_user_rrsp_annual_limits(db, user_id)
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

    account_contributions = db.execute(
        """
        SELECT rrsp_account_id, contribution_type, SUM(amount) as total
        FROM rrsp_contributions
        WHERE rrsp_account_id IN (SELECT id FROM rrsp_accounts WHERE user_id = ?)
        GROUP BY rrsp_account_id, contribution_type
        """,
        (user_id,),
    ).fetchall()

    room_contributions = db.execute(
        """
        SELECT contribution_type, amount, memo, is_unused, deducted_tax_year
        FROM rrsp_contributions
        WHERE user_id = ?
        ORDER BY contribution_date, id
        """,
        (user_id,),
    ).fetchall()

    contrib_map = {}
    total_deposits = 0
    total_withdrawals = 0

    for contrib in account_contributions:
        account_id = contrib["rrsp_account_id"]
        if account_id not in contrib_map:
            contrib_map[account_id] = {"deposits": 0, "withdrawals": 0}

        if contrib["contribution_type"] == "Deposit":
            contrib_map[account_id]["deposits"] += contrib["total"]
            total_deposits += contrib["total"]
        elif contrib["contribution_type"] == "Withdrawal":
            contrib_map[account_id]["withdrawals"] += contrib["total"]
            total_withdrawals += contrib["total"]

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
    total_unused_contributions = 0
    total_used_carry_forward_contributions = 0
    for row in room_contributions:
        memo = str(row["memo"] or "")
        if memo.startswith("[Transfer ") or memo.startswith("[Transfer to ") or memo.startswith("[Transfer from "):
            continue
        if str(row["contribution_type"] or "") == "Deposit":
            amount = float(row["amount"] or 0)
            room_deposits += amount
            if int(row["is_unused"] or 0) == 1:
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
