"""Change-feed recording and offline batch application.

The server is authoritative. Clients may send old events, but an event never
overwrites a newer server state blindly: dose actions go through the existing
state machine, and an optional ``expected_version`` provides optimistic
concurrency for clients that need it.
"""

import logging

from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework.exceptions import (
    NotFound,
    PermissionDenied,
    ValidationError,
)

from apps.core.exceptions import Conflict
from apps.core.permissions import (
    accessible_patient_ids,
    can_confirm_dose,
    can_read_patient,
)

from .models import SyncChange, SyncCursor

logger = logging.getLogger("apps.sync")


def _dt(value):
    return value.isoformat() if value is not None else None


def _date(value):
    return value.isoformat() if value is not None else None


def _time(value):
    return value.isoformat() if value is not None else None


def serialize_medication(medication):
    return {
        "id": str(medication.pk),
        "patient_id": medication.patient_id,
        "name": medication.name,
        "strength": medication.strength,
        "dosage_form": medication.dosage_form,
        "instructions": medication.instructions,
        "dose_amount": (
            str(medication.dose_amount)
            if medication.dose_amount is not None
            else None
        ),
        "dose_unit": medication.dose_unit,
        "start_date": _date(medication.start_date),
        "end_date": _date(medication.end_date),
        "is_active": medication.is_active,
        "created_by_id": medication.created_by_id,
        "created_at": _dt(medication.created_at),
        "updated_at": _dt(medication.updated_at),
    }


def serialize_schedule(schedule):
    return {
        "id": str(schedule.pk),
        "patient_id": schedule.medication.patient_id,
        "medication_id": str(schedule.medication_id),
        "schedule_type": schedule.schedule_type,
        "times": schedule.times,
        "weekdays": schedule.weekdays,
        "interval_hours": schedule.interval_hours,
        "anchor_time": _time(schedule.anchor_time),
        "timezone": schedule.timezone,
        "is_active": schedule.is_active,
        "created_by_id": schedule.created_by_id,
        "created_at": _dt(schedule.created_at),
        "updated_at": _dt(schedule.updated_at),
    }


def serialize_occurrence(occurrence):
    return {
        "occurrence_id": str(occurrence.pk),
        "patient_id": occurrence.patient_id,
        "medication_id": str(occurrence.medication_id),
        "schedule_id": str(occurrence.schedule_id),
        "scheduled_at": _dt(occurrence.scheduled_at),
        "scheduled_date": _date(occurrence.scheduled_date),
        "status": occurrence.status,
        "alert_status": occurrence.alert_status,
        "taken_at": _dt(occurrence.taken_at),
        "skipped_at": _dt(occurrence.skipped_at),
        "snoozed_until": _dt(occurrence.snoozed_until),
        "snooze_count": occurrence.snooze_count,
        "cancelled_at": _dt(occurrence.cancelled_at),
        "cancellation_reason": occurrence.cancellation_reason,
        "superseded_by_id": (
            str(occurrence.superseded_by_id)
            if occurrence.superseded_by_id
            else None
        ),
        "created_at": _dt(occurrence.created_at),
        "updated_at": _dt(occurrence.updated_at),
    }


def serialize_event(event):
    return {
        "event_id": str(event.pk),
        "occurrence_id": str(event.occurrence_id),
        "patient_id": event.occurrence.patient_id,
        "event_type": event.event_type,
        "actor_id": event.actor_id,
        "client_event_id": event.client_event_id,
        "client_recorded_at": _dt(event.client_recorded_at),
        "server_received_at": _dt(event.server_received_at),
        "source": event.source,
        "payload": event.payload,
    }


def serialize_water_intake(log):
    return {
        "water_intake_id": str(log.pk),
        "patient_id": log.patient_id,
        "client_event_id": (
            str(log.client_event_id) if log.client_event_id else None
        ),
        "amount_ml": log.amount_ml,
        "consumed_at": _dt(log.consumed_at),
        "local_date": _date(log.local_date),
        "source": log.source,
        "notes": log.notes,
        "created_by_id": log.created_by_id,
        "created_at": _dt(log.created_at),
        "updated_at": _dt(log.updated_at),
    }


def serialize_water_settings(settings_obj):
    return {
        "water_settings_id": str(settings_obj.pk),
        "patient_id": settings_obj.patient_id,
        "enabled": settings_obj.enabled,
        "start_time": _time(settings_obj.start_time),
        "end_time": _time(settings_obj.end_time),
        "interval_minutes": settings_obj.interval_minutes,
        "daily_goal_ml": settings_obj.daily_goal_ml,
        "cup_size_ml": settings_obj.cup_size_ml,
        "timezone": settings_obj.timezone,
        "created_at": _dt(settings_obj.created_at),
        "updated_at": _dt(settings_obj.updated_at),
    }


def _lock_sync_cursor():
    """Return the singleton cursor row locked until the outer commit."""
    cursor = SyncCursor.objects.select_for_update().filter(pk=1).first()
    if cursor is not None:
        return cursor

    initial = SyncChange.objects.aggregate(Max("sequence"))["sequence__max"] or 0
    try:
        with transaction.atomic():
            SyncCursor.objects.create(pk=1, last_sequence=initial)
    except IntegrityError:
        pass
    return SyncCursor.objects.select_for_update().get(pk=1)


def record_change(
    patient_id,
    entity_type,
    object_id,
    operation=SyncChange.Operation.UPSERT,
    data=None,
    actor=None,
):
    if patient_id is None:
        return None

    with transaction.atomic():
        cursor = _lock_sync_cursor()
        sequence = cursor.last_sequence + 1
        cursor.last_sequence = sequence
        cursor.save(update_fields=["last_sequence"])
        return SyncChange.objects.create(
            sequence=sequence,
            patient_id=patient_id,
            entity_type=entity_type,
            object_id=object_id,
            operation=operation,
            data=data or {},
            actor=actor,
        )


def record_medication(medication, actor=None):
    return record_change(
        medication.patient_id,
        SyncChange.EntityType.MEDICATION,
        medication.pk,
        data=serialize_medication(medication),
        actor=actor,
    )


def record_schedule(schedule, actor=None):
    return record_change(
        schedule.medication.patient_id,
        SyncChange.EntityType.SCHEDULE,
        schedule.pk,
        data=serialize_schedule(schedule),
        actor=actor,
    )


def record_occurrence(occurrence, actor=None):
    return record_change(
        occurrence.patient_id,
        SyncChange.EntityType.DOSE_OCCURRENCE,
        occurrence.pk,
        data=serialize_occurrence(occurrence),
        actor=actor,
    )


def record_event(event, actor=None):
    return record_change(
        event.occurrence.patient_id,
        SyncChange.EntityType.DOSE_EVENT,
        event.pk,
        data=serialize_event(event),
        actor=actor,
    )


def record_water_intake(log, actor=None):
    return record_change(
        log.patient_id,
        SyncChange.EntityType.WATER_INTAKE,
        log.pk,
        data=serialize_water_intake(log),
        actor=actor,
    )


def record_water_settings(settings_obj, actor=None):
    return record_change(
        settings_obj.patient_id,
        SyncChange.EntityType.WATER_SETTINGS,
        settings_obj.pk,
        data=serialize_water_settings(settings_obj),
        actor=actor,
    )


def record_delete(patient_id, entity_type, object_id, actor=None):
    return record_change(
        patient_id,
        entity_type,
        object_id,
        operation=SyncChange.Operation.DELETE,
        data={},
        actor=actor,
    )


def latest_version(entity_type, object_id):
    return (
        SyncChange.objects.filter(
            entity_type=entity_type, object_id=object_id
        )
        .order_by("-sequence")
        .values_list("sequence", flat=True)
        .first()
        or 0
    )


def get_changes(user, cursor=0, limit=50, patient_id=None):
    patient_ids = accessible_patient_ids(user)
    if patient_id is not None:
        if patient_id not in patient_ids:
            raise NotFound("Patient not found.")
        patient_ids = [patient_id]

    queryset = SyncChange.objects.filter(
        patient_id__in=patient_ids, sequence__gt=cursor
    ).order_by("sequence")
    rows = list(queryset[: limit + 1])
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = rows[-1].sequence if rows else cursor

    from .serializers import SyncChangeSerializer

    return {
        "changes": SyncChangeSerializer(rows, many=True).data,
        "next_cursor": next_cursor,
        "has_more": has_more,
        "server_time": timezone.now(),
    }


def _item_result(item, status, **extra):
    result = {
        "client_event_id": str(item["client_event_id"]),
        "type": item["type"],
        "status": status,
    }
    result.update(extra)
    return result


def _conflict_result(item, code, message, server=None):
    result = _item_result(item, "conflict", code=code, message=message)
    if server is not None:
        result["server"] = server
    return result


def _error_result(item, code, message):
    return _item_result(item, "error", code=code, message=message)


def _not_found_result(item):
    return _item_result(
        item, "not_found", code="not_found", message="Record not found."
    )


def _forbidden_result(item):
    return _item_result(
        item,
        "forbidden",
        code="forbidden",
        message="You do not have permission to modify this record.",
    )


def _load_occurrence(occurrence_id):
    from apps.medications.models import DoseOccurrence

    return (
        DoseOccurrence.objects.select_related("medication", "schedule", "patient")
        .filter(pk=occurrence_id)
        .first()
    )


def _apply_dose(item, actor):
    from apps.medications.models import DoseEvent
    from apps.medications.services import confirm_dose, skip_dose, snooze_dose

    occurrence = _load_occurrence(item["occurrence_id"])
    if occurrence is None:
        return _not_found_result(item)
    if not can_confirm_dose(actor, occurrence.patient_id):
        if can_read_patient(actor, occurrence.patient_id):
            return _forbidden_result(item)
        return _not_found_result(item)

    client_event_id = str(item["client_event_id"])
    existing = (
        DoseEvent.objects.select_related("occurrence")
        .filter(client_event_id=client_event_id)
        .first()
    )
    if existing is not None:
        if existing.occurrence_id != occurrence.pk:
            return _conflict_result(
                item,
                "client_event_id_reused",
                "This client event id was already used for another dose.",
            )
        return _item_result(
            item,
            "duplicate",
            event_id=str(existing.pk),
            occurrence_id=str(occurrence.pk),
            server={
                "occurrence": serialize_occurrence(occurrence),
                "event": serialize_event(existing),
            },
        )

    expected_version = item.get("expected_version")
    if expected_version is not None:
        current_version = latest_version(
            SyncChange.EntityType.DOSE_OCCURRENCE, occurrence.pk
        )
        if expected_version != current_version:
            return _conflict_result(
                item,
                "version_conflict",
                "The dose changed on the server after this client version.",
                server={"occurrence": serialize_occurrence(occurrence)},
            )

    try:
        if item["type"] == "dose.confirm":
            occurrence, event = confirm_dose(
                occurrence,
                actor=actor,
                client_event_id=client_event_id,
                client_recorded_at=item.get("client_recorded_at"),
            )
        elif item["type"] == "dose.skip":
            occurrence, event = skip_dose(
                occurrence,
                actor=actor,
                client_event_id=client_event_id,
                client_recorded_at=item.get("client_recorded_at"),
            )
        else:
            occurrence, event = snooze_dose(
                occurrence,
                actor=actor,
                client_event_id=client_event_id,
                minutes=item.get("minutes"),
                client_recorded_at=item.get("client_recorded_at"),
            )
    except Conflict as exc:
        occurrence.refresh_from_db()
        return _conflict_result(
            item,
            "state_conflict",
            str(exc.detail),
            server={"occurrence": serialize_occurrence(occurrence)},
        )
    except PermissionDenied:
        return _forbidden_result(item)
    except ValidationError as exc:
        return _error_result(item, "validation_error", str(exc.detail))

    if event is None:
        occurrence.refresh_from_db()
        return _conflict_result(
            item,
            "state_conflict",
            "The dose was already in a terminal state on the server.",
            server={"occurrence": serialize_occurrence(occurrence)},
        )

    occurrence.refresh_from_db()
    return _item_result(
        item,
        "applied",
        event_id=str(event.pk),
        occurrence_id=str(occurrence.pk),
        server={
            "occurrence": serialize_occurrence(occurrence),
            "event": serialize_event(event),
        },
    )


def _apply_water(item, actor):
    from apps.water.models import WaterIntakeLog
    from apps.water.services import record_intake

    if not actor.is_patient:
        return _forbidden_result(item)

    client_event_id = str(item["client_event_id"])
    existing = WaterIntakeLog.objects.filter(
        client_event_id=client_event_id
    ).first()
    if existing is not None:
        if existing.patient_id != actor.pk:
            return _conflict_result(
                item,
                "client_event_id_reused",
                "This client event id was already used for another patient.",
            )
        return _item_result(
            item,
            "duplicate",
            water_intake_id=str(existing.pk),
            server={"water_intake": serialize_water_intake(existing)},
        )

    try:
        log = record_intake(
            actor,
            item["amount_ml"],
            consumed_at=item.get("consumed_at"),
            source=item.get("source") or "manual",
            notes=item.get("notes") or "",
            created_by=actor,
            client_event_id=client_event_id,
        )
    except IntegrityError:
        log = WaterIntakeLog.objects.filter(
            client_event_id=client_event_id, patient=actor
        ).first()
        if log is None:
            raise
        return _item_result(
            item,
            "duplicate",
            water_intake_id=str(log.pk),
            server={"water_intake": serialize_water_intake(log)},
        )

    return _item_result(
        item,
        "applied",
        water_intake_id=str(log.pk),
        server={"water_intake": serialize_water_intake(log)},
    )


def apply_sync_batch(items, actor):
    results = []
    for item in items:
        try:
            with transaction.atomic():
                if item["type"].startswith("dose."):
                    result = _apply_dose(item, actor)
                else:
                    result = _apply_water(item, actor)
        except Exception:  # noqa: BLE001 - isolate one bad item from the batch
            logger.exception(
                "Unexpected sync item failure for %s", item.get("client_event_id")
            )
            result = _error_result(
                item,
                "internal_error",
                "The item could not be processed.",
            )
        results.append(result)

    counts = {"applied": 0, "duplicate": 0, "conflict": 0, "error": 0}
    for result in results:
        if result["status"] in counts:
            counts[result["status"]] += 1
        elif result["status"] in {"not_found", "forbidden"}:
            counts["error"] += 1

    return {
        "results": results,
        "counts": counts,
    }
