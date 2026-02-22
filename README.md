# ACB Tracker

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
- Click **Load File For Review**.
- Review/edit staged rows.
- Click **Commit Import**.

## Run with Docker
```bash
docker compose up --build
```

Open: http://localhost:8000

Data is persisted in `./data/acb.sqlite3`.