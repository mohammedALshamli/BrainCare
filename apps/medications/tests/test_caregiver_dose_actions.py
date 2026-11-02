import uuid

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.medications.models import DoseEvent, DoseOccurrence
from apps.medications.tests.utils import (
    create_caregiver,
    create_medication,
    create_occurrence,
    create_patient,
    create_schedule,
    link_caregiver,
)


class CaregiverDoseActionTests(APITestCase):
    def setUp(self):
        self.patient = create_patient()
        self.caregiver = create_caregiver()
        self.medication = create_medication(self.patient)
        self.schedule = create_schedule(self.medication)
        self.occurrence = create_occurrence(
            self.medication, self.schedule
        )

    def payload(self):
        return {"client_event_id": str(uuid.uuid4())}

    def test_patient_can_confirm_own_dose(self):
        self.client.force_authenticate(self.patient)
        response = self.client.post(
            reverse("dose-confirm", args=[self.occurrence.pk]),
            self.payload(),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.occurrence.refresh_from_db()
        self.assertEqual(self.occurrence.status, DoseOccurrence.Status.TAKEN)

    def test_linked_caregiver_can_confirm_dose_for_patient(self):
        link_caregiver(
            self.caregiver, self.patient, can_confirm_doses=True
        )
        self.client.force_authenticate(self.caregiver)

        response = self.client.post(
            reverse("dose-confirm", args=[self.occurrence.pk]),
            self.payload(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.occurrence.refresh_from_db()
        self.assertEqual(self.occurrence.status, DoseOccurrence.Status.TAKEN)
        event = DoseEvent.objects.get(occurrence=self.occurrence)
        self.assertEqual(event.actor, self.caregiver)
        self.assertEqual(event.source, DoseEvent.Source.CAREGIVER_APP)

    def test_linked_caregiver_can_skip_dose_for_patient(self):
        link_caregiver(
            self.caregiver, self.patient, can_confirm_doses=True
        )
        self.client.force_authenticate(self.caregiver)

        response = self.client.post(
            reverse("dose-skip", args=[self.occurrence.pk]),
            self.payload(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.occurrence.refresh_from_db()
        self.assertEqual(self.occurrence.status, DoseOccurrence.Status.SKIPPED)
        event = DoseEvent.objects.get(occurrence=self.occurrence)
        self.assertEqual(event.actor, self.caregiver)
        self.assertEqual(event.source, DoseEvent.Source.CAREGIVER_APP)

    def test_unlinked_or_view_only_caregiver_cannot_confirm_dose(self):
        link_caregiver(
            self.caregiver,
            self.patient,
            can_edit_medications=True,
            can_confirm_doses=False,
        )
        self.client.force_authenticate(self.caregiver)

        response = self.client.post(
            reverse("dose-confirm", args=[self.occurrence.pk]),
            self.payload(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.occurrence.refresh_from_db()
        self.assertEqual(
            self.occurrence.status, DoseOccurrence.Status.PENDING
        )

    def test_revoked_caregiver_cannot_confirm_dose(self):
        link_caregiver(
            self.caregiver,
            self.patient,
            is_active=False,
            can_confirm_doses=True,
        )
        self.client.force_authenticate(self.caregiver)

        response = self.client.post(
            reverse("dose-confirm", args=[self.occurrence.pk]),
            self.payload(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_unrelated_caregiver_cannot_confirm_dose(self):
        other = create_patient(email="other@example.com")
        self.client.force_authenticate(other)
        response = self.client.post(
            reverse("dose-confirm", args=[self.occurrence.pk]),
            self.payload(),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_caregiver_confirmation_is_visible_with_actor_email(self):
        link_caregiver(
            self.caregiver, self.patient, can_confirm_doses=True
        )
        self.client.force_authenticate(self.caregiver)
        self.client.post(
            reverse("dose-confirm", args=[self.occurrence.pk]),
            self.payload(),
            format="json",
        )

        self.client.force_authenticate(self.patient)
        response = self.client.get(
            reverse("dose-events", args=[self.occurrence.pk])
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["results"][0]["actor"], self.caregiver.pk
        )
        self.assertEqual(
            response.data["results"][0]["actor_email"],
            self.caregiver.email,
        )

    def test_linked_caregiver_can_snooze_dose_for_patient(self):
        link_caregiver(
            self.caregiver, self.patient, can_confirm_doses=True
        )
        self.client.force_authenticate(self.caregiver)

        response = self.client.post(
            reverse("dose-snooze", args=[self.occurrence.pk]),
            {"client_event_id": str(uuid.uuid4()), "minutes": 15},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.occurrence.refresh_from_db()
        self.assertEqual(self.occurrence.status, DoseOccurrence.Status.PENDING)
        self.assertIsNotNone(self.occurrence.snoozed_until)
        event = DoseEvent.objects.get(occurrence=self.occurrence)
        self.assertEqual(event.actor, self.caregiver)
        self.assertEqual(event.source, DoseEvent.Source.CAREGIVER_APP)
        self.assertEqual(event.event_type, DoseEvent.EventType.SNOOZED)

    def test_caregiver_can_confirm_through_sync_push(self):
        link_caregiver(
            self.caregiver, self.patient, can_confirm_doses=True
        )
        self.client.force_authenticate(self.caregiver)

        response = self.client.post(
            reverse("sync:push"),
            {
                "changes": [
                    {
                        "client_event_id": str(uuid.uuid4()),
                        "type": "dose.confirm",
                        "occurrence_id": str(self.occurrence.pk),
                    }
                ]
            },
            format="json",
        )

        result = response.data["results"][0]
        self.assertEqual(result["status"], "applied")
        event = DoseEvent.objects.get(occurrence=self.occurrence)
        self.assertEqual(event.actor, self.caregiver)
        self.assertEqual(event.source, DoseEvent.Source.CAREGIVER_APP)

    def test_caregiver_can_skip_through_sync_push(self):
        link_caregiver(
            self.caregiver, self.patient, can_confirm_doses=True
        )
        self.client.force_authenticate(self.caregiver)

        response = self.client.post(
            reverse("sync:push"),
            {
                "changes": [
                    {
                        "client_event_id": str(uuid.uuid4()),
                        "type": "dose.skip",
                        "occurrence_id": str(self.occurrence.pk),
                    }
                ]
            },
            format="json",
        )

        result = response.data["results"][0]
        self.assertEqual(result["status"], "applied")
        self.occurrence.refresh_from_db()
        self.assertEqual(self.occurrence.status, DoseOccurrence.Status.SKIPPED)
        event = DoseEvent.objects.get(occurrence=self.occurrence)
        self.assertEqual(event.actor, self.caregiver)
        self.assertEqual(event.source, DoseEvent.Source.CAREGIVER_APP)

    def test_caregiver_can_snooze_through_sync_push(self):
        link_caregiver(
            self.caregiver, self.patient, can_confirm_doses=True
        )
        self.client.force_authenticate(self.caregiver)

        response = self.client.post(
            reverse("sync:push"),
            {
                "changes": [
                    {
                        "client_event_id": str(uuid.uuid4()),
                        "type": "dose.snooze",
                        "occurrence_id": str(self.occurrence.pk),
                        "minutes": 20,
                    }
                ]
            },
            format="json",
        )

        result = response.data["results"][0]
        self.assertEqual(result["status"], "applied")
        self.occurrence.refresh_from_db()
        self.assertEqual(self.occurrence.status, DoseOccurrence.Status.PENDING)
        self.assertIsNotNone(self.occurrence.snoozed_until)
        event = DoseEvent.objects.get(occurrence=self.occurrence)
        self.assertEqual(event.actor, self.caregiver)
        self.assertEqual(event.source, DoseEvent.Source.CAREGIVER_APP)

    def test_unauthorized_caregiver_rejected_on_sync_push(self):
        link_caregiver(
            self.caregiver,
            self.patient,
            can_edit_medications=True,
            can_confirm_doses=False,
        )
        self.client.force_authenticate(self.caregiver)

        response = self.client.post(
            reverse("sync:push"),
            {
                "changes": [
                    {
                        "client_event_id": str(uuid.uuid4()),
                        "type": "dose.confirm",
                        "occurrence_id": str(self.occurrence.pk),
                    }
                ]
            },
            format="json",
        )

        result = response.data["results"][0]
        self.assertEqual(result["status"], "forbidden")
        self.occurrence.refresh_from_db()
        self.assertEqual(self.occurrence.status, DoseOccurrence.Status.PENDING)

