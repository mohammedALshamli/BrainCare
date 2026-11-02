from django.conf import settings
from django.db import models


class SyncChange(models.Model):
    """Append-only, commit-ordered change feed.

    ``sequence`` is allocated from ``SyncCursor`` under a row lock that is held
    until the surrounding transaction commits. A plain database sequence would
    allocate values before commit, allowing a later transaction to commit first
    and a client to advance past an earlier uncommitted change. The locked
    counter makes allocation order equal to commit order for every patient.
    """

    class EntityType(models.TextChoices):
        MEDICATION = "medication", "Medication"
        SCHEDULE = "schedule", "Medication schedule"
        DOSE_OCCURRENCE = "dose_occurrence", "Dose occurrence"
        DOSE_EVENT = "dose_event", "Dose event"
        WATER_INTAKE = "water_intake", "Water intake"
        WATER_SETTINGS = "water_settings", "Water settings"

    class Operation(models.TextChoices):
        UPSERT = "upsert", "Upsert"
        DELETE = "delete", "Delete (tombstone)"

    sequence = models.BigIntegerField(primary_key=True, editable=False)
    patient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sync_changes",
    )
    entity_type = models.CharField(max_length=32, choices=EntityType.choices)
    object_id = models.UUIDField(db_index=True)
    operation = models.CharField(
        max_length=8, choices=Operation.choices, default=Operation.UPSERT
    )
    data = models.JSONField(default=dict, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sync_changes_made",
    )
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sequence"]
        indexes = [
            models.Index(
                fields=["patient", "sequence"],
                name="sync_patient_sequence_idx",
            ),
            models.Index(
                fields=["entity_type", "object_id"],
                name="sync_entity_object_idx",
            ),
        ]

    def __str__(self):
        return f"{self.sequence}: {self.entity_type} {self.object_id}"


class SyncCursor(models.Model):
    """Singleton counter for the global commit-ordered sync sequence.

    The row is locked with ``SELECT ... FOR UPDATE`` for the whole transaction
    that writes a change. The lock is intentionally global rather than
    per-patient: caregivers can read a feed spanning multiple patients, so a
    single global commit order is required to avoid advancing a cursor past a
    still-uncommitted change for another patient.
    """

    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    last_sequence = models.PositiveBigIntegerField(default=0)

    class Meta:
        verbose_name = "sync cursor"
        verbose_name_plural = "sync cursor"

    def __str__(self):
        return f"sync cursor {self.last_sequence}"
