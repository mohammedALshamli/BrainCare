from rest_framework import serializers

from .serializers import SyncChangeSerializer


class SyncChangesResponseSerializer(serializers.Serializer):
    changes = SyncChangeSerializer(many=True)
    next_cursor = serializers.IntegerField()
    has_more = serializers.BooleanField()
    server_time = serializers.DateTimeField()


class SyncPushResultSerializer(serializers.Serializer):
    client_event_id = serializers.UUIDField()
    type = serializers.CharField()
    status = serializers.ChoiceField(
        choices=(
            "applied",
            "duplicate",
            "conflict",
            "not_found",
            "forbidden",
            "error",
        )
    )
    code = serializers.CharField(required=False)
    message = serializers.CharField(required=False)
    occurrence_id = serializers.UUIDField(required=False)
    event_id = serializers.UUIDField(required=False)
    water_intake_id = serializers.UUIDField(required=False)
    server = serializers.JSONField(required=False)


class SyncPushCountsSerializer(serializers.Serializer):
    applied = serializers.IntegerField()
    duplicate = serializers.IntegerField()
    conflict = serializers.IntegerField()
    error = serializers.IntegerField()


class SyncPushResponseSerializer(serializers.Serializer):
    batch_id = serializers.UUIDField(required=False, allow_null=True)
    results = SyncPushResultSerializer(many=True)
    counts = SyncPushCountsSerializer()
