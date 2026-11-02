from django.conf import settings
from django.test import SimpleTestCase
from django.urls import NoReverseMatch, reverse


class AdminExposureTests(SimpleTestCase):
    def test_admin_is_not_mounted_when_disabled(self):
        self.assertFalse(settings.ADMIN_ENABLED)
        with self.assertRaises(NoReverseMatch):
            reverse("admin:index")


class PasswordPolicyTests(SimpleTestCase):
    def test_minimum_password_length_is_at_least_twelve(self):
        validators = settings.AUTH_PASSWORD_VALIDATORS
        minimum = next(
            item
            for item in validators
            if item["NAME"].endswith("MinimumLengthValidator")
        )
        self.assertGreaterEqual(minimum["OPTIONS"]["min_length"], 12)

    def test_common_and_numeric_password_validators_are_enabled(self):
        names = {item["NAME"] for item in settings.AUTH_PASSWORD_VALIDATORS}
        self.assertIn(
            "django.contrib.auth.password_validation.CommonPasswordValidator",
            names,
        )
        self.assertIn(
            "django.contrib.auth.password_validation.NumericPasswordValidator",
            names,
        )


class JwtAndThrottleSettingsTests(SimpleTestCase):
    def test_jwt_rotation_and_blacklist_are_enabled(self):
        self.assertTrue(settings.SIMPLE_JWT["ROTATE_REFRESH_TOKENS"])
        self.assertTrue(settings.SIMPLE_JWT["BLACKLIST_AFTER_ROTATION"])
        self.assertEqual(settings.SIMPLE_JWT["ALGORITHM"], "HS256")
        self.assertEqual(settings.SIMPLE_JWT["AUTH_HEADER_TYPES"], ("Bearer",))

    def test_sensitive_scopes_have_throttle_entries(self):
        rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
        for scope in ("auth", "pairing_generate", "pairing_redeem", "sync"):
            self.assertIn(scope, rates)

    def test_fcm_is_disabled_in_tests(self):
        self.assertFalse(settings.FCM_ENABLED)
