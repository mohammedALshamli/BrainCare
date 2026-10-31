from rest_framework.permissions import BasePermission


class IsRelationshipParticipant(BasePermission):
    """A patient or caregiver who is part of the relationship may read/revoke."""

    message = "You are not a participant in this care relationship."

    def has_object_permission(self, request, view, obj):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.pk in {obj.patient_id, obj.caregiver_id}
        )


class IsRelationshipPatient(BasePermission):
    """Only the patient can change relationship permissions."""

    message = "Only the patient can change relationship permissions."

    def has_object_permission(self, request, view, obj):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.pk == obj.patient_id
        )
