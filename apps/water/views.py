from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.core.permissions import (
    IsPatient,
    accessible_patient_ids,
    can_read_patient,
)
from apps.core.serializers import ErrorResponseSerializer
from apps.sync import services as sync_services

from .filters import WaterIntakeFilter
from .models import WaterIntakeLog
from .serializers import (
    WaterIntakeLogSerializer,
    WaterReminderSettingsSerializer,
    WaterSummarySerializer,
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
            patient = User.objects.get(pk=raw_patient, is_patient=True)
        except (User.DoesNotExist, ValueError, TypeError) as exc:
            raise NotFound("Patient not found.") from exc
        if not can_read_patient(request.user, patient.pk):
            raise NotFound("Patient not found.")
        return patient

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

    @extend_schema(
        summary="Read water reminder settings",
        parameters=[
            OpenApiParameter(
                "patient",
                int,
                description="Linked patient id for caregiver access.",
            )
        ],
        responses={
            200: WaterReminderSettingsSerializer,
            400: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    def get(self, request):
        patient = resolve_patient(request)
        settings_obj = get_or_create_settings(patient)
        return Response(WaterReminderSettingsSerializer(settings_obj).data)

    @extend_schema(
        summary="Replace water reminder settings",
        request=WaterReminderSettingsSerializer,
        responses={
            200: WaterReminderSettingsSerializer,
            400: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
        },
    )
    def put(self, request):
        return self._update(request, partial=False)

    @extend_schema(
        summary="Update water reminder settings",
        request=WaterReminderSettingsSerializer,
        responses={
            200: WaterReminderSettingsSerializer,
            400: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
        },
    )
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
        settings_obj = serializer.save(patient=request.user)
        sync_services.record_water_settings(settings_obj, actor=request.user)
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

    @extend_schema(
        summary="Read a daily water summary",
        parameters=[
            OpenApiParameter(
                "patient",
                int,
                description="Linked patient id for caregiver access.",
            ),
            OpenApiParameter(
                "date", str, description="Local date in YYYY-MM-DD format."
            ),
        ],
        responses={
            200: WaterSummarySerializer,
            400: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
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
