"""Device registration and reliable notification outbox services."""

import logging
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import CaregiverPatientLink

from .crypto import token_fingerprint
from .fcm import FCMNotConfigured, send_push
from .models import Device, NotificationOutbox

logger = logging.getLogger("apps.notifications")


def _setting(name, default):
    return getattr(settings, name, default)


def _max_attempts():
    return int(_setting("NOTIFICATION_MAX_ATTEMPTS", 5))


def _processing_timeout_seconds():
    return int(_setting("NOTIFICATION_PROCESSING_TIMEOUT_SECONDS", 300))


def backoff_seconds(attempts: int) -> int:
    base = int(_setting("NOTIFICATION_RETRY_BASE_SECONDS", 60))
    maximum = int(_setting("NOTIFICATION_RETRY_MAX_SECONDS", 3600))
    exponent = max(0, attempts - 1)
    return min(base * (2**exponent), maximum)


def _safe_enqueue_dispatch(outbox_id):
    try:
        from .tasks import dispatch_notification

        dispatch_notification.delay(str(outbox_id))
    except Exception:  # noqa: BLE001 - broker outages must not lose the outbox row
        logger.warning(
            "Could not enqueue notification dispatch for outbox %s; "
            "the periodic dispatcher will retry.",
            outbox_id,
            exc_info=True,
        )


def enqueue_notification(
    *,
    idempotency_key,
    recipient,
    patient,
    notification_type,
    payload=None,
    now=None,
):
    """Create one outbox row per stable idempotency key.

    Callers should invoke this inside the same database transaction as the
    state change that produced the notification.
    """
    now = now or timezone.now()
    defaults = {
        "recipient": recipient,
        "patient": patient,
        "notification_type": notification_type,
        "payload": payload or {},
        "status": NotificationOutbox.Status.PENDING,
        "attempts": 0,
        "max_attempts": _max_attempts(),
        "next_attempt_at": now,
    }
    try:
        with transaction.atomic():
            outbox, created = NotificationOutbox.objects.get_or_create(
                idempotency_key=idempotency_key,
                defaults=defaults,
            )
    except IntegrityError:
        outbox = NotificationOutbox.objects.get(idempotency_key=idempotency_key)
        created = False

    if created:
        transaction.on_commit(
            lambda outbox_id=outbox.pk: _safe_enqueue_dispatch(outbox_id)
        )
    return outbox, created


def enqueue_dose_overdue_notifications(occurrence, now=None):
    """Create one missed-dose notification per opted-in linked caregiver."""
    now = now or timezone.now()
    links = (
        CaregiverPatientLink.objects.filter(
            patient_id=occurrence.patient_id,
            is_active=True,
            can_view=True,
            notify_missed_doses=True,
            caregiver__is_active=True,
        )
        .select_related("caregiver")
        .order_by("caregiver_id")
    )

    created = []
    for link in links:
        outbox, was_created = enqueue_notification(
            idempotency_key=(
                f"dose-overdue:{occurrence.pk}:{link.caregiver_id}"
            ),
            recipient=link.caregiver,
            patient=occurrence.patient,
            notification_type=NotificationOutbox.NotificationType.DOSE_OVERDUE,
            payload={
                "title": "Medication reminder",
                "body": (
                    "A scheduled dose is overdue. "
                    "Please check in with your patient."
                ),
                "data": {
                    "type": "dose_overdue",
                    "occurrence_id": str(occurrence.pk),
                },
            },
            now=now,
        )
        if was_created:
            created.append(outbox)
    return created


def register_device(user, data, now=None):
    """Create or update a device, encrypting the FCM token at rest."""
    now = now or timezone.now()
    raw_token = (data.get("fcm_token") or "").strip()
    if len(raw_token) < 20 or len(raw_token) > 4096:
        raise ValueError("Invalid FCM token.")

    fingerprint = token_fingerprint(raw_token)
    identifier = (data.get("device_identifier") or "").strip()
    platform = data.get("platform") or Device.Platform.ANDROID
    metadata = data.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise ValueError("Device metadata must be an object.")

    with transaction.atomic():
        device = None
        if identifier:
            device = (
                Device.objects.select_for_update()
                .filter(user=user, device_identifier=identifier)
                .first()
            )
        if device is None:
            device = (
                Device.objects.select_for_update()
                .filter(token_fingerprint=fingerprint)
                .first()
            )

        if device is None:
            device = Device(user=user, platform=platform)
        else:
            duplicate = (
                Device.objects.select_for_update()
                .filter(token_fingerprint=fingerprint)
                .exclude(pk=device.pk)
                .first()
            )
            if duplicate is not None:
                # The token now belongs to this device row; the old row cannot
                # keep the same unique fingerprint.
                duplicate.delete()

        device.user = user
        if identifier:
            device.device_identifier = identifier
        device.platform = platform
        device.device_name = data.get("device_name", device.device_name or "")
        device.app_version = data.get("app_version", device.app_version or "")
        device.os_version = data.get("os_version", device.os_version or "")
        device.metadata = metadata
        device.set_fcm_token(raw_token)
        device.is_active = True
        device.last_seen_at = now
        device.save()
    return device


def deactivate_device(device, now=None):
    now = now or timezone.now()
    device.is_active = False
    device.last_seen_at = now
    device.save(update_fields=["is_active", "last_seen_at", "updated_at"])
    return device


def _finish_accepted(outbox_id, now):
    with transaction.atomic():
        outbox = NotificationOutbox.objects.select_for_update().get(pk=outbox_id)
        if outbox.status == NotificationOutbox.Status.ACCEPTED:
            return
        outbox.status = NotificationOutbox.Status.ACCEPTED
        outbox.accepted_at = now
        outbox.processing_started_at = None
        outbox.last_error = ""
        outbox.save(
            update_fields=[
                "status",
                "accepted_at",
                "processing_started_at",
                "last_error",
                "updated_at",
            ]
        )


def _finish_retry(outbox_id, reason, now):
    with transaction.atomic():
        outbox = NotificationOutbox.objects.select_for_update().get(pk=outbox_id)
        if outbox.status in (
            NotificationOutbox.Status.ACCEPTED,
            NotificationOutbox.Status.SUPPRESSED,
        ):
            return
        outbox.processing_started_at = None
        outbox.last_error = reason
        if outbox.attempts >= outbox.max_attempts:
            outbox.status = NotificationOutbox.Status.DEAD_LETTER
        else:
            outbox.status = NotificationOutbox.Status.PENDING
            outbox.next_attempt_at = now + timedelta(
                seconds=backoff_seconds(outbox.attempts)
            )
        outbox.save(
            update_fields=[
                "status",
                "next_attempt_at",
                "processing_started_at",
                "last_error",
                "updated_at",
            ]
        )


def _finish_dead(outbox_id, reason, now):
    with transaction.atomic():
        outbox = NotificationOutbox.objects.select_for_update().get(pk=outbox_id)
        if outbox.status == NotificationOutbox.Status.ACCEPTED:
            return
        outbox.status = NotificationOutbox.Status.DEAD_LETTER
        outbox.processing_started_at = None
        outbox.last_error = reason
        outbox.save(
            update_fields=[
                "status",
                "processing_started_at",
                "last_error",
                "updated_at",
            ]
        )


def _outbox_occurrence_id(outbox):
    payload = outbox.payload or {}
    data = payload.get("data") or {}
    occurrence_id = data.get("occurrence_id")
    if occurrence_id:
        return occurrence_id
    parts = (outbox.idempotency_key or "").split(":")
    if len(parts) >= 3 and parts[0] == "dose-overdue":
        return parts[1]
    return None


def _current_occurrence_status(outbox):
    occurrence_id = _outbox_occurrence_id(outbox)
    if not occurrence_id:
        return None
    from django.core.exceptions import ValidationError as DjangoValidationError

    from apps.medications.models import DoseOccurrence

    try:
        return (
            DoseOccurrence.objects.filter(pk=occurrence_id)
            .values_list("status", flat=True)
            .first()
        )
    except (TypeError, ValueError, DjangoValidationError):
        return None


def _suppress_locked(outbox, reason, now):
    outbox.status = NotificationOutbox.Status.SUPPRESSED
    outbox.suppression_reason = reason
    outbox.suppressed_at = now
    outbox.processing_started_at = None
    outbox.last_error = reason
    outbox.save(
        update_fields=[
            "status",
            "suppression_reason",
            "suppressed_at",
            "processing_started_at",
            "last_error",
            "updated_at",
        ]
    )


def dispatch_outbox(outbox_id, now=None):
    """Claim and dispatch one outbox row. Safe to call repeatedly."""
    now = now or timezone.now()
    timeout = timedelta(seconds=_processing_timeout_seconds())

    with transaction.atomic():
        outbox = (
            NotificationOutbox.objects.select_for_update()
            .filter(pk=outbox_id)
            .first()
        )
        if outbox is None:
            return "missing"
        if outbox.status == NotificationOutbox.Status.ACCEPTED:
            return "already_accepted"
        if outbox.status == NotificationOutbox.Status.DEAD_LETTER:
            return "dead_letter"
        if outbox.status == NotificationOutbox.Status.SUPPRESSED:
            return "already_suppressed"
        if (
            outbox.status == NotificationOutbox.Status.PROCESSING
            and outbox.processing_started_at
            and outbox.processing_started_at > now - timeout
        ):
            return "locked"
        if (
            outbox.status == NotificationOutbox.Status.PENDING
            and outbox.next_attempt_at > now
        ):
            return "not_due"

        # A dose may be confirmed or skipped after the overdue outbox row was
        # created but before this worker runs. Re-check the durable occurrence
        # state inside the same row lock before sending a false alert.
        if outbox.notification_type == NotificationOutbox.NotificationType.DOSE_OVERDUE:
            current_status = _current_occurrence_status(outbox)
            if current_status in {"taken", "skipped", "cancelled"}:
                _suppress_locked(
                    outbox, "stale_dose_already_resolved", now
                )
                return "suppressed_stale"

        if outbox.attempts >= outbox.max_attempts:
            outbox.status = NotificationOutbox.Status.DEAD_LETTER
            outbox.processing_started_at = None
            outbox.last_error = "max_attempts_reached"
            outbox.save(
                update_fields=[
                    "status",
                    "processing_started_at",
                    "last_error",
                    "updated_at",
                ]
            )
            return "max_attempts"

        outbox.status = NotificationOutbox.Status.PROCESSING
        outbox.attempts += 1
        outbox.processing_started_at = now
        outbox.save(
            update_fields=[
                "status",
                "attempts",
                "processing_started_at",
                "updated_at",
            ]
        )

    devices = list(
        Device.objects.filter(user_id=outbox.recipient_id, is_active=True)
    )
    token_map = {}
    for device in devices:
        try:
            token = device.get_fcm_token()
        except ValueError:
            device.is_active = False
            device.save(update_fields=["is_active", "updated_at"])
            continue
        token_map[token] = device

    if not token_map:
        _finish_dead(outbox.pk, "no_active_devices", now)
        return "no_active_devices"

    payload = outbox.payload or {}
    title = payload.get("title") or "BrainCare reminder"
    body = payload.get("body") or "You have a care reminder."
    data = payload.get("data") or {}

    try:
        results = send_push(list(token_map), title, body, data)
    except FCMNotConfigured:
        _finish_dead(outbox.pk, "fcm_not_configured", now)
        return "fcm_not_configured"
    except Exception:  # noqa: BLE001
        # Provider failures are retried without logging the payload.
        logger.warning(
            "FCM dispatch raised for outbox %s", outbox.pk, exc_info=True
        )
        _finish_retry(outbox.pk, "provider_exception", now)
        return "provider_exception"

    invalid_tokens = {
        result.token for result in results if result.invalid_token
    }
    if invalid_tokens:
        for token in invalid_tokens:
            device = token_map.get(token)
            if device is not None:
                device.is_active = False
                device.save(update_fields=["is_active", "updated_at"])

    if any(result.success for result in results):
        _finish_accepted(outbox.pk, now)
        return "accepted"

    if any(result.retryable for result in results):
        _finish_retry(outbox.pk, "provider_transient", now)
        return "retry"

    _finish_dead(outbox.pk, "provider_permanent", now)
    return "dead_letter"


def dispatch_pending_notifications(limit=100, now=None):
    """Recover stale workers and dispatch due outbox rows."""
    now = now or timezone.now()
    stale_before = now - timedelta(seconds=_processing_timeout_seconds())
    NotificationOutbox.objects.filter(
        status=NotificationOutbox.Status.PROCESSING,
        processing_started_at__lt=stale_before,
    ).update(
        status=NotificationOutbox.Status.PENDING,
        processing_started_at=None,
        next_attempt_at=now,
    )

    ids = list(
        NotificationOutbox.objects.filter(
            Q(
                status=NotificationOutbox.Status.PENDING,
                next_attempt_at__lte=now,
            )
            | Q(
                status=NotificationOutbox.Status.FAILED,
                next_attempt_at__lte=now,
            )
        )
        .order_by("next_attempt_at", "created_at")
        .values_list("pk", flat=True)[: int(limit)]
    )
    for outbox_id in ids:
        dispatch_outbox(outbox_id, now=now)
    return len(ids)
