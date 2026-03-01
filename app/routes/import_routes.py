from datetime import datetime
from pathlib import Path
import os
import shutil
import sqlite3
import tempfile

from flask import Blueprint, after_this_request, jsonify, request, send_file

from ..context import get_current_user, require_user_id
from ..db import DB_PATH, close_db, get_db, init_db
from ..importer import (
    import_holdings_rows,
    import_rogers_credit_rows,
    parse_holdings_csv_text,
    parse_rogers_credit_csv_text,
)
from ..staged_imports import (
    SUPPORTED_IMPORT_TYPES,
    commit_batch,
    create_import_batch,
    delete_batch_row,
    get_batch,
    parse_upload,
    update_batch_row,
)

bp = Blueprint("imports", __name__)


REQUIRED_IMPORT_TABLES = {
    "users",
    "transactions",
    "import_batches",
    "import_batch_rows",
    "holdings_snapshots",
    "net_worth_history",
    "credit_card_transactions",
    "app_settings",
}


def _validate_uploaded_database(validation_conn):
    object_rows = validation_conn.execute(
        """
        SELECT type, name
        FROM sqlite_master
        WHERE name NOT LIKE 'sqlite_%'
        """
    ).fetchall()

    if not object_rows:
        raise ValueError("Uploaded file is not a valid SQLite database")

    object_types = {str(row[0] or "").lower() for row in object_rows}
    if "trigger" in object_types or "view" in object_types:
        raise ValueError("Uploaded database contains unsupported objects (views/triggers)")

    if not object_types.issubset({"table", "index"}):
        raise ValueError("Uploaded database contains unsupported schema objects")

    table_names = {
        str(row[1] or "").strip()
        for row in object_rows
        if str(row[0] or "").lower() == "table"
    }
    missing_tables = sorted(REQUIRED_IMPORT_TABLES - table_names)
    if missing_tables:
        raise ValueError("Uploaded database is missing required tables")


@bp.get("/api/db/export")
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


@bp.post("/api/db/import")
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
            _validate_uploaded_database(validation_conn)
        finally:
            validation_conn.close()

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
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except sqlite3.DatabaseError:
        return jsonify({"error": "Uploaded file is not a valid SQLite database"}), 400
    except Exception as exc:
        return jsonify({"error": f"Failed to import database: {exc}"}), 500
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)

    return jsonify({"imported": True, "overwritten": True})


@bp.post("/api/import/holdings-csv")
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


@bp.post("/api/import/credit-card/rogers-csv")
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


@bp.post("/api/import/review")
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


@bp.get("/api/import/review/<int:batch_id>")
def get_import_review(batch_id):
    user_id = require_user_id()
    batch_data = get_batch(batch_id, user_id=user_id)
    if not batch_data:
        return jsonify({"error": "Import batch not found"}), 404
    return jsonify(batch_data)


@bp.put("/api/import/review/<int:batch_id>/rows/<int:row_id>")
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


@bp.delete("/api/import/review/<int:batch_id>/rows/<int:row_id>")
def delete_import_review_row(batch_id, row_id):
    user_id = require_user_id()
    ok = delete_batch_row(batch_id, row_id, user_id=user_id)
    if not ok:
        return jsonify({"error": "Import row not found"}), 404
    return jsonify({"deleted": 1})


@bp.post("/api/import/review/<int:batch_id>/commit")
def commit_import_review(batch_id):
    user_id = require_user_id()
    summary = commit_batch(batch_id, user_id=user_id)
    if summary is None:
        return jsonify({"error": "Import batch not found"}), 404
    return jsonify(summary)
