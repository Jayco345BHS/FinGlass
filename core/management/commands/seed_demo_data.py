"""
Django management command: seed_demo_data

Populates the database with realistic fake data across all FinGlass features
so that every screen can be reviewed and tested with real-looking content.

Usage:
    python manage.py seed_demo_data                  # seed into existing user 'testuser'
    python manage.py seed_demo_data --username demo  # seed into a specific username
    python manage.py seed_demo_data --flush          # clear existing demo data first
    python manage.py seed_demo_data --username demo --flush --create-user

The command is idempotent when run without --flush: it skips records that
already exist (checked by date/security/unique constraint).
"""

import random
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import (
    AppSetting,
    CreditCardTransaction,
    FhsaAccount,
    FhsaContribution,
    HoldingSnapshot,
    NetWorthHistory,
    RrspAccount,
    RrspAnnualLimit,
    RrspContribution,
    TfsaAccount,
    TfsaAnnualLimit,
    TfsaContribution,
    Transaction,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _d(year, month, day):
    return date(year, month, day)


def _dec(val):
    return Decimal(str(round(val, 6)))


# ---------------------------------------------------------------------------
# Data tables
# ---------------------------------------------------------------------------

# ACB securities: (symbol, name, start_price, annual_drift)
SECURITIES = [
    ("XEQT.TO",  "iShares Core Equity ETF Portfolio",             28.50,  0.10),
    ("VFV.TO",   "Vanguard S&P 500 Index ETF",                    110.00, 0.15),
    ("ZAG.TO",   "BMO Aggregate Bond Index ETF",                   14.20, 0.03),
    ("SHOP.TO",  "Shopify Inc.",                                   70.00,  0.25),
    ("ENB.TO",   "Enbridge Inc.",                                  50.00,  0.05),
]

# Credit card merchants by category
CC_MERCHANTS = {
    "Groceries":      [("LOBLAWS",          10.00, 250.00),
                       ("METRO",            8.00, 180.00),
                       ("WHOLE FOODS",      15.00, 320.00),
                       ("SOBEYS",           9.00, 200.00)],
    "Dining":         [("TIM HORTONS",      4.00,  18.00),
                       ("MCDONALDS",        6.00,  25.00),
                       ("STARBUCKS",        5.00,  22.00),
                       ("SWISS CHALET",    12.00,  80.00),
                       ("LOCAL RAMEN",     10.00,  55.00)],
    "Transport":      [("UBER",             8.00,  45.00),
                       ("PRESTO",          12.00, 160.00),
                       ("ESSO",            20.00, 120.00),
                       ("SHELL",           22.00, 130.00)],
    "Shopping":       [("AMAZON",          15.00, 350.00),
                       ("BESTBUY",         50.00, 600.00),
                       ("WINNERS",         10.00,  90.00),
                       ("INDIGO",           8.00,  55.00)],
    "Entertainment":  [("NETFLIX",         17.00,  17.00),
                       ("SPOTIFY",          9.00,   9.99),
                       ("CINEPLEX",        12.00,  28.00),
                       ("APPLE",           10.00,  15.00)],
    "Health":         [("SHOPPERS DRUG",    5.00, 120.00),
                       ("GYM",             35.00,  65.00),
                       ("DENTAL CLINIC",   80.00, 320.00)],
    "Utilities":      [("HYDRO ONE",       40.00, 180.00),
                       ("ROGERS",          60.00, 130.00),
                       ("INTERNET CO",     55.00, 120.00)],
    "Travel":         [("AIR CANADA",     150.00, 800.00),
                       ("MARRIOTT",       120.00, 450.00),
                       ("EXPEDIA",         80.00, 600.00)],
}

# TFSA annual contribution limits (government-announced)
TFSA_ANNUAL_LIMITS = {
    2022: 6000, 2023: 6500, 2024: 7000, 2025: 7000,
}

# RRSP annual contribution limits
RRSP_ANNUAL_LIMITS = {
    2022: 29210, 2023: 30780, 2024: 31560, 2025: 32490,
}


# ---------------------------------------------------------------------------
# Seeder functions
# ---------------------------------------------------------------------------

def _seed_acb_transactions(user, stdout):
    """Buy/sell/dividend transactions for 5 securities over 3 years."""
    stdout.write("  Seeding ACB transactions...")
    created = 0
    rng = random.Random(42)

    for symbol, _name, start_price, drift in SECURITIES:
        price = start_price
        shares_held = Decimal("0")

        # Build a sequence of dated events
        events = []

        # Initial buy in early 2022
        events.append((_d(2022, 1, 15), "Buy", 200))
        events.append((_d(2022, 4, 10), "Buy", 100))

        if symbol in ("XEQT.TO", "VFV.TO", "ZAG.TO"):
            # ETFs get quarterly reinvested dividends
            for yr in (2022, 2023, 2024):
                for mo in (3, 6, 9, 12):
                    events.append((_d(yr, mo, 15), "Reinvested Dividend", None))

        if symbol == "SHOP.TO":
            # Partial sell in 2023 bull run
            events.append((_d(2023, 6, 20), "Buy", 50))
            events.append((_d(2023, 11, 5), "Sell", 120))

        if symbol == "ENB.TO":
            # Dividend income + extra buy
            for yr in (2022, 2023, 2024):
                for mo in (3, 6, 9, 12):
                    events.append((_d(yr, mo, 1), "Capital Gains Dividend", None))
            events.append((_d(2024, 3, 1), "Buy", 150))
            events.append((_d(2024, 9, 1), "Return of Capital", None))

        events.append((_d(2025, 1, 10), "Buy", 75))

        events.sort(key=lambda e: e[0])

        for event_date, tx_type, qty in events:
            # Advance price with drift + noise
            days_elapsed = (event_date - _d(2022, 1, 1)).days
            price = start_price * (1 + drift) ** (days_elapsed / 365.0) * (1 + rng.uniform(-0.05, 0.05))
            price = round(max(1.0, price), 2)

            if tx_type == "Buy":
                shares = Decimal(str(qty))
                amount = _dec(float(shares) * price)
                commission = _dec(rng.choice([0, 0, 4.95, 9.99]))
                shares_held += shares
            elif tx_type == "Sell":
                shares = Decimal(str(min(qty, int(shares_held))))
                if shares <= 0:
                    continue
                amount = _dec(float(shares) * price)
                commission = _dec(rng.choice([0, 4.95, 9.99]))
                shares_held -= shares
            elif tx_type in ("Reinvested Dividend", "Capital Gains Dividend"):
                if shares_held <= 0:
                    continue
                dividend_per_share = round(price * rng.uniform(0.005, 0.012), 4)
                amount = _dec(float(shares_held) * dividend_per_share)
                reinvested_shares = _dec(float(amount) / price)
                shares = reinvested_shares
                commission = Decimal("0")
                if tx_type == "Reinvested Dividend":
                    shares_held += reinvested_shares
            elif tx_type == "Return of Capital":
                if shares_held <= 0:
                    continue
                roc_per_share = round(price * 0.003, 4)
                amount = _dec(float(shares_held) * roc_per_share)
                shares = Decimal("0")
                commission = Decimal("0")
            else:
                continue

            exists = Transaction.objects.filter(
                user=user, security=symbol.upper(), trade_date=event_date, transaction_type=tx_type
            ).exists()
            if not exists:
                Transaction.objects.create(
                    user=user,
                    security=symbol.upper(),
                    trade_date=event_date,
                    transaction_type=tx_type,
                    amount=amount,
                    shares=shares,
                    commission=commission,
                    source="seed_demo_data",
                )
                created += 1

    stdout.write(f"    Created {created} ACB transaction(s).")


def _seed_holdings(user, stdout):
    """Holdings snapshot as of today for TFSA, RRSP, and Non-registered accounts."""
    stdout.write("  Seeding holdings snapshots...")
    as_of = date(2025, 2, 28)
    created = 0

    accounts = [
        ("TD TFSA",          "TFSA",           "tfsa-001",    "Registered"),
        ("RBC RRSP",         "RRSP",           "rrsp-001",    "Registered"),
        ("Questrade NR",     "Non-registered", "nr-001",      "Non-Registered"),
    ]

    # (symbol, name, qty, book_cad, mkt_cad)
    holdings_by_account = {
        "tfsa-001": [
            ("XEQT.TO",  "iShares Core Equity ETF Portfolio",  700.0,  19040.00,  28224.00),
            ("VFV.TO",   "Vanguard S&P 500 Index ETF",         160.0,  16640.00,  25800.00),
            ("ZAG.TO",   "BMO Aggregate Bond Index ETF",      1000.0,  14100.00,  18144.00),
        ],
        "rrsp-001": [
            ("XEQT.TO",  "iShares Core Equity ETF Portfolio", 1000.0, 27000.00,  40320.00),
            ("ENB.TO",   "Enbridge Inc.",                      800.0, 38400.00,  54432.00),
        ],
        "nr-001": [
            ("VFV.TO",   "Vanguard S&P 500 Index ETF",         400.0, 42000.00,  64512.00),
            ("SHOP.TO",  "Shopify Inc.",                       200.0, 14000.00,  24696.00),
            ("ENB.TO",   "Enbridge Inc.",                      600.0, 28800.00,  40068.00),
            ("ZAG.TO",   "BMO Aggregate Bond Index ETF",       500.0,  7100.00,   9072.00),
        ],
    }

    for acc_name, acc_type, acc_num, acc_class in accounts:
        for sym, sec_name, qty, book, mkt in holdings_by_account.get(acc_num, []):
            unrealized = round(mkt - book, 2)
            obj, created_flag = HoldingSnapshot.objects.get_or_create(
                user=user,
                as_of=as_of,
                account_number=acc_num,
                symbol=sym.upper(),
                defaults=dict(
                    account_name=acc_name,
                    account_type=acc_type,
                    account_classification=acc_class,
                    security_name=sec_name,
                    quantity=_dec(qty),
                    book_value_cad=_dec(book),
                    market_value=_dec(mkt),
                    unrealized_return=_dec(unrealized),
                    market_price=_dec(round(mkt / qty, 4)),
                    market_price_currency="CAD",
                    market_value_currency="CAD",
                    source_filename="seed_demo_data",
                ),
            )
            if created_flag:
                created += 1

    stdout.write(f"    Created {created} holding snapshot row(s).")


def _seed_net_worth(user, stdout):
    """Monthly net worth entries from Jan 2023 through Feb 2025."""
    stdout.write("  Seeding net worth history...")
    created = 0
    rng = random.Random(7)

    base = 85_000.0
    entries = []
    d = date(2023, 1, 31)
    end = date(2025, 2, 28)
    notes = {
        date(2023, 3, 31): "Tax refund deposited",
        date(2023, 7, 31): "Summer travel expenses",
        date(2023, 12, 31): "Year-end bonus",
        date(2024, 4, 30): "Car purchase — net worth dip",
        date(2024, 12, 31): "Strong market year",
    }

    while d <= end:
        base *= 1 + rng.uniform(0.005, 0.022)  # monthly growth with noise
        entries.append((d, round(base, 2), notes.get(d, "")))
        # advance to last day of next month
        if d.month == 12:
            d = date(d.year + 1, 1, 31)
        else:
            import calendar
            next_month = d.month + 1
            last_day = calendar.monthrange(d.year, next_month)[1]
            d = date(d.year, next_month, last_day)

    for entry_date, amount, note in entries:
        _, created_flag = NetWorthHistory.objects.get_or_create(
            user=user,
            entry_date=entry_date,
            defaults={"amount": _dec(amount), "note": note or None},
        )
        if created_flag:
            created += 1

    stdout.write(f"    Created {created} net worth entry/entries.")


def _seed_credit_card(user, stdout):
    """~150 credit card transactions across 14 months with realistic spending patterns, across 2 card providers."""
    stdout.write("  Seeding credit card transactions...")
    created = 0
    rng = random.Random(13)

    start = date(2024, 1, 1)
    end = date(2025, 2, 28)

    # Each card: (provider, card_label, card_last4, rewards_rate, category_weight_multiplier)
    CARDS = [
        ("rogers_bank", "Rogers Bank Visa", "4242", 0.015, 1.0),
        ("td_bank", "TD Cashback Visa", "8811", 0.010, 0.5),
    ]

    # Monthly frequency weights per category
    MONTHLY_FREQ = {
        "Groceries":     10,
        "Dining":        14,
        "Transport":      8,
        "Shopping":       5,
        "Entertainment":  4,
        "Health":         3,
        "Utilities":      3,
        "Travel":         1,
    }

    d = start
    while d <= end:
        for provider, card_label, card_last4, rewards_rate, weight_mult in CARDS:
            for category, freq in MONTHLY_FREQ.items():
                adjusted_freq = max(1, int(freq * weight_mult))
                for _ in range(rng.randint(max(1, adjusted_freq - 1), adjusted_freq + 1)):
                    merchant, min_amt, max_amt = rng.choice(CC_MERCHANTS[category])
                    amount = round(rng.uniform(min_amt, max_amt), 2)
                    tx_date = d + timedelta(days=rng.randint(0, 27))
                    if tx_date > end:
                        tx_date = end

                    CreditCardTransaction.objects.create(
                        user=user,
                        provider=provider,
                        card_label=card_label,
                        transaction_date=tx_date,
                        posted_date=tx_date + timedelta(days=rng.randint(1, 3)),
                        reference_number=f"REF{rng.randint(100000, 999999)}",
                        activity_type="Purchase",
                        status="Posted",
                        card_last4=card_last4,
                        merchant_category=category,
                        merchant_name=merchant,
                        merchant_city="Toronto",
                        merchant_region="ON",
                        merchant_country="Canada",
                        amount=_dec(amount),
                        rewards=_dec(round(amount * rewards_rate, 2)),
                    )
                    created += 1

        # Advance by roughly one month
        if d.month == 12:
            d = date(d.year + 1, 1, 1)
        else:
            d = date(d.year, d.month + 1, 1)

    stdout.write(f"    Created {created} credit card transaction(s).")


def _seed_tfsa(user, stdout):
    """Two TFSA accounts with deposits, withdrawals and annual limits 2022-2025."""
    stdout.write("  Seeding TFSA data...")

    # Annual limits
    for year, limit in TFSA_ANNUAL_LIMITS.items():
        TfsaAnnualLimit.objects.get_or_create(
            user=user, year=year,
            defaults={"annual_limit": _dec(limit)},
        )

    # Opening balance (CRA room as of 2022-01-01 base year)
    AppSetting.objects.update_or_create(
        user=user, key="tfsa_opening_balance",
        defaults={"value": "41500"},
    )
    AppSetting.objects.update_or_create(
        user=user, key="tfsa_opening_balance_base_year",
        defaults={"value": "2022"},
    )

    acc1, _ = TfsaAccount.objects.get_or_create(
        user=user, account_name="TD Direct TFSA",
        defaults={"account_number": "tfsa-td-001"},
    )
    acc2, _ = TfsaAccount.objects.get_or_create(
        user=user, account_name="Questrade TFSA",
        defaults={"account_number": "tfsa-qt-001"},
    )

    contributions = [
        # (account, date, type, amount, memo)
        (acc1, _d(2022, 1, 15),  "Deposit",    6000, "Annual max contribution"),
        (acc1, _d(2022, 6, 10),  "Withdrawal", 2500, "Emergency fund draw"),
        (acc1, _d(2023, 1, 10),  "Deposit",    6500, "Annual max contribution"),
        (acc1, _d(2023, 8, 1),   "Deposit",    2500, "Re-contribution of 2022 withdrawal"),
        (acc2, _d(2024, 1, 5),   "Deposit",    7000, "Annual max contribution"),
        (acc2, _d(2024, 6, 15),  "Deposit",    3500, "Mid-year top-up"),
        (acc2, _d(2025, 1, 8),   "Deposit",    7000, "Annual max contribution"),
    ]

    created = 0
    for acc, cdate, ctype, amt, memo in contributions:
        exists = TfsaContribution.objects.filter(
            user=user, tfsa_account=acc, contribution_date=cdate, contribution_type=ctype,
        ).exists()
        if not exists:
            TfsaContribution.objects.create(
                user=user, tfsa_account=acc,
                contribution_date=cdate, contribution_type=ctype,
                amount=_dec(amt), memo=memo,
            )
            created += 1

    stdout.write(f"    Created {created} TFSA contribution(s).")


def _seed_rrsp(user, stdout):
    """Two RRSP accounts with deposits and annual limits 2022-2025."""
    stdout.write("  Seeding RRSP data...")

    for year, limit in RRSP_ANNUAL_LIMITS.items():
        RrspAnnualLimit.objects.get_or_create(
            user=user, year=year,
            defaults={"annual_limit": _dec(limit)},
        )

    AppSetting.objects.update_or_create(
        user=user, key="rrsp_opening_balance",
        defaults={"value": "45000"},
    )
    AppSetting.objects.update_or_create(
        user=user, key="rrsp_opening_balance_base_year",
        defaults={"value": "2022"},
    )

    acc1, _ = RrspAccount.objects.get_or_create(
        user=user, account_name="RBC RRSP",
        defaults={"account_number": "rrsp-rbc-001"},
    )
    acc2, _ = RrspAccount.objects.get_or_create(
        user=user, account_name="Spousal RRSP — RBC",
        defaults={"account_number": "rrsp-rbc-002"},
    )

    contributions = [
        (acc1, _d(2022, 3, 1),  "Deposit",    15000, "Lump-sum RRSP contribution",    False, 2022),
        (acc1, _d(2023, 2, 20), "Deposit",    18000, "Annual contribution",            False, 2023),
        (acc2, _d(2023, 2, 20), "Deposit",     5000, "Spousal contribution",           False, 2023),
        (acc1, _d(2024, 2, 15), "Deposit",    20000, "Annual contribution",            False, 2024),
        (acc2, _d(2024, 2, 15), "Deposit",     5000, "Spousal contribution",           False, 2024),
        (acc1, _d(2025, 1, 20), "Deposit",    10000, "Early 2025 contribution",        True,  None),
    ]

    created = 0
    for acc, cdate, ctype, amt, memo, is_unused, deducted_yr in contributions:
        exists = RrspContribution.objects.filter(
            user=user, rrsp_account=acc, contribution_date=cdate, contribution_type=ctype,
        ).exists()
        if not exists:
            RrspContribution.objects.create(
                user=user, rrsp_account=acc,
                contribution_date=cdate, contribution_type=ctype,
                amount=_dec(amt), memo=memo,
                is_unused=is_unused, deducted_tax_year=deducted_yr,
            )
            created += 1

    stdout.write(f"    Created {created} RRSP contribution(s).")


def _seed_fhsa(user, stdout):
    """One FHSA account opened 2023 with annual contributions."""
    stdout.write("  Seeding FHSA data...")

    AppSetting.objects.update_or_create(
        user=user, key="fhsa_opening_balance",
        defaults={"value": "0"},
    )
    AppSetting.objects.update_or_create(
        user=user, key="fhsa_opening_balance_base_year",
        defaults={"value": "2023"},
    )

    acc, _ = FhsaAccount.objects.get_or_create(
        user=user, account_name="Questrade FHSA",
        defaults={"account_number": "fhsa-qt-001"},
    )

    contributions = [
        (_d(2023, 4, 1),  "Deposit",  8000, "Max annual contribution — year 1"),
        (_d(2024, 1, 10), "Deposit",  8000, "Max annual contribution — year 2"),
        (_d(2024, 7, 15), "Deposit",  8000, "Carry-forward room from 2023"),
        (_d(2025, 1, 12), "Deposit",  8000, "Max annual contribution — year 3"),
    ]

    created = 0
    for cdate, ctype, amt, memo in contributions:
        exists = FhsaContribution.objects.filter(
            user=user, fhsa_account=acc, contribution_date=cdate, contribution_type=ctype,
        ).exists()
        if not exists:
            FhsaContribution.objects.create(
                user=user, fhsa_account=acc,
                contribution_date=cdate, contribution_type=ctype,
                amount=_dec(amt), memo=memo,
                is_qualifying_withdrawal=False,
            )
            created += 1

    stdout.write(f"    Created {created} FHSA contribution(s).")


def _flush_user_data(user, stdout):
    """Delete all seeded data for the given user."""
    stdout.write(f"  Flushing all demo data for user '{user.username}'...")
    with transaction.atomic():
        Transaction.objects.filter(user=user).delete()
        HoldingSnapshot.objects.filter(user=user).delete()
        NetWorthHistory.objects.filter(user=user).delete()
        CreditCardTransaction.objects.filter(user=user).delete()
        TfsaContribution.objects.filter(user=user).delete()
        TfsaAccount.objects.filter(user=user).delete()
        TfsaAnnualLimit.objects.filter(user=user).delete()
        RrspContribution.objects.filter(user=user).delete()
        RrspAccount.objects.filter(user=user).delete()
        RrspAnnualLimit.objects.filter(user=user).delete()
        FhsaContribution.objects.filter(user=user).delete()
        FhsaAccount.objects.filter(user=user).delete()
        AppSetting.objects.filter(
            user=user,
            key__in=[
                "tfsa_opening_balance", "tfsa_opening_balance_base_year",
                "rrsp_opening_balance", "rrsp_opening_balance_base_year",
                "fhsa_opening_balance", "fhsa_opening_balance_base_year",
            ],
        ).delete()
    stdout.write("  Flush complete.")


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------

class Command(BaseCommand):
    help = (
        "Seed realistic demo data across all FinGlass features. "
        "Safe to re-run; existing records are skipped unless --flush is passed."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            default="testuser",
            help="Username to seed data for (default: testuser)",
        )
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Delete all existing data for the user before seeding",
        )
        parser.add_argument(
            "--create-user",
            action="store_true",
            dest="create_user",
            help="Create the user if they do not exist (password: testpass123)",
        )

    def handle(self, *args, **options):
        username = options["username"]

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            if options["create_user"]:
                user = User.objects.create_superuser(username=username, password="testpass123")
                self.stdout.write(self.style.SUCCESS(f"Created superuser '{username}' (password: testpass123)"))
            else:
                raise CommandError(
                    f"User '{username}' does not exist. "
                    "Use --create-user to create them automatically."
                )

        self.stdout.write(self.style.MIGRATE_HEADING(f"Seeding demo data for user '{username}'"))

        if options["flush"]:
            _flush_user_data(user, self.stdout)

        with transaction.atomic():
            _seed_acb_transactions(user, self.stdout)
            _seed_holdings(user, self.stdout)
            _seed_net_worth(user, self.stdout)
            _seed_credit_card(user, self.stdout)
            _seed_tfsa(user, self.stdout)
            _seed_rrsp(user, self.stdout)
            _seed_fhsa(user, self.stdout)

        self.stdout.write(self.style.SUCCESS("Done! All demo data seeded successfully."))
