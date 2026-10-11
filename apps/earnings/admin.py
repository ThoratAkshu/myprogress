from django.contrib import admin
from .models import CoinTransaction, CreatorAccount, EarningSettings, FinanceAuditLog, PayoutRequest, TreasuryEntry
# Day-to-day money work happens in the finance console at /finance/; these are read-mostly views for support.
@admin.register(EarningSettings)
class EarningSettingsAdmin(admin.ModelAdmin):
    list_display = ["program_enabled", "follower_goal", "follower_bonus", "coins_per_article", "coins_per_video", "coins_per_conversion", "rupees_per_conversion", "updated_at"]
@admin.register(CreatorAccount)
class CreatorAccountAdmin(admin.ModelAdmin):
    list_display = ["user", "eligible_since", "follower_bonus_paid_at", "suspended", "upi_id"]
    list_filter = ["suspended"]
    search_fields = ["user__email", "user__profile__handle", "upi_id"]
@admin.register(CoinTransaction)
class CoinTransactionAdmin(admin.ModelAdmin):
    list_display = ["user", "amount", "kind", "description", "created_at"]
    list_filter = ["kind"]
    search_fields = ["user__email", "description"]
    raw_id_fields = ["user", "post"]
    def has_change_permission(self, request, obj=None):
        return False
@admin.register(PayoutRequest)
class PayoutRequestAdmin(admin.ModelAdmin):
    list_display = ["user", "amount", "upi_id", "status", "requested_at", "processed_at", "reference"]
    list_filter = ["status"]
    search_fields = ["user__email", "upi_id", "reference"]
    readonly_fields = [field.name for field in PayoutRequest._meta.fields]
@admin.register(TreasuryEntry)
class TreasuryEntryAdmin(admin.ModelAdmin):
    list_display = ["kind", "amount", "reference", "created_by", "created_at"]
    list_filter = ["kind"]
    readonly_fields = [field.name for field in TreasuryEntry._meta.fields]
@admin.register(FinanceAuditLog)
class FinanceAuditLogAdmin(admin.ModelAdmin):
    list_display = ["created_at", "actor", "action", "details"]
    list_filter = ["action"]
    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False
    def has_delete_permission(self, request, obj=None):
        return False
