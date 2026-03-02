import json
from datetime import datetime

from django.db import transaction
from django.db.models import F
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from django_apps.core.models import FhsaAccount, FhsaContribution
from django_apps.core.services.fhsa_import_service import (
    import_fhsa_transactions_rows,
    parse_fhsa_import_csv_text,
    validate_fhsa_import_rows,
)
from django_apps.core.services.fhsa_service import (
    FHSA_FIRST_YEAR,
    FHSA_TRACKED_OPENING_ROOM_CAP,
    can_accept_new_fhsa_contributions,
    create_fhsa_transfer,
    ensure_fhsa_setup_from_import,
    get_fhsa_summary,
    get_user_fhsa_opening_balance,
    get_user_fhsa_opening_balance_base_year,
    is_user_fhsa_opening_balance_configured,
    reset_user_fhsa_data,
    set_user_fhsa_opening_balance,
    set_user_fhsa_opening_balance_base_year,
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


def _require_opening_balance_configured(user_id):
    if not is_user_fhsa_opening_balance_configured(user_id):
        return JsonResponse({"error": "Set FHSA available contribution room first"}, status=400)
    return None


@require_http_methods(["GET"])
def fhsa_summary(request):
    user_id = request.user.id
    summary = get_fhsa_summary(user_id)
    return JsonResponse(summary)


@require_http_methods(["POST"])
def fhsa_accounts(request):
    user_id = request.user.id
    data = _read_json(request)

    setup_error = _require_opening_balance_configured(user_id)
    if setup_error is not None:
        return setup_error

    account_name = (data.get("account_name") or "").strip()
    if not account_name:
        return JsonResponse({"error": "account_name required"}, status=400)

    try:
        account = FhsaAccount.objects.create(user_id=user_id, account_name=account_name, opening_balance=0)
        return JsonResponse({"id": account.id}, status=201)
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@require_http_methods(["GET", "PUT"])
def fhsa_opening_balance(request):
    user_id = request.user.id
    if request.method == "GET":
        balance = get_user_fhsa_opening_balance(user_id)
        base_year = get_user_fhsa_opening_balance_base_year(user_id)
        configured = is_user_fhsa_opening_balance_configured(user_id)
        return JsonResponse({"opening_balance": balance, "base_year": base_year, "configured": configured})

    data = _read_json(request)
    try:
        opening_balance = float(data.get("opening_balance") or 0)
    except (TypeError, ValueError):
        return JsonResponse({"error": "opening_balance must be a number"}, status=400)

    if opening_balance < 0:
        return JsonResponse({"error": "opening_balance must be >= 0"}, status=400)

    if opening_balance > FHSA_TRACKED_OPENING_ROOM_CAP:
        return JsonResponse({"error": f"opening_balance must be <= {int(FHSA_TRACKED_OPENING_ROOM_CAP)}"}, status=400)

    set_user_fhsa_opening_balance(user_id, opening_balance)
    return JsonResponse({"success": True})


@require_http_methods(["PUT"])
def fhsa_opening_balance_base_year(request):
    user_id = request.user.id
    data = _read_json(request)

    raw_year = data.get("base_year")
    try:
        base_year = int(str(raw_year))
    except (TypeError, ValueError):
        return JsonResponse({"error": "base_year must be an integer"}, status=400)

    current_year = datetime.now().year
    if base_year < FHSA_FIRST_YEAR or base_year > current_year:
        return JsonResponse({"error": f"base_year must be between {FHSA_FIRST_YEAR} and {current_year}"}, status=400)

    set_user_fhsa_opening_balance_base_year(user_id, base_year)
    return JsonResponse({"success": True})


@require_http_methods(["GET"])
def fhsa_transactions(request):
    user_id = request.user.id
    rows = list(
        FhsaContribution.objects.filter(user_id=user_id)
        .select_related("fhsa_account")
        .order_by("-contribution_date", "-id")
        .values(
            "id",
            "contribution_date",
            "contribution_type",
            "amount",
            "is_qualifying_withdrawal",
            "memo",
            "created_at",
            "fhsa_account_id",
            account_name=F("fhsa_account__account_name"),
        )
    )
    return JsonResponse(rows, safe=False)


@require_http_methods(["PUT", "DELETE"])
def fhsa_transaction_item(request, transaction_id):
    user_id = request.user.id
    if request.method == "DELETE":
        deleted, _ = FhsaContribution.objects.filter(id=transaction_id, user_id=user_id).delete()
        if deleted == 0:
            return JsonResponse({"error": "Transaction not found"}, status=404)
        return JsonResponse({"deleted": 1})

    data = _read_json(request)
    fhsa_account_id = data.get("fhsa_account_id")
    contribution_date = (data.get("contribution_date") or "").strip()
    contribution_type = (data.get("contribution_type") or "").strip()
    is_qualifying_withdrawal = _parse_bool(data.get("is_qualifying_withdrawal", False))
    memo = (data.get("memo") or "").strip()

    try:
        amount = float(data.get("amount") or 0)
    except (TypeError, ValueError):
        return JsonResponse({"error": "amount must be a number"}, status=400)

    try:
        normalized_account_id = int(str(fhsa_account_id))
    except (TypeError, ValueError):
        return JsonResponse({"error": "fhsa_account_id must be an integer"}, status=400)

    if not contribution_date:
        return JsonResponse({"error": "contribution_date required"}, status=400)
    if contribution_type not in ("Deposit", "Withdrawal"):
        return JsonResponse({"error": "contribution_type must be 'Deposit' or 'Withdrawal'"}, status=400)
    if contribution_type != "Withdrawal" and is_qualifying_withdrawal:
        return JsonResponse({"error": "is_qualifying_withdrawal can only be true for Withdrawal"}, status=400)
    if amount <= 0:
        return JsonResponse({"error": "amount must be > 0"}, status=400)

    tx_row = FhsaContribution.objects.filter(id=transaction_id, user_id=user_id).first()
    if not tx_row:
        return JsonResponse({"error": "Transaction not found"}, status=404)

    account = FhsaAccount.objects.filter(id=normalized_account_id, user_id=user_id).first()
    if not account:
        return JsonResponse({"error": "Account not found"}, status=404)

    tx_row.fhsa_account_id = normalized_account_id
    tx_row.contribution_date = contribution_date
    tx_row.amount = amount
    tx_row.contribution_type = contribution_type
    tx_row.is_qualifying_withdrawal = bool(is_qualifying_withdrawal)
    tx_row.memo = memo
    tx_row.save(
        update_fields=[
            "fhsa_account",
            "contribution_date",
            "amount",
            "contribution_type",
            "is_qualifying_withdrawal",
            "memo",
        ]
    )

    return JsonResponse({"updated": 1})


@require_http_methods(["POST"])
def fhsa_contributions(request):
    user_id = request.user.id
    data = _read_json(request)

    setup_error = _require_opening_balance_configured(user_id)
    if setup_error is not None:
        return setup_error

    fhsa_account_id = data.get("fhsa_account_id")
    contribution_type = (data.get("contribution_type") or "Deposit").strip()
    is_qualifying_withdrawal = _parse_bool(data.get("is_qualifying_withdrawal", False))
    memo = (data.get("memo") or "").strip()
    contribution_date = (data.get("contribution_date") or "").strip()

    try:
        amount = float(data.get("amount") or 0)
    except (TypeError, ValueError):
        return JsonResponse({"error": "amount must be a number"}, status=400)

    if not all([fhsa_account_id, amount > 0, contribution_date]):
        return JsonResponse({"error": "Missing required fields"}, status=400)
    if contribution_type not in ("Deposit", "Withdrawal"):
        return JsonResponse({"error": "contribution_type must be 'Deposit' or 'Withdrawal'"}, status=400)
    if contribution_type != "Withdrawal" and is_qualifying_withdrawal:
        return JsonResponse({"error": "is_qualifying_withdrawal can only be true for Withdrawal"}, status=400)

    if contribution_type == "Deposit":
        can_contribute, lock_info = can_accept_new_fhsa_contributions(user_id)
        if not can_contribute:
            return JsonResponse({"error": str(lock_info.get("message") or "FHSA contributions are currently locked")}, status=400)

    acc = FhsaAccount.objects.filter(id=fhsa_account_id, user_id=user_id).first()
    if not acc:
        return JsonResponse({"error": "Account not found"}, status=404)

    if contribution_type == "Deposit":
        summary = get_fhsa_summary(user_id)
        if amount > float(summary.get("total_remaining") or 0):
            return JsonResponse({"error": "Contribution exceeds tracked FHSA contribution room"}, status=400)

    try:
        FhsaContribution.objects.create(
            user_id=user_id,
            fhsa_account_id=fhsa_account_id,
            contribution_date=contribution_date,
            amount=amount,
            contribution_type=contribution_type,
            is_qualifying_withdrawal=(contribution_type == "Withdrawal" and bool(is_qualifying_withdrawal)),
            memo=memo,
        )
        return JsonResponse({"success": True}, status=201)
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@require_http_methods(["POST"])
def fhsa_transfers(request):
    user_id = request.user.id
    data = _read_json(request)

    setup_error = _require_opening_balance_configured(user_id)
    if setup_error is not None:
        return setup_error

    can_contribute, lock_info = can_accept_new_fhsa_contributions(user_id)
    if not can_contribute:
        return JsonResponse({"error": str(lock_info.get("message") or "FHSA contributions are currently locked")}, status=400)

    try:
        amount = float(data.get("amount") or 0)
    except (TypeError, ValueError):
        return JsonResponse({"error": "amount must be a number"}, status=400)

    try:
        from_fhsa_account_id = int(str(data.get("from_fhsa_account_id")))
        to_fhsa_account_id = int(str(data.get("to_fhsa_account_id")))
    except (TypeError, ValueError):
        return JsonResponse({"error": "from_fhsa_account_id and to_fhsa_account_id must be integers"}, status=400)

    try:
        create_fhsa_transfer(
            user_id=user_id,
            from_fhsa_account_id=from_fhsa_account_id,
            to_fhsa_account_id=to_fhsa_account_id,
            transfer_date=(data.get("transfer_date") or "").strip(),
            amount=amount,
            memo=(data.get("memo") or "").strip(),
        )
        return JsonResponse({"success": True}, status=201)
    except (TypeError, ValueError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@require_http_methods(["DELETE"])
def fhsa_account_item(request, account_id):
    user_id = request.user.id
    acc = FhsaAccount.objects.filter(id=account_id, user_id=user_id).first()
    if not acc:
        return JsonResponse({"error": "Account not found"}, status=404)

    acc.delete()
    return JsonResponse({"success": True})


@require_http_methods(["POST"])
def fhsa_reset(request):
    user_id = request.user.id
    reset_user_fhsa_data(user_id)
    return JsonResponse({"success": True})


@require_http_methods(["POST"])
def fhsa_import_csv(request):
    user_id = request.user.id

    overwrite_mode = str(request.POST.get("overwrite_mode") or "").strip().lower()
    overwrite_confirm = str(request.POST.get("overwrite_confirm") or "").strip().upper()

    if overwrite_mode != "replace_all" or overwrite_confirm != "REPLACE":
        return JsonResponse(
            {
                "error": (
                    "FHSA import requires explicit overwrite confirmation. "
                    "Set overwrite_mode=replace_all and overwrite_confirm=REPLACE."
                )
            },
            status=400,
        )

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
        parsed_import = parse_fhsa_import_csv_text(file_text)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    parsed_rows = parsed_import.get("transactions") or []
    setup_opening_balance = parsed_import.get("opening_balance")
    setup_base_year = parsed_import.get("opening_balance_base_year")

    try:
        validate_fhsa_import_rows(parsed_rows, opening_base_year=setup_base_year)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    if not parsed_rows and setup_opening_balance is None:
        return JsonResponse({"error": "No FHSA rows found in uploaded CSV"}, status=400)

    with transaction.atomic():
        reset_user_fhsa_data(user_id)

        setup_opening_balance_applied = False
        setup_base_year_applied = False

        if setup_opening_balance is not None:
            set_user_fhsa_opening_balance(user_id, float(setup_opening_balance))
            setup_opening_balance_applied = True

        if setup_base_year is not None:
            set_user_fhsa_opening_balance_base_year(user_id, int(setup_base_year))
            setup_base_year_applied = True

        summary = {
            "parsed": 0,
            "inserted": 0,
            "skipped": 0,
            "transfers": 0,
            "inferred_base_year": None,
        }
        if parsed_rows:
            try:
                summary = import_fhsa_transactions_rows(user_id, parsed_rows)
            except ValueError as exc:
                return JsonResponse({"error": str(exc)}, status=400)

        inferred_base_year = summary.get("inferred_base_year")
        if inferred_base_year is not None and not setup_base_year_applied:
            ensure_fhsa_setup_from_import(user_id, inferred_base_year)

    summary["setup_opening_balance_applied"] = setup_opening_balance_applied
    summary["setup_base_year_applied"] = setup_base_year_applied
    summary["setup_rows_parsed"] = (1 if setup_opening_balance is not None else 0)
    return JsonResponse(summary)
