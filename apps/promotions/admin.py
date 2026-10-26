from django.contrib import admin
from .models import Promotion, PromotionHide
@admin.register(Promotion)
class PromotionAdmin(admin.ModelAdmin):
    list_display = ["headline", "sponsor_name", "sponsor_kind", "status", "views", "clicks", "submitted_at"]
    list_filter = ["status", "sponsor_kind"]
    search_fields = ["headline", "sponsor_name", "created_by__email"]
    readonly_fields = ["views", "clicks", "submitted_at", "reviewed_at", "reviewed_by"]
@admin.register(PromotionHide)
class PromotionHideAdmin(admin.ModelAdmin):
    list_display = ["promotion", "user", "reason", "created_at"]
    list_filter = ["reason"]
