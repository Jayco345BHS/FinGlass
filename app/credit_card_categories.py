import re


LOWERCASE_WORDS = {
    "and",
    "or",
    "of",
    "the",
    "for",
    "to",
    "in",
    "on",
    "at",
    "by",
    "with",
    "a",
    "an",
}

UPPERCASE_WORDS = {"tv", "atm", "mcc", "gps", "usa", "cad", "usd"}
MAX_FALLBACK_WORDS = 4
HOTEL_KEYWORDS = {
    "hotel",
    "hotels",
    "motel",
    "motels",
    "inn",
    "inns",
    "resort",
    "resorts",
    "lodging",
    "hyatt",
    "marriott",
    "hilton",
    "sheraton",
    "westin",
    "fairmont",
    "holiday inn",
    "doubletree",
    "hampton",
    "four points",
    "best western",
    "comfort inn",
    "radisson",
}


def _slug(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _canonical_from_slug(slug):
    if not slug:
        return "Uncategorized"

    words = slug.split()[:MAX_FALLBACK_WORDS]
    normalized = []
    for index, word in enumerate(words):
        if word in UPPERCASE_WORDS:
            normalized.append(word.upper())
            continue

        if word in LOWERCASE_WORDS and index != 0:
            normalized.append(word)
            continue

        normalized.append(word.capitalize())

    return " ".join(normalized)


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
    if "telecommunication equipment and telephone sales" in slug:
        return "Telecom"
    if "cable satellite and other pay television and radio services" in slug:
        return "Telecom"
    if "computer software stores" in slug:
        return "Software"
    if "computers computer peripheral equipment and software" in slug:
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
    if "continuity subscription merchants" in slug:
        return "Online Subscription"
    if "cashback" in slug or "remises" in slug:
        return "Cashback"
    if "doctors and physicians" in slug:
        return "Medical"
    if "wholesale club" in slug:
        return "Wholesale"
    if "package stores" in slug and "liquor" in slug:
        return "Liquor"
    if "hobby toy and game stores" in slug:
        return "Hobby, Toy and Game Stores"
    if "candy nut and confectionary stores" in slug or "candy nut and confectionery stores" in slug:
        return "Candy, Nut, and Confectionary Stores"
    if "mens and boys clothing and accessory stores" in slug:
        return "Clothing"
    if "mens and womens clothing stores" in slug:
        return "Clothing"
    if "family clothing stores" in slug:
        return "Clothing"
    if "automotive service shops non dealer" in slug:
        return "Automotive Service"
    if "dental laboratory medical ophthalmic hospital equipment and supplies" in slug:
        return "Medical Supplies"
    if any(keyword in slug for keyword in HOTEL_KEYWORDS):
        return "Hotel"

    return _canonical_from_slug(slug)