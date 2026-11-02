from datetime import timedelta

from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.medications.models import DoseOccurrence, Medication
from apps.medications.tests.utils import (
    create_caregiver,
    create_medication,
    create_occurrence,
    create_patient,
    create_schedule,
    link_caregiver,
)

LIST_URL = reverse("medication-list")


def payload(**overrides):
    data = {
        "name": "Metformin",
        "strength": "500 mg",
        "dosage_form": "tablet",
        "instructions": "Take with food",
        "start_date": timezone.localdate().isoformat(),
        "is_active": True,
    }
    data.update(overrides)
    return data


class MedicationCreateTests(APITestCase):
    def setUp(self):
        self.patient = create_patient()
        self.client.force_authenticate(self.patient)

    def test_patient_can_create_medication_for_self(self):
        response = self.client.post(LIST_URL, payload(), format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        medication = Medication.objects.get(pk=response.data["id"])
        self.assertEqual(medication.patient, self.patient)
        self.assertEqual(medication.created_by, self.patient)
        self.assertEqual(response.data["patient"], self.patient.pk)

    def test_patient_cannot_assign_medication_to_another_patient(self):
        other = create_patient(email="other@example.com")
        response = self.client.post(
            LIST_URL, payload(patient=other.pk), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        medication = Medication.objects.get(pk=response.data["id"])
        self.assertEqual(medication.patient, self.patient)

    def test_caregiver_cannot_create_medication(self):
        caregiver = create_caregiver()
        link_caregiver(caregiver, self.patient)
        self.client.force_authenticate(caregiver)

        response = self.client.post(LIST_URL, payload(), format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_end_date_before_start_date_is_rejected(self):
        response = self.client.post(
            LIST_URL,
            payload(start_date="2026-05-10", end_date="2026-05-01"),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("end_date", response.data["error"]["details"])

    def test_dose_amount_requires_unit(self):
        response = self.client.post(
            LIST_URL, payload(dose_amount="1.5"), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("dose_unit", response.data["error"]["details"])

    def test_dose_unit_requires_amount(self):
        response = self.client.post(
            LIST_URL, payload(dose_unit="tablet"), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("dose_amount", response.data["error"]["details"])

    def test_database_rejects_invalid_date_range(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                create_medication(
                    self.patient,
                    start_date=timezone.localdate(),
                    end_date=timezone.localdate() - timedelta(days=1),
                )


class MedicationAccessTests(APITestCase):
    def setUp(self):
        self.patient = create_patient()
        self.other_patient = create_patient(email="other@example.com")
        self.caregiver = create_caregiver()
        link_caregiver(self.caregiver, self.patient)
        self.medication = create_medication(self.patient, name="Private")

    def test_patient_lists_only_own_medications(self):
        create_medication(self.other_patient, name="Other")
        self.client.force_authenticate(self.patient)

        response = self.client.get(LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [item["name"] for item in response.data["results"]]
        self.assertEqual(names, ["Private"])

    def test_linked_caregiver_can_read_medication(self):
        self.client.force_authenticate(self.caregiver)

        list_response = self.client.get(LIST_URL)
        detail_response = self.client.get(
            reverse("medication-detail", args=[self.medication.pk])
        )

        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(list_response.data["count"], 1)
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)

    def test_unlinked_caregiver_cannot_read_medication(self):
        unlinked = create_caregiver(email="unlinked@example.com")
        self.client.force_authenticate(unlinked)

        list_response = self.client.get(LIST_URL)
        detail_response = self.client.get(
            reverse("medication-detail", args=[self.medication.pk])
        )

        self.assertEqual(list_response.data["count"], 0)
        self.assertEqual(detail_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_inactive_caregiver_link_denies_access(self):
        self.caregiver.patient_links.update(is_active=False)
        self.client.force_authenticate(self.caregiver)

        response = self.client.get(
            reverse("medication-detail", args=[self.medication.pk])
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cross_patient_access_is_not_found(self):
        self.client.force_authenticate(self.other_patient)
        response = self.client.get(
            reverse("medication-detail", args=[self.medication.pk])
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_linked_caregiver_is_read_only(self):
        self.client.force_authenticate(self.caregiver)

        patch_response = self.client.patch(
            reverse("medication-detail", args=[self.medication.pk]),
            {"name": "Changed"},
            format="json",
        )
        deactivate_response = self.client.post(
            reverse("medication-deactivate", args=[self.medication.pk])
        )

        self.assertEqual(patch_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            deactivate_response.status_code, status.HTTP_403_FORBIDDEN
        )


class MedicationUpdateTests(APITestCase):
    def setUp(self):
        self.patient = create_patient()
        self.client.force_authenticate(self.patient)
        self.medication = create_medication(self.patient, name="Original")

    def test_patient_can_update_medication(self):
        response = self.client.patch(
            reverse("medication-detail", args=[self.medication.pk]),
            {"name": "Updated", "instructions": "With water"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.medication.refresh_from_db()
        self.assertEqual(self.medication.name, "Updated")

    def test_deactivate_preserves_historical_doses(self):
        schedule = create_schedule(self.medication)
        historical = create_occurrence(
            self.medication,
            schedule,
            scheduled_at=timezone.now() - timedelta(days=1),
            status="taken",
            taken_at=timezone.now() - timedelta(days=1),
        )
        future = create_occurrence(
            self.medication,
            schedule,
            scheduled_at=timezone.now() + timedelta(days=1),
        )

        response = self.client.post(
            reverse("medication-deactivate", args=[self.medication.pk])
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["is_active"])
        self.assertTrue(
            self.medication.dose_occurrences.filter(pk=historical.pk).exists()
        )
        future.refresh_from_db()
        self.assertEqual(
            future.status, DoseOccurrence.Status.CANCELLED
        )
        self.assertIsNotNone(future.cancelled_at)

    def test_deactivate_is_idempotent(self):
        first = self.client.post(
            reverse("medication-deactivate", args=[self.medication.pk])
        )
        second = self.client.post(
            reverse("medication-deactivate", args=[self.medication.pk])
        )
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)

    def test_patch_is_active_false_deactivates_safely(self):
        response = self.client.patch(
            reverse("medication-detail", args=[self.medication.pk]),
            {"is_active": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.medication.refresh_from_db()
        self.assertFalse(self.medication.is_active)


class MedicationFilteringTests(APITestCase):
    def setUp(self):
        self.patient = create_patient()
        self.client.force_authenticate(self.patient)
        create_medication(self.patient, name="Alpha", is_active=True)
        create_medication(self.patient, name="Bravo", is_active=False)

    def test_filter_by_active_status(self):
        response = self.client.get(LIST_URL, {"is_active": "true"})
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["name"], "Alpha")

    def test_search_by_name(self):
        response = self.client.get(LIST_URL, {"search": "Brav"})
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["name"], "Bravo")

    def test_ordering(self):
        response = self.client.get(LIST_URL, {"ordering": "name"})
        names = [item["name"] for item in response.data["results"]]
        self.assertEqual(names, ["Alpha", "Bravo"])
