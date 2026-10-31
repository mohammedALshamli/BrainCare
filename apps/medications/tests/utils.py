from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.utils import timezone

from apps.accounts.models import CaregiverPatientLink, User
from apps.medications.models import (
    DoseEvent,
    DoseOccurrence,
    Medication,
    MedicationSchedule,
)

PASSWORD = "Str0ng-Passw0rd!2026"


def create_patient(email="patient@example.com", **extra):
    return User.objects.create_user(
        email=email, password=PASSWORD, is_patient=True, **extra
    )


def create_caregiver(email="caregiver@example.com", **extra):
    return User.objects.create_user(
        email=email, password=PASSWORD, is_caregiver=True, **extra
    )


def link_caregiver(
    caregiver,
    patient,
    is_active=True,
    can_view=True,
    can_edit_medications=False,
    notify_missed_doses=True,
):
    return CaregiverPatientLink.objects.create(
        caregiver=caregiver,
        patient=patient,
        is_active=is_active,
        can_view=can_view,
        can_edit_medications=can_edit_medications,
        notify_missed_doses=notify_missed_doses,
    )


def create_medication(patient, **overrides):
    defaults = {
        "patient": patient,
        "created_by": patient,
        "name": "Test Medication",
        "strength": "500 mg",
        "dosage_form": "tablet",
        "instructions": "After food",
        "start_date": timezone.localdate(),
        "is_active": True,
    }
    defaults.update(overrides)
    return Medication.objects.create(**defaults)


def create_schedule(medication, **overrides):
    defaults = {
        "medication": medication,
        "created_by": medication.patient,
        "schedule_type": MedicationSchedule.ScheduleType.FIXED_TIMES,
        "times": ["08:00"],
        "timezone": "UTC",
        "is_active": True,
    }
    defaults.update(overrides)
    return MedicationSchedule.objects.create(**defaults)


def create_occurrence(medication, schedule, scheduled_at=None, **overrides):
    scheduled_at = scheduled_at or timezone.now()
    local_date = scheduled_at.astimezone(
        ZoneInfo(schedule.timezone)
    ).date()
    defaults = {
        "medication": medication,
        "schedule": schedule,
        "patient": medication.patient,
        "scheduled_at": scheduled_at,
        "scheduled_date": local_date,
        "status": DoseOccurrence.Status.PENDING,
    }
    defaults.update(overrides)
    return DoseOccurrence.objects.create(**defaults)


def add_event(occurrence, event_type, **overrides):
    defaults = {
        "occurrence": occurrence,
        "event_type": event_type,
        "source": DoseEvent.Source.SYSTEM,
    }
    defaults.update(overrides)
    return DoseEvent.objects.create(**defaults)


def utc(*args, **kwargs):
    return datetime(*args, tzinfo=dt_timezone.utc, **kwargs)


def local_datetime(local_date, local_time, tz_name):
    return datetime.combine(
        local_date, local_time, tzinfo=ZoneInfo(tz_name)
    )


def occurrence_count(schedule):
    return DoseOccurrence.objects.filter(schedule=schedule).count()


__all__ = [
    "PASSWORD",
    "add_event",
    "create_caregiver",
    "create_medication",
    "create_occurrence",
    "create_patient",
    "create_schedule",
    "link_caregiver",
    "local_datetime",
    "occurrence_count",
    "utc",
]
