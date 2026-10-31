from datetime import date, datetime, timedelta, timezone as dt_timezone

from django.test import TestCase

from apps.medications.models import MedicationSchedule
from apps.medications.recurrence import iter_occurrences
from apps.medications.tests.utils import (
    create_medication,
    create_patient,
    create_schedule,
)


class FixedRecurrenceTests(TestCase):
    def setUp(self):
        self.patient = create_patient()
        self.medication = create_medication(
            self.patient, start_date=date(2026, 3, 1)
        )

    def test_fixed_times_returns_utc_instants(self):
        schedule = create_schedule(
            self.medication, times=["08:00", "20:00"], timezone="UTC"
        )
        occurrences = list(
            iter_occurrences(schedule, date(2026, 3, 1), date(2026, 3, 2))
        )

        self.assertEqual(len(occurrences), 4)
        self.assertEqual(
            occurrences[0][0],
            datetime(2026, 3, 1, 8, 0, tzinfo=dt_timezone.utc),
        )
        self.assertEqual(occurrences[0][1], date(2026, 3, 1))
        for instant, _ in occurrences:
            self.assertEqual(instant.utcoffset(), timedelta(0))

    def test_end_date_caps_occurrences(self):
        self.medication.end_date = date(2026, 3, 2)
        self.medication.save(update_fields=["end_date"])
        schedule = create_schedule(self.medication, times=["08:00"])

        occurrences = list(
            iter_occurrences(schedule, date(2026, 3, 1), date(2026, 3, 5))
        )
        self.assertEqual(len(occurrences), 2)
        self.assertEqual(occurrences[-1][1], date(2026, 3, 2))

    def test_timezone_boundary_uses_local_date(self):
        schedule = create_schedule(
            self.medication, times=["23:30"], timezone="America/Los_Angeles"
        )
        occurrences = list(
            iter_occurrences(schedule, date(2026, 3, 1), date(2026, 3, 1))
        )

        self.assertEqual(len(occurrences), 1)
        instant, local_date = occurrences[0]
        self.assertEqual(local_date, date(2026, 3, 1))
        self.assertEqual(
            instant,
            datetime(2026, 3, 2, 7, 30, tzinfo=dt_timezone.utc),
        )

    def test_spring_forward_nonexistent_local_time(self):
        self.medication.start_date = date(2026, 3, 8)
        self.medication.save(update_fields=["start_date"])
        schedule = create_schedule(
            self.medication,
            times=["02:30"],
            timezone="America/New_York",
        )

        occurrences = list(
            iter_occurrences(schedule, date(2026, 3, 8), date(2026, 3, 8))
        )
        self.assertEqual(len(occurrences), 1)
        self.assertEqual(
            occurrences[0][0],
            datetime(2026, 3, 8, 7, 30, tzinfo=dt_timezone.utc),
        )

    def test_fall_back_ambiguous_local_time(self):
        self.medication.start_date = date(2026, 11, 1)
        self.medication.save(update_fields=["start_date"])
        schedule = create_schedule(
            self.medication,
            times=["01:30"],
            timezone="America/New_York",
        )

        occurrences = list(
            iter_occurrences(schedule, date(2026, 11, 1), date(2026, 11, 1))
        )
        self.assertEqual(len(occurrences), 1)
        self.assertEqual(
            occurrences[0][0],
            datetime(2026, 11, 1, 5, 30, tzinfo=dt_timezone.utc),
        )


class WeekdayRecurrenceTests(TestCase):
    def test_only_selected_weekdays_are_generated(self):
        patient = create_patient()
        medication = create_medication(
            patient, start_date=date(2026, 3, 2)
        )
        schedule = create_schedule(
            medication,
            schedule_type=MedicationSchedule.ScheduleType.WEEKDAYS,
            times=["09:00"],
            weekdays=[0, 2],
            timezone="UTC",
        )

        occurrences = list(
            iter_occurrences(schedule, date(2026, 3, 2), date(2026, 3, 8))
        )
        self.assertEqual(len(occurrences), 2)
        self.assertEqual(
            [local_date for _, local_date in occurrences],
            [date(2026, 3, 2), date(2026, 3, 4)],
        )


class IntervalRecurrenceTests(TestCase):
    def setUp(self):
        self.patient = create_patient()
        self.medication = create_medication(
            self.patient, start_date=date(2026, 3, 1)
        )

    def test_interval_steps_by_absolute_hours(self):
        schedule = create_schedule(
            self.medication,
            schedule_type=MedicationSchedule.ScheduleType.INTERVAL_HOURS,
            times=[],
            interval_hours=6,
            anchor_time=datetime.min.time(),
            timezone="UTC",
        )
        occurrences = list(
            iter_occurrences(schedule, date(2026, 3, 1), date(2026, 3, 1))
        )
        self.assertEqual(len(occurrences), 4)
        self.assertEqual(
            [instant.hour for instant, _ in occurrences], [0, 6, 12, 18]
        )

    def test_interval_across_spring_forward_keeps_absolute_spacing(self):
        self.medication.start_date = date(2026, 3, 7)
        self.medication.save(update_fields=["start_date"])
        schedule = create_schedule(
            self.medication,
            schedule_type=MedicationSchedule.ScheduleType.INTERVAL_HOURS,
            times=[],
            interval_hours=24,
            anchor_time=datetime.min.time(),
            timezone="America/New_York",
        )

        occurrences = list(
            iter_occurrences(schedule, date(2026, 3, 7), date(2026, 3, 9))
        )
        self.assertEqual(len(occurrences), 3)
        instants = [instant for instant, _ in occurrences]
        for previous, current in zip(instants, instants[1:]):
            self.assertEqual(current - previous, timedelta(hours=24))
        self.assertEqual(
            instants[0], datetime(2026, 3, 7, 5, 0, tzinfo=dt_timezone.utc)
        )
