from rest_framework import serializers


class ErrorBodySerializer(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()
    details = serializers.JSONField(required=False)
    request_id = serializers.CharField(required=False)


class ErrorResponseSerializer(serializers.Serializer):
    error = ErrorBodySerializer()
