"""Dedicated Firebase Cloud Messaging service layer.

Credentials are loaded from environment-based Django settings. Tests replace
``send_push`` with a mock and never initialize Firebase.
"""

import json
import logging
from dataclasses import dataclass

from django.conf import settings
from firebase_admin import credentials, exceptions, messaging

logger = logging.getLogger("apps.notifications.fcm")

_firebase_app = None


class FCMNotConfigured(RuntimeError):
    """Raised when FCM is disabled or credentials are not available."""


@dataclass(frozen=True)
class FCMResult:
    token: str
    success: bool
    retryable: bool = False
    invalid_token: bool = False
    error_code: str = ""


def _credentials_from_settings():
    raw_json = getattr(settings, "FIREBASE_CREDENTIALS_JSON", "")
    path = getattr(settings, "FIREBASE_CREDENTIALS_PATH", "")
    if raw_json:
        try:
            return credentials.Certificate(json.loads(raw_json))
        except (ValueError, TypeError) as exc:
            raise FCMNotConfigured("FIREBASE_CREDENTIALS_JSON is invalid.") from exc
    if path:
        return credentials.Certificate(path)
    raise FCMNotConfigured("Firebase credentials are not configured.")


def _get_app():
    global _firebase_app
    if not getattr(settings, "FCM_ENABLED", False):
        raise FCMNotConfigured("FCM is disabled.")
    if _firebase_app is None:
        import firebase_admin

        _firebase_app = firebase_admin.initialize_app(
            _credentials_from_settings()
        )
    return _firebase_app


def _classify(exc):
    """Return ``(retryable, invalid_token, error_code)`` without leaking data."""
    name = type(exc).__name__
    if isinstance(exc, messaging.UnregisteredError):
        return False, True, name
    if isinstance(
        exc,
        (
            exceptions.InvalidArgumentError,
            exceptions.NotFoundError,
            exceptions.PermissionDeniedError,
            exceptions.UnauthenticatedError,
            exceptions.FailedPreconditionError,
        ),
    ):
        return False, True, name
    if isinstance(
        exc,
        (
            exceptions.UnavailableError,
            exceptions.InternalError,
            exceptions.DeadlineExceededError,
            exceptions.ResourceExhaustedError,
            exceptions.AbortedError,
            exceptions.UnknownError,
        ),
    ):
        return True, False, name
    return False, False, name


def send_push(tokens, title, body, data=None):
    """Send a generic push notification and return one result per token.

    The caller is responsible for keeping ``title``/``body`` free of medical
    details. Provider failures are classified so the outbox can decide between
    retrying and dead-lettering.
    """
    unique_tokens = list(dict.fromkeys(token for token in tokens if token))
    if not unique_tokens:
        return []

    message = messaging.MulticastMessage(
        tokens=unique_tokens,
        notification=messaging.Notification(title=title, body=body),
        data={str(key): str(value) for key, value in (data or {}).items()},
    )

    try:
        response = messaging.send_each_for_multicast(message, app=_get_app())
    except exceptions.FirebaseError as exc:
        retryable, invalid, code = _classify(exc)
        logger.warning("FCM request failed: %s", code)
        return [
            FCMResult(
                token=token,
                success=False,
                retryable=retryable,
                invalid_token=invalid,
                error_code=code,
            )
            for token in unique_tokens
        ]

    results = []
    for token, result in zip(unique_tokens, response.responses):
        if result.success:
            results.append(FCMResult(token=token, success=True))
            continue
        retryable, invalid, code = _classify(result.exception)
        logger.warning("FCM token delivery failed: %s", code)
        results.append(
            FCMResult(
                token=token,
                success=False,
                retryable=retryable,
                invalid_token=invalid,
                error_code=code,
            )
        )
    return results
