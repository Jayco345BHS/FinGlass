# FinGlass

Simple web app to track securities transactions over time, with Adjusted Cost Base (ACB) calculations.

## Stack
- Python API: Flask
- Database: SQLite
- Frontend: server-rendered HTML + vanilla JS
- Containerization: Docker + docker compose

## Features
- Two-page flow: portfolio overview + per-security detail/edit page
- Staged import review (edit before save) for:
	- Broker activities CSV (`activities-export-YYYY-MM-DD.csv`)
	- Tax PDFs for ROC / Reinvested Capital Gains (`VFV.pdf`, `XEQT.pdf`, etc.)
	- AdjustedCostBase CSV (initial migration)
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

Import flow:
- Go to overview page.
- Choose **Import Type**.
- For **Activities CSV**, **Tax PDF**, and **AdjustedCostBase CSV**:
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

Data is persisted in `./data/acb.sqlite3`.