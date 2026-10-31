from django.contrib import admin

from .models import WaterIntakeLog, WaterReminderSettings


@admin.register(WaterReminderSettings)
class WaterReminderSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "patient",
        "enabled",
        "start_time",
        "end_time",
        "interval_minutes",
        "daily_goal_ml",
        "cup_size_ml",
        "timezone",
    )
    search_fields = ("patient__email",)


@admin.register(WaterIntakeLog)
class WaterIntakeLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "patient",
        "amount_ml",
        "consumed_at",
        "local_date",
        "source",
    )
    list_filter = ("source", "local_date")
    search_fields = ("patient__email", "notes")
    date_hierarchy = "local_date"
