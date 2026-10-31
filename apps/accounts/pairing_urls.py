from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .pairing_views import (
    PairingCodeGenerateView,
    PairingCodeRedeemView,
    RelationshipViewSet,
)

router = DefaultRouter()
router.register("relationships", RelationshipViewSet, basename="relationship")

app_name = "pairing"

urlpatterns = [
    path("codes/", PairingCodeGenerateView.as_view(), name="code-generate"),
    path("redeem/", PairingCodeRedeemView.as_view(), name="code-redeem"),
    path("", include(router.urls)),
]
