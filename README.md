# FinGlass

Simple web app to track securities transactions over time, with Adjusted Cost Base (ACB) calculations.

## Stack
- Python API: Flask
- Database: SQLite
- Frontend: server-rendered HTML + vanilla JS
- Containerization: Docker + docker compose

## Architecture
- App factory: `app/main.py` initializes Flask, database setup, and global auth guard.
- Route layer: domain blueprints in `app/routes/` (`auth`, `pages`, `transactions`, `holdings`, `net_worth`, `credit_card`, `imports`, `settings`).
- Service layer: shared business/parsing helpers in `app/services/`.
- Data/persistence: SQLite schema and migration-safe bootstrap in `app/db.py`.
- Frontend shared helpers: `app/static/common.js` used by page scripts to standardize API/error handling and formatting.

## Features
- Two-page flow: portfolio overview + per-security detail/edit page
- Staged import review (edit before save) for:
	- Broker activities CSV (`activities-export-YYYY-MM-DD.csv`)
	- Tax PDFs for ROC / Reinvested Capital Gains (`VFV.pdf`, `XEQT.pdf`, etc.)
- Add manual transactions (Buy, Sell, Return of Capital)
- View per-security summary (shares, ACB, ACB/share, realized capital gain)
- View rolling transaction ledger over time for each security
- Overview chart for portfolio allocation (%)
- Investment accounts dashboard with totals, account table, and holdings charts
- Broker holdings CSV import for account snapshot updates

## Run locally (without Docker)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Open: http://localhost:8000

Market data setup:
- Holdings symbol search and quote-based market value refresh use Alpha Vantage.
- API key is read from `config/market_data.json` (`alpha_vantage_api_key`).
- Optional override: set `ALPHA_VANTAGE_API_KEY` in the environment.
- Optional custom config path: set `MARKET_DATA_CONFIG_PATH`.
- Free-tier rate limits can still apply during heavy usage.

Import flow:
- Go to overview page.
- Choose **Import Type**.
- For **Activities CSV** and **Tax PDF**:
	- Click **Load File For Review**.
	- Review/edit staged rows.
	- Click **Commit Import**.
- For **Broker Holdings CSV**:
	- Click **Load File For Review** and pick your holdings report.
	- The snapshot is imported directly and the account dashboard updates.

## Run with Docker
```bash
docker compose up --build
```

Open: http://localhost:8000

Data is persisted in `./data/finglass.sqlite3`.