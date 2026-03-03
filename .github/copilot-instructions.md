# Copilot Instructions for FinGlass

## Architecture at a glance
- `manage.py` is the Django management script; `finglass_project/` contains Django project settings (settings.py, urls.py, wsgi.py).
- Production container runs `gunicorn finglass_project.wsgi`.
- Apps are organized in `django_apps/`: `accounts` (auth/user management) and `core` (transaction/holdings/credit-card/import logic).
- Each app has models.py (ORM), views.py (view functions/logic), urls.py (routing), and services/ (reusable business logic).
- Data persistence is SQLite at `data/finglass.sqlite3`; schema is managed via Django ORM models in `django_apps/*/models.py` and migrations in `django_apps/*/migrations/`.
- Core domains in one DB: ACB transactions, holdings snapshots, net worth history, credit-card transactions, and account-specific data (RRSP, TFSA, FHSA).

### App modules & views
- `django_apps/accounts/`: user auth, login/register (accounts/views.py, accounts/urls.py)
- `django_apps/core/`: main business logic across multiple view files:
  - `transaction_views.py`: ACB ledger, securities, transaction CRUD
  - `holdings_views.py`: holdings dashboard/CRUD/cash/market refresh
  - `net_worth_views.py`: net worth CRUD
  - `credit_card_views.py`: credit card dashboard/filters/visibility/delete
  - `import_views.py`: DB import/export + staged import review + direct holdings/CC imports
  - `rrsp_views.py`, `tfsa_views.py`, `fhsa_views.py`: account-specific views and imports
  - `settings_views.py`: feature settings APIs

## Data flow and service boundaries
- ACB math is isolated in `django_apps/core/acb.py` (`calculate_ledger_rows`) and reused by transaction views and API endpoints.
- CSV/PDF parsing + idempotent import behavior lives in service modules (`django_apps/core/services/*_import_service.py`); views should stay thin and delegate there.
- Service-oriented architecture in `django_apps/core/services/`:
  - `settings_service.py` for feature settings parsing/persistence
  - `transactions_service.py` for transaction payload validation/normalization
  - `holdings_service.py` for holdings symbol/account/date/number normalization
  - `credit_card_service.py` for credit-card filter parsing
  - `rrsp_import_service.py`, `tfsa_import_service.py`, `fhsa_import_service.py` for account-specific imports
  - `rrsp_service.py`, `tfsa_service.py`, `fhsa_service.py` for account-specific logic
- Import-review flow is stateful:
  1. Parse file via service handler in `django_apps/core/services/`
  2. Persist staged rows via Django ORM models
  3. UI edits rows through review endpoints
  4. Commit endpoint forwards parsed rows to final import logic
- Account-specific and direct imports use corresponding service modules and persist via ORM upsert patterns.

## Frontend patterns (vanilla JS, server-rendered HTML)
- Templates are minimal shells (`app/templates/*.html`) and logic lives in page JS:
  - `app/static/overview.js` (dashboard, imports, net worth, cash account)
  - `app/static/security.js` (transaction CRUD + inline edit + ledger)
  - `app/static/credit_card.js` (filters, charts, transactions)
- Shared frontend utilities are in `app/static/common.js` (`fetchJson`, `escapeHtml`, number/currency formatters, chart defaults/helpers).
- Frontend API convention: `fetchJson()` expects `{ error: "..." }` payload for non-2xx responses.
- Use `escapeHtml()` from `common.js` before writing untrusted values into `innerHTML`.

## Project-specific conventions to preserve
- Security symbols are normalized uppercase at write boundaries (`security = ...upper()`).
- Transaction ordering is deterministic and important for ACB: always `ORDER BY trade_date, id`.
- Supported transaction types are a strict allowlist in `SUPPORTED_TRANSACTION_TYPES` (`django_apps/core/constants.py`); keep frontend dropdown in sync via API endpoints (do not hardcode duplicate lists).
- Numeric dedupe/upsert logic uses tolerance checks (`ABS(x - ?) < 0.000001`) in importer service paths; preserve this when extending import logic.
- Cash account is synthetic and keyed by account number `__CASH__` (`CASH_ACCOUNT_NUMBER` in `django_apps/core/constants.py`) in holdings models.
- For new DB fields/tables, define Django ORM models in `django_apps/*/models.py` and create migrations via `python manage.py makemigrations` and `python manage.py migrate`.

## Developer workflows
- Local run:
  - `python3 -m venv .venv && source .venv/bin/activate`
  - `pip install -r requirements.txt`
  - `python manage.py migrate` (apply database migrations)
  - `python manage.py runserver` or `python run.py` (serves on `http://localhost:8000`)
- Docker run: `docker compose up --build`.
- Database migrations:
  - After modifying models: `python manage.py makemigrations`
  - Apply migrations: `python manage.py migrate`
- Seeding demo data:
  - Populate database with fake data for testing: `python manage.py seed_demo_data` (source: `django_apps/core/management/commands/seed_demo_data.py`)
- There is no test suite in the repo currently; validate changes by exercising affected API endpoints/pages manually.

## Agent guidance for edits
- Keep view handlers thin in `django_apps/core/*.py`; place reusable validation/parsing/business logic in `django_apps/core/services/`.
- When adding UI features, wire HTML IDs/classes in the appropriate template first, then implement behavior in the matching JS file (do not add framework abstractions).
- Reuse `app/static/common.js` in page scripts rather than duplicating `fetchJson`/`escapeHtml`/formatting logic.
- Prefer additive, minimal schema/API changes; this app relies on stable endpoint names already consumed by existing JS.
- Use Django's class-based views (if extending) or function-based views following project conventions; keep authentication/authorization via Django's built-in auth system in `django_apps/accounts/`.
- When implementing new features (new models, fields, or domains), update the data seed command in `django_apps/core/management/commands/seed_demo_data.py` to include representative sample data for the new feature; this ensures the feature can be tested and demonstrated with `python manage.py seed_demo_data`.
