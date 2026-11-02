import uuid
from datetime import time, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Medication(models.Model):
    """A medication owned by a patient."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="medications",
    )
    name = models.CharField(max_length=200)
    strength = models.CharField(max_length=100, blank=True)
    dosage_form = models.CharField(max_length=100, blank=True)
    instructions = models.TextField(blank=True)
    dose_amount = models.DecimalField(
        max_digits=10, decimal_places=3, null=True, blank=True
    )
    dose_unit = models.CharField(max_length=50, blank=True)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_medications",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__isnull=True)
                | models.Q(end_date__gte=models.F("start_date")),
                name="medication_end_date_not_before_start",
            ),
        ]
        indexes = [
            models.Index(
                fields=["patient", "is_active"],
                name="med_patient_active_idx",
            ),
            models.Index(
                fields=["patient", "name"],
                name="med_patient_name_idx",
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError(
                {"end_date": "End date cannot be before the start date."}
            )
        if self.dose_amount is not None and not self.dose_unit:
            raise ValidationError(
                {"dose_unit": "A dose unit is required when a dose amount is set."}
            )
        if self.dose_amount is None and self.dose_unit:
            raise ValidationError(
                {"dose_amount": "A dose amount is required when a dose unit is set."}
            )


class MedicationSchedule(models.Model):
    class ScheduleType(models.TextChoices):
        FIXED_TIMES = "fixed_times", "Fixed daily times"
        WEEKDAYS = "weekdays", "Selected weekdays and times"
        INTERVAL_HOURS = "interval_hours", "Every N hours"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    medication = models.ForeignKey(
        Medication,
        on_delete=models.PROTECT,
        related_name="schedules",
    )
    schedule_type = models.CharField(max_length=20, choices=ScheduleType.choices)
    times = models.JSONField(default=list, blank=True)
    weekdays = models.JSONField(default=list, blank=True)
    interval_hours = models.PositiveSmallIntegerField(null=True, blank=True)
    anchor_time = models.TimeField(default=time(0, 0))
    timezone = models.CharField(max_length=64, default="UTC")
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_schedules",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    schedule_type__in=[
                        "fixed_times",
                        "weekdays",
                        "interval_hours",
                    ]
                ),
                name="schedule_type_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(interval_hours__isnull=True)
                | models.Q(interval_hours__gte=1, interval_hours__lte=24),
                name="schedule_interval_between_1_and_24",
            ),
            models.CheckConstraint(
                condition=models.Q(schedule_type="interval_hours")
                | models.Q(interval_hours__isnull=True),
                name="schedule_non_interval_has_no_interval",
            ),
            models.CheckConstraint(
                condition=models.Q(schedule_type="interval_hours")
                & models.Q(interval_hours__isnull=False)
                | ~models.Q(schedule_type="interval_hours"),
                name="interval_schedule_requires_interval",
            ),
        ]
        indexes = [
            models.Index(
                fields=["medication", "is_active"],
                name="schedule_med_active_idx",
            ),
            models.Index(fields=["is_active"], name="schedule_active_idx"),
        ]

    def __str__(self):
        return f"{self.medication_id} ({self.schedule_type})"

    @property
    def patient_id(self):
        return self.medication.patient_id


class DoseOccurrence(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        TAKEN = "taken", "Taken"
        SKIPPED = "skipped", "Skipped"
        OVERDUE_UNCONFIRMED = "overdue_unconfirmed", "Overdue / unconfirmed"
        CANCELLED = "cancelled", "Cancelled (schedule changed)"

    class AlertStatus(models.TextChoices):
        NONE = "none", "None"
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        ACKNOWLEDGED = "acknowledged", "Acknowledged"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    medication = models.ForeignKey(
        Medication,
        on_delete=models.PROTECT,
        related_name="dose_occurrences",
    )
    schedule = models.ForeignKey(
        MedicationSchedule,
        on_delete=models.PROTECT,
        related_name="dose_occurrences",
    )
    patient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="dose_occurrences",
    )
    scheduled_at = models.DateTimeField()
    scheduled_date = models.DateField()
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.PENDING,
    )
    alert_status = models.CharField(
        max_length=20,
        choices=AlertStatus.choices,
        default=AlertStatus.NONE,
    )
    taken_at = models.DateTimeField(null=True, blank=True)
    skipped_at = models.DateTimeField(null=True, blank=True)
    snoozed_until = models.DateTimeField(null=True, blank=True)
    snooze_count = models.PositiveIntegerField(default=0)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=64, blank=True)
    superseded_by = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="supersedes",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["scheduled_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["schedule", "scheduled_at"],
                name="unique_schedule_occurrence",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=[
                        "pending",
                        "taken",
                        "skipped",
                        "overdue_unconfirmed",
                        "cancelled",
                    ]
                ),
                name="dose_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    alert_status__in=[
                        "none",
                        "pending",
                        "sent",
                        "acknowledged",
                        "failed",
                    ]
                ),
                name="dose_alert_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(status="taken", taken_at__isnull=False)
                | ~models.Q(status="taken"),
                name="taken_occurrence_requires_taken_at",
            ),
            models.CheckConstraint(
                condition=models.Q(status="skipped", skipped_at__isnull=False)
                | ~models.Q(status="skipped"),
                name="skipped_occurrence_requires_skipped_at",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status="cancelled", cancelled_at__isnull=False
                )
                | ~models.Q(status="cancelled"),
                name="cancelled_occurrence_requires_cancelled_at",
            ),
        ]
        indexes = [
            models.Index(
                fields=["patient", "scheduled_at"],
                name="dose_patient_sched_idx",
            ),
            models.Index(
                fields=["patient", "status"],
                name="dose_patient_status_idx",
            ),
            models.Index(
                fields=["medication", "scheduled_at"],
                name="dose_med_sched_idx",
            ),
            models.Index(
                fields=["status", "scheduled_at"],
                name="dose_status_sched_idx",
            ),
        ]

    def __str__(self):
        return f"{self.medication_id} @ {self.scheduled_at.isoformat()}"

    def is_late(self, grace_minutes=None, now=None) -> bool:
        now = now or timezone.now()
        grace = (
            settings.DOSE_OVERDUE_GRACE_MINUTES
            if grace_minutes is None
            else grace_minutes
        )
        return self.scheduled_at + timedelta(minutes=grace) <= now


class DoseEvent(models.Model):
    """Append-only audit record for a dose occurrence."""

    class EventType(models.TextChoices):
        TAKEN = "taken", "Taken"
        SKIPPED = "skipped", "Skipped"
        SNOOZED = "snoozed", "Snoozed"
        CONFIRMED_LATE = "confirmed_late", "Confirmed late"
        OVERDUE = "overdue", "Marked overdue"
        REMINDER_SENT = "reminder_sent", "Reminder sent"
        ESCALATION_SENT = "escalation_sent", "Escalation sent"
        ESCALATION_ACKNOWLEDGED = "escalation_acknowledged", "Escalation acknowledged"

    class Source(models.TextChoices):
        PATIENT_APP = "patient_app", "Patient app"
        CAREGIVER_APP = "caregiver_app", "Caregiver app"
        SYSTEM = "system", "System"
        API = "api", "API"
        ADMIN = "admin", "Admin"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    occurrence = models.ForeignKey(
        DoseOccurrence,
        on_delete=models.PROTECT,
        related_name="events",
    )
    event_type = models.CharField(max_length=32, choices=EventType.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dose_events",
    )
    client_event_id = models.CharField(
        max_length=128, unique=True, null=True, blank=True
    )
    client_recorded_at = models.DateTimeField(null=True, blank=True)
    server_received_at = models.DateTimeField(auto_now_add=True)
    source = models.CharField(
        max_length=20, choices=Source.choices, default=Source.API
    )
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["server_received_at", "id"]
        indexes = [
            models.Index(
                fields=["occurrence", "server_received_at"],
                name="event_occurrence_time_idx",
            ),
            models.Index(fields=["event_type"], name="event_type_idx"),
        ]

    def __str__(self):
        return f"{self.event_type} for {self.occurrence_id}"
