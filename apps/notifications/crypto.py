"""Encryption helpers for push tokens stored at rest."""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _fernet() -> Fernet:
    configured = getattr(settings, "FCM_TOKEN_ENCRYPTION_KEY", "")
    if configured:
        key = configured.encode("utf-8") if isinstance(configured, str) else configured
    else:
        digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
        key = base64.urlsafe_b64encode(digest)
    try:
        return Fernet(key)
    except (ValueError, TypeError) as exc:
        raise ImproperlyConfigured(
            "FCM_TOKEN_ENCRYPTION_KEY must be a valid Fernet key."
        ) from exc


def encrypt_token(raw_token: str) -> str:
    return _fernet().encrypt(raw_token.encode("utf-8")).decode("utf-8")


def decrypt_token(encrypted_token: str) -> str:
    try:
        return _fernet().decrypt(encrypted_token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError) as exc:
        raise ValueError("Stored push token could not be decrypted.") from exc


def token_fingerprint(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
