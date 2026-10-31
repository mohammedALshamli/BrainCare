"""Secure patient-caregiver pairing.

Pairing codes are short-lived, single-use secrets. Only an HMAC-SHA256 digest
of the normalized code is stored; the raw code is returned once to the patient
and can be shown as a QR code by the client.

Brute-force protection is layered:

* DRF scoped throttles on code generation and redemption.
* A cache-backed failed-attempt counter per caregiver. Once the configured
  threshold is reached the caregiver is locked out for a cooling-off window.
* Per-code state (expiry, used, invalidated) is checked under a row lock and
  the code is consumed with a conditional update.
"""

import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, Throttled, ValidationError

from apps.core.exceptions import Conflict

from .models import CaregiverPatientLink, PairingCode

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _setting(name, default):
    return getattr(settings, name, default)


def normalize_pairing_code(value: str) -> str:
    if value is None:
        return ""
    return "".join(ch for ch in str(value).upper() if ch.isalnum())


def hash_pairing_code(value: str) -> str:
    pepper = _setting("PAIRING_CODE_PEPPER", settings.SECRET_KEY)
    normalized = normalize_pairing_code(value)
    return hmac.new(
        str(pepper).encode("utf-8"),
        normalized.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _failure_cache_key(caregiver) -> str:
    return f"pairing:failed:{caregiver.pk}"


def _failed_attempt_limit():
    return int(_setting("PAIRING_CODE_MAX_FAILED_ATTEMPTS", 5))


def _failure_window_seconds():
    return int(_setting("PAIRING_CODE_FAILED_ATTEMPT_WINDOW_SECONDS", 900))


def _assert_not_locked(caregiver):
    attempts = cache.get(_failure_cache_key(caregiver), 0) or 0
    if attempts >= _failed_attempt_limit():
        raise Throttled(wait=_failure_window_seconds())


def _record_failure(caregiver):
    key = _failure_cache_key(caregiver)
    window = _failure_window_seconds()
    cache.add(key, 0, timeout=window)
    try:
        attempts = cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=window)
        attempts = 1
    if attempts >= _failed_attempt_limit():
        raise Throttled(wait=window)


def _clear_failures(caregiver):
    cache.delete(_failure_cache_key(caregiver))


def _generate_raw_code() -> str:
    length = int(_setting("PAIRING_CODE_LENGTH", 10))
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(length))


def generate_pairing_code(patient, expires_in_minutes=None, now=None):
    """Create a pairing code and return ``(pairing_code, raw_code)``."""
    now = now or timezone.now()
    default_minutes = int(_setting("PAIRING_CODE_TTL_MINUTES", 10))
    minutes = default_minutes if expires_in_minutes is None else int(expires_in_minutes)
    if minutes < 1 or minutes > 60:
        raise ValidationError(
            {"expires_in_minutes": "Expiry must be between 1 and 60 minutes."}
        )

    expires_at = now + timedelta(minutes=minutes)
    for _ in range(5):
        raw_code = _generate_raw_code()
        try:
            with transaction.atomic():
                pairing_code = PairingCode.objects.create(
                    patient=patient,
                    code_hash=hash_pairing_code(raw_code),
                    expires_at=expires_at,
                )
            return pairing_code, raw_code
        except IntegrityError:
            continue
    raise Conflict("Could not allocate a unique pairing code. Try again.")


def pairing_qr_payload(raw_code: str) -> str:
    return f"braincare://pair?code={raw_code}"


def redeem_pairing_code(raw_code, caregiver, now=None):
    """Consume a pairing code and create/reactivate a care relationship."""
    if not caregiver or not getattr(caregiver, "is_caregiver", False):
        raise PermissionDenied("Only caregivers can redeem pairing codes.")

    now = now or timezone.now()
    _assert_not_locked(caregiver)

    normalized = normalize_pairing_code(raw_code)
    if not normalized:
        _record_failure(caregiver)
        raise ValidationError({"code": "Invalid or expired pairing code."})

    with transaction.atomic():
        pairing_code = (
            PairingCode.objects.select_for_update()
            .select_related("patient")
            .filter(code_hash=hash_pairing_code(normalized))
            .first()
        )
        if pairing_code is None or not pairing_code.is_usable(now):
            _record_failure(caregiver)
            raise ValidationError({"code": "Invalid or expired pairing code."})

        patient = pairing_code.patient
        if patient.pk == caregiver.pk or not patient.is_active:
            _record_failure(caregiver)
            raise ValidationError({"code": "Invalid or expired pairing code."})

        link = (
            CaregiverPatientLink.objects.select_for_update()
            .filter(caregiver=caregiver, patient=patient)
            .first()
        )
        if link is not None and link.is_active:
            raise Conflict("An active care relationship already exists.")

        consumed = PairingCode.objects.filter(
            pk=pairing_code.pk,
            used_at__isnull=True,
            invalidated_at__isnull=True,
            expires_at__gt=now,
        ).update(used_at=now, used_by=caregiver)
        if not consumed:
            _record_failure(caregiver)
            raise ValidationError({"code": "Invalid or expired pairing code."})

        if link is None:
            link = CaregiverPatientLink.objects.create(
                caregiver=caregiver,
                patient=patient,
                is_active=True,
                can_view=True,
                can_edit_medications=False,
                notify_missed_doses=True,
                consent_at=now,
            )
        else:
            link.is_active = True
            link.can_view = True
            link.can_edit_medications = False
            link.notify_missed_doses = True
            link.consent_at = now
            link.revoked_at = None
            link.save(
                update_fields=[
                    "is_active",
                    "can_view",
                    "can_edit_medications",
                    "notify_missed_doses",
                    "consent_at",
                    "revoked_at",
                    "updated_at",
                ]
            )

    _clear_failures(caregiver)
    return link


def revoke_relationship(link, now=None):
    """Revoke a relationship immediately without deleting its history."""
    now = now or timezone.now()
    with transaction.atomic():
        locked = CaregiverPatientLink.objects.select_for_update().get(pk=link.pk)
        if locked.is_active:
            locked.is_active = False
            locked.revoked_at = now
            locked.save(update_fields=["is_active", "revoked_at", "updated_at"])
        return locked


def cleanup_pairing_codes(now=None, retention_days=None) -> int:
    """Delete pairing codes that can no longer be used and are past retention."""
    now = now or timezone.now()
    days = (
        int(_setting("PAIRING_CODE_RETENTION_DAYS", 7))
        if retention_days is None
        else int(retention_days)
    )
    cutoff = now - timedelta(days=days)
    deleted, _ = PairingCode.objects.filter(
        Q(expires_at__lt=cutoff)
        | Q(used_at__lt=cutoff)
        | Q(invalidated_at__lt=cutoff)
    ).delete()
    return deleted
