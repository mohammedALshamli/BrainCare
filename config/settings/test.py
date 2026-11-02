"""Settings used by the automated test suite.

Tests must not require PostgreSQL, Redis or a running Celery worker.
"""

from .base import *  # noqa: F401,F403

DEBUG = False

SECRET_KEY = "test-only-secret-key-with-more-than-fifty-characters-000000"

ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "braincare-test",
    }
}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"

# Throttling is disabled so tests exercise business logic, not rate limits.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_THROTTLE_RATES": {
        "anon": None,
        "user": None,
        "auth": None,
        "pairing_generate": None,
        "pairing_redeem": None,
        "sync": None,
    },
}

# Keep the test output readable; logging configuration itself is covered by
# dedicated settings tests.
LOGGING["handlers"]["null"] = {"class": "logging.NullHandler"}  # noqa: F405
LOGGING["root"]["handlers"] = ["null"]  # noqa: F405
LOGGING["loggers"] = {}  # noqa: F405
