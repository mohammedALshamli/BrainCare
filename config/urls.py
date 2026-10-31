from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", include("apps.core.urls")),
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("api/v1/pairing/", include("apps.accounts.pairing_urls")),
    path("api/v1/water/", include("apps.water.urls")),
    path("api/v1/", include("apps.notifications.urls")),
    path("api/v1/", include("apps.medications.urls")),
]
