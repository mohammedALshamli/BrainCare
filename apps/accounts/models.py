import uuid

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    """Application user.

    A user may act as a patient, a caregiver, or both. Roles are deliberately
    represented as independent flags instead of a single mutually exclusive
    choice so that one account can hold more than one role.
    """

    email = models.EmailField("email address", unique=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    is_patient = models.BooleanField(default=False)
    is_caregiver = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        ordering = ["email"]
        verbose_name = "user"
        verbose_name_plural = "users"
        constraints = [
            models.UniqueConstraint(
                Lower("email"), name="accounts_user_email_ci_unique"
            )
        ]

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    @property
    def roles(self) -> list[str]:
        roles = []
        if self.is_patient:
            roles.append("patient")
        if self.is_caregiver:
            roles.append("caregiver")
        return roles

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def get_full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def get_short_name(self) -> str:
        return self.first_name


class CaregiverPatientLink(models.Model):
    """An authorized caregiver relationship.

    A link is created when a caregiver redeems a patient's single-use pairing
    code. Links are never hard deleted by the API; revoking sets ``is_active``
    to False and records ``revoked_at``. Access checks always read the database
    so revocation takes effect immediately, including for existing JWTs.
    """

    caregiver = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="patient_links",
    )
    patient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="caregiver_links",
    )
    is_active = models.BooleanField(default=True)
    can_view = models.BooleanField(default=True)
    can_edit_medications = models.BooleanField(default=False)
    can_confirm_doses = models.BooleanField(default=False)
    notify_missed_doses = models.BooleanField(default=True)
    consent_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["caregiver", "patient"],
                condition=models.Q(is_active=True),
                name="unique_active_caregiver_patient_link",
            ),
            models.CheckConstraint(
                condition=~models.Q(caregiver=models.F("patient")),
                name="caregiver_and_patient_must_differ",
            ),
            models.CheckConstraint(
                condition=models.Q(can_edit_medications=False)
                | models.Q(can_view=True),
                name="edit_permission_requires_view",
            ),
            models.CheckConstraint(
                condition=models.Q(can_confirm_doses=False)
                | models.Q(can_view=True),
                name="confirm_permission_requires_view",
            ),
        ]
        indexes = [
            models.Index(
                fields=["patient", "is_active"],
                name="link_patient_active_idx",
            ),
            models.Index(
                fields=["caregiver", "is_active"],
                name="link_caregiver_active_idx",
            ),
        ]

    def __str__(self):
        return f"{self.caregiver_id} -> {self.patient_id}"


class PairingCode(models.Model):
    """A short-lived, single-use patient-caregiver pairing code.

    Only an HMAC-SHA256 digest of the normalized code is persisted. The raw
    code is returned exactly once when it is generated and is never stored.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="pairing_codes",
    )
    code_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    used_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="redeemed_pairing_codes",
    )
    invalidated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["patient", "expires_at"],
                name="pairing_patient_expiry_idx",
            ),
            models.Index(
                fields=["expires_at", "used_at"],
                name="pairing_expiry_used_idx",
            ),
        ]

    def __str__(self):
        return f"pairing code for {self.patient_id}"

    def is_expired(self, now=None) -> bool:
        now = now or timezone.now()
        return self.expires_at <= now

    def is_usable(self, now=None) -> bool:
        return (
            self.used_at is None
            and self.invalidated_at is None
            and not self.is_expired(now)
        )
