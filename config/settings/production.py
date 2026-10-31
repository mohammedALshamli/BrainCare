"""Production settings.

The module refuses to start when mandatory secrets or infrastructure settings
are missing instead of silently falling back to insecure defaults.
"""

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import env

DEBUG = False

SECRET_KEY = env("DJANGO_SECRET_KEY", default="")
if len(SECRET_KEY) < 50 or SECRET_KEY.startswith("insecure-"):
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY must be set to a strong value of at least 50 characters."
    )

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS must be set in production.")

if not DATABASE_URL and not env("POSTGRES_DB", default=""):  # noqa: F405
    raise ImproperlyConfigured(
        "DATABASE_URL or POSTGRES_DB must be set in production."
    )

REDIS_URL = env("REDIS_URL", default="")
if not REDIS_URL:
    raise ImproperlyConfigured("REDIS_URL must be set in production.")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "TIMEOUT": env.int("CACHE_DEFAULT_TIMEOUT", default=300),
    }
}

CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=REDIS_URL)

# Keep JWT signing tied to the production secret even if the base module was
# imported with a different value.
SIMPLE_JWT["SIGNING_KEY"] = SECRET_KEY  # noqa: F405

CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SECURE_HSTS_SECONDS = env.int("DJANGO_SECURE_HSTS_SECONDS", default=31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

LOGGING["handlers"]["console"]["formatter"] = "json"  # noqa: F405
