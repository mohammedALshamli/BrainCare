from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.medications.tests.utils import create_patient
from apps.notifications.models import Device

DEVICE_LIST_URL = reverse("device-list")


class DeviceRegistrationTests(APITestCase):
    def setUp(self):
        self.patient = create_patient()
        self.client.force_authenticate(self.patient)

    def register(self, token, **overrides):
        payload = {"fcm_token": token, "platform": "android"}
        payload.update(overrides)
        return self.client.post(DEVICE_LIST_URL, payload, format="json")

    def test_device_is_registered_without_exposing_token(self):
        token = "fcm-token-0123456789abcdef"
        response = self.register(token)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotIn("fcm_token", response.data)
        self.assertNotIn(token, str(response.data))
        device = Device.objects.get(user=self.patient)
        self.assertNotEqual(device.fcm_token_encrypted, token)
        self.assertNotIn(token, device.fcm_token_encrypted)
        self.assertEqual(device.get_fcm_token(), token)
        self.assertEqual(device.token_preview, token[-6:])

    def test_token_update_uses_stable_device_identifier(self):
        first = self.register(
            "old-token-0123456789abcdef", device_identifier="phone-1"
        )
        second = self.register(
            "new-token-0123456789abcdef", device_identifier="phone-1"
        )

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Device.objects.filter(user=self.patient).count(), 1)
        device = Device.objects.get(user=self.patient)
        self.assertEqual(device.get_fcm_token(), "new-token-0123456789abcdef")

    def test_multiple_devices_are_supported(self):
        self.register("phone-token-0123456789abcdef", device_identifier="phone")
        self.register("tablet-token-0123456789abcdef", device_identifier="tablet")
        self.assertEqual(Device.objects.filter(user=self.patient).count(), 2)

    def test_short_token_is_rejected(self):
        response = self.register("short")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_device_can_be_deactivated(self):
        response = self.register("phone-token-0123456789abcdef")
        device_id = response.data["id"]

        delete = self.client.delete(
            reverse("device-detail", args=[device_id])
        )
        self.assertEqual(delete.status_code, status.HTTP_204_NO_CONTENT)
        device = Device.objects.get(pk=device_id)
        self.assertFalse(device.is_active)

    def test_unauthenticated_registration_is_rejected(self):
        self.client.force_authenticate(None)
        response = self.client.post(
            DEVICE_LIST_URL,
            {"fcm_token": "phone-token-0123456789abcdef", "platform": "ios"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
