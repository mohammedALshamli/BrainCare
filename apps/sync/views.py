from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.serializers import ErrorResponseSerializer

from .docs_serializers import (
    SyncChangesResponseSerializer,
    SyncPushResponseSerializer,
)
from .serializers import (
    SyncChangesQuerySerializer,
    SyncPushSerializer,
)
from .services import apply_sync_batch, get_changes


class SyncChangesView(APIView):
    """Paginated, cursor-based download of changed records."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "sync"

    @extend_schema(
        summary="Download changed records",
        description=(
            "Cursor-based change feed. The cursor is a monotonic server "
            "sequence, not a timestamp. Apply changes in order and persist "
            "next_cursor transactionally."
        ),
        parameters=[
            OpenApiParameter("cursor", int, description="Last applied cursor."),
            OpenApiParameter("limit", int, description="1-200 records."),
            OpenApiParameter(
                "patient",
                int,
                description="Linked patient id for caregiver access.",
            ),
        ],
        responses={
            200: SyncChangesResponseSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    def get(self, request):
        query = SyncChangesQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        payload = get_changes(
            request.user,
            cursor=query.validated_data["cursor"],
            limit=query.validated_data["limit"],
            patient_id=query.validated_data.get("patient"),
        )
        return Response(payload)


class SyncPushView(APIView):
    """Apply client-generated offline events with per-item results."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "sync"

    @extend_schema(
        summary="Push offline events",
        description=(
            "Apply client-generated UUID events. Each item receives its own "
            "status. Retrying the same client_event_id is idempotent."
        ),
        request=SyncPushSerializer,
        responses={
            200: SyncPushResponseSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
        },
    )
    def post(self, request):
        serializer = SyncPushSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = apply_sync_batch(
            serializer.validated_data["changes"], request.user
        )
        payload["batch_id"] = (
            str(serializer.validated_data["batch_id"])
            if serializer.validated_data.get("batch_id")
            else None
        )
        return Response(payload, status=status.HTTP_200_OK)
