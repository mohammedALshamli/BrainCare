import logging

from django.core.cache import cache
from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)

READINESS_CACHE_KEY = "health:readiness"
READINESS_CACHE_VALUE = "ok"


@require_GET
@never_cache
def liveness(request):
    """Process liveness probe. Does not touch external dependencies."""
    return JsonResponse({"status": "ok"})


@require_GET
@never_cache
def readiness(request):
    """Readiness probe for the database and cache.

    Details of failures are logged but never returned to the caller so that
    infrastructure information is not disclosed publicly.
    """
    checks = {}
    healthy = True

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["database"] = "ok"
    except DatabaseError:
        logger.exception("Readiness check failed for the database")
        checks["database"] = "unavailable"
        healthy = False

    try:
        cache.set(READINESS_CACHE_KEY, READINESS_CACHE_VALUE, timeout=5)
        if cache.get(READINESS_CACHE_KEY) != READINESS_CACHE_VALUE:
            raise RuntimeError("Cache round trip returned an unexpected value")
        checks["cache"] = "ok"
    except Exception:  # noqa: BLE001 - any cache failure means not ready
        logger.exception("Readiness check failed for the cache")
        checks["cache"] = "unavailable"
        healthy = False

    return JsonResponse(
        {"status": "ok" if healthy else "unavailable", "checks": checks},
        status=200 if healthy else 503,
    )
