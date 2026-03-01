from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from ..context import get_current_user
from ..db import get_db

bp = Blueprint("auth", __name__)


@bp.get("/login")
def login_page():
    if get_current_user():
        return redirect(url_for("pages.index"))
    return render_template("login.html")


@bp.post("/api/auth/register")
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
    created_user_id = int(cursor.lastrowid or 0)

    session.clear()
    session["user_id"] = created_user_id
    session.permanent = True

    return jsonify({"id": created_user_id, "username": username}), 201


@bp.post("/api/auth/login")
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


@bp.post("/api/auth/logout")
def logout_user():
    session.clear()
    return jsonify({"logged_out": True})


@bp.get("/api/auth/me")
def auth_me():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Authentication required"}), 401
    return jsonify({"id": int(user["id"]), "username": user["username"]})
