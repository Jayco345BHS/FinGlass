import json
from collections import defaultdict

from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_http_methods

from core.credit_card_categories import normalize_credit_card_category
from core.models import CreditCardTransaction
from core.services.credit_card_service import parse_bool_query, parse_credit_card_category_filters


def _read_json(request):
    try:
        if not request.body:
            return {}
        return json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}


def _tx_dict(row):
    return {
        "id": row.id,
        "provider": row.provider,
        "card_label": row.card_label or row.provider or "",
        "transaction_date": row.transaction_date.isoformat() if row.transaction_date else "",
        "posted_date": row.posted_date.isoformat() if row.posted_date else None,
        "card_last4": row.card_last4,
        "merchant_category": row.merchant_category,
        "merchant_name": row.merchant_name,
        "merchant_city": row.merchant_city,
        "merchant_region": row.merchant_region,
        "merchant_country": row.merchant_country,
        "amount": float(row.amount or 0),
        "rewards": float(row.rewards or 0),
        "is_hidden": bool(row.is_hidden),
        "status": row.status,
        "activity_type": row.activity_type,
        "reference_number": row.reference_number,
    }


@require_http_methods(["GET", "DELETE"])
def credit_card_transactions_collection(request):
    if request.method == "GET":
        return credit_card_transactions(request)
    return delete_all_credit_card_transactions(request)


@require_GET
def credit_card_dashboard(request):
    provider = str(request.GET.get("provider") or "").strip()
    card_label = str(request.GET.get("card_label") or "").strip()
    start_date = str(request.GET.get("start_date") or "").strip()
    end_date = str(request.GET.get("end_date") or "").strip()
    merchant = str(request.GET.get("merchant") or "").strip()
    include_hidden = parse_bool_query(request.GET.get("include_hidden"))
    selected_categories = {
        normalize_credit_card_category(category)
        for category in parse_credit_card_category_filters(request.GET)
    }

    queryset = CreditCardTransaction.objects.filter(user=request.user)
    if provider:
        queryset = queryset.filter(provider=provider)
    if card_label:
        # Search for transactions with the exact card_label OR with provider matching the label
        # (in case the label came from the provider field when card_label was empty)
        queryset = queryset.filter(Q(card_label=card_label) | Q(provider=card_label))
    if start_date:
        queryset = queryset.filter(transaction_date__gte=start_date)
    if end_date:
        queryset = queryset.filter(transaction_date__lte=end_date)
    if merchant:
        queryset = queryset.filter(merchant_name__icontains=merchant)
    if not include_hidden:
        queryset = queryset.filter(is_hidden=False)

    rows = []
    for row in queryset:
        mapped = _tx_dict(row)
        mapped["merchant_category"] = normalize_credit_card_category(mapped.get("merchant_category", ""))
        if selected_categories and mapped["merchant_category"] not in selected_categories:
            continue
        rows.append(mapped)

    expense_rows = [row for row in rows if float(row.get("amount") or 0) > 0]

    total_expenses = round(sum(float(row.get("amount") or 0) for row in expense_rows), 2)
    summary = {
        "total_expenses": total_expenses,
        "transactions": len(expense_rows),
    }

    monthly_totals = defaultdict(float)
    for row in expense_rows:
        month = str(row.get("transaction_date") or "")[:7]
        if month:
            monthly_totals[month] += float(row.get("amount") or 0)

    monthly = [{"month": month, "expenses": round(monthly_totals[month], 2)} for month in sorted(monthly_totals.keys())]

    category_totals = defaultdict(lambda: {"amount": 0.0, "transaction_count": 0})
    for row in expense_rows:
        normalized_category = row["merchant_category"]
        category_totals[normalized_category]["amount"] += float(row.get("amount") or 0)
        category_totals[normalized_category]["transaction_count"] += 1

    categories = []
    for category_name, totals in category_totals.items():
        tx_count = totals["transaction_count"]
        amount = round(totals["amount"], 2)
        categories.append(
            {
                "merchant_category": category_name,
                "amount": amount,
                "transaction_count": tx_count,
                "average_amount": round(amount / tx_count, 2) if tx_count else 0,
            }
        )
    categories.sort(key=lambda row: row["amount"], reverse=True)

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

    return JsonResponse(
        {
            "provider": provider,
            "latest_transaction_date": latest_transaction_date,
            "summary": summary,
            "monthly": monthly,
            "categories": categories,
            "top_merchants": merchants,
            "recent": recent_rows,
        }
    )


@require_GET
def credit_card_categories(request):
    provider = str(request.GET.get("provider") or "").strip()
    card_label = str(request.GET.get("card_label") or "").strip()
    queryset = CreditCardTransaction.objects.filter(user=request.user, is_hidden=False)
    if provider:
        queryset = queryset.filter(provider=provider)
    if card_label:
        queryset = queryset.filter(card_label=card_label)
    rows = queryset.values_list("merchant_category", flat=True).distinct().order_by("merchant_category")
    categories = sorted(
        {
            normalize_credit_card_category(value if value else "Uncategorized")
            for value in rows
            if value is not None
        }
    )
    return JsonResponse(categories, safe=False)


@require_GET
def credit_card_transactions(request):
    provider = str(request.GET.get("provider") or "").strip()
    card_label = str(request.GET.get("card_label") or "").strip()
    start_date = str(request.GET.get("start_date") or "").strip()
    end_date = str(request.GET.get("end_date") or "").strip()
    selected_categories = {
        normalize_credit_card_category(category)
        for category in parse_credit_card_category_filters(request.GET)
    }
    merchant = str(request.GET.get("merchant") or "").strip()
    include_payments = parse_bool_query(request.GET.get("include_payments"))
    include_hidden = parse_bool_query(request.GET.get("include_hidden"))
    limit_raw = str(request.GET.get("limit") or "").strip().lower()

    if not limit_raw:
        limit = 300
    elif limit_raw in {"all", "none"}:
        limit = None
    else:
        try:
            limit = int(limit_raw)
        except ValueError:
            return JsonResponse({"error": "limit must be an integer or 'all'"}, status=400)
        if limit < 1:
            return JsonResponse({"error": "limit must be >= 1 or 'all'"}, status=400)

    queryset = CreditCardTransaction.objects.filter(user=request.user)
    if provider:
        queryset = queryset.filter(provider=provider)
    if card_label:
        # Search for transactions with the exact card_label OR with provider matching the label
        # (in case the label came from the provider field when card_label was empty)
        queryset = queryset.filter(Q(card_label=card_label) | Q(provider=card_label))
    if start_date:
        queryset = queryset.filter(transaction_date__gte=start_date)
    if end_date:
        queryset = queryset.filter(transaction_date__lte=end_date)
    if merchant:
        queryset = queryset.filter(merchant_name__icontains=merchant)
    if not include_payments:
        queryset = queryset.filter(amount__gt=0)
    if not include_hidden:
        queryset = queryset.filter(is_hidden=False)

    rows = queryset.order_by("-transaction_date", "-id")
    normalized_rows = []
    for row in rows:
        mapped = _tx_dict(row)
        mapped["merchant_category"] = normalize_credit_card_category(mapped.get("merchant_category", ""))
        if selected_categories and mapped["merchant_category"] not in selected_categories:
            continue
        normalized_rows.append(mapped)
        if limit is not None and len(normalized_rows) >= limit:
            break

    return JsonResponse(normalized_rows, safe=False)


@require_GET
def credit_card_cards(request):
    provider = str(request.GET.get("provider") or "").strip()
    queryset = CreditCardTransaction.objects.filter(user=request.user)
    if provider:
        queryset = queryset.filter(provider=provider)

    rows = queryset.values_list("card_label", "provider").distinct()
    cards = sorted(
        {
            str(card if card else provider_name if provider_name else "").strip()
            for card, provider_name in rows
            if str(card if card else provider_name if provider_name else "").strip()
        }
    )
    return JsonResponse(cards, safe=False)


@require_http_methods(["PATCH"])
def set_credit_card_transaction_hidden(request, transaction_id):
    payload = _read_json(request)
    hidden = bool(payload.get("hidden", True))

    updated = CreditCardTransaction.objects.filter(
        id=transaction_id,
        user=request.user,
    ).update(is_hidden=hidden)
    if updated == 0:
        return JsonResponse({"error": "Credit card transaction not found"}, status=404)
    return JsonResponse({"updated": 1, "hidden": hidden})


@require_http_methods(["POST"])
def set_many_credit_card_transactions_hidden(request):
    payload = _read_json(request)
    hidden = bool(payload.get("hidden", True))
    ids = payload.get("ids")
    if not isinstance(ids, list) or len(ids) == 0:
        return JsonResponse({"error": "ids must be a non-empty array"}, status=400)

    normalized_ids = []
    for item in ids:
        try:
            normalized_ids.append(int(item))
        except (TypeError, ValueError):
            return JsonResponse({"error": "ids must contain only integers"}, status=400)

    updated = CreditCardTransaction.objects.filter(
        user=request.user,
        id__in=normalized_ids,
    ).update(is_hidden=hidden)

    return JsonResponse({"updated": updated, "hidden": hidden})


@require_http_methods(["DELETE"])
def delete_credit_card_transaction(request, transaction_id):
    deleted, _ = CreditCardTransaction.objects.filter(
        id=transaction_id,
        user=request.user,
    ).delete()
    if deleted == 0:
        return JsonResponse({"error": "Credit card transaction not found"}, status=404)
    return JsonResponse({"deleted": 1})


@require_http_methods(["POST"])
def delete_many_credit_card_transactions(request):
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

    deleted, _ = CreditCardTransaction.objects.filter(
        user=request.user,
        id__in=normalized_ids,
    ).delete()

    return JsonResponse({"deleted": deleted})


@require_http_methods(["DELETE"])
def delete_all_credit_card_transactions(request):
    provider = str(request.GET.get("provider") or "").strip()
    queryset = CreditCardTransaction.objects.filter(user=request.user)
    if provider:
        queryset = queryset.filter(provider=provider)
    deleted, _ = queryset.delete()
    return JsonResponse({"deleted": deleted})


@require_http_methods(["PATCH"])
def rename_credit_card(request, card_label):
    payload = _read_json(request)
    new_label = str(payload.get("new_label") or "").strip()

    if not new_label:
        return JsonResponse({"error": "new_label is required"}, status=400)

    # Update transactions with matching card_label OR provider (cards list can return either)
    updated = CreditCardTransaction.objects.filter(
        user=request.user
    ).filter(
        Q(card_label=card_label) | Q(provider=card_label)
    ).update(card_label=new_label)

    if updated == 0:
        return JsonResponse({"error": "Credit card not found"}, status=404)

    return JsonResponse({"updated": updated, "old_label": card_label, "new_label": new_label})


@require_http_methods(["DELETE"])
def delete_credit_card(request, card_label):
    # Delete transactions with matching card_label OR provider (cards list can return either)
    deleted, _ = CreditCardTransaction.objects.filter(
        user=request.user
    ).filter(
        Q(card_label=card_label) | Q(provider=card_label)
    ).delete()

    if deleted == 0:
        return JsonResponse({"error": "Credit card not found"}, status=404)

    return JsonResponse({"deleted": deleted, "card_label": card_label})
