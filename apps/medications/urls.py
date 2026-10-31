from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    DoseOccurrenceViewSet,
    MedicationViewSet,
    ScheduleDeactivateView,
    ScheduleDetailView,
    ScheduleListCreateView,
)

router = DefaultRouter()
router.register("medications", MedicationViewSet, basename="medication")
router.register("doses", DoseOccurrenceViewSet, basename="dose")

urlpatterns = [
    path(
        "medications/<uuid:medication_id>/schedules/",
        ScheduleListCreateView.as_view(),
        name="medication-schedule-list",
    ),
    path(
        "schedules/<uuid:pk>/",
        ScheduleDetailView.as_view(),
        name="schedule-detail",
    ),
    path(
        "schedules/<uuid:pk>/deactivate/",
        ScheduleDeactivateView.as_view(),
        name="schedule-deactivate",
    ),
    path("", include(router.urls)),
]
