"""Local development settings.

Never use these settings in production. ``DJANGO_DEBUG`` defaults to ``True``
so that Django's error pages are available while developing.
"""

from .base import *  # noqa: F401,F403
from .base import env

DEBUG = env.bool("DJANGO_DEBUG", default=True)

ALLOWED_HOSTS = env.list(
    "DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "[::1]"]
)

INTERNAL_IPS = ["127.0.0.1"]

# Human readable logs while developing; production emits JSON.
LOGGING["handlers"]["console"]["formatter"] = "plain"  # noqa: F405
