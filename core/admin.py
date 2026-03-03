import csv
from decimal import Decimal
from django.contrib import admin
from django.db.models import Sum, Q
from django.http import HttpResponse
from django.urls import reverse
from django.utils.html import format_html
from django.utils.timezone import now

from .models import (
    Transaction,
    ImportBatch,
    ImportBatchRow,
    HoldingSnapshot,
    NetWorthHistory,
    CreditCardTransaction,
    AppSetting,
    TfsaAccount,
    TfsaAnnualLimit,
    TfsaContribution,
    RrspAccount,
    RrspAnnualLimit,
    RrspContribution,
    FhsaAccount,
    FhsaContribution,
)


# ============================================================================
# INLINE ADMINS FOR RELATED DATA
# ============================================================================


class ImportBatchRowInline(admin.TabularInline):
    """Edit ImportBatchRows directly within ImportBatch form."""
    model = ImportBatchRow
    extra = 1
    fields = ("row_order", "security", "trade_date", "transaction_type", "shares", "amount", "commission")
    readonly_fields = ("row_order",)


class TfsaContributionInline(admin.TabularInline):
    """Edit TfsaContributions directly within TfsaAccount form."""
    model = TfsaContribution
    extra = 1
    fields = ("contribution_date", "amount", "contribution_type", "memo")


class RrspContributionInline(admin.TabularInline):
    """Edit RrspContributions directly within RrspAccount form."""
    model = RrspContribution
    extra = 1
    fields = ("contribution_date", "amount", "contribution_type", "is_unused", "deducted_tax_year", "memo")


class FhsaContributionInline(admin.TabularInline):
    """Edit FhsaContributions directly within FhsaAccount form."""
    model = FhsaContribution
    extra = 1
    fields = ("contribution_date", "amount", "contribution_type", "is_qualifying_withdrawal", "memo")


# ============================================================================
# HELPER FUNCTIONS FOR FORMATTING
# ============================================================================


def format_currency(value):
    """Format Decimal as currency (CAD)."""
    if value is None or value == "":
        return "—"
    try:
        decimal_value = Decimal(str(value))
        return f"${decimal_value:,.2f}"
    except (ValueError, TypeError):
        return str(value)


def format_currency_display(decimal_field_name):
    """Factory function to create list_display methods that format currency."""
    def display_method(obj):
        value = getattr(obj, decimal_field_name, None)
        return format_currency(value)
    display_method.short_description = decimal_field_name.replace("_", " ").title()
    display_method.admin_order_field = decimal_field_name
    return display_method


# ============================================================================
# TRANSACTION ADMIN
# ============================================================================


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "security",
        "trade_date",
        "transaction_type",
        "shares_display",
        "amount_display",
        "commission_display",
    )
    list_filter = ("transaction_type", "trade_date", "security", "source")
    search_fields = ("security", "user__username", "memo")
    ordering = ("-trade_date", "-id")

    fieldsets = (
        ("Security Info", {"fields": ("user", "security", "trade_date", "transaction_type")}),
        ("Trade Details", {"fields": ("shares", "amount_per_share", "amount", "commission")}),
        ("Metadata", {"fields": ("memo", "source", "created_at")}),
    )
    readonly_fields = ("created_at",)

    def shares_display(self, obj):
        return f"{obj.shares:.8g}"
    shares_display.short_description = "Shares"
    shares_display.admin_order_field = "shares"

    def amount_display(self, obj):
        return format_currency(obj.amount)
    amount_display.short_description = "Amount"
    amount_display.admin_order_field = "amount"

    def commission_display(self, obj):
        return format_currency(obj.commission)
    commission_display.short_description = "Commission"
    commission_display.admin_order_field = "commission"

    @admin.action(description="Export selected transactions to CSV")
    def export_to_csv(self, request, queryset):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="transactions.csv"'
        writer = csv.writer(response)
        writer.writerow([
            "ID", "User", "Security", "Trade Date", "Type", "Shares", "Amount Per Share",
            "Amount", "Commission", "Memo", "Source", "Created"
        ])
        for obj in queryset:
            writer.writerow([
                obj.id, obj.user.username, obj.security, obj.trade_date, obj.transaction_type,
                obj.shares, obj.amount_per_share, obj.amount, obj.commission, obj.memo,
                obj.source, obj.created_at
            ])
        return response

    actions = ["export_to_csv"]


# ============================================================================
# IMPORT BATCH ADMIN
# ============================================================================


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "source_type", "source_filename", "status_badge", "created_at", "row_count")
    list_filter = ("status", "source_type", "created_at")
    search_fields = ("user__username", "source_filename")
    ordering = ("-created_at",)
    inlines = [ImportBatchRowInline]

    fieldsets = (
        ("Batch Info", {"fields": ("user", "source_type", "source_filename", "status")}),
        ("Timestamps", {"fields": ("created_at", "committed_at")}),
    )
    readonly_fields = ("created_at", "committed_at")

    def status_badge(self, obj):
        colors = {"staged": "orange", "committed": "green", "failed": "red"}
        color = colors.get(obj.status, "gray")
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px;">{}</span>',
            color,
            obj.status.upper(),
        )
    status_badge.short_description = "Status"
    status_badge.admin_order_field = "status"

    def row_count(self, obj):
        return obj.rows.count()
    row_count.short_description = "Row Count"

    @admin.action(description="Mark selected batches as committed")
    def mark_committed(self, request, queryset):
        updated = queryset.update(status="committed", committed_at=now())
        self.message_user(request, f"{updated} batch(es) marked as committed.")

    @admin.action(description="Mark selected batches as staged")
    def mark_staged(self, request, queryset):
        updated = queryset.update(status="staged", committed_at=None)
        self.message_user(request, f"{updated} batch(es) marked as staged.")

    actions = ["mark_committed", "mark_staged"]


# ============================================================================
# HOLDING SNAPSHOT ADMIN
# ============================================================================


@admin.register(HoldingSnapshot)
class HoldingSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "as_of",
        "account_name",
        "symbol",
        "quantity_display",
        "market_value_display",
        "unrealized_return_display",
    )
    list_filter = ("as_of", "symbol", "account_name", "security_type")
    search_fields = ("user__username", "symbol", "account_name", "security_name")
    ordering = ("-as_of", "account_name", "symbol")

    fieldsets = (
        ("User & Date", {"fields": ("user", "as_of")}),
        ("Account Info", {
            "fields": ("account_name", "account_type", "account_classification", "account_number")
        }),
        ("Security", {
            "fields": ("symbol", "exchange", "mic", "security_name", "security_type")
        }),
        ("Quantities & Pricing", {
            "fields": ("quantity", "market_price", "market_price_currency")
        }),
        ("Values", {
            "fields": ("book_value_cad", "market_value", "market_value_currency", "unrealized_return")
        }),
        ("Import Info", {
            "fields": ("source_filename", "imported_at")
        }),
    )
    readonly_fields = ("imported_at",)

    def quantity_display(self, obj):
        return f"{obj.quantity:.8g}"
    quantity_display.short_description = "Quantity"
    quantity_display.admin_order_field = "quantity"

    def market_value_display(self, obj):
        return format_currency(obj.market_value)
    market_value_display.short_description = "Market Value"
    market_value_display.admin_order_field = "market_value"

    def unrealized_return_display(self, obj):
        return format_currency(obj.unrealized_return)
    unrealized_return_display.short_description = "Unrealized Return"
    unrealized_return_display.admin_order_field = "unrealized_return"


# ============================================================================
# NET WORTH HISTORY ADMIN
# ============================================================================


@admin.register(NetWorthHistory)
class NetWorthHistoryAdmin(admin.ModelAdmin):
    list_display = ("user", "entry_date", "amount_display", "created_at")
    list_filter = ("entry_date", "created_at")
    search_fields = ("user__username", "note")
    ordering = ("-entry_date",)

    fieldsets = (
        ("Entry", {"fields": ("user", "entry_date", "amount", "note")}),
        ("Metadata", {"fields": ("created_at", "updated_at")}),
    )
    readonly_fields = ("created_at", "updated_at")

    def amount_display(self, obj):
        return format_currency(obj.amount)
    amount_display.short_description = "Amount"
    amount_display.admin_order_field = "amount"

    @admin.action(description="Delete selected net worth entries")
    def delete_entries(self, request, queryset):
        count = queryset.count()
        queryset.delete()
        self.message_user(request, f"Deleted {count} net worth entr(ies).")

    actions = ["delete_entries"]


# ============================================================================
# CREDIT CARD TRANSACTION ADMIN
# ============================================================================


@admin.register(CreditCardTransaction)
class CreditCardTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "transaction_date",
        "card_label",
        "merchant_name",
        "merchant_category",
        "amount_display",
        "rewards_display",
        "visibility_badge",
    )
    list_filter = ("provider", "transaction_date", "merchant_category", "is_hidden", "card_label")
    search_fields = ("user__username", "merchant_name", "merchant_city", "cardholder_name")
    ordering = ("-transaction_date",)

    fieldsets = (
        ("User & Card", {"fields": ("user", "card_last4", "card_label", "cardholder_name", "provider")}),
        ("Transaction", {
            "fields": ("transaction_date", "posted_date", "reference_number", "activity_type", "status")
        }),
        ("Merchant", {
            "fields": (
                "merchant_name", "merchant_category", "merchant_city", "merchant_region",
                "merchant_country", "merchant_postal"
            )
        }),
        ("Amount", {
            "fields": ("amount", "rewards")
        }),
        ("Visibility", {
            "fields": ("is_hidden",)
        }),
        ("Import Info", {
            "fields": ("source_filename", "imported_at")
        }),
    )
    readonly_fields = ("imported_at",)

    def amount_display(self, obj):
        return format_currency(obj.amount)
    amount_display.short_description = "Amount"
    amount_display.admin_order_field = "amount"

    def rewards_display(self, obj):
        return format_currency(obj.rewards) if obj.rewards and obj.rewards > 0 else "—"
    rewards_display.short_description = "Rewards"
    rewards_display.admin_order_field = "rewards"

    def visibility_badge(self, obj):
        if obj.is_hidden:
            return format_html(
                '<span style="background-color: red; color: white; padding: 3px 8px; border-radius: 3px;">Hidden</span>'
            )
        return format_html(
            '<span style="background-color: green; color: white; padding: 3px 8px; border-radius: 3px;">Visible</span>'
        )
    visibility_badge.short_description = "Visibility"

    @admin.action(description="Hide selected transactions")
    def hide_transactions(self, request, queryset):
        updated = queryset.update(is_hidden=True)
        self.message_user(request, f"{updated} transaction(s) hidden.")

    @admin.action(description="Show selected transactions")
    def show_transactions(self, request, queryset):
        updated = queryset.update(is_hidden=False)
        self.message_user(request, f"{updated} transaction(s) shown.")

    @admin.action(description="Export selected credit card transactions to CSV")
    def export_to_csv(self, request, queryset):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="credit_card_transactions.csv"'
        writer = csv.writer(response)
        writer.writerow([
            "User", "Transaction Date", "Posted Date", "Card Label", "Merchant", "Category",
            "Amount", "Rewards", "Status", "Hidden"
        ])
        for obj in queryset:
            writer.writerow([
                obj.user.username, obj.transaction_date, obj.posted_date, obj.card_label,
                obj.merchant_name, obj.merchant_category, obj.amount, obj.rewards,
                obj.status, obj.is_hidden
            ])
        return response

    actions = ["hide_transactions", "show_transactions", "export_to_csv"]


# ============================================================================
# APP SETTING ADMIN
# ============================================================================


@admin.register(AppSetting)
class AppSettingAdmin(admin.ModelAdmin):
    list_display = ("user", "key", "value_preview", "updated_at")
    list_filter = ("key", "updated_at")
    search_fields = ("user__username", "key", "value")
    ordering = ("-updated_at",)

    fieldsets = (
        ("Setting", {"fields": ("user", "key", "value")}),
        ("Metadata", {"fields": ("updated_at",)}),
    )
    readonly_fields = ("updated_at",)

    def value_preview(self, obj):
        preview = obj.value[:50] + "..." if len(obj.value) > 50 else obj.value
        return preview
    value_preview.short_description = "Value"
    value_preview.admin_order_field = "value"


# ============================================================================
# TFSA ADMIN
# ============================================================================


@admin.register(TfsaAccount)
class TfsaAccountAdmin(admin.ModelAdmin):
    list_display = ("user", "account_name", "account_number", "opening_balance_display", "created_at")
    list_filter = ("created_at",)
    search_fields = ("user__username", "account_name", "account_number")
    ordering = ("-created_at",)
    inlines = [TfsaContributionInline]

    fieldsets = (
        ("Account Info", {"fields": ("user", "account_name", "account_number", "opening_balance")}),
        ("Metadata", {"fields": ("created_at",)}),
    )
    readonly_fields = ("created_at",)

    def opening_balance_display(self, obj):
        return format_currency(obj.opening_balance)
    opening_balance_display.short_description = "Opening Balance"
    opening_balance_display.admin_order_field = "opening_balance"


@admin.register(TfsaAnnualLimit)
class TfsaAnnualLimitAdmin(admin.ModelAdmin):
    list_display = ("user", "year", "annual_limit_display", "updated_at")
    list_filter = ("year",)
    search_fields = ("user__username",)
    ordering = ("-year",)

    fieldsets = (
        ("Limit Info", {"fields": ("user", "year", "annual_limit")}),
        ("Metadata", {"fields": ("created_at", "updated_at")}),
    )
    readonly_fields = ("created_at", "updated_at")

    def annual_limit_display(self, obj):
        return format_currency(obj.annual_limit)
    annual_limit_display.short_description = "Annual Limit"
    annual_limit_display.admin_order_field = "annual_limit"


@admin.register(TfsaContribution)
class TfsaContributionAdmin(admin.ModelAdmin):
    list_display = ("user", "tfsa_account", "contribution_date", "contribution_type", "amount_display", "created_at")
    list_filter = ("contribution_type", "contribution_date")
    search_fields = ("user__username", "tfsa_account__account_name", "memo")
    ordering = ("-contribution_date",)

    fieldsets = (
        ("Contribution Info", {
            "fields": ("user", "tfsa_account", "contribution_date", "contribution_type", "amount", "memo")
        }),
        ("Metadata", {"fields": ("created_at",)}),
    )
    readonly_fields = ("created_at",)

    def amount_display(self, obj):
        return format_currency(obj.amount)
    amount_display.short_description = "Amount"
    amount_display.admin_order_field = "amount"


# ============================================================================
# RRSP ADMIN
# ============================================================================


@admin.register(RrspAccount)
class RrspAccountAdmin(admin.ModelAdmin):
    list_display = ("user", "account_name", "account_number", "opening_balance_display", "created_at")
    list_filter = ("created_at",)
    search_fields = ("user__username", "account_name", "account_number")
    ordering = ("-created_at",)
    inlines = [RrspContributionInline]

    fieldsets = (
        ("Account Info", {"fields": ("user", "account_name", "account_number", "opening_balance")}),
        ("Metadata", {"fields": ("created_at",)}),
    )
    readonly_fields = ("created_at",)

    def opening_balance_display(self, obj):
        return format_currency(obj.opening_balance)
    opening_balance_display.short_description = "Opening Balance"
    opening_balance_display.admin_order_field = "opening_balance"


@admin.register(RrspAnnualLimit)
class RrspAnnualLimitAdmin(admin.ModelAdmin):
    list_display = ("user", "year", "annual_limit_display", "updated_at")
    list_filter = ("year",)
    search_fields = ("user__username",)
    ordering = ("-year",)

    fieldsets = (
        ("Limit Info", {"fields": ("user", "year", "annual_limit")}),
        ("Metadata", {"fields": ("created_at", "updated_at")}),
    )
    readonly_fields = ("created_at", "updated_at")

    def annual_limit_display(self, obj):
        return format_currency(obj.annual_limit)
    annual_limit_display.short_description = "Annual Limit"
    annual_limit_display.admin_order_field = "annual_limit"


@admin.register(RrspContribution)
class RrspContributionAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "rrsp_account",
        "contribution_date",
        "contribution_type",
        "amount_display",
        "unused_badge",
        "created_at",
    )
    list_filter = ("contribution_type", "contribution_date", "is_unused", "deducted_tax_year")
    search_fields = ("user__username", "rrsp_account__account_name", "memo")
    ordering = ("-contribution_date",)

    fieldsets = (
        ("Contribution Info", {
            "fields": (
                "user", "rrsp_account", "contribution_date", "contribution_type",
                "amount", "is_unused", "deducted_tax_year", "memo"
            )
        }),
        ("Metadata", {"fields": ("created_at",)}),
    )
    readonly_fields = ("created_at",)

    def amount_display(self, obj):
        return format_currency(obj.amount)
    amount_display.short_description = "Amount"
    amount_display.admin_order_field = "amount"

    def unused_badge(self, obj):
        if obj.is_unused:
            return format_html(
                '<span style="background-color: blue; color: white; padding: 3px 8px; border-radius: 3px;">Unused</span>'
            )
        return "—"
    unused_badge.short_description = "Status"


# ============================================================================
# FHSA ADMIN
# ============================================================================


@admin.register(FhsaAccount)
class FhsaAccountAdmin(admin.ModelAdmin):
    list_display = ("user", "account_name", "account_number", "opening_balance_display", "created_at")
    list_filter = ("created_at",)
    search_fields = ("user__username", "account_name", "account_number")
    ordering = ("-created_at",)
    inlines = [FhsaContributionInline]

    fieldsets = (
        ("Account Info", {"fields": ("user", "account_name", "account_number", "opening_balance")}),
        ("Metadata", {"fields": ("created_at",)}),
    )
    readonly_fields = ("created_at",)

    def opening_balance_display(self, obj):
        return format_currency(obj.opening_balance)
    opening_balance_display.short_description = "Opening Balance"
    opening_balance_display.admin_order_field = "opening_balance"


@admin.register(FhsaContribution)
class FhsaContributionAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "fhsa_account",
        "contribution_date",
        "contribution_type",
        "amount_display",
        "withdrawal_badge",
        "created_at",
    )
    list_filter = ("contribution_type", "contribution_date", "is_qualifying_withdrawal")
    search_fields = ("user__username", "fhsa_account__account_name", "memo")
    ordering = ("-contribution_date",)

    fieldsets = (
        ("Contribution Info", {
            "fields": (
                "user", "fhsa_account", "contribution_date", "contribution_type",
                "amount", "is_qualifying_withdrawal", "memo"
            )
        }),
        ("Metadata", {"fields": ("created_at",)}),
    )
    readonly_fields = ("created_at",)

    def amount_display(self, obj):
        return format_currency(obj.amount)
    amount_display.short_description = "Amount"
    amount_display.admin_order_field = "amount"

    def withdrawal_badge(self, obj):
        if obj.is_qualifying_withdrawal:
            return format_html(
                '<span style="background-color: purple; color: white; padding: 3px 8px; border-radius: 3px;">Withdrawal</span>'
            )
        return "—"
    withdrawal_badge.short_description = "Type"
