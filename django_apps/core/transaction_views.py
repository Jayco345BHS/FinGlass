import json

from django.db.models import Count
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_http_methods

from django_apps.core.acb import calculate_ledger_rows
from django_apps.core.constants import SUPPORTED_TRANSACTION_TYPES
from django_apps.core.models import Transaction
from django_apps.core.services.transactions_service import parse_transaction_payload


def _read_json(request):
    try:
        if not request.body:
            return {}
        return json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}


def _tx_to_dict(tx):
    return {
        "id": tx.id,
        "security": tx.security,
        "trade_date": tx.trade_date.isoformat(),
        "transaction_type": tx.transaction_type,
        "amount": float(tx.amount),
        "shares": float(tx.shares),
        "amount_per_share": float(tx.amount_per_share or 0),
        "commission": float(tx.commission),
        "memo": tx.memo,
        "source": tx.source,
        "created_at": tx.created_at.isoformat() if tx.created_at else None,
    }


@require_http_methods(["GET", "POST"])
def transactions_collection(request):
    if request.method == "GET":
        return list_transactions(request)
    return create_transaction(request)


@require_http_methods(["PUT", "DELETE"])
def transactions_item(request, transaction_id):
    if request.method == "PUT":
        return update_transaction(request, transaction_id)
    return delete_transaction(request, transaction_id)


@require_GET
def list_transactions(request):
    security = request.GET.get("security", "").strip()
    queryset = Transaction.objects.filter(user=request.user)
    if security:
        queryset = queryset.filter(security=security)
    rows = queryset.order_by("trade_date", "id")
    return JsonResponse([_tx_to_dict(row) for row in rows], safe=False)


@require_http_methods(["POST"])
def create_transaction(request):
    payload = _read_json(request)
    try:
        tx = parse_transaction_payload(payload)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    created = Transaction.objects.create(
        user=request.user,
        security=tx["security"],
        trade_date=tx["trade_date"],
        transaction_type=tx["transaction_type"],
        amount=tx["amount"],
        shares=tx["shares"],
        amount_per_share=tx["amount_per_share"],
        commission=tx["commission"],
        memo=tx["memo"],
        source="manual",
    )
    return JsonResponse({"id": created.id}, status=201)


@require_http_methods(["PUT"])
def update_transaction(request, transaction_id):
    payload = _read_json(request)
    try:
        tx = parse_transaction_payload(payload)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    updated = Transaction.objects.filter(id=transaction_id, user=request.user).update(
        security=tx["security"],
        trade_date=tx["trade_date"],
        transaction_type=tx["transaction_type"],
        amount=tx["amount"],
        shares=tx["shares"],
        amount_per_share=tx["amount_per_share"],
        commission=tx["commission"],
        memo=tx["memo"],
    )
    if updated == 0:
        return JsonResponse({"error": "Transaction not found"}, status=404)

    return JsonResponse({"updated": 1})


@require_http_methods(["DELETE"])
def delete_transaction(request, transaction_id):
    deleted, _ = Transaction.objects.filter(id=transaction_id, user=request.user).delete()
    if deleted == 0:
        return JsonResponse({"error": "Transaction not found"}, status=404)
    return JsonResponse({"deleted": 1})


@require_http_methods(["POST"])
def delete_many_transactions(request):
    payload = _read_json(request)
    ids = payload.get("ids")
    if not isinstance(ids, list) or len(ids) == 0:
        return JsonResponse({"error": "ids must be a non-empty array"}, status=400)

    normalized_ids = []
    for item in ids:
        try:
            normalized_ids.append(int(item))
        except (TypeError, ValueError):
            return JsonResponse({"error": "ids must contain only integers"}, status=400)

    deleted, _ = Transaction.objects.filter(user=request.user, id__in=normalized_ids).delete()
    return JsonResponse({"deleted": deleted})


@require_GET
def get_ledger(request):
    security = request.GET.get("security", "").strip()
    if not security:
        return JsonResponse({"error": "security query parameter is required"}, status=400)

    rows = (
        Transaction.objects.filter(user=request.user, security=security)
        .order_by("trade_date", "id")
    )
    ledger = calculate_ledger_rows([_tx_to_dict(row) for row in rows])
    return JsonResponse(ledger, safe=False)


@require_GET
def list_securities(request):
    securities = (
        Transaction.objects.filter(user=request.user)
        .values("security")
        .annotate(transaction_count=Count("id"))
        .order_by("security")
    )

    result = []
    for sec in securities:
        security = sec["security"]
        rows = (
            Transaction.objects.filter(user=request.user, security=security)
            .order_by("trade_date", "id")
        )
        ledger = calculate_ledger_rows([_tx_to_dict(row) for row in rows])
        latest = (
            ledger[-1]
            if ledger
            else {
                "share_balance": 0,
                "acb": 0,
                "acb_per_share": 0,
                "capital_gain": 0,
            }
        )
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

    return JsonResponse(result, safe=False)


@require_GET
def list_transaction_types(request):
    return JsonResponse(sorted(SUPPORTED_TRANSACTION_TYPES), safe=False)
