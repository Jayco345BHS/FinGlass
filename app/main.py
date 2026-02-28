from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta
import os
import shutil
import sqlite3
import tempfile

from flask import (
    Flask,
    after_this_request,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from .acb import calculate_ledger_rows
from .db import DB_PATH, close_db, get_db, init_db
from .credit_card_categories import normalize_credit_card_category
from .importer import (
    import_holdings_rows,
    import_rogers_credit_rows,
    import_transactions_rows,
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
from .market_data import MarketDataError, get_quote

BASE_DIR = Path(__file__).resolve().parent.parent
CASH_ACCOUNT_NUMBER = "__CASH__"
HOLDINGS_SYMBOL_SUFFIXES = (".TO", ".TRT", ".V", ".NE")
SUPPORTED_TRANSACTION_TYPES = {
    "Buy",
    "Sell",
    "Return of Capital",
    "Capital Gains Dividend",
    "Reinvested Dividend",
    "Reinvested Capital Gains Distribution",
    "Split",
}
DEFAULT_FEATURE_SETTINGS = {
    "imports": True,
    "holdings_overview": True,
    "acb_tracker": True,
    "net_worth": True,
    "credit_card": True,
}


def normalize_holding_symbol(symbol):
    value = str(symbol or "").strip().upper()
    if not value:
        return ""
    for suffix in HOLDINGS_SYMBOL_SUFFIXES:
        if value.endswith(suffix) and len(value) > len(suffix):
            return value[: -len(suffix)]
    return value


def derive_account_number(account_name):
    normalized = "".join(ch for ch in str(account_name or "").upper() if ch.isalnum())
    if not normalized:
        return "__ACCOUNT__"
    return f"__ACCOUNT__{normalized}"


def parse_setting_bool(value):
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    return normalized in {"1", "true", "yes", "on"}


def get_feature_settings(db, user_id):
    settings = dict(DEFAULT_FEATURE_SETTINGS)
    rows = db.execute(
        """
        SELECT key, value
        FROM app_settings
    WHERE user_id = ?
      AND key LIKE 'feature.%'
    """,
    (user_id,),
    ).fetchall()
    for row in rows:
        key = str(row["key"] or "")
        feature = key.removeprefix("feature.")
        if feature in settings:
            settings[feature] = parse_setting_bool(row["value"])
    return settings


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = (
        os.environ.get("FLASK_SECRET_KEY")
        or os.environ.get("SECRET_KEY")
        or "finglass-dev-secret-change-me"
    )
    app.permanent_session_lifetime = timedelta(days=30)

    init_db()
    app.teardown_appcontext(close_db)

    def get_current_user():
        user_id = session.get("user_id")
        if not user_id:
            return None

        db = get_db()
        row = db.execute(
            "SELECT id, username FROM users WHERE id = ? AND is_active = 1",
            (int(user_id),),
        ).fetchone()
        if not row:
            session.clear()
            return None
        return dict(row)

    def require_user_id():
        user = get_current_user()
        if not user:
            return None
        return int(user["id"])

    @app.before_request
    def require_authentication():
        path = request.path or ""
        if path.startswith("/static/"):
            return None
        if path in {"/login", "/api/auth/login", "/api/auth/register"}:
            return None

        if get_current_user():
            return None

        if path.startswith("/api/"):
            return jsonify({"error": "Authentication required"}), 401
        return redirect(url_for("login_page"))

    @app.get("/login")
    def login_page():
        if get_current_user():
            return redirect(url_for("index"))
        return render_template("login.html")

    @app.post("/api/auth/register")
    def register_user():
        payload = request.get_json(force=True)
        username = str(payload.get("username") or "").strip()
        password = str(payload.get("password") or "")

        if not username:
            return jsonify({"error": "username is required"}), 400
        if len(password) < 8:
            return jsonify({"error": "password must be at least 8 characters"}), 400

        db = get_db()
        existing = db.execute(
            "SELECT id FROM users WHERE username = ? COLLATE NOCASE",
            (username,),
        ).fetchone()
        if existing:
            return jsonify({"error": "username already exists"}), 409

        cursor = db.execute(
            """
            INSERT INTO users (username, password_hash, is_active)
            VALUES (?, ?, 1)
            """,
            (username, generate_password_hash(password)),
        )
        db.commit()

        session.clear()
        session["user_id"] = int(cursor.lastrowid)
        session.permanent = True

        return jsonify({"id": int(cursor.lastrowid), "username": username}), 201

    @app.post("/api/auth/login")
    def login_user():
        payload = request.get_json(force=True)
        username = str(payload.get("username") or "").strip()
        password = str(payload.get("password") or "")

        if not username or not password:
            return jsonify({"error": "username and password are required"}), 400

        db = get_db()
        row = db.execute(
            "SELECT id, username, password_hash, is_active FROM users WHERE username = ? COLLATE NOCASE",
            (username,),
        ).fetchone()
        if not row or not row["is_active"]:
            return jsonify({"error": "Invalid username or password"}), 401
        if not check_password_hash(row["password_hash"], password):
            return jsonify({"error": "Invalid username or password"}), 401

        session.clear()
        session["user_id"] = int(row["id"])
        session.permanent = True

        return jsonify({"id": int(row["id"]), "username": row["username"]})

    @app.post("/api/auth/logout")
    def logout_user():
        session.clear()
        return jsonify({"logged_out": True})

    @app.get("/api/auth/me")
    def auth_me():
        user = get_current_user()
        if not user:
            return jsonify({"error": "Authentication required"}), 401
        return jsonify({"id": int(user["id"]), "username": user["username"]})

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/security/<security>")
    def security_detail(security):
        user_id = require_user_id()
        settings = get_feature_settings(get_db(), user_id)
        if not settings.get("acb_tracker", True):
            return jsonify({"error": "ACB tracker is disabled in settings"}), 403
        return render_template("security.html", security=security.upper())

    @app.get("/acb")
    def acb_detail():
        user_id = require_user_id()
        settings = get_feature_settings(get_db(), user_id)
        if not settings.get("acb_tracker", True):
            return jsonify({"error": "ACB tracker is disabled in settings"}), 403
        return render_template("acb.html")

    @app.get("/credit-card")
    def credit_card_detail():
        user_id = require_user_id()
        settings = get_feature_settings(get_db(), user_id)
        if not settings.get("credit_card", True):
            return jsonify({"error": "Credit card feature is disabled in settings"}), 403
        provider = str(request.args.get("provider") or "rogers_bank").strip() or "rogers_bank"
        return render_template("credit_card.html", provider=provider)

    @app.get("/net-worth")
    def net_worth_detail():
        user_id = require_user_id()
        settings = get_feature_settings(get_db(), user_id)
        if not settings.get("net_worth", True):
            return jsonify({"error": "Net worth tracker is disabled in settings"}), 403
        return render_template("net_worth.html")

    @app.get("/holdings")
    def holdings_detail():
        user_id = require_user_id()
        settings = get_feature_settings(get_db(), user_id)
        if not settings.get("holdings_overview", True):
            return jsonify({"error": "Holdings overview is disabled in settings"}), 403
        return render_template("holdings.html")

    @app.get("/api/transactions")
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
                security,
                trade_date,
                transaction_type,
                amount,
                shares,
                amount_per_share,
                commission,
                memo,
                transaction_id,
                user_id,
            ),
        )
        db.commit()

        return jsonify({"updated": 1})

    @app.delete("/api/transactions/<int:transaction_id>")
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

        user_id = require_user_id()
        placeholders = ",".join("?" for _ in normalized_ids)
        db = get_db()
        cursor = db.execute(
            f"DELETE FROM transactions WHERE user_id = ? AND id IN ({placeholders})",
            [user_id, *normalized_ids],
        )
        db.commit()

        return jsonify({"deleted": cursor.rowcount})

    @app.get("/api/ledger")
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

    @app.get("/api/securities")
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

    @app.get("/api/accounts/dashboard")
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

    @app.put("/api/accounts/cash")
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

    @app.get("/api/holdings")
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

    @app.post("/api/holdings")
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

        as_of = str(payload.get("as_of") or "").strip()
        if as_of:
            try:
                as_of = datetime.strptime(as_of, "%Y-%m-%d").strftime("%Y-%m-%d")
            except ValueError:
                return jsonify({"error": "as_of must be YYYY-MM-DD"}), 400
        else:
            latest_row = db.execute(
                "SELECT MAX(as_of) AS as_of FROM holdings_snapshots WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            as_of = latest_row["as_of"] if latest_row and latest_row["as_of"] else datetime.now().strftime("%Y-%m-%d")

        def parse_float(field_name):
            value = payload.get(field_name, 0)
            try:
                return float(value or 0)
            except (TypeError, ValueError):
                raise ValueError(f"{field_name} must be a number")

        try:
            quantity = parse_float("quantity")
            book_value_cad = parse_float("book_value_cad")
            market_value = parse_float("market_value")
            if "unrealized_return" in payload:
                unrealized_return = parse_float("unrealized_return")
            else:
                unrealized_return = market_value - book_value_cad
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

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

    @app.put("/api/holdings/<int:holding_id>")
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

        def parse_float(field_name, default_value):
            value = payload.get(field_name, default_value)
            try:
                return float(value or 0)
            except (TypeError, ValueError):
                raise ValueError(f"{field_name} must be a number")

        try:
            quantity = parse_float("quantity", 0)
            book_value_cad = parse_float("book_value_cad", 0)
            market_value = parse_float("market_value", 0)
            if "unrealized_return" in payload:
                unrealized_return = parse_float("unrealized_return", 0)
            else:
                unrealized_return = market_value - book_value_cad
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

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

    @app.delete("/api/holdings/<int:holding_id>")
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

    @app.get("/api/market-data/quote")
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

    @app.post("/api/holdings/refresh-market-values")
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

    @app.get("/api/net-worth")
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

    def parse_credit_card_category_filters():
        requested_categories = []
        for raw_value in request.args.getlist("category"):
            for part in str(raw_value or "").split(","):
                normalized_part = part.strip()
                if normalized_part:
                    requested_categories.append(normalized_part)

        return {
            normalize_credit_card_category(category)
            for category in requested_categories
            if str(category or "").strip()
        }

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

    @app.delete("/api/net-worth/<int:entry_id>")
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

    @app.get("/api/credit-card/dashboard")
    def credit_card_dashboard():
        user_id = require_user_id()
        provider = str(request.args.get("provider") or "rogers_bank").strip()
        start_date = str(request.args.get("start_date") or "").strip()
        end_date = str(request.args.get("end_date") or "").strip()
        merchant = str(request.args.get("merchant") or "").strip()
        include_hidden = str(request.args.get("include_hidden") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        selected_categories = parse_credit_card_category_filters()

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

    @app.get("/api/credit-card/categories")
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

    @app.get("/api/credit-card/transactions")
    def credit_card_transactions():
        user_id = require_user_id()
        provider = str(request.args.get("provider") or "rogers_bank").strip()
        start_date = str(request.args.get("start_date") or "").strip()
        end_date = str(request.args.get("end_date") or "").strip()
        selected_categories = parse_credit_card_category_filters()
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

    @app.patch("/api/credit-card/transactions/<int:transaction_id>/hidden")
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

    @app.post("/api/credit-card/transactions/hide-many")
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

    @app.delete("/api/credit-card/transactions/<int:transaction_id>")
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

    @app.post("/api/credit-card/transactions/delete-many")
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

    @app.delete("/api/credit-card/transactions")
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

    @app.get("/api/db/export")
    def export_database_file():
        user_id = require_user_id()
        if not DB_PATH.exists():
            init_db()

        data_dir = DB_PATH.parent
        data_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.NamedTemporaryFile(
            suffix=".sqlite3",
            prefix=f"finglass-export-user-{user_id}-",
            dir=data_dir,
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)

        shutil.copy2(DB_PATH, temp_path)

        export_conn = sqlite3.connect(temp_path)
        export_cursor = export_conn.cursor()
        export_cursor.execute("PRAGMA foreign_keys = OFF")

        export_cursor.execute(
            "DELETE FROM import_batch_rows WHERE batch_id IN (SELECT id FROM import_batches WHERE user_id != ?)",
            (user_id,),
        )

        user_scoped_tables = [
            "transactions",
            "import_batches",
            "holdings_snapshots",
            "net_worth_history",
            "credit_card_transactions",
            "app_settings",
        ]
        for table_name in user_scoped_tables:
            export_cursor.execute(f"DELETE FROM {table_name} WHERE user_id != ?", (user_id,))

        export_cursor.execute("DELETE FROM users WHERE id != ?", (user_id,))
        export_conn.commit()
        export_conn.close()

        @after_this_request
        def cleanup_temp_export(response):
            temp_path.unlink(missing_ok=True)
            return response

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"finglass-user-{user_id}-backup-{timestamp}.sqlite3"
        return send_file(
            temp_path,
            as_attachment=True,
            download_name=filename,
            mimetype="application/x-sqlite3",
        )

    @app.post("/api/db/import")
    def import_database_file():
        current_user_id = None
        current_user_record = None
        current_user = get_current_user()
        if current_user:
            current_user_id = int(current_user["id"])
            existing_db = get_db()
            current_user_record = existing_db.execute(
                """
                SELECT id, username, password_hash, is_active,
                       COALESCE(auth_provider, 'local') AS auth_provider,
                       external_subject
                FROM users
                WHERE id = ?
                """,
                (current_user_id,),
            ).fetchone()

        if "file" not in request.files:
            return jsonify({"error": "Missing file upload field: file"}), 400

        uploaded_file = request.files["file"]
        if uploaded_file.filename == "":
            return jsonify({"error": "No selected file"}), 400

        data_dir = DB_PATH.parent
        data_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.NamedTemporaryFile(
            suffix=".sqlite3",
            prefix="finglass-import-",
            dir=data_dir,
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            uploaded_file.save(temp_file)

        try:
            validation_conn = sqlite3.connect(temp_path)
            try:
                table_rows = validation_conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            finally:
                validation_conn.close()

            if not table_rows:
                return jsonify({"error": "Uploaded file is not a valid SQLite database"}), 400

            close_db()

            if DB_PATH.exists():
                backup_name = f"finglass-pre-restore-{datetime.now().strftime('%Y%m%d-%H%M%S')}.sqlite3"
                backup_path = data_dir / backup_name
                shutil.copy2(DB_PATH, backup_path)

            os.replace(temp_path, DB_PATH)
            init_db()

            if current_user_id is not None:
                db = get_db()

                if current_user_record:
                    db.execute(
                        """
                        INSERT INTO users (id, username, password_hash, auth_provider, external_subject, is_active, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(id) DO UPDATE SET
                            username = excluded.username,
                            password_hash = excluded.password_hash,
                            auth_provider = excluded.auth_provider,
                            external_subject = excluded.external_subject,
                            is_active = excluded.is_active,
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        (
                            current_user_record["id"],
                            current_user_record["username"],
                            current_user_record["password_hash"],
                            current_user_record["auth_provider"],
                            current_user_record["external_subject"],
                            current_user_record["is_active"],
                        ),
                    )

                user_owned_tables = [
                    "transactions",
                    "import_batches",
                    "holdings_snapshots",
                    "net_worth_history",
                    "credit_card_transactions",
                    "app_settings",
                ]

                for table_name in user_owned_tables:
                    columns = {
                        row["name"]
                        for row in db.execute(f"PRAGMA table_info({table_name})").fetchall()
                    }
                    if "user_id" not in columns:
                        continue
                    db.execute(
                        f"UPDATE OR IGNORE {table_name} SET user_id = ? WHERE user_id = 0",
                        (current_user_id,),
                    )

                db.commit()
        except sqlite3.DatabaseError:
            return jsonify({"error": "Uploaded file is not a valid SQLite database"}), 400
        except Exception as exc:
            return jsonify({"error": f"Failed to import database: {exc}"}), 500
        finally:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)

        return jsonify({"imported": True, "overwritten": True})

    @app.post("/api/import/holdings-csv")
    def import_holdings_csv():
        user_id = require_user_id()
        if "file" not in request.files:
            return jsonify({"error": "Missing file upload field: file"}), 400

        uploaded_file = request.files["file"]
        if uploaded_file.filename == "":
            return jsonify({"error": "No selected file"}), 400

        file_text = uploaded_file.read().decode("utf-8-sig")
        parsed_rows = parse_holdings_csv_text(file_text, filename=uploaded_file.filename)
        if not parsed_rows:
            return jsonify({"error": "No holdings rows found in uploaded CSV"}), 400

        summary = import_holdings_rows(
            parsed_rows,
            source_filename=uploaded_file.filename,
            user_id=user_id,
        )
        return jsonify(summary)

    @app.post("/api/import/credit-card/rogers-csv")
    def import_rogers_credit_csv():
        user_id = require_user_id()
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

            summary = import_rogers_credit_rows(
                parsed_rows,
                source_filename=uploaded_file.filename,
                user_id=user_id,
            )
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
        user_id = require_user_id()
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

        batch_id = create_import_batch(import_type, uploaded_file.filename, rows, user_id=user_id)
        batch_data = get_batch(batch_id, user_id=user_id)
        return jsonify(batch_data), 201

    @app.get("/api/import/review/<int:batch_id>")
    def get_import_review(batch_id):
        user_id = require_user_id()
        batch_data = get_batch(batch_id, user_id=user_id)
        if not batch_data:
            return jsonify({"error": "Import batch not found"}), 404
        return jsonify(batch_data)

    @app.put("/api/import/review/<int:batch_id>/rows/<int:row_id>")
    def update_import_review_row(batch_id, row_id):
        user_id = require_user_id()
        payload = request.get_json(force=True)
        try:
            ok = update_batch_row(batch_id, row_id, payload, user_id=user_id)
        except Exception as exc:
            return jsonify({"error": f"Invalid row data: {exc}"}), 400

        if not ok:
            return jsonify({"error": "Import row not found"}), 404

        return jsonify({"updated": 1})

    @app.delete("/api/import/review/<int:batch_id>/rows/<int:row_id>")
    def delete_import_review_row(batch_id, row_id):
        user_id = require_user_id()
        ok = delete_batch_row(batch_id, row_id, user_id=user_id)
        if not ok:
            return jsonify({"error": "Import row not found"}), 404
        return jsonify({"deleted": 1})

    @app.post("/api/import/review/<int:batch_id>/commit")
    def commit_import_review(batch_id):
        user_id = require_user_id()
        summary = commit_batch(batch_id, user_id=user_id)
        if summary is None:
            return jsonify({"error": "Import batch not found"}), 404
        return jsonify(summary)

    @app.get("/api/transaction-types")
    def list_transaction_types():
        return jsonify(sorted(SUPPORTED_TRANSACTION_TYPES))

    @app.get("/api/settings/features")
    def get_settings_features():
        user_id = require_user_id()
        db = get_db()
        return jsonify({"features": get_feature_settings(db, user_id)})

    @app.put("/api/settings/features")
    def update_settings_features():
        user_id = require_user_id()
        payload = request.get_json(force=True)
        raw_features = payload.get("features") if isinstance(payload, dict) else None
        if not isinstance(raw_features, dict):
            return jsonify({"error": "features object is required"}), 400

        db = get_db()
        current = get_feature_settings(db, user_id)

        for feature, value in raw_features.items():
            if feature not in DEFAULT_FEATURE_SETTINGS:
                return jsonify({"error": f"Unsupported feature: {feature}"}), 400
            current[feature] = parse_setting_bool(value)

        for feature, enabled in current.items():
            db.execute(
                """
                INSERT INTO app_settings (user_id, key, value, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id, key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, f"feature.{feature}", "1" if enabled else "0"),
            )
        db.commit()

        return jsonify({"features": current})

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
