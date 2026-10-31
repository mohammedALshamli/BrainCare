import uuid
from unittest.mock import patch

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.medications.tests.utils import (
    create_caregiver,
    create_medication,
    create_patient,
    link_caregiver,
)
from apps.medications.views import MedicationViewSet

MEDICATION_LIST_URL = reverse("medication-list")


class ErrorFormatTests(APITestCase):
    def setUp(self):
        self.patient = create_patient()
        self.caregiver = create_caregiver()
        link_caregiver(self.caregiver, self.patient)
        self.medication = create_medication(self.patient)

    def assert_error(self, response, status_code, code):
        self.assertEqual(response.status_code, status_code, response.data)
        self.assertIn("error", response.data)
        self.assertEqual(response.data["error"]["code"], code)
        self.assertIn("message", response.data["error"])
        self.assertIn("request_id", response.data["error"])

    def test_validation_error_shape(self):
        self.client.force_authenticate(self.patient)
        response = self.client.post(
            MEDICATION_LIST_URL,
            {
                "name": "Bad dates",
                "start_date": "2026-05-10",
                "end_date": "2026-05-01",
            },
            format="json",
        )

        self.assert_error(response, status.HTTP_400_BAD_REQUEST, "validation_error")
        self.assertIn("end_date", response.data["error"]["details"])

    def test_unauthenticated_error_shape(self):
        response = self.client.get(MEDICATION_LIST_URL)
        self.assert_error(
            response, status.HTTP_401_UNAUTHORIZED, "authentication_required"
        )

    def test_not_found_error_shape(self):
        self.client.force_authenticate(self.patient)
        response = self.client.get(
            reverse("medication-detail", args=[uuid.uuid4()])
        )
        self.assert_error(response, status.HTTP_404_NOT_FOUND, "not_found")

    def test_permission_denied_error_shape(self):
        self.client.force_authenticate(self.caregiver)
        response = self.client.patch(
            reverse("medication-detail", args=[self.medication.pk]),
            {"name": "Caregiver edit"},
            format="json",
        )
        self.assert_error(response, status.HTTP_403_FORBIDDEN, "permission_denied")

    def test_method_not_allowed_shape(self):
        self.client.force_authenticate(self.patient)
        response = self.client.delete(
            reverse("medication-detail", args=[self.medication.pk])
        )
        self.assert_error(
            response, status.HTTP_405_METHOD_NOT_ALLOWED, "method_not_allowed"
        )

    def test_unhandled_exception_is_generic(self):
        self.client.force_authenticate(self.patient)
        self.client.raise_request_exception = False
        with patch.object(
            MedicationViewSet, "list", side_effect=RuntimeError("secret details")
        ):
            response = self.client.get(MEDICATION_LIST_URL)

        self.assert_error(
            response, status.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error"
        )
        body = response.content.decode()
        self.assertNotIn("secret details", body)
        self.assertNotIn("Traceback", body)

    def test_request_id_is_included_in_error_and_header(self):
        self.client.force_authenticate(self.patient)
        response = self.client.post(
            MEDICATION_LIST_URL,
            {},
            format="json",
            HTTP_X_REQUEST_ID="corr-12345",
        )
        self.assertEqual(response.headers["X-Request-ID"], "corr-12345")
        self.assertEqual(response.data["error"]["request_id"], "corr-12345")


class SuccessConventionTests(APITestCase):
    def setUp(self):
        self.patient = create_patient()
        self.client.force_authenticate(self.patient)

    def test_list_endpoint_is_paginated(self):
        for index in range(3):
            create_medication(self.patient, name=f"Medication {index}")

        response = self.client.get(MEDICATION_LIST_URL, {"page_size": 2})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            set(response.data), {"count", "next", "previous", "results"}
        )
        self.assertEqual(response.data["count"], 3)
        self.assertEqual(len(response.data["results"]), 2)

    def test_filtering_and_ordering(self):
        create_medication(self.patient, name="Bravo", is_active=True)
        create_medication(self.patient, name="Alpha", is_active=True)
        create_medication(self.patient, name="Inactive", is_active=False)

        response = self.client.get(
            MEDICATION_LIST_URL, {"is_active": "true", "ordering": "name"}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [item["name"] for item in response.data["results"]]
        self.assertEqual(names, ["Alpha", "Bravo"])

    def test_detail_response_is_plain_resource(self):
        medication = create_medication(self.patient, name="Detail")
        response = self.client.get(
            reverse("medication-detail", args=[medication.pk])
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], str(medication.pk))
        self.assertEqual(response.data["name"], "Detail")

    def test_versioned_path_is_available(self):
        response = self.client.get("/api/v1/medications/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
