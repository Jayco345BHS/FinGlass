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
- Portfolio overview dashboard with charts and summaries
- Per-security detail/edit page with full transaction history
- **Intuitive Import Wizard** with guided step-by-step process for:
	- Investment transactions (Activities CSV from your broker)
	- Holdings snapshots (Portfolio positions CSV from your broker)
	- Credit card transactions (Rogers Bank statement CSV)
	- Tax documents (ROC / Reinvested Capital Gains PDFs)
- Preview and review all imports before committing
- Add manual transactions (Buy, Sell, Return of Capital)
- View per-security summary (shares, ACB, ACB/share, realized capital gain)
- View rolling transaction ledger over time for each security
- Overview charts for portfolio allocation and market value
- Investment accounts dashboard with holdings breakdown
- Credit card expense tracking with category breakdowns
- Net worth tracker with historical graphs
- Database export/import for backups

## Run locally (without Docker)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Open: http://localhost:8000

Security env vars:
- Set `FLASK_SECRET_KEY` (or `SECRET_KEY`) in production to use a stable strong session-signing key.
- Optional: set `SESSION_COOKIE_SECURE=true` when serving over HTTPS.

Market data setup:
- Holdings symbol search and quote-based market value refresh use Alpha Vantage.
- API key is read from `config/market_data.json` (`alpha_vantage_api_key`).
- Optional override: set `ALPHA_VANTAGE_API_KEY` in the environment.
- Optional custom config path: set `MARKET_DATA_CONFIG_PATH`.
- Free-tier rate limits can still apply during heavy usage.

## Using the Import Wizard

The revamped import wizard provides a clear, step-by-step experience for bringing data into FinGlass:

### Getting Started
1. From the dashboard, click **"Launch Import Wizard"**
2. Select the type of data you want to import:
   - **Investment Transactions** - For ACB tracking
   - **Holdings Snapshot** - Current portfolio positions
   - **Credit Card Transactions** - Expense tracking
   - **Tax Documents** - ROC and reinvested gains

### Import Process
1. **Select Type**: Choose what you're importing
2. **Upload File**: Drag & drop or browse for your file
   - See format requirements and download templates
   - File is validated immediately
3. **Review & Edit**: Preview parsed data before importing
   - Edit any fields if needed
   - See warnings about duplicates or issues
4. **Complete**: Data is imported and dashboard updates

### File Format Requirements

**Investment Transactions CSV:**
Required columns: `transaction_date`, `symbol`, `activity_type`, `activity_sub_type`, `quantity`, `net_cash_amount`, `commission`

**Holdings Snapshot CSV:**
Required columns: `Symbol`, `Account Number`, `Account Name`, `Account Type`, `Quantity`, `Market Price`, `Market Value`, `Book Value (CAD)`

**Credit Card CSV:**
Download from Rogers Bank online banking. Should include: Transaction Date, Posted Date, Description, Amount, Category

**Tax PDFs:**
T3/T5 slips with Return of Capital or reinvested capital gains. Include security symbol in filename (e.g., `VDY-T3-2024.pdf`)

### Template Files
Each import type includes a downloadable template showing the expected format. Click "Download Template File" in the wizard to get a sample.

## Legacy Import (Deprecated)
The old dropdown-based import on the overview page has been replaced with the Import Wizard, which provides:
- Clear descriptions of what each import type does
- Format requirements shown upfront
- Better error messages
- Consistent preview/review flow for all imports

## Run with Docker
```bash
docker compose up --build
```

Optional environment setup (recommended):
- Create a `.env` file in project root.
- Set `FLASK_SECRET_KEY` to a strong random value so sessions remain valid across container restarts.

Open: http://localhost:8000

Data is persisted in `./data/finglass.sqlite3`.