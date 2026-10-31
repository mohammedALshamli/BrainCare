from datetime import datetime, time, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.medications.models import DoseOccurrence, MedicationSchedule
from apps.medications.tests.utils import (
    create_caregiver,
    create_medication,
    create_occurrence,
    create_patient,
    create_schedule,
    link_caregiver,
)


def fixed_now():
    return datetime.combine(
        timezone.localdate(), time(0, 0), tzinfo=dt_timezone.utc
    )


def schedule_payload(**overrides):
    data = {
        "schedule_type": "fixed_times",
        "times": ["08:00", "20:00"],
        "timezone": "UTC",
    }
    data.update(overrides)
    return data


@override_settings(DOSE_GENERATION_WINDOW_DAYS=2)
class ScheduleCreateTests(APITestCase):
    def setUp(self):
        self.patient = create_patient()
        self.client.force_authenticate(self.patient)
        self.medication = create_medication(self.patient)
        self.url = reverse(
            "medication-schedule-list",
            args=[self.medication.pk],
        )

    def test_create_fixed_schedule_generates_occurrences(self):
        with patch(
            "django.utils.timezone.now", return_value=fixed_now()
        ):
            response = self.client.post(
                self.url, schedule_payload(), format="json"
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        schedule = MedicationSchedule.objects.get(pk=response.data["id"])
        self.assertEqual(schedule.timezone, "UTC")
        self.assertEqual(
            DoseOccurrence.objects.filter(schedule=schedule).count(), 6
        )
        first = schedule.dose_occurrences.order_by("scheduled_at").first()
        self.assertEqual(first.scheduled_at.utcoffset(), timedelta(0))

    def test_create_weekday_schedule(self):
        today = timezone.localdate()
        with patch(
            "django.utils.timezone.now", return_value=fixed_now()
        ):
            response = self.client.post(
                self.url,
                schedule_payload(
                    schedule_type="weekdays",
                    times=["09:00"],
                    weekdays=[today.weekday()],
                ),
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        schedule = MedicationSchedule.objects.get(pk=response.data["id"])
        occurrences = schedule.dose_occurrences.all()
        self.assertGreater(occurrences.count(), 0)
        for occurrence in occurrences:
            self.assertEqual(occurrence.scheduled_date.weekday(), today.weekday())

    def test_create_interval_schedule(self):
        with patch(
            "django.utils.timezone.now", return_value=fixed_now()
        ):
            response = self.client.post(
                self.url,
                schedule_payload(
                    schedule_type="interval_hours",
                    times=[],
                    interval_hours=6,
                    anchor_time="00:00",
                ),
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        schedule = MedicationSchedule.objects.get(pk=response.data["id"])
        occurrences = list(
            schedule.dose_occurrences.order_by("scheduled_at").values_list(
                "scheduled_at", flat=True
            )
        )
        self.assertEqual(len(occurrences), 12)
        self.assertEqual(
            occurrences[1] - occurrences[0], timedelta(hours=6)
        )

    def test_fixed_schedule_requires_times(self):
        response = self.client.post(
            self.url, schedule_payload(times=[]), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("times", response.data["error"]["details"])

    def test_weekday_schedule_requires_weekdays(self):
        response = self.client.post(
            self.url,
            schedule_payload(
                schedule_type="weekdays", times=["09:00"], weekdays=[]
            ),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("weekdays", response.data["error"]["details"])

    def test_interval_must_be_between_one_and_24_hours(self):
        for interval in (0, 25):
            response = self.client.post(
                self.url,
                schedule_payload(
                    schedule_type="interval_hours",
                    times=[],
                    interval_hours=interval,
                ),
                format="json",
            )
            self.assertEqual(
                response.status_code, status.HTTP_400_BAD_REQUEST, interval
            )
            self.assertIn("interval_hours", response.data["error"]["details"])

    def test_invalid_time_is_rejected(self):
        response = self.client.post(
            self.url, schedule_payload(times=["25:00"]), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_timezone_is_rejected(self):
        response = self.client.post(
            self.url, schedule_payload(timezone="Mars/Olympus"), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_caregiver_cannot_create_schedule(self):
        caregiver = create_caregiver()
        link_caregiver(caregiver, self.patient)
        self.client.force_authenticate(caregiver)

        response = self.client.post(self.url, schedule_payload(), format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cannot_add_schedule_to_inactive_medication(self):
        self.medication.is_active = False
        self.medication.save(update_fields=["is_active"])

        response = self.client.post(self.url, schedule_payload(), format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


@override_settings(DOSE_GENERATION_WINDOW_DAYS=2)
class ScheduleUpdateTests(APITestCase):
    def setUp(self):
        self.patient = create_patient()
        self.client.force_authenticate(self.patient)
        self.medication = create_medication(self.patient)
        self.schedule = create_schedule(self.medication, times=["08:00"])

    def test_material_change_replaces_future_pending_occurrences(self):
        from apps.medications.services import generate_occurrences

        with patch("django.utils.timezone.now", return_value=fixed_now()):
            generate_occurrences(self.schedule)
            self.assertGreater(
                DoseOccurrence.objects.filter(
                    schedule=self.schedule
                ).count(),
                0,
            )

            response = self.client.patch(
                reverse("schedule-detail", args=[self.schedule.pk]),
                {"times": ["09:00"]},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        occurrences = DoseOccurrence.objects.filter(schedule=self.schedule)
        self.assertGreater(occurrences.count(), 0)
        for occurrence in occurrences:
            self.assertEqual(occurrence.scheduled_at.hour, 9)

    def test_material_change_preserves_historical_completed_occurrences(self):
        from apps.medications.services import generate_occurrences

        generate_occurrences(self.schedule)
        historical = create_occurrence(
            self.medication,
            self.schedule,
            scheduled_at=timezone.now() - timedelta(days=1),
            status=DoseOccurrence.Status.TAKEN,
            taken_at=timezone.now() - timedelta(days=1),
        )

        self.client.patch(
            reverse("schedule-detail", args=[self.schedule.pk]),
            {"times": ["09:00"]},
            format="json",
        )

        self.assertTrue(
            DoseOccurrence.objects.filter(pk=historical.pk).exists()
        )

    def test_deactivate_schedule_removes_future_pending_but_keeps_history(self):
        from apps.medications.services import generate_occurrences

        historical = create_occurrence(
            self.medication,
            self.schedule,
            scheduled_at=timezone.now() - timedelta(days=1),
            status=DoseOccurrence.Status.TAKEN,
            taken_at=timezone.now() - timedelta(days=1),
        )
        with patch("django.utils.timezone.now", return_value=fixed_now()):
            generate_occurrences(self.schedule)
            response = self.client.post(
                reverse("schedule-deactivate", args=[self.schedule.pk])
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["is_active"])
        self.assertTrue(
            DoseOccurrence.objects.filter(pk=historical.pk).exists()
        )
        self.assertFalse(
            DoseOccurrence.objects.filter(
                schedule=self.schedule,
                scheduled_at__gte=timezone.now(),
                status=DoseOccurrence.Status.PENDING,
            ).exists()
        )

    def test_patch_is_active_false_deactivates(self):
        response = self.client.patch(
            reverse("schedule-detail", args=[self.schedule.pk]),
            {"is_active": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.schedule.refresh_from_db()
        self.assertFalse(self.schedule.is_active)

    def test_caregiver_cannot_update_schedule(self):
        caregiver = create_caregiver()
        link_caregiver(caregiver, self.patient)
        self.client.force_authenticate(caregiver)

        response = self.client.patch(
            reverse("schedule-detail", args=[self.schedule.pk]),
            {"times": ["09:00"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_other_patient_gets_not_found(self):
        other = create_patient(email="other@example.com")
        self.client.force_authenticate(other)

        response = self.client.get(
            reverse("schedule-detail", args=[self.schedule.pk])
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


@override_settings(DOSE_GENERATION_WINDOW_DAYS=2)
class ScheduleReadTests(APITestCase):
    def setUp(self):
        self.patient = create_patient()
        self.caregiver = create_caregiver()
        link_caregiver(self.caregiver, self.patient)
        self.medication = create_medication(self.patient)
        self.schedule = create_schedule(self.medication)
        self.url = reverse(
            "medication-schedule-list", args=[self.medication.pk]
        )

    def test_linked_caregiver_can_list_schedules(self):
        self.client.force_authenticate(self.caregiver)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

    def test_unlinked_caregiver_gets_not_found(self):
        unlinked = create_caregiver(email="unlinked@example.com")
        self.client.force_authenticate(unlinked)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_filter_by_schedule_type(self):
        self.client.force_authenticate(self.patient)
        response = self.client.get(self.url, {"schedule_type": "fixed_times"})
        self.assertEqual(response.data["count"], 1)

        response = self.client.get(self.url, {"schedule_type": "weekdays"})
        self.assertEqual(response.data["count"], 0)
