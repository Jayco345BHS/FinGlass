from django.conf import settings
from django.db import models


class Transaction(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="transactions")
    security = models.CharField(max_length=32)
    trade_date = models.DateField()
    transaction_type = models.CharField(max_length=32)
    amount = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    shares = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    amount_per_share = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    commission = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    memo = models.TextField(null=True, blank=True)
    source = models.CharField(max_length=64, default="manual")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["security", "trade_date", "id"], name="idx_transactions_security_date"),
        ]


class ImportBatch(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="import_batches")
    source_type = models.CharField(max_length=64)
    source_filename = models.CharField(max_length=255, null=True, blank=True)
    status = models.CharField(max_length=32, default="staged")
    created_at = models.DateTimeField(auto_now_add=True)
    committed_at = models.DateTimeField(null=True, blank=True)


class ImportBatchRow(models.Model):
    batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name="rows")
    row_order = models.IntegerField()
    security = models.CharField(max_length=32)
    trade_date = models.DateField()
    transaction_type = models.CharField(max_length=32)
    amount = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    shares = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    amount_per_share = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    commission = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    source = models.CharField(max_length=64, default="import_review")

    class Meta:
        indexes = [models.Index(fields=["batch", "row_order", "id"], name="idx_import_batch_rows_batch")]


class HoldingSnapshot(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="holdings_snapshots")
    as_of = models.DateField()
    account_name = models.CharField(max_length=255)
    account_type = models.CharField(max_length=128, null=True, blank=True)
    account_classification = models.CharField(max_length=128, null=True, blank=True)
    account_number = models.CharField(max_length=64)
    symbol = models.CharField(max_length=32)
    exchange = models.CharField(max_length=32, null=True, blank=True)
    mic = models.CharField(max_length=16, null=True, blank=True)
    security_name = models.CharField(max_length=255, null=True, blank=True)
    security_type = models.CharField(max_length=128, null=True, blank=True)
    quantity = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    market_price = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    market_price_currency = models.CharField(max_length=8, null=True, blank=True)
    book_value_cad = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    market_value = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    market_value_currency = models.CharField(max_length=8, null=True, blank=True)
    unrealized_return = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    source_filename = models.CharField(max_length=255, null=True, blank=True)
    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "as_of", "account_number", "symbol"],
                name="holdings_unique_snapshot",
            )
        ]
        indexes = [models.Index(fields=["as_of", "account_number", "symbol"], name="idx_holdings_as_of_account")]


class NetWorthHistory(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="net_worth_history")
    entry_date = models.DateField()
    amount = models.DecimalField(max_digits=20, decimal_places=6)
    note = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "entry_date"], name="networth_user_date_unique")]
        indexes = [models.Index(fields=["entry_date"], name="idx_net_worth_entry_date")]


class CreditCardTransaction(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="credit_card_transactions")
    provider = models.CharField(max_length=64)
    transaction_date = models.DateField()
    posted_date = models.DateField(null=True, blank=True)
    reference_number = models.CharField(max_length=128, default="")
    activity_type = models.CharField(max_length=128, null=True, blank=True)
    status = models.CharField(max_length=64, null=True, blank=True)
    card_last4 = models.CharField(max_length=8, null=True, blank=True)
    merchant_category = models.CharField(max_length=128, null=True, blank=True)
    merchant_name = models.CharField(max_length=255, null=True, blank=True)
    merchant_city = models.CharField(max_length=128, null=True, blank=True)
    merchant_region = models.CharField(max_length=128, null=True, blank=True)
    merchant_country = models.CharField(max_length=128, null=True, blank=True)
    merchant_postal = models.CharField(max_length=32, null=True, blank=True)
    amount = models.DecimalField(max_digits=20, decimal_places=6)
    rewards = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    is_hidden = models.BooleanField(default=False)
    cardholder_name = models.CharField(max_length=255, null=True, blank=True)
    source_filename = models.CharField(max_length=255, null=True, blank=True)
    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["provider", "transaction_date", "id"], name="idx_cc_provider_date"),
            models.Index(fields=["provider", "merchant_category"], name="idx_cc_provider_category"),
        ]


class AppSetting(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="app_settings")
    key = models.CharField(max_length=128)
    value = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "key"], name="app_settings_user_key_pk")]


class TfsaAccount(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tfsa_accounts")
    account_name = models.CharField(max_length=255)
    account_number = models.CharField(max_length=64, null=True, blank=True)
    opening_balance = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    created_at = models.DateTimeField(auto_now_add=True)


class TfsaAnnualLimit(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tfsa_annual_limits")
    year = models.IntegerField()
    annual_limit = models.DecimalField(max_digits=20, decimal_places=6)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "year"], name="tfsa_user_year_unique")]


class TfsaContribution(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tfsa_contributions")
    tfsa_account = models.ForeignKey(TfsaAccount, on_delete=models.CASCADE, related_name="contributions")
    contribution_date = models.DateField()
    amount = models.DecimalField(max_digits=20, decimal_places=6)
    contribution_type = models.CharField(max_length=64)
    memo = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["contribution_date", "id"], name="idx_tfsa_contributions_date")]


class RrspAccount(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="rrsp_accounts")
    account_name = models.CharField(max_length=255)
    account_number = models.CharField(max_length=64, null=True, blank=True)
    opening_balance = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    created_at = models.DateTimeField(auto_now_add=True)


class RrspAnnualLimit(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="rrsp_annual_limits")
    year = models.IntegerField()
    annual_limit = models.DecimalField(max_digits=20, decimal_places=6)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "year"], name="rrsp_user_year_unique")]


class RrspContribution(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="rrsp_contributions")
    rrsp_account = models.ForeignKey(RrspAccount, on_delete=models.CASCADE, related_name="contributions")
    contribution_date = models.DateField()
    amount = models.DecimalField(max_digits=20, decimal_places=6)
    contribution_type = models.CharField(max_length=64)
    is_unused = models.BooleanField(default=False)
    deducted_tax_year = models.IntegerField(null=True, blank=True)
    memo = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["contribution_date", "id"], name="idx_rrsp_contributions_date")]


class FhsaAccount(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="fhsa_accounts")
    account_name = models.CharField(max_length=255)
    account_number = models.CharField(max_length=64, null=True, blank=True)
    opening_balance = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    created_at = models.DateTimeField(auto_now_add=True)


class FhsaContribution(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="fhsa_contributions")
    fhsa_account = models.ForeignKey(FhsaAccount, on_delete=models.CASCADE, related_name="contributions")
    contribution_date = models.DateField()
    amount = models.DecimalField(max_digits=20, decimal_places=6)
    contribution_type = models.CharField(max_length=64)
    is_qualifying_withdrawal = models.BooleanField(default=False)
    memo = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["contribution_date", "id"], name="idx_fhsa_contributions_date")]
