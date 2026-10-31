from django.urls import path

from .views import (
    WaterIntakeDetailView,
    WaterIntakeListCreateView,
    WaterSettingsView,
    WaterSummaryView,
)

app_name = "water"

urlpatterns = [
    path("settings/", WaterSettingsView.as_view(), name="settings"),
    path(
        "intake/",
        WaterIntakeListCreateView.as_view(),
        name="intake-list",
    ),
    path(
        "intake/<uuid:pk>/",
        WaterIntakeDetailView.as_view(),
        name="intake-detail",
    ),
    path("summary/", WaterSummaryView.as_view(), name="summary"),
]
