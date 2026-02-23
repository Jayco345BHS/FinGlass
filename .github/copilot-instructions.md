# Copilot Instructions for FinGlass

## Architecture at a glance
- `run.py` launches a Flask app from `app/main.py`; production container runs `gunicorn run:app`.
- App style is monolithic: routes, API handlers, and page rendering are all in `app/main.py`.
- Data persistence is SQLite at `data/finglass.sqlite3`; schema/init is centralized in `app/db.py` (`init_db()` is called at app startup and defensively in `get_db()`).
- Core domains in one DB: ACB transactions, staged imports, holdings snapshots, net worth history, and credit-card transactions.

## Data flow and service boundaries
- ACB math is isolated in `app/acb.py` (`calculate_ledger_rows`) and reused by `/api/ledger` and `/api/securities`.
- CSV/PDF parsing + idempotent import behavior lives in `app/importer.py` and `app/staged_imports.py`; route layer should stay thin and delegate there.
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
- Frontend API convention: shared `fetchJson()` helper expects `{ error: "..." }` payload for non-2xx responses.
- Use `escapeHtml()` before writing untrusted values into `innerHTML` (existing code consistently does this).

## Project-specific conventions to preserve
- Security symbols are normalized uppercase at write boundaries (`security = ...upper()`).
- Transaction ordering is deterministic and important for ACB: always `ORDER BY trade_date, id`.
- Supported transaction types are a strict allowlist in `SUPPORTED_TRANSACTION_TYPES` (`app/main.py`); keep frontend dropdown in sync via `/api/transaction-types` (do not hardcode duplicate lists).
- Numeric dedupe/upsert logic uses tolerance checks (`ABS(x - ?) < 0.000001`) in importer paths; preserve this when extending import logic.
- Cash account is synthetic and keyed by account number `__CASH__` in holdings snapshots (`/api/accounts/cash`).
- For new DB fields/tables, update `init_db()` migration-safe `CREATE TABLE IF NOT EXISTS` script in `app/db.py`.

## Developer workflows
- Local run:
  - `python3 -m venv .venv && source .venv/bin/activate`
  - `pip install -r requirements.txt`
  - `python run.py` (serves on `http://localhost:8000`)
- Docker run: `docker compose up --build`.
- There is no test suite in the repo currently; validate changes by exercising affected API endpoints/pages manually.

## Agent guidance for edits
- Keep business logic in `app/importer.py`, `app/staged_imports.py`, or `app/acb.py`; keep route handlers in `app/main.py` focused on validation + orchestration.
- When adding UI features, wire HTML IDs/classes in template first, then implement behavior in the matching JS file (do not add framework abstractions).
- Prefer additive, minimal schema/API changes; this app relies on stable endpoint names already consumed by existing JS.
