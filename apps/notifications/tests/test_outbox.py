from datetime import timedelta
from unittest.mock import patch

from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from apps.medications.services import confirm_dose
from apps.medications.tests.utils import (
    create_caregiver,
    create_medication,
    create_occurrence,
    create_patient,
    create_schedule,
    link_caregiver,
)
from apps.notifications.fcm import FCMNotConfigured, FCMResult
from apps.notifications.models import Device, NotificationOutbox
from apps.notifications.services import (
    dispatch_outbox,
    dispatch_pending_notifications,
    enqueue_dose_overdue_notifications,
    enqueue_notification,
    register_device,
)
from apps.notifications.tasks import dispatch_notification


class OutboxTestBase(TestCase):
    def setUp(self):
        self.patient = create_patient()
        self.caregiver = create_caregiver()
        self.link = link_caregiver(self.caregiver, self.patient)
        self.device = register_device(
            self.caregiver,
            {
                "fcm_token": "caregiver-token-0123456789abcdef",
                "platform": "android",
                "device_identifier": "caregiver-phone",
            },
        )
        self.medication = create_medication(self.patient)
        self.schedule = create_schedule(self.medication)
        self.occurrence = create_occurrence(
            self.medication,
            self.schedule,
            scheduled_at=timezone.now() - timedelta(hours=1),
        )

    def make_outbox(self, key="test-key", **overrides):
        defaults = {
            "idempotency_key": key,
            "recipient": self.caregiver,
            "patient": self.patient,
            "notification_type": NotificationOutbox.NotificationType.DOSE_OVERDUE,
            "payload": {
                "title": "Medication reminder",
                "body": "A scheduled dose is overdue.",
                "data": {"type": "dose_overdue"},
            },
        }
        defaults.update(overrides)
        return NotificationOutbox.objects.create(**defaults)


class OutboxCreationTests(OutboxTestBase):
    def test_duplicate_idempotency_key_creates_one_record(self):
        first, created_first = enqueue_notification(
            idempotency_key="dose-1-caregiver-1",
            recipient=self.caregiver,
            patient=self.patient,
            notification_type=NotificationOutbox.NotificationType.DOSE_OVERDUE,
        )
        second, created_second = enqueue_notification(
            idempotency_key="dose-1-caregiver-1",
            recipient=self.caregiver,
            patient=self.patient,
            notification_type=NotificationOutbox.NotificationType.DOSE_OVERDUE,
        )

        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(NotificationOutbox.objects.count(), 1)

    def test_overdue_enqueue_respects_caregiver_preferences(self):
        self.link.notify_missed_doses = False
        self.link.save(update_fields=["notify_missed_doses"])

        created = enqueue_dose_overdue_notifications(self.occurrence)
        self.assertEqual(created, [])
        self.assertEqual(NotificationOutbox.objects.count(), 0)

        self.link.notify_missed_doses = True
        self.link.save(update_fields=["notify_missed_doses"])
        created = enqueue_dose_overdue_notifications(self.occurrence)
        self.assertEqual(len(created), 1)

        again = enqueue_dose_overdue_notifications(self.occurrence)
        self.assertEqual(again, [])
        self.assertEqual(NotificationOutbox.objects.count(), 1)

    def test_outbox_rolls_back_with_its_transaction(self):
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                enqueue_notification(
                    idempotency_key="rollback-key",
                    recipient=self.caregiver,
                    patient=self.patient,
                    notification_type=(
                        NotificationOutbox.NotificationType.DOSE_OVERDUE
                    ),
                )
                raise RuntimeError("rollback")
        self.assertEqual(NotificationOutbox.objects.count(), 0)

    def test_broker_outage_leaves_outbox_pending(self):
        with patch(
            "apps.notifications.tasks.dispatch_notification.delay",
            side_effect=RuntimeError("redis unavailable"),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                outbox, _ = enqueue_notification(
                    idempotency_key="broker-down",
                    recipient=self.caregiver,
                    patient=self.patient,
                    notification_type=(
                        NotificationOutbox.NotificationType.DOSE_OVERDUE
                    ),
                )

        outbox.refresh_from_db()
        self.assertEqual(outbox.status, NotificationOutbox.Status.PENDING)
        self.assertEqual(NotificationOutbox.objects.count(), 1)

    def test_overdue_enqueue_skips_revoked_links(self):
        self.link.is_active = False
        self.link.save(update_fields=["is_active"])

        created = enqueue_dose_overdue_notifications(self.occurrence)
        self.assertEqual(created, [])

    def test_payload_does_not_contain_medication_details(self):
        outbox = enqueue_dose_overdue_notifications(self.occurrence)[0]
        body = str(outbox.payload).lower()
        self.assertNotIn("test medication", body)
        self.assertNotIn("500 mg", body)


class DispatchTests(OutboxTestBase):
    def test_successful_dispatch_is_accepted_not_delivered(self):
        outbox = self.make_outbox()
        with patch(
            "apps.notifications.services.send_push",
            return_value=[
                FCMResult(token=self.device.get_fcm_token(), success=True)
            ],
        ) as sender:
            result = dispatch_outbox(outbox.pk)

        self.assertEqual(result, "accepted")
        outbox.refresh_from_db()
        self.assertEqual(outbox.status, NotificationOutbox.Status.ACCEPTED)
        self.assertIsNotNone(outbox.accepted_at)
        self.assertEqual(outbox.attempts, 1)
        self.assertFalse(hasattr(outbox, "delivered_at"))
        sender.assert_called_once()

    def test_duplicate_dispatch_does_not_send_twice(self):
        outbox = self.make_outbox()
        with patch(
            "apps.notifications.services.send_push",
            return_value=[
                FCMResult(token=self.device.get_fcm_token(), success=True)
            ],
        ) as sender:
            dispatch_outbox(outbox.pk)
            second = dispatch_outbox(outbox.pk)

        self.assertEqual(second, "already_accepted")
        self.assertEqual(sender.call_count, 1)

    def test_transient_failure_is_retried_with_backoff(self):
        outbox = self.make_outbox()
        with patch(
            "apps.notifications.services.send_push",
            return_value=[
                FCMResult(
                    token=self.device.get_fcm_token(),
                    success=False,
                    retryable=True,
                    error_code="UnavailableError",
                )
            ],
        ):
            result = dispatch_outbox(outbox.pk)

        self.assertEqual(result, "retry")
        outbox.refresh_from_db()
        self.assertEqual(outbox.status, NotificationOutbox.Status.PENDING)
        self.assertEqual(outbox.attempts, 1)
        self.assertGreater(outbox.next_attempt_at, timezone.now())
        self.assertEqual(outbox.last_error, "provider_transient")

    def test_retry_can_succeed_after_backoff(self):
        outbox = self.make_outbox()
        with patch(
            "apps.notifications.services.send_push",
            return_value=[
                FCMResult(
                    token=self.device.get_fcm_token(),
                    success=False,
                    retryable=True,
                )
            ],
        ):
            dispatch_outbox(outbox.pk)
        outbox.refresh_from_db()

        with patch(
            "apps.notifications.services.send_push",
            return_value=[
                FCMResult(token=self.device.get_fcm_token(), success=True)
            ],
        ):
            result = dispatch_outbox(
                outbox.pk, now=outbox.next_attempt_at + timedelta(seconds=1)
            )

        self.assertEqual(result, "accepted")
        outbox.refresh_from_db()
        self.assertEqual(outbox.status, NotificationOutbox.Status.ACCEPTED)
        self.assertEqual(outbox.attempts, 2)

    def test_permanent_failure_is_dead_lettered(self):
        outbox = self.make_outbox()
        with patch(
            "apps.notifications.services.send_push",
            return_value=[
                FCMResult(
                    token=self.device.get_fcm_token(),
                    success=False,
                    invalid_token=True,
                    error_code="UnregisteredError",
                )
            ],
        ):
            result = dispatch_outbox(outbox.pk)

        self.assertEqual(result, "dead_letter")
        outbox.refresh_from_db()
        self.assertEqual(outbox.status, NotificationOutbox.Status.DEAD_LETTER)
        self.device.refresh_from_db()
        self.assertFalse(self.device.is_active)

    def test_no_active_devices_dead_letters(self):
        Device.objects.filter(pk=self.device.pk).update(is_active=False)
        outbox = self.make_outbox()

        result = dispatch_outbox(outbox.pk)
        self.assertEqual(result, "no_active_devices")
        outbox.refresh_from_db()
        self.assertEqual(outbox.status, NotificationOutbox.Status.DEAD_LETTER)

    def test_fcm_not_configured_is_dead_lettered(self):
        outbox = self.make_outbox()
        with patch(
            "apps.notifications.services.send_push",
            side_effect=FCMNotConfigured("FCM is disabled."),
        ):
            result = dispatch_outbox(outbox.pk)

        self.assertEqual(result, "fcm_not_configured")
        outbox.refresh_from_db()
        self.assertEqual(outbox.status, NotificationOutbox.Status.DEAD_LETTER)

    def test_unexpected_provider_exception_is_retried(self):
        outbox = self.make_outbox()
        with patch(
            "apps.notifications.services.send_push",
            side_effect=Exception("provider down"),
        ):
            result = dispatch_outbox(outbox.pk)

        self.assertEqual(result, "provider_exception")
        outbox.refresh_from_db()
        self.assertEqual(outbox.status, NotificationOutbox.Status.PENDING)

    def test_stale_processing_row_is_recovered(self):
        outbox = self.make_outbox()
        NotificationOutbox.objects.filter(pk=outbox.pk).update(
            status=NotificationOutbox.Status.PROCESSING,
            attempts=1,
            processing_started_at=timezone.now() - timedelta(hours=1),
        )

        with patch(
            "apps.notifications.services.send_push",
            return_value=[
                FCMResult(token=self.device.get_fcm_token(), success=True)
            ],
        ):
            dispatched = dispatch_pending_notifications()

        self.assertEqual(dispatched, 1)
        outbox.refresh_from_db()
        self.assertEqual(outbox.status, NotificationOutbox.Status.ACCEPTED)

    def test_stale_overdue_outbox_suppressed_if_dose_confirmed_before_dispatch(
        self,
    ):
        outbox = enqueue_dose_overdue_notifications(self.occurrence)[0]
        confirm_dose(
            self.occurrence,
            actor=self.patient,
            client_event_id="confirmed-before-dispatch",
        )

        with patch(
            "apps.notifications.services.send_push"
        ) as sender:
            result = dispatch_outbox(outbox.pk)

        self.assertEqual(result, "suppressed_stale")
        outbox.refresh_from_db()
        self.assertEqual(
            outbox.status, NotificationOutbox.Status.SUPPRESSED
        )
        self.assertEqual(
            outbox.suppression_reason, "stale_dose_already_resolved"
        )
        self.assertIsNotNone(outbox.suppressed_at)
        sender.assert_not_called()

    def test_duplicate_task_execution_does_not_send_two_notifications(self):
        outbox = self.make_outbox()
        with patch(
            "apps.notifications.services.send_push",
            return_value=[
                FCMResult(token=self.device.get_fcm_token(), success=True)
            ],
        ) as sender:
            dispatch_notification.apply(args=[str(outbox.pk)]).get()
            dispatch_notification.apply(args=[str(outbox.pk)]).get()

        self.assertEqual(sender.call_count, 1)
        outbox.refresh_from_db()
        self.assertEqual(
            outbox.status, NotificationOutbox.Status.ACCEPTED
        )

    def test_max_attempts_are_enforced(self):
        outbox = self.make_outbox(max_attempts=1)
        with patch(
            "apps.notifications.services.send_push",
            return_value=[
                FCMResult(
                    token=self.device.get_fcm_token(),
                    success=False,
                    retryable=True,
                )
            ],
        ):
            result = dispatch_outbox(outbox.pk)

        self.assertEqual(result, "retry")
        outbox.refresh_from_db()
        self.assertEqual(outbox.status, NotificationOutbox.Status.DEAD_LETTER)
