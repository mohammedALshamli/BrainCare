import django_filters

from .models import DoseOccurrence, Medication, MedicationSchedule


class MedicationFilter(django_filters.FilterSet):
    patient = django_filters.UUIDFilter(field_name="patient_id")

    class Meta:
        model = Medication
        fields = {
            "is_active": ["exact"],
            "start_date": ["gte", "lte"],
            "end_date": ["gte", "lte"],
        }


class MedicationScheduleFilter(django_filters.FilterSet):
    class Meta:
        model = MedicationSchedule
        fields = {
            "is_active": ["exact"],
            "schedule_type": ["exact"],
        }


class DoseOccurrenceFilter(django_filters.FilterSet):
    patient = django_filters.UUIDFilter(field_name="patient_id")
    from_date = django_filters.DateFilter(
        field_name="scheduled_date", lookup_expr="gte"
    )
    to_date = django_filters.DateFilter(
        field_name="scheduled_date", lookup_expr="lte"
    )
    scheduled_date = django_filters.DateFilter(
        field_name="scheduled_date", lookup_expr="exact"
    )

    class Meta:
        model = DoseOccurrence
        fields = {
            "status": ["exact"],
            "medication": ["exact"],
            "schedule": ["exact"],
            "scheduled_at": ["gte", "lte"],
        }
