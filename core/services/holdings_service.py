from datetime import datetime

from django.utils import timezone

from core.constants import HOLDINGS_SYMBOL_SUFFIXES
from core.models import HoldingSnapshot


def normalize_holding_symbol(symbol):
    value = str(symbol or "").strip().upper()
    if not value:
        return ""
    for suffix in HOLDINGS_SYMBOL_SUFFIXES:
        if value.endswith(suffix) and len(value) > len(suffix):
            return value[: -len(suffix)]
    return value


def derive_account_number(account_name):
    normalized = "".join(ch for ch in str(account_name or "").upper() if ch.isalnum())
    if not normalized:
        return "__ACCOUNT__"
    return f"__ACCOUNT__{normalized}"


def parse_as_of_value(user, as_of):
    normalized = str(as_of or "").strip()
    if normalized:
        return datetime.strptime(normalized, "%Y-%m-%d").date()

    latest = (
        HoldingSnapshot.objects.filter(user=user)
        .order_by("-as_of")
        .values_list("as_of", flat=True)
        .first()
    )
    if latest:
        return latest

    return timezone.now().date()


def parse_numeric_field(payload, field_name, default_value=0):
    value = payload.get(field_name, default_value)
    return float(value or 0)
