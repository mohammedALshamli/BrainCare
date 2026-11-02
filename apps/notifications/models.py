import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from .crypto import decrypt_token, encrypt_token, token_fingerprint


class Device(models.Model):
    """A user's push-notification device.

    FCM tokens are secrets. They are encrypted at rest and only a short preview
    is exposed by the API. The fingerprint provides uniqueness without storing
    the plaintext token in an index.
    """

    class Platform(models.TextChoices):
        ANDROID = "android", "Android"
        IOS = "ios", "iOS"
        WEB = "web", "Web"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="devices",
    )
    device_identifier = models.CharField(max_length=128, blank=True)
    platform = models.CharField(max_length=20, choices=Platform.choices)
    fcm_token_encrypted = models.TextField()
    token_fingerprint = models.CharField(max_length=64, unique=True)
    token_preview = models.CharField(max_length=8, blank=True)
    device_name = models.CharField(max_length=120, blank=True)
    app_version = models.CharField(max_length=50, blank=True)
    os_version = models.CharField(max_length=50, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_seen_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "device_identifier"],
                condition=~models.Q(device_identifier=""),
                name="unique_user_device_identifier",
            ),
        ]
        indexes = [
            models.Index(
                fields=["user", "is_active"],
                name="device_user_active_idx",
            ),
            models.Index(
                fields=["is_active", "last_seen_at"],
                name="device_active_seen_idx",
            ),
        ]

    def __str__(self):
        return f"{self.platform} device for {self.user_id}"

    def set_fcm_token(self, raw_token: str) -> None:
        self.fcm_token_encrypted = encrypt_token(raw_token)
        self.token_fingerprint = token_fingerprint(raw_token)
        self.token_preview = raw_token[-6:]

    def get_fcm_token(self) -> str:
        return decrypt_token(self.fcm_token_encrypted)


class NotificationOutbox(models.Model):
    """Transactional outbox for notification delivery.

    ``ACCEPTED`` means the push provider accepted the message for sending. It
    is deliberately not called delivered: FCM acceptance is not a delivery
    receipt.
    """

    class NotificationType(models.TextChoices):
        DOSE_OVERDUE = "dose_overdue", "Dose overdue"
        DOSE_REMINDER = "dose_reminder", "Dose reminder"
        WATER_REMINDER = "water_reminder", "Water reminder"
        SYSTEM = "system", "System"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        ACCEPTED = "accepted", "Accepted by provider"
        FAILED = "failed", "Failed"
        DEAD_LETTER = "dead_letter", "Dead letter"
        SUPPRESSED = "suppressed", "Suppressed (no longer relevant)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idempotency_key = models.CharField(max_length=255, unique=True)
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_outbox",
    )
    patient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="patient_notification_outbox",
    )
    notification_type = models.CharField(
        max_length=32, choices=NotificationType.choices
    )
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=5)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    processing_started_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    suppressed_at = models.DateTimeField(null=True, blank=True)
    suppression_reason = models.CharField(max_length=64, blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(
                fields=["status", "next_attempt_at"],
                name="outbox_status_next_idx",
            ),
            models.Index(
                fields=["recipient", "status"],
                name="outbox_recipient_status_idx",
            ),
            models.Index(
                fields=["notification_type", "created_at"],
                name="outbox_type_created_idx",
            ),
        ]

    def __str__(self):
        return f"{self.notification_type} -> {self.recipient_id}"
