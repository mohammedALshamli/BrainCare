from datetime import date, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.sync import services as sync_services

from .models import WaterIntakeLog, WaterReminderSettings


def timezone_for(settings_obj) -> ZoneInfo:
    name = getattr(settings_obj, "timezone", None) or "UTC"
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def get_or_create_settings(patient):
    settings_obj, _ = WaterReminderSettings.objects.get_or_create(
        patient=patient
    )
    return settings_obj


def local_date_for(settings_obj, moment=None) -> date:
    moment = moment or timezone.now()
    return moment.astimezone(timezone_for(settings_obj)).date()


def record_intake(
    patient,
    amount_ml,
    consumed_at=None,
    source=WaterIntakeLog.Source.MANUAL,
    notes="",
    created_by=None,
    client_event_id=None,
):
    if client_event_id is not None:
        existing = WaterIntakeLog.objects.filter(
            patient=patient, client_event_id=client_event_id
        ).first()
        if existing is not None:
            return existing

    consumed_at = consumed_at or timezone.now()
    settings_obj = get_or_create_settings(patient)
    try:
        log = WaterIntakeLog.objects.create(
            patient=patient,
            client_event_id=client_event_id,
            amount_ml=amount_ml,
            consumed_at=consumed_at,
            local_date=local_date_for(settings_obj, consumed_at),
            source=source,
            notes=notes,
            created_by=created_by or patient,
        )
    except IntegrityError:
        if client_event_id is not None:
            existing = WaterIntakeLog.objects.filter(
                patient=patient, client_event_id=client_event_id
            ).first()
            if existing is not None:
                return existing
        raise

    sync_services.record_water_intake(log, actor=log.created_by)
    return log


def daily_summary(patient, day=None, settings_obj=None):
    settings_obj = settings_obj or get_or_create_settings(patient)
    day = day or local_date_for(settings_obj)
    logs = WaterIntakeLog.objects.filter(patient=patient, local_date=day)
    total = sum(logs.values_list("amount_ml", flat=True))
    goal = settings_obj.daily_goal_ml
    if goal is None:
        return {
            "date": day,
            "total_ml": total,
            "goal_ml": None,
            "remaining_ml": None,
            "progress_percentage": None,
            "log_count": logs.count(),
            "goal_reached": None,
        }
    return {
        "date": day,
        "total_ml": total,
        "goal_ml": goal,
        "remaining_ml": max(goal - total, 0),
        "progress_percentage": min(int(total * 100 / goal), 100),
        "log_count": logs.count(),
        "goal_reached": total >= goal,
    }


def day_bounds_utc(settings_obj, day: date):
    """Return the UTC instants for a local calendar day."""
    tz = timezone_for(settings_obj)
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = datetime.combine(day, time.max, tzinfo=tz)
    return start.astimezone(ZoneInfo("UTC")), end.astimezone(ZoneInfo("UTC"))
