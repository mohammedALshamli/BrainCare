from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.db import DatabaseError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse


class HealthEndpointTests(TestCase):
    def test_liveness_returns_ok(self):
        response = self.client.get(reverse("core:liveness"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_readiness_returns_ok(self):
        response = self.client.get(reverse("core:readiness"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(response.json()["checks"], {"database": "ok", "cache": "ok"})

    def test_readiness_is_available_at_health_root(self):
        response = self.client.get("/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_readiness_returns_503_and_hides_failure_details(self):
        with patch(
            "apps.core.views.connection.cursor", side_effect=DatabaseError("boom")
        ), patch("apps.core.views.cache.set", side_effect=RuntimeError("boom")):
            response = self.client.get(reverse("core:readiness"))

        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertEqual(body["status"], "unavailable")
        self.assertEqual(
            body["checks"], {"database": "unavailable", "cache": "unavailable"}
        )
        self.assertNotIn("boom", response.content.decode())


class RequestIDTests(TestCase):
    def test_generates_request_id_when_missing(self):
        response = self.client.get(reverse("core:liveness"))
        request_id = response.headers.get("X-Request-ID")
        self.assertIsNotNone(request_id)
        self.assertEqual(len(request_id), 32)

    def test_echoes_valid_request_id(self):
        response = self.client.get(
            reverse("core:liveness"), HTTP_X_REQUEST_ID="abc-123.valid"
        )
        self.assertEqual(response.headers["X-Request-ID"], "abc-123.valid")

    def test_replaces_invalid_request_id(self):
        response = self.client.get(
            reverse("core:liveness"), HTTP_X_REQUEST_ID="not a valid id!"
        )
        self.assertNotEqual(response.headers["X-Request-ID"], "not a valid id!")
        self.assertEqual(len(response.headers["X-Request-ID"]), 32)


class FoundationSettingsTests(SimpleTestCase):
    def test_custom_user_model_is_configured(self):
        self.assertEqual(settings.AUTH_USER_MODEL, "accounts.User")

    def test_rest_framework_uses_jwt_authentication(self):
        self.assertEqual(
            settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"][0],
            "rest_framework_simplejwt.authentication.JWTAuthentication",
        )
        self.assertEqual(
            settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"][0],
            "rest_framework.permissions.IsAuthenticated",
        )

    def test_jwt_lifetimes_are_safe_defaults(self):
        self.assertEqual(
            settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"], timedelta(minutes=15)
        )
        self.assertEqual(
            settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"], timedelta(days=7)
        )
        self.assertTrue(settings.SIMPLE_JWT["ROTATE_REFRESH_TOKENS"])
        self.assertTrue(settings.SIMPLE_JWT["BLACKLIST_AFTER_ROTATION"])

    def test_utc_and_timezone_aware_datetimes(self):
        self.assertTrue(settings.USE_TZ)
        self.assertEqual(settings.TIME_ZONE, "UTC")

    def test_tests_do_not_require_postgres_or_redis(self):
        self.assertEqual(
            settings.DATABASES["default"]["ENGINE"], "django.db.backends.sqlite3"
        )
        self.assertIn(
            "LocMemCache", settings.CACHES["default"]["BACKEND"]
        )

    def test_structured_logging_formatter_is_configured(self):
        self.assertEqual(
            settings.LOGGING["formatters"]["json"]["()"],
            "config.logging.JsonFormatter",
        )
        self.assertIn("request_id", settings.LOGGING["filters"])

    def test_celery_is_configured_with_json_serialisation(self):
        self.assertEqual(settings.CELERY_TASK_SERIALIZER, "json")
        self.assertEqual(settings.CELERY_ACCEPT_CONTENT, ["json"])
        self.assertEqual(settings.CELERY_TIMEZONE, "UTC")
