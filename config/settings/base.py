"""Settings shared by every environment.

Environment specific modules (``development``, ``production``, ``test``) import
from this module and only override what differs. Secrets and infrastructure
locations are read from environment variables; see ``.env.example``.
"""

from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY", default="insecure-development-key-change-me")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])
ADMIN_ENABLED = env.bool("DJANGO_ADMIN_ENABLED", default=DEBUG)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_filters",
    "rest_framework",
    "drf_spectacular",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "apps.core",
    "apps.accounts",
    "apps.medications",
    "apps.notifications",
    "apps.water",
    "apps.sync",
]

MIDDLEWARE = [
    "apps.core.middleware.RequestIDMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---------------------------------------------------------------------------
# Database (PostgreSQL is the approved production database)
# ---------------------------------------------------------------------------
DATABASE_URL = env("DATABASE_URL", default="")

if DATABASE_URL:
    DATABASES = {"default": env.db_url_config(DATABASE_URL)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("POSTGRES_DB", default="braincare"),
            "USER": env("POSTGRES_USER", default="braincare"),
            "PASSWORD": env("POSTGRES_PASSWORD", default=""),
            "HOST": env("POSTGRES_HOST", default="127.0.0.1"),
            "PORT": env.int("POSTGRES_PORT", default=5432),
        }
    }

DATABASES["default"].setdefault(
    "CONN_MAX_AGE", env.int("DB_CONN_MAX_AGE", default=60)
)
DATABASES["default"].setdefault("CONN_HEALTH_CHECKS", True)
if DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql":
    DATABASES["default"].setdefault(
        "OPTIONS", {"connect_timeout": env.int("DB_CONNECT_TIMEOUT", default=5)}
    )

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "UserAttributeSimilarityValidator"
        )
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": env.int("PASSWORD_MIN_LENGTH", default=12)},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_RENDERER_CLASSES": (
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ),
    "EXCEPTION_HANDLER": "apps.core.exceptions.api_exception_handler",
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
    "DEFAULT_VERSIONING_CLASS": "rest_framework.versioning.URLPathVersioning",
    "DEFAULT_VERSION": "v1",
    "ALLOWED_VERSIONS": ["v1"],
    "VERSION_PARAM": "version",
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.ScopedRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "anon": env("THROTTLE_ANON_RATE", default="60/min"),
        "user": env("THROTTLE_USER_RATE", default="1000/hour"),
        "auth": env("THROTTLE_AUTH_RATE", default="10/min"),
        "pairing_generate": env(
            "THROTTLE_PAIRING_GENERATE_RATE", default="10/hour"
        ),
        "pairing_redeem": env(
            "THROTTLE_PAIRING_REDEEM_RATE", default="10/min"
        ),
        "sync": env("THROTTLE_SYNC_RATE", default="120/min"),
    },
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.StandardPageNumberPagination",
    "PAGE_SIZE": env.int("DRF_PAGE_SIZE", default=50),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "BrainCare API",
    "DESCRIPTION": (
        "Backend API for patient medication tracking, caregiver pairing, "
        "notifications, water intake, and offline synchronization."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SORT_OPERATIONS": True,
    "SERVE_PERMISSIONS": ["rest_framework.permissions.AllowAny"],
    "SWAGGER_UI_SETTINGS": {
        "deepLinking": True,
        "persistAuthorization": True,
    },
    "APPEND_COMPONENTS": {
        "securitySchemes": {
            "jwtAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
            }
        }
    },
    "ENUM_NAME_OVERRIDES": {
        "DoseEventSourceEnum": "apps.medications.models.DoseEvent.Source",
        "DoseActionSourceEnum": "apps.medications.serializers.DoseActionSource",
        "WaterIntakeSourceEnum": "apps.water.models.WaterIntakeLog.Source",
    },
}

# ---------------------------------------------------------------------------
# Dose scheduling / tracking
# ---------------------------------------------------------------------------
DOSE_GENERATION_WINDOW_DAYS = env.int("DOSE_GENERATION_WINDOW_DAYS", default=14)
DOSE_OVERDUE_GRACE_MINUTES = env.int("DOSE_OVERDUE_GRACE_MINUTES", default=30)
DOSE_SNOOZE_DEFAULT_MINUTES = env.int("DOSE_SNOOZE_DEFAULT_MINUTES", default=10)
DOSE_SNOOZE_MAX_MINUTES = env.int("DOSE_SNOOZE_MAX_MINUTES", default=1440)

# ---------------------------------------------------------------------------
# Offline synchronization
# ---------------------------------------------------------------------------
SYNC_PAGE_SIZE = env.int("SYNC_PAGE_SIZE", default=50)
SYNC_MAX_BATCH_SIZE = env.int("SYNC_MAX_BATCH_SIZE", default=100)
SYNC_MAX_CLIENT_CLOCK_SKEW_SECONDS = env.int(
    "SYNC_MAX_CLIENT_CLOCK_SKEW_SECONDS", default=300
)

# ---------------------------------------------------------------------------
# Patient-caregiver pairing
# ---------------------------------------------------------------------------
PAIRING_CODE_TTL_MINUTES = env.int("PAIRING_CODE_TTL_MINUTES", default=10)
PAIRING_CODE_LENGTH = env.int("PAIRING_CODE_LENGTH", default=10)
PAIRING_CODE_MAX_FAILED_ATTEMPTS = env.int(
    "PAIRING_CODE_MAX_FAILED_ATTEMPTS", default=5
)
PAIRING_CODE_FAILED_ATTEMPT_WINDOW_SECONDS = env.int(
    "PAIRING_CODE_FAILED_ATTEMPT_WINDOW_SECONDS", default=900
)
PAIRING_CODE_RETENTION_DAYS = env.int("PAIRING_CODE_RETENTION_DAYS", default=7)
PAIRING_CODE_PEPPER = env("PAIRING_CODE_PEPPER", default=SECRET_KEY)

# ---------------------------------------------------------------------------
# Notifications / FCM
# ---------------------------------------------------------------------------
FCM_ENABLED = env.bool("FCM_ENABLED", default=False)
FIREBASE_CREDENTIALS_JSON = env("FIREBASE_CREDENTIALS_JSON", default="")
FIREBASE_CREDENTIALS_PATH = env("FIREBASE_CREDENTIALS_PATH", default="")
FCM_TOKEN_ENCRYPTION_KEY = env("FCM_TOKEN_ENCRYPTION_KEY", default="")
NOTIFICATION_MAX_ATTEMPTS = env.int("NOTIFICATION_MAX_ATTEMPTS", default=5)
NOTIFICATION_RETRY_BASE_SECONDS = env.int(
    "NOTIFICATION_RETRY_BASE_SECONDS", default=60
)
NOTIFICATION_RETRY_MAX_SECONDS = env.int(
    "NOTIFICATION_RETRY_MAX_SECONDS", default=3600
)
NOTIFICATION_PROCESSING_TIMEOUT_SECONDS = env.int(
    "NOTIFICATION_PROCESSING_TIMEOUT_SECONDS", default=300
)

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=env.int("JWT_ACCESS_TOKEN_MINUTES", default=15)
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=env.int("JWT_REFRESH_TOKEN_DAYS", default=7)
    ),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": False,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
}

# ---------------------------------------------------------------------------
# Cache / Redis
# ---------------------------------------------------------------------------
REDIS_URL = env("REDIS_URL", default="")

if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
            "TIMEOUT": env.int("CACHE_DEFAULT_TIMEOUT", default=300),
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "braincare-local",
        }
    }

# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = env(
    "CELERY_BROKER_URL",
    default=REDIS_URL or "redis://127.0.0.1:6379/0",
)
CELERY_RESULT_BACKEND = env(
    "CELERY_RESULT_BACKEND", default="redis://127.0.0.1:6379/1"
)
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = "UTC"
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = env.int("CELERY_TASK_TIME_LIMIT", default=600)
CELERY_TASK_SOFT_TIME_LIMIT = env.int("CELERY_TASK_SOFT_TIME_LIMIT", default=540)
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
# Redis visibility must exceed the hard task limit so a redelivered task is
# not handed to a second worker while the first is still running.
CELERY_VISIBILITY_TIMEOUT = max(
    env.int("CELERY_VISIBILITY_TIMEOUT", default=3600),
    CELERY_TASK_TIME_LIMIT + 60,
)
CELERY_BROKER_TRANSPORT_OPTIONS = {
    "visibility_timeout": CELERY_VISIBILITY_TIMEOUT,
}
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BEAT_SCHEDULE = {
    "generate-rolling-dose-occurrences": {
        "task": "apps.medications.tasks.generate_rolling_dose_occurrences",
        "schedule": 6 * 60 * 60,
    },
    "mark-overdue-doses": {
        "task": "apps.medications.tasks.mark_overdue_doses",
        "schedule": 5 * 60,
    },
    "dispatch-pending-notifications": {
        "task": "apps.notifications.tasks.dispatch_pending_notifications_task",
        "schedule": 60,
    },
    "cleanup-pairing-codes": {
        "task": "apps.accounts.tasks.cleanup_pairing_codes",
        "schedule": 60 * 60,
    },
}

# ---------------------------------------------------------------------------
# Internationalisation
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_LEVEL = env("DJANGO_LOG_LEVEL", default="INFO")
LOG_FORMAT = env("DJANGO_LOG_FORMAT", default="json")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_id": {"()": "config.logging.RequestIdFilter"},
        "redact": {"()": "config.logging.SensitiveDataFilter"},
    },
    "formatters": {
        "json": {"()": "config.logging.JsonFormatter"},
        "plain": {
            "format": "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": LOG_FORMAT if LOG_FORMAT in {"json", "plain"} else "json",
            "filters": ["request_id", "redact"],
        },
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
        "celery": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "apps": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
    },
}
