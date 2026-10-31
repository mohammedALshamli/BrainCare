import threading
from unittest.mock import patch
import time as time_module
from datetime import date, datetime, timedelta, timezone as dt_timezone

from django.db import IntegrityError, OperationalError, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from apps.medications.models import DoseOccurrence
from apps.medications.services import generate_occurrences, regenerate_future
from apps.medications.tests.utils import (
    create_medication,
    create_occurrence,
    create_patient,
    create_schedule,
)


@override_settings(DOSE_GENERATION_WINDOW_DAYS=2)
class GenerationTests(TestCase):
    def setUp(self):
        self.patient = create_patient()
        self.medication = create_medication(self.patient)
        self.schedule = create_schedule(self.medication, times=["08:00"])

    def test_generation_is_idempotent(self):
        now = datetime.combine(
            timezone.localdate(), datetime.min.time(), tzinfo=dt_timezone.utc
        )
        first = generate_occurrences(self.schedule, now=now)
        second = generate_occurrences(self.schedule, now=now)

        self.assertEqual(first, 3)
        self.assertEqual(second, 0)
        self.assertEqual(
            DoseOccurrence.objects.filter(schedule=self.schedule).count(), 3
        )

    def test_database_constraint_prevents_duplicate_occurrence(self):
        generate_occurrences(self.schedule)
        existing = DoseOccurrence.objects.filter(
            schedule=self.schedule
        ).first()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                create_occurrence(
                    self.medication,
                    self.schedule,
                    scheduled_at=existing.scheduled_at,
                )

    def test_rolling_generation_adds_new_window_only(self):
        now = datetime.combine(
            timezone.localdate(), datetime.min.time(), tzinfo=dt_timezone.utc
        )
        generate_occurrences(self.schedule, window_days=1, now=now)
        self.assertEqual(
            DoseOccurrence.objects.filter(schedule=self.schedule).count(), 2
        )

        generate_occurrences(
            self.schedule, window_days=1, now=now + timedelta(days=1)
        )
        self.assertEqual(
            DoseOccurrence.objects.filter(schedule=self.schedule).count(), 3
        )

    def test_regeneration_preserves_completed_history(self):
        historical = create_occurrence(
            self.medication,
            self.schedule,
            scheduled_at=timezone.now() - timedelta(days=2),
            status=DoseOccurrence.Status.TAKEN,
            taken_at=timezone.now() - timedelta(days=2),
        )
        generate_occurrences(self.schedule)

        regenerate_future(self.schedule, remove_future_pending=True)

        self.assertTrue(
            DoseOccurrence.objects.filter(pk=historical.pk).exists()
        )

    def test_inactive_schedule_is_not_generated(self):
        self.schedule.is_active = False
        self.schedule.save(update_fields=["is_active"])

        self.assertEqual(generate_occurrences(self.schedule), 0)
        self.assertEqual(
            DoseOccurrence.objects.filter(schedule=self.schedule).count(), 0
        )

    def test_inactive_medication_is_not_generated(self):
        self.medication.is_active = False
        self.medication.save(update_fields=["is_active"])

        self.assertEqual(generate_occurrences(self.schedule), 0)

    def test_timezone_boundary_is_stored_in_utc_with_local_date(self):
        self.medication.start_date = date(2026, 3, 1)
        self.medication.save(update_fields=["start_date"])
        schedule = create_schedule(
            self.medication, times=["23:30"], timezone="America/Los_Angeles"
        )

        generate_occurrences(
            schedule,
            window_days=0,
            now=datetime(2026, 3, 1, 12, 0, tzinfo=dt_timezone.utc),
        )

        occurrence = DoseOccurrence.objects.get(schedule=schedule)
        self.assertEqual(occurrence.scheduled_date, date(2026, 3, 1))
        self.assertEqual(
            occurrence.scheduled_at,
            datetime(2026, 3, 2, 7, 30, tzinfo=dt_timezone.utc),
        )


class ConcurrentGenerationTests(TransactionTestCase):
    reset_sequences = True

    @override_settings(DOSE_GENERATION_WINDOW_DAYS=2)
    def test_concurrent_generation_does_not_duplicate_occurrences(self):
        patient = create_patient()
        medication = create_medication(patient)
        schedule = create_schedule(medication, times=["08:00"])

        barrier = threading.Barrier(2)
        errors = []
        now = datetime.combine(
            timezone.localdate(), datetime.min.time(), tzinfo=dt_timezone.utc
        )

        def worker():
            try:
                barrier.wait(timeout=10)
                for _ in range(20):
                    try:
                        generate_occurrences(schedule, now=now)
                        return
                    except OperationalError:
                        time_module.sleep(0.05)
                errors.append("database stayed locked")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertEqual(errors, [])
        self.assertEqual(
            DoseOccurrence.objects.filter(schedule=schedule).count(), 3
        )
