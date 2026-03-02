from datetime import datetime

from flask import Blueprint, jsonify, request

from ..context import require_user_id
from ..db import get_db
from ..services.fhsa_import_service import (
    import_fhsa_transactions_rows,
    parse_fhsa_import_csv_text,
    validate_fhsa_import_rows,
)
from ..services.fhsa_service import (
    FHSA_FIRST_YEAR,
    FHSA_LIFETIME_LIMIT,
    FHSA_TRACKED_OPENING_ROOM_CAP,
    can_accept_new_fhsa_contributions,
    create_fhsa_transfer,
    ensure_fhsa_setup_from_import,
    get_fhsa_summary,
    get_user_fhsa_opening_balance,
    get_user_fhsa_opening_balance_base_year,
    is_user_fhsa_opening_balance_configured,
    reset_user_fhsa_data,
    set_user_fhsa_opening_balance,
    set_user_fhsa_opening_balance_base_year,
)

bp = Blueprint("fhsa", __name__)


def _parse_bool(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _require_opening_balance_configured(db, user_id):
    if not is_user_fhsa_opening_balance_configured(db, user_id):
        return jsonify({"error": "Set FHSA available contribution room first"}), 400
    return None


@bp.get("/api/fhsa/summary")
def fhsa_summary():
    user_id = require_user_id()
    db = get_db()
    summary = get_fhsa_summary(db, user_id)
    return jsonify(summary)


@bp.post("/api/fhsa/accounts")
def create_fhsa_account():
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
            INSERT INTO fhsa_accounts (user_id, account_name, opening_balance)
            VALUES (?, ?, 0)
            """,
            (user_id, account_name),
        )
        db.commit()
        return jsonify({"id": result.lastrowid}), 201
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@bp.put("/api/fhsa/opening-balance")
def update_user_opening_balance():
    user_id = require_user_id()
    db = get_db()
    data = request.get_json() or {}

    try:
        opening_balance = float(data.get("opening_balance") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "opening_balance must be a number"}), 400

    if opening_balance < 0:
        return jsonify({"error": "opening_balance must be >= 0"}), 400

    if opening_balance > FHSA_TRACKED_OPENING_ROOM_CAP:
        return jsonify({"error": f"opening_balance must be <= {int(FHSA_TRACKED_OPENING_ROOM_CAP)}"}), 400

    set_user_fhsa_opening_balance(db, user_id, opening_balance)
    return jsonify({"success": True})


@bp.get("/api/fhsa/opening-balance")
def get_user_opening_balance():
    user_id = require_user_id()
    db = get_db()
    balance = get_user_fhsa_opening_balance(db, user_id)
    base_year = get_user_fhsa_opening_balance_base_year(db, user_id)
    configured = is_user_fhsa_opening_balance_configured(db, user_id)
    return jsonify({"opening_balance": balance, "base_year": base_year, "configured": configured})


@bp.put("/api/fhsa/opening-balance-base-year")
def update_fhsa_opening_balance_base_year():
    user_id = require_user_id()
    db = get_db()
    data = request.get_json() or {}

    raw_year = data.get("base_year")
    try:
        base_year = int(str(raw_year))
    except (TypeError, ValueError):
        return jsonify({"error": "base_year must be an integer"}), 400

    current_year = datetime.now().year
    if base_year < FHSA_FIRST_YEAR or base_year > current_year:
        return jsonify({"error": f"base_year must be between {FHSA_FIRST_YEAR} and {current_year}"}), 400

    set_user_fhsa_opening_balance_base_year(db, user_id, base_year)
    return jsonify({"success": True})


@bp.get("/api/fhsa/transactions")
def list_fhsa_transactions():
    user_id = require_user_id()
    db = get_db()

    rows = db.execute(
        """
        SELECT
            c.id,
            c.contribution_date,
            c.contribution_type,
            c.amount,
            c.is_qualifying_withdrawal,
            c.memo,
            c.created_at,
            c.fhsa_account_id,
            a.account_name
        FROM fhsa_contributions c
        JOIN fhsa_accounts a ON a.id = c.fhsa_account_id
        WHERE c.user_id = ?
        ORDER BY c.contribution_date DESC, c.id DESC
        """,
        (user_id,),
    ).fetchall()

    return jsonify([dict(row) for row in rows])


@bp.put("/api/fhsa/transactions/<int:transaction_id>")
def update_fhsa_transaction(transaction_id):
    user_id = require_user_id()
    db = get_db()
    data = request.get_json() or {}

    fhsa_account_id = data.get("fhsa_account_id")
    contribution_date = (data.get("contribution_date") or "").strip()
    contribution_type = (data.get("contribution_type") or "").strip()
    is_qualifying_withdrawal = _parse_bool(data.get("is_qualifying_withdrawal", False))
    memo = (data.get("memo") or "").strip()

    try:
        amount = float(data.get("amount") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a number"}), 400

    try:
        normalized_account_id = int(str(fhsa_account_id))
    except (TypeError, ValueError):
        return jsonify({"error": "fhsa_account_id must be an integer"}), 400

    if not contribution_date:
        return jsonify({"error": "contribution_date required"}), 400

    if contribution_type not in ("Deposit", "Withdrawal"):
        return jsonify({"error": "contribution_type must be 'Deposit' or 'Withdrawal'"}), 400

    if contribution_type != "Withdrawal" and is_qualifying_withdrawal:
        return jsonify({"error": "is_qualifying_withdrawal can only be true for Withdrawal"}), 400

    if amount <= 0:
        return jsonify({"error": "amount must be > 0"}), 400

    existing = db.execute(
        "SELECT id FROM fhsa_contributions WHERE id = ? AND user_id = ?",
        (transaction_id, user_id),
    ).fetchone()
    if not existing:
        return jsonify({"error": "Transaction not found"}), 404

    account = db.execute(
        "SELECT id FROM fhsa_accounts WHERE id = ? AND user_id = ?",
        (normalized_account_id, user_id),
    ).fetchone()
    if not account:
        return jsonify({"error": "Account not found"}), 404

    db.execute(
        """
        UPDATE fhsa_contributions
        SET fhsa_account_id = ?,
            contribution_date = ?,
            amount = ?,
            contribution_type = ?,
            is_qualifying_withdrawal = ?,
            memo = ?
        WHERE id = ?
          AND user_id = ?
        """,
        (
            normalized_account_id,
            contribution_date,
            amount,
            contribution_type,
            1 if is_qualifying_withdrawal else 0,
            memo,
            transaction_id,
            user_id,
        ),
    )
    db.commit()

    return jsonify({"updated": 1})


@bp.delete("/api/fhsa/transactions/<int:transaction_id>")
def delete_fhsa_transaction(transaction_id):
    user_id = require_user_id()
    db = get_db()

    cursor = db.execute(
        "DELETE FROM fhsa_contributions WHERE id = ? AND user_id = ?",
        (transaction_id, user_id),
    )
    db.commit()

    if cursor.rowcount == 0:
        return jsonify({"error": "Transaction not found"}), 404

    return jsonify({"deleted": 1})


@bp.post("/api/fhsa/contributions")
def add_contribution():
    user_id = require_user_id()
    db = get_db()
    setup_error = _require_opening_balance_configured(db, user_id)
    if setup_error is not None:
        return setup_error

    data = request.get_json() or {}

    fhsa_account_id = data.get("fhsa_account_id")
    contribution_type = (data.get("contribution_type") or "Deposit").strip()
    is_qualifying_withdrawal = _parse_bool(data.get("is_qualifying_withdrawal", False))
    memo = (data.get("memo") or "").strip()
    contribution_date = (data.get("contribution_date") or "").strip()

    try:
        amount = float(data.get("amount") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a number"}), 400

    if not all([fhsa_account_id, amount > 0, contribution_date]):
        return jsonify({"error": "Missing required fields"}), 400

    if contribution_type not in ("Deposit", "Withdrawal"):
        return jsonify({"error": "contribution_type must be 'Deposit' or 'Withdrawal'"}), 400

    if contribution_type != "Withdrawal" and is_qualifying_withdrawal:
        return jsonify({"error": "is_qualifying_withdrawal can only be true for Withdrawal"}), 400

    if contribution_type == "Deposit":
        can_contribute, lock_info = can_accept_new_fhsa_contributions(db, user_id)
        if not can_contribute:
            return jsonify({"error": str(lock_info.get("message") or "FHSA contributions are currently locked")}), 400

    acc = db.execute(
        "SELECT user_id FROM fhsa_accounts WHERE id = ?",
        (fhsa_account_id,),
    ).fetchone()

    if not acc or acc["user_id"] != user_id:
        return jsonify({"error": "Account not found"}), 404

    if contribution_type == "Deposit":
        summary = get_fhsa_summary(db, user_id)
        if amount > float(summary.get("total_remaining") or 0):
            return jsonify({"error": "Contribution exceeds tracked FHSA contribution room"}), 400

    try:
        db.execute(
            """
            INSERT INTO fhsa_contributions
            (user_id, fhsa_account_id, contribution_date, amount, contribution_type, is_qualifying_withdrawal, memo)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                fhsa_account_id,
                contribution_date,
                amount,
                contribution_type,
                1 if (contribution_type == "Withdrawal" and is_qualifying_withdrawal) else 0,
                memo,
            ),
        )
        db.commit()
        return jsonify({"success": True}), 201
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@bp.post("/api/fhsa/transfers")
def add_transfer():
    user_id = require_user_id()
    db = get_db()
    setup_error = _require_opening_balance_configured(db, user_id)
    if setup_error is not None:
        return setup_error

    can_contribute, lock_info = can_accept_new_fhsa_contributions(db, user_id)
    if not can_contribute:
        return jsonify({"error": str(lock_info.get("message") or "FHSA contributions are currently locked")}), 400

    data = request.get_json() or {}

    raw_from_account_id = data.get("from_fhsa_account_id")
    raw_to_account_id = data.get("to_fhsa_account_id")
    transfer_date = (data.get("transfer_date") or "").strip()
    memo = (data.get("memo") or "").strip()

    try:
        amount = float(data.get("amount") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a number"}), 400

    try:
        from_fhsa_account_id = int(str(raw_from_account_id))
        to_fhsa_account_id = int(str(raw_to_account_id))
    except (TypeError, ValueError):
        return jsonify({"error": "from_fhsa_account_id and to_fhsa_account_id must be integers"}), 400

    try:
        create_fhsa_transfer(
            db=db,
            user_id=user_id,
            from_fhsa_account_id=from_fhsa_account_id,
            to_fhsa_account_id=to_fhsa_account_id,
            transfer_date=transfer_date,
            amount=amount,
            memo=memo,
        )
        return jsonify({"success": True}), 201
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@bp.delete("/api/fhsa/accounts/<int:account_id>")
def delete_fhsa_account(account_id):
    user_id = require_user_id()
    db = get_db()

    acc = db.execute(
        "SELECT user_id FROM fhsa_accounts WHERE id = ?",
        (account_id,),
    ).fetchone()

    if not acc or acc["user_id"] != user_id:
        return jsonify({"error": "Account not found"}), 404

    db.execute("DELETE FROM fhsa_accounts WHERE id = ?", (account_id,))
    db.commit()
    return jsonify({"success": True})


@bp.post("/api/fhsa/reset")
def reset_fhsa_data():
    user_id = require_user_id()
    db = get_db()
    reset_user_fhsa_data(db, user_id)
    return jsonify({"success": True})


@bp.post("/api/fhsa/import-csv")
def import_fhsa_csv():
    user_id = require_user_id()
    db = get_db()

    overwrite_mode = str(request.form.get("overwrite_mode") or "").strip().lower()
    overwrite_confirm = str(request.form.get("overwrite_confirm") or "").strip().upper()

    if overwrite_mode != "replace_all" or overwrite_confirm != "REPLACE":
        return jsonify(
            {
                "error": (
                    "FHSA import requires explicit overwrite confirmation. "
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
        parsed_import = parse_fhsa_import_csv_text(file_text)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    parsed_rows = parsed_import.get("transactions") or []
    setup_opening_balance = parsed_import.get("opening_balance")
    setup_base_year = parsed_import.get("opening_balance_base_year")

    try:
        validate_fhsa_import_rows(parsed_rows, opening_base_year=setup_base_year)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if not parsed_rows and setup_opening_balance is None:
        return jsonify({"error": "No FHSA rows found in uploaded CSV"}), 400

    reset_user_fhsa_data(db, user_id)

    setup_opening_balance_applied = False
    setup_base_year_applied = False

    if setup_opening_balance is not None:
        set_user_fhsa_opening_balance(db, user_id, float(setup_opening_balance))
        setup_opening_balance_applied = True

    if setup_base_year is not None:
        set_user_fhsa_opening_balance_base_year(db, user_id, int(setup_base_year))
        setup_base_year_applied = True

    summary = {
        "parsed": 0,
        "inserted": 0,
        "skipped": 0,
        "transfers": 0,
        "inferred_base_year": None,
    }

    if parsed_rows:
        try:
            summary = import_fhsa_transactions_rows(db, user_id, parsed_rows)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    inferred_base_year = summary.get("inferred_base_year")
    if inferred_base_year is not None and not setup_base_year_applied:
        ensure_fhsa_setup_from_import(db, user_id, inferred_base_year)

    summary["setup_opening_balance_applied"] = setup_opening_balance_applied
    summary["setup_base_year_applied"] = setup_base_year_applied
    summary["setup_rows_parsed"] = (1 if setup_opening_balance is not None else 0)

    return jsonify(summary)
