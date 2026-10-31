from rest_framework import mixins, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Device
from .serializers import DeviceRegistrationSerializer, DeviceSerializer
from .services import deactivate_device, register_device


class DeviceViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated]
    serializer_class = DeviceSerializer

    def get_queryset(self):
        return Device.objects.filter(user=self.request.user)

    def get_serializer_class(self):
        if self.action == "create":
            return DeviceRegistrationSerializer
        return DeviceSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        device = register_device(request.user, serializer.validated_data)
        return Response(
            DeviceSerializer(device).data,
            status=status.HTTP_201_CREATED,
        )

    def perform_destroy(self, instance):
        deactivate_device(instance)
