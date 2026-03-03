import json
from collections import defaultdict
from datetime import datetime

from django.db import IntegrityError
from django.db.models import Case, Count, F, Max, Q, Sum, Value, When
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_http_methods

from core.constants import CASH_ACCOUNT_NUMBER
from core.market_data import MarketDataError, get_quote
from core.models import HoldingSnapshot
from core.services.holdings_service import (
    derive_account_number,
    normalize_holding_symbol,
    parse_as_of_value,
    parse_numeric_field,
)


def _read_json(request):
    try:
        if not request.body:
            return {}
        return json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}


def _float(value):
    return float(value or 0)


def _holding_row_dict(row):
    return {
        "id": row.id,
        "as_of": row.as_of.isoformat(),
        "account_name": row.account_name,
        "account_type": row.account_type,
        "account_classification": row.account_classification,
        "account_number": row.account_number,
        "symbol": row.symbol,
        "security_name": row.security_name,
        "quantity": _float(row.quantity),
        "book_value_cad": _float(row.book_value_cad),
        "market_value": _float(row.market_value),
        "unrealized_return": _float(row.unrealized_return),
    }


@require_http_methods(["GET", "POST"])
def holdings_collection(request):
    if request.method == "GET":
        return list_holdings_rows(request)
    return create_holding_row(request)


@require_http_methods(["PUT", "DELETE"])
def holdings_item(request, holding_id):
    if request.method == "PUT":
        return update_holding_row(request, holding_id)
    return delete_holding_row(request, holding_id)


@require_GET
def accounts_dashboard(request):
    latest_as_of = (
        HoldingSnapshot.objects.filter(user=request.user)
        .aggregate(as_of=Max("as_of"))
        .get("as_of")
    )

    if not latest_as_of:
        return JsonResponse(
            {
                "as_of": None,
                "summary": {
                    "accounts": 0,
                    "positions": 0,
                    "book_value_cad": 0,
                    "market_value": 0,
                    "unrealized_return": 0,
                },
                "accounts": [],
                "account_types": [],
                "top_holdings": [],
                "holdings_securities": [],
                "symbol_allocations": [],
            }
        )

    base = HoldingSnapshot.objects.filter(user=request.user, as_of=latest_as_of)
    normalized_account_type = Case(
        When(Q(account_type__isnull=True) | Q(account_type=""), then=Value("Unknown")),
        default=F("account_type"),
    )

    accounts = list(
        base.values(
            "account_name",
            "account_type",
            "account_classification",
            "account_number",
        )
        .annotate(
            positions=Count("id"),
            book_value_cad=Sum("book_value_cad"),
            market_value=Sum("market_value"),
            unrealized_return=Sum("unrealized_return"),
        )
        .order_by("-market_value", "account_name")
    )

    account_types = list(
        base.annotate(normalized_account_type=normalized_account_type)
        .values("normalized_account_type")
        .annotate(market_value=Sum("market_value"))
        .order_by("-market_value")
    )

    top_holdings = list(
        base.values("symbol")
        .annotate(
            security_name=Max("security_name"),
            quantity=Sum("quantity"),
            book_value_cad=Sum("book_value_cad"),
            market_value=Sum("market_value"),
            unrealized_return=Sum("unrealized_return"),
        )
        .order_by("-market_value", "symbol")[:12]
    )

    holdings_securities = list(
        base.values("symbol")
        .annotate(
            security_name=Max("security_name"),
            quantity=Sum("quantity"),
            book_value_cad=Sum("book_value_cad"),
            market_value=Sum("market_value"),
            unrealized_return=Sum("unrealized_return"),
        )
        .order_by("-market_value", "symbol")
    )

    security_account_types = list(
        base.annotate(normalized_account_type=normalized_account_type)
        .values("symbol", "normalized_account_type")
        .annotate(market_value=Sum("market_value"))
        .order_by("symbol", "-market_value", "normalized_account_type")
    )

    account_types_by_symbol = defaultdict(list)
    for row in security_account_types:
        account_types_by_symbol[row["symbol"]].append(
            {
                "account_type": row["normalized_account_type"],
                "market_value": _float(row["market_value"]),
            }
        )

    holdings_securities_result = []
    for row in holdings_securities:
        symbol = row.get("symbol")
        symbol_market_value = _float(row.get("market_value"))
        type_rows = account_types_by_symbol.get(symbol, [])
        labels = []
        for type_row in type_rows:
            percentage = (type_row["market_value"] / symbol_market_value * 100) if symbol_market_value > 0 else 0
            labels.append(f"{type_row['account_type']} ({percentage:.2f}%)")

        holdings_securities_result.append(
            {
                "symbol": symbol,
                "security_name": row.get("security_name"),
                "quantity": _float(row.get("quantity")),
                "book_value_cad": _float(row.get("book_value_cad")),
                "market_value": _float(row.get("market_value")),
                "unrealized_return": _float(row.get("unrealized_return")),
                "account_types": ", ".join(labels),
            }
        )

    symbol_allocations = list(
        base.values("symbol")
        .annotate(market_value=Sum("market_value"))
        .filter(market_value__gt=0)
        .order_by("-market_value", "symbol")
    )

    accounts_result = [
        {
            **row,
            "book_value_cad": _float(row.get("book_value_cad")),
            "market_value": _float(row.get("market_value")),
            "unrealized_return": _float(row.get("unrealized_return")),
        }
        for row in accounts
    ]

    account_types_result = [
        {
            "account_type": row.get("normalized_account_type"),
            "market_value": _float(row.get("market_value")),
        }
        for row in account_types
    ]

    top_holdings_result = [
        {
            **row,
            "quantity": _float(row.get("quantity")),
            "book_value_cad": _float(row.get("book_value_cad")),
            "market_value": _float(row.get("market_value")),
            "unrealized_return": _float(row.get("unrealized_return")),
        }
        for row in top_holdings
    ]

    symbol_allocations_result = [
        {
            **row,
            "market_value": _float(row.get("market_value")),
        }
        for row in symbol_allocations
    ]

    summary = {
        "accounts": len(accounts_result),
        "positions": sum(int(item.get("positions") or 0) for item in accounts_result),
        "book_value_cad": round(sum(_float(item.get("book_value_cad")) for item in accounts_result), 4),
        "market_value": round(sum(_float(item.get("market_value")) for item in accounts_result), 4),
        "unrealized_return": round(sum(_float(item.get("unrealized_return")) for item in accounts_result), 4),
    }

    return JsonResponse(
        {
            "as_of": latest_as_of.isoformat(),
            "summary": summary,
            "accounts": accounts_result,
            "account_types": account_types_result,
            "top_holdings": top_holdings_result,
            "holdings_securities": holdings_securities_result,
            "symbol_allocations": symbol_allocations_result,
        }
    )


@require_http_methods(["PUT"])
def upsert_cash_account(request):
    payload = _read_json(request)
    as_of = str(payload.get("as_of") or "").strip()

    if not as_of:
        latest = (
            HoldingSnapshot.objects.filter(user=request.user)
            .order_by("-as_of")
            .values_list("as_of", flat=True)
            .first()
        )
        as_of = latest.isoformat() if latest else ""

    if not as_of:
        return JsonResponse({"error": "No holdings snapshot found"}, status=400)

    try:
        as_of_date = datetime.strptime(as_of, "%Y-%m-%d").date()
    except ValueError:
        return JsonResponse({"error": "as_of must be YYYY-MM-DD"}, status=400)

    try:
        amount = float(payload.get("amount"))
    except (TypeError, ValueError):
        return JsonResponse({"error": "amount must be a number"}, status=400)

    if abs(amount) < 0.0000001:
        HoldingSnapshot.objects.filter(
            user=request.user,
            as_of=as_of_date,
            account_number=CASH_ACCOUNT_NUMBER,
            symbol="CASH",
        ).delete()
        return JsonResponse({"updated": 1, "as_of": as_of, "account_number": CASH_ACCOUNT_NUMBER, "cash": 0.0})

    HoldingSnapshot.objects.update_or_create(
        user=request.user,
        as_of=as_of_date,
        account_number=CASH_ACCOUNT_NUMBER,
        symbol="CASH",
        defaults={
            "account_name": "Cash Account",
            "account_type": "Cash",
            "account_classification": "Cash",
            "exchange": "",
            "mic": "",
            "security_name": "Cash",
            "security_type": "Cash",
            "quantity": 1,
            "market_price": amount,
            "market_price_currency": "CAD",
            "book_value_cad": amount,
            "market_value": amount,
            "market_value_currency": "CAD",
            "unrealized_return": 0,
            "source_filename": "manual_cash_entry",
        },
    )

    return JsonResponse(
        {
            "updated": 1,
            "as_of": as_of,
            "account_number": CASH_ACCOUNT_NUMBER,
            "cash": round(amount, 4),
        }
    )


@require_GET
def list_holdings_rows(request):
    as_of = str(request.GET.get("as_of") or "").strip()
    latest = (
        HoldingSnapshot.objects.filter(user=request.user)
        .order_by("-as_of")
        .values_list("as_of", flat=True)
        .first()
    )
    latest_as_of = latest.isoformat() if latest else None

    target_as_of = as_of or latest_as_of
    if not target_as_of:
        return JsonResponse({"as_of": None, "latest_as_of": None, "rows": []})

    try:
        target_date = datetime.strptime(target_as_of, "%Y-%m-%d").date()
    except ValueError:
        return JsonResponse({"error": "as_of must be YYYY-MM-DD"}, status=400)

    rows = (
        HoldingSnapshot.objects.filter(user=request.user, as_of=target_date)
        .order_by("account_name", "account_number", "symbol", "id")
    )

    return JsonResponse(
        {
            "as_of": target_as_of,
            "latest_as_of": latest_as_of,
            "rows": [_holding_row_dict(row) for row in rows],
        }
    )


@require_http_methods(["POST"])
def create_holding_row(request):
    payload = _read_json(request)

    account_name = str(payload.get("account_name") or "").strip()
    account_number = str(payload.get("account_number") or "").strip() or derive_account_number(account_name)
    symbol = normalize_holding_symbol(payload.get("symbol"))
    if not account_name:
        return JsonResponse({"error": "account_name is required"}, status=400)
    if not symbol:
        return JsonResponse({"error": "symbol is required"}, status=400)

    try:
        as_of = parse_as_of_value(request.user, payload.get("as_of"))
    except ValueError:
        return JsonResponse({"error": "as_of must be YYYY-MM-DD"}, status=400)

    try:
        quantity = parse_numeric_field(payload, "quantity")
        book_value_cad = parse_numeric_field(payload, "book_value_cad")
        market_value = parse_numeric_field(payload, "market_value")
        unrealized_return = parse_numeric_field(payload, "unrealized_return") if "unrealized_return" in payload else market_value - book_value_cad
    except (TypeError, ValueError):
        return JsonResponse({"error": "numeric fields must be valid numbers"}, status=400)

    if "market_price" in payload:
        try:
            market_price = float(payload.get("market_price") or 0)
        except (TypeError, ValueError):
            return JsonResponse({"error": "market_price must be a number"}, status=400)
    else:
        market_price = (market_value / quantity) if abs(quantity) > 0.0000001 else 0.0

    account_type = str(payload.get("account_type") or "").strip()
    account_classification = str(payload.get("account_classification") or "").strip()
    exchange = str(payload.get("exchange") or "").strip()
    mic = str(payload.get("mic") or "").strip()
    security_name = str(payload.get("security_name") or "").strip()
    security_type = str(payload.get("security_type") or "").strip()
    market_price_currency = str(payload.get("market_price_currency") or "CAD").strip() or "CAD"
    market_value_currency = str(payload.get("market_value_currency") or "CAD").strip() or "CAD"

    holding, _ = HoldingSnapshot.objects.update_or_create(
        user=request.user,
        as_of=as_of,
        account_number=account_number,
        symbol=symbol,
        defaults={
            "account_name": account_name,
            "account_type": account_type,
            "account_classification": account_classification,
            "exchange": exchange,
            "mic": mic,
            "security_name": security_name,
            "security_type": security_type,
            "quantity": quantity,
            "market_price": market_price,
            "market_price_currency": market_price_currency,
            "book_value_cad": book_value_cad,
            "market_value": market_value,
            "market_value_currency": market_value_currency,
            "unrealized_return": unrealized_return,
            "source_filename": "manual_holding_entry",
        },
    )

    return JsonResponse(_holding_row_dict(holding), status=201)


@require_http_methods(["PUT"])
def update_holding_row(request, holding_id):
    payload = _read_json(request)

    existing = HoldingSnapshot.objects.filter(id=holding_id, user=request.user).first()
    if not existing:
        return JsonResponse({"error": "Holding row not found"}, status=404)

    account_name = str(payload.get("account_name") or "").strip()
    account_number = str(payload.get("account_number") or "").strip()
    symbol = normalize_holding_symbol(payload.get("symbol"))
    if not account_name:
        return JsonResponse({"error": "account_name is required"}, status=400)
    if not symbol:
        return JsonResponse({"error": "symbol is required"}, status=400)

    if not account_number:
        account_number = str(existing.account_number or "").strip()
    if not account_number:
        account_number = derive_account_number(account_name)

    as_of = str(payload.get("as_of") or "").strip() or existing.as_of.isoformat()
    if not as_of:
        return JsonResponse({"error": "as_of is required"}, status=400)
    try:
        as_of_date = datetime.strptime(as_of, "%Y-%m-%d").date()
    except ValueError:
        return JsonResponse({"error": "as_of must be YYYY-MM-DD"}, status=400)

    try:
        quantity = parse_numeric_field(payload, "quantity", 0)
        book_value_cad = parse_numeric_field(payload, "book_value_cad", 0)
        market_value = parse_numeric_field(payload, "market_value", 0)
        unrealized_return = parse_numeric_field(payload, "unrealized_return", 0) if "unrealized_return" in payload else market_value - book_value_cad
    except (TypeError, ValueError):
        return JsonResponse({"error": "numeric fields must be valid numbers"}, status=400)

    if "market_price" in payload:
        try:
            market_price = float(payload.get("market_price") or 0)
        except (TypeError, ValueError):
            return JsonResponse({"error": "market_price must be a number"}, status=400)
    else:
        existing_market_price = float(existing.market_price or 0)
        market_price = existing_market_price if abs(existing_market_price) > 0.0000001 else ((market_value / quantity) if abs(quantity) > 0.0000001 else 0.0)

    existing.as_of = as_of_date
    existing.account_name = account_name
    existing.account_type = str(payload.get("account_type") or existing.account_type or "").strip()
    existing.account_classification = str(payload.get("account_classification") or existing.account_classification or "").strip()
    existing.account_number = account_number
    existing.symbol = symbol
    existing.exchange = str(payload.get("exchange") or existing.exchange or "").strip()
    existing.mic = str(payload.get("mic") or existing.mic or "").strip()
    existing.security_name = str(payload.get("security_name") or existing.security_name or "").strip()
    existing.security_type = str(payload.get("security_type") or existing.security_type or "").strip()
    existing.quantity = quantity
    existing.market_price = market_price
    existing.market_price_currency = str(payload.get("market_price_currency") or existing.market_price_currency or "CAD").strip() or "CAD"
    existing.book_value_cad = book_value_cad
    existing.market_value = market_value
    existing.market_value_currency = str(payload.get("market_value_currency") or existing.market_value_currency or "CAD").strip() or "CAD"
    existing.unrealized_return = unrealized_return
    existing.source_filename = "manual_holding_entry"

    try:
        existing.save()
    except IntegrityError:
        return JsonResponse({"error": "A row already exists for this date/account/symbol"}, status=409)

    return JsonResponse(_holding_row_dict(existing))


@require_http_methods(["DELETE"])
def delete_holding_row(request, holding_id):
    deleted, _ = HoldingSnapshot.objects.filter(id=holding_id, user=request.user).delete()
    if deleted == 0:
        return JsonResponse({"error": "Holding row not found"}, status=404)
    return JsonResponse({"deleted": 1})


@require_GET
def market_data_quote(request):
    symbol = str(request.GET.get("symbol") or "").strip().upper()
    if not symbol:
        return JsonResponse({"error": "symbol is required"}, status=400)

    try:
        quote = get_quote(symbol)
    except MarketDataError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except Exception:
        return JsonResponse({"error": "Failed to fetch quote"}, status=502)

    return JsonResponse(quote)


@require_http_methods(["POST"])
def refresh_holdings_market_values(request):
    payload = _read_json(request)
    as_of = str(payload.get("as_of") or "").strip()

    if not as_of:
        latest = (
            HoldingSnapshot.objects.filter(user=request.user)
            .order_by("-as_of")
            .values_list("as_of", flat=True)
            .first()
        )
        as_of = latest.isoformat() if latest else ""

    if not as_of:
        return JsonResponse({"error": "No holdings snapshot found"}, status=400)

    try:
        as_of_date = datetime.strptime(as_of, "%Y-%m-%d").date()
    except ValueError:
        return JsonResponse({"error": "as_of must be YYYY-MM-DD"}, status=400)

    rows = list(
        HoldingSnapshot.objects.filter(user=request.user, as_of=as_of_date)
        .order_by("id")
    )

    if not rows:
        return JsonResponse({"error": "No holdings rows found for snapshot"}, status=400)

    symbols = {
        str(row.symbol or "").strip().upper()
        for row in rows
        if str(row.symbol or "").strip().upper() not in {"", "CASH"}
    }

    quotes_by_symbol = {}
    errors = []
    for symbol in sorted(symbols):
        try:
            quote = get_quote(symbol)
            quotes_by_symbol[symbol] = float(quote["price"])
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")

    updated = 0
    for row in rows:
        symbol = str(row.symbol or "").strip().upper()
        if symbol not in quotes_by_symbol:
            continue

        quantity = float(row.quantity or 0)
        book_value = float(row.book_value_cad or 0)
        price = float(quotes_by_symbol[symbol])
        market_value = round(quantity * price, 4)
        unrealized = round(market_value - book_value, 4)

        row.market_price = price
        row.market_value = market_value
        row.unrealized_return = unrealized
        row.source_filename = "market_data_refresh"
        row.save(update_fields=["market_price", "market_value", "unrealized_return", "source_filename", "imported_at"])
        updated += 1

    return JsonResponse(
        {
            "as_of": as_of,
            "symbols_requested": len(symbols),
            "symbols_priced": len(quotes_by_symbol),
            "rows_updated": updated,
            "errors": errors,
        }
    )
