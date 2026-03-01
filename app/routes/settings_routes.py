from flask import Blueprint, jsonify, request

from ..context import require_user_id
from ..db import get_db
from ..services.settings_service import get_feature_settings, update_feature_settings

bp = Blueprint("settings", __name__)


@bp.get("/api/settings/features")
def get_settings_features():
    user_id = require_user_id()
    db = get_db()
    return jsonify({"features": get_feature_settings(db, user_id)})


@bp.put("/api/settings/features")
def update_settings_features():
    user_id = require_user_id()
    payload = request.get_json(force=True)
    raw_features = payload.get("features") if isinstance(payload, dict) else None

    db = get_db()
    try:
        updated = update_feature_settings(db, user_id, raw_features)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify({"features": updated})
