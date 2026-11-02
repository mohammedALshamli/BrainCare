from datetime import datetime
from zoneinfo import ZoneInfo

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.medications.tests.utils import create_patient
from apps.water.models import WaterIntakeLog, WaterReminderSettings
from apps.water.services import record_intake


class WaterSettingsTests(APITestCase):
    def setUp(self):
        self.patient = create_patient()
        self.client.force_authenticate(self.patient)

    def test_settings_are_created_with_defaults(self):
        response = self.client.get(reverse("water:settings"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["enabled"])
        self.assertIsNone(response.data["daily_goal_ml"])
        self.assertEqual(response.data["cup_size_ml"], 250)
        self.assertEqual(response.data["interval_minutes"], 60)

    def test_water_settings_allows_null_daily_goal(self):
        response = self.client.patch(
            reverse("water:settings"),
            {"daily_goal_ml": None},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIsNone(response.data["daily_goal_ml"])

        summary = self.client.get(reverse("water:summary"))
        self.assertEqual(summary.status_code, status.HTTP_200_OK)
        self.assertIsNone(summary.data["goal_ml"])
        self.assertIsNone(summary.data["remaining_ml"])
        self.assertIsNone(summary.data["progress_percentage"])
        self.assertIsNone(summary.data["goal_reached"])

    def test_patient_can_update_settings(self):
        response = self.client.patch(
            reverse("water:settings"),
            {
                "enabled": True,
                "start_time": "07:30",
                "end_time": "21:00",
                "interval_minutes": 90,
                "daily_goal_ml": 2500,
                "cup_size_ml": 300,
                "timezone": "America/New_York",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        settings_obj = WaterReminderSettings.objects.get(patient=self.patient)
        self.assertTrue(settings_obj.enabled)
        self.assertEqual(settings_obj.daily_goal_ml, 2500)
        self.assertEqual(settings_obj.timezone, "America/New_York")

    def test_invalid_time_window_is_rejected(self):
        response = self.client.patch(
            reverse("water:settings"),
            {"start_time": "20:00", "end_time": "08:00"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_timezone_is_rejected(self):
        response = self.client.patch(
            reverse("water:settings"),
            {"timezone": "Not/AZone"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_interval_and_amount_bounds_are_validated(self):
        bad_interval = self.client.patch(
            reverse("water:settings"),
            {"interval_minutes": 5},
            format="json",
        )
        bad_goal = self.client.patch(
            reverse("water:settings"),
            {"daily_goal_ml": 50},
            format="json",
        )
        bad_cup = self.client.patch(
            reverse("water:settings"),
            {"cup_size_ml": 10},
            format="json",
        )
        self.assertEqual(bad_interval.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(bad_goal.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(bad_cup.status_code, status.HTTP_400_BAD_REQUEST)


class WaterIntakeTests(APITestCase):
    def setUp(self):
        self.patient = create_patient()
        self.client.force_authenticate(self.patient)

    def test_record_intake_and_daily_total(self):
        first = self.client.post(
            reverse("water:intake-list"), {"amount_ml": 250}, format="json"
        )
        second = self.client.post(
            reverse("water:intake-list"),
            {"amount_ml": 500, "source": "cup"},
            format="json",
        )
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)

        summary = self.client.get(reverse("water:summary"))
        self.assertEqual(summary.status_code, status.HTTP_200_OK)
        self.assertEqual(summary.data["total_ml"], 750)
        self.assertEqual(summary.data["log_count"], 2)
        self.assertFalse(summary.data["goal_reached"])

    def test_amount_bounds_are_enforced(self):
        zero = self.client.post(
            reverse("water:intake-list"), {"amount_ml": 0}, format="json"
        )
        too_large = self.client.post(
            reverse("water:intake-list"), {"amount_ml": 5001}, format="json"
        )
        self.assertEqual(zero.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(too_large.status_code, status.HTTP_400_BAD_REQUEST)

    def test_daily_totals_respect_patient_timezone_boundary(self):
        WaterReminderSettings.objects.create(
            patient=self.patient, timezone="America/Los_Angeles"
        )
        first = datetime(
            2026, 3, 1, 23, 30, tzinfo=ZoneInfo("America/Los_Angeles")
        )
        second = datetime(
            2026, 3, 2, 0, 30, tzinfo=ZoneInfo("America/Los_Angeles")
        )
        record_intake(self.patient, 200, consumed_at=first)
        record_intake(self.patient, 300, consumed_at=second)

        first_log = WaterIntakeLog.objects.get(amount_ml=200)
        second_log = WaterIntakeLog.objects.get(amount_ml=300)
        self.assertEqual(first_log.local_date.isoformat(), "2026-03-01")
        self.assertEqual(second_log.local_date.isoformat(), "2026-03-02")

        summary = self.client.get(
            reverse("water:summary"), {"date": "2026-03-01"}
        )
        self.assertEqual(summary.data["total_ml"], 200)
        summary_next = self.client.get(
            reverse("water:summary"), {"date": "2026-03-02"}
        )
        self.assertEqual(summary_next.data["total_ml"], 300)

    def test_history_can_be_filtered_by_date(self):
        WaterReminderSettings.objects.create(
            patient=self.patient, timezone="UTC"
        )
        record_intake(
            self.patient,
            100,
            consumed_at=datetime(2026, 1, 1, 10, tzinfo=ZoneInfo("UTC")),
        )
        record_intake(
            self.patient,
            200,
            consumed_at=datetime(2026, 1, 2, 10, tzinfo=ZoneInfo("UTC")),
        )

        response = self.client.get(
            reverse("water:intake-list"),
            {"from_date": "2026-01-02", "to_date": "2026-01-02"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["amount_ml"], 200)

    def test_goal_reached_is_reported(self):
        self.client.patch(
            reverse("water:settings"),
            {"daily_goal_ml": 500},
            format="json",
        )
        self.client.post(
            reverse("water:intake-list"), {"amount_ml": 500}, format="json"
        )
        summary = self.client.get(reverse("water:summary"))
        self.assertTrue(summary.data["goal_reached"])
        self.assertEqual(summary.data["remaining_ml"], 0)
