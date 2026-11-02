from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from firebase_admin import exceptions, messaging

from apps.notifications import fcm


class FCMConfigurationTests(SimpleTestCase):
    def tearDown(self):
        fcm._firebase_app = None

    @override_settings(FCM_ENABLED=False)
    def test_disabled_fcm_is_not_configured(self):
        with self.assertRaises(fcm.FCMNotConfigured):
            fcm._get_app()

    @override_settings(
        FCM_ENABLED=True,
        FIREBASE_CREDENTIALS_JSON="{not-json",
        FIREBASE_CREDENTIALS_PATH="",
    )
    def test_invalid_credentials_json_is_rejected(self):
        with self.assertRaises(fcm.FCMNotConfigured):
            fcm._get_app()

    @override_settings(
        FCM_ENABLED=True,
        FIREBASE_CREDENTIALS_JSON="",
        FIREBASE_CREDENTIALS_PATH="",
    )
    def test_missing_credentials_are_rejected(self):
        with self.assertRaises(fcm.FCMNotConfigured):
            fcm._get_app()


class FCMClassificationTests(SimpleTestCase):
    def test_unregistered_token_is_invalid(self):
        retryable, invalid, code = fcm._classify(
            messaging.UnregisteredError("gone")
        )
        self.assertFalse(retryable)
        self.assertTrue(invalid)
        self.assertEqual(code, "UnregisteredError")

    def test_unavailable_provider_is_retryable(self):
        retryable, invalid, _ = fcm._classify(
            exceptions.UnavailableError("try later")
        )
        self.assertTrue(retryable)
        self.assertFalse(invalid)

    def test_unknown_provider_error_is_not_retried(self):
        retryable, invalid, code = fcm._classify(RuntimeError("boom"))
        self.assertFalse(retryable)
        self.assertFalse(invalid)
        self.assertEqual(code, "RuntimeError")


class FCMSendTests(SimpleTestCase):
    def test_empty_token_list_does_not_contact_provider(self):
        with patch.object(fcm, "_get_app") as get_app:
            self.assertEqual(fcm.send_push([], "Title", "Body"), [])
        get_app.assert_not_called()

    @patch("apps.notifications.fcm.messaging.send_each_for_multicast")
    @patch("apps.notifications.fcm._get_app", return_value=object())
    def test_mixed_results_are_reported_per_unique_token(
        self, get_app, send_each
    ):
        send_each.return_value = SimpleNamespace(
            responses=[
                SimpleNamespace(success=True, exception=None),
                SimpleNamespace(
                    success=False,
                    exception=messaging.UnregisteredError("gone"),
                ),
            ]
        )

        results = fcm.send_push(
            ["token-a", "token-a", "token-b"],
            "Title",
            "Body",
            {"kind": "dose_overdue"},
        )

        self.assertEqual([item.token for item in results], ["token-a", "token-b"])
        self.assertTrue(results[0].success)
        self.assertTrue(results[1].invalid_token)
        message = send_each.call_args.args[0]
        self.assertEqual(message.tokens, ["token-a", "token-b"])
        self.assertEqual(message.data, {"kind": "dose_overdue"})
        get_app.assert_called_once()

    @patch("apps.notifications.fcm.messaging.send_each_for_multicast")
    @patch("apps.notifications.fcm._get_app", return_value=object())
    def test_top_level_firebase_error_marks_all_tokens_retryable(
        self, get_app, send_each
    ):
        send_each.side_effect = exceptions.UnavailableError("provider down")

        results = fcm.send_push(["token-a", "token-b"], "Title", "Body")

        self.assertEqual(len(results), 2)
        self.assertTrue(all(item.retryable for item in results))
        self.assertTrue(all(not item.success for item in results))

    @patch("apps.notifications.fcm.messaging.send_each_for_multicast")
    @patch("apps.notifications.fcm._get_app", return_value=object())
    def test_non_firebase_exception_is_not_swallowed(
        self, get_app, send_each
    ):
        send_each.side_effect = RuntimeError("unexpected")
        with self.assertRaises(RuntimeError):
            fcm.send_push(["token-a"], "Title", "Body")
