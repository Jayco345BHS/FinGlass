from pathlib import Path
from collections import defaultdict

from flask import Flask, jsonify, render_template, request

from .acb import calculate_ledger_rows
from .db import close_db, get_db, init_db
from .credit_card_categories import normalize_credit_card_category
from .importer import (
    import_holdings_rows,
    import_rogers_credit_rows,
    import_transactions_rows,
    parse_adjustedcostbase_csv_text,
    parse_holdings_csv_text,
    parse_rogers_credit_csv_text,
)
from .staged_imports import (
    SUPPORTED_IMPORT_TYPES,
    commit_batch,
    create_import_batch,
    delete_batch_row,
    get_batch,
    parse_upload,
    update_batch_row,
)

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CSV = BASE_DIR / "AdjustedCostBase.ca.2026-02-22.csv"
CASH_ACCOUNT_NUMBER = "__CASH__"
SUPPORTED_TRANSACTION_TYPES = {
    "Buy",
    "Sell",
    "Return of Capital",
    "Capital Gains Dividend",
    "Reinvested Dividend",
    "Reinvested Capital Gains Distribution",
    "Split",
}


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")

    init_db()
    app.teardown_appcontext(close_db)

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/security/<security>")
    def security_detail(security):
        return render_template("security.html", security=security.upper())

    @app.get("/credit-card")
    def credit_card_detail():
        provider = str(request.args.get("provider") or "rogers_bank").strip() or "rogers_bank"
        return render_template("credit_card.html", provider=provider)

    @app.get("/net-worth")
    def net_worth_detail():
        return render_template("net_worth.html")

    @app.get("/api/transactions")
    def list_transactions():
        security = request.args.get("security", "").strip()
        db = get_db()

        if security:
            rows = db.execute(
                """
                SELECT *
                FROM transactions
                WHERE security = ?
                ORDER BY trade_date, id
                """,
                (security,),
            ).fetchall()
        else:
            rows = db.execute(
                """
                SELECT *
                FROM transactions
                ORDER BY trade_date, id
                """
            ).fetchall()

        return jsonify([dict(row) for row in rows])

    @app.post("/api/transactions")
    def create_transaction():
        payload = request.get_json(force=True)
        required = ["security", "trade_date", "transaction_type", "amount", "shares"]
        for field in required:
            if field not in payload:
                return jsonify({"error": f"Missing field: {field}"}), 400

        security = str(payload["security"]).strip().upper()
        trade_date = str(payload["trade_date"]).strip()
        transaction_type = str(payload["transaction_type"]).strip()
        if transaction_type not in SUPPORTED_TRANSACTION_TYPES:
            return jsonify({"error": "Unsupported transaction type"}), 400

        amount = float(payload.get("amount") or 0)
        shares = float(payload.get("shares") or 0)
        amount_per_share = payload.get("amount_per_share")
        commission = float(payload.get("commission") or 0)
        memo = str(payload.get("memo") or "").strip()

        if amount_per_share in (None, ""):
            amount_per_share = (amount / shares) if shares else 0
        amount_per_share = float(amount_per_share)

        db = get_db()
        cursor = db.execute(
            """
            INSERT INTO transactions
            (security, trade_date, transaction_type, amount, shares, amount_per_share, commission, memo, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                security,
                trade_date,
                transaction_type,
                amount,
                shares,
                amount_per_share,
                commission,
                memo,
                "manual",
            ),
        )
        db.commit()

        return jsonify({"id": cursor.lastrowid}), 201

    @app.put("/api/transactions/<int:transaction_id>")
    def update_transaction(transaction_id):
        payload = request.get_json(force=True)
        required = ["security", "trade_date", "transaction_type", "amount", "shares"]
        for field in required:
            if field not in payload:
                return jsonify({"error": f"Missing field: {field}"}), 400

        security = str(payload["security"]).strip().upper()
        trade_date = str(payload["trade_date"]).strip()
        transaction_type = str(payload["transaction_type"]).strip()
        if transaction_type not in SUPPORTED_TRANSACTION_TYPES:
            return jsonify({"error": "Unsupported transaction type"}), 400

        amount = float(payload.get("amount") or 0)
        shares = float(payload.get("shares") or 0)
        amount_per_share = payload.get("amount_per_share")
        commission = float(payload.get("commission") or 0)
        memo = str(payload.get("memo") or "").strip()

        if amount_per_share in (None, ""):
            amount_per_share = (amount / shares) if shares else 0
        amount_per_share = float(amount_per_share)

        db = get_db()
        cursor = db.execute("SELECT id FROM transactions WHERE id = ?", (transaction_id,))
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
            """,
            (
                security,
                trade_date,
                transaction_type,
                amount,
                shares,
                amount_per_share,
                commission,
                memo,
                transaction_id,
            ),
        )
        db.commit()

        return jsonify({"updated": 1})

    @app.delete("/api/transactions/<int:transaction_id>")
    def delete_transaction(transaction_id):
        db = get_db()
        cursor = db.execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))
        db.commit()
        if cursor.rowcount == 0:
            return jsonify({"error": "Transaction not found"}), 404
        return jsonify({"deleted": 1})

    @app.post("/api/transactions/delete-many")
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

        placeholders = ",".join("?" for _ in normalized_ids)
        db = get_db()
        cursor = db.execute(
            f"DELETE FROM transactions WHERE id IN ({placeholders})",
            normalized_ids,
        )
        db.commit()

        return jsonify({"deleted": cursor.rowcount})

    @app.get("/api/ledger")
    def get_ledger():
        security = request.args.get("security", "").strip()
        if not security:
            return jsonify({"error": "security query parameter is required"}), 400

        db = get_db()
        rows = db.execute(
            """
            SELECT *
            FROM transactions
            WHERE security = ?
            ORDER BY trade_date, id
            """,
            (security,),
        ).fetchall()

        ledger = calculate_ledger_rows(rows)
        return jsonify(ledger)

    @app.get("/api/securities")
    def list_securities():
        db = get_db()
        securities = db.execute(
            "SELECT DISTINCT security FROM transactions ORDER BY security"
        ).fetchall()

        result = []
        for sec in securities:
            security = sec["security"]
            rows = db.execute(
                """
                SELECT *
                FROM transactions
                WHERE security = ?
                ORDER BY trade_date, id
                """,
                (security,),
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

    @app.get("/api/accounts/dashboard")
    def accounts_dashboard():
        db = get_db()
        latest_row = db.execute(
            "SELECT MAX(as_of) AS as_of FROM holdings_snapshots"
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
            WHERE as_of = ?
            GROUP BY account_name, account_type, account_classification, account_number
            ORDER BY market_value DESC, account_name
            """,
            (latest_as_of,),
        ).fetchall()

        account_types = db.execute(
            """
            SELECT
                COALESCE(NULLIF(account_type, ''), 'Unknown') AS account_type,
                ROUND(SUM(market_value), 4) AS market_value
            FROM holdings_snapshots
            WHERE as_of = ?
            GROUP BY COALESCE(NULLIF(account_type, ''), 'Unknown')
            ORDER BY market_value DESC
            """,
            (latest_as_of,),
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
            WHERE as_of = ?
            GROUP BY symbol
            ORDER BY market_value DESC, symbol
            LIMIT 12
            """,
            (latest_as_of,),
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
            WHERE as_of = ?
            GROUP BY symbol
            ORDER BY market_value DESC, symbol
            """,
            (latest_as_of,),
        ).fetchall()

        holdings_security_account_types = db.execute(
            """
            SELECT
                symbol,
                COALESCE(NULLIF(account_type, ''), 'Unknown') AS account_type,
                ROUND(SUM(market_value), 4) AS market_value
            FROM holdings_snapshots
            WHERE as_of = ?
            GROUP BY symbol, COALESCE(NULLIF(account_type, ''), 'Unknown')
            ORDER BY symbol, market_value DESC, account_type
            """,
            (latest_as_of,),
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
            WHERE as_of = ?
            GROUP BY symbol
            HAVING SUM(market_value) > 0
            ORDER BY market_value DESC, symbol
            """,
            (latest_as_of,),
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

    @app.put("/api/accounts/cash")
    def upsert_cash_account():
        payload = request.get_json(force=True)
        as_of = str(payload.get("as_of") or "").strip()

        db = get_db()

        if not as_of:
            latest_row = db.execute(
                "SELECT MAX(as_of) AS as_of FROM holdings_snapshots"
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
                WHERE as_of = ? AND account_number = ? AND symbol = 'CASH'
                """,
                (as_of, CASH_ACCOUNT_NUMBER),
            )
            db.commit()
            return jsonify({"updated": 1, "as_of": as_of, "account_number": CASH_ACCOUNT_NUMBER, "cash": 0.0})

        db.execute(
            """
            INSERT INTO holdings_snapshots (
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
            ) VALUES (?, 'Cash Account', 'Cash', 'Cash', ?, 'CASH', '', '', 'Cash', 'Cash', ?, ?, 'CAD', ?, ?, 'CAD', 0, 'manual_cash_entry')
            ON CONFLICT(as_of, account_number, symbol)
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

    @app.get("/api/net-worth")
    def list_net_worth_entries():
        db = get_db()
        rows = db.execute(
            """
            SELECT id, entry_date, amount, COALESCE(note, '') AS note
            FROM net_worth_history
            ORDER BY entry_date ASC, id ASC
            """
        ).fetchall()
        return jsonify([dict(row) for row in rows])

    @app.post("/api/net-worth")
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

        db = get_db()
        try:
            cursor = db.execute(
                """
                INSERT INTO net_worth_history (entry_date, amount, note)
                VALUES (?, ?, ?)
                """,
                (entry_date, amount, note),
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            return jsonify({"error": f"Failed to create net worth entry: {exc}"}), 400

        created = db.execute(
            """
            SELECT id, entry_date, amount, COALESCE(note, '') AS note
            FROM net_worth_history
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()
        return jsonify(dict(created)), 201

    @app.put("/api/net-worth/<int:entry_id>")
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

        db = get_db()
        existing = db.execute(
            "SELECT id FROM net_worth_history WHERE id = ?", (entry_id,)
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
                """,
                (entry_date, amount, note, entry_id),
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            return jsonify({"error": f"Failed to update net worth entry: {exc}"}), 400

        updated = db.execute(
            """
            SELECT id, entry_date, amount, COALESCE(note, '') AS note
            FROM net_worth_history
            WHERE id = ?
            """,
            (entry_id,),
        ).fetchone()
        return jsonify(dict(updated))

    @app.delete("/api/net-worth/<int:entry_id>")
    def delete_net_worth_entry(entry_id):
        db = get_db()
        cursor = db.execute("DELETE FROM net_worth_history WHERE id = ?", (entry_id,))
        db.commit()
        if cursor.rowcount == 0:
            return jsonify({"error": "Net worth entry not found"}), 404
        return jsonify({"deleted": 1})

    @app.get("/api/credit-card/dashboard")
    def credit_card_dashboard():
        provider = str(request.args.get("provider") or "rogers_bank").strip()
        db = get_db()

        summary_row = db.execute(
            """
            SELECT
                ROUND(COALESCE(SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END), 0), 2) AS total_expenses,
                COUNT(CASE WHEN amount > 0 THEN 1 END) AS transactions
            FROM credit_card_transactions
                        WHERE provider = ?
                            AND is_hidden = 0
            """,
            (provider,),
        ).fetchone()

        monthly = db.execute(
            """
            SELECT
                SUBSTR(transaction_date, 1, 7) AS month,
                ROUND(SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END), 2) AS expenses
            FROM credit_card_transactions
                        WHERE provider = ?
                            AND is_hidden = 0
            GROUP BY SUBSTR(transaction_date, 1, 7)
            ORDER BY month
            """,
            (provider,),
        ).fetchall()

        categories = db.execute(
            """
            SELECT
                COALESCE(NULLIF(merchant_category, ''), 'Uncategorized') AS merchant_category,
                ROUND(SUM(amount), 2) AS amount,
                COUNT(*) AS transaction_count,
                ROUND(AVG(amount), 2) AS average_amount
            FROM credit_card_transactions
                        WHERE provider = ?
                            AND is_hidden = 0
                            AND amount > 0
            GROUP BY COALESCE(NULLIF(merchant_category, ''), 'Uncategorized')
            """,
            (provider,),
        ).fetchall()

        category_totals = defaultdict(lambda: {"amount": 0.0, "transaction_count": 0})
        for row in categories:
            normalized_category = normalize_credit_card_category(row["merchant_category"])
            category_totals[normalized_category]["amount"] += float(row["amount"] or 0)
            category_totals[normalized_category]["transaction_count"] += int(
                row["transaction_count"] or 0
            )

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
        normalized_categories = normalized_categories[:10]

        merchants = db.execute(
            """
            SELECT
                COALESCE(NULLIF(merchant_name, ''), 'Unknown Merchant') AS merchant_name,
                ROUND(SUM(amount), 2) AS amount,
                COUNT(*) AS transaction_count,
                ROUND(AVG(amount), 2) AS average_amount
            FROM credit_card_transactions
                        WHERE provider = ?
                            AND is_hidden = 0
                            AND amount > 0
            GROUP BY COALESCE(NULLIF(merchant_name, ''), 'Unknown Merchant')
            ORDER BY amount DESC
            LIMIT 12
            """,
            (provider,),
        ).fetchall()

        recent = db.execute(
            """
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
                        WHERE provider = ?
                            AND is_hidden = 0
                            AND amount > 0
            ORDER BY transaction_date DESC, id DESC
            LIMIT 80
            """,
            (provider,),
        ).fetchall()
        recent_rows = []
        for row in recent:
            mapped = dict(row)
            mapped["merchant_category"] = normalize_credit_card_category(
                mapped.get("merchant_category", "")
            )
            recent_rows.append(mapped)

        latest_row = db.execute(
            """
            SELECT MAX(transaction_date) AS latest_transaction_date
            FROM credit_card_transactions
                        WHERE provider = ?
                            AND is_hidden = 0
                            AND amount > 0
            """,
            (provider,),
        ).fetchone()

        return jsonify(
            {
                "provider": provider,
                "latest_transaction_date": latest_row["latest_transaction_date"] if latest_row else None,
                "summary": dict(summary_row) if summary_row else {
                    "total_expenses": 0,
                    "transactions": 0,
                },
                "monthly": [dict(row) for row in monthly],
                "categories": normalized_categories,
                "top_merchants": [dict(row) for row in merchants],
                "recent": recent_rows,
            }
        )

    @app.get("/api/credit-card/categories")
    def credit_card_categories():
        provider = str(request.args.get("provider") or "rogers_bank").strip()
        db = get_db()
        rows = db.execute(
            """
            SELECT DISTINCT COALESCE(NULLIF(merchant_category, ''), 'Uncategorized') AS merchant_category
            FROM credit_card_transactions
            WHERE provider = ?
              AND is_hidden = 0
            ORDER BY merchant_category ASC
            """,
            (provider,),
        ).fetchall()
        categories = sorted(
            {
                normalize_credit_card_category(row["merchant_category"])
                for row in rows
                if row["merchant_category"] is not None
            }
        )
        return jsonify(categories)

    @app.get("/api/credit-card/transactions")
    def credit_card_transactions():
        provider = str(request.args.get("provider") or "rogers_bank").strip()
        start_date = str(request.args.get("start_date") or "").strip()
        end_date = str(request.args.get("end_date") or "").strip()
        category = str(request.args.get("category") or "").strip()
        merchant = str(request.args.get("merchant") or "").strip()
        include_payments = str(request.args.get("include_payments") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        include_hidden = str(request.args.get("include_hidden") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        try:
            limit = int(request.args.get("limit") or 300)
        except ValueError:
            return jsonify({"error": "limit must be an integer"}), 400
        limit = min(max(limit, 1), 1000)

        clauses = ["provider = ?"]
        params = [provider]

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
            if category and mapped["merchant_category"] != category:
                continue
            normalized_rows.append(mapped)
            if len(normalized_rows) >= limit:
                break

        return jsonify(normalized_rows)

    @app.patch("/api/credit-card/transactions/<int:transaction_id>/hidden")
    def set_credit_card_transaction_hidden(transaction_id):
        payload = request.get_json(force=True)
        provider = str(payload.get("provider") or "rogers_bank").strip()
        hidden = bool(payload.get("hidden", True))

        db = get_db()
        cursor = db.execute(
            """
            UPDATE credit_card_transactions
            SET is_hidden = ?
            WHERE id = ?
              AND provider = ?
            """,
            (1 if hidden else 0, transaction_id, provider),
        )
        db.commit()
        if cursor.rowcount == 0:
            return jsonify({"error": "Credit card transaction not found"}), 404
        return jsonify({"updated": 1, "hidden": hidden})

    @app.post("/api/credit-card/transactions/hide-many")
    def set_many_credit_card_transactions_hidden():
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
            f"UPDATE credit_card_transactions SET is_hidden = ? WHERE provider = ? AND id IN ({placeholders})",
            [1 if hidden else 0, provider, *normalized_ids],
        )
        db.commit()

        return jsonify({"updated": cursor.rowcount, "hidden": hidden})

    @app.delete("/api/credit-card/transactions/<int:transaction_id>")
    def delete_credit_card_transaction(transaction_id):
        provider = str(request.args.get("provider") or "rogers_bank").strip()
        db = get_db()
        cursor = db.execute(
            "DELETE FROM credit_card_transactions WHERE id = ? AND provider = ?",
            (transaction_id, provider),
        )
        db.commit()
        if cursor.rowcount == 0:
            return jsonify({"error": "Credit card transaction not found"}), 404
        return jsonify({"deleted": 1})

    @app.post("/api/credit-card/transactions/delete-many")
    def delete_many_credit_card_transactions():
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
            f"DELETE FROM credit_card_transactions WHERE provider = ? AND id IN ({placeholders})",
            [provider, *normalized_ids],
        )
        db.commit()

        return jsonify({"deleted": cursor.rowcount})

    @app.delete("/api/credit-card/transactions")
    def delete_all_credit_card_transactions():
        provider = str(request.args.get("provider") or "rogers_bank").strip()
        db = get_db()
        cursor = db.execute(
            "DELETE FROM credit_card_transactions WHERE provider = ?",
            (provider,),
        )
        db.commit()
        return jsonify({"deleted": cursor.rowcount})

    @app.post("/api/import-csv")
    def import_csv():
        if "file" not in request.files:
            return jsonify({"error": "Missing file upload field: file"}), 400

        uploaded_file = request.files["file"]
        if uploaded_file.filename == "":
            return jsonify({"error": "No selected file"}), 400

        file_text = uploaded_file.read().decode("utf-8-sig")
        parsed_rows = parse_adjustedcostbase_csv_text(file_text)
        summary = import_transactions_rows(parsed_rows)
        return jsonify(summary)

    @app.post("/api/import/holdings-csv")
    def import_holdings_csv():
        if "file" not in request.files:
            return jsonify({"error": "Missing file upload field: file"}), 400

        uploaded_file = request.files["file"]
        if uploaded_file.filename == "":
            return jsonify({"error": "No selected file"}), 400

        file_text = uploaded_file.read().decode("utf-8-sig")
        parsed_rows = parse_holdings_csv_text(file_text, filename=uploaded_file.filename)
        if not parsed_rows:
            return jsonify({"error": "No holdings rows found in uploaded CSV"}), 400

        summary = import_holdings_rows(parsed_rows, source_filename=uploaded_file.filename)
        return jsonify(summary)

    @app.post("/api/import/credit-card/rogers-csv")
    def import_rogers_credit_csv():
        if "file" not in request.files:
            return jsonify({"error": "Missing file upload field: file"}), 400

        uploaded_files = [file for file in request.files.getlist("file") if file and file.filename]
        if not uploaded_files:
            return jsonify({"error": "No selected file"}), 400

        total_parsed = 0
        total_inserted = 0
        files_processed = 0

        for uploaded_file in uploaded_files:
            file_text = uploaded_file.read().decode("utf-8-sig")
            parsed_rows = parse_rogers_credit_csv_text(file_text)
            if not parsed_rows:
                continue

            summary = import_rogers_credit_rows(parsed_rows, source_filename=uploaded_file.filename)
            total_parsed += int(summary.get("parsed") or 0)
            total_inserted += int(summary.get("inserted") or 0)
            files_processed += 1

        if total_parsed == 0:
            return jsonify({"error": "No credit card rows found in uploaded CSV file(s)"}), 400

        return jsonify(
            {
                "parsed": total_parsed,
                "inserted": total_inserted,
                "files": files_processed,
            }
        )

    @app.post("/api/import/review")
    def create_import_review():
        if "file" not in request.files:
            return jsonify({"error": "Missing file upload field: file"}), 400

        import_type = str(request.form.get("import_type") or "").strip()
        if import_type not in SUPPORTED_IMPORT_TYPES:
            return jsonify({"error": "Unsupported import_type"}), 400

        uploaded_file = request.files["file"]
        if uploaded_file.filename == "":
            return jsonify({"error": "No selected file"}), 400

        file_bytes = uploaded_file.read()
        try:
            rows = parse_upload(import_type, uploaded_file.filename, file_bytes)
        except Exception as exc:
            return jsonify({"error": f"Failed to parse import file: {exc}"}), 400

        if not rows:
            return jsonify({"error": "No importable transactions found in file"}), 400

        batch_id = create_import_batch(import_type, uploaded_file.filename, rows)
        batch_data = get_batch(batch_id)
        return jsonify(batch_data), 201

    @app.get("/api/import/review/<int:batch_id>")
    def get_import_review(batch_id):
        batch_data = get_batch(batch_id)
        if not batch_data:
            return jsonify({"error": "Import batch not found"}), 404
        return jsonify(batch_data)

    @app.put("/api/import/review/<int:batch_id>/rows/<int:row_id>")
    def update_import_review_row(batch_id, row_id):
        payload = request.get_json(force=True)
        try:
            ok = update_batch_row(batch_id, row_id, payload)
        except Exception as exc:
            return jsonify({"error": f"Invalid row data: {exc}"}), 400

        if not ok:
            return jsonify({"error": "Import row not found"}), 404

        return jsonify({"updated": 1})

    @app.delete("/api/import/review/<int:batch_id>/rows/<int:row_id>")
    def delete_import_review_row(batch_id, row_id):
        ok = delete_batch_row(batch_id, row_id)
        if not ok:
            return jsonify({"error": "Import row not found"}), 404
        return jsonify({"deleted": 1})

    @app.post("/api/import/review/<int:batch_id>/commit")
    def commit_import_review(batch_id):
        summary = commit_batch(batch_id)
        if summary is None:
            return jsonify({"error": "Import batch not found"}), 404
        return jsonify(summary)

    @app.get("/api/transaction-types")
    def list_transaction_types():
        return jsonify(sorted(SUPPORTED_TRANSACTION_TYPES))

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
