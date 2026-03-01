from .auth_routes import bp as auth_bp
from .credit_card_routes import bp as credit_card_bp
from .holdings_routes import bp as holdings_bp
from .import_routes import bp as import_bp
from .net_worth_routes import bp as net_worth_bp
from .page_routes import bp as page_bp
from .settings_routes import bp as settings_bp
from .transactions_routes import bp as transactions_bp

ALL_BLUEPRINTS = [
    auth_bp,
    page_bp,
    transactions_bp,
    holdings_bp,
    net_worth_bp,
    credit_card_bp,
    import_bp,
    settings_bp,
]
