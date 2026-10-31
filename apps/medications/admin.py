from django.contrib import admin

from .models import DoseEvent, DoseOccurrence, Medication, MedicationSchedule


@admin.register(Medication)
class MedicationAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "patient",
        "strength",
        "start_date",
        "end_date",
        "is_active",
    )
    list_filter = ("is_active", "dosage_form")
    search_fields = ("name", "patient__email", "instructions")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(MedicationSchedule)
class MedicationScheduleAdmin(admin.ModelAdmin):
    list_display = (
        "medication",
        "schedule_type",
        "timezone",
        "is_active",
        "created_at",
    )
    list_filter = ("schedule_type", "is_active", "timezone")
    search_fields = ("medication__name", "medication__patient__email")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(DoseOccurrence)
class DoseOccurrenceAdmin(admin.ModelAdmin):
    list_display = (
        "medication",
        "patient",
        "scheduled_at",
        "status",
        "alert_status",
    )
    list_filter = ("status", "alert_status", "scheduled_date")
    search_fields = ("medication__name", "patient__email")
    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
    )
    date_hierarchy = "scheduled_date"


@admin.register(DoseEvent)
class DoseEventAdmin(admin.ModelAdmin):
    list_display = (
        "occurrence",
        "event_type",
        "actor",
        "source",
        "server_received_at",
    )
    list_filter = ("event_type", "source")
    search_fields = ("occurrence__medication__name", "client_event_id")
    readonly_fields = (
        "id",
        "occurrence",
        "event_type",
        "actor",
        "client_event_id",
        "client_recorded_at",
        "server_received_at",
        "source",
        "payload",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
