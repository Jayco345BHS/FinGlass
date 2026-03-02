from flask import Blueprint, jsonify, render_template, request

from ..context import require_user_id
from ..db import get_db
from ..services.settings_service import get_feature_settings

bp = Blueprint("pages", __name__)


@bp.get("/")
def index():
    return render_template("index.html")


@bp.get("/security/<security>")
def security_detail(security):
    user_id = require_user_id()
    settings = get_feature_settings(get_db(), user_id)
    if not settings.get("acb_tracker", True):
        return jsonify({"error": "ACB tracker is disabled in settings"}), 403
    return render_template("security.html", security=security.upper())


@bp.get("/acb")
def acb_detail():
    user_id = require_user_id()
    settings = get_feature_settings(get_db(), user_id)
    if not settings.get("acb_tracker", True):
        return jsonify({"error": "ACB tracker is disabled in settings"}), 403
    return render_template("acb.html")


@bp.get("/credit-card")
def credit_card_detail():
    user_id = require_user_id()
    settings = get_feature_settings(get_db(), user_id)
    if not settings.get("credit_card", True):
        return jsonify({"error": "Credit card feature is disabled in settings"}), 403
    provider = str(request.args.get("provider") or "rogers_bank").strip() or "rogers_bank"
    return render_template("credit_card.html", provider=provider)


@bp.get("/net-worth")
def net_worth_detail():
    user_id = require_user_id()
    settings = get_feature_settings(get_db(), user_id)
    if not settings.get("net_worth", True):
        return jsonify({"error": "Net worth tracker is disabled in settings"}), 403
    return render_template("net_worth.html")


@bp.get("/tfsa")
def tfsa_detail():
    user_id = require_user_id()
    settings = get_feature_settings(get_db(), user_id)
    if not settings.get("tfsa_tracker", True):
        return jsonify({"error": "TFSA tracker is disabled in settings"}), 403
    return render_template("tfsa.html")


@bp.get("/rrsp")
def rrsp_detail():
    user_id = require_user_id()
    settings = get_feature_settings(get_db(), user_id)
    if not settings.get("rrsp_tracker", True):
        return jsonify({"error": "RRSP tracker is disabled in settings"}), 403
    return render_template("rrsp.html")


@bp.get("/fhsa")
def fhsa_detail():
    user_id = require_user_id()
    settings = get_feature_settings(get_db(), user_id)
    if not settings.get("fhsa_tracker", True):
        return jsonify({"error": "FHSA tracker is disabled in settings"}), 403
    return render_template("fhsa.html")


@bp.get("/import")
def import_wizard():
    require_user_id()
    return render_template("import_wizard.html")


@bp.get("/holdings")
def holdings_detail():
    user_id = require_user_id()
    settings = get_feature_settings(get_db(), user_id)
    if not settings.get("holdings_overview", True):
        return jsonify({"error": "Holdings overview is disabled in settings"}), 403
    return render_template("holdings.html")
