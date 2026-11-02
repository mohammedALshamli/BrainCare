from django.contrib import admin

from .models import SyncChange


@admin.register(SyncChange)
class SyncChangeAdmin(admin.ModelAdmin):
    list_display = (
        "sequence",
        "entity_type",
        "object_id",
        "operation",
        "patient",
        "changed_at",
    )
    list_filter = ("entity_type", "operation")
    search_fields = ("object_id", "patient__email")
    readonly_fields = (
        "sequence",
        "patient",
        "entity_type",
        "object_id",
        "operation",
        "data",
        "actor",
        "changed_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
