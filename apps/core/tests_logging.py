import json
import logging

from django.test import SimpleTestCase

from config.logging import (
    JsonFormatter,
    RequestIdFilter,
    SensitiveDataFilter,
    normalise_request_id,
    redact_text,
    request_id_var,
)


class RedactionTests(SimpleTestCase):
    def test_redacts_common_credentials(self):
        text = (
            "Authorization: Bearer abc.def.ghi "
            "password=hunter2 token: fcm-secret refresh=refresh-token"
        )
        redacted = redact_text(text)
        for secret in ("abc.def.ghi", "hunter2", "fcm-secret", "refresh-token"):
            self.assertNotIn(secret, redacted)
        self.assertIn("[REDACTED]", redacted)

    def test_filter_redacts_arguments_and_extras(self):
        record = logging.LogRecord(
            "apps.test",
            logging.INFO,
            __file__,
            1,
            "login %(password)s %(token)s",
            {"password": "hunter2", "token": "secret-token"},
            None,
        )
        record.authorization = "Bearer secret-access"
        record.safe_value = "visible"

        self.assertTrue(SensitiveDataFilter().filter(record))
        message = record.getMessage()
        self.assertNotIn("hunter2", message)
        self.assertNotIn("secret-token", message)
        self.assertEqual(record.authorization, "[REDACTED]")
        self.assertEqual(record.safe_value, "visible")

    def test_json_formatter_never_emits_redacted_values(self):
        record = logging.LogRecord(
            "apps.test",
            logging.INFO,
            __file__,
            1,
            "password=%s",
            ("hunter2",),
            None,
        )
        record.request_id = "req-1"
        record.fcm_token = "fcm-secret-token"
        SensitiveDataFilter().filter(record)

        payload = json.loads(JsonFormatter().format(record))
        self.assertNotIn("hunter2", payload["message"])
        self.assertEqual(payload["fcm_token"], "[REDACTED]")
        self.assertEqual(payload["request_id"], "req-1")


class RequestIdTests(SimpleTestCase):
    def test_normalise_request_id_rejects_unsafe_values(self):
        self.assertEqual(normalise_request_id("abc-123"), "abc-123")
        self.assertIsNone(normalise_request_id("bad value"))
        self.assertIsNone(normalise_request_id("x" * 65))
        self.assertIsNone(normalise_request_id(None))

    def test_request_id_filter_uses_context(self):
        token = request_id_var.set("req-42")
        try:
            record = logging.LogRecord(
                "apps.test", logging.INFO, __file__, 1, "hello", (), None
            )
            RequestIdFilter().filter(record)
            self.assertEqual(record.request_id, "req-42")
        finally:
            request_id_var.reset(token)
