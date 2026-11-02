from datetime import time

from django.conf import settings
from django.db import models
from rest_framework import serializers

from .models import DoseEvent, DoseOccurrence, Medication, MedicationSchedule
from .recurrence import (
    InvalidScheduleConfiguration,
    normalise_times,
    normalise_weekdays,
    validate_timezone,
)


class MedicationSerializer(serializers.ModelSerializer):
    patient = serializers.PrimaryKeyRelatedField(read_only=True)
    created_by = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Medication
        fields = (
            "id",
            "patient",
            "name",
            "strength",
            "dosage_form",
            "instructions",
            "dose_amount",
            "dose_unit",
            "start_date",
            "end_date",
            "is_active",
            "created_by",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "patient",
            "created_by",
            "created_at",
            "updated_at",
        )

    def validate(self, attrs):
        instance = self.instance
        start_date = attrs.get(
            "start_date", getattr(instance, "start_date", None)
        )
        end_date = attrs.get("end_date", getattr(instance, "end_date", None))
        if end_date and start_date and end_date < start_date:
            raise serializers.ValidationError(
                {"end_date": "End date cannot be before the start date."}
            )

        dose_amount = attrs.get(
            "dose_amount", getattr(instance, "dose_amount", None)
        )
        dose_unit = attrs.get("dose_unit", getattr(instance, "dose_unit", ""))
        if dose_amount is not None and not dose_unit:
            raise serializers.ValidationError(
                {"dose_unit": "A dose unit is required when a dose amount is set."}
            )
        if dose_amount is None and dose_unit:
            raise serializers.ValidationError(
                {"dose_amount": "A dose amount is required when a dose unit is set."}
            )
        return attrs


class MedicationScheduleSerializer(serializers.ModelSerializer):
    medication = serializers.PrimaryKeyRelatedField(read_only=True)
    created_by = serializers.PrimaryKeyRelatedField(read_only=True)
    times = serializers.ListField(
        child=serializers.CharField(), required=False
    )
    weekdays = serializers.ListField(
        child=serializers.IntegerField(), required=False
    )
    interval_hours = serializers.IntegerField(
        required=False, allow_null=True, min_value=1, max_value=24
    )
    anchor_time = serializers.TimeField(required=False)
    timezone = serializers.CharField(required=False, default="UTC")

    class Meta:
        model = MedicationSchedule
        fields = (
            "id",
            "medication",
            "schedule_type",
            "times",
            "weekdays",
            "interval_hours",
            "anchor_time",
            "timezone",
            "is_active",
            "created_by",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "medication",
            "created_by",
            "created_at",
            "updated_at",
        )

    def validate(self, attrs):
        instance = self.instance
        schedule_type = attrs.get(
            "schedule_type", getattr(instance, "schedule_type", None)
        )

        if schedule_type not in MedicationSchedule.ScheduleType.values:
            raise serializers.ValidationError(
                {"schedule_type": "Unsupported schedule type."}
            )

        raw_times = attrs.get("times", getattr(instance, "times", []))
        raw_weekdays = attrs.get(
            "weekdays", getattr(instance, "weekdays", [])
        )

        try:
            times = normalise_times(raw_times)
            weekdays = normalise_weekdays(raw_weekdays)
            timezone_name = validate_timezone(
                attrs.get("timezone", getattr(instance, "timezone", "UTC"))
            )
        except InvalidScheduleConfiguration as exc:
            raise serializers.ValidationError({"detail": str(exc)})

        attrs["timezone"] = timezone_name

        if schedule_type == MedicationSchedule.ScheduleType.INTERVAL_HOURS:
            interval_hours = attrs.get(
                "interval_hours", getattr(instance, "interval_hours", None)
            )
            if interval_hours is None:
                raise serializers.ValidationError(
                    {"interval_hours": "This field is required for interval schedules."}
                )
            if interval_hours < 1 or interval_hours > 24:
                raise serializers.ValidationError(
                    {"interval_hours": "Interval must be between 1 and 24 hours."}
                )
            attrs["times"] = []
            attrs["weekdays"] = []
            attrs["interval_hours"] = interval_hours
        else:
            attrs["interval_hours"] = None
            if not times:
                raise serializers.ValidationError(
                    {"times": "At least one time is required."}
                )
            attrs["times"] = times
            if schedule_type == MedicationSchedule.ScheduleType.WEEKDAYS:
                if not weekdays:
                    raise serializers.ValidationError(
                        {"weekdays": "At least one weekday is required."}
                    )
                attrs["weekdays"] = weekdays
            else:
                attrs["weekdays"] = []

        attrs.setdefault(
            "anchor_time",
            getattr(instance, "anchor_time", time(0, 0)),
        )
        return attrs


class DoseMedicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Medication
        fields = (
            "id",
            "name",
            "strength",
            "dosage_form",
            "dose_amount",
            "dose_unit",
        )
        read_only_fields = fields


class DoseScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = MedicationSchedule
        fields = ("id", "schedule_type", "timezone")
        read_only_fields = fields


class DoseOccurrenceSerializer(serializers.ModelSerializer):
    medication = DoseMedicationSerializer(read_only=True)
    schedule = DoseScheduleSerializer(read_only=True)
    superseded_by = serializers.PrimaryKeyRelatedField(
        read_only=True, allow_null=True
    )
    superseded_by_id = serializers.PrimaryKeyRelatedField(
        source="superseded_by", read_only=True, allow_null=True
    )

    class Meta:
        model = DoseOccurrence
        fields = (
            "id",
            "medication",
            "schedule",
            "scheduled_at",
            "scheduled_date",
            "status",
            "alert_status",
            "taken_at",
            "skipped_at",
            "snoozed_until",
            "snooze_count",
            "cancelled_at",
            "cancellation_reason",
            "superseded_by",
            "superseded_by_id",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class DoseEventSerializer(serializers.ModelSerializer):
    actor_email = serializers.EmailField(source="actor.email", read_only=True)

    class Meta:
        model = DoseEvent
        fields = (
            "id",
            "event_type",
            "actor",
            "actor_email",
            "client_event_id",
            "client_recorded_at",
            "server_received_at",
            "source",
            "payload",
        )
        read_only_fields = fields


class DoseActionSource(models.TextChoices):
    PATIENT_APP = "patient_app", "Patient app"
    CAREGIVER_APP = "caregiver_app", "Caregiver app"
    API = "api", "API"


class DoseActionSerializer(serializers.Serializer):
    client_event_id = serializers.CharField(max_length=128)
    client_recorded_at = serializers.DateTimeField(
        required=False, allow_null=True
    )
    source = serializers.ChoiceField(
        choices=DoseActionSource.choices,
        default=DoseActionSource.PATIENT_APP,
    )


class DoseSnoozeSerializer(DoseActionSerializer):
    minutes = serializers.IntegerField(
        required=False, min_value=1, allow_null=True
    )

    def validate_minutes(self, value):
        if value is not None and value > settings.DOSE_SNOOZE_MAX_MINUTES:
            raise serializers.ValidationError(
                f"Snooze cannot exceed {settings.DOSE_SNOOZE_MAX_MINUTES} minutes."
            )
        return value
