from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import generics, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated, SAFE_METHODS
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import (
    IsOwnerOrLinkedCaregiver,
    IsPatient,
    IsPatientOwner,
    IsPatientOwnerOrCaregiverEditor,
    accessible_patient_ids,
    can_edit_patient,
)

from .filters import (
    DoseOccurrenceFilter,
    MedicationFilter,
    MedicationScheduleFilter,
)
from .models import DoseOccurrence, Medication, MedicationSchedule
from .serializers import (
    DoseActionSerializer,
    DoseEventSerializer,
    DoseOccurrenceSerializer,
    DoseSnoozeSerializer,
    MedicationScheduleSerializer,
    MedicationSerializer,
)
from .services import (
    confirm_dose,
    deactivate_medication,
    deactivate_schedule,
    generate_occurrences,
    regenerate_future,
    skip_dose,
    snooze_dose,
)

MATERIAL_SCHEDULE_FIELDS = (
    "schedule_type",
    "times",
    "weekdays",
    "interval_hours",
    "anchor_time",
    "timezone",
)


class MedicationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = MedicationSerializer
    filterset_class = MedicationFilter
    search_fields = ("name", "strength", "instructions")
    ordering_fields = ("name", "start_date", "created_at", "updated_at")
    ordering = ("-created_at",)

    def get_queryset(self):
        return (
            Medication.objects.filter(
                patient_id__in=accessible_patient_ids(self.request.user)
            )
            .select_related("patient", "created_by")
        )

    def get_permissions(self):
        if self.action == "create":
            return [IsAuthenticated(), IsPatient()]
        if self.action in ("update", "partial_update", "deactivate"):
            return [
                IsAuthenticated(),
                IsPatientOwnerOrCaregiverEditor(),
            ]
        return [IsAuthenticated(), IsOwnerOrLinkedCaregiver()]

    def perform_create(self, serializer):
        serializer.save(
            patient=self.request.user,
            created_by=self.request.user,
        )

    def perform_update(self, serializer):
        with transaction.atomic():
            instance = serializer.instance
            old_start = instance.start_date
            old_end = instance.end_date
            old_active = instance.is_active

            medication = serializer.save()
            dates_changed = (
                medication.start_date != old_start
                or medication.end_date != old_end
            )

            if old_active and not medication.is_active:
                deactivate_medication(medication)
            elif medication.is_active and (dates_changed or not old_active):
                for schedule in medication.schedules.filter(
                    is_active=True
                ).select_related("medication"):
                    regenerate_future(schedule, remove_future_pending=True)

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        medication = self.get_object()
        deactivate_medication(medication)
        medication.refresh_from_db()
        return Response(self.get_serializer(medication).data)


class ScheduleListCreateView(generics.ListCreateAPIView):
    serializer_class = MedicationScheduleSerializer
    filterset_class = MedicationScheduleFilter
    ordering_fields = ("created_at", "schedule_type", "is_active")
    ordering = ("-created_at",)

    def get_medication(self):
        queryset = Medication.objects.filter(
            pk=self.kwargs["medication_id"],
            patient_id__in=accessible_patient_ids(self.request.user),
        ).select_related("patient")
        return get_object_or_404(queryset)

    def get_queryset(self):
        medication = self.get_medication()
        return MedicationSchedule.objects.filter(
            medication=medication
        ).select_related("medication")

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsOwnerOrLinkedCaregiver()]

    def perform_create(self, serializer):
        medication = self.get_medication()
        if not can_edit_patient(
            self.request.user, medication.patient_id
        ):
            raise PermissionDenied(
                "You do not have permission to edit this medication."
            )
        if not medication.is_active:
            raise ValidationError(
                {"medication": "Cannot add a schedule to an inactive medication."}
            )

        with transaction.atomic():
            schedule = serializer.save(
                medication=medication,
                created_by=self.request.user,
            )
            generate_occurrences(schedule)


class ScheduleDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = MedicationScheduleSerializer

    def get_queryset(self):
        return MedicationSchedule.objects.filter(
            medication__patient_id__in=accessible_patient_ids(
                self.request.user
            )
        ).select_related("medication")

    def get_permissions(self):
        if self.request.method in SAFE_METHODS:
            return [IsAuthenticated(), IsOwnerOrLinkedCaregiver()]
        return [
            IsAuthenticated(),
            IsPatientOwnerOrCaregiverEditor(),
        ]

    def perform_update(self, serializer):
        with transaction.atomic():
            schedule = serializer.instance
            before = {
                field: getattr(schedule, field)
                for field in MATERIAL_SCHEDULE_FIELDS
            }
            was_active = schedule.is_active

            updated = serializer.save()
            material_change = any(
                before[field] != getattr(updated, field)
                for field in MATERIAL_SCHEDULE_FIELDS
            )

            if not updated.is_active:
                deactivate_schedule(updated)
            elif material_change or not was_active:
                regenerate_future(updated, remove_future_pending=True)
            else:
                generate_occurrences(updated)


class ScheduleDeactivateView(APIView):
    permission_classes = [
        IsAuthenticated,
        IsPatientOwnerOrCaregiverEditor,
    ]

    def post(self, request, pk):
        queryset = MedicationSchedule.objects.filter(
            medication__patient_id__in=accessible_patient_ids(request.user)
        ).select_related("medication")
        schedule = get_object_or_404(queryset, pk=pk)
        self.check_object_permissions(request, schedule)

        deactivate_schedule(schedule)
        schedule.refresh_from_db()
        return Response(MedicationScheduleSerializer(schedule).data)


class DoseOccurrenceViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = DoseOccurrenceSerializer
    filterset_class = DoseOccurrenceFilter
    search_fields = ("medication__name",)
    ordering_fields = ("scheduled_at", "status", "created_at")
    ordering = ("-scheduled_at",)

    def get_queryset(self):
        return DoseOccurrence.objects.filter(
            patient_id__in=accessible_patient_ids(self.request.user)
        ).select_related("medication", "schedule", "patient")

    def get_permissions(self):
        if self.action in ("confirm", "skip", "snooze"):
            return [IsAuthenticated(), IsPatientOwner()]
        return [IsAuthenticated(), IsOwnerOrLinkedCaregiver()]

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        occurrence = self.get_object()
        serializer = DoseActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        occurrence, _ = confirm_dose(
            occurrence,
            actor=request.user,
            client_event_id=serializer.validated_data["client_event_id"],
            client_recorded_at=serializer.validated_data.get(
                "client_recorded_at"
            ),
            source=serializer.validated_data["source"],
        )
        return Response(self.get_serializer(occurrence).data)

    @action(detail=True, methods=["post"])
    def skip(self, request, pk=None):
        occurrence = self.get_object()
        serializer = DoseActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        occurrence, _ = skip_dose(
            occurrence,
            actor=request.user,
            client_event_id=serializer.validated_data["client_event_id"],
            client_recorded_at=serializer.validated_data.get(
                "client_recorded_at"
            ),
            source=serializer.validated_data["source"],
        )
        return Response(self.get_serializer(occurrence).data)

    @action(detail=True, methods=["post"])
    def snooze(self, request, pk=None):
        occurrence = self.get_object()
        serializer = DoseSnoozeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        occurrence, _ = snooze_dose(
            occurrence,
            actor=request.user,
            client_event_id=serializer.validated_data["client_event_id"],
            minutes=serializer.validated_data.get("minutes"),
            client_recorded_at=serializer.validated_data.get(
                "client_recorded_at"
            ),
            source=serializer.validated_data["source"],
        )
        return Response(self.get_serializer(occurrence).data)

    @action(detail=True, methods=["get"])
    def events(self, request, pk=None):
        occurrence = self.get_object()
        queryset = occurrence.events.select_related("actor").order_by(
            "server_received_at", "id"
        )
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = DoseEventSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        return Response(DoseEventSerializer(queryset, many=True).data)
