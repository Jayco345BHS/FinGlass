# FinGlass Import Guide

This guide explains how to import your financial data into FinGlass using the new Import Wizard.

## Quick Start

1. Click **"Launch Import Wizard"** from the dashboard
2. Select your import type
3. Upload your file (drag & drop or browse)
4. Review the parsed data
5. Click **"Import Data"** to complete

## Import Types Explained

### 📊 Investment Transactions
**Purpose:** Track buy/sell transactions for tax reporting and ACB (Adjusted Cost Base) calculations

**When to use:**
- End of year tax preparation
- After making trades in your investment account
- When you need to update your cost basis

**Where to get the file:**
- Download from your broker's website
- Look for "Activities Export" or "Transaction History"
- Export as CSV format
- Date range: typically annual (Jan 1 - Dec 31)

**What happens:**
- Transactions are staged for review
- You can edit dates, symbols, amounts before importing
- After import, ACB calculations update automatically
- View results in "ACB Securities" section on dashboard

---

### 💼 Holdings Snapshot
**Purpose:** Show your current investment positions across all accounts

**When to use:**
- Monthly or quarterly portfolio reviews
- When you want to see total market value
- To track allocation by account or security

**Where to get the file:**
- Download from your broker's portfolio page
- Look for "Holdings Export" or "Positions Report"
- Export as CSV format
- Contains current as-of date and market prices

**What happens:**
- Replaces your previous snapshot (not additive)
- Dashboard shows: accounts, positions, market values
- Charts update with new allocation percentages
- Can also track cash holdings

---

### 💳 Credit Card Transactions
**Purpose:** Track spending and expenses by category

**When to use:**
- Monthly budget reviews
- Expense analysis by category
- Year-end spending summaries

**Where to get the file:**
- Download from Rogers Bank online banking
- Transaction history export
- CSV format with transaction details

**Also supported:**
- Scotiabank credit card CSV exports (account activity/statement download)
- FinGlass auto-detects Rogers vs Scotiabank format during import

**What happens:**
- Transactions import directly (no review step)
- Categories are automatically normalized
- View summary and charts in "Credit Card" section
- Can filter by date range and category

---

### 📄 Tax Documents
**Purpose:** Import Return of Capital (ROC) and reinvested capital gains from tax slips

**When to use:**
- After receiving T3/T5 tax slips
- Need to adjust ACB for distributions
- Tax season preparation

**Where to get the file:**
- Download PDF from broker or fund company
- T3 slips (ROC is typically Box 42)
- T5 slips for reinvested gains

**Important:**
- Include the security symbol in the PDF filename
- Example: `VDY-T3-2024.pdf` or `XEQT-T3-2024.pdf`
- The wizard will extract transactions from the PDF

**What happens:**
- PDF is parsed for relevant tax information
- Transactions are staged for review
- You can verify amounts before importing
- ACB calculations incorporate the adjustments

---

## Tips & Best Practices

### File Naming
- Use descriptive filenames with dates: `activities-2024.csv`
- For tax PDFs, include symbol: `SYMBOL-T3-YYYY.pdf`
- Avoid special characters in filenames

### Before Importing
- Download the template file to see expected format
- Check that your file has all required columns
- Verify dates are in YYYY-MM-DD format
- Remove any header/footer rows from exports

### Review Step
- Always review the preview before importing
- Check for duplicate transactions
- Verify symbols are uppercase and correct
- Confirm dates and amounts match your records

### After Importing
- Check the dashboard to confirm data loaded
- For transactions: verify ACB calculations look correct
- For holdings: check total market value makes sense
- Export a database backup regularly

### Common Issues

**"No rows found"**
- Check your file has the correct columns
- Verify there's actual data (not just headers)
- Try downloading the template and comparing

**"Invalid date format"**
- Dates should be YYYY-MM-DD or YYYY-MMM-DD
- Examples: `2024-01-15` or `2024-Jan-15`

**"Unsupported file type"**
- Investment transactions: CSV only
- Holdings: CSV only
- Credit card: CSV only
- Tax documents: PDF only

**Symbol not recognized**
- Ensure ticker symbols are correct
- Use exchange-specific tickers (e.g., `VDY` for TSX)
- Edit in the review step if needed

---

## Database Backup & Restore

### Exporting Your Database
- Click **"Export Database"** on the dashboard
- Downloads complete backup with all your data
- Filename includes timestamp
- Keep regular backups (weekly or monthly)

### Importing a Database
- Click **"Import Database"** on the dashboard
- ⚠️ **WARNING:** This overwrites all existing data
- Confirm you want to replace everything
- Your current user account is preserved

**When to use:**
- Restoring from backup
- Moving data to a new installation
- Recovering from accidental deletions

---

## Need Help?

If you're stuck or something isn't working:

1. Check the format requirements in the wizard
2. Download and compare with the template file
3. Try a small test file first (1-2 rows)
4. Check the error message for specific issues
5. Verify your broker's export format hasn't changed

The Import Wizard is designed to be self-explanatory, but if you have questions about where to find specific files from your broker or bank, consult their help documentation or contact their support.
