import re

MAX_FALLBACK_WORDS = 4

HOTEL_KEYWORDS = {
    "hotel", "motel", "inn", "resort", "lodging",
    "hyatt", "marriott", "hilton", "sheraton", "westin",
    "fairmont", "holiday inn", "doubletree", "hampton",
    "four points", "best western", "comfort inn", "radisson",
}


def _slug(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _fallback(slug):
    if not slug:
        return "Uncategorized"
    return " ".join(w.capitalize() for w in slug.split()[:MAX_FALLBACK_WORDS])


RULES = [

    # --- FOOD ---

    ("Groceries", ["grocery stores", "supermarkets"]),

    ("Dining", ["restaurants", "eating places", "caterers"]),

    ("Fast Food", ["fast food"]),

    ("Coffee & Snacks", ["bakeries", "candy", "confectionery"]),

    ("Alcohol & Bars", ["drinking places", "liquor", "package stores"]),

    # --- TRANSPORT ---

    ("Fuel", ["service stations", "automated fuel dispensers"]),

    ("Parking", ["parking lots", "garages"]),

    ("Transit & Taxi", [
        "taxicabs", "limousines", "bus lines",
        "commuter transportation", "passenger rail"
    ]),

    ("Auto Maintenance", ["automotive service shops", "repair shops"]),

    # --- HOME & BILLS ---

    ("Telecom", [
        "telecommunication services",
        "telecommunication equipment",
        "cable satellite",
    ]),

    ("Utilities", ["utilities"]),

    ("Insurance", ["insurance sales and underwriting"]),

    # --- SHOPPING ---

    ("Clothing", [
        "clothing stores", "family clothing",
        "mens and womens clothing"
    ]),

    ("Electronics", ["electronics stores"]),

    ("Home & Furniture", ["furniture", "home furnishings"]),

    ("General Retail", [
        "department stores", "discount stores",
        "miscellaneous retail", "specialty retail",
        "hardware stores", "office supplies"
    ]),

    ("Wholesale", ["wholesale club"]),

    # --- DIGITAL ---

    ("Software & SaaS", [
        "computer software stores",
        "computers computer peripheral equipment"
    ]),

    ("Gaming", ["digital goods games"]),

    ("Streaming & Digital", [
        "digital goods",
        "large digital goods merchant"
    ]),

    ("Online Subscriptions", [
        "continuity subscription",
        "direct marketing",
        "computer network information services",
        "online services"
    ]),

    # --- HEALTH ---

    ("Medical", ["doctors and physicians", "hospitals"]),

    ("Pharmacy", ["drug stores and pharmacies"]),

    ("Dental", ["dentists and orthodontists"]),

    ("Medical Supplies", [
        "dental laboratory medical ophthalmic hospital equipment"
    ]),

    # --- LIFESTYLE ---

    ("Entertainment & Events", [
        "theatrical", "bands", "orchestras",
        "motion picture", "amusement parks",
        "tourist attractions"
    ]),

    ("Hobbies & Toys", ["hobby toy and game stores"]),

    ("Sports & Outdoors", ["sporting goods", "riding apparel"]),

    # --- TRAVEL ---

    ("Travel", ["airlines", "travel agencies", "car rental"]),

    ("Lodging", []),  # handled separately

    # --- MONEY & GOV ---

    ("Taxes & Government", ["tax payments", "government services"]),

    ("Fees & Fines", ["fines", "court costs"]),

    # --- SERVICES ---

    ("Professional Services", [
        "professional services", "legal services", "accounting"
    ]),

    ("Personal Services", [
        "personal services", "business services"
    ]),

    ("Education & Memberships", [
        "schools", "colleges", "membership clubs",
        "civic social", "charitable"
    ]),

    ("Cashback", ["cashback", "remises"]),
]


def normalize_credit_card_category(value):

    raw = str(value or "").strip()
    if not raw:
        return "Uncategorized"

    slug = _slug(raw)

    # --- HOTEL BRAND DETECTION ---
    if any(k in slug for k in HOTEL_KEYWORDS):
        return "Lodging"

    # --- RULE MATCH ---
    for category, keywords in RULES:
        if any(k in slug for k in keywords):
            return category

    # --- FALLBACK ---
    return _fallback(slug)