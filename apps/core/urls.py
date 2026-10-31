from django.urls import path

from .views import liveness, readiness

app_name = "core"

urlpatterns = [
    path("", readiness, name="readiness"),
    path("live/", liveness, name="liveness"),
    path("ready/", readiness, name="readiness"),
]
