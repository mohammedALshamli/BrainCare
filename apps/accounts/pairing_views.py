from django.db.models import Q
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsCaregiver, IsPatient

from .models import CaregiverPatientLink
from .pairing import (
    generate_pairing_code,
    pairing_qr_payload,
    redeem_pairing_code,
    revoke_relationship,
)
from .pairing_serializers import (
    CaregiverPatientLinkSerializer,
    PairingCodeCreateSerializer,
    PairingRedeemSerializer,
)
from .permissions import IsRelationshipParticipant, IsRelationshipPatient


class PairingCodeGenerateView(APIView):
    permission_classes = [IsAuthenticated, IsPatient]
    throttle_scope = "pairing_generate"

    def post(self, request):
        serializer = PairingCodeCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pairing_code, raw_code = generate_pairing_code(
            request.user,
            expires_in_minutes=serializer.validated_data.get(
                "expires_in_minutes"
            ),
        )
        return Response(
            {
                "id": str(pairing_code.pk),
                "code": raw_code,
                "qr_payload": pairing_qr_payload(raw_code),
                "expires_at": pairing_code.expires_at,
            },
            status=status.HTTP_201_CREATED,
        )


class PairingCodeRedeemView(APIView):
    permission_classes = [IsAuthenticated, IsCaregiver]
    throttle_scope = "pairing_redeem"

    def post(self, request):
        serializer = PairingRedeemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        link = redeem_pairing_code(
            serializer.validated_data["code"], request.user
        )
        return Response(
            CaregiverPatientLinkSerializer(link).data,
            status=status.HTTP_201_CREATED,
        )


class RelationshipViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = CaregiverPatientLinkSerializer

    def get_queryset(self):
        user = self.request.user
        return CaregiverPatientLink.objects.filter(
            Q(patient=user) | Q(caregiver=user)
        ).select_related("patient", "caregiver")

    def get_permissions(self):
        if self.action in ("update", "partial_update"):
            return [IsAuthenticated(), IsRelationshipPatient()]
        if self.action == "revoke":
            return [IsAuthenticated(), IsRelationshipParticipant()]
        return [IsAuthenticated(), IsRelationshipParticipant()]

    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        link = self.get_object()
        link = revoke_relationship(link)
        return Response(self.get_serializer(link).data)
