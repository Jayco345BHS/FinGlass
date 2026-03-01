from flask import Blueprint, jsonify, request

from ..context import require_user_id
from ..db import get_db

bp = Blueprint("net_worth", __name__)


@bp.get("/api/net-worth")
def list_net_worth_entries():
    user_id = require_user_id()
    db = get_db()
    rows = db.execute(
        """
        SELECT id, entry_date, amount, COALESCE(note, '') AS note
        FROM net_worth_history
        WHERE user_id = ?
        ORDER BY entry_date ASC, id ASC
        """,
        (user_id,),
    ).fetchall()
    return jsonify([dict(row) for row in rows])


@bp.post("/api/net-worth")
def create_net_worth_entry():
    payload = request.get_json(force=True)
    entry_date = str(payload.get("entry_date") or "").strip()
    if not entry_date:
        return jsonify({"error": "entry_date is required"}), 400

    try:
        amount = float(payload.get("amount"))
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a number"}), 400

    note = str(payload.get("note") or "").strip()

    user_id = require_user_id()
    db = get_db()
    try:
        cursor = db.execute(
            """
            INSERT INTO net_worth_history (user_id, entry_date, amount, note)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, entry_date, amount, note),
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        return jsonify({"error": f"Failed to create net worth entry: {exc}"}), 400

    created = db.execute(
        """
        SELECT id, entry_date, amount, COALESCE(note, '') AS note
        FROM net_worth_history
        WHERE id = ? AND user_id = ?
        """,
        (cursor.lastrowid, user_id),
    ).fetchone()
    return jsonify(dict(created)), 201


@bp.put("/api/net-worth/<int:entry_id>")
def update_net_worth_entry(entry_id):
    payload = request.get_json(force=True)
    entry_date = str(payload.get("entry_date") or "").strip()
    if not entry_date:
        return jsonify({"error": "entry_date is required"}), 400

    try:
        amount = float(payload.get("amount"))
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a number"}), 400

    note = str(payload.get("note") or "").strip()

    user_id = require_user_id()
    db = get_db()
    existing = db.execute(
        "SELECT id FROM net_worth_history WHERE id = ? AND user_id = ?",
        (entry_id, user_id),
    ).fetchone()
    if not existing:
        return jsonify({"error": "Net worth entry not found"}), 404

    try:
        db.execute(
            """
            UPDATE net_worth_history
            SET entry_date = ?,
                amount = ?,
                note = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND user_id = ?
            """,
            (entry_date, amount, note, entry_id, user_id),
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        return jsonify({"error": f"Failed to update net worth entry: {exc}"}), 400

    updated = db.execute(
        """
        SELECT id, entry_date, amount, COALESCE(note, '') AS note
        FROM net_worth_history
        WHERE id = ? AND user_id = ?
        """,
        (entry_id, user_id),
    ).fetchone()
    return jsonify(dict(updated))


@bp.delete("/api/net-worth/<int:entry_id>")
def delete_net_worth_entry(entry_id):
    user_id = require_user_id()
    db = get_db()
    cursor = db.execute(
        "DELETE FROM net_worth_history WHERE id = ? AND user_id = ?",
        (entry_id, user_id),
    )
    db.commit()
    if cursor.rowcount == 0:
        return jsonify({"error": "Net worth entry not found"}), 404
    return jsonify({"deleted": 1})
