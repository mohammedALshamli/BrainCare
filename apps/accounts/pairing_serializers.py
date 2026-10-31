from rest_framework import serializers

from .models import CaregiverPatientLink


class PairingCodeCreateSerializer(serializers.Serializer):
    expires_in_minutes = serializers.IntegerField(
        required=False, min_value=1, max_value=60
    )


class PairingRedeemSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=64, trim_whitespace=True)


class CaregiverPatientLinkSerializer(serializers.ModelSerializer):
    patient_email = serializers.EmailField(source="patient.email", read_only=True)
    caregiver_email = serializers.EmailField(
        source="caregiver.email", read_only=True
    )

    class Meta:
        model = CaregiverPatientLink
        fields = (
            "id",
            "patient",
            "patient_email",
            "caregiver",
            "caregiver_email",
            "is_active",
            "can_view",
            "can_edit_medications",
            "notify_missed_doses",
            "consent_at",
            "revoked_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "patient",
            "patient_email",
            "caregiver",
            "caregiver_email",
            "is_active",
            "consent_at",
            "revoked_at",
            "created_at",
            "updated_at",
        )

    def validate(self, attrs):
        can_view = attrs.get("can_view", getattr(self.instance, "can_view", True))
        can_edit = attrs.get(
            "can_edit_medications",
            getattr(self.instance, "can_edit_medications", False),
        )
        if can_edit and not can_view:
            raise serializers.ValidationError(
                {
                    "can_edit_medications": (
                        "Medication editing requires view permission."
                    )
                }
            )
        return attrs
