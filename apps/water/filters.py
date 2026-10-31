import django_filters

from .models import WaterIntakeLog


class WaterIntakeFilter(django_filters.FilterSet):
    patient = django_filters.UUIDFilter(field_name="patient_id")
    date = django_filters.DateFilter(field_name="local_date", lookup_expr="exact")
    from_date = django_filters.DateFilter(
        field_name="local_date", lookup_expr="gte"
    )
    to_date = django_filters.DateFilter(field_name="local_date", lookup_expr="lte")

    class Meta:
        model = WaterIntakeLog
        fields = {
            "source": ["exact"],
            "consumed_at": ["gte", "lte"],
        }
