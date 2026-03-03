from decimal import Decimal

from core.constants import SUPPORTED_TRANSACTION_TYPES


def parse_transaction_payload(payload):
    required = ["security", "trade_date", "transaction_type", "amount", "shares"]
    for field in required:
        if field not in payload:
            raise ValueError(f"Missing field: {field}")

    security = str(payload["security"]).strip().upper()
    trade_date = str(payload["trade_date"]).strip()
    transaction_type = str(payload["transaction_type"]).strip()
    if transaction_type not in SUPPORTED_TRANSACTION_TYPES:
        raise ValueError("Unsupported transaction type")

    amount = Decimal(str(payload.get("amount") or 0))
    shares = Decimal(str(payload.get("shares") or 0))
    amount_per_share = payload.get("amount_per_share")
    commission = Decimal(str(payload.get("commission") or 0))
    memo = str(payload.get("memo") or "").strip()

    if amount_per_share in (None, ""):
        amount_per_share = (amount / shares) if shares else Decimal("0")
    amount_per_share = Decimal(str(amount_per_share))

    return {
        "security": security,
        "trade_date": trade_date,
        "transaction_type": transaction_type,
        "amount": amount,
        "shares": shares,
        "amount_per_share": amount_per_share,
        "commission": commission,
        "memo": memo,
    }
