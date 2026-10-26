from django.contrib import admin
from .models import StepDismissal, StepEvent
@admin.register(StepEvent)
class StepEventAdmin(admin.ModelAdmin):
    list_display = ["day", "user", "step", "action", "count"]
    list_filter = ["step", "action", "day"]
@admin.register(StepDismissal)
class StepDismissalAdmin(admin.ModelAdmin):
    list_display = ["user", "step", "reason", "until"]
    list_filter = ["step", "reason"]
