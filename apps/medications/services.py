"""Domain services for generation and dose tracking.

All state transitions that can race are guarded by either ``select_for_update``
(on databases that support it) or conditional ``UPDATE ... WHERE status IN
(...)`` statements, so the conditional update is the source of truth.
"""

from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, F, OuterRef, Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.core.exceptions import Conflict
from apps.core.permissions import can_confirm_dose
from apps.notifications.services import enqueue_dose_overdue_notifications
from apps.sync import services as sync_services

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
    existing_rows = list(
        DoseOccurrence.objects.filter(
            schedule=schedule, scheduled_at__in=instants
        ).annotate(event_count=Count("events"))
    )
    existing_by_instant = {row.scheduled_at: row for row in existing_rows}

    new_occurrences = []
    reactivate_ids = []
    for instant, local_date in occurrences:
        existing = existing_by_instant.get(instant)
        if existing is None:
            new_occurrences.append(
                DoseOccurrence(
                    medication_id=schedule.medication_id,
                    schedule=schedule,
                    patient_id=schedule.medication.patient_id,
                    scheduled_at=instant,
                    scheduled_date=local_date,
                )
            )
        elif (
            existing.status == DoseOccurrence.Status.CANCELLED
            and existing.snoozed_until is None
            and existing.event_count == 0
        ):
            # The same wall-clock slot is still required after a schedule
            # edit. Reuse the cancelled row instead of inserting a duplicate
            # that would violate unique(schedule, scheduled_at).
            reactivate_ids.append(existing.pk)

    if reactivate_ids:
        DoseOccurrence.objects.filter(
            pk__in=reactivate_ids,
            status=DoseOccurrence.Status.CANCELLED,
            snoozed_until__isnull=True,
        ).update(
            status=DoseOccurrence.Status.PENDING,
            cancelled_at=None,
            cancellation_reason="",
            superseded_by=None,
            updated_at=timezone.now(),
        )

    if new_occurrences:
        # The unique (schedule, scheduled_at) constraint makes concurrent
        # generators harmless even if both build the same batch.
        DoseOccurrence.objects.bulk_create(
            new_occurrences, ignore_conflicts=True, batch_size=500
        )
        # PostgreSQL does not populate primary keys for ignore_conflicts
        # inserts, so re-read the slots that did not exist before this batch.
        existing_ids = [row.pk for row in existing_rows]
        created_rows = DoseOccurrence.objects.filter(
            schedule=schedule,
            scheduled_at__in=[row.scheduled_at for row in new_occurrences],
        ).exclude(pk__in=existing_ids)
        for occurrence in created_rows:
            sync_services.record_occurrence(occurrence)

    if reactivate_ids:
        for occurrence in DoseOccurrence.objects.filter(pk__in=reactivate_ids):
            sync_services.record_occurrence(occurrence)

    return len(new_occurrences) + len(reactivate_ids)


@transaction.atomic
def generate_occurrences(schedule, window_days=None, now=None) -> int:
    locked = (
        MedicationSchedule.objects.select_for_update()
        .select_related("medication")
        .get(pk=schedule.pk)
    )
    return _generate_locked(locked, window_days=window_days, now=now)


def _cancel_future_pending(schedule, now, reason="schedule_changed") -> int:
    """Cancel untouched future doses without destroying their identity.

    The rows are kept so an offline device that already received them can still
    submit a confirmation. Only pending rows with no events and no snooze are
    cancelled; completed, overdue, snoozed, or event-bearing rows are never
    touched.
    """
    no_events = ~Exists(
        DoseEvent.objects.filter(occurrence_id=OuterRef("pk"))
    )
    queryset = DoseOccurrence.objects.filter(
        schedule=schedule,
        scheduled_at__gte=now,
        status=DoseOccurrence.Status.PENDING,
        snoozed_until__isnull=True,
    ).filter(no_events)
    candidate_ids = list(
        queryset.select_for_update().values_list("pk", flat=True)
    )
    if not candidate_ids:
        return 0

    updated = DoseOccurrence.objects.filter(
        pk__in=candidate_ids,
        status=DoseOccurrence.Status.PENDING,
        snoozed_until__isnull=True,
    ).filter(no_events).update(
        status=DoseOccurrence.Status.CANCELLED,
        cancelled_at=now,
        cancellation_reason=reason,
        superseded_by=None,
        updated_at=now,
    )
    for occurrence in DoseOccurrence.objects.filter(
        pk__in=candidate_ids,
        status=DoseOccurrence.Status.CANCELLED,
        cancelled_at=now,
    ):
        sync_services.record_occurrence(occurrence)
    return updated


def _link_superseded(schedule, now) -> int:
    """Best-effort link from a cancelled dose to its same-day replacement."""
    cancelled = list(
        DoseOccurrence.objects.filter(
            schedule=schedule,
            status=DoseOccurrence.Status.CANCELLED,
            scheduled_at__gte=now,
            superseded_by__isnull=True,
        ).order_by("scheduled_date", "scheduled_at")
    )
    if not cancelled:
        return 0

    pending_by_date = {}
    for occurrence in DoseOccurrence.objects.filter(
        schedule=schedule,
        status=DoseOccurrence.Status.PENDING,
        scheduled_at__gte=now,
    ).order_by("scheduled_at"):
        pending_by_date.setdefault(occurrence.scheduled_date, []).append(
            occurrence
        )

    used = set()
    linked = 0
    for old in cancelled:
        candidates = [
            candidate
            for candidate in pending_by_date.get(old.scheduled_date, [])
            if candidate.pk not in used
        ]
        if not candidates:
            continue
        replacement = min(
            candidates,
            key=lambda candidate: abs(
                (candidate.scheduled_at - old.scheduled_at).total_seconds()
            ),
        )
        old.superseded_by = replacement
        old.save(update_fields=["superseded_by", "updated_at"])
        used.add(replacement.pk)
        linked += 1
        sync_services.record_occurrence(old)
    return linked


@transaction.atomic
def regenerate_future(
    schedule, window_days=None, now=None, cancel_future_pending=True
) -> int:
    """Refresh generated future doses after a material schedule change.

    Future untouched pending occurrences are soft-cancelled, not deleted.
    Completed, overdue, snoozed, or event-bearing occurrences are never
    modified. Cancelled rows are reactivated when the updated schedule needs the
    same instant again; otherwise they are linked to a same-day replacement.
    """
    now = now or timezone.now()
    locked = (
        MedicationSchedule.objects.select_for_update()
        .select_related("medication")
        .get(pk=schedule.pk)
    )
    if cancel_future_pending:
        _cancel_future_pending(locked, now)
    generated = _generate_locked(locked, window_days=window_days, now=now)
    _link_superseded(locked, now)
    return generated


@transaction.atomic
def deactivate_schedule(schedule, now=None) -> int:
    now = now or timezone.now()
    locked = (
        MedicationSchedule.objects.select_for_update()
        .select_related("medication")
        .get(pk=schedule.pk)
    )
    cancelled = _cancel_future_pending(
        locked, now, reason="schedule_deactivated"
    )
    locked.is_active = False
    locked.save(update_fields=["is_active", "updated_at"])
    sync_services.record_schedule(locked)
    return cancelled


@transaction.atomic
def deactivate_medication(medication, now=None) -> int:
    """Deactivate a medication without deleting any historical dose data."""
    now = now or timezone.now()
    locked = Medication.objects.select_for_update().get(pk=medication.pk)
    locked.is_active = False
    locked.save(update_fields=["is_active", "updated_at"])
    sync_services.record_medication(locked)

    schedule_ids = list(
        locked.schedules.values_list("pk", flat=True)
    )
    cancelled = 0
    for schedule_id in schedule_ids:
        cancelled += _cancel_future_pending(
            MedicationSchedule(pk=schedule_id),
            now,
            reason="medication_deactivated",
        )
    return cancelled


@transaction.atomic
def reactivate_medication(medication, window_days=None, now=None) -> int:
    locked = Medication.objects.select_for_update().get(pk=medication.pk)
    if not locked.is_active:
        locked.is_active = True
        locked.save(update_fields=["is_active", "updated_at"])
        sync_services.record_medication(locked)

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
                event = DoseEvent.objects.create(
                    occurrence_id=occurrence_id,
                    event_type=DoseEvent.EventType.OVERDUE,
                    source=DoseEvent.Source.SYSTEM,
                    payload={"grace_minutes": grace},
                )
                occurrence = DoseOccurrence.objects.get(pk=occurrence_id)
                sync_services.record_occurrence(occurrence)
                sync_services.record_event(event)
                enqueue_dose_overdue_notifications(occurrence, now=now)
                marked += 1
    return marked


def _assert_dose_actor(actor, occurrence) -> str:
    """Authorize a dose action and return ``"patient"`` or ``"caregiver"``.

    Caregivers must hold the dedicated ``can_confirm_doses`` permission. Role
    and identity always come from the authenticated server-side user, never
    from client-supplied data.
    """
    if not can_confirm_dose(actor, occurrence.patient_id):
        raise PermissionDenied(
            "You do not have permission to act on this dose."
        )
    if actor.is_patient and occurrence.patient_id == actor.pk:
        return "patient"
    return "caregiver"


def _resolved_source(actor_role, requested_source):
    if actor_role == "caregiver":
        return DoseEvent.Source.CAREGIVER_APP
    if requested_source == DoseEvent.Source.API:
        return DoseEvent.Source.API
    return DoseEvent.Source.PATIENT_APP


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
        actor_role = _assert_dose_actor(actor, locked)
        resolved_source = _resolved_source(actor_role, source)

        existing = _existing_event(client_event_id, locked)
        if existing is not None:
            return locked, existing

        late = locked.is_late(now=now)
        previous_status = locked.status
        after_cancellation = (
            previous_status == DoseOccurrence.Status.CANCELLED
        )
        superseded_by_id = locked.superseded_by_id

        updated = DoseOccurrence.objects.filter(
            pk=locked.pk,
            status__in=[
                DoseOccurrence.Status.PENDING,
                DoseOccurrence.Status.OVERDUE_UNCONFIRMED,
                DoseOccurrence.Status.CANCELLED,
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
            source=resolved_source,
            payload={
                "late": late,
                "previous_status": previous_status,
                "confirmed_after_cancellation": after_cancellation,
                "recorded_against_superseded": superseded_by_id is not None,
                "superseded_by_id": (
                    str(superseded_by_id) if superseded_by_id else None
                ),
                "actor_role": actor_role,
            },
        )
        locked.refresh_from_db()
        sync_services.record_occurrence(locked, actor=actor)
        sync_services.record_event(event, actor=actor)
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
        actor_role = _assert_dose_actor(actor, locked)
        resolved_source = _resolved_source(actor_role, source)

        existing = _existing_event(client_event_id, locked)
        if existing is not None:
            return locked, existing

        if locked.status == DoseOccurrence.Status.SKIPPED:
            return locked, None

        previous_status = locked.status
        after_cancellation = (
            previous_status == DoseOccurrence.Status.CANCELLED
        )
        superseded_by_id = locked.superseded_by_id
        updated = DoseOccurrence.objects.filter(
            pk=locked.pk,
            status__in=[
                DoseOccurrence.Status.PENDING,
                DoseOccurrence.Status.OVERDUE_UNCONFIRMED,
                DoseOccurrence.Status.CANCELLED,
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
            source=resolved_source,
            payload={
                "late": locked.is_late(now=now),
                "previous_status": previous_status,
                "skipped_after_cancellation": after_cancellation,
                "recorded_against_superseded": superseded_by_id is not None,
                "superseded_by_id": (
                    str(superseded_by_id) if superseded_by_id else None
                ),
                "actor_role": actor_role,
            },
        )
        locked.refresh_from_db()
        sync_services.record_occurrence(locked, actor=actor)
        sync_services.record_event(event, actor=actor)
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
        actor_role = _assert_dose_actor(actor, locked)
        resolved_source = _resolved_source(actor_role, source)

        existing = _existing_event(client_event_id, locked)
        if existing is not None:
            return locked, existing

        if locked.status in (
            DoseOccurrence.Status.TAKEN,
            DoseOccurrence.Status.SKIPPED,
            DoseOccurrence.Status.CANCELLED,
        ):
            raise Conflict("A completed or cancelled dose cannot be snoozed.")

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
            source=resolved_source,
            payload={
                "minutes": minutes,
                "previous_status": previous_status,
                "snoozed_until": snoozed_until.isoformat(),
                "actor_role": actor_role,
            },
        )
        locked.refresh_from_db()
        sync_services.record_occurrence(locked, actor=actor)
        sync_services.record_event(event, actor=actor)
        return locked, event
