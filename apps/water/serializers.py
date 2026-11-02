from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone
from rest_framework import serializers

from .models import WaterIntakeLog, WaterReminderSettings
from .services import record_intake


class WaterReminderSettingsSerializer(serializers.ModelSerializer):
    patient = serializers.PrimaryKeyRelatedField(read_only=True)
    interval_minutes = serializers.IntegerField(
        required=False, min_value=15, max_value=720
    )
    daily_goal_ml = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=100,
        max_value=20000,
    )
    cup_size_ml = serializers.IntegerField(
        required=False, min_value=50, max_value=2000
    )

    class Meta:
        model = WaterReminderSettings
        fields = (
            "id",
            "patient",
            "enabled",
            "start_time",
            "end_time",
            "interval_minutes",
            "daily_goal_ml",
            "cup_size_ml",
            "timezone",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "patient", "created_at", "updated_at")

    def validate_timezone(self, value):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise serializers.ValidationError("Unknown IANA timezone.") from exc
        return value

    def validate(self, attrs):
        instance = self.instance
        start = attrs.get("start_time", getattr(instance, "start_time", None))
        end = attrs.get("end_time", getattr(instance, "end_time", None))
        if start and end and start >= end:
            raise serializers.ValidationError(
                {"end_time": "End time must be after the start time."}
            )
        return attrs


class WaterSummarySerializer(serializers.Serializer):
    date = serializers.DateField()
    total_ml = serializers.IntegerField()
    goal_ml = serializers.IntegerField(allow_null=True)
    remaining_ml = serializers.IntegerField(allow_null=True)
    progress_percentage = serializers.IntegerField(allow_null=True)
    log_count = serializers.IntegerField()
    goal_reached = serializers.BooleanField(allow_null=True)


class WaterIntakeLogSerializer(serializers.ModelSerializer):
    patient = serializers.PrimaryKeyRelatedField(read_only=True)
    created_by = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = WaterIntakeLog
        fields = (
            "id",
            "patient",
            "client_event_id",
            "amount_ml",
            "consumed_at",
            "local_date",
            "source",
            "notes",
            "created_by",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "patient",
            "client_event_id",
            "local_date",
            "created_by",
            "created_at",
            "updated_at",
        )
        extra_kwargs = {
            "amount_ml": {"min_value": 1, "max_value": 5000},
            "consumed_at": {"required": False, "default": timezone.now},
        }

    def create(self, validated_data):
        request = self.context.get("request")
        user = request.user
        return record_intake(
            patient=user,
            amount_ml=validated_data["amount_ml"],
            consumed_at=validated_data.get("consumed_at"),
            source=validated_data.get(
                "source", WaterIntakeLog.Source.MANUAL
            ),
            notes=validated_data.get("notes", ""),
            created_by=user,
        )
