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


def parse_rogers_credit_csv_text(csv_text, card_label=None):
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
                "card_label": card_label or "Rogers Bank",
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
            card_label=row.get("card_label") or None,
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

    card_label = str(request.POST.get("card_label") or "").strip() or None

    total_parsed = 0
    total_inserted = 0
    files_processed = 0

    for uploaded_file in uploaded_files:
        file_text = uploaded_file.read().decode("utf-8-sig")
        parsed_rows = parse_rogers_credit_csv_text(file_text, card_label=card_label)
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


# Export Views

def _export_to_csv(headers, rows):
    """Helper function to generate CSV content from headers and rows."""
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    return output.getvalue()


@require_GET
def export_transactions(request):
    """Export all ACB transactions to CSV."""
    user_id = request.user.id
    transactions = Transaction.objects.filter(user_id=user_id).order_by("trade_date", "id").values(
        "security", "trade_date", "transaction_type", "amount", "shares",
        "amount_per_share", "commission", "memo", "source", "created_at"
    )

    headers = [
        "Security", "Trade Date", "Transaction Type", "Amount", "Shares",
        "Amount Per Share", "Commission", "Memo", "Source", "Created At"
    ]

    rows = [
        [
            tx["security"],
            tx["trade_date"].strftime("%Y-%m-%d") if tx["trade_date"] else "",
            tx["transaction_type"],
            str(tx["amount"]),
            str(tx["shares"]),
            str(tx["amount_per_share"]) if tx["amount_per_share"] else "",
            str(tx["commission"]),
            tx["memo"] or "",
            tx["source"],
            tx["created_at"].strftime("%Y-%m-%d %H:%M:%S") if tx["created_at"] else "",
        ]
        for tx in transactions
    ]

    csv_content = _export_to_csv(headers, rows)
    response = HttpResponse(csv_content, content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="transactions_{datetime.now().strftime("%Y%m%d")}.csv"'
    return response


@require_GET
def export_holdings(request):
    """Export all holdings snapshots to CSV."""
    user_id = request.user.id
    holdings = HoldingSnapshot.objects.filter(user_id=user_id).order_by("as_of", "account_number", "symbol").values(
        "as_of", "account_name", "account_type", "account_classification", "account_number",
        "symbol", "exchange", "mic", "security_name", "security_type", "quantity",
        "market_price", "market_price_currency", "book_value_cad", "market_value",
        "market_value_currency", "unrealized_return", "source_filename", "imported_at"
    )

    headers = [
        "As Of", "Account Name", "Account Type", "Account Classification", "Account Number",
        "Symbol", "Exchange", "MIC", "Security Name", "Security Type", "Quantity",
        "Market Price", "Market Price Currency", "Book Value (CAD)", "Market Value",
        "Market Value Currency", "Unrealized Return", "Source Filename", "Imported At"
    ]

    rows = [
        [
            h["as_of"].strftime("%Y-%m-%d") if h["as_of"] else "",
            h["account_name"],
            h["account_type"] or "",
            h["account_classification"] or "",
            h["account_number"],
            h["symbol"],
            h["exchange"] or "",
            h["mic"] or "",
            h["security_name"] or "",
            h["security_type"] or "",
            str(h["quantity"]),
            str(h["market_price"]),
            h["market_price_currency"] or "",
            str(h["book_value_cad"]),
            str(h["market_value"]),
            h["market_value_currency"] or "",
            str(h["unrealized_return"]),
            h["source_filename"] or "",
            h["imported_at"].strftime("%Y-%m-%d %H:%M:%S") if h["imported_at"] else "",
        ]
        for h in holdings
    ]

    csv_content = _export_to_csv(headers, rows)
    response = HttpResponse(csv_content, content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="holdings_{datetime.now().strftime("%Y%m%d")}.csv"'
    return response


@require_GET
def export_net_worth(request):
    """Export all net worth history to CSV."""
    from core.models import NetWorthHistory

    user_id = request.user.id
    net_worth_data = NetWorthHistory.objects.filter(user_id=user_id).order_by("entry_date").values(
        "entry_date", "amount", "note", "created_at", "updated_at"
    )

    headers = ["Entry Date", "Amount", "Note", "Created At", "Updated At"]

    rows = [
        [
            nw["entry_date"].strftime("%Y-%m-%d") if nw["entry_date"] else "",
            str(nw["amount"]),
            nw["note"] or "",
            nw["created_at"].strftime("%Y-%m-%d %H:%M:%S") if nw["created_at"] else "",
            nw["updated_at"].strftime("%Y-%m-%d %H:%M:%S") if nw["updated_at"] else "",
        ]
        for nw in net_worth_data
    ]

    csv_content = _export_to_csv(headers, rows)
    response = HttpResponse(csv_content, content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="net_worth_{datetime.now().strftime("%Y%m%d")}.csv"'
    return response


@require_GET
def export_credit_cards(request):
    """Export all credit card transactions to CSV."""
    user_id = request.user.id
    cc_transactions = CreditCardTransaction.objects.filter(user_id=user_id).order_by("transaction_date", "id").values(
        "provider", "transaction_date", "posted_date", "reference_number", "activity_type",
        "status", "card_last4", "card_label", "merchant_category", "merchant_name",
        "merchant_city", "merchant_region", "merchant_country", "merchant_postal",
        "amount", "rewards", "is_hidden", "cardholder_name", "source_filename", "imported_at"
    )

    headers = [
        "Provider", "Transaction Date", "Posted Date", "Reference Number", "Activity Type",
        "Status", "Card Last 4", "Card Label", "Merchant Category", "Merchant Name",
        "Merchant City", "Merchant Region", "Merchant Country", "Merchant Postal",
        "Amount", "Rewards", "Is Hidden", "Cardholder Name", "Source Filename", "Imported At"
    ]

    rows = [
        [
            cc["provider"],
            cc["transaction_date"].strftime("%Y-%m-%d") if cc["transaction_date"] else "",
            cc["posted_date"].strftime("%Y-%m-%d") if cc["posted_date"] else "",
            cc["reference_number"] or "",
            cc["activity_type"] or "",
            cc["status"] or "",
            cc["card_last4"] or "",
            cc["card_label"] or "",
            cc["merchant_category"] or "",
            cc["merchant_name"] or "",
            cc["merchant_city"] or "",
            cc["merchant_region"] or "",
            cc["merchant_country"] or "",
            cc["merchant_postal"] or "",
            str(cc["amount"]),
            str(cc["rewards"]),
            str(cc["is_hidden"]),
            cc["cardholder_name"] or "",
            cc["source_filename"] or "",
            cc["imported_at"].strftime("%Y-%m-%d %H:%M:%S") if cc["imported_at"] else "",
        ]
        for cc in cc_transactions
    ]

    csv_content = _export_to_csv(headers, rows)
    response = HttpResponse(csv_content, content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="credit_cards_{datetime.now().strftime("%Y%m%d")}.csv"'
    return response


@require_GET
def export_tfsa(request):
    """Export all TFSA data to CSV."""
    from core.models import TfsaAccount, TfsaAnnualLimit, TfsaContribution

    user_id = request.user.id

    # Get all TFSA data
    accounts = list(TfsaAccount.objects.filter(user_id=user_id).values(
        "id", "account_name", "account_number", "opening_balance", "created_at"
    ))

    limits = list(TfsaAnnualLimit.objects.filter(user_id=user_id).order_by("year").values(
        "year", "annual_limit", "created_at", "updated_at"
    ))

    contributions = list(TfsaContribution.objects.filter(user_id=user_id).order_by("contribution_date", "id").values(
        "tfsa_account_id", "contribution_date", "amount", "contribution_type", "memo", "created_at"
    ))

    # Create account ID to name mapping
    account_map = {acc["id"]: acc["account_name"] for acc in accounts}

    # Build CSV with multiple sections
    output = StringIO()
    writer = csv.writer(output)

    # Accounts section
    writer.writerow(["=== TFSA Accounts ==="])
    writer.writerow(["Account Name", "Account Number", "Opening Balance", "Created At"])
    for acc in accounts:
        writer.writerow([
            acc["account_name"],
            acc["account_number"] or "",
            str(acc["opening_balance"]),
            acc["created_at"].strftime("%Y-%m-%d %H:%M:%S") if acc["created_at"] else "",
        ])

    writer.writerow([])  # Empty row

    # Annual Limits section
    writer.writerow(["=== TFSA Annual Limits ==="])
    writer.writerow(["Year", "Annual Limit", "Created At", "Updated At"])
    for limit in limits:
        writer.writerow([
            str(limit["year"]),
            str(limit["annual_limit"]),
            limit["created_at"].strftime("%Y-%m-%d %H:%M:%S") if limit["created_at"] else "",
            limit["updated_at"].strftime("%Y-%m-%d %H:%M:%S") if limit["updated_at"] else "",
        ])

    writer.writerow([])  # Empty row

    # Contributions section
    writer.writerow(["=== TFSA Contributions ==="])
    writer.writerow(["Account Name", "Contribution Date", "Amount", "Contribution Type", "Memo", "Created At"])
    for contrib in contributions:
        writer.writerow([
            account_map.get(contrib["tfsa_account_id"], "Unknown"),
            contrib["contribution_date"].strftime("%Y-%m-%d") if contrib["contribution_date"] else "",
            str(contrib["amount"]),
            contrib["contribution_type"],
            contrib["memo"] or "",
            contrib["created_at"].strftime("%Y-%m-%d %H:%M:%S") if contrib["created_at"] else "",
        ])

    csv_content = output.getvalue()
    response = HttpResponse(csv_content, content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="tfsa_{datetime.now().strftime("%Y%m%d")}.csv"'
    return response


@require_GET
def export_rrsp(request):
    """Export all RRSP data to CSV."""
    from core.models import RrspAccount, RrspAnnualLimit, RrspContribution

    user_id = request.user.id

    # Get all RRSP data
    accounts = list(RrspAccount.objects.filter(user_id=user_id).values(
        "id", "account_name", "account_number", "opening_balance", "created_at"
    ))

    limits = list(RrspAnnualLimit.objects.filter(user_id=user_id).order_by("year").values(
        "year", "annual_limit", "created_at", "updated_at"
    ))

    contributions = list(RrspContribution.objects.filter(user_id=user_id).order_by("contribution_date", "id").values(
        "rrsp_account_id", "contribution_date", "amount", "contribution_type",
        "is_unused", "deducted_tax_year", "memo", "created_at"
    ))

    # Create account ID to name mapping
    account_map = {acc["id"]: acc["account_name"] for acc in accounts}

    # Build CSV with multiple sections
    output = StringIO()
    writer = csv.writer(output)

    # Accounts section
    writer.writerow(["=== RRSP Accounts ==="])
    writer.writerow(["Account Name", "Account Number", "Opening Balance", "Created At"])
    for acc in accounts:
        writer.writerow([
            acc["account_name"],
            acc["account_number"] or "",
            str(acc["opening_balance"]),
            acc["created_at"].strftime("%Y-%m-%d %H:%M:%S") if acc["created_at"] else "",
        ])

    writer.writerow([])  # Empty row

    # Annual Limits section
    writer.writerow(["=== RRSP Annual Limits ==="])
    writer.writerow(["Year", "Annual Limit", "Created At", "Updated At"])
    for limit in limits:
        writer.writerow([
            str(limit["year"]),
            str(limit["annual_limit"]),
            limit["created_at"].strftime("%Y-%m-%d %H:%M:%S") if limit["created_at"] else "",
            limit["updated_at"].strftime("%Y-%m-%d %H:%M:%S") if limit["updated_at"] else "",
        ])

    writer.writerow([])  # Empty row

    # Contributions section
    writer.writerow(["=== RRSP Contributions ==="])
    writer.writerow(["Account Name", "Contribution Date", "Amount", "Contribution Type",
                     "Is Unused", "Deducted Tax Year", "Memo", "Created At"])
    for contrib in contributions:
        writer.writerow([
            account_map.get(contrib["rrsp_account_id"], "Unknown"),
            contrib["contribution_date"].strftime("%Y-%m-%d") if contrib["contribution_date"] else "",
            str(contrib["amount"]),
            contrib["contribution_type"],
            str(contrib["is_unused"]),
            str(contrib["deducted_tax_year"]) if contrib["deducted_tax_year"] else "",
            contrib["memo"] or "",
            contrib["created_at"].strftime("%Y-%m-%d %H:%M:%S") if contrib["created_at"] else "",
        ])

    csv_content = output.getvalue()
    response = HttpResponse(csv_content, content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="rrsp_{datetime.now().strftime("%Y%m%d")}.csv"'
    return response


@require_GET
def export_fhsa(request):
    """Export all FHSA data to CSV."""
    from core.models import FhsaAccount, FhsaContribution

    user_id = request.user.id

    # Get all FHSA data
    accounts = list(FhsaAccount.objects.filter(user_id=user_id).values(
        "id", "account_name", "account_number", "opening_balance", "created_at"
    ))

    contributions = list(FhsaContribution.objects.filter(user_id=user_id).order_by("contribution_date", "id").values(
        "fhsa_account_id", "contribution_date", "amount", "contribution_type",
        "is_qualifying_withdrawal", "memo", "created_at"
    ))

    # Create account ID to name mapping
    account_map = {acc["id"]: acc["account_name"] for acc in accounts}

    # Build CSV with multiple sections
    output = StringIO()
    writer = csv.writer(output)

    # Accounts section
    writer.writerow(["=== FHSA Accounts ==="])
    writer.writerow(["Account Name", "Account Number", "Opening Balance", "Created At"])
    for acc in accounts:
        writer.writerow([
            acc["account_name"],
            acc["account_number"] or "",
            str(acc["opening_balance"]),
            acc["created_at"].strftime("%Y-%m-%d %H:%M:%S") if acc["created_at"] else "",
        ])

    writer.writerow([])  # Empty row

    # Contributions section
    writer.writerow(["=== FHSA Contributions ==="])
    writer.writerow(["Account Name", "Contribution Date", "Amount", "Contribution Type",
                     "Is Qualifying Withdrawal", "Memo", "Created At"])
    for contrib in contributions:
        writer.writerow([
            account_map.get(contrib["fhsa_account_id"], "Unknown"),
            contrib["contribution_date"].strftime("%Y-%m-%d") if contrib["contribution_date"] else "",
            str(contrib["amount"]),
            contrib["contribution_type"],
            str(contrib["is_qualifying_withdrawal"]),
            contrib["memo"] or "",
            contrib["created_at"].strftime("%Y-%m-%d %H:%M:%S") if contrib["created_at"] else "",
        ])

    csv_content = output.getvalue()
    response = HttpResponse(csv_content, content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="fhsa_{datetime.now().strftime("%Y%m%d")}.csv"'
    return response


@require_GET
def export_all_data(request):
    """Export all data as a ZIP file containing multiple CSV files."""
    import zipfile
    from io import BytesIO
    from core.models import (
        NetWorthHistory, TfsaAccount, TfsaAnnualLimit, TfsaContribution,
        RrspAccount, RrspAnnualLimit, RrspContribution, FhsaAccount, FhsaContribution
    )

    user_id = request.user.id
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Create a ZIP file in memory
    zip_buffer = BytesIO()

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        # 1. Transactions
        transactions = Transaction.objects.filter(user_id=user_id).order_by("trade_date", "id").values(
            "security", "trade_date", "transaction_type", "amount", "shares",
            "amount_per_share", "commission", "memo", "source", "created_at"
        )
        headers = ["Security", "Trade Date", "Transaction Type", "Amount", "Shares",
                  "Amount Per Share", "Commission", "Memo", "Source", "Created At"]
        rows = [
            [tx["security"], tx["trade_date"].strftime("%Y-%m-%d") if tx["trade_date"] else "",
             tx["transaction_type"], str(tx["amount"]), str(tx["shares"]),
             str(tx["amount_per_share"]) if tx["amount_per_share"] else "", str(tx["commission"]),
             tx["memo"] or "", tx["source"],
             tx["created_at"].strftime("%Y-%m-%d %H:%M:%S") if tx["created_at"] else ""]
            for tx in transactions
        ]
        zip_file.writestr(f"transactions_{timestamp}.csv", _export_to_csv(headers, rows))

        # 2. Holdings
        holdings = HoldingSnapshot.objects.filter(user_id=user_id).order_by("as_of", "account_number", "symbol").values(
            "as_of", "account_name", "account_type", "account_classification", "account_number",
            "symbol", "exchange", "mic", "security_name", "security_type", "quantity",
            "market_price", "market_price_currency", "book_value_cad", "market_value",
            "market_value_currency", "unrealized_return", "source_filename", "imported_at"
        )
        headers = ["As Of", "Account Name", "Account Type", "Account Classification", "Account Number",
                  "Symbol", "Exchange", "MIC", "Security Name", "Security Type", "Quantity",
                  "Market Price", "Market Price Currency", "Book Value (CAD)", "Market Value",
                  "Market Value Currency", "Unrealized Return", "Source Filename", "Imported At"]
        rows = [
            [h["as_of"].strftime("%Y-%m-%d") if h["as_of"] else "", h["account_name"],
             h["account_type"] or "", h["account_classification"] or "", h["account_number"],
             h["symbol"], h["exchange"] or "", h["mic"] or "", h["security_name"] or "",
             h["security_type"] or "", str(h["quantity"]), str(h["market_price"]),
             h["market_price_currency"] or "", str(h["book_value_cad"]), str(h["market_value"]),
             h["market_value_currency"] or "", str(h["unrealized_return"]), h["source_filename"] or "",
             h["imported_at"].strftime("%Y-%m-%d %H:%M:%S") if h["imported_at"] else ""]
            for h in holdings
        ]
        zip_file.writestr(f"holdings_{timestamp}.csv", _export_to_csv(headers, rows))

        # 3. Net Worth
        net_worth_data = NetWorthHistory.objects.filter(user_id=user_id).order_by("entry_date").values(
            "entry_date", "amount", "note", "created_at", "updated_at"
        )
        headers = ["Entry Date", "Amount", "Note", "Created At", "Updated At"]
        rows = [
            [nw["entry_date"].strftime("%Y-%m-%d") if nw["entry_date"] else "", str(nw["amount"]),
             nw["note"] or "", nw["created_at"].strftime("%Y-%m-%d %H:%M:%S") if nw["created_at"] else "",
             nw["updated_at"].strftime("%Y-%m-%d %H:%M:%S") if nw["updated_at"] else ""]
            for nw in net_worth_data
        ]
        zip_file.writestr(f"net_worth_{timestamp}.csv", _export_to_csv(headers, rows))

        # 4. Credit Cards
        cc_transactions = CreditCardTransaction.objects.filter(user_id=user_id).order_by("transaction_date", "id").values(
            "provider", "transaction_date", "posted_date", "reference_number", "activity_type",
            "status", "card_last4", "card_label", "merchant_category", "merchant_name",
            "merchant_city", "merchant_region", "merchant_country", "merchant_postal",
            "amount", "rewards", "is_hidden", "cardholder_name", "source_filename", "imported_at"
        )
        headers = ["Provider", "Transaction Date", "Posted Date", "Reference Number", "Activity Type",
                  "Status", "Card Last 4", "Card Label", "Merchant Category", "Merchant Name",
                  "Merchant City", "Merchant Region", "Merchant Country", "Merchant Postal",
                  "Amount", "Rewards", "Is Hidden", "Cardholder Name", "Source Filename", "Imported At"]
        rows = [
            [cc["provider"], cc["transaction_date"].strftime("%Y-%m-%d") if cc["transaction_date"] else "",
             cc["posted_date"].strftime("%Y-%m-%d") if cc["posted_date"] else "", cc["reference_number"] or "",
             cc["activity_type"] or "", cc["status"] or "", cc["card_last4"] or "", cc["card_label"] or "",
             cc["merchant_category"] or "", cc["merchant_name"] or "", cc["merchant_city"] or "",
             cc["merchant_region"] or "", cc["merchant_country"] or "", cc["merchant_postal"] or "",
             str(cc["amount"]), str(cc["rewards"]), str(cc["is_hidden"]), cc["cardholder_name"] or "",
             cc["source_filename"] or "", cc["imported_at"].strftime("%Y-%m-%d %H:%M:%S") if cc["imported_at"] else ""]
            for cc in cc_transactions
        ]
        zip_file.writestr(f"credit_cards_{timestamp}.csv", _export_to_csv(headers, rows))

        # 5-7. TFSA, RRSP, FHSA (simplified - just basic data)
        # TFSA
        tfsa_contribs = TfsaContribution.objects.filter(user_id=user_id).select_related("tfsa_account").order_by("contribution_date").values(
            "tfsa_account__account_name", "contribution_date", "amount", "contribution_type", "memo"
        )
        headers = ["Account Name", "Contribution Date", "Amount", "Contribution Type", "Memo"]
        rows = [
            [tc["tfsa_account__account_name"], tc["contribution_date"].strftime("%Y-%m-%d") if tc["contribution_date"] else "",
             str(tc["amount"]), tc["contribution_type"], tc["memo"] or ""]
            for tc in tfsa_contribs
        ]
        zip_file.writestr(f"tfsa_contributions_{timestamp}.csv", _export_to_csv(headers, rows))

        # RRSP
        rrsp_contribs = RrspContribution.objects.filter(user_id=user_id).select_related("rrsp_account").order_by("contribution_date").values(
            "rrsp_account__account_name", "contribution_date", "amount", "contribution_type",
            "is_unused", "deducted_tax_year", "memo"
        )
        headers = ["Account Name", "Contribution Date", "Amount", "Contribution Type", "Is Unused", "Deducted Tax Year", "Memo"]
        rows = [
            [rc["rrsp_account__account_name"], rc["contribution_date"].strftime("%Y-%m-%d") if rc["contribution_date"] else "",
             str(rc["amount"]), rc["contribution_type"], str(rc["is_unused"]),
             str(rc["deducted_tax_year"]) if rc["deducted_tax_year"] else "", rc["memo"] or ""]
            for rc in rrsp_contribs
        ]
        zip_file.writestr(f"rrsp_contributions_{timestamp}.csv", _export_to_csv(headers, rows))

        # FHSA
        fhsa_contribs = FhsaContribution.objects.filter(user_id=user_id).select_related("fhsa_account").order_by("contribution_date").values(
            "fhsa_account__account_name", "contribution_date", "amount", "contribution_type",
            "is_qualifying_withdrawal", "memo"
        )
        headers = ["Account Name", "Contribution Date", "Amount", "Contribution Type", "Is Qualifying Withdrawal", "Memo"]
        rows = [
            [fc["fhsa_account__account_name"], fc["contribution_date"].strftime("%Y-%m-%d") if fc["contribution_date"] else "",
             str(fc["amount"]), fc["contribution_type"], str(fc["is_qualifying_withdrawal"]), fc["memo"] or ""]
            for fc in fhsa_contribs
        ]
        zip_file.writestr(f"fhsa_contributions_{timestamp}.csv", _export_to_csv(headers, rows))

    # Prepare the response
    zip_buffer.seek(0)
    response = HttpResponse(zip_buffer.getvalue(), content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="finglass_export_{timestamp}.zip"'
    return response


# Full Data Import (Restore)

def _import_csv_to_model(csv_content, model_class, field_mapping, user_id, unique_fields=None, account_mapping=None):
    """
    Generic helper to import CSV data into a Django model.

    Args:
        csv_content: CSV text content
        model_class: Django model class to import into
        field_mapping: Dict mapping CSV headers to model field names
        user_id: User ID for the import
        unique_fields: List of fields to check for uniqueness (for update_or_create)
        account_mapping: Dict mapping account names to account IDs (for related models)

    Returns:
        Dict with counts of inserted and updated records
    """
    reader = csv.DictReader(StringIO(csv_content))
    inserted = 0
    updated = 0
    errors = []

    for row_num, row in enumerate(reader, start=2):  # Start at 2 (header is row 1)
        try:
            # Build the data dict from field mapping
            data = {"user_id": user_id}
            lookup_fields = {}

            for csv_header, model_field in field_mapping.items():
                value = row.get(csv_header, "").strip()

                # Skip empty values for nullable fields
                if value == "":
                    continue

                # Handle special field transformations
                if model_field.endswith("_date") or model_field == "as_of":
                    # Parse date fields
                    if value:
                        data[model_field] = datetime.strptime(value.split()[0], "%Y-%m-%d").date()
                elif model_field.endswith("_at"):
                    # Skip auto-generated timestamp fields
                    continue
                elif model_field in ["amount", "shares", "commission", "quantity", "market_price",
                                     "book_value_cad", "market_value", "unrealized_return",
                                     "amount_per_share", "rewards", "annual_limit", "opening_balance"]:
                    # Numeric fields
                    data[model_field] = _to_decimal(value) if value else 0
                elif model_field == "is_hidden" or model_field == "is_unused" or model_field == "is_qualifying_withdrawal":
                    # Boolean fields
                    data[model_field] = value.lower() in ("true", "1", "yes")
                elif model_field == "year" or model_field == "deducted_tax_year":
                    # Integer fields
                    data[model_field] = int(value) if value else None
                elif model_field.endswith("_account_id"):
                    # Foreign key to account - use account_mapping
                    if account_mapping and value:
                        data[model_field] = account_mapping.get(value)
                else:
                    data[model_field] = value

                # Build lookup fields for unique constraint checking
                if unique_fields and model_field in unique_fields and model_field != "user_id":
                    lookup_fields[model_field] = data[model_field]

            # Create or update
            if unique_fields and lookup_fields:
                lookup_fields["user_id"] = user_id
                obj, created = model_class.objects.update_or_create(
                    **lookup_fields,
                    defaults={k: v for k, v in data.items() if k not in lookup_fields}
                )
                if created:
                    inserted += 1
                else:
                    updated += 1
            else:
                model_class.objects.create(**data)
                inserted += 1

        except Exception as e:
            errors.append(f"Row {row_num}: {str(e)}")
            if len(errors) > 10:  # Limit error reporting
                errors.append("... (additional errors truncated)")
                break

    return {"inserted": inserted, "updated": updated, "errors": errors}


@require_http_methods(["POST"])
def import_full_backup(request):
    """
    Import a full backup ZIP file containing all exported data.
    This is a complete restore operation.
    """
    from core.models import (
        NetWorthHistory, TfsaAccount, TfsaAnnualLimit, TfsaContribution,
        RrspAccount, RrspAnnualLimit, RrspContribution, FhsaAccount, FhsaContribution
    )

    user_id = request.user.id

    if "file" not in request.FILES:
        return JsonResponse({"error": "Missing file upload field: file"}, status=400)

    uploaded_file = request.FILES["file"]
    if not uploaded_file.name or not uploaded_file.name.endswith(".zip"):
        return JsonResponse({"error": "Please upload a ZIP file"}, status=400)

    clear_existing = request.POST.get("clear_existing", "false").lower() == "true"

    try:
        import zipfile

        # Read the ZIP file
        zip_bytes = uploaded_file.read()
        zip_buffer = BytesIO(zip_bytes)

        summary = {
            "transactions": {"inserted": 0, "updated": 0, "errors": []},
            "holdings": {"inserted": 0, "updated": 0, "errors": []},
            "net_worth": {"inserted": 0, "updated": 0, "errors": []},
            "credit_cards": {"inserted": 0, "updated": 0, "errors": []},
            "tfsa": {"inserted": 0, "updated": 0, "errors": []},
            "rrsp": {"inserted": 0, "updated": 0, "errors": []},
            "fhsa": {"inserted": 0, "updated": 0, "errors": []},
        }

        # Clear existing data if requested
        if clear_existing:
            Transaction.objects.filter(user_id=user_id).delete()
            HoldingSnapshot.objects.filter(user_id=user_id).delete()
            NetWorthHistory.objects.filter(user_id=user_id).delete()
            CreditCardTransaction.objects.filter(user_id=user_id).delete()
            TfsaContribution.objects.filter(user_id=user_id).delete()
            TfsaAnnualLimit.objects.filter(user_id=user_id).delete()
            TfsaAccount.objects.filter(user_id=user_id).delete()
            RrspContribution.objects.filter(user_id=user_id).delete()
            RrspAnnualLimit.objects.filter(user_id=user_id).delete()
            RrspAccount.objects.filter(user_id=user_id).delete()
            FhsaContribution.objects.filter(user_id=user_id).delete()
            FhsaAccount.objects.filter(user_id=user_id).delete()

        with zipfile.ZipFile(zip_buffer, 'r') as zip_file:
            file_list = zip_file.namelist()

            # 1. Import Transactions
            tx_files = [f for f in file_list if f.startswith("transactions_") and f.endswith(".csv")]
            if tx_files:
                csv_content = zip_file.read(tx_files[0]).decode("utf-8")
                field_mapping = {
                    "Security": "security",
                    "Trade Date": "trade_date",
                    "Transaction Type": "transaction_type",
                    "Amount": "amount",
                    "Shares": "shares",
                    "Amount Per Share": "amount_per_share",
                    "Commission": "commission",
                    "Memo": "memo",
                    "Source": "source",
                }
                summary["transactions"] = _import_csv_to_model(
                    csv_content, Transaction, field_mapping, user_id
                )

            # 2. Import Holdings
            holdings_files = [f for f in file_list if f.startswith("holdings_") and f.endswith(".csv")]
            if holdings_files:
                csv_content = zip_file.read(holdings_files[0]).decode("utf-8")
                field_mapping = {
                    "As Of": "as_of",
                    "Account Name": "account_name",
                    "Account Type": "account_type",
                    "Account Classification": "account_classification",
                    "Account Number": "account_number",
                    "Symbol": "symbol",
                    "Exchange": "exchange",
                    "MIC": "mic",
                    "Security Name": "security_name",
                    "Security Type": "security_type",
                    "Quantity": "quantity",
                    "Market Price": "market_price",
                    "Market Price Currency": "market_price_currency",
                    "Book Value (CAD)": "book_value_cad",
                    "Market Value": "market_value",
                    "Market Value Currency": "market_value_currency",
                    "Unrealized Return": "unrealized_return",
                    "Source Filename": "source_filename",
                }
                summary["holdings"] = _import_csv_to_model(
                    csv_content, HoldingSnapshot, field_mapping, user_id,
                    unique_fields=["as_of", "account_number", "symbol"]
                )

            # 3. Import Net Worth
            nw_files = [f for f in file_list if f.startswith("net_worth_") and f.endswith(".csv")]
            if nw_files:
                csv_content = zip_file.read(nw_files[0]).decode("utf-8")
                field_mapping = {
                    "Entry Date": "entry_date",
                    "Amount": "amount",
                    "Note": "note",
                }
                summary["net_worth"] = _import_csv_to_model(
                    csv_content, NetWorthHistory, field_mapping, user_id,
                    unique_fields=["entry_date"]
                )

            # 4. Import Credit Cards
            cc_files = [f for f in file_list if f.startswith("credit_cards_") and f.endswith(".csv")]
            if cc_files:
                csv_content = zip_file.read(cc_files[0]).decode("utf-8")
                field_mapping = {
                    "Provider": "provider",
                    "Transaction Date": "transaction_date",
                    "Posted Date": "posted_date",
                    "Reference Number": "reference_number",
                    "Activity Type": "activity_type",
                    "Status": "status",
                    "Card Last 4": "card_last4",
                    "Card Label": "card_label",
                    "Merchant Category": "merchant_category",
                    "Merchant Name": "merchant_name",
                    "Merchant City": "merchant_city",
                    "Merchant Region": "merchant_region",
                    "Merchant Country": "merchant_country",
                    "Merchant Postal": "merchant_postal",
                    "Amount": "amount",
                    "Rewards": "rewards",
                    "Is Hidden": "is_hidden",
                    "Cardholder Name": "cardholder_name",
                    "Source Filename": "source_filename",
                }
                summary["credit_cards"] = _import_csv_to_model(
                    csv_content, CreditCardTransaction, field_mapping, user_id
                )

            # 5. Import TFSA (simplified for now - just contributions)
            tfsa_files = [f for f in file_list if f.startswith("tfsa_contributions_") and f.endswith(".csv")]
            if tfsa_files:
                csv_content = zip_file.read(tfsa_files[0]).decode("utf-8")

                # First, ensure we have accounts created
                account_names = set()
                reader = csv.DictReader(StringIO(csv_content))
                for row in reader:
                    account_name = row.get("Account Name", "").strip()
                    if account_name:
                        account_names.add(account_name)

                # Create accounts if they don't exist
                account_mapping = {}
                for acc_name in account_names:
                    acc, _ = TfsaAccount.objects.get_or_create(
                        user_id=user_id,
                        account_name=acc_name,
                        defaults={"opening_balance": 0}
                    )
                    account_mapping[acc_name] = acc.id

                # Now import contributions
                field_mapping = {
                    "Account Name": "tfsa_account_id",
                    "Contribution Date": "contribution_date",
                    "Amount": "amount",
                    "Contribution Type": "contribution_type",
                    "Memo": "memo",
                }
                summary["tfsa"] = _import_csv_to_model(
                    csv_content, TfsaContribution, field_mapping, user_id,
                    account_mapping=account_mapping
                )

            # 6. Import RRSP
            rrsp_files = [f for f in file_list if f.startswith("rrsp_contributions_") and f.endswith(".csv")]
            if rrsp_files:
                csv_content = zip_file.read(rrsp_files[0]).decode("utf-8")

                # Create accounts
                account_names = set()
                reader = csv.DictReader(StringIO(csv_content))
                for row in reader:
                    account_name = row.get("Account Name", "").strip()
                    if account_name:
                        account_names.add(account_name)

                account_mapping = {}
                for acc_name in account_names:
                    acc, _ = RrspAccount.objects.get_or_create(
                        user_id=user_id,
                        account_name=acc_name,
                        defaults={"opening_balance": 0}
                    )
                    account_mapping[acc_name] = acc.id

                # Import contributions
                field_mapping = {
                    "Account Name": "rrsp_account_id",
                    "Contribution Date": "contribution_date",
                    "Amount": "amount",
                    "Contribution Type": "contribution_type",
                    "Is Unused": "is_unused",
                    "Deducted Tax Year": "deducted_tax_year",
                    "Memo": "memo",
                }
                summary["rrsp"] = _import_csv_to_model(
                    csv_content, RrspContribution, field_mapping, user_id,
                    account_mapping=account_mapping
                )

            # 7. Import FHSA
            fhsa_files = [f for f in file_list if f.startswith("fhsa_contributions_") and f.endswith(".csv")]
            if fhsa_files:
                csv_content = zip_file.read(fhsa_files[0]).decode("utf-8")

                # Create accounts
                account_names = set()
                reader = csv.DictReader(StringIO(csv_content))
                for row in reader:
                    account_name = row.get("Account Name", "").strip()
                    if account_name:
                        account_names.add(account_name)

                account_mapping = {}
                for acc_name in account_names:
                    acc, _ = FhsaAccount.objects.get_or_create(
                        user_id=user_id,
                        account_name=acc_name,
                        defaults={"opening_balance": 0}
                    )
                    account_mapping[acc_name] = acc.id

                # Import contributions
                field_mapping = {
                    "Account Name": "fhsa_account_id",
                    "Contribution Date": "contribution_date",
                    "Amount": "amount",
                    "Contribution Type": "contribution_type",
                    "Is Qualifying Withdrawal": "is_qualifying_withdrawal",
                    "Memo": "memo",
                }
                summary["fhsa"] = _import_csv_to_model(
                    csv_content, FhsaContribution, field_mapping, user_id,
                    account_mapping=account_mapping
                )

        # Calculate totals
        total_inserted = sum(s.get("inserted", 0) for s in summary.values())
        total_updated = sum(s.get("updated", 0) for s in summary.values())
        all_errors = []
        for domain, data in summary.items():
            if data.get("errors"):
                all_errors.extend([f"{domain}: {err}" for err in data["errors"][:3]])  # Limit errors per domain

        response_data = {
            "success": True,
            "cleared": clear_existing,
            "total_inserted": total_inserted,
            "total_updated": total_updated,
            "summary": summary,
        }

        if all_errors:
            response_data["warnings"] = all_errors[:10]  # Limit total warnings

        return JsonResponse(response_data)

    except zipfile.BadZipFile:
        return JsonResponse({"error": "Invalid ZIP file"}, status=400)
    except Exception as e:
        return JsonResponse({"error": f"Import failed: {str(e)}"}, status=500)
