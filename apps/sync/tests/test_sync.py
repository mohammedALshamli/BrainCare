import uuid
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.medications.models import DoseEvent, DoseOccurrence
from apps.medications.services import regenerate_future
from apps.medications.tests.utils import (
    create_caregiver,
    create_medication,
    create_occurrence,
    create_patient,
    create_schedule,
    link_caregiver,
)
from apps.sync.models import SyncChange
from apps.sync.services import record_change
from apps.water.models import WaterIntakeLog
from apps.water.services import record_intake

CHANGES_URL = reverse("sync:changes")
PUSH_URL = reverse("sync:push")


class SyncFeedTests(APITestCase):
    def setUp(self):
        self.patient = create_patient()
        self.caregiver = create_caregiver()
        self.other = create_patient(email="other@example.com")
        self.client.force_authenticate(self.patient)

    def changes(self, **params):
        return self.client.get(CHANGES_URL, params)

    def test_changes_require_authentication(self):
        self.client.force_authenticate(None)
        response = self.changes()
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_cursor_pagination_does_not_skip_or_duplicate(self):
        for amount in (100, 200, 300, 400, 500):
            record_intake(self.patient, amount)

        first = self.changes(limit=2)
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(len(first.data["changes"]), 2)
        self.assertTrue(first.data["has_more"])

        second = self.changes(limit=2, cursor=first.data["next_cursor"])
        third = self.changes(limit=2, cursor=second.data["next_cursor"])

        self.assertEqual(len(second.data["changes"]), 2)
        self.assertEqual(len(third.data["changes"]), 1)
        self.assertFalse(third.data["has_more"])

        cursors = [
            row["cursor"]
            for payload in (first, second, third)
            for row in payload.data["changes"]
        ]
        self.assertEqual(cursors, sorted(cursors))
        self.assertEqual(len(cursors), len(set(cursors)))
        self.assertEqual(len(cursors), 5)

    def test_cursor_is_sequence_based_not_timestamp_based(self):
        first = record_change(
            self.patient.pk,
            SyncChange.EntityType.WATER_SETTINGS,
            uuid.uuid4(),
        )
        second = record_change(
            self.patient.pk,
            SyncChange.EntityType.WATER_SETTINGS,
            uuid.uuid4(),
        )

        response = self.changes(cursor=first.sequence)
        returned = [row["cursor"] for row in response.data["changes"]]
        self.assertEqual(returned, [second.sequence])

    def test_patient_only_sees_own_changes(self):
        own = record_change(
            self.patient.pk,
            SyncChange.EntityType.WATER_SETTINGS,
            uuid.uuid4(),
        )
        record_change(
            self.other.pk,
            SyncChange.EntityType.WATER_SETTINGS,
            uuid.uuid4(),
        )

        response = self.changes()
        returned = [row["cursor"] for row in response.data["changes"]]
        self.assertEqual(returned, [own.sequence])

    def test_caregiver_feed_follows_link_and_revocation(self):
        own = record_change(
            self.patient.pk,
            SyncChange.EntityType.WATER_SETTINGS,
            uuid.uuid4(),
        )
        self.client.force_authenticate(self.caregiver)

        self.assertEqual(self.changes().data["changes"], [])

        link = link_caregiver(self.caregiver, self.patient)
        response = self.changes()
        self.assertEqual(
            [row["cursor"] for row in response.data["changes"]],
            [own.sequence],
        )

        link.is_active = False
        link.save(update_fields=["is_active"])
        self.assertEqual(self.changes().data["changes"], [])

    def test_caregiver_cannot_request_unlinked_patient(self):
        link_caregiver(self.caregiver, self.patient)
        self.client.force_authenticate(self.caregiver)
        response = self.changes(patient=self.other.pk)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_invalid_cursor_is_rejected(self):
        response = self.changes(cursor=-1)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_future_dose_is_soft_cancelled_not_deleted(self):
        medication = create_medication(self.patient)
        schedule = create_schedule(medication)
        future = create_occurrence(
            medication,
            schedule,
            scheduled_at=timezone.now() + timedelta(days=1),
        )

        regenerate_future(schedule, now=timezone.now())

        future.refresh_from_db()
        self.assertEqual(
            future.status, DoseOccurrence.Status.CANCELLED
        )
        self.assertIsNotNone(future.cancelled_at)
        self.assertTrue(
            SyncChange.objects.filter(
                entity_type=SyncChange.EntityType.DOSE_OCCURRENCE,
                object_id=future.pk,
                operation=SyncChange.Operation.UPSERT,
                data__status="cancelled",
            ).exists()
        )
        self.assertFalse(
            SyncChange.objects.filter(
                entity_type=SyncChange.EntityType.DOSE_OCCURRENCE,
                object_id=future.pk,
                operation=SyncChange.Operation.DELETE,
            ).exists()
        )

    def test_schedule_creation_feeds_generated_occurrences(self):
        medication_response = self.client.post(
            reverse("medication-list"),
            {
                "name": "Sync medication",
                "start_date": timezone.localdate().isoformat(),
            },
            format="json",
        )
        self.assertEqual(medication_response.status_code, status.HTTP_201_CREATED)
        medication_id = medication_response.data["id"]

        schedule_response = self.client.post(
            reverse("medication-schedule-list", args=[medication_id]),
            {
                "schedule_type": "fixed_times",
                "times": ["08:00"],
                "timezone": "UTC",
            },
            format="json",
        )
        self.assertEqual(schedule_response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            SyncChange.objects.filter(
                entity_type=SyncChange.EntityType.DOSE_OCCURRENCE
            ).exists()
        )
        self.assertTrue(
            SyncChange.objects.filter(
                entity_type=SyncChange.EntityType.SCHEDULE
            ).exists()
        )

    def test_dose_and_event_have_separate_ids(self):
        medication = create_medication(self.patient)
        schedule = create_schedule(medication)
        occurrence = create_occurrence(medication, schedule)
        client_event_id = uuid.uuid4()

        response = self.client.post(
            PUSH_URL,
            {
                "changes": [
                    {
                        "client_event_id": str(client_event_id),
                        "type": "dose.confirm",
                        "occurrence_id": str(occurrence.pk),
                    }
                ]
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = response.data["results"][0]
        self.assertEqual(result["status"], "applied")
        self.assertNotEqual(result["event_id"], result["occurrence_id"])

        event = DoseEvent.objects.get(pk=result["event_id"])
        self.assertEqual(event.occurrence_id, occurrence.pk)
        self.assertEqual(event.client_event_id, str(client_event_id))

        feed = self.changes(limit=200)
        event_rows = [
            row
            for row in feed.data["changes"]
            if row["entity_type"] == "dose_event"
        ]
        self.assertEqual(len(event_rows), 1)
        self.assertEqual(
            event_rows[0]["data"]["occurrence_id"], str(occurrence.pk)
        )
        self.assertEqual(event_rows[0]["data"]["event_id"], str(event.pk))


class SyncPushTests(APITestCase):
    def setUp(self):
        self.patient = create_patient()
        self.caregiver = create_caregiver()
        self.other = create_patient(email="other@example.com")
        self.medication = create_medication(self.patient)
        self.schedule = create_schedule(self.medication)
        self.occurrence = create_occurrence(self.medication, self.schedule)
        self.client.force_authenticate(self.patient)

    def push(self, *items, batch_id=None):
        payload = {"changes": list(items)}
        if batch_id:
            payload["batch_id"] = str(batch_id)
        return self.client.post(PUSH_URL, payload, format="json")

    def dose_item(self, event_type="dose.confirm", **extra):
        payload = {
            "client_event_id": str(uuid.uuid4()),
            "type": event_type,
            "occurrence_id": str(self.occurrence.pk),
        }
        payload.update(extra)
        return payload

    def water_item(self, **extra):
        payload = {
            "client_event_id": str(uuid.uuid4()),
            "type": "water.intake.create",
            "amount_ml": 250,
        }
        payload.update(extra)
        return payload

    def test_duplicate_submission_is_idempotent(self):
        item = self.dose_item()
        first = self.push(item)
        second = self.push(item)

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(first.data["results"][0]["status"], "applied")
        self.assertEqual(second.data["results"][0]["status"], "duplicate")
        self.assertEqual(
            first.data["results"][0]["event_id"],
            second.data["results"][0]["event_id"],
        )
        self.assertEqual(DoseEvent.objects.count(), 1)
        self.occurrence.refresh_from_db()
        self.assertEqual(self.occurrence.status, DoseOccurrence.Status.TAKEN)

    def test_interrupted_batch_keeps_successful_items(self):
        valid = self.dose_item()
        missing = {
            "client_event_id": str(uuid.uuid4()),
            "type": "dose.skip",
            "occurrence_id": str(uuid.uuid4()),
        }

        response = self.push(valid, missing)
        self.assertEqual(response.data["results"][0]["status"], "applied")
        self.assertEqual(response.data["results"][1]["status"], "not_found")

        retry = self.push(valid, missing)
        self.assertEqual(retry.data["results"][0]["status"], "duplicate")
        self.assertEqual(retry.data["results"][1]["status"], "not_found")
        self.assertEqual(DoseEvent.objects.count(), 1)

    def test_conflict_does_not_overwrite_newer_state(self):
        confirm = self.dose_item()
        self.push(confirm)
        skip = self.dose_item(event_type="dose.skip")
        response = self.push(skip)

        result = response.data["results"][0]
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["code"], "state_conflict")
        self.assertEqual(result["server"]["occurrence"]["status"], "taken")
        self.occurrence.refresh_from_db()
        self.assertEqual(self.occurrence.status, DoseOccurrence.Status.TAKEN)
        self.assertEqual(DoseEvent.objects.count(), 1)

    def test_expected_version_conflict_is_reported(self):
        item = self.dose_item(expected_version=999)
        response = self.push(item)

        result = response.data["results"][0]
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["code"], "version_conflict")
        self.occurrence.refresh_from_db()
        self.assertEqual(self.occurrence.status, DoseOccurrence.Status.PENDING)
        self.assertEqual(DoseEvent.objects.count(), 0)

    def test_late_event_uses_server_state_and_preserves_client_time(self):
        self.occurrence.scheduled_at = timezone.now() - timedelta(hours=2)
        self.occurrence.scheduled_date = timezone.localdate(
            self.occurrence.scheduled_at
        )
        self.occurrence.save(update_fields=["scheduled_at", "scheduled_date"])
        recorded_at = timezone.now() - timedelta(hours=2)
        item = self.dose_item(client_recorded_at=recorded_at.isoformat())

        response = self.push(item)
        result = response.data["results"][0]
        self.assertEqual(result["status"], "applied")
        event = DoseEvent.objects.get(pk=result["event_id"])
        self.assertEqual(event.event_type, DoseEvent.EventType.CONFIRMED_LATE)
        self.assertEqual(event.client_recorded_at, recorded_at)
        self.assertGreaterEqual(event.server_received_at, event.client_recorded_at)

    def test_unauthorized_occurrence_is_not_revealed(self):
        other_medication = create_medication(self.other)
        other_schedule = create_schedule(other_medication)
        other_occurrence = create_occurrence(
            other_medication, other_schedule
        )
        item = {
            "client_event_id": str(uuid.uuid4()),
            "type": "dose.confirm",
            "occurrence_id": str(other_occurrence.pk),
        }

        response = self.push(item)
        self.assertEqual(response.data["results"][0]["status"], "not_found")
        other_occurrence.refresh_from_db()
        self.assertEqual(
            other_occurrence.status, DoseOccurrence.Status.PENDING
        )

    def test_caregiver_cannot_push_dose_action(self):
        link_caregiver(self.caregiver, self.patient)
        self.client.force_authenticate(self.caregiver)
        response = self.push(self.dose_item())
        self.assertEqual(response.data["results"][0]["status"], "forbidden")
        self.occurrence.refresh_from_db()
        self.assertEqual(self.occurrence.status, DoseOccurrence.Status.PENDING)

    def test_client_event_id_cannot_be_reused_for_another_occurrence(self):
        first = self.dose_item()
        self.push(first)
        second_occurrence = create_occurrence(
            self.medication,
            self.schedule,
            scheduled_at=timezone.now() + timedelta(hours=1),
        )
        reused = {
            "client_event_id": first["client_event_id"],
            "type": "dose.confirm",
            "occurrence_id": str(second_occurrence.pk),
        }
        response = self.push(reused)
        self.assertEqual(response.data["results"][0]["status"], "conflict")
        self.assertEqual(
            response.data["results"][0]["code"], "client_event_id_reused"
        )
        second_occurrence.refresh_from_db()
        self.assertEqual(
            second_occurrence.status, DoseOccurrence.Status.PENDING
        )

    def test_water_duplicate_is_idempotent(self):
        item = self.water_item()
        first = self.push(item)
        second = self.push(item)

        self.assertEqual(first.data["results"][0]["status"], "applied")
        self.assertEqual(second.data["results"][0]["status"], "duplicate")
        self.assertEqual(WaterIntakeLog.objects.count(), 1)
        self.assertEqual(
            first.data["results"][0]["water_intake_id"],
            second.data["results"][0]["water_intake_id"],
        )

    def test_water_event_records_local_date_from_client_time(self):
        consumed_at = timezone.now() - timedelta(days=1)
        item = self.water_item(
            consumed_at=consumed_at.isoformat(), source="cup", notes="offline"
        )
        response = self.push(item)
        self.assertEqual(response.data["results"][0]["status"], "applied")
        log = WaterIntakeLog.objects.get()
        self.assertEqual(log.source, "cup")
        self.assertEqual(log.notes, "offline")
        self.assertIsNotNone(log.local_date)

    def test_caregiver_cannot_push_water_intake(self):
        self.client.force_authenticate(self.caregiver)
        response = self.push(self.water_item())
        self.assertEqual(response.data["results"][0]["status"], "forbidden")
        self.assertEqual(WaterIntakeLog.objects.count(), 0)

    def test_future_client_timestamp_is_rejected(self):
        item = self.dose_item(
            client_recorded_at=(timezone.now() + timedelta(hours=1)).isoformat()
        )
        response = self.push(item)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_batch_id_is_echoed(self):
        batch_id = uuid.uuid4()
        response = self.push(self.dose_item(), batch_id=batch_id)
        self.assertEqual(response.data["batch_id"], str(batch_id))
