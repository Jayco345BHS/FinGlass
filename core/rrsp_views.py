import json

from django.db import transaction
from django.db.models import F
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from core.models import RrspAccount, RrspContribution
from core.services.rrsp_import_service import import_rrsp_transactions_rows, parse_rrsp_import_csv_text
from core.services.rrsp_service import (
    create_rrsp_transfer,
    delete_user_rrsp_annual_limit,
    ensure_rrsp_setup_from_import,
    get_rrsp_summary,
    get_user_rrsp_opening_balance,
    get_user_rrsp_opening_balance_base_year,
    is_user_rrsp_opening_balance_configured,
    list_user_rrsp_annual_limits,
    reset_user_rrsp_data,
    set_user_rrsp_opening_balance,
    set_user_rrsp_opening_balance_base_year,
    upsert_user_rrsp_annual_limit,
)


def _read_json(request):
    try:
        if not request.body:
            return {}
        return json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}


def _parse_bool(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_optional_year(value, *, field_name):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        year = int(text)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be an integer year")
    if year < 1957 or year > 2100:
        raise ValueError(f"{field_name} must be between 1957 and 2100")
    return year


def _require_opening_balance_configured(user_id):
    if not is_user_rrsp_opening_balance_configured(user_id):
        return JsonResponse({"error": "Set RRSP available contribution room first"}, status=400)
    return None


@require_http_methods(["GET"])
def rrsp_summary(request):
    user_id = request.user.id
    summary = get_rrsp_summary(user_id)
    return JsonResponse(summary)


@require_http_methods(["POST"])
def rrsp_accounts(request):
    user_id = request.user.id
    data = _read_json(request)
    setup_error = _require_opening_balance_configured(user_id)
    if setup_error is not None:
        return setup_error

    account_name = (data.get("account_name") or "").strip()
    if not account_name:
        return JsonResponse({"error": "account_name required"}, status=400)

    try:
        account = RrspAccount.objects.create(user_id=user_id, account_name=account_name, opening_balance=0)
        return JsonResponse({"id": account.id}, status=201)
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@require_http_methods(["GET", "PUT"])
def rrsp_opening_balance(request):
    user_id = request.user.id
    if request.method == "GET":
        balance = get_user_rrsp_opening_balance(user_id)
        base_year = get_user_rrsp_opening_balance_base_year(user_id)
        configured = is_user_rrsp_opening_balance_configured(user_id)
        return JsonResponse({"opening_balance": balance, "base_year": base_year, "configured": configured})

    data = _read_json(request)
    opening_balance = float(data.get("opening_balance") or 0)
    if opening_balance < 0:
        return JsonResponse({"error": "opening_balance must be >= 0"}, status=400)

    set_user_rrsp_opening_balance(user_id, opening_balance)
    return JsonResponse({"success": True})


@require_http_methods(["GET", "POST"])
def rrsp_annual_limits(request):
    user_id = request.user.id
    if request.method == "GET":
        return JsonResponse({"annual_limits": list_user_rrsp_annual_limits(user_id)})

    data = _read_json(request)
    setup_error = _require_opening_balance_configured(user_id)
    if setup_error is not None:
        return setup_error

    try:
        year = int(str(data.get("year")))
    except (TypeError, ValueError):
        return JsonResponse({"error": "year must be an integer"}, status=400)

    try:
        annual_limit = float(str(data.get("annual_limit")))
    except (TypeError, ValueError):
        return JsonResponse({"error": "annual_limit must be a number"}, status=400)

    if year < 1957 or year > 2100:
        return JsonResponse({"error": "year must be between 1957 and 2100"}, status=400)

    if annual_limit < 0:
        return JsonResponse({"error": "annual_limit must be >= 0"}, status=400)

    base_year = get_user_rrsp_opening_balance_base_year(user_id)
    if base_year is not None and year <= int(base_year):
        return JsonResponse({"error": f"year must be greater than opening balance base year ({base_year})"}, status=400)

    upsert_user_rrsp_annual_limit(user_id, year, annual_limit)
    return JsonResponse({"success": True}, status=201)


@require_http_methods(["DELETE"])
def rrsp_annual_limit_item(request, year):
    user_id = request.user.id
    deleted = delete_user_rrsp_annual_limit(user_id, year)
    if not deleted:
        return JsonResponse({"error": "Annual limit not found"}, status=404)
    return JsonResponse({"success": True})


@require_http_methods(["GET"])
def rrsp_transactions(request):
    user_id = request.user.id
    rows = list(
        RrspContribution.objects.filter(user_id=user_id)
        .select_related("rrsp_account")
        .order_by("-contribution_date", "-id")
        .values(
            "id",
            "contribution_date",
            "contribution_type",
            "amount",
            "is_unused",
            "deducted_tax_year",
            "memo",
            "created_at",
            "rrsp_account_id",
            account_name=F("rrsp_account__account_name"),
        )
    )
    return JsonResponse(rows, safe=False)


@require_http_methods(["PUT", "DELETE"])
def rrsp_transaction_item(request, transaction_id):
    user_id = request.user.id
    if request.method == "DELETE":
        deleted, _ = RrspContribution.objects.filter(id=transaction_id, user_id=user_id).delete()
        if deleted == 0:
            return JsonResponse({"error": "Transaction not found"}, status=404)
        return JsonResponse({"deleted": 1})

    data = _read_json(request)

    rrsp_account_id = data.get("rrsp_account_id")
    contribution_date = (data.get("contribution_date") or "").strip()
    contribution_type = (data.get("contribution_type") or "").strip()
    is_unused = _parse_bool(data.get("is_unused", False))
    raw_deducted_tax_year = data.get("deducted_tax_year")
    memo = (data.get("memo") or "").strip()

    try:
        deducted_tax_year = _parse_optional_year(raw_deducted_tax_year, field_name="deducted_tax_year")
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    try:
        amount = float(data.get("amount") or 0)
    except (TypeError, ValueError):
        return JsonResponse({"error": "amount must be a number"}, status=400)

    try:
        normalized_account_id = int(str(rrsp_account_id))
    except (TypeError, ValueError):
        return JsonResponse({"error": "rrsp_account_id must be an integer"}, status=400)

    if not contribution_date:
        return JsonResponse({"error": "contribution_date required"}, status=400)
    if contribution_type not in ("Deposit", "Withdrawal"):
        return JsonResponse({"error": "contribution_type must be 'Deposit' or 'Withdrawal'"}, status=400)
    if contribution_type != "Deposit" and is_unused:
        return JsonResponse({"error": "is_unused can only be true for Deposit transactions"}, status=400)
    if contribution_type != "Deposit" and deducted_tax_year is not None:
        return JsonResponse({"error": "deducted_tax_year can only be set for Deposit transactions"}, status=400)
    if is_unused and deducted_tax_year is not None:
        return JsonResponse({"error": "deducted_tax_year cannot be set while contribution is marked unused"}, status=400)
    if amount <= 0:
        return JsonResponse({"error": "amount must be > 0"}, status=400)

    existing = RrspContribution.objects.filter(id=transaction_id, user_id=user_id).first()
    if not existing:
        return JsonResponse({"error": "Transaction not found"}, status=404)

    account = RrspAccount.objects.filter(id=normalized_account_id, user_id=user_id).first()
    if not account:
        return JsonResponse({"error": "Account not found"}, status=404)

    existing.rrsp_account_id = normalized_account_id
    existing.contribution_date = contribution_date
    existing.amount = amount
    existing.contribution_type = contribution_type
    existing.is_unused = bool(is_unused)
    existing.deducted_tax_year = deducted_tax_year
    existing.memo = memo
    existing.save(
        update_fields=[
            "rrsp_account",
            "contribution_date",
            "amount",
            "contribution_type",
            "is_unused",
            "deducted_tax_year",
            "memo",
        ]
    )

    return JsonResponse({"updated": 1})


@require_http_methods(["POST"])
def rrsp_contributions(request):
    user_id = request.user.id
    data = _read_json(request)

    setup_error = _require_opening_balance_configured(user_id)
    if setup_error is not None:
        return setup_error

    rrsp_account_id = data.get("rrsp_account_id")
    contribution_date = (data.get("contribution_date") or "").strip()
    contribution_type = (data.get("contribution_type") or "Deposit").strip()
    is_unused = _parse_bool(data.get("is_unused", False))
    raw_deducted_tax_year = data.get("deducted_tax_year")
    memo = (data.get("memo") or "").strip()

    try:
        amount = float(data.get("amount") or 0)
    except (TypeError, ValueError):
        return JsonResponse({"error": "amount must be a number"}, status=400)

    try:
        deducted_tax_year = _parse_optional_year(raw_deducted_tax_year, field_name="deducted_tax_year")
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    if not all([rrsp_account_id, amount > 0, contribution_date]):
        return JsonResponse({"error": "Missing required fields"}, status=400)
    if contribution_type not in ("Deposit", "Withdrawal"):
        return JsonResponse({"error": "contribution_type must be 'Deposit' or 'Withdrawal'"}, status=400)
    if contribution_type != "Deposit" and is_unused:
        return JsonResponse({"error": "is_unused can only be true for Deposit transactions"}, status=400)
    if contribution_type != "Deposit" and deducted_tax_year is not None:
        return JsonResponse({"error": "deducted_tax_year can only be set for Deposit transactions"}, status=400)
    if is_unused and deducted_tax_year is not None:
        return JsonResponse({"error": "deducted_tax_year cannot be set while contribution is marked unused"}, status=400)

    acc = RrspAccount.objects.filter(id=rrsp_account_id, user_id=user_id).first()
    if not acc:
        return JsonResponse({"error": "Account not found"}, status=404)

    try:
        RrspContribution.objects.create(
            user_id=user_id,
            rrsp_account_id=rrsp_account_id,
            contribution_date=contribution_date,
            amount=amount,
            contribution_type=contribution_type,
            is_unused=bool(is_unused),
            deducted_tax_year=deducted_tax_year,
            memo=memo,
        )
        return JsonResponse({"success": True}, status=201)
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@require_http_methods(["POST"])
def rrsp_transfers(request):
    user_id = request.user.id
    data = _read_json(request)

    setup_error = _require_opening_balance_configured(user_id)
    if setup_error is not None:
        return setup_error

    try:
        amount = float(data.get("amount") or 0)
    except (TypeError, ValueError):
        return JsonResponse({"error": "amount must be a number"}, status=400)

    try:
        from_rrsp_account_id = int(str(data.get("from_rrsp_account_id")))
        to_rrsp_account_id = int(str(data.get("to_rrsp_account_id")))
    except (TypeError, ValueError):
        return JsonResponse({"error": "from_rrsp_account_id and to_rrsp_account_id must be integers"}, status=400)

    try:
        create_rrsp_transfer(
            user_id=user_id,
            from_rrsp_account_id=from_rrsp_account_id,
            to_rrsp_account_id=to_rrsp_account_id,
            transfer_date=(data.get("transfer_date") or "").strip(),
            amount=amount,
            memo=(data.get("memo") or "").strip(),
        )
        return JsonResponse({"success": True}, status=201)
    except (TypeError, ValueError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@require_http_methods(["DELETE"])
def rrsp_account_item(request, account_id):
    user_id = request.user.id
    acc = RrspAccount.objects.filter(id=account_id, user_id=user_id).first()
    if not acc:
        return JsonResponse({"error": "Account not found"}, status=404)

    acc.delete()

    return JsonResponse({"success": True})


@require_http_methods(["POST"])
def rrsp_reset(request):
    user_id = request.user.id
    reset_user_rrsp_data(user_id)
    return JsonResponse({"success": True})


@require_http_methods(["POST"])
def rrsp_import_csv(request):
    user_id = request.user.id

    overwrite_mode = str(request.POST.get("overwrite_mode") or "").strip().lower()
    overwrite_confirm = str(request.POST.get("overwrite_confirm") or "").strip().upper()

    if overwrite_mode != "replace_all" or overwrite_confirm != "REPLACE":
        return JsonResponse({"error": "RRSP import requires explicit overwrite confirmation. Set overwrite_mode=replace_all and overwrite_confirm=REPLACE."}, status=400)

    if "file" not in request.FILES:
        return JsonResponse({"error": "Missing file upload field: file"}, status=400)

    uploaded_file = request.FILES["file"]
    if not uploaded_file.name:
        return JsonResponse({"error": "No selected file"}, status=400)

    try:
        file_text = uploaded_file.read().decode("utf-8-sig")
    except Exception:
        return JsonResponse({"error": "Failed to read uploaded CSV file"}, status=400)

    try:
        parsed_import = parse_rrsp_import_csv_text(file_text)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    parsed_rows = parsed_import.get("transactions") or []
    setup_opening_balance = parsed_import.get("opening_balance")
    setup_base_year = parsed_import.get("opening_balance_base_year")
    setup_annual_limits = parsed_import.get("annual_limits") or []

    if not parsed_rows and setup_opening_balance is None and not setup_annual_limits:
        return JsonResponse({"error": "No RRSP rows found in uploaded CSV"}, status=400)

    with transaction.atomic():
        reset_user_rrsp_data(user_id)

        setup_opening_balance_applied = False
        setup_base_year_applied = False
        setup_annual_limits_applied = 0

        if setup_opening_balance is not None:
            set_user_rrsp_opening_balance(user_id, float(setup_opening_balance))
            setup_opening_balance_applied = True

        if setup_base_year is not None:
            set_user_rrsp_opening_balance_base_year(user_id, int(setup_base_year))
            setup_base_year_applied = True

        for annual_limit in setup_annual_limits:
            upsert_user_rrsp_annual_limit(user_id, int(annual_limit["year"]), float(annual_limit["annual_limit"]))
            setup_annual_limits_applied += 1

        summary = {"parsed": 0, "inserted": 0, "skipped": 0, "transfers": 0, "inferred_base_year": None}
        if parsed_rows:
            try:
                summary = import_rrsp_transactions_rows(user_id, parsed_rows)
            except ValueError as exc:
                return JsonResponse({"error": str(exc)}, status=400)

        inferred_base_year = summary.get("inferred_base_year")
        if inferred_base_year is not None and not setup_base_year_applied:
            ensure_rrsp_setup_from_import(user_id, inferred_base_year)

    summary["setup_opening_balance_applied"] = setup_opening_balance_applied
    summary["setup_base_year_applied"] = setup_base_year_applied
    summary["setup_annual_limits_applied"] = setup_annual_limits_applied
    summary["setup_rows_parsed"] = (1 if setup_opening_balance is not None else 0) + len(setup_annual_limits)
    return JsonResponse(summary)
