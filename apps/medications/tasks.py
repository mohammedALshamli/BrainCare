from celery import shared_task

from .models import MedicationSchedule
from .services import generate_occurrences
from .services import mark_overdue_doses as mark_overdue_doses_service


@shared_task
def generate_rolling_dose_occurrences():
    """Top up the future occurrence window for every active schedule."""
    total = 0
    queryset = (
        MedicationSchedule.objects.filter(
            is_active=True,
            medication__is_active=True,
        )
        .select_related("medication")
        .iterator()
    )
    for schedule in queryset:
        total += generate_occurrences(schedule)
    return total


@shared_task
def mark_overdue_doses():
    return mark_overdue_doses_service()
