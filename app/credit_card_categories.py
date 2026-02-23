import re


def _slug(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def normalize_credit_card_category(value):
    raw = str(value or "").strip()
    if not raw:
        return "Uncategorized"

    slug = _slug(raw)

    if "grocery stores and supermarkets" in slug:
        return "Groceries"
    if "drug stores and pharmacies" in slug:
        return "Pharmacy"
    if "eating places and restaurants" in slug:
        return "Restaurants"
    if "quick payment service" in slug and "fast food" in slug:
        return "Fast Food"
    if "drinking places" in slug:
        return "Bars"
    if "bakeries" in slug:
        return "Bakery"
    if "parking lots and garages" in slug:
        return "Parking"
    if "service stations" in slug or "automated fuel dispensers" in slug:
        return "Fuel"
    if "taxicabs and limousines" in slug:
        return "Taxi"
    if "bus lines" in slug or "commuter passenger transportation" in slug:
        return "Transit"
    if "telecommunication services" in slug:
        return "Telecom"
    if "computer software stores" in slug:
        return "Software"
    if "digital goods" in slug and "games" in slug:
        return "Gaming"
    if "digital goods" in slug:
        return "Digital Goods"
    if "large digital goods merchant" in slug:
        return "Digital Services"
    if "computer network information services" in slug or "online services" in slug:
        return "Online Services"
    if "direct marketing" in slug and "telemarketing" in slug:
        return "Online Subscription"
    if "cashback" in slug or "remises" in slug:
        return "Cashback"
    if "doctors and physicians" in slug:
        return "Medical"
    if "wholesale club" in slug:
        return "Wholesale"
    if "package stores" in slug and "liquor" in slug:
        return "Liquor"

    return re.sub(r"\s+", " ", raw)