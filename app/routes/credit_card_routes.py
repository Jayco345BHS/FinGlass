from collections import defaultdict

from flask import Blueprint, jsonify, request

from ..context import require_user_id
from ..credit_card_categories import normalize_credit_card_category
from ..db import get_db
from ..services.credit_card_service import parse_bool_query, parse_credit_card_category_filters

bp = Blueprint("credit_card", __name__)


@bp.get("/api/credit-card/dashboard")
def credit_card_dashboard():
    user_id = require_user_id()
    provider = str(request.args.get("provider") or "rogers_bank").strip()
    start_date = str(request.args.get("start_date") or "").strip()
    end_date = str(request.args.get("end_date") or "").strip()
    merchant = str(request.args.get("merchant") or "").strip()
    include_hidden = parse_bool_query(request.args.get("include_hidden"))
    selected_categories = parse_credit_card_category_filters(request.args)

    clauses = ["user_id = ?", "provider = ?"]
    params = [user_id, provider]

    if start_date:
        clauses.append("transaction_date >= ?")
        params.append(start_date)

    if end_date:
        clauses.append("transaction_date <= ?")
        params.append(end_date)

    if merchant:
        clauses.append("COALESCE(merchant_name, '') LIKE ?")
        params.append(f"%{merchant}%")

    if not include_hidden:
        clauses.append("is_hidden = 0")

    where_sql = " AND ".join(clauses)
    db = get_db()
    rows = db.execute(
        f"""
        SELECT
            id,
            transaction_date,
            posted_date,
            card_last4,
            merchant_category,
            merchant_name,
            amount,
            rewards,
            status
        FROM credit_card_transactions
        WHERE {where_sql}
        """,
        params,
    ).fetchall()

    filtered_rows = []
    for row in rows:
        mapped = dict(row)
        mapped["merchant_category"] = normalize_credit_card_category(
            mapped.get("merchant_category", "")
        )
        if selected_categories and mapped["merchant_category"] not in selected_categories:
            continue
        filtered_rows.append(mapped)

    expense_rows = [row for row in filtered_rows if float(row.get("amount") or 0) > 0]

    total_expenses = round(
        sum(float(row.get("amount") or 0) for row in expense_rows),
        2,
    )
    summary = {
        "total_expenses": total_expenses,
        "transactions": len(expense_rows),
    }

    monthly_totals = defaultdict(float)
    for row in expense_rows:
        month = str(row.get("transaction_date") or "")[:7]
        if month:
            monthly_totals[month] += float(row.get("amount") or 0)

    monthly = [
        {
            "month": month,
            "expenses": round(monthly_totals[month], 2),
        }
        for month in sorted(monthly_totals.keys())
    ]

    category_totals = defaultdict(lambda: {"amount": 0.0, "transaction_count": 0})
    for row in expense_rows:
        normalized_category = row["merchant_category"]
        category_totals[normalized_category]["amount"] += float(row.get("amount") or 0)
        category_totals[normalized_category]["transaction_count"] += 1

    normalized_categories = []
    for category_name, totals in category_totals.items():
        tx_count = totals["transaction_count"]
        amount = round(totals["amount"], 2)
        normalized_categories.append(
            {
                "merchant_category": category_name,
                "amount": amount,
                "transaction_count": tx_count,
                "average_amount": round(amount / tx_count, 2) if tx_count else 0,
            }
        )

    normalized_categories.sort(key=lambda row: row["amount"], reverse=True)

    merchant_totals = defaultdict(lambda: {"amount": 0.0, "transaction_count": 0})
    for row in expense_rows:
        merchant_name = str(row.get("merchant_name") or "").strip() or "Unknown Merchant"
        merchant_totals[merchant_name]["amount"] += float(row.get("amount") or 0)
        merchant_totals[merchant_name]["transaction_count"] += 1

    merchants = []
    for merchant_name, totals in merchant_totals.items():
        tx_count = totals["transaction_count"]
        amount = round(totals["amount"], 2)
        merchants.append(
            {
                "merchant_name": merchant_name,
                "amount": amount,
                "transaction_count": tx_count,
                "average_amount": round(amount / tx_count, 2) if tx_count else 0,
            }
        )
    merchants.sort(key=lambda row: row["amount"], reverse=True)

    recent_rows = sorted(
        expense_rows,
        key=lambda row: (row.get("transaction_date") or "", int(row.get("id") or 0)),
        reverse=True,
    )[:80]

    latest_transaction_date = None
    if expense_rows:
        latest_transaction_date = max(str(row.get("transaction_date") or "") for row in expense_rows)

    return jsonify(
        {
            "provider": provider,
            "latest_transaction_date": latest_transaction_date,
            "summary": summary,
            "monthly": monthly,
            "categories": normalized_categories,
            "top_merchants": merchants,
            "recent": recent_rows,
        }
    )


@bp.get("/api/credit-card/categories")
def credit_card_categories():
    user_id = require_user_id()
    provider = str(request.args.get("provider") or "rogers_bank").strip()
    db = get_db()
    rows = db.execute(
        """
        SELECT DISTINCT COALESCE(NULLIF(merchant_category, ''), 'Uncategorized') AS merchant_category
        FROM credit_card_transactions
        WHERE user_id = ?
          AND provider = ?
          AND is_hidden = 0
        ORDER BY merchant_category ASC
        """,
        (user_id, provider),
    ).fetchall()
    categories = sorted(
        {
            normalize_credit_card_category(row["merchant_category"])
            for row in rows
            if row["merchant_category"] is not None
        }
    )
    return jsonify(categories)


@bp.get("/api/credit-card/transactions")
def credit_card_transactions():
    user_id = require_user_id()
    provider = str(request.args.get("provider") or "rogers_bank").strip()
    start_date = str(request.args.get("start_date") or "").strip()
    end_date = str(request.args.get("end_date") or "").strip()
    selected_categories = parse_credit_card_category_filters(request.args)
    merchant = str(request.args.get("merchant") or "").strip()
    include_payments = parse_bool_query(request.args.get("include_payments"))
    include_hidden = parse_bool_query(request.args.get("include_hidden"))
    limit_raw = str(request.args.get("limit") or "").strip().lower()
    if not limit_raw:
        limit = 300
    elif limit_raw in {"all", "none"}:
        limit = None
    else:
        try:
            limit = int(limit_raw)
        except ValueError:
            return jsonify({"error": "limit must be an integer or 'all'"}), 400
        if limit < 1:
            return jsonify({"error": "limit must be >= 1 or 'all'"}), 400

    clauses = ["user_id = ?", "provider = ?"]
    params = [user_id, provider]

    if start_date:
        clauses.append("transaction_date >= ?")
        params.append(start_date)

    if end_date:
        clauses.append("transaction_date <= ?")
        params.append(end_date)

    if merchant:
        clauses.append("COALESCE(merchant_name, '') LIKE ?")
        params.append(f"%{merchant}%")

    if not include_payments:
        clauses.append("amount > 0")

    if not include_hidden:
        clauses.append("is_hidden = 0")

    where_sql = " AND ".join(clauses)
    query = f"""
        SELECT
            id,
            transaction_date,
            posted_date,
            card_last4,
            merchant_category,
            merchant_name,
            merchant_city,
            merchant_region,
            merchant_country,
            amount,
            rewards,
            is_hidden,
            status,
            activity_type,
            reference_number
        FROM credit_card_transactions
        WHERE {where_sql}
        ORDER BY transaction_date DESC, id DESC
    """

    db = get_db()
    rows = db.execute(query, params).fetchall()
    normalized_rows = []
    for row in rows:
        mapped = dict(row)
        mapped["merchant_category"] = normalize_credit_card_category(
            mapped.get("merchant_category", "")
        )
        if selected_categories and mapped["merchant_category"] not in selected_categories:
            continue
        normalized_rows.append(mapped)
        if limit is not None and len(normalized_rows) >= limit:
            break

    return jsonify(normalized_rows)


@bp.patch("/api/credit-card/transactions/<int:transaction_id>/hidden")
def set_credit_card_transaction_hidden(transaction_id):
    user_id = require_user_id()
    payload = request.get_json(force=True)
    provider = str(payload.get("provider") or "rogers_bank").strip()
    hidden = bool(payload.get("hidden", True))

    db = get_db()
    cursor = db.execute(
        """
        UPDATE credit_card_transactions
        SET is_hidden = ?
        WHERE id = ?
          AND user_id = ?
          AND provider = ?
        """,
        (1 if hidden else 0, transaction_id, user_id, provider),
    )
    db.commit()
    if cursor.rowcount == 0:
        return jsonify({"error": "Credit card transaction not found"}), 404
    return jsonify({"updated": 1, "hidden": hidden})


@bp.post("/api/credit-card/transactions/hide-many")
def set_many_credit_card_transactions_hidden():
    user_id = require_user_id()
    payload = request.get_json(force=True)
    provider = str(payload.get("provider") or "rogers_bank").strip()
    hidden = bool(payload.get("hidden", True))
    ids = payload.get("ids")
    if not isinstance(ids, list) or len(ids) == 0:
        return jsonify({"error": "ids must be a non-empty array"}), 400

    normalized_ids = []
    for item in ids:
        try:
            normalized_ids.append(int(item))
        except (TypeError, ValueError):
            return jsonify({"error": "ids must contain only integers"}), 400

    placeholders = ",".join("?" for _ in normalized_ids)
    db = get_db()
    cursor = db.execute(
        f"UPDATE credit_card_transactions SET is_hidden = ? WHERE user_id = ? AND provider = ? AND id IN ({placeholders})",
        [1 if hidden else 0, user_id, provider, *normalized_ids],
    )
    db.commit()

    return jsonify({"updated": cursor.rowcount, "hidden": hidden})


@bp.delete("/api/credit-card/transactions/<int:transaction_id>")
def delete_credit_card_transaction(transaction_id):
    user_id = require_user_id()
    provider = str(request.args.get("provider") or "rogers_bank").strip()
    db = get_db()
    cursor = db.execute(
        "DELETE FROM credit_card_transactions WHERE id = ? AND user_id = ? AND provider = ?",
        (transaction_id, user_id, provider),
    )
    db.commit()
    if cursor.rowcount == 0:
        return jsonify({"error": "Credit card transaction not found"}), 404
    return jsonify({"deleted": 1})


@bp.post("/api/credit-card/transactions/delete-many")
def delete_many_credit_card_transactions():
    user_id = require_user_id()
    payload = request.get_json(force=True)
    provider = str(payload.get("provider") or "rogers_bank").strip()
    ids = payload.get("ids")
    if not isinstance(ids, list) or len(ids) == 0:
        return jsonify({"error": "ids must be a non-empty array"}), 400

    normalized_ids = []
    for item in ids:
        try:
            normalized_ids.append(int(item))
        except (TypeError, ValueError):
            return jsonify({"error": "ids must contain only integers"}), 400

    placeholders = ",".join("?" for _ in normalized_ids)
    db = get_db()
    cursor = db.execute(
        f"DELETE FROM credit_card_transactions WHERE user_id = ? AND provider = ? AND id IN ({placeholders})",
        [user_id, provider, *normalized_ids],
    )
    db.commit()

    return jsonify({"deleted": cursor.rowcount})


@bp.delete("/api/credit-card/transactions")
def delete_all_credit_card_transactions():
    user_id = require_user_id()
    provider = str(request.args.get("provider") or "rogers_bank").strip()
    db = get_db()
    cursor = db.execute(
        "DELETE FROM credit_card_transactions WHERE user_id = ? AND provider = ?",
        (user_id, provider),
    )
    db.commit()
    return jsonify({"deleted": cursor.rowcount})
