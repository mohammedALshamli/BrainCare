from django.urls import path

from .views import SyncChangesView, SyncPushView

app_name = "sync"

urlpatterns = [
    path("changes/", SyncChangesView.as_view(), name="changes"),
    path("push/", SyncPushView.as_view(), name="push"),
]
