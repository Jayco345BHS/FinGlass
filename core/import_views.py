import csv
import re
from collections import Counter
from decimal import Decimal
from datetime import datetime
from io import BytesIO, StringIO
from pathlib import Path

from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods
from pypdf import PdfReader

from core.credit_card_categories import normalize_credit_card_category
from core.models import CreditCardTransaction, HoldingSnapshot, ImportBatch, ImportBatchRow, Transaction

SUPPORTED_IMPORT_TYPES = {"activities_csv", "tax_pdf"}
EPSILON = Decimal("0.000001")


def _parse_number(value, default=0.0):
    if value is None:
        return default
    cleaned = str(value).strip().replace(",", "")
    is_negative = cleaned.startswith("(") and cleaned.endswith(")")
    cleaned = cleaned.replace("$", "").replace("(", "").replace(")", "")
    if cleaned == "":
        return default
    parsed = float(cleaned)
    return -parsed if is_negative else parsed


def _normalize_date(raw):
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("Missing date")

    for fmt in ("%Y-%m-%d", "%Y-%b-%d"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    raise ValueError(f"Unsupported date format: {raw}")


def _normalize_trade_date(value):
    raw = (value or "").strip()
    if not raw:
        raise ValueError("Missing trade date")

    for fmt in ("%Y-%b-%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    raise ValueError(f"Unsupported date format: {raw}")


def parse_activities_csv_text(csv_text):
    reader = csv.DictReader(StringIO(csv_text))
    rows = []

    for item in reader:
        activity_type = (item.get("activity_type") or "").strip()
        symbol = (item.get("symbol") or "").strip().upper()
        if not activity_type:
            continue

        mapped_type = None
        amount = 0.0
        shares = 0.0

        if activity_type == "Trade":
            sub_type = (item.get("activity_sub_type") or "").strip().upper()
            quantity = _parse_number(item.get("quantity"), 0.0)
            net_cash = _parse_number(item.get("net_cash_amount"), 0.0)
            commission = _parse_number(item.get("commission"), 0.0)

            if sub_type == "BUY":
                mapped_type = "Buy"
                shares = abs(quantity)
                amount = abs(net_cash)
            elif sub_type == "SELL":
                mapped_type = "Sell"
                shares = abs(quantity)
                amount = abs(net_cash)
            else:
                continue
        elif activity_type == "ReturnOfCapital":
            mapped_type = "Return of Capital"
            amount = abs(_parse_number(item.get("net_cash_amount"), 0.0))
            shares = 0.0
            commission = 0.0
        else:
            continue

        if not symbol:
            continue

        trade_date = _normalize_date(item.get("transaction_date", ""))
        amount_per_share = amount / shares if shares else 0.0
        commission = _parse_number(item.get("commission"), 0.0)

        rows.append(
            {
                "security": symbol,
                "trade_date": trade_date,
                "transaction_type": mapped_type,
                "amount": amount,
                "shares": shares,
                "amount_per_share": amount_per_share,
                "commission": commission,
                "source": "activities_csv",
            }
        )

    return rows


def _extract_security_from_filename(filename):
    stem = Path(filename or "").stem.upper()
    match = re.match(r"([A-Z][A-Z0-9.\-]{0,9})", stem)
    if match:
        return match.group(1)
    return ""


def _extract_tax_year(text):
    years = [int(y) for y in re.findall(r"\b(20\d{2})\b", text)]
    years = [y for y in years if 2000 <= y <= 2100]
    if not years:
        return datetime.now().year
    return Counter(years).most_common(1)[0][0]


def _extract_first_amount(text, patterns):
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            value = match.group(1)
            return abs(_parse_number(value, 0.0))
    return 0.0


def _extract_distribution_blocks(text):
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    date_indexes = []
    for idx, line in enumerate(lines):
        if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", line):
            date_indexes.append(idx)

    blocks = []
    for idx in range(len(date_indexes) - 1):
        record_idx = date_indexes[idx]
        payment_idx = date_indexes[idx + 1]
        if payment_idx - record_idx > 6:
            continue

        record_date = lines[record_idx]

        if idx + 2 < len(date_indexes):
            next_date_idx = date_indexes[idx + 2]
            j = next_date_idx - 1
            pre_date_numeric = 0
            while (
                j > payment_idx
                and pre_date_numeric < 2
                and re.fullmatch(r"[\d,]+(?:\.\d+)?", lines[j])
            ):
                pre_date_numeric += 1
                j -= 1
            stop_idx = next_date_idx - pre_date_numeric
        else:
            stop_idx = len(lines)

        value_lines = lines[payment_idx + 1 : stop_idx]
        values = []
        for value_line in value_lines:
            if re.fullmatch(r"[\d,]+(?:\.\d+)?", value_line):
                values.append(_parse_number(value_line, 0.0))
            elif values:
                break

        if values:
            blocks.append(
                {
                    "record_date": record_date,
                    "payment_date": lines[payment_idx],
                    "values": values,
                }
            )

    return blocks


def _guess_roc_from_values(values):
    if not values:
        return 0.0
    total_cash = values[0]
    meaningful = list(values)
    while meaningful and abs(meaningful[-1] - total_cash) < 0.0001:
        meaningful.pop()
    if len(meaningful) < 2:
        return 0.0

    roc_candidate = meaningful[-2]
    next_val = meaningful[-1]
    if roc_candidate < 0.00001:
        return 0.0

    ratio = next_val / roc_candidate if roc_candidate > 0 else 0.0
    if 1.0 < ratio <= 1.5:
        return roc_candidate
    if ratio > 1.5 and len(meaningful) >= 3:
        prev_val = meaningful[-3]
        if prev_val > 0 and roc_candidate < prev_val * 0.5:
            return roc_candidate
    return 0.0


def _extract_non_cash_mentions(text):
    mentions = []
    for match in re.finditer(
        r"non[-\s]?cash\s+distribution[^$\d]*\$\s*([\d,]+(?:\.\d+)?)",
        text,
        flags=re.IGNORECASE,
    ):
        mentions.append(abs(_parse_number(match.group(1), 0.0)))
    return mentions


def _guess_non_cash_from_values(values, non_cash_mentions):
    positive = [v for v in values if v > 0.0]
    if not positive:
        return 0.0
    for mention in non_cash_mentions:
        for value in positive:
            if abs(value - mention) <= 0.0002:
                return value
    if len(positive) >= 3:
        cash = positive[0]
        non_cash = positive[1]
        total = positive[2]
        if abs((cash + non_cash) - total) <= 0.002:
            return non_cash
    return 0.0


def parse_tax_pdf_bytes(pdf_bytes, filename):
    reader = PdfReader(BytesIO(pdf_bytes))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)

    security = _extract_security_from_filename(filename)
    tax_year = _extract_tax_year(text)
    trade_date = f"{tax_year}-12-31"

    roc_amount = _extract_first_amount(
        text,
        [
            r"return\s+of\s+capital[^\d\-]*([\d,]*\.\d+)",
            r"roc[^\d\-]*([\d,]*\.\d+)",
        ],
    )
    rcg_amount = _extract_first_amount(
        text,
        [
            r"reinvested\s+capital\s+gains?(?:\s+distribution)?[^\d\-]*([\d,]*\.\d+)",
            r"capital\s+gains?\s+distribution[^\d\-]*([\d,]*\.\d+)",
        ],
    )

    rows = []
    distribution_blocks = _extract_distribution_blocks(text)
    non_cash_mentions = _extract_non_cash_mentions(text)

    for block in distribution_blocks:
        guessed_roc = _guess_roc_from_values(block["values"])
        guessed_non_cash = _guess_non_cash_from_values(block["values"], non_cash_mentions)

        if guessed_roc > 0:
            rows.append(
                {
                    "security": security,
                    "trade_date": block["record_date"],
                    "transaction_type": "Return of Capital",
                    "amount": guessed_roc,
                    "shares": 0.0,
                    "amount_per_share": 0.0,
                    "commission": 0.0,
                    "source": "tax_pdf",
                }
            )

        if guessed_non_cash > 0:
            rows.append(
                {
                    "security": security,
                    "trade_date": block["record_date"],
                    "transaction_type": "Reinvested Capital Gains Distribution",
                    "amount": guessed_non_cash,
                    "shares": 0.0,
                    "amount_per_share": 0.0,
                    "commission": 0.0,
                    "source": "tax_pdf",
                }
            )

    if not rows and roc_amount > 0:
        rows.append(
            {
                "security": security,
                "trade_date": trade_date,
                "transaction_type": "Return of Capital",
                "amount": roc_amount,
                "shares": 0.0,
                "amount_per_share": 0.0,
                "commission": 0.0,
                "source": "tax_pdf",
            }
        )

    has_rcg = any(row["transaction_type"] == "Reinvested Capital Gains Distribution" for row in rows)
    if rcg_amount > 0 and not has_rcg:
        rows.append(
            {
                "security": security,
                "trade_date": trade_date,
                "transaction_type": "Reinvested Capital Gains Distribution",
                "amount": rcg_amount,
                "shares": 0.0,
                "amount_per_share": 0.0,
                "commission": 0.0,
                "source": "tax_pdf",
            }
        )

    return rows


def _extract_iso_date(value):
    match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", value or "")
    return match.group(1) if match else None


def _extract_as_of_date(csv_text, filename=""):
    for line in csv_text.splitlines():
        maybe_date = _extract_iso_date(line)
        if maybe_date:
            return maybe_date
    fallback = _extract_iso_date(filename)
    if fallback:
        return fallback
    return datetime.now().strftime("%Y-%m-%d")


def parse_holdings_csv_text(csv_text, filename=""):
    as_of = _extract_as_of_date(csv_text, filename)
    rows = []
    reader = csv.DictReader(StringIO(csv_text))

    for item in reader:
        symbol = (item.get("Symbol") or "").strip().upper()
        account_number = (item.get("Account Number") or "").strip()
        account_name = (item.get("Account Name") or "").strip()
        if not symbol or not account_number or not account_name:
            continue

        rows.append(
            {
                "as_of": as_of,
                "account_name": account_name,
                "account_type": (item.get("Account Type") or "").strip(),
                "account_classification": (item.get("Account Classification") or "").strip(),
                "account_number": account_number,
                "symbol": symbol,
                "exchange": (item.get("Exchange") or "").strip(),
                "mic": (item.get("MIC") or "").strip(),
                "security_name": (item.get("Name") or "").strip(),
                "security_type": (item.get("Security Type") or "").strip(),
                "quantity": _parse_number(item.get("Quantity"), 0.0),
                "market_price": _parse_number(item.get("Market Price"), 0.0),
                "market_price_currency": (item.get("Market Price Currency") or "").strip(),
                "book_value_cad": _parse_number(item.get("Book Value (CAD)"), 0.0),
                "market_value": _parse_number(item.get("Market Value"), 0.0),
                "market_value_currency": (item.get("Market Value Currency") or "").strip(),
                "unrealized_return": _parse_number(item.get("Market Unrealized Returns"), 0.0),
            }
        )

    return rows


def parse_rogers_credit_csv_text(csv_text):
    def normalize_header(header):
        return re.sub(r"[^a-z0-9]", "", str(header or "").lower())

    def get_value(row, *candidate_headers):
        for header in candidate_headers:
            value = row.get(normalize_header(header), "")
            if value is not None and str(value).strip() != "":
                return str(value).strip()
        return ""

    rows = []
    reader = csv.DictReader(StringIO(csv_text))

    for item in reader:
        normalized_item = {
            normalize_header(key): value for key, value in (item or {}).items() if key is not None
        }

        tx_date = get_value(normalized_item, "Date", "Transaction Date")
        if not tx_date:
            continue

        amount = _parse_number(get_value(normalized_item, "Amount"), 0.0)
        card_number = get_value(normalized_item, "Transaction Card Number", "Card Number")
        card_last4 = card_number[-4:] if len(card_number) >= 4 else ""
        merchant_category = normalize_credit_card_category(
            get_value(normalized_item, "Merchant Category", "Merchant Category Description")
        )

        rows.append(
            {
                "provider": "rogers_bank",
                "transaction_date": tx_date,
                "posted_date": get_value(normalized_item, "Posted Date"),
                "reference_number": get_value(normalized_item, "Reference Number").replace('"', ""),
                "activity_type": get_value(normalized_item, "Activity Type"),
                "status": get_value(normalized_item, "Status", "Activity Status"),
                "card_last4": card_last4,
                "merchant_category": merchant_category,
                "merchant_name": get_value(normalized_item, "Merchant Name"),
                "merchant_city": get_value(normalized_item, "Merchant City"),
                "merchant_region": get_value(normalized_item, "Merchant State/Province", "Merchant State or Province"),
                "merchant_country": get_value(normalized_item, "Merchant Country", "Merchant Country Code"),
                "merchant_postal": get_value(normalized_item, "Merchant Postal Code/Zip", "Merchant Postal Code"),
                "amount": amount,
                "rewards": _parse_number(get_value(normalized_item, "Rewards"), 0.0),
                "cardholder_name": get_value(normalized_item, "Name on Card"),
            }
        )

    return rows


def parse_upload(import_type, filename, file_bytes):
    if import_type == "activities_csv":
        return parse_activities_csv_text(file_bytes.decode("utf-8-sig"))
    if import_type == "tax_pdf":
        return parse_tax_pdf_bytes(file_bytes, filename)
    raise ValueError("Unsupported import type")


def _to_decimal(value):
    return Decimal(str(value or 0))


def _import_transactions_rows(parsed_rows, user_id):
    inserted = 0
    for tx in parsed_rows:
        amount = _to_decimal(tx["amount"])
        shares = _to_decimal(tx["shares"])
        commission = _to_decimal(tx["commission"])
        memo = tx.get("memo", "")

        memo_filter = {"memo": memo} if memo else {"memo__in": ["", None]}
        exists = Transaction.objects.filter(
            user_id=user_id,
            security=tx["security"],
            trade_date=tx["trade_date"],
            transaction_type=tx["transaction_type"],
            amount__gte=amount - EPSILON,
            amount__lte=amount + EPSILON,
            shares__gte=shares - EPSILON,
            shares__lte=shares + EPSILON,
            commission__gte=commission - EPSILON,
            commission__lte=commission + EPSILON,
            **memo_filter,
        ).exists()
        if exists:
            continue

        Transaction.objects.create(
            user_id=user_id,
            security=tx["security"],
            trade_date=tx["trade_date"],
            transaction_type=tx["transaction_type"],
            amount=amount,
            shares=shares,
            amount_per_share=_to_decimal(tx["amount_per_share"]),
            commission=commission,
            memo=memo,
            source=tx["source"],
        )
        inserted += 1

    return {"parsed": len(parsed_rows), "inserted": inserted}


def _import_holdings_rows(parsed_rows, source_filename, user_id):
    inserted = 0
    updated = 0

    for row in parsed_rows:
        _, created = HoldingSnapshot.objects.update_or_create(
            user_id=user_id,
            as_of=row["as_of"],
            account_number=row["account_number"],
            symbol=row["symbol"],
            defaults={
                "account_name": row["account_name"],
                "account_type": row.get("account_type", ""),
                "account_classification": row.get("account_classification", ""),
                "exchange": row.get("exchange", ""),
                "mic": row.get("mic", ""),
                "security_name": row.get("security_name", ""),
                "security_type": row.get("security_type", ""),
                "quantity": _to_decimal(row.get("quantity", 0.0)),
                "market_price": _to_decimal(row.get("market_price", 0.0)),
                "market_price_currency": row.get("market_price_currency", ""),
                "book_value_cad": _to_decimal(row.get("book_value_cad", 0.0)),
                "market_value": _to_decimal(row.get("market_value", 0.0)),
                "market_value_currency": row.get("market_value_currency", ""),
                "unrealized_return": _to_decimal(row.get("unrealized_return", 0.0)),
                "source_filename": source_filename,
                "imported_at": timezone.now(),
            },
        )

        if created:
            inserted += 1
        else:
            updated += 1

    unique_as_of = sorted({row["as_of"] for row in parsed_rows})
    return {
        "parsed": len(parsed_rows),
        "inserted": inserted,
        "updated": updated,
        "as_of": unique_as_of[-1] if unique_as_of else None,
    }


def _import_rogers_credit_rows(parsed_rows, source_filename, user_id):
    inserted = 0
    for row in parsed_rows:
        amount = _to_decimal(row["amount"])
        merchant_name = row.get("merchant_name", "")
        posted_date = row.get("posted_date") or None
        merchant_filter = {"merchant_name": merchant_name} if merchant_name else {"merchant_name__in": ["", None]}
        existing = CreditCardTransaction.objects.filter(
            user_id=user_id,
            provider=row["provider"],
            transaction_date=row["transaction_date"],
            posted_date=posted_date,
            card_last4=row.get("card_last4", ""),
            reference_number=row.get("reference_number", ""),
            amount__gte=amount - EPSILON,
            amount__lte=amount + EPSILON,
            **merchant_filter,
        ).exists()
        if existing:
            continue

        CreditCardTransaction.objects.create(
            user_id=user_id,
            provider=row["provider"],
            transaction_date=row["transaction_date"],
            posted_date=posted_date,
            reference_number=row.get("reference_number", ""),
            activity_type=row.get("activity_type", ""),
            status=row.get("status", ""),
            card_last4=row.get("card_last4", ""),
            merchant_category=row.get("merchant_category", ""),
            merchant_name=merchant_name,
            merchant_city=row.get("merchant_city", ""),
            merchant_region=row.get("merchant_region", ""),
            merchant_country=row.get("merchant_country", ""),
            merchant_postal=row.get("merchant_postal", ""),
            amount=amount,
            rewards=_to_decimal(row.get("rewards", 0.0)),
            is_hidden=False,
            cardholder_name=row.get("cardholder_name", ""),
            source_filename=source_filename,
            imported_at=timezone.now(),
        )
        inserted += 1

    return {"parsed": len(parsed_rows), "inserted": inserted}


def _create_import_batch(source_type, source_filename, rows, user_id):
    batch = ImportBatch.objects.create(user_id=user_id, source_type=source_type, source_filename=source_filename, status="staged")
    batch_id = batch.id

    for idx, row in enumerate(rows, start=1):
        ImportBatchRow.objects.create(
            batch_id=batch_id,
            row_order=idx,
            security=row["security"],
            trade_date=row["trade_date"],
            transaction_type=row["transaction_type"],
            amount=_to_decimal(row["amount"]),
            shares=_to_decimal(row["shares"]),
            amount_per_share=_to_decimal(row.get("amount_per_share", 0.0)),
            commission=_to_decimal(row.get("commission", 0.0)),
            source=row.get("source", source_type),
        )

    return batch_id


def _get_batch(batch_id, user_id):
    batch = ImportBatch.objects.filter(id=batch_id, user_id=user_id).values().first()
    if not batch:
        return None
    rows = list(ImportBatchRow.objects.filter(batch_id=batch_id).order_by("row_order", "id").values())
    return {"batch": batch, "rows": rows}


def _update_batch_row(batch_id, row_id, payload, user_id):
    row = (
        ImportBatchRow.objects.select_related("batch")
        .filter(id=row_id, batch_id=batch_id, batch__user_id=user_id)
        .first()
    )
    if not row:
        return False

    security = str(payload.get("security") or "").strip().upper()
    trade_date = _normalize_date(str(payload.get("trade_date") or ""))
    transaction_type = str(payload.get("transaction_type") or "").strip()
    amount = float(payload.get("amount") or 0)
    shares = float(payload.get("shares") or 0)
    commission = float(payload.get("commission") or 0)
    amount_per_share = amount / shares if shares else 0.0

    row.security = security
    row.trade_date = trade_date
    row.transaction_type = transaction_type
    row.amount = _to_decimal(amount)
    row.shares = _to_decimal(shares)
    row.amount_per_share = _to_decimal(amount_per_share)
    row.commission = _to_decimal(commission)
    row.save(update_fields=["security", "trade_date", "transaction_type", "amount", "shares", "amount_per_share", "commission"])
    return True


def _delete_batch_row(batch_id, row_id, user_id):
    deleted, _ = ImportBatchRow.objects.filter(id=row_id, batch_id=batch_id, batch__user_id=user_id).delete()
    return deleted > 0


def _commit_batch(batch_id, user_id):
    batch = ImportBatch.objects.filter(id=batch_id, user_id=user_id).first()
    if not batch:
        return None
    if batch.status == "committed":
        return {"inserted": 0, "parsed": 0, "already_committed": True}

    rows = list(
        ImportBatchRow.objects.filter(batch_id=batch_id)
        .order_by("row_order", "id")
        .values("security", "trade_date", "transaction_type", "amount", "shares", "amount_per_share", "commission", "source")
    )

    parsed_rows = [
        {
            "security": row["security"],
            "trade_date": row["trade_date"],
            "transaction_type": row["transaction_type"],
            "amount": row["amount"],
            "shares": row["shares"],
            "amount_per_share": row["amount_per_share"],
            "commission": row["commission"],
            "source": row["source"],
        }
        for row in rows
    ]

    summary = _import_transactions_rows(parsed_rows, user_id)

    batch.status = "committed"
    batch.committed_at = timezone.now()
    batch.save(update_fields=["status", "committed_at"])
    return summary


@require_http_methods(["POST"])
def import_holdings_csv(request):
    user_id = request.user.id
    if "file" not in request.FILES:
        return JsonResponse({"error": "Missing file upload field: file"}, status=400)

    uploaded_file = request.FILES["file"]
    if not uploaded_file.name:
        return JsonResponse({"error": "No selected file"}, status=400)

    file_text = uploaded_file.read().decode("utf-8-sig")
    parsed_rows = parse_holdings_csv_text(file_text, filename=uploaded_file.name)
    if not parsed_rows:
        return JsonResponse({"error": "No holdings rows found in uploaded CSV"}, status=400)

    summary = _import_holdings_rows(parsed_rows, uploaded_file.name, user_id)
    return JsonResponse(summary)


@require_http_methods(["POST"])
def import_rogers_credit_csv(request):
    user_id = request.user.id
    if "file" not in request.FILES:
        return JsonResponse({"error": "Missing file upload field: file"}, status=400)

    uploaded_files = [file for file in request.FILES.getlist("file") if file and file.name]
    if not uploaded_files:
        return JsonResponse({"error": "No selected file"}, status=400)

    total_parsed = 0
    total_inserted = 0
    files_processed = 0

    for uploaded_file in uploaded_files:
        file_text = uploaded_file.read().decode("utf-8-sig")
        parsed_rows = parse_rogers_credit_csv_text(file_text)
        if not parsed_rows:
            continue

        summary = _import_rogers_credit_rows(parsed_rows, uploaded_file.name, user_id)
        total_parsed += int(summary.get("parsed") or 0)
        total_inserted += int(summary.get("inserted") or 0)
        files_processed += 1

    if total_parsed == 0:
        return JsonResponse({"error": "No credit card rows found in uploaded CSV file(s)"}, status=400)

    return JsonResponse({"parsed": total_parsed, "inserted": total_inserted, "files": files_processed})


@require_http_methods(["POST"])
def create_import_review(request):
    user_id = request.user.id
    if "file" not in request.FILES:
        return JsonResponse({"error": "Missing file upload field: file"}, status=400)

    import_type = str(request.POST.get("import_type") or "").strip()
    if import_type not in SUPPORTED_IMPORT_TYPES:
        return JsonResponse({"error": "Unsupported import_type"}, status=400)

    uploaded_file = request.FILES["file"]
    if not uploaded_file.name:
        return JsonResponse({"error": "No selected file"}, status=400)

    file_bytes = uploaded_file.read()
    try:
        rows = parse_upload(import_type, uploaded_file.name, file_bytes)
    except Exception as exc:
        return JsonResponse({"error": f"Failed to parse import file: {exc}"}, status=400)

    if not rows:
        return JsonResponse({"error": "No importable transactions found in file"}, status=400)

    batch_id = _create_import_batch(import_type, uploaded_file.name, rows, user_id)
    batch_data = _get_batch(batch_id, user_id)
    return JsonResponse(batch_data, status=201)


@require_GET
def get_import_review(request, batch_id):
    user_id = request.user.id
    batch_data = _get_batch(batch_id, user_id)
    if not batch_data:
        return JsonResponse({"error": "Import batch not found"}, status=404)
    return JsonResponse(batch_data)


@require_http_methods(["PUT"])
def update_import_review_row(request, batch_id, row_id):
    user_id = request.user.id
    try:
        payload = _read_json(request)
    except Exception:
        payload = {}

    try:
        ok = _update_batch_row(batch_id, row_id, payload, user_id)
    except Exception as exc:
        return JsonResponse({"error": f"Invalid row data: {exc}"}, status=400)

    if not ok:
        return JsonResponse({"error": "Import row not found"}, status=404)
    return JsonResponse({"updated": 1})


@require_http_methods(["PUT", "DELETE"])
def import_review_row_item(request, batch_id, row_id):
    if request.method == "PUT":
        return update_import_review_row(request, batch_id, row_id)
    return delete_import_review_row(request, batch_id, row_id)


@require_http_methods(["DELETE"])
def delete_import_review_row(request, batch_id, row_id):
    user_id = request.user.id
    ok = _delete_batch_row(batch_id, row_id, user_id)
    if not ok:
        return JsonResponse({"error": "Import row not found"}, status=404)
    return JsonResponse({"deleted": 1})


@require_http_methods(["POST"])
def commit_import_review(request, batch_id):
    user_id = request.user.id
    summary = _commit_batch(batch_id, user_id)
    if summary is None:
        return JsonResponse({"error": "Import batch not found"}, status=404)
    return JsonResponse(summary)


@require_http_methods(["POST"])
def commit_batch_endpoint(request, batch_id):
    return commit_import_review(request, batch_id)


@require_GET
def download_template(request, template_type):
    templates = {
        "transactions": {
            "filename": "transactions_template.csv",
            "content": """transaction_date,symbol,activity_type,activity_sub_type,quantity,net_cash_amount,commission
2024-01-15,AAPL,Trade,BUY,10,1500.00,4.95
2024-02-20,AAPL,Trade,SELL,5,800.00,4.95
2024-03-10,VDY,ReturnOfCapital,,0,25.50,0.00
2024-04-01,MSFT,Trade,BUY,8,2400.00,4.95""",
        },
        "holdings": {
            "filename": "holdings_template.csv",
            "content": """Symbol,Account Number,Account Name,Account Type,Account Classification,Quantity,Market Price,Market Price Currency,Book Value (CAD),Market Value,Market Value Currency,Market Unrealized Returns,Exchange,MIC,Name,Security Type
AAPL,12345678,My TFSA,TFSA,Tax Advantaged,10,150.00,USD,1200.00,1500.00,CAD,300.00,NASDAQ,XNAS,Apple Inc,Stock
VDY,12345678,My TFSA,TFSA,Tax Advantaged,50,35.00,CAD,1600.00,1750.00,CAD,150.00,TSX,XTSE,Vanguard FTSE Canadian High Dividend Yield Index ETF,ETF""",
        },
        "credit-card": {
            "filename": "credit_card_template.csv",
            "content": """Transaction Date,Posted Date,Description,Amount,Category
2024-01-15,2024-01-16,GROCERY STORE,-125.50,Groceries
2024-01-20,2024-01-21,GAS STATION,-60.00,Gas
2024-02-01,2024-02-02,RESTAURANT,-45.00,Dining
2024-02-10,2024-02-11,ONLINE SHOPPING,-89.99,Shopping""",
        },
    }

    template = templates.get(template_type)
    if not template:
        return JsonResponse({"error": "Template not found"}, status=404)

    response = HttpResponse(template["content"], content_type="text/csv")
    response["Content-Disposition"] = f"attachment; filename={template['filename']}"
    return response


def _read_json(request):
    try:
        if not request.body:
            return {}
        import json

        return json.loads(request.body.decode("utf-8"))
    except Exception:
        return {}
