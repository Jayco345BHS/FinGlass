from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

from django_apps.core.services.settings_service import get_feature_settings


@ensure_csrf_cookie
def login_page(request):
    return render(request, "login.html")


def index_page(request):
    return render(request, "index.html")


def _feature_enabled(request, feature):
    settings = get_feature_settings(request.user)
    return settings.get(feature, True)


def security_page(request, security):
    if not _feature_enabled(request, "acb_tracker"):
        return JsonResponse({"error": "ACB tracker is disabled in settings"}, status=403)
    return render(request, "security.html", {"security": security})


def acb_page(request):
    if not _feature_enabled(request, "acb_tracker"):
        return JsonResponse({"error": "ACB tracker is disabled in settings"}, status=403)
    return render(request, "acb.html")


def credit_card_page(request):
    if not _feature_enabled(request, "credit_card"):
        return JsonResponse({"error": "Credit card feature is disabled in settings"}, status=403)
    provider = str(request.GET.get("provider") or "rogers_bank").strip() or "rogers_bank"
    return render(request, "credit_card.html", {"provider": provider})


def net_worth_page(request):
    if not _feature_enabled(request, "net_worth"):
        return JsonResponse({"error": "Net worth tracker is disabled in settings"}, status=403)
    return render(request, "net_worth.html")


def tfsa_page(request):
    if not _feature_enabled(request, "tfsa_tracker"):
        return JsonResponse({"error": "TFSA tracker is disabled in settings"}, status=403)
    return render(request, "tfsa.html")


def rrsp_page(request):
    if not _feature_enabled(request, "rrsp_tracker"):
        return JsonResponse({"error": "RRSP tracker is disabled in settings"}, status=403)
    return render(request, "rrsp.html")


def fhsa_page(request):
    if not _feature_enabled(request, "fhsa_tracker"):
        return JsonResponse({"error": "FHSA tracker is disabled in settings"}, status=403)
    return render(request, "fhsa.html")


def import_page(request):
    return render(request, "import_wizard.html")


def holdings_page(request):
    if not _feature_enabled(request, "holdings_overview"):
        return JsonResponse({"error": "Holdings overview is disabled in settings"}, status=403)
    return render(request, "holdings.html")


def health_view(request):
    return JsonResponse({"ok": True, "service": "django", "status": "healthy"})
