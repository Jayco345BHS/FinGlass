import json
from datetime import datetime

from django.db import IntegrityError
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from core.models import NetWorthHistory


def _read_json(request):
    try:
        if not request.body:
            return {}
        return json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}


def _entry_dict(entry):
    return {
        "id": entry.id,
        "entry_date": entry.entry_date.isoformat(),
        "amount": float(entry.amount or 0),
        "note": entry.note or "",
    }


@require_http_methods(["GET", "POST"])
def net_worth_collection(request):
    if request.method == "GET":
        rows = NetWorthHistory.objects.filter(user=request.user).order_by("entry_date", "id")
        return JsonResponse([_entry_dict(row) for row in rows], safe=False)

    payload = _read_json(request)
    entry_date = str(payload.get("entry_date") or "").strip()
    if not entry_date:
        return JsonResponse({"error": "entry_date is required"}, status=400)

    try:
        entry_date_value = datetime.strptime(entry_date, "%Y-%m-%d").date()
    except ValueError:
        return JsonResponse({"error": "entry_date must be YYYY-MM-DD"}, status=400)

    try:
        amount = float(payload.get("amount"))
    except (TypeError, ValueError):
        return JsonResponse({"error": "amount must be a number"}, status=400)

    note = str(payload.get("note") or "").strip()

    try:
        created = NetWorthHistory.objects.create(
            user=request.user,
            entry_date=entry_date_value,
            amount=amount,
            note=note,
        )
    except (IntegrityError, ValueError) as exc:
        return JsonResponse({"error": f"Failed to create net worth entry: {exc}"}, status=400)

    return JsonResponse(_entry_dict(created), status=201)


@require_http_methods(["PUT", "DELETE"])
def net_worth_item(request, entry_id):
    entry = NetWorthHistory.objects.filter(id=entry_id, user=request.user).first()
    if not entry:
        return JsonResponse({"error": "Net worth entry not found"}, status=404)

    if request.method == "DELETE":
        entry.delete()
        return JsonResponse({"deleted": 1})

    payload = _read_json(request)
    entry_date = str(payload.get("entry_date") or "").strip()
    if not entry_date:
        return JsonResponse({"error": "entry_date is required"}, status=400)

    try:
        entry_date_value = datetime.strptime(entry_date, "%Y-%m-%d").date()
    except ValueError:
        return JsonResponse({"error": "entry_date must be YYYY-MM-DD"}, status=400)

    try:
        amount = float(payload.get("amount"))
    except (TypeError, ValueError):
        return JsonResponse({"error": "amount must be a number"}, status=400)

    note = str(payload.get("note") or "").strip()

    try:
        entry.entry_date = entry_date_value
        entry.amount = amount
        entry.note = note
        entry.save(update_fields=["entry_date", "amount", "note", "updated_at"])
    except (IntegrityError, ValueError) as exc:
        return JsonResponse({"error": f"Failed to update net worth entry: {exc}"}, status=400)

    return JsonResponse(_entry_dict(entry))
