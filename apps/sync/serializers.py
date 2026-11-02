from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers

from .models import SyncChange


class SyncChangeSerializer(serializers.ModelSerializer):
    cursor = serializers.IntegerField(source="sequence", read_only=True)

    class Meta:
        model = SyncChange
        fields = (
            "cursor",
            "entity_type",
            "object_id",
            "operation",
            "data",
            "patient",
            "changed_at",
        )
        read_only_fields = fields


class SyncChangesQuerySerializer(serializers.Serializer):
    cursor = serializers.IntegerField(required=False, min_value=0, default=0)
    limit = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=200,
        default=getattr(settings, "SYNC_PAGE_SIZE", 50),
    )
    patient = serializers.IntegerField(required=False, min_value=1)


class SyncPushItemSerializer(serializers.Serializer):
    TYPE_DOSE_CONFIRM = "dose.confirm"
    TYPE_DOSE_SKIP = "dose.skip"
    TYPE_DOSE_SNOOZE = "dose.snooze"
    TYPE_WATER_INTAKE = "water.intake.create"

    TYPE_CHOICES = (
        (TYPE_DOSE_CONFIRM, "Confirm dose"),
        (TYPE_DOSE_SKIP, "Skip dose"),
        (TYPE_DOSE_SNOOZE, "Snooze dose"),
        (TYPE_WATER_INTAKE, "Create water intake"),
    )

    client_event_id = serializers.UUIDField()
    type = serializers.ChoiceField(choices=TYPE_CHOICES)
    occurrence_id = serializers.UUIDField(required=False)
    client_recorded_at = serializers.DateTimeField(
        required=False, allow_null=True
    )
    expected_version = serializers.IntegerField(
        required=False, min_value=0, allow_null=True
    )
    minutes = serializers.IntegerField(required=False, min_value=1)
    amount_ml = serializers.IntegerField(required=False, min_value=1, max_value=5000)
    consumed_at = serializers.DateTimeField(required=False, allow_null=True)
    source = serializers.CharField(
        required=False, allow_blank=True, max_length=20, default="manual"
    )
    notes = serializers.CharField(
        required=False, allow_blank=True, max_length=255, default=""
    )

    def validate(self, attrs):
        item_type = attrs["type"]
        if item_type in {
            self.TYPE_DOSE_CONFIRM,
            self.TYPE_DOSE_SKIP,
            self.TYPE_DOSE_SNOOZE,
        }:
            if not attrs.get("occurrence_id"):
                raise serializers.ValidationError(
                    {"occurrence_id": "This field is required for dose actions."}
                )
        if item_type == self.TYPE_DOSE_SNOOZE:
            if attrs.get("minutes") is None:
                raise serializers.ValidationError(
                    {"minutes": "This field is required when snoozing."}
                )
            max_minutes = getattr(settings, "DOSE_SNOOZE_MAX_MINUTES", 1440)
            if attrs["minutes"] > max_minutes:
                raise serializers.ValidationError(
                    {
                        "minutes": (
                            f"Snooze cannot exceed {max_minutes} minutes."
                        )
                    }
                )
        if item_type == self.TYPE_WATER_INTAKE:
            if attrs.get("amount_ml") is None:
                raise serializers.ValidationError(
                    {"amount_ml": "This field is required for water intake."}
                )
            allowed_sources = {"manual", "cup", "quick_add"}
            if attrs.get("source") and attrs["source"] not in allowed_sources:
                raise serializers.ValidationError(
                    {"source": "Unsupported water intake source."}
                )
        if attrs.get("client_recorded_at"):
            max_skew = getattr(settings, "SYNC_MAX_CLIENT_CLOCK_SKEW_SECONDS", 300)
            if attrs["client_recorded_at"] > timezone.now() + timedelta(
                seconds=max_skew
            ):
                raise serializers.ValidationError(
                    {
                        "client_recorded_at": (
                            "Client timestamp is too far in the future."
                        )
                    }
                )
        return attrs


class SyncPushSerializer(serializers.Serializer):
    batch_id = serializers.UUIDField(required=False)
    device_identifier = serializers.CharField(
        required=False, allow_blank=True, max_length=128
    )
    changes = SyncPushItemSerializer(many=True)

    def validate_changes(self, value):
        max_items = getattr(settings, "SYNC_MAX_BATCH_SIZE", 100)
        if not value:
            raise serializers.ValidationError("At least one change is required.")
        if len(value) > max_items:
            raise serializers.ValidationError(
                f"A batch may contain at most {max_items} changes."
            )
        return value
