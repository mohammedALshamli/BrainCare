"""Domain services for generation and dose tracking.

All state transitions that can race are guarded by either ``select_for_update``
(on databases that support it) or conditional ``UPDATE ... WHERE status IN
(...)`` statements, so the conditional update is the source of truth.
"""

from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.core.exceptions import Conflict
from apps.notifications.services import enqueue_dose_overdue_notifications

from .models import DoseEvent, DoseOccurrence, Medication, MedicationSchedule
from .recurrence import calculate_window_occurrences


def _window_days(window_days):
    return (
        settings.DOSE_GENERATION_WINDOW_DAYS
        if window_days is None
        else window_days
    )


def _generate_locked(schedule, window_days=None, now=None) -> int:
    if not schedule.is_active or not schedule.medication.is_active:
        return 0

    occurrences = calculate_window_occurrences(
        schedule, _window_days(window_days), now=now
    )
    if not occurrences:
        return 0

    instants = [instant for instant, _ in occurrences]
    existing = set(
        DoseOccurrence.objects.filter(
            schedule=schedule, scheduled_at__in=instants
        ).values_list("scheduled_at", flat=True)
    )

    new_occurrences = [
        DoseOccurrence(
            medication_id=schedule.medication_id,
            schedule=schedule,
            patient_id=schedule.medication.patient_id,
            scheduled_at=instant,
            scheduled_date=local_date,
        )
        for instant, local_date in occurrences
        if instant not in existing
    ]
    if new_occurrences:
        # The unique (schedule, scheduled_at) constraint makes concurrent
        # generators harmless even if both build the same batch.
        DoseOccurrence.objects.bulk_create(
            new_occurrences, ignore_conflicts=True, batch_size=500
        )
    return len(new_occurrences)


@transaction.atomic
def generate_occurrences(schedule, window_days=None, now=None) -> int:
    locked = (
        MedicationSchedule.objects.select_for_update()
        .select_related("medication")
        .get(pk=schedule.pk)
    )
    return _generate_locked(locked, window_days=window_days, now=now)


def _delete_future_pending(schedule, now) -> int:
    deleted, _ = (
        DoseOccurrence.objects.filter(
            schedule=schedule,
            scheduled_at__gte=now,
            status=DoseOccurrence.Status.PENDING,
            events__isnull=True,
            snoozed_until__isnull=True,
        ).delete()
    )
    return deleted


@transaction.atomic
def regenerate_future(
    schedule, window_days=None, now=None, remove_future_pending=True
) -> int:
    """Refresh generated future doses after a material schedule change.

    Completed, overdue, snoozed, or event-bearing occurrences are never
    removed. Only generated future pending occurrences with no interaction are
    replaced.
    """
    now = now or timezone.now()
    locked = (
        MedicationSchedule.objects.select_for_update()
        .select_related("medication")
        .get(pk=schedule.pk)
    )
    if remove_future_pending:
        _delete_future_pending(locked, now)
    return _generate_locked(locked, window_days=window_days, now=now)


@transaction.atomic
def deactivate_schedule(schedule, now=None) -> int:
    now = now or timezone.now()
    locked = (
        MedicationSchedule.objects.select_for_update()
        .select_related("medication")
        .get(pk=schedule.pk)
    )
    deleted = _delete_future_pending(locked, now)
    locked.is_active = False
    locked.save(update_fields=["is_active", "updated_at"])
    return deleted


@transaction.atomic
def deactivate_medication(medication, now=None) -> int:
    """Deactivate a medication without deleting any historical dose data."""
    now = now or timezone.now()
    locked = Medication.objects.select_for_update().get(pk=medication.pk)
    locked.is_active = False
    locked.save(update_fields=["is_active", "updated_at"])

    schedule_ids = list(
        locked.schedules.values_list("pk", flat=True)
    )
    deleted = 0
    for schedule_id in schedule_ids:
        deleted += _delete_future_pending(
            MedicationSchedule(pk=schedule_id), now
        )
    return deleted


@transaction.atomic
def reactivate_medication(medication, window_days=None, now=None) -> int:
    locked = Medication.objects.select_for_update().get(pk=medication.pk)
    if not locked.is_active:
        locked.is_active = True
        locked.save(update_fields=["is_active", "updated_at"])

    generated = 0
    for schedule in locked.schedules.filter(is_active=True).select_related(
        "medication"
    ):
        generated += _generate_locked(schedule, window_days=window_days, now=now)
    return generated


def mark_overdue_doses(grace_minutes=None, now=None) -> int:
    """Mark unconfirmed doses as overdue without touching alert state.

    The dose status and the notification/escalation status stay independent:
    this function never writes ``alert_status``.
    """
    now = now or timezone.now()
    grace = (
        settings.DOSE_OVERDUE_GRACE_MINUTES
        if grace_minutes is None
        else grace_minutes
    )
    cutoff = now - timedelta(minutes=grace)

    base_filter = Q(status=DoseOccurrence.Status.PENDING) & Q(
        scheduled_at__lte=cutoff
    ) & (Q(snoozed_until__isnull=True) | Q(snoozed_until__lte=now))

    candidate_ids = list(
        DoseOccurrence.objects.filter(base_filter).values_list("pk", flat=True)
    )

    marked = 0
    for occurrence_id in candidate_ids:
        with transaction.atomic():
            updated = DoseOccurrence.objects.filter(
                base_filter, pk=occurrence_id
            ).update(
                status=DoseOccurrence.Status.OVERDUE_UNCONFIRMED,
                updated_at=now,
            )
            if updated:
                DoseEvent.objects.create(
                    occurrence_id=occurrence_id,
                    event_type=DoseEvent.EventType.OVERDUE,
                    source=DoseEvent.Source.SYSTEM,
                    payload={"grace_minutes": grace},
                )
                occurrence = DoseOccurrence.objects.get(pk=occurrence_id)
                enqueue_dose_overdue_notifications(occurrence, now=now)
                marked += 1
    return marked


def _assert_patient_actor(actor, occurrence):
    if (
        actor is None
        or not getattr(actor, "is_authenticated", False)
        or not getattr(actor, "is_patient", False)
        or occurrence.patient_id != actor.pk
    ):
        raise PermissionDenied(
            "Only the patient who owns this dose can perform this action."
        )


def _existing_event(client_event_id, occurrence):
    event = DoseEvent.objects.filter(client_event_id=client_event_id).first()
    if event is None:
        return None
    if event.occurrence_id != occurrence.pk:
        raise Conflict(
            "This client event id has already been used for another dose."
        )
    return event


def _require_client_event_id(value):
    if not value or not str(value).strip():
        raise ValidationError({"client_event_id": "This field is required."})
    return str(value).strip()


def _create_client_event(locked, client_event_id, **fields):
    """Create an event, tolerating a concurrent insert of the same event id."""
    try:
        with transaction.atomic():
            return DoseEvent.objects.create(
                occurrence=locked,
                client_event_id=client_event_id,
                **fields,
            )
    except IntegrityError:
        existing = _existing_event(client_event_id, locked)
        if existing is not None:
            return existing
        raise Conflict(
            "This client event id has already been used for another dose."
        )


def confirm_dose(
    occurrence,
    actor,
    client_event_id,
    client_recorded_at=None,
    source=DoseEvent.Source.PATIENT_APP,
    now=None,
):
    client_event_id = _require_client_event_id(client_event_id)
    now = now or timezone.now()

    with transaction.atomic():
        locked = DoseOccurrence.objects.select_for_update().get(pk=occurrence.pk)
        _assert_patient_actor(actor, locked)

        existing = _existing_event(client_event_id, locked)
        if existing is not None:
            return locked, existing

        late = locked.is_late(now=now)
        previous_status = locked.status

        updated = DoseOccurrence.objects.filter(
            pk=locked.pk,
            status__in=[
                DoseOccurrence.Status.PENDING,
                DoseOccurrence.Status.OVERDUE_UNCONFIRMED,
            ],
        ).update(
            status=DoseOccurrence.Status.TAKEN,
            taken_at=now,
            snoozed_until=None,
            updated_at=now,
        )

        if not updated:
            locked.refresh_from_db()
            if locked.status == DoseOccurrence.Status.TAKEN:
                return locked, None
            raise Conflict("A skipped dose cannot be confirmed.")

        event = _create_client_event(
            locked,
            client_event_id,
            event_type=(
                DoseEvent.EventType.CONFIRMED_LATE
                if late
                else DoseEvent.EventType.TAKEN
            ),
            actor=actor,
            client_recorded_at=client_recorded_at,
            source=source,
            payload={"late": late, "previous_status": previous_status},
        )
        locked.refresh_from_db()
        return locked, event


def skip_dose(
    occurrence,
    actor,
    client_event_id,
    client_recorded_at=None,
    source=DoseEvent.Source.PATIENT_APP,
    now=None,
):
    client_event_id = _require_client_event_id(client_event_id)
    now = now or timezone.now()

    with transaction.atomic():
        locked = DoseOccurrence.objects.select_for_update().get(pk=occurrence.pk)
        _assert_patient_actor(actor, locked)

        existing = _existing_event(client_event_id, locked)
        if existing is not None:
            return locked, existing

        if locked.status == DoseOccurrence.Status.SKIPPED:
            return locked, None

        previous_status = locked.status
        updated = DoseOccurrence.objects.filter(
            pk=locked.pk,
            status__in=[
                DoseOccurrence.Status.PENDING,
                DoseOccurrence.Status.OVERDUE_UNCONFIRMED,
            ],
        ).update(
            status=DoseOccurrence.Status.SKIPPED,
            skipped_at=now,
            snoozed_until=None,
            updated_at=now,
        )

        if not updated:
            locked.refresh_from_db()
            if locked.status == DoseOccurrence.Status.SKIPPED:
                return locked, None
            raise Conflict("A taken dose cannot be skipped.")

        event = _create_client_event(
            locked,
            client_event_id,
            event_type=DoseEvent.EventType.SKIPPED,
            actor=actor,
            client_recorded_at=client_recorded_at,
            source=source,
            payload={
                "late": locked.is_late(now=now),
                "previous_status": previous_status,
            },
        )
        locked.refresh_from_db()
        return locked, event


def snooze_dose(
    occurrence,
    actor,
    client_event_id,
    minutes=None,
    client_recorded_at=None,
    source=DoseEvent.Source.PATIENT_APP,
    now=None,
):
    client_event_id = _require_client_event_id(client_event_id)
    now = now or timezone.now()
    minutes = (
        settings.DOSE_SNOOZE_DEFAULT_MINUTES if minutes is None else int(minutes)
    )
    if minutes < 1 or minutes > settings.DOSE_SNOOZE_MAX_MINUTES:
        raise ValidationError(
            {
                "minutes": (
                    "Snooze must be between 1 and "
                    f"{settings.DOSE_SNOOZE_MAX_MINUTES} minutes."
                )
            }
        )

    with transaction.atomic():
        locked = DoseOccurrence.objects.select_for_update().get(pk=occurrence.pk)
        _assert_patient_actor(actor, locked)

        existing = _existing_event(client_event_id, locked)
        if existing is not None:
            return locked, existing

        if locked.status in (
            DoseOccurrence.Status.TAKEN,
            DoseOccurrence.Status.SKIPPED,
        ):
            raise Conflict("A completed dose cannot be snoozed.")

        previous_status = locked.status
        snoozed_until = now + timedelta(minutes=minutes)
        updated = DoseOccurrence.objects.filter(
            pk=locked.pk,
            status__in=[
                DoseOccurrence.Status.PENDING,
                DoseOccurrence.Status.OVERDUE_UNCONFIRMED,
            ],
        ).update(
            status=DoseOccurrence.Status.PENDING,
            snoozed_until=snoozed_until,
            snooze_count=F("snooze_count") + 1,
            updated_at=now,
        )

        if not updated:
            locked.refresh_from_db()
            raise Conflict("A completed dose cannot be snoozed.")

        event = _create_client_event(
            locked,
            client_event_id,
            event_type=DoseEvent.EventType.SNOOZED,
            actor=actor,
            client_recorded_at=client_recorded_at,
            source=source,
            payload={
                "minutes": minutes,
                "previous_status": previous_status,
                "snoozed_until": snoozed_until.isoformat(),
            },
        )
        locked.refresh_from_db()
        return locked, event
