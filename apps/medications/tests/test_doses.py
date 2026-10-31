import threading
import time as time_module
from datetime import timedelta

from django.db import OperationalError, connections
from django.urls import reverse
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.medications.models import DoseEvent, DoseOccurrence
from apps.medications.services import confirm_dose, mark_overdue_doses
from apps.medications.tests.utils import (
    add_event,
    create_caregiver,
    create_medication,
    create_occurrence,
    create_patient,
    create_schedule,
    link_caregiver,
)


class DoseActionTestCase(APITestCase):
    def setUp(self):
        self.patient = create_patient()
        self.client.force_authenticate(self.patient)
        self.medication = create_medication(self.patient)
        self.schedule = create_schedule(self.medication)
        self.occurrence = create_occurrence(
            self.medication, self.schedule, scheduled_at=timezone.now()
        )

    def action(self, name, occurrence=None, **payload):
        occurrence = occurrence or self.occurrence
        return self.client.post(
            reverse(name, args=[occurrence.pk]), payload, format="json"
        )


class ConfirmDoseTests(DoseActionTestCase):
    def test_confirm_pending_dose(self):
        response = self.action(
            "dose-confirm", client_event_id="evt-1", source="patient_app"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.occurrence.refresh_from_db()
        self.assertEqual(self.occurrence.status, DoseOccurrence.Status.TAKEN)
        self.assertIsNotNone(self.occurrence.taken_at)

        event = self.occurrence.events.get()
        self.assertEqual(event.event_type, DoseEvent.EventType.TAKEN)
        self.assertEqual(event.actor, self.patient)
        self.assertEqual(event.client_event_id, "evt-1")
        self.assertEqual(event.source, DoseEvent.Source.PATIENT_APP)
        self.assertIsNotNone(event.server_received_at)

    def test_confirm_is_idempotent_for_same_client_event_id(self):
        first = self.action("dose-confirm", client_event_id="evt-1")
        second = self.action("dose-confirm", client_event_id="evt-1")

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(self.occurrence.events.count(), 1)

    def test_confirm_after_taken_with_new_event_id_does_not_duplicate(self):
        self.action("dose-confirm", client_event_id="evt-1")
        response = self.action("dose-confirm", client_event_id="evt-2")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.occurrence.events.count(), 1)

    def test_confirm_requires_client_event_id(self):
        response = self.action("dose-confirm", source="patient_app")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(
            "client_event_id", response.data["error"]["details"]
        )

    def test_confirm_rejects_server_only_source(self):
        response = self.action(
            "dose-confirm", client_event_id="evt-1", source="system"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_confirm_after_skip_conflicts(self):
        self.action("dose-skip", client_event_id="evt-skip")
        response = self.action("dose-confirm", client_event_id="evt-confirm")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["error"]["code"], "conflict")

    def test_late_confirmation_is_recorded_without_losing_alert_history(self):
        late = create_occurrence(
            self.medication,
            self.schedule,
            scheduled_at=timezone.now() - timedelta(hours=1),
            status=DoseOccurrence.Status.OVERDUE_UNCONFIRMED,
            alert_status=DoseOccurrence.AlertStatus.SENT,
        )
        escalation = add_event(
            late, DoseEvent.EventType.ESCALATION_SENT
        )

        response = self.action(
            "dose-confirm", occurrence=late, client_event_id="evt-late"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        late.refresh_from_db()
        self.assertEqual(late.status, DoseOccurrence.Status.TAKEN)
        self.assertEqual(late.alert_status, DoseOccurrence.AlertStatus.SENT)
        self.assertTrue(
            late.events.filter(
                event_type=DoseEvent.EventType.CONFIRMED_LATE
            ).exists()
        )
        self.assertTrue(
            late.events.filter(pk=escalation.pk).exists()
        )

    def test_client_event_id_cannot_be_reused_for_another_dose(self):
        other = create_occurrence(
            self.medication,
            self.schedule,
            scheduled_at=timezone.now() + timedelta(days=1),
        )
        self.action("dose-confirm", client_event_id="evt-shared")
        response = self.action(
            "dose-confirm", occurrence=other, client_event_id="evt-shared"
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)


class SkipDoseTests(DoseActionTestCase):
    def test_skip_pending_dose(self):
        response = self.action("dose-skip", client_event_id="evt-skip")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.occurrence.refresh_from_db()
        self.assertEqual(self.occurrence.status, DoseOccurrence.Status.SKIPPED)
        self.assertIsNotNone(self.occurrence.skipped_at)
        self.assertEqual(
            self.occurrence.events.get().event_type,
            DoseEvent.EventType.SKIPPED,
        )

    def test_skip_is_idempotent(self):
        self.action("dose-skip", client_event_id="evt-skip")
        response = self.action("dose-skip", client_event_id="evt-skip")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.occurrence.events.count(), 1)

    def test_skip_after_taken_conflicts(self):
        self.action("dose-confirm", client_event_id="evt-taken")
        response = self.action("dose-skip", client_event_id="evt-skip")
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)


class SnoozeDoseTests(DoseActionTestCase):
    def test_snooze_pending_dose(self):
        response = self.action(
            "dose-snooze", client_event_id="evt-snooze", minutes=15
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.occurrence.refresh_from_db()
        self.assertEqual(self.occurrence.status, DoseOccurrence.Status.PENDING)
        self.assertIsNotNone(self.occurrence.snoozed_until)
        self.assertEqual(self.occurrence.snooze_count, 1)

        event = self.occurrence.events.get()
        self.assertEqual(event.event_type, DoseEvent.EventType.SNOOZED)
        self.assertEqual(event.payload["minutes"], 15)

    def test_snooze_after_overdue_returns_to_pending(self):
        overdue = create_occurrence(
            self.medication,
            self.schedule,
            scheduled_at=timezone.now() - timedelta(hours=2),
            status=DoseOccurrence.Status.OVERDUE_UNCONFIRMED,
        )
        response = self.action(
            "dose-snooze",
            occurrence=overdue,
            client_event_id="evt-snooze",
            minutes=10,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        overdue.refresh_from_db()
        self.assertEqual(overdue.status, DoseOccurrence.Status.PENDING)
        self.assertGreater(overdue.snoozed_until, timezone.now())

    def test_snooze_completed_dose_conflicts(self):
        self.action("dose-confirm", client_event_id="evt-taken")
        response = self.action(
            "dose-snooze", client_event_id="evt-snooze", minutes=10
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_snooze_minutes_are_bounded(self):
        response = self.action(
            "dose-snooze", client_event_id="evt-snooze", minutes=99999
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class DoseAccessTests(DoseActionTestCase):
    def test_linked_caregiver_can_read_but_not_act(self):
        caregiver = create_caregiver()
        link_caregiver(caregiver, self.patient)
        self.client.force_authenticate(caregiver)

        detail = self.client.get(
            reverse("dose-detail", args=[self.occurrence.pk])
        )
        confirm = self.action("dose-confirm", client_event_id="evt-care")

        self.assertEqual(detail.status_code, status.HTTP_200_OK)
        self.assertEqual(confirm.status_code, status.HTTP_403_FORBIDDEN)

    def test_other_patient_cannot_read_or_act(self):
        other = create_patient(email="other@example.com")
        self.client.force_authenticate(other)

        detail = self.client.get(
            reverse("dose-detail", args=[self.occurrence.pk])
        )
        confirm = self.action("dose-confirm", client_event_id="evt-other")

        self.assertEqual(detail.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(confirm.status_code, status.HTTP_404_NOT_FOUND)

    def test_event_history_is_available_to_linked_caregiver(self):
        self.action("dose-confirm", client_event_id="evt-1")
        caregiver = create_caregiver()
        link_caregiver(caregiver, self.patient)
        self.client.force_authenticate(caregiver)

        response = self.client.get(
            reverse("dose-events", args=[self.occurrence.pk])
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["event_type"],
            DoseEvent.EventType.TAKEN,
        )


class OverdueTests(APITestCase):
    def setUp(self):
        self.patient = create_patient()
        self.medication = create_medication(self.patient)
        self.schedule = create_schedule(self.medication)

    def test_overdue_marks_only_unconfirmed_doses_past_grace(self):
        now = timezone.now()
        due = create_occurrence(
            self.medication,
            self.schedule,
            scheduled_at=now - timedelta(minutes=31),
        )
        not_due = create_occurrence(
            self.medication,
            self.schedule,
            scheduled_at=now - timedelta(minutes=10),
        )
        snoozed = create_occurrence(
            self.medication,
            self.schedule,
            scheduled_at=now - timedelta(minutes=32),
            snoozed_until=now + timedelta(minutes=10),
        )

        marked = mark_overdue_doses(grace_minutes=30, now=now)

        self.assertEqual(marked, 1)
        due.refresh_from_db()
        not_due.refresh_from_db()
        snoozed.refresh_from_db()
        self.assertEqual(
            due.status, DoseOccurrence.Status.OVERDUE_UNCONFIRMED
        )
        self.assertEqual(not_due.status, DoseOccurrence.Status.PENDING)
        self.assertEqual(snoozed.status, DoseOccurrence.Status.PENDING)
        self.assertEqual(due.alert_status, DoseOccurrence.AlertStatus.NONE)
        self.assertTrue(
            due.events.filter(event_type=DoseEvent.EventType.OVERDUE).exists()
        )

    def test_overdue_marking_is_idempotent(self):
        now = timezone.now()
        create_occurrence(
            self.medication,
            self.schedule,
            scheduled_at=now - timedelta(minutes=31),
        )

        self.assertEqual(mark_overdue_doses(grace_minutes=30, now=now), 1)
        self.assertEqual(mark_overdue_doses(grace_minutes=30, now=now), 0)

    def test_overdue_does_not_touch_taken_or_skipped(self):
        now = timezone.now()
        taken = create_occurrence(
            self.medication,
            self.schedule,
            scheduled_at=now - timedelta(hours=2),
            status=DoseOccurrence.Status.TAKEN,
            taken_at=now - timedelta(hours=2),
        )
        skipped = create_occurrence(
            self.medication,
            self.schedule,
            scheduled_at=now - timedelta(hours=3),
            status=DoseOccurrence.Status.SKIPPED,
            skipped_at=now - timedelta(hours=3),
        )

        self.assertEqual(mark_overdue_doses(grace_minutes=30, now=now), 0)
        taken.refresh_from_db()
        skipped.refresh_from_db()
        self.assertEqual(taken.status, DoseOccurrence.Status.TAKEN)
        self.assertEqual(skipped.status, DoseOccurrence.Status.SKIPPED)


class DoseHistoryTests(DoseActionTestCase):
    def test_retrieve_dose_status(self):
        response = self.client.get(
            reverse("dose-detail", args=[self.occurrence.pk])
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], DoseOccurrence.Status.PENDING)
        self.assertEqual(
            response.data["alert_status"], DoseOccurrence.AlertStatus.NONE
        )

    def test_list_history_filter_and_order(self):
        taken = create_occurrence(
            self.medication,
            self.schedule,
            scheduled_at=timezone.now() - timedelta(days=1),
            status=DoseOccurrence.Status.TAKEN,
            taken_at=timezone.now() - timedelta(days=1),
        )
        create_occurrence(
            self.medication,
            self.schedule,
            scheduled_at=timezone.now() + timedelta(days=1),
        )

        response = self.client.get(
            reverse("dose-list"), {"status": "taken", "ordering": "scheduled_at"}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], str(taken.pk))

    def test_filter_by_local_date_range(self):
        response = self.client.get(
            reverse("dose-list"),
            {
                "from_date": timezone.localdate().isoformat(),
                "to_date": timezone.localdate().isoformat(),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(response.data["count"], 1)


class ConcurrentConfirmationTests(TransactionTestCase):
    def test_concurrent_confirmations_create_one_event(self):
        patient = create_patient()
        medication = create_medication(patient)
        schedule = create_schedule(medication)
        occurrence = create_occurrence(
            medication, schedule, scheduled_at=timezone.now()
        )

        barrier = threading.Barrier(2)
        errors = []

        def worker(index):
            try:
                barrier.wait(timeout=10)
                for _ in range(20):
                    try:
                        confirm_dose(
                            occurrence,
                            actor=patient,
                            client_event_id=f"evt-{index}",
                        )
                        return
                    except OperationalError:
                        time_module.sleep(0.05)
                errors.append("database stayed locked")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                connections.close_all()

        threads = [
            threading.Thread(target=worker, args=(index,))
            for index in range(2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertEqual(errors, [])
        occurrence.refresh_from_db()
        self.assertEqual(occurrence.status, DoseOccurrence.Status.TAKEN)
        self.assertEqual(occurrence.events.count(), 1)
