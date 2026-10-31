import uuid

from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.core.permissions import (
    IsPatient,
    accessible_patient_ids,
    can_read_patient,
)

from .filters import WaterIntakeFilter
from .models import WaterIntakeLog
from .serializers import (
    WaterIntakeLogSerializer,
    WaterReminderSettingsSerializer,
)
from .services import (
    daily_summary,
    get_or_create_settings,
    local_date_for,
)


def resolve_patient(request, required=True):
    raw_patient = request.query_params.get("patient")
    if raw_patient:
        try:
            patient_id = uuid.UUID(str(raw_patient))
        except (ValueError, TypeError) as exc:
            raise ValidationError({"patient": "Invalid patient id."}) from exc
        if not can_read_patient(request.user, patient_id):
            raise NotFound("Patient not found.")
        return get_object_or_404(User, pk=patient_id, is_patient=True)

    if request.user.is_patient:
        return request.user
    if required:
        raise ValidationError(
            {"patient": "Provide a patient id for caregiver access."}
        )
    return None


class WaterSettingsView(APIView):
    def get_permissions(self):
        if self.request.method in ("PUT", "PATCH"):
            return [IsAuthenticated(), IsPatient()]
        return [IsAuthenticated()]

    def get(self, request):
        patient = resolve_patient(request)
        settings_obj = get_or_create_settings(patient)
        return Response(WaterReminderSettingsSerializer(settings_obj).data)

    def put(self, request):
        return self._update(request, partial=False)

    def patch(self, request):
        return self._update(request, partial=True)

    def _update(self, request, partial):
        settings_obj = get_or_create_settings(request.user)
        serializer = WaterReminderSettingsSerializer(
            settings_obj,
            data=request.data,
            partial=partial,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(patient=request.user)
        return Response(serializer.data)


class WaterIntakeListCreateView(generics.ListCreateAPIView):
    serializer_class = WaterIntakeLogSerializer
    filterset_class = WaterIntakeFilter
    search_fields = ("notes",)
    ordering_fields = ("consumed_at", "local_date", "amount_ml", "created_at")
    ordering = ("-consumed_at",)

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), IsPatient()]
        return [IsAuthenticated()]

    def get_queryset(self):
        return WaterIntakeLog.objects.filter(
            patient_id__in=accessible_patient_ids(self.request.user)
        ).select_related("patient", "created_by")


class WaterIntakeDetailView(generics.RetrieveAPIView):
    serializer_class = WaterIntakeLogSerializer

    def get_queryset(self):
        return WaterIntakeLog.objects.filter(
            patient_id__in=accessible_patient_ids(self.request.user)
        ).select_related("patient", "created_by")


class WaterSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        patient = resolve_patient(request)
        settings_obj = get_or_create_settings(patient)
        raw_date = request.query_params.get("date")
        if raw_date:
            from datetime import date

            try:
                day = date.fromisoformat(raw_date)
            except ValueError as exc:
                raise ValidationError(
                    {"date": "Use YYYY-MM-DD format."}
                ) from exc
        else:
            day = local_date_for(settings_obj)
        return Response(daily_summary(patient, day, settings_obj))
