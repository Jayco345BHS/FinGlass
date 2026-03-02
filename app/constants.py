CASH_ACCOUNT_NUMBER = "__CASH__"
HOLDINGS_SYMBOL_SUFFIXES = (".TO", ".TRT", ".V", ".NE")
SUPPORTED_TRANSACTION_TYPES = {
    "Buy",
    "Sell",
    "Return of Capital",
    "Capital Gains Dividend",
    "Reinvested Dividend",
    "Reinvested Capital Gains Distribution",
    "Split",
}
DEFAULT_FEATURE_SETTINGS = {
    "imports": True,
    "holdings_overview": True,
    "acb_tracker": True,
    "net_worth": True,
    "credit_card": True,
    "tfsa_tracker": True,
    "rrsp_tracker": True,
}
