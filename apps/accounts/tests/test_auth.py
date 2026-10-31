from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

User = get_user_model()

STRONG_PASSWORD = "Str0ng-Passw0rd!2026"
REGISTER_URL = reverse("accounts:register")
LOGIN_URL = reverse("accounts:login")
REFRESH_URL = reverse("accounts:refresh")
LOGOUT_URL = reverse("accounts:logout")
ME_URL = reverse("accounts:me")


def registration_payload(**overrides):
    payload = {
        "email": "patient@example.com",
        "password": STRONG_PASSWORD,
        "password_confirm": STRONG_PASSWORD,
        "first_name": "Pat",
        "last_name": "Ient",
        "roles": ["patient"],
    }
    payload.update(overrides)
    return payload


class RegistrationTests(APITestCase):
    def test_patient_can_register(self):
        response = self.client.post(
            REGISTER_URL, registration_payload(), format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        user = User.objects.get(email="patient@example.com")
        self.assertTrue(user.is_patient)
        self.assertFalse(user.is_caregiver)
        self.assertEqual(response.data["roles"], ["patient"])
        self.assertNotIn("password", response.data)

    def test_caregiver_can_register(self):
        response = self.client.post(
            REGISTER_URL,
            registration_payload(email="care@example.com", roles=["caregiver"]),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email="care@example.com")
        self.assertFalse(user.is_patient)
        self.assertTrue(user.is_caregiver)

    def test_user_can_register_with_both_roles(self):
        response = self.client.post(
            REGISTER_URL,
            registration_payload(
                email="both@example.com", roles=["patient", "caregiver"]
            ),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email="both@example.com")
        self.assertTrue(user.is_patient)
        self.assertTrue(user.is_caregiver)
        self.assertEqual(set(response.data["roles"]), {"patient", "caregiver"})

    def test_password_is_hashed_and_not_stored_in_plaintext(self):
        self.client.post(REGISTER_URL, registration_payload(), format="json")

        user = User.objects.get(email="patient@example.com")
        self.assertNotEqual(user.password, STRONG_PASSWORD)
        self.assertTrue(user.password.startswith("md5$"))
        self.assertTrue(user.check_password(STRONG_PASSWORD))

    def test_registration_requires_at_least_one_role(self):
        response = self.client.post(
            REGISTER_URL, registration_payload(roles=[]), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("roles", response.data["error"]["details"])

    def test_registration_rejects_unknown_role(self):
        response = self.client.post(
            REGISTER_URL, registration_payload(roles=["admin"]), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("roles", response.data["error"]["details"])

    def test_registration_rejects_mismatched_passwords(self):
        response = self.client.post(
            REGISTER_URL,
            registration_payload(password_confirm="Different-Passw0rd!"),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password_confirm", response.data["error"]["details"])

    def test_registration_rejects_weak_password(self):
        response = self.client.post(
            REGISTER_URL,
            registration_payload(password="12345678", password_confirm="12345678"),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", response.data["error"]["details"])

    def test_registration_rejects_invalid_email(self):
        response = self.client.post(
            REGISTER_URL, registration_payload(email="not-an-email"), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", response.data["error"]["details"])

    def test_duplicate_email_uses_generic_message(self):
        self.client.post(REGISTER_URL, registration_payload(), format="json")
        response = self.client.post(
            REGISTER_URL, registration_payload(), format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        body = str(response.data).lower()
        self.assertIn("could not be completed", body)
        self.assertNotIn("already", body)
        self.assertEqual(User.objects.filter(email="patient@example.com").count(), 1)

    def test_duplicate_email_is_case_insensitive(self):
        self.client.post(REGISTER_URL, registration_payload(), format="json")
        response = self.client.post(
            REGISTER_URL,
            registration_payload(email="PATIENT@EXAMPLE.COM"),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class LoginTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="patient@example.com",
            password=STRONG_PASSWORD,
            is_patient=True,
        )

    def test_login_returns_tokens_and_user(self):
        response = self.client.post(
            LOGIN_URL,
            {"email": "patient@example.com", "password": STRONG_PASSWORD},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        self.assertEqual(response.data["user"]["email"], "patient@example.com")
        self.assertEqual(response.data["user"]["roles"], ["patient"])

    def test_login_is_case_insensitive_for_email(self):
        response = self.client.post(
            LOGIN_URL,
            {"email": "PATIENT@Example.com", "password": STRONG_PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_login_updates_last_login(self):
        self.assertIsNone(self.user.last_login)
        self.client.post(
            LOGIN_URL,
            {"email": "patient@example.com", "password": STRONG_PASSWORD},
            format="json",
        )
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.last_login)

    def test_wrong_password_is_generic(self):
        response = self.client.post(
            LOGIN_URL,
            {"email": "patient@example.com", "password": "Wrong-Passw0rd!"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["error"]["message"], "Invalid email or password.")

    def test_unknown_email_matches_wrong_password_response(self):
        unknown = self.client.post(
            LOGIN_URL,
            {"email": "nobody@example.com", "password": STRONG_PASSWORD},
            format="json",
        )
        wrong = self.client.post(
            LOGIN_URL,
            {"email": "patient@example.com", "password": "Wrong-Passw0rd!"},
            format="json",
        )

        self.assertEqual(unknown.status_code, wrong.status_code)
        self.assertEqual(
            unknown.data["error"]["code"], wrong.data["error"]["code"]
        )
        self.assertEqual(
            unknown.data["error"]["message"], wrong.data["error"]["message"]
        )

    def test_inactive_user_cannot_log_in(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        response = self.client.post(
            LOGIN_URL,
            {"email": "patient@example.com", "password": STRONG_PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["error"]["message"], "Invalid email or password.")

    def test_malformed_login_request_does_not_reveal_details(self):
        response = self.client.post(LOGIN_URL, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["error"]["message"], "Invalid email or password.")


class TokenRefreshTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="patient@example.com",
            password=STRONG_PASSWORD,
            is_patient=True,
        )
        login = self.client.post(
            LOGIN_URL,
            {"email": "patient@example.com", "password": STRONG_PASSWORD},
            format="json",
        )
        self.refresh = login.data["refresh"]

    def test_refresh_returns_new_access_token(self):
        response = self.client.post(
            REFRESH_URL, {"refresh": self.refresh}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIn("access", response.data)

    def test_rotation_blacklists_the_previous_refresh_token(self):
        first = self.client.post(
            REFRESH_URL, {"refresh": self.refresh}, format="json"
        )
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertIn("refresh", first.data)

        replay = self.client.post(
            REFRESH_URL, {"refresh": self.refresh}, format="json"
        )
        self.assertEqual(replay.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_invalid_refresh_token_is_rejected(self):
        response = self.client.post(
            REFRESH_URL, {"refresh": "not-a-token"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class LogoutTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="patient@example.com",
            password=STRONG_PASSWORD,
            is_patient=True,
        )
        login = self.client.post(
            LOGIN_URL,
            {"email": "patient@example.com", "password": STRONG_PASSWORD},
            format="json",
        )
        self.access = login.data["access"]
        self.refresh = login.data["refresh"]

    def authenticate(self, access=None):
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {access or self.access}"
        )

    def test_logout_revokes_refresh_token(self):
        self.authenticate()
        response = self.client.post(
            LOGOUT_URL, {"refresh": self.refresh}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        refresh_attempt = self.client.post(
            REFRESH_URL, {"refresh": self.refresh}, format="json"
        )
        self.assertEqual(refresh_attempt.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_is_idempotent(self):
        self.authenticate()
        first = self.client.post(
            LOGOUT_URL, {"refresh": self.refresh}, format="json"
        )
        second = self.client.post(
            LOGOUT_URL, {"refresh": self.refresh}, format="json"
        )
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)

    def test_logout_rejects_another_users_refresh_token(self):
        other = User.objects.create_user(
            email="other@example.com", password=STRONG_PASSWORD, is_patient=True
        )
        other_login = self.client.post(
            LOGIN_URL,
            {"email": other.email, "password": STRONG_PASSWORD},
            format="json",
        )

        self.authenticate()
        response = self.client.post(
            LOGOUT_URL, {"refresh": other_login.data["refresh"]}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_logout_requires_authentication(self):
        response = self.client.post(
            LOGOUT_URL, {"refresh": self.refresh}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class MeEndpointTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="patient@example.com",
            password=STRONG_PASSWORD,
            is_patient=True,
            is_caregiver=True,
        )

    def login(self):
        response = self.client.post(
            LOGIN_URL,
            {"email": "patient@example.com", "password": STRONG_PASSWORD},
            format="json",
        )
        return response.data["access"]

    def test_me_requires_authentication(self):
        response = self.client.get(ME_URL)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_returns_authenticated_user(self):
        access = self.login()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        response = self.client.get(ME_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], "patient@example.com")
        self.assertEqual(set(response.data["roles"]), {"patient", "caregiver"})

    def test_inactive_user_token_is_rejected(self):
        access = self.login()
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        response = self.client.get(ME_URL)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
