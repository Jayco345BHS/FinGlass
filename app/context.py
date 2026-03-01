from flask import session

from .db import get_db


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
        raise RuntimeError("Authentication required")
    return int(user["id"])
