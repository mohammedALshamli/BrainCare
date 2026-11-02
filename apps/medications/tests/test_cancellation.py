import uuid
from datetime import date, datetime, timezone as dt_timezone

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.medications.models import DoseEvent, DoseOccurrence
from apps.medications.services import (
    deactivate_schedule,
    regenerate_future,
)
from apps.medications.tests.utils import (
    create_medication,
    create_occurrence,
    create_patient,
    create_schedule,
)
from apps.sync.models import SyncChange

FIXED_NOW = datetime(2026, 3, 2, 6, 0, tzinfo=dt_timezone.utc)
SCHEDULED_AT = datetime(2026, 3, 2, 8, 0, tzinfo=dt_timezone.utc)
SCHEDULED_DATE = date(2026, 3, 2)


class SoftCancellationTests(APITestCase):
    def setUp(self):
        self.patient = create_patient()
        self.medication = create_medication(
            self.patient, start_date=date(2026, 3, 1)
        )
        self.schedule = create_schedule(
            self.medication, times=["08:00"], timezone="UTC"
        )
        self.occurrence = create_occurrence(
            self.medication,
            self.schedule,
            scheduled_at=SCHEDULED_AT,
            scheduled_date=SCHEDULED_DATE,
        )

    def test_material_change_soft_cancels_and_links_replacement(self):
        self.schedule.times = ["09:00"]
        self.schedule.save(update_fields=["times", "updated_at"])

        regenerate_future(self.schedule, now=FIXED_NOW)

        self.occurrence.refresh_from_db()
        self.assertEqual(
            self.occurrence.status, DoseOccurrence.Status.CANCELLED
        )
        self.assertEqual(
            self.occurrence.cancellation_reason, "schedule_changed"
        )
        self.assertIsNotNone(self.occurrence.cancelled_at)
        self.assertIsNotNone(self.occurrence.superseded_by_id)

        replacement = DoseOccurrence.objects.get(
            schedule=self.schedule,
            status=DoseOccurrence.Status.PENDING,
            scheduled_at=datetime(
                2026, 3, 2, 9, 0, tzinfo=dt_timezone.utc
            ),
        )
        self.assertEqual(self.occurrence.superseded_by_id, replacement.pk)

    def test_same_instant_is_reactivated_not_duplicated(self):
        regenerate_future(self.schedule, now=FIXED_NOW)

        self.occurrence.refresh_from_db()
        self.assertEqual(
            self.occurrence.status, DoseOccurrence.Status.PENDING
        )
        self.assertIsNone(self.occurrence.cancelled_at)
        same_slot = DoseOccurrence.objects.filter(
            schedule=self.schedule, scheduled_at=SCHEDULED_AT
        )
        self.assertEqual(same_slot.count(), 1)
        self.assertEqual(same_slot.get().pk, self.occurrence.pk)

    def test_deactivation_keeps_cancelled_rows(self):
        deactivate_schedule(self.schedule, now=FIXED_NOW)

        self.occurrence.refresh_from_db()
        self.assertEqual(
            self.occurrence.status, DoseOccurrence.Status.CANCELLED
        )
        self.assertEqual(
            self.occurrence.cancellation_reason, "schedule_deactivated"
        )
        self.assertTrue(
            SyncChange.objects.filter(
                entity_type=SyncChange.EntityType.DOSE_OCCURRENCE,
                object_id=self.occurrence.pk,
                data__status="cancelled",
            ).exists()
        )

    def test_taken_and_skipped_occurrences_are_never_cancelled(self):
        taken = create_occurrence(
            self.medication,
            self.schedule,
            scheduled_at=datetime(
                2026, 3, 2, 10, 0, tzinfo=dt_timezone.utc
            ),
            status=DoseOccurrence.Status.TAKEN,
            taken_at=FIXED_NOW,
        )
        skipped = create_occurrence(
            self.medication,
            self.schedule,
            scheduled_at=datetime(
                2026, 3, 2, 12, 0, tzinfo=dt_timezone.utc
            ),
            status=DoseOccurrence.Status.SKIPPED,
            skipped_at=FIXED_NOW,
        )

        deactivate_schedule(self.schedule, now=FIXED_NOW)

        taken.refresh_from_db()
        skipped.refresh_from_db()
        self.assertEqual(taken.status, DoseOccurrence.Status.TAKEN)
        self.assertEqual(skipped.status, DoseOccurrence.Status.SKIPPED)
        self.assertIsNone(taken.cancelled_at)
        self.assertIsNone(skipped.cancelled_at)


class OfflineCancelledDoseTests(APITestCase):
    def setUp(self):
        self.patient = create_patient()
        self.medication = create_medication(
            self.patient, start_date=date(2026, 3, 1)
        )
        self.schedule = create_schedule(
            self.medication, times=["08:00"], timezone="UTC"
        )
        self.occurrence = create_occurrence(
            self.medication,
            self.schedule,
            scheduled_at=SCHEDULED_AT,
            scheduled_date=SCHEDULED_DATE,
        )
        self.client.force_authenticate(self.patient)

    def push(self, item):
        return self.client.post(
            reverse("sync:push"), {"changes": [item]}, format="json"
        )

    def cancelled_occurrence(self):
        self.schedule.times = ["09:00"]
        self.schedule.save(update_fields=["times", "updated_at"])
        regenerate_future(self.schedule, now=FIXED_NOW)
        self.occurrence.refresh_from_db()
        self.assertEqual(
            self.occurrence.status, DoseOccurrence.Status.CANCELLED
        )
        return self.occurrence

    def test_offline_confirm_on_cancelled_or_modified_occurrence(self):
        occurrence = self.cancelled_occurrence()
        client_event_id = str(uuid.uuid4())
        item = {
            "client_event_id": client_event_id,
            "type": "dose.confirm",
            "occurrence_id": str(occurrence.pk),
        }

        response = self.push(item)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = response.data["results"][0]
        self.assertEqual(result["status"], "applied")

        occurrence.refresh_from_db()
        self.assertEqual(occurrence.status, DoseOccurrence.Status.TAKEN)
        event = DoseEvent.objects.get(client_event_id=client_event_id)
        self.assertEqual(event.occurrence_id, occurrence.pk)
        self.assertTrue(event.payload["confirmed_after_cancellation"])
        self.assertTrue(event.payload["recorded_against_superseded"])
        self.assertEqual(event.payload["previous_status"], "cancelled")
        self.assertIsNotNone(event.payload["superseded_by_id"])

        replay = self.push(item)
        self.assertEqual(replay.data["results"][0]["status"], "duplicate")
        self.assertEqual(DoseEvent.objects.count(), 1)

    def test_offline_skip_on_cancelled_occurrence(self):
        occurrence = self.cancelled_occurrence()
        client_event_id = str(uuid.uuid4())

        response = self.push(
            {
                "client_event_id": client_event_id,
                "type": "dose.skip",
                "occurrence_id": str(occurrence.pk),
            }
        )

        self.assertEqual(response.data["results"][0]["status"], "applied")
        occurrence.refresh_from_db()
        self.assertEqual(occurrence.status, DoseOccurrence.Status.SKIPPED)
        event = DoseEvent.objects.get(client_event_id=client_event_id)
        self.assertTrue(event.payload["skipped_after_cancellation"])
        self.assertTrue(event.payload["recorded_against_superseded"])

    def test_stale_skip_does_not_overwrite_a_taken_dose(self):
        occurrence = self.cancelled_occurrence()
        self.push(
            {
                "client_event_id": str(uuid.uuid4()),
                "type": "dose.confirm",
                "occurrence_id": str(occurrence.pk),
            }
        )

        response = self.push(
            {
                "client_event_id": str(uuid.uuid4()),
                "type": "dose.skip",
                "occurrence_id": str(occurrence.pk),
            }
        )

        result = response.data["results"][0]
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["code"], "state_conflict")
        occurrence.refresh_from_db()
        self.assertEqual(occurrence.status, DoseOccurrence.Status.TAKEN)
        self.assertEqual(DoseEvent.objects.count(), 1)

    def test_cancelled_dose_is_hidden_from_default_list_but_filterable(self):
        occurrence = self.cancelled_occurrence()

        default = self.client.get(reverse("dose-list"))
        self.assertEqual(default.status_code, status.HTTP_200_OK)
        default_ids = {
            row["id"] for row in default.data["results"]
        }
        self.assertNotIn(str(occurrence.pk), default_ids)

        filtered = self.client.get(
            reverse("dose-list"), {"status": "cancelled"}
        )
        filtered_ids = {
            row["id"] for row in filtered.data["results"]
        }
        self.assertIn(str(occurrence.pk), filtered_ids)

    def test_cancelled_dose_remains_retrievable_by_id(self):
        occurrence = self.cancelled_occurrence()
        response = self.client.get(
            reverse("dose-detail", args=[occurrence.pk])
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "cancelled")
