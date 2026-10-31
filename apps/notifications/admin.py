from django.contrib import admin

from .models import Device, NotificationOutbox


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "platform",
        "device_name",
        "is_active",
        "last_seen_at",
    )
    list_filter = ("platform", "is_active")
    search_fields = ("user__email", "device_identifier", "device_name")
    readonly_fields = (
        "id",
        "fcm_token_encrypted",
        "token_fingerprint",
        "token_preview",
        "created_at",
        "updated_at",
    )


@admin.register(NotificationOutbox)
class NotificationOutboxAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "notification_type",
        "recipient",
        "patient",
        "status",
        "attempts",
        "next_attempt_at",
        "created_at",
    )
    list_filter = ("notification_type", "status")
    search_fields = ("idempotency_key", "recipient__email", "patient__email")
    readonly_fields = (
        "id",
        "idempotency_key",
        "recipient",
        "patient",
        "notification_type",
        "payload",
        "status",
        "attempts",
        "max_attempts",
        "next_attempt_at",
        "processing_started_at",
        "accepted_at",
        "last_error",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
