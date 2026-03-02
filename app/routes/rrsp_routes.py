from flask import Blueprint, jsonify, request

from ..context import require_user_id
from ..db import get_db
from ..services.rrsp_import_service import import_rrsp_transactions_rows, parse_rrsp_import_csv_text
from ..services.rrsp_service import (
    create_rrsp_transfer,
    delete_user_rrsp_annual_limit,
    ensure_rrsp_setup_from_import,
    get_rrsp_summary,
    get_user_rrsp_opening_balance,
    get_user_rrsp_opening_balance_base_year,
    is_user_rrsp_opening_balance_configured,
    list_user_rrsp_annual_limits,
    reset_user_rrsp_data,
    set_user_rrsp_opening_balance,
    set_user_rrsp_opening_balance_base_year,
    upsert_user_rrsp_annual_limit,
)

bp = Blueprint("rrsp", __name__)


def _parse_bool(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_optional_year(value, *, field_name):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        year = int(text)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be an integer year")
    if year < 1957 or year > 2100:
        raise ValueError(f"{field_name} must be between 1957 and 2100")
    return year


def _require_opening_balance_configured(db, user_id):
    if not is_user_rrsp_opening_balance_configured(db, user_id):
        return jsonify({"error": "Set RRSP available contribution room first"}), 400
    return None


@bp.get("/api/rrsp/summary")
def rrsp_summary():
    user_id = require_user_id()
    db = get_db()
    summary = get_rrsp_summary(db, user_id)
    return jsonify(summary)


@bp.post("/api/rrsp/accounts")
def create_rrsp_account():
    user_id = require_user_id()
    db = get_db()
    setup_error = _require_opening_balance_configured(db, user_id)
    if setup_error is not None:
        return setup_error

    data = request.get_json() or {}
    account_name = (data.get("account_name") or "").strip()

    if not account_name:
        return jsonify({"error": "account_name required"}), 400

    try:
        result = db.execute(
            """
            INSERT INTO rrsp_accounts (user_id, account_name, opening_balance)
            VALUES (?, ?, 0)
            """,
            (user_id, account_name),
        )
        db.commit()
        return jsonify({"id": result.lastrowid}), 201
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@bp.put("/api/rrsp/opening-balance")
def update_user_opening_balance():
    user_id = require_user_id()
    db = get_db()
    data = request.get_json() or {}

    opening_balance = float(data.get("opening_balance") or 0)
    if opening_balance < 0:
        return jsonify({"error": "opening_balance must be >= 0"}), 400

    set_user_rrsp_opening_balance(db, user_id, opening_balance)
    return jsonify({"success": True})


@bp.get("/api/rrsp/opening-balance")
def get_user_opening_balance():
    user_id = require_user_id()
    db = get_db()
    balance = get_user_rrsp_opening_balance(db, user_id)
    base_year = get_user_rrsp_opening_balance_base_year(db, user_id)
    configured = is_user_rrsp_opening_balance_configured(db, user_id)
    return jsonify({"opening_balance": balance, "base_year": base_year, "configured": configured})


@bp.get("/api/rrsp/annual-limits")
def get_rrsp_annual_limits():
    user_id = require_user_id()
    db = get_db()
    return jsonify({"annual_limits": list_user_rrsp_annual_limits(db, user_id)})


@bp.post("/api/rrsp/annual-limits")
def upsert_rrsp_annual_limit():
    user_id = require_user_id()
    db = get_db()
    data = request.get_json() or {}

    setup_error = _require_opening_balance_configured(db, user_id)
    if setup_error is not None:
        return setup_error

    raw_year = data.get("year")
    raw_annual_limit = data.get("annual_limit")

    try:
        year = int(str(raw_year))
    except (TypeError, ValueError):
        return jsonify({"error": "year must be an integer"}), 400

    try:
        annual_limit = float(str(raw_annual_limit))
    except (TypeError, ValueError):
        return jsonify({"error": "annual_limit must be a number"}), 400

    if year < 1957 or year > 2100:
        return jsonify({"error": "year must be between 1957 and 2100"}), 400

    if annual_limit < 0:
        return jsonify({"error": "annual_limit must be >= 0"}), 400

    base_year = get_user_rrsp_opening_balance_base_year(db, user_id)
    if base_year is not None and year <= int(base_year):
        return jsonify(
            {"error": f"year must be greater than opening balance base year ({base_year})"}
        ), 400

    upsert_user_rrsp_annual_limit(db, user_id, year, annual_limit)
    return jsonify({"success": True}), 201


@bp.delete("/api/rrsp/annual-limits/<int:year>")
def delete_rrsp_annual_limit(year):
    user_id = require_user_id()
    db = get_db()

    deleted = delete_user_rrsp_annual_limit(db, user_id, year)
    if not deleted:
        return jsonify({"error": "Annual limit not found"}), 404

    return jsonify({"success": True})


@bp.get("/api/rrsp/transactions")
def list_rrsp_transactions():
    user_id = require_user_id()
    db = get_db()

    rows = db.execute(
        """
        SELECT
            c.id,
            c.contribution_date,
            c.contribution_type,
            c.amount,
            c.is_unused,
            c.deducted_tax_year,
            c.memo,
            c.created_at,
            c.rrsp_account_id,
            a.account_name
        FROM rrsp_contributions c
        JOIN rrsp_accounts a ON a.id = c.rrsp_account_id
        WHERE c.user_id = ?
        ORDER BY c.contribution_date DESC, c.id DESC
        """,
        (user_id,),
    ).fetchall()

    return jsonify([dict(row) for row in rows])


@bp.put("/api/rrsp/transactions/<int:transaction_id>")
def update_rrsp_transaction(transaction_id):
    user_id = require_user_id()
    db = get_db()
    data = request.get_json() or {}

    rrsp_account_id = data.get("rrsp_account_id")
    contribution_date = (data.get("contribution_date") or "").strip()
    contribution_type = (data.get("contribution_type") or "").strip()
    is_unused = _parse_bool(data.get("is_unused", False))
    raw_deducted_tax_year = data.get("deducted_tax_year")
    memo = (data.get("memo") or "").strip()

    try:
        deducted_tax_year = _parse_optional_year(raw_deducted_tax_year, field_name="deducted_tax_year")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        amount = float(data.get("amount") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a number"}), 400

    try:
        normalized_account_id = int(str(rrsp_account_id))
    except (TypeError, ValueError):
        return jsonify({"error": "rrsp_account_id must be an integer"}), 400

    if not contribution_date:
        return jsonify({"error": "contribution_date required"}), 400

    if contribution_type not in ("Deposit", "Withdrawal"):
        return jsonify({"error": "contribution_type must be 'Deposit' or 'Withdrawal'"}), 400

    if contribution_type != "Deposit" and is_unused:
        return jsonify({"error": "is_unused can only be true for Deposit transactions"}), 400

    if contribution_type != "Deposit" and deducted_tax_year is not None:
        return jsonify({"error": "deducted_tax_year can only be set for Deposit transactions"}), 400

    if is_unused and deducted_tax_year is not None:
        return jsonify({"error": "deducted_tax_year cannot be set while contribution is marked unused"}), 400

    if amount <= 0:
        return jsonify({"error": "amount must be > 0"}), 400

    existing = db.execute(
        "SELECT id FROM rrsp_contributions WHERE id = ? AND user_id = ?",
        (transaction_id, user_id),
    ).fetchone()
    if not existing:
        return jsonify({"error": "Transaction not found"}), 404

    account = db.execute(
        "SELECT id FROM rrsp_accounts WHERE id = ? AND user_id = ?",
        (normalized_account_id, user_id),
    ).fetchone()
    if not account:
        return jsonify({"error": "Account not found"}), 404

    db.execute(
        """
        UPDATE rrsp_contributions
        SET rrsp_account_id = ?,
            contribution_date = ?,
            amount = ?,
            contribution_type = ?,
                        is_unused = ?,
                        deducted_tax_year = ?,
            memo = ?
        WHERE id = ?
          AND user_id = ?
        """,
        (
            normalized_account_id,
            contribution_date,
            amount,
            contribution_type,
                        1 if is_unused else 0,
            deducted_tax_year,
            memo,
            transaction_id,
            user_id,
        ),
    )
    db.commit()

    return jsonify({"updated": 1})


@bp.delete("/api/rrsp/transactions/<int:transaction_id>")
def delete_rrsp_transaction(transaction_id):
    user_id = require_user_id()
    db = get_db()

    cursor = db.execute(
        "DELETE FROM rrsp_contributions WHERE id = ? AND user_id = ?",
        (transaction_id, user_id),
    )
    db.commit()

    if cursor.rowcount == 0:
        return jsonify({"error": "Transaction not found"}), 404

    return jsonify({"deleted": 1})


@bp.post("/api/rrsp/contributions")
def add_contribution():
    user_id = require_user_id()
    db = get_db()
    setup_error = _require_opening_balance_configured(db, user_id)
    if setup_error is not None:
        return setup_error

    data = request.get_json() or {}

    rrsp_account_id = data.get("rrsp_account_id")
    amount = float(data.get("amount") or 0)
    contribution_date = (data.get("contribution_date") or "").strip()
    contribution_type = (data.get("contribution_type") or "Deposit").strip()
    is_unused = _parse_bool(data.get("is_unused", False))
    raw_deducted_tax_year = data.get("deducted_tax_year")
    memo = (data.get("memo") or "").strip()

    try:
        deducted_tax_year = _parse_optional_year(raw_deducted_tax_year, field_name="deducted_tax_year")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if not all([rrsp_account_id, amount > 0, contribution_date]):
        return jsonify({"error": "Missing required fields"}), 400

    if contribution_type not in ("Deposit", "Withdrawal"):
        return jsonify({"error": "contribution_type must be 'Deposit' or 'Withdrawal'"}), 400

    if contribution_type != "Deposit" and is_unused:
        return jsonify({"error": "is_unused can only be true for Deposit transactions"}), 400

    if contribution_type != "Deposit" and deducted_tax_year is not None:
        return jsonify({"error": "deducted_tax_year can only be set for Deposit transactions"}), 400

    if is_unused and deducted_tax_year is not None:
        return jsonify({"error": "deducted_tax_year cannot be set while contribution is marked unused"}), 400

    acc = db.execute(
        "SELECT user_id FROM rrsp_accounts WHERE id = ?",
        (rrsp_account_id,),
    ).fetchone()

    if not acc or acc["user_id"] != user_id:
        return jsonify({"error": "Account not found"}), 404

    try:
        db.execute(
            """
            INSERT INTO rrsp_contributions
            (user_id, rrsp_account_id, contribution_date, amount, contribution_type, is_unused, deducted_tax_year, memo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                rrsp_account_id,
                contribution_date,
                amount,
                contribution_type,
                1 if is_unused else 0,
                deducted_tax_year,
                memo,
            ),
        )
        db.commit()
        return jsonify({"success": True}), 201
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@bp.post("/api/rrsp/transfers")
def add_transfer():
    user_id = require_user_id()
    db = get_db()
    setup_error = _require_opening_balance_configured(db, user_id)
    if setup_error is not None:
        return setup_error

    data = request.get_json() or {}

    raw_from_account_id = data.get("from_rrsp_account_id")
    raw_to_account_id = data.get("to_rrsp_account_id")
    transfer_date = (data.get("transfer_date") or "").strip()
    memo = (data.get("memo") or "").strip()

    try:
        amount = float(data.get("amount") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a number"}), 400

    try:
        from_rrsp_account_id = int(str(raw_from_account_id))
        to_rrsp_account_id = int(str(raw_to_account_id))
    except (TypeError, ValueError):
        return jsonify({"error": "from_rrsp_account_id and to_rrsp_account_id must be integers"}), 400

    try:
        create_rrsp_transfer(
            db=db,
            user_id=user_id,
            from_rrsp_account_id=from_rrsp_account_id,
            to_rrsp_account_id=to_rrsp_account_id,
            transfer_date=transfer_date,
            amount=amount,
            memo=memo,
        )
        return jsonify({"success": True}), 201
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@bp.delete("/api/rrsp/accounts/<int:account_id>")
def delete_rrsp_account(account_id):
    user_id = require_user_id()
    db = get_db()

    acc = db.execute(
        "SELECT user_id FROM rrsp_accounts WHERE id = ?",
        (account_id,),
    ).fetchone()

    if not acc or acc["user_id"] != user_id:
        return jsonify({"error": "Account not found"}), 404

    db.execute("DELETE FROM rrsp_accounts WHERE id = ?", (account_id,))
    db.commit()
    return jsonify({"success": True})


@bp.post("/api/rrsp/reset")
def reset_rrsp_data():
    user_id = require_user_id()
    db = get_db()
    reset_user_rrsp_data(db, user_id)
    return jsonify({"success": True})


@bp.post("/api/rrsp/import-csv")
def import_rrsp_csv():
    user_id = require_user_id()
    db = get_db()

    overwrite_mode = str(request.form.get("overwrite_mode") or "").strip().lower()
    overwrite_confirm = str(request.form.get("overwrite_confirm") or "").strip().upper()

    if overwrite_mode != "replace_all" or overwrite_confirm != "REPLACE":
        return jsonify(
            {
                "error": (
                    "RRSP import requires explicit overwrite confirmation. "
                    "Set overwrite_mode=replace_all and overwrite_confirm=REPLACE."
                )
            }
        ), 400

    if "file" not in request.files:
        return jsonify({"error": "Missing file upload field: file"}), 400

    uploaded_file = request.files["file"]
    if uploaded_file.filename == "":
        return jsonify({"error": "No selected file"}), 400

    try:
        file_text = uploaded_file.read().decode("utf-8-sig")
    except Exception:
        return jsonify({"error": "Failed to read uploaded CSV file"}), 400

    try:
        parsed_import = parse_rrsp_import_csv_text(file_text)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    parsed_rows = parsed_import.get("transactions") or []
    setup_opening_balance = parsed_import.get("opening_balance")
    setup_base_year = parsed_import.get("opening_balance_base_year")
    setup_annual_limits = parsed_import.get("annual_limits") or []

    if not parsed_rows and setup_opening_balance is None and not setup_annual_limits:
        return jsonify({"error": "No RRSP rows found in uploaded CSV"}), 400

    reset_user_rrsp_data(db, user_id)

    setup_opening_balance_applied = False
    setup_base_year_applied = False
    setup_annual_limits_applied = 0

    if setup_opening_balance is not None:
        set_user_rrsp_opening_balance(db, user_id, float(setup_opening_balance))
        setup_opening_balance_applied = True

    if setup_base_year is not None:
        set_user_rrsp_opening_balance_base_year(db, user_id, int(setup_base_year))
        setup_base_year_applied = True

    for annual_limit in setup_annual_limits:
        upsert_user_rrsp_annual_limit(
            db,
            user_id,
            int(annual_limit["year"]),
            float(annual_limit["annual_limit"]),
        )
        setup_annual_limits_applied += 1

    summary = {
        "parsed": 0,
        "inserted": 0,
        "skipped": 0,
        "transfers": 0,
        "inferred_base_year": None,
    }

    if parsed_rows:
        try:
            summary = import_rrsp_transactions_rows(db, user_id, parsed_rows)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    inferred_base_year = summary.get("inferred_base_year")
    if inferred_base_year is not None and not setup_base_year_applied:
        ensure_rrsp_setup_from_import(db, user_id, inferred_base_year)

    summary["setup_opening_balance_applied"] = setup_opening_balance_applied
    summary["setup_base_year_applied"] = setup_base_year_applied
    summary["setup_annual_limits_applied"] = setup_annual_limits_applied
    summary["setup_rows_parsed"] = (
        (1 if setup_opening_balance is not None else 0) + len(setup_annual_limits)
    )

    return jsonify(summary)
