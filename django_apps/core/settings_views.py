import json

from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_http_methods

from django_apps.core.services.settings_service import get_feature_settings, update_feature_settings


def _read_json(request):
    try:
        if not request.body:
            return {}
        return json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}


@require_http_methods(["GET", "PUT"])
def settings_features(request):
    if request.method == "GET":
        return get_settings_features(request)
    return update_settings_features(request)


@require_GET
def get_settings_features(request):
    return JsonResponse({"features": get_feature_settings(request.user)})


@require_http_methods(["PUT"])
def update_settings_features(request):
    payload = _read_json(request)
    raw_features = payload.get("features") if isinstance(payload, dict) else None

    try:
        updated = update_feature_settings(request.user, raw_features)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    return JsonResponse({"features": updated})
