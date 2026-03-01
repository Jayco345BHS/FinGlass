from flask import Blueprint, jsonify, request

from ..acb import calculate_ledger_rows
from ..constants import SUPPORTED_TRANSACTION_TYPES
from ..context import require_user_id
from ..db import get_db
from ..services.transactions_service import parse_transaction_payload

bp = Blueprint("transactions", __name__)


@bp.get("/api/transactions")
def list_transactions():
    security = request.args.get("security", "").strip()
    user_id = require_user_id()
    db = get_db()

    if security:
        rows = db.execute(
            """
            SELECT *
            FROM transactions
            WHERE user_id = ?
              AND security = ?
            ORDER BY trade_date, id
            """,
            (user_id, security),
        ).fetchall()
    else:
        rows = db.execute(
            """
            SELECT *
            FROM transactions
            WHERE user_id = ?
            ORDER BY trade_date, id
            """,
            (user_id,),
        ).fetchall()

    return jsonify([dict(row) for row in rows])


@bp.post("/api/transactions")
def create_transaction():
    payload = request.get_json(force=True)
    try:
        tx = parse_transaction_payload(payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    user_id = require_user_id()
    db = get_db()
    cursor = db.execute(
        """
        INSERT INTO transactions
        (user_id, security, trade_date, transaction_type, amount, shares, amount_per_share, commission, memo, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            tx["security"],
            tx["trade_date"],
            tx["transaction_type"],
            tx["amount"],
            tx["shares"],
            tx["amount_per_share"],
            tx["commission"],
            tx["memo"],
            "manual",
        ),
    )
    db.commit()

    return jsonify({"id": cursor.lastrowid}), 201


@bp.put("/api/transactions/<int:transaction_id>")
def update_transaction(transaction_id):
    payload = request.get_json(force=True)
    try:
        tx = parse_transaction_payload(payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    user_id = require_user_id()
    db = get_db()
    cursor = db.execute(
        "SELECT id FROM transactions WHERE id = ? AND user_id = ?",
        (transaction_id, user_id),
    )
    if not cursor.fetchone():
        return jsonify({"error": "Transaction not found"}), 404

    db.execute(
        """
        UPDATE transactions
        SET security = ?,
            trade_date = ?,
            transaction_type = ?,
            amount = ?,
            shares = ?,
            amount_per_share = ?,
            commission = ?,
            memo = ?
        WHERE id = ?
          AND user_id = ?
        """,
        (
            tx["security"],
            tx["trade_date"],
            tx["transaction_type"],
            tx["amount"],
            tx["shares"],
            tx["amount_per_share"],
            tx["commission"],
            tx["memo"],
            transaction_id,
            user_id,
        ),
    )
    db.commit()

    return jsonify({"updated": 1})


@bp.delete("/api/transactions/<int:transaction_id>")
def delete_transaction(transaction_id):
    user_id = require_user_id()
    db = get_db()
    cursor = db.execute(
        "DELETE FROM transactions WHERE id = ? AND user_id = ?",
        (transaction_id, user_id),
    )
    db.commit()
    if cursor.rowcount == 0:
        return jsonify({"error": "Transaction not found"}), 404
    return jsonify({"deleted": 1})


@bp.post("/api/transactions/delete-many")
def delete_many_transactions():
    payload = request.get_json(force=True)
    ids = payload.get("ids")
    if not isinstance(ids, list) or len(ids) == 0:
        return jsonify({"error": "ids must be a non-empty array"}), 400

    normalized_ids = []
    for item in ids:
        try:
            normalized_ids.append(int(item))
        except (TypeError, ValueError):
            return jsonify({"error": "ids must contain only integers"}), 400

    user_id = require_user_id()
    placeholders = ",".join("?" for _ in normalized_ids)
    db = get_db()
    cursor = db.execute(
        f"DELETE FROM transactions WHERE user_id = ? AND id IN ({placeholders})",
        [user_id, *normalized_ids],
    )
    db.commit()

    return jsonify({"deleted": cursor.rowcount})


@bp.get("/api/ledger")
def get_ledger():
    security = request.args.get("security", "").strip()
    if not security:
        return jsonify({"error": "security query parameter is required"}), 400

    user_id = require_user_id()
    db = get_db()
    rows = db.execute(
        """
        SELECT *
        FROM transactions
        WHERE user_id = ?
          AND security = ?
        ORDER BY trade_date, id
        """,
        (user_id, security),
    ).fetchall()

    ledger = calculate_ledger_rows(rows)
    return jsonify(ledger)


@bp.get("/api/securities")
def list_securities():
    user_id = require_user_id()
    db = get_db()
    securities = db.execute(
        "SELECT DISTINCT security FROM transactions WHERE user_id = ? ORDER BY security",
        (user_id,),
    ).fetchall()

    result = []
    for sec in securities:
        security = sec["security"]
        rows = db.execute(
            """
            SELECT *
            FROM transactions
            WHERE user_id = ?
              AND security = ?
            ORDER BY trade_date, id
            """,
            (user_id, security),
        ).fetchall()
        ledger = calculate_ledger_rows(rows)
        latest = ledger[-1] if ledger else {
            "share_balance": 0,
            "acb": 0,
            "acb_per_share": 0,
            "capital_gain": 0,
        }
        total_capital_gain = round(sum(item["capital_gain"] for item in ledger), 4)

        result.append(
            {
                "security": security,
                "share_balance": latest["share_balance"],
                "acb": latest["acb"],
                "acb_per_share": latest["acb_per_share"],
                "realized_capital_gain": total_capital_gain,
                "transaction_count": len(ledger),
            }
        )

    return jsonify(result)


@bp.get("/api/transaction-types")
def list_transaction_types():
    return jsonify(sorted(SUPPORTED_TRANSACTION_TYPES))
