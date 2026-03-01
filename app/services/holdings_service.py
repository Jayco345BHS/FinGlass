from datetime import datetime

from ..constants import HOLDINGS_SYMBOL_SUFFIXES


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


def parse_as_of_value(db, user_id, as_of):
    normalized = str(as_of or "").strip()
    if normalized:
        return datetime.strptime(normalized, "%Y-%m-%d").strftime("%Y-%m-%d")

    latest_row = db.execute(
        "SELECT MAX(as_of) AS as_of FROM holdings_snapshots WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    latest = latest_row["as_of"] if latest_row and latest_row["as_of"] else None
    if latest:
        return latest

    return datetime.now().strftime("%Y-%m-%d")


def parse_numeric_field(payload, field_name, default_value=0):
    value = payload.get(field_name, default_value)
    return float(value or 0)
