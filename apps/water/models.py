import uuid
from datetime import time

from django.conf import settings
from django.db import models
from django.utils import timezone


class WaterReminderSettings(models.Model):
    """Patient-specific water reminder configuration."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="water_settings",
    )
    enabled = models.BooleanField(default=False)
    start_time = models.TimeField(default=time(8, 0))
    end_time = models.TimeField(default=time(20, 0))
    interval_minutes = models.PositiveSmallIntegerField(default=60)
    daily_goal_ml = models.PositiveIntegerField(default=2000)
    cup_size_ml = models.PositiveIntegerField(default=250)
    timezone = models.CharField(max_length=64, default="UTC")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["patient_id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(start_time__lt=models.F("end_time")),
                name="water_window_start_before_end",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    interval_minutes__gte=15,
                    interval_minutes__lte=720,
                ),
                name="water_interval_between_15_and_720",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    daily_goal_ml__gte=100,
                    daily_goal_ml__lte=20000,
                ),
                name="water_goal_between_100_and_20000",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    cup_size_ml__gte=50,
                    cup_size_ml__lte=2000,
                ),
                name="water_cup_between_50_and_2000",
            ),
        ]

    def __str__(self):
        return f"Water settings for {self.patient_id}"


class WaterIntakeLog(models.Model):
    class Source(models.TextChoices):
        MANUAL = "manual", "Manual"
        CUP = "cup", "Cup"
        QUICK_ADD = "quick_add", "Quick add"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="water_intake_logs",
    )
    amount_ml = models.PositiveIntegerField()
    consumed_at = models.DateTimeField(default=timezone.now)
    local_date = models.DateField()
    source = models.CharField(
        max_length=20, choices=Source.choices, default=Source.MANUAL
    )
    notes = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_water_intake_logs",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-consumed_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount_ml__gte=1, amount_ml__lte=5000),
                name="water_intake_amount_between_1_and_5000",
            ),
        ]
        indexes = [
            models.Index(
                fields=["patient", "local_date"],
                name="water_patient_date_idx",
            ),
            models.Index(
                fields=["patient", "consumed_at"],
                name="water_patient_time_idx",
            ),
            models.Index(
                fields=["local_date"],
                name="water_date_idx",
            ),
        ]

    def __str__(self):
        return f"{self.amount_ml} ml for {self.patient_id}"
