from rest_framework import serializers

from .models import Device
from .services import register_device


class DeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Device
        fields = (
            "id",
            "device_identifier",
            "platform",
            "token_preview",
            "device_name",
            "app_version",
            "os_version",
            "metadata",
            "is_active",
            "last_seen_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class DeviceRegistrationSerializer(serializers.Serializer):
    fcm_token = serializers.CharField(
        write_only=True, min_length=20, max_length=4096, trim_whitespace=True
    )
    platform = serializers.ChoiceField(choices=Device.Platform.choices)
    device_identifier = serializers.CharField(
        required=False, allow_blank=True, max_length=128
    )
    device_name = serializers.CharField(
        required=False, allow_blank=True, max_length=120
    )
    app_version = serializers.CharField(
        required=False, allow_blank=True, max_length=50
    )
    os_version = serializers.CharField(
        required=False, allow_blank=True, max_length=50
    )
    metadata = serializers.JSONField(required=False)

    def validate_metadata(self, value):
        if value is not None and not isinstance(value, dict):
            raise serializers.ValidationError("Metadata must be an object.")
        return value or {}

    def create(self, validated_data):
        try:
            return register_device(
                self.context["request"].user, validated_data
            )
        except ValueError as exc:
            raise serializers.ValidationError({"fcm_token": str(exc)})
