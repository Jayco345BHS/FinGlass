from flask import Blueprint, jsonify, request

from ..context import require_user_id
from ..db import get_db
from ..services.tfsa_import_service import import_tfsa_transactions_rows, parse_tfsa_import_csv_text
from ..services.tfsa_service import (
    create_tfsa_transfer,
    delete_user_tfsa_annual_limit,
    ensure_tfsa_setup_from_import,
    get_tfsa_summary,
    get_user_tfsa_opening_balance,
    get_user_tfsa_opening_balance_base_year,
    is_user_tfsa_opening_balance_configured,
    list_user_tfsa_annual_limits,
    reset_user_tfsa_data,
    set_user_tfsa_opening_balance,
    set_user_tfsa_opening_balance_base_year,
    upsert_user_tfsa_annual_limit,
)

bp = Blueprint("tfsa", __name__)


def _require_opening_balance_configured(db, user_id):
    if not is_user_tfsa_opening_balance_configured(db, user_id):
        return jsonify({"error": "Set lifetime TFSA room first"}), 400
    return None


@bp.get("/api/tfsa/summary")
def tfsa_summary():
    """Get all TFSA accounts and user-level room remaining across all accounts"""
    user_id = require_user_id()
    db = get_db()
    summary = get_tfsa_summary(db, user_id)
    return jsonify(summary)


@bp.post("/api/tfsa/accounts")
def create_tfsa_account():
    """Create a new TFSA account (account name only; opening balance is user-level)"""
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
            INSERT INTO tfsa_accounts (user_id, account_name, opening_balance)
            VALUES (?, ?, 0)
            """,
            (user_id, account_name),
        )
        db.commit()
        return jsonify({"id": result.lastrowid}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@bp.put("/api/tfsa/opening-balance")
def update_user_opening_balance():
    """Set the total lifetime TFSA opening balance for this user"""
    user_id = require_user_id()
    db = get_db()
    data = request.get_json() or {}

    opening_balance = float(data.get("opening_balance") or 0)

    if opening_balance < 0:
        return jsonify({"error": "opening_balance must be >= 0"}), 400

    set_user_tfsa_opening_balance(db, user_id, opening_balance)
    return jsonify({"success": True})


@bp.get("/api/tfsa/opening-balance")
def get_user_opening_balance():
    """Get the total lifetime TFSA opening balance for this user"""
    user_id = require_user_id()
    db = get_db()
    balance = get_user_tfsa_opening_balance(db, user_id)
    base_year = get_user_tfsa_opening_balance_base_year(db, user_id)
    configured = is_user_tfsa_opening_balance_configured(db, user_id)
    return jsonify({"opening_balance": balance, "base_year": base_year, "configured": configured})


@bp.get("/api/tfsa/annual-limits")
def get_tfsa_annual_limits():
    user_id = require_user_id()
    db = get_db()
    return jsonify({"annual_limits": list_user_tfsa_annual_limits(db, user_id)})


@bp.post("/api/tfsa/annual-limits")
def upsert_tfsa_annual_limit():
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

    if year < 2009 or year > 2100:
        return jsonify({"error": "year must be between 2009 and 2100"}), 400

    if annual_limit < 0:
        return jsonify({"error": "annual_limit must be >= 0"}), 400

    base_year = get_user_tfsa_opening_balance_base_year(db, user_id)
    if base_year is not None and year <= int(base_year):
        return jsonify({
            "error": f"year must be greater than opening balance base year ({base_year})"
        }), 400

    upsert_user_tfsa_annual_limit(db, user_id, year, annual_limit)
    return jsonify({"success": True}), 201


@bp.delete("/api/tfsa/annual-limits/<int:year>")
def delete_tfsa_annual_limit(year):
    user_id = require_user_id()
    db = get_db()

    deleted = delete_user_tfsa_annual_limit(db, user_id, year)
    if not deleted:
        return jsonify({"error": "Annual limit not found"}), 404

    return jsonify({"success": True})


@bp.get("/api/tfsa/transactions")
def list_tfsa_transactions():
    """List all TFSA contribution transactions for the current user."""
    user_id = require_user_id()
    db = get_db()

    rows = db.execute(
        """
        SELECT
            c.id,
            c.contribution_date,
            c.contribution_type,
            c.amount,
            c.memo,
            c.created_at,
            c.tfsa_account_id,
            a.account_name
        FROM tfsa_contributions c
        JOIN tfsa_accounts a ON a.id = c.tfsa_account_id
        WHERE c.user_id = ?
        ORDER BY c.contribution_date DESC, c.id DESC
        """,
        (user_id,),
    ).fetchall()

    return jsonify([dict(row) for row in rows])


@bp.put("/api/tfsa/transactions/<int:transaction_id>")
def update_tfsa_transaction(transaction_id):
    """Update a TFSA contribution transaction for the current user."""
    user_id = require_user_id()
    db = get_db()
    data = request.get_json() or {}

    tfsa_account_id = data.get("tfsa_account_id")
    contribution_date = (data.get("contribution_date") or "").strip()
    contribution_type = (data.get("contribution_type") or "").strip()
    memo = (data.get("memo") or "").strip()

    try:
        amount = float(data.get("amount") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a number"}), 400

    try:
        normalized_account_id = int(str(tfsa_account_id))
    except (TypeError, ValueError):
        return jsonify({"error": "tfsa_account_id must be an integer"}), 400

    if not contribution_date:
        return jsonify({"error": "contribution_date required"}), 400

    if contribution_type not in ("Deposit", "Withdrawal"):
        return jsonify({"error": "contribution_type must be 'Deposit' or 'Withdrawal'"}), 400

    if amount <= 0:
        return jsonify({"error": "amount must be > 0"}), 400

    existing = db.execute(
        "SELECT id FROM tfsa_contributions WHERE id = ? AND user_id = ?",
        (transaction_id, user_id),
    ).fetchone()
    if not existing:
        return jsonify({"error": "Transaction not found"}), 404

    account = db.execute(
        "SELECT id FROM tfsa_accounts WHERE id = ? AND user_id = ?",
        (normalized_account_id, user_id),
    ).fetchone()
    if not account:
        return jsonify({"error": "Account not found"}), 404

    db.execute(
        """
        UPDATE tfsa_contributions
        SET tfsa_account_id = ?,
            contribution_date = ?,
            amount = ?,
            contribution_type = ?,
            memo = ?
        WHERE id = ?
          AND user_id = ?
        """,
        (
            normalized_account_id,
            contribution_date,
            amount,
            contribution_type,
            memo,
            transaction_id,
            user_id,
        ),
    )
    db.commit()

    return jsonify({"updated": 1})


@bp.delete("/api/tfsa/transactions/<int:transaction_id>")
def delete_tfsa_transaction(transaction_id):
    """Delete a TFSA contribution transaction for the current user."""
    user_id = require_user_id()
    db = get_db()

    cursor = db.execute(
        "DELETE FROM tfsa_contributions WHERE id = ? AND user_id = ?",
        (transaction_id, user_id),
    )
    db.commit()

    if cursor.rowcount == 0:
        return jsonify({"error": "Transaction not found"}), 404

    return jsonify({"deleted": 1})


@bp.post("/api/tfsa/contributions")
def add_contribution():
    """Add a deposit or withdrawal to a TFSA account"""
    user_id = require_user_id()
    db = get_db()
    setup_error = _require_opening_balance_configured(db, user_id)
    if setup_error is not None:
        return setup_error

    data = request.get_json() or {}

    tfsa_account_id = data.get("tfsa_account_id")
    amount = float(data.get("amount") or 0)
    contribution_date = (data.get("contribution_date") or "").strip()
    contribution_type = (data.get("contribution_type") or "Deposit").strip()
    memo = (data.get("memo") or "").strip()

    if not all([tfsa_account_id, amount > 0, contribution_date]):
        return jsonify({"error": "Missing required fields"}), 400

    if contribution_type not in ("Deposit", "Withdrawal"):
        return jsonify({"error": "contribution_type must be 'Deposit' or 'Withdrawal'"}), 400

    # Verify account belongs to user
    acc = db.execute(
        "SELECT user_id FROM tfsa_accounts WHERE id = ?",
        (tfsa_account_id,),
    ).fetchone()

    if not acc or acc["user_id"] != user_id:
        return jsonify({"error": "Account not found"}), 404

    try:
        db.execute(
            """
            INSERT INTO tfsa_contributions
            (user_id, tfsa_account_id, contribution_date, amount, contribution_type, memo)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, tfsa_account_id, contribution_date, amount, contribution_type, memo),
        )
        db.commit()
        return jsonify({"success": True}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@bp.post("/api/tfsa/transfers")
def add_transfer():
    """Transfer funds between two TFSA accounts without changing total contribution room"""
    user_id = require_user_id()
    db = get_db()
    setup_error = _require_opening_balance_configured(db, user_id)
    if setup_error is not None:
        return setup_error

    data = request.get_json() or {}

    raw_from_account_id = data.get("from_tfsa_account_id")
    raw_to_account_id = data.get("to_tfsa_account_id")
    transfer_date = (data.get("transfer_date") or "").strip()
    memo = (data.get("memo") or "").strip()

    try:
        amount = float(data.get("amount") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a number"}), 400

    try:
        from_tfsa_account_id = int(str(raw_from_account_id))
        to_tfsa_account_id = int(str(raw_to_account_id))
    except (TypeError, ValueError):
        return jsonify({"error": "from_tfsa_account_id and to_tfsa_account_id must be integers"}), 400

    try:
        create_tfsa_transfer(
            db=db,
            user_id=user_id,
            from_tfsa_account_id=from_tfsa_account_id,
            to_tfsa_account_id=to_tfsa_account_id,
            transfer_date=transfer_date,
            amount=amount,
            memo=memo,
        )
        return jsonify({"success": True}), 201
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@bp.delete("/api/tfsa/accounts/<int:account_id>")
def delete_tfsa_account(account_id):
    """Delete a TFSA account and all its contributions"""
    user_id = require_user_id()
    db = get_db()

    acc = db.execute(
        "SELECT user_id FROM tfsa_accounts WHERE id = ?",
        (account_id,),
    ).fetchone()

    if not acc or acc["user_id"] != user_id:
        return jsonify({"error": "Account not found"}), 404

    db.execute("DELETE FROM tfsa_accounts WHERE id = ?", (account_id,))
    db.commit()
    return jsonify({"success": True})


@bp.post("/api/tfsa/reset")
def reset_tfsa_data():
    """Delete all TFSA feature data for the current user."""
    user_id = require_user_id()
    db = get_db()
    reset_user_tfsa_data(db, user_id)
    return jsonify({"success": True})


@bp.post("/api/tfsa/import-csv")
def import_tfsa_csv():
    """Replace all TFSA data for the current user with uploaded CSV data."""
    user_id = require_user_id()
    db = get_db()

    overwrite_mode = str(request.form.get("overwrite_mode") or "").strip().lower()
    overwrite_confirm = str(request.form.get("overwrite_confirm") or "").strip().upper()

    if overwrite_mode != "replace_all" or overwrite_confirm != "REPLACE":
        return jsonify(
            {
                "error": (
                    "TFSA import requires explicit overwrite confirmation. "
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
        parsed_import = parse_tfsa_import_csv_text(file_text)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    parsed_rows = parsed_import.get("transactions") or []
    setup_opening_balance = parsed_import.get("opening_balance")
    setup_base_year = parsed_import.get("opening_balance_base_year")
    setup_annual_limits = parsed_import.get("annual_limits") or []

    if not parsed_rows and setup_opening_balance is None and not setup_annual_limits:
        return jsonify({"error": "No TFSA rows found in uploaded CSV"}), 400

    reset_user_tfsa_data(db, user_id)

    setup_opening_balance_applied = False
    setup_base_year_applied = False
    setup_annual_limits_applied = 0

    if setup_opening_balance is not None:
        set_user_tfsa_opening_balance(db, user_id, float(setup_opening_balance))
        setup_opening_balance_applied = True

    if setup_base_year is not None:
        set_user_tfsa_opening_balance_base_year(db, user_id, int(setup_base_year))
        setup_base_year_applied = True

    for annual_limit in setup_annual_limits:
        upsert_user_tfsa_annual_limit(
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
            summary = import_tfsa_transactions_rows(db, user_id, parsed_rows)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    inferred_base_year = summary.get("inferred_base_year")
    if inferred_base_year is not None and not setup_base_year_applied:
        ensure_tfsa_setup_from_import(db, user_id, inferred_base_year)

    summary["setup_opening_balance_applied"] = setup_opening_balance_applied
    summary["setup_base_year_applied"] = setup_base_year_applied
    summary["setup_annual_limits_applied"] = setup_annual_limits_applied
    summary["setup_rows_parsed"] = (
        (1 if setup_opening_balance is not None else 0) + len(setup_annual_limits)
    )

    return jsonify(summary)

