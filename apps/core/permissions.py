from rest_framework.permissions import BasePermission, SAFE_METHODS

from apps.accounts.models import CaregiverPatientLink


def accessible_patient_ids(user):
    """Return ids of patients the user may read.

    A patient always has access to their own records. A caregiver gets access
    only through an active link with ``can_view=True``. Revocation and
    permission changes are checked against the database on every request.
    """
    if not user or not user.is_authenticated:
        return []

    patient_ids = []
    if user.is_patient:
        patient_ids.append(user.pk)

    patient_ids.extend(
        CaregiverPatientLink.objects.filter(
            caregiver=user,
            is_active=True,
            can_view=True,
            patient__is_active=True,
        ).values_list("patient_id", flat=True)
    )
    return list(dict.fromkeys(patient_ids))


def editable_patient_ids(user):
    """Return ids of patients whose medication data the user may edit."""
    if not user or not user.is_authenticated:
        return []

    patient_ids = []
    if user.is_patient:
        patient_ids.append(user.pk)

    patient_ids.extend(
        CaregiverPatientLink.objects.filter(
            caregiver=user,
            is_active=True,
            can_view=True,
            can_edit_medications=True,
            patient__is_active=True,
        ).values_list("patient_id", flat=True)
    )
    return list(dict.fromkeys(patient_ids))


def can_read_patient(user, patient_id) -> bool:
    return patient_id in set(accessible_patient_ids(user))


def can_edit_patient(user, patient_id) -> bool:
    return patient_id in set(editable_patient_ids(user))


def is_linked_caregiver(user, patient_id, require_edit=False) -> bool:
    if not user or not user.is_authenticated or not user.is_caregiver:
        return False
    queryset = CaregiverPatientLink.objects.filter(
        caregiver=user,
        patient_id=patient_id,
        is_active=True,
        can_view=True,
        patient__is_active=True,
    )
    if require_edit:
        queryset = queryset.filter(can_edit_medications=True)
    return queryset.exists()


class IsPatient(BasePermission):
    """Only users holding the patient role may create patient-owned data."""

    message = "Only patients can perform this action."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_patient
        )


class IsCaregiver(BasePermission):
    """Only users holding the caregiver role may redeem pairing codes."""

    message = "Only caregivers can perform this action."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_caregiver
        )


class IsOwnerOrLinkedCaregiver(BasePermission):
    """Read access for the owner or an actively linked caregiver.

    Write access is restricted to the patient who owns the object. Use
    ``IsPatientOwnerOrCaregiverEditor`` on endpoints where a caregiver with
    explicit edit permission may write.
    """

    message = "You do not have permission to access this patient's data."

    def has_object_permission(self, request, view, obj):
        patient_id = getattr(obj, "patient_id", None)
        if patient_id is None:
            return False

        if request.user.is_patient and patient_id == request.user.pk:
            return True

        if request.method in SAFE_METHODS:
            return is_linked_caregiver(request.user, patient_id)

        return False


class IsPatientOwner(BasePermission):
    """Object access restricted to the patient who owns it."""

    message = "Only the patient who owns this data can perform this action."

    def has_object_permission(self, request, view, obj):
        patient_id = getattr(obj, "patient_id", None)
        return bool(
            request.user.is_patient
            and patient_id is not None
            and patient_id == request.user.pk
        )


class IsPatientOwnerOrCaregiverEditor(BasePermission):
    """Allow the owning patient or a caregiver with explicit edit rights."""

    message = "You do not have permission to edit this patient's data."

    def has_object_permission(self, request, view, obj):
        patient_id = getattr(obj, "patient_id", None)
        if patient_id is None:
            return False
        return can_edit_patient(request.user, patient_id)
