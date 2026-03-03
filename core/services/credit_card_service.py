from core.services.settings_service import parse_setting_bool


def parse_credit_card_category_filters(args):
    requested_categories = []
    for raw_value in args.getlist("category"):
        for part in str(raw_value or "").split(","):
            normalized_part = part.strip()
            if normalized_part:
                requested_categories.append(normalized_part)

    return {str(category).strip() for category in requested_categories if str(category or "").strip()}


def parse_bool_query(value):
    return parse_setting_bool(value)
