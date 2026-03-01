from collections import defaultdict
from datetime import datetime
import sqlite3

from flask import Blueprint, jsonify, request

from ..constants import CASH_ACCOUNT_NUMBER
from ..context import require_user_id
from ..db import get_db
from ..market_data import MarketDataError, get_quote
from ..services.holdings_service import (
    derive_account_number,
    normalize_holding_symbol,
    parse_as_of_value,
    parse_numeric_field,
)

bp = Blueprint("holdings", __name__)


@bp.get("/api/accounts/dashboard")
def accounts_dashboard():
    user_id = require_user_id()
    db = get_db()
    latest_row = db.execute(
        "SELECT MAX(as_of) AS as_of FROM holdings_snapshots WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    latest_as_of = latest_row["as_of"] if latest_row else None

    if not latest_as_of:
        return jsonify(
            {
                "as_of": None,
                "summary": {
                    "accounts": 0,
                    "positions": 0,
                    "book_value_cad": 0,
                    "market_value": 0,
                    "unrealized_return": 0,
                },
                "accounts": [],
                "account_types": [],
                "top_holdings": [],
                "holdings_securities": [],
            }
        )

    accounts = db.execute(
        """
        SELECT
            account_name,
            account_type,
            account_classification,
            account_number,
            COUNT(*) AS positions,
            ROUND(SUM(book_value_cad), 4) AS book_value_cad,
            ROUND(SUM(market_value), 4) AS market_value,
            ROUND(SUM(unrealized_return), 4) AS unrealized_return
        FROM holdings_snapshots
        WHERE user_id = ?
          AND as_of = ?
        GROUP BY account_name, account_type, account_classification, account_number
        ORDER BY market_value DESC, account_name
        """,
        (user_id, latest_as_of),
    ).fetchall()

    account_types = db.execute(
        """
        SELECT
            COALESCE(NULLIF(account_type, ''), 'Unknown') AS account_type,
            ROUND(SUM(market_value), 4) AS market_value
        FROM holdings_snapshots
        WHERE user_id = ?
          AND as_of = ?
        GROUP BY COALESCE(NULLIF(account_type, ''), 'Unknown')
        ORDER BY market_value DESC
        """,
        (user_id, latest_as_of),
    ).fetchall()

    top_holdings = db.execute(
        """
        SELECT
            symbol,
            MAX(security_name) AS security_name,
            ROUND(SUM(quantity), 6) AS quantity,
            ROUND(SUM(book_value_cad), 4) AS book_value_cad,
            ROUND(SUM(market_value), 4) AS market_value,
            ROUND(SUM(unrealized_return), 4) AS unrealized_return
        FROM holdings_snapshots
        WHERE user_id = ?
          AND as_of = ?
        GROUP BY symbol
        ORDER BY market_value DESC, symbol
        LIMIT 12
        """,
        (user_id, latest_as_of),
    ).fetchall()

    holdings_securities = db.execute(
        """
        SELECT
            symbol,
            MAX(security_name) AS security_name,
            ROUND(SUM(quantity), 6) AS quantity,
            ROUND(SUM(book_value_cad), 4) AS book_value_cad,
            ROUND(SUM(market_value), 4) AS market_value,
            ROUND(SUM(unrealized_return), 4) AS unrealized_return
        FROM holdings_snapshots
        WHERE user_id = ?
          AND as_of = ?
        GROUP BY symbol
        ORDER BY market_value DESC, symbol
        """,
        (user_id, latest_as_of),
    ).fetchall()

    holdings_security_account_types = db.execute(
        """
        SELECT
            symbol,
            COALESCE(NULLIF(account_type, ''), 'Unknown') AS account_type,
            ROUND(SUM(market_value), 4) AS market_value
        FROM holdings_snapshots
        WHERE user_id = ?
          AND as_of = ?
        GROUP BY symbol, COALESCE(NULLIF(account_type, ''), 'Unknown')
        ORDER BY symbol, market_value DESC, account_type
        """,
        (user_id, latest_as_of),
    ).fetchall()

    account_types_by_symbol = defaultdict(list)
    for row in holdings_security_account_types:
        account_types_by_symbol[row["symbol"]].append(
            {
                "account_type": row["account_type"],
                "market_value": float(row["market_value"] or 0),
            }
        )

    holdings_securities_result = []
    for row in holdings_securities:
        row_dict = dict(row)
        symbol = row_dict.get("symbol")
        symbol_market_value = float(row_dict.get("market_value") or 0)
        type_rows = account_types_by_symbol.get(symbol, [])

        type_labels = []
        for type_row in type_rows:
            percentage = (
                (type_row["market_value"] / symbol_market_value) * 100
                if symbol_market_value > 0
                else 0
            )
            type_labels.append(f"{type_row['account_type']} ({percentage:.2f}%)")

        row_dict["account_types"] = ", ".join(type_labels)
        holdings_securities_result.append(row_dict)

    symbol_allocations = db.execute(
        """
        SELECT
            symbol,
            ROUND(SUM(market_value), 4) AS market_value
        FROM holdings_snapshots
        WHERE user_id = ?
          AND as_of = ?
        GROUP BY symbol
        HAVING SUM(market_value) > 0
        ORDER BY market_value DESC, symbol
        """,
        (user_id, latest_as_of),
    ).fetchall()

    summary = {
        "accounts": len(accounts),
        "positions": sum(int(item["positions"] or 0) for item in accounts),
        "book_value_cad": round(sum(float(item["book_value_cad"] or 0) for item in accounts), 4),
        "market_value": round(sum(float(item["market_value"] or 0) for item in accounts), 4),
        "unrealized_return": round(sum(float(item["unrealized_return"] or 0) for item in accounts), 4),
    }

    return jsonify(
        {
            "as_of": latest_as_of,
            "summary": summary,
            "accounts": [dict(row) for row in accounts],
            "account_types": [dict(row) for row in account_types],
            "top_holdings": [dict(row) for row in top_holdings],
            "holdings_securities": holdings_securities_result,
            "symbol_allocations": [dict(row) for row in symbol_allocations],
        }
    )


@bp.put("/api/accounts/cash")
def upsert_cash_account():
    payload = request.get_json(force=True)
    as_of = str(payload.get("as_of") or "").strip()

    user_id = require_user_id()
    db = get_db()

    if not as_of:
        latest_row = db.execute(
            "SELECT MAX(as_of) AS as_of FROM holdings_snapshots WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        as_of = latest_row["as_of"] if latest_row else None

    if not as_of:
        return jsonify({"error": "No holdings snapshot found"}), 400

    try:
        amount = float(payload.get("amount"))
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a number"}), 400

    if abs(amount) < 0.0000001:
        db.execute(
            """
            DELETE FROM holdings_snapshots
            WHERE user_id = ? AND as_of = ? AND account_number = ? AND symbol = 'CASH'
            """,
            (user_id, as_of, CASH_ACCOUNT_NUMBER),
        )
        db.commit()
        return jsonify({"updated": 1, "as_of": as_of, "account_number": CASH_ACCOUNT_NUMBER, "cash": 0.0})

    db.execute(
        """
        INSERT INTO holdings_snapshots (
            user_id,
            as_of,
            account_name,
            account_type,
            account_classification,
            account_number,
            symbol,
            exchange,
            mic,
            security_name,
            security_type,
            quantity,
            market_price,
            market_price_currency,
            book_value_cad,
            market_value,
            market_value_currency,
            unrealized_return,
            source_filename
        ) VALUES (?, ?, 'Cash Account', 'Cash', 'Cash', ?, 'CASH', '', '', 'Cash', 'Cash', ?, ?, 'CAD', ?, ?, 'CAD', 0, 'manual_cash_entry')
        ON CONFLICT(user_id, as_of, account_number, symbol)
        DO UPDATE SET
            account_name = excluded.account_name,
            account_type = excluded.account_type,
            account_classification = excluded.account_classification,
            security_name = excluded.security_name,
            security_type = excluded.security_type,
            quantity = excluded.quantity,
            market_price = excluded.market_price,
            market_price_currency = excluded.market_price_currency,
            book_value_cad = excluded.book_value_cad,
            market_value = excluded.market_value,
            market_value_currency = excluded.market_value_currency,
            unrealized_return = excluded.unrealized_return,
            source_filename = excluded.source_filename,
            imported_at = CURRENT_TIMESTAMP
        """,
        (
            user_id,
            as_of,
            CASH_ACCOUNT_NUMBER,
            1.0,
            amount,
            amount,
            amount,
        ),
    )
    db.commit()

    return jsonify(
        {
            "updated": 1,
            "as_of": as_of,
            "account_number": CASH_ACCOUNT_NUMBER,
            "cash": round(amount, 4),
        }
    )


@bp.get("/api/holdings")
def list_holdings_rows():
    user_id = require_user_id()
    as_of = str(request.args.get("as_of") or "").strip()
    db = get_db()

    latest_row = db.execute(
        "SELECT MAX(as_of) AS as_of FROM holdings_snapshots WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    latest_as_of = latest_row["as_of"] if latest_row else None

    target_as_of = as_of or latest_as_of
    if not target_as_of:
        return jsonify({"as_of": None, "latest_as_of": None, "rows": []})

    rows = db.execute(
        """
        SELECT
            id,
            as_of,
            account_name,
            account_type,
            account_classification,
            account_number,
            symbol,
            security_name,
            quantity,
            book_value_cad,
            market_value,
            unrealized_return
        FROM holdings_snapshots
        WHERE user_id = ?
          AND as_of = ?
        ORDER BY account_name, account_number, symbol, id
        """,
        (user_id, target_as_of),
    ).fetchall()

    return jsonify(
        {
            "as_of": target_as_of,
            "latest_as_of": latest_as_of,
            "rows": [dict(row) for row in rows],
        }
    )


@bp.post("/api/holdings")
def create_holding_row():
    payload = request.get_json(force=True)
    user_id = require_user_id()
    db = get_db()

    account_name = str(payload.get("account_name") or "").strip()
    account_number = str(payload.get("account_number") or "").strip() or derive_account_number(account_name)
    symbol = normalize_holding_symbol(payload.get("symbol"))
    if not account_name:
        return jsonify({"error": "account_name is required"}), 400
    if not symbol:
        return jsonify({"error": "symbol is required"}), 400

    try:
        as_of = parse_as_of_value(db, user_id, payload.get("as_of"))
    except ValueError:
        return jsonify({"error": "as_of must be YYYY-MM-DD"}), 400

    try:
        quantity = parse_numeric_field(payload, "quantity")
        book_value_cad = parse_numeric_field(payload, "book_value_cad")
        market_value = parse_numeric_field(payload, "market_value")
        if "unrealized_return" in payload:
            unrealized_return = parse_numeric_field(payload, "unrealized_return")
        else:
            unrealized_return = market_value - book_value_cad
    except (TypeError, ValueError):
        return jsonify({"error": "numeric fields must be valid numbers"}), 400

    if "market_price" in payload:
        try:
            market_price = float(payload.get("market_price") or 0)
        except (TypeError, ValueError):
            return jsonify({"error": "market_price must be a number"}), 400
    else:
        market_price = (market_value / quantity) if abs(quantity) > 0.0000001 else 0.0

    account_type = str(payload.get("account_type") or "").strip()
    account_classification = str(payload.get("account_classification") or "").strip()
    exchange = str(payload.get("exchange") or "").strip()
    mic = str(payload.get("mic") or "").strip()
    security_name = str(payload.get("security_name") or "").strip()
    security_type = str(payload.get("security_type") or "").strip()
    market_price_currency = str(payload.get("market_price_currency") or "CAD").strip() or "CAD"
    market_value_currency = str(payload.get("market_value_currency") or "CAD").strip() or "CAD"

    db.execute(
        """
        INSERT INTO holdings_snapshots (
            user_id,
            as_of,
            account_name,
            account_type,
            account_classification,
            account_number,
            symbol,
            exchange,
            mic,
            security_name,
            security_type,
            quantity,
            market_price,
            market_price_currency,
            book_value_cad,
            market_value,
            market_value_currency,
            unrealized_return,
            source_filename
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, as_of, account_number, symbol)
        DO UPDATE SET
            account_name = excluded.account_name,
            account_type = excluded.account_type,
            account_classification = excluded.account_classification,
            exchange = excluded.exchange,
            mic = excluded.mic,
            security_name = excluded.security_name,
            security_type = excluded.security_type,
            quantity = excluded.quantity,
            market_price = excluded.market_price,
            market_price_currency = excluded.market_price_currency,
            book_value_cad = excluded.book_value_cad,
            market_value = excluded.market_value,
            market_value_currency = excluded.market_value_currency,
            unrealized_return = excluded.unrealized_return,
            source_filename = excluded.source_filename,
            imported_at = CURRENT_TIMESTAMP
        """,
        (
            user_id,
            as_of,
            account_name,
            account_type,
            account_classification,
            account_number,
            symbol,
            exchange,
            mic,
            security_name,
            security_type,
            quantity,
            market_price,
            market_price_currency,
            book_value_cad,
            market_value,
            market_value_currency,
            unrealized_return,
            "manual_holding_entry",
        ),
    )
    db.commit()

    created = db.execute(
        """
        SELECT
            id,
            as_of,
            account_name,
            account_type,
            account_classification,
            account_number,
            symbol,
            security_name,
            quantity,
            book_value_cad,
            market_value,
            unrealized_return
        FROM holdings_snapshots
        WHERE user_id = ?
          AND as_of = ?
          AND account_number = ?
          AND symbol = ?
        LIMIT 1
        """,
        (user_id, as_of, account_number, symbol),
    ).fetchone()

    return jsonify(dict(created)), 201


@bp.put("/api/holdings/<int:holding_id>")
def update_holding_row(holding_id):
    payload = request.get_json(force=True)
    user_id = require_user_id()
    db = get_db()

    existing = db.execute(
        """
        SELECT
            id,
            account_type,
            account_classification,
            exchange,
            mic,
            security_name,
            security_type,
            market_price,
            market_price_currency,
            market_value_currency
        FROM holdings_snapshots
        WHERE id = ? AND user_id = ?
        """,
        (holding_id, user_id),
    ).fetchone()
    if not existing:
        return jsonify({"error": "Holding row not found"}), 404

    account_name = str(payload.get("account_name") or "").strip()
    account_number = str(payload.get("account_number") or "").strip()
    symbol = normalize_holding_symbol(payload.get("symbol"))
    if not account_name:
        return jsonify({"error": "account_name is required"}), 400
    if not symbol:
        return jsonify({"error": "symbol is required"}), 400

    if not account_number:
        current_account_row = db.execute(
            "SELECT account_number FROM holdings_snapshots WHERE id = ? AND user_id = ?",
            (holding_id, user_id),
        ).fetchone()
        account_number = (
            str(current_account_row["account_number"] or "").strip()
            if current_account_row
            else ""
        )

    if not account_number:
        account_number = derive_account_number(account_name)

    as_of = str(payload.get("as_of") or "").strip()
    if not as_of:
        as_of_row = db.execute(
            "SELECT as_of FROM holdings_snapshots WHERE id = ? AND user_id = ?",
            (holding_id, user_id),
        ).fetchone()
        as_of = as_of_row["as_of"] if as_of_row else ""
    if not as_of:
        return jsonify({"error": "as_of is required"}), 400
    try:
        as_of = datetime.strptime(as_of, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return jsonify({"error": "as_of must be YYYY-MM-DD"}), 400

    try:
        quantity = parse_numeric_field(payload, "quantity", 0)
        book_value_cad = parse_numeric_field(payload, "book_value_cad", 0)
        market_value = parse_numeric_field(payload, "market_value", 0)
        if "unrealized_return" in payload:
            unrealized_return = parse_numeric_field(payload, "unrealized_return", 0)
        else:
            unrealized_return = market_value - book_value_cad
    except (TypeError, ValueError):
        return jsonify({"error": "numeric fields must be valid numbers"}), 400

    if "market_price" in payload:
        try:
            market_price = float(payload.get("market_price") or 0)
        except (TypeError, ValueError):
            return jsonify({"error": "market_price must be a number"}), 400
    else:
        existing_market_price = float(existing["market_price"] or 0)
        market_price = existing_market_price if abs(existing_market_price) > 0.0000001 else (
            (market_value / quantity) if abs(quantity) > 0.0000001 else 0.0
        )

    account_type = str(payload.get("account_type") or existing["account_type"] or "").strip()
    account_classification = str(
        payload.get("account_classification") or existing["account_classification"] or ""
    ).strip()
    exchange = str(payload.get("exchange") or existing["exchange"] or "").strip()
    mic = str(payload.get("mic") or existing["mic"] or "").strip()
    security_name = str(payload.get("security_name") or existing["security_name"] or "").strip()
    security_type = str(payload.get("security_type") or existing["security_type"] or "").strip()
    market_price_currency = str(
        payload.get("market_price_currency")
        or existing["market_price_currency"]
        or "CAD"
    ).strip() or "CAD"
    market_value_currency = str(
        payload.get("market_value_currency")
        or existing["market_value_currency"]
        or "CAD"
    ).strip() or "CAD"

    try:
        db.execute(
            """
            UPDATE holdings_snapshots
            SET as_of = ?,
                account_name = ?,
                account_type = ?,
                account_classification = ?,
                account_number = ?,
                symbol = ?,
                exchange = ?,
                mic = ?,
                security_name = ?,
                security_type = ?,
                quantity = ?,
                market_price = ?,
                market_price_currency = ?,
                book_value_cad = ?,
                market_value = ?,
                market_value_currency = ?,
                unrealized_return = ?,
                source_filename = ?,
                imported_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND user_id = ?
            """,
            (
                as_of,
                account_name,
                account_type,
                account_classification,
                account_number,
                symbol,
                exchange,
                mic,
                security_name,
                security_type,
                quantity,
                market_price,
                market_price_currency,
                book_value_cad,
                market_value,
                market_value_currency,
                unrealized_return,
                "manual_holding_entry",
                holding_id,
                user_id,
            ),
        )
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        return jsonify({"error": "A row already exists for this date/account/symbol"}), 409

    updated = db.execute(
        """
        SELECT
            id,
            as_of,
            account_name,
            account_type,
            account_classification,
            account_number,
            symbol,
            security_name,
            quantity,
            book_value_cad,
            market_value,
            unrealized_return
        FROM holdings_snapshots
        WHERE id = ?
          AND user_id = ?
        """,
        (holding_id, user_id),
    ).fetchone()

    return jsonify(dict(updated))


@bp.delete("/api/holdings/<int:holding_id>")
def delete_holding_row(holding_id):
    user_id = require_user_id()
    db = get_db()
    cursor = db.execute(
        "DELETE FROM holdings_snapshots WHERE id = ? AND user_id = ?",
        (holding_id, user_id),
    )
    db.commit()
    if cursor.rowcount == 0:
        return jsonify({"error": "Holding row not found"}), 404
    return jsonify({"deleted": 1})


@bp.get("/api/market-data/quote")
def market_data_quote():
    symbol = str(request.args.get("symbol") or "").strip().upper()
    if not symbol:
        return jsonify({"error": "symbol is required"}), 400

    try:
        quote = get_quote(symbol)
    except MarketDataError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        return jsonify({"error": "Failed to fetch quote"}), 502

    return jsonify(quote)


@bp.post("/api/holdings/refresh-market-values")
def refresh_holdings_market_values():
    user_id = require_user_id()
    payload = request.get_json(silent=True) or {}
    as_of = str(payload.get("as_of") or "").strip()
    db = get_db()

    if not as_of:
        latest_row = db.execute(
            "SELECT MAX(as_of) AS as_of FROM holdings_snapshots WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        as_of = latest_row["as_of"] if latest_row and latest_row["as_of"] else ""

    if not as_of:
        return jsonify({"error": "No holdings snapshot found"}), 400

    rows = db.execute(
        """
        SELECT id, symbol, quantity, book_value_cad
        FROM holdings_snapshots
        WHERE user_id = ?
          AND as_of = ?
        ORDER BY id
        """,
        (user_id, as_of),
    ).fetchall()

    if not rows:
        return jsonify({"error": "No holdings rows found for snapshot"}), 400

    symbols = {
        str(row["symbol"] or "").strip().upper()
        for row in rows
        if str(row["symbol"] or "").strip().upper() not in {"", "CASH"}
    }

    quotes_by_symbol = {}
    errors = []
    for symbol in sorted(symbols):
        try:
            quote = get_quote(symbol)
            quotes_by_symbol[symbol] = float(quote["price"])
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")

    updated = 0
    for row in rows:
        symbol = str(row["symbol"] or "").strip().upper()
        if symbol not in quotes_by_symbol:
            continue

        quantity = float(row["quantity"] or 0)
        book_value = float(row["book_value_cad"] or 0)
        price = float(quotes_by_symbol[symbol])
        market_value = round(quantity * price, 4)
        unrealized = round(market_value - book_value, 4)

        db.execute(
            """
            UPDATE holdings_snapshots
            SET market_price = ?,
                market_value = ?,
                unrealized_return = ?,
                source_filename = ?,
                imported_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND user_id = ?
            """,
            (
                price,
                market_value,
                unrealized,
                "market_data_refresh",
                int(row["id"]),
                user_id,
            ),
        )
        updated += 1

    db.commit()

    return jsonify(
        {
            "as_of": as_of,
            "symbols_requested": len(symbols),
            "symbols_priced": len(quotes_by_symbol),
            "rows_updated": updated,
            "errors": errors,
        }
    )
