from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.medications.models import DoseEvent, DoseOccurrence
from apps.medications.services import confirm_dose, mark_overdue_doses
from apps.medications.tests.utils import (
    create_caregiver,
    create_medication,
    create_occurrence,
    create_patient,
    create_schedule,
    link_caregiver,
)
from apps.notifications.models import NotificationOutbox


class MissedDoseEscalationTests(TestCase):
    def setUp(self):
        self.patient = create_patient()
        self.caregiver = create_caregiver()
        self.link = link_caregiver(self.caregiver, self.patient)
        self.medication = create_medication(self.patient)
        self.schedule = create_schedule(self.medication)

    def make_occurrence(self, minutes_ago=31):
        return create_occurrence(
            self.medication,
            self.schedule,
            scheduled_at=timezone.now() - timedelta(minutes=minutes_ago),
        )

    def test_overdue_creates_one_outbox_per_caregiver(self):
        occurrence = self.make_occurrence()
        marked = mark_overdue_doses(grace_minutes=30)

        self.assertEqual(marked, 1)
        occurrence.refresh_from_db()
        self.assertEqual(
            occurrence.status, DoseOccurrence.Status.OVERDUE_UNCONFIRMED
        )
        self.assertEqual(
            occurrence.alert_status, DoseOccurrence.AlertStatus.NONE
        )
        self.assertEqual(NotificationOutbox.objects.count(), 1)
        outbox = NotificationOutbox.objects.get()
        self.assertEqual(outbox.recipient, self.caregiver)
        self.assertEqual(
            outbox.notification_type,
            NotificationOutbox.NotificationType.DOSE_OVERDUE,
        )
        self.assertIn(str(occurrence.pk), outbox.idempotency_key)
        self.assertTrue(
            occurrence.events.filter(
                event_type=DoseEvent.EventType.OVERDUE
            ).exists()
        )

    def test_repeated_job_execution_does_not_duplicate_alerts(self):
        self.make_occurrence()
        self.assertEqual(mark_overdue_doses(grace_minutes=30), 1)
        self.assertEqual(mark_overdue_doses(grace_minutes=30), 0)
        self.assertEqual(NotificationOutbox.objects.count(), 1)

    def test_notification_preferences_are_respected(self):
        self.link.notify_missed_doses = False
        self.link.save(update_fields=["notify_missed_doses"])
        self.make_occurrence()

        self.assertEqual(mark_overdue_doses(grace_minutes=30), 1)
        self.assertEqual(NotificationOutbox.objects.count(), 0)

    def test_revoked_or_unviewable_caregivers_are_not_notified(self):
        self.link.can_view = False
        self.link.save(update_fields=["can_view"])
        self.make_occurrence()

        mark_overdue_doses(grace_minutes=30)
        self.assertEqual(NotificationOutbox.objects.count(), 0)

    def test_grace_boundary_is_inclusive_and_future_dose_is_not_marked(self):
        now = timezone.now()
        exactly_due = create_occurrence(
            self.medication,
            self.schedule,
            scheduled_at=now - timedelta(minutes=30),
        )
        not_due = create_occurrence(
            self.medication,
            self.schedule,
            scheduled_at=now - timedelta(minutes=29, seconds=59),
        )

        marked = mark_overdue_doses(grace_minutes=30, now=now)
        self.assertEqual(marked, 1)
        exactly_due.refresh_from_db()
        not_due.refresh_from_db()
        self.assertEqual(
            exactly_due.status, DoseOccurrence.Status.OVERDUE_UNCONFIRMED
        )
        self.assertEqual(not_due.status, DoseOccurrence.Status.PENDING)

    def test_late_confirmation_preserves_history_and_outbox(self):
        occurrence = self.make_occurrence()
        mark_overdue_doses(grace_minutes=30)
        outbox = NotificationOutbox.objects.get()

        confirmed, event = confirm_dose(
            occurrence,
            actor=self.patient,
            client_event_id="late-confirm-1",
        )

        self.assertEqual(confirmed.status, DoseOccurrence.Status.TAKEN)
        self.assertEqual(event.event_type, DoseEvent.EventType.CONFIRMED_LATE)
        self.assertEqual(
            occurrence.events.filter(
                event_type=DoseEvent.EventType.OVERDUE
            ).count(),
            1,
        )
        self.assertTrue(
            occurrence.events.filter(
                event_type=DoseEvent.EventType.CONFIRMED_LATE
            ).exists()
        )
        outbox.refresh_from_db()
        self.assertIn(
            outbox.status,
            {
                NotificationOutbox.Status.PENDING,
                NotificationOutbox.Status.ACCEPTED,
            },
        )
