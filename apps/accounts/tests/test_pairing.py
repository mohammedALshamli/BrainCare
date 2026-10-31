from datetime import timedelta

from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import CaregiverPatientLink, PairingCode
from apps.medications.tests.utils import (
    create_caregiver,
    create_patient,
    link_caregiver,
)

CODE_URL = reverse("pairing:code-generate")
REDEEM_URL = reverse("pairing:code-redeem")
RELATIONSHIPS_URL = reverse("pairing:relationship-list")


class PairingCodeTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.patient = create_patient()
        self.caregiver = create_caregiver()

    def generate(self, user=None):
        self.client.force_authenticate(user or self.patient)
        return self.client.post(CODE_URL, {}, format="json")

    def redeem(self, code, user=None):
        self.client.force_authenticate(user or self.caregiver)
        return self.client.post(REDEEM_URL, {"code": code}, format="json")

    def test_patient_can_generate_qr_compatible_code(self):
        response = self.generate()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(response.data["code"]), 10)
        self.assertEqual(
            response.data["qr_payload"],
            f"braincare://pair?code={response.data['code']}",
        )
        self.assertIn("expires_at", response.data)

    def test_code_is_stored_as_hash_not_plaintext(self):
        response = self.generate()
        code = response.data["code"]

        pairing = PairingCode.objects.get(patient=self.patient)
        self.assertNotEqual(pairing.code_hash, code)
        self.assertEqual(len(pairing.code_hash), 64)
        self.assertNotIn(code, pairing.code_hash)

    def test_caregiver_cannot_generate_code(self):
        response = self.generate(self.caregiver)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_cannot_generate_code(self):
        self.client.force_authenticate(None)
        response = self.client.post(CODE_URL, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_caregiver_can_redeem_and_relationship_is_created(self):
        code = self.generate().data["code"]
        response = self.redeem(code)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        link = CaregiverPatientLink.objects.get(
            caregiver=self.caregiver, patient=self.patient
        )
        self.assertTrue(link.is_active)
        self.assertTrue(link.can_view)
        self.assertFalse(link.can_edit_medications)
        self.assertIsNotNone(link.consent_at)
        self.assertIsNone(link.revoked_at)

        pairing = PairingCode.objects.get(patient=self.patient)
        self.assertIsNotNone(pairing.used_at)
        self.assertEqual(pairing.used_by, self.caregiver)

    def test_patient_cannot_redeem(self):
        code = self.generate().data["code"]
        response = self.redeem(code, user=self.patient)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_cannot_redeem(self):
        code = self.generate().data["code"]
        self.client.force_authenticate(None)
        response = self.client.post(
            REDEEM_URL, {"code": code}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_expired_code_cannot_be_redeemed(self):
        code = self.generate().data["code"]
        PairingCode.objects.filter(patient=self.patient).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )

        response = self.redeem(code)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(
            CaregiverPatientLink.objects.filter(
                caregiver=self.caregiver
            ).exists()
        )

    def test_code_can_only_be_used_once(self):
        code = self.generate().data["code"]
        first = self.redeem(code)
        second_caregiver = create_caregiver(email="second@example.com")
        second = self.redeem(code, user=second_caregiver)

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            CaregiverPatientLink.objects.filter(
                patient=self.patient
            ).count(),
            1,
        )

    def test_brute_force_attempts_are_locked_out(self):
        for attempt in range(4):
            response = self.redeem("WRONGCODE1")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        blocked = self.redeem("WRONGCODE1")
        self.assertEqual(blocked.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

        still_blocked = self.redeem("WRONGCODE1")
        self.assertEqual(
            still_blocked.status_code, status.HTTP_429_TOO_MANY_REQUESTS
        )

    def test_existing_active_relationship_cannot_pair_again(self):
        link_caregiver(self.caregiver, self.patient)
        code = self.generate().data["code"]

        response = self.redeem(code)
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_revoked_relationship_can_be_reactivated_with_new_code(self):
        link = link_caregiver(
            self.caregiver, self.patient, can_edit_medications=True
        )
        link.is_active = False
        link.revoked_at = timezone.now()
        link.save()

        code = self.generate().data["code"]
        response = self.redeem(code)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        link.refresh_from_db()
        self.assertTrue(link.is_active)
        self.assertFalse(link.can_edit_medications)


class RelationshipTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.patient = create_patient()
        self.caregiver = create_caregiver()
        self.other = create_patient(email="other@example.com")
        self.link = link_caregiver(self.caregiver, self.patient)

    def test_patient_can_list_own_relationship(self):
        self.client.force_authenticate(self.patient)
        response = self.client.get(RELATIONSHIPS_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

    def test_caregiver_can_list_own_relationship(self):
        self.client.force_authenticate(self.caregiver)
        response = self.client.get(RELATIONSHIPS_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

    def test_unrelated_user_cannot_see_relationship(self):
        self.client.force_authenticate(self.other)
        response = self.client.get(RELATIONSHIPS_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

    def test_patient_can_change_permissions(self):
        self.client.force_authenticate(self.patient)
        response = self.client.patch(
            reverse("pairing:relationship-detail", args=[self.link.pk]),
            {"can_edit_medications": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.link.refresh_from_db()
        self.assertTrue(self.link.can_edit_medications)

    def test_caregiver_cannot_change_permissions(self):
        self.client.force_authenticate(self.caregiver)
        response = self.client.patch(
            reverse("pairing:relationship-detail", args=[self.link.pk]),
            {"can_edit_medications": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_edit_permission_requires_view_permission(self):
        self.client.force_authenticate(self.patient)
        response = self.client.patch(
            reverse("pairing:relationship-detail", args=[self.link.pk]),
            {"can_view": False, "can_edit_medications": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_patient_can_revoke_relationship(self):
        self.client.force_authenticate(self.patient)
        response = self.client.post(
            reverse("pairing:relationship-revoke", args=[self.link.pk])
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.link.refresh_from_db()
        self.assertFalse(self.link.is_active)
        self.assertIsNotNone(self.link.revoked_at)

    def test_caregiver_can_revoke_own_relationship(self):
        self.client.force_authenticate(self.caregiver)
        response = self.client.post(
            reverse("pairing:relationship-revoke", args=[self.link.pk])
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.link.refresh_from_db()
        self.assertFalse(self.link.is_active)

    def test_unrelated_user_cannot_revoke(self):
        self.client.force_authenticate(self.other)
        response = self.client.post(
            reverse("pairing:relationship-revoke", args=[self.link.pk])
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
