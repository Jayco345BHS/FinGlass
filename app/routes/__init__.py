from .auth_routes import bp as auth_bp
from .credit_card_routes import bp as credit_card_bp
from .fhsa_routes import bp as fhsa_bp
from .holdings_routes import bp as holdings_bp
from .import_routes import bp as import_bp
from .net_worth_routes import bp as net_worth_bp
from .page_routes import bp as page_bp
from .rrsp_routes import bp as rrsp_bp
from .settings_routes import bp as settings_bp
from .tfsa_routes import bp as tfsa_bp
from .transactions_routes import bp as transactions_bp

ALL_BLUEPRINTS = [
    auth_bp,
    page_bp,
    transactions_bp,
    holdings_bp,
    net_worth_bp,
    credit_card_bp,
    import_bp,
    tfsa_bp,
    rrsp_bp,
    fhsa_bp,
    settings_bp,
]
