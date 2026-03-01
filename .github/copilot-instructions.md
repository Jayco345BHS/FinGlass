# Copilot Instructions for FinGlass

## Architecture at a glance
- `run.py` launches a Flask app from `app/main.py`; production container runs `gunicorn run:app`.
- App is modular: app factory + auth guard in `app/main.py`, route blueprints in `app/routes/`, shared helpers in `app/services/` and `app/context.py`.
- Data persistence is SQLite at `data/finglass.sqlite3`; schema/init is centralized in `app/db.py` (`init_db()` is called at app startup and defensively in `get_db()`).
- Core domains in one DB: ACB transactions, staged imports, holdings snapshots, net worth history, and credit-card transactions.

### Route modules
- `app/routes/auth_routes.py`: auth + login/register/session APIs
- `app/routes/page_routes.py`: server-rendered page endpoints
- `app/routes/transactions_routes.py`: transactions, ledger, securities, transaction types
- `app/routes/holdings_routes.py`: holdings dashboard/CRUD/cash/market refresh
- `app/routes/net_worth_routes.py`: net worth CRUD
- `app/routes/credit_card_routes.py`: credit card dashboard/filters/visibility/delete
- `app/routes/import_routes.py`: DB import/export + staged import review + direct holdings/CC imports
- `app/routes/settings_routes.py`: feature settings APIs

## Data flow and service boundaries
- ACB math is isolated in `app/acb.py` (`calculate_ledger_rows`) and reused by `/api/ledger` and `/api/securities`.
- CSV/PDF parsing + idempotent import behavior lives in `app/importer.py` and `app/staged_imports.py`; route layer should stay thin and delegate there.
- Route-specific parsing/normalization helpers live in `app/services/`:
  - `settings_service.py` for feature settings parsing/persistence
  - `transactions_service.py` for transaction payload validation/normalization
  - `holdings_service.py` for holdings symbol/account/date/number normalization
  - `credit_card_service.py` for credit-card filter parsing
- Import-review flow is stateful:
  1. Parse file via `parse_upload()` in `staged_imports.py`
  2. Persist staged rows in `import_batches` / `import_batch_rows`
  3. UI edits rows through review endpoints
  4. `commit_batch()` forwards parsed rows to `import_transactions_rows()`
- Holdings and Rogers credit card imports bypass staged review (`/api/import/holdings-csv`, `/api/import/credit-card/rogers-csv`) and upsert/insert directly.

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
- Supported transaction types are a strict allowlist in `SUPPORTED_TRANSACTION_TYPES` (`app/constants.py`); keep frontend dropdown in sync via `/api/transaction-types` (do not hardcode duplicate lists).
- Numeric dedupe/upsert logic uses tolerance checks (`ABS(x - ?) < 0.000001`) in importer paths; preserve this when extending import logic.
- Cash account is synthetic and keyed by account number `__CASH__` (`CASH_ACCOUNT_NUMBER` in `app/constants.py`) in holdings snapshots (`/api/accounts/cash`).
- For new DB fields/tables, update both schema (`SCHEMA_SQL`) and migration-safe logic in `app/db.py`.

## Developer workflows
- Local run:
  - `python3 -m venv .venv && source .venv/bin/activate`
  - `pip install -r requirements.txt`
  - `python run.py` (serves on `http://localhost:8000`)
- Docker run: `docker compose up --build`.
- There is no test suite in the repo currently; validate changes by exercising affected API endpoints/pages manually.

## Agent guidance for edits
- Keep route handlers thin in `app/routes/*`; place reusable validation/parsing/business logic in `app/services/` (or domain modules like `app/importer.py`, `app/staged_imports.py`, `app/acb.py`).
- When adding UI features, wire HTML IDs/classes in template first, then implement behavior in the matching JS file (do not add framework abstractions).
- Reuse `app/static/common.js` in page scripts rather than duplicating `fetchJson`/`escapeHtml`/formatting logic.
- Prefer additive, minimal schema/API changes; this app relies on stable endpoint names already consumed by existing JS.
