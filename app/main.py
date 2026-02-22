from pathlib import Path

from flask import Flask, jsonify, render_template, request

from .acb import calculate_ledger_rows
from .db import close_db, get_db, init_db
from .importer import import_transactions_rows, parse_adjustedcostbase_csv_text
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
