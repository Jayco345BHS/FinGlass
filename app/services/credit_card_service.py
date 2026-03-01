from .settings_service import parse_setting_bool
from ..credit_card_categories import normalize_credit_card_category


def parse_credit_card_category_filters(args):
    requested_categories = []
    for raw_value in args.getlist("category"):
        for part in str(raw_value or "").split(","):
            normalized_part = part.strip()
            if normalized_part:
                requested_categories.append(normalized_part)

    return {
        normalize_credit_card_category(category)
        for category in requested_categories
        if str(category or "").strip()
    }


def parse_bool_query(value):
    return parse_setting_bool(value)
