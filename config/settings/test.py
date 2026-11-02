"""Settings used by the automated test suite.

Tests must not require PostgreSQL, Redis or a running Celery worker.
"""

from .base import *  # noqa: F401,F403

DEBUG = False

SECRET_KEY = "test-only-secret-key-with-more-than-fifty-characters-000000"

ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]

import os

_TEST_DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("TEST_DATABASE_URL")

if _TEST_DATABASE_URL:
    DATABASES = {"default": env.db_url_config(_TEST_DATABASE_URL)}  # noqa: F405
    DATABASES["default"].setdefault("CONN_MAX_AGE", 0)
elif os.environ.get("USE_POSTGRES", "").lower() in ("1", "true", "yes"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("POSTGRES_DB", default="braincare_test"),  # noqa: F405
            "USER": env("POSTGRES_USER", default="braincare"),  # noqa: F405
            "PASSWORD": env("POSTGRES_PASSWORD", default="braincare"),  # noqa: F405
            "HOST": env("POSTGRES_HOST", default="127.0.0.1"),  # noqa: F405
            "PORT": env.int("POSTGRES_PORT", default=5432),  # noqa: F405
            "CONN_MAX_AGE": 0,
        }
    }
else:
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
