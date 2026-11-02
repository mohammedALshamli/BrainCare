from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import CaregiverPatientLink
from apps.medications.models import DoseEvent
from apps.medications.tests.utils import (
    add_event,
    create_caregiver,
    create_medication,
    create_occurrence,
    create_patient,
    create_schedule,
    link_caregiver,
)
from apps.notifications.services import register_device
from apps.water.models import WaterIntakeLog
from apps.water.services import record_intake


class PermissionTestBase(APITestCase):
    def setUp(self):
        self.patient = create_patient()
        self.other_patient = create_patient(email="other@example.com")
        self.caregiver = create_caregiver()
        self.link = link_caregiver(self.caregiver, self.patient)

        self.medication = create_medication(self.patient, name="Owned")
        self.other_medication = create_medication(
            self.other_patient, name="Other"
        )
        self.schedule = create_schedule(self.medication)
        self.other_schedule = create_schedule(self.other_medication)
        self.dose = create_occurrence(self.medication, self.schedule)
        self.other_dose = create_occurrence(
            self.other_medication, self.other_schedule
        )
        self.event = add_event(self.dose, DoseEvent.EventType.TAKEN)

    def auth(self, user):
        self.client.force_authenticate(user)


class MedicationPermissionTests(PermissionTestBase):
    def test_patient_can_only_read_own_medication(self):
        self.auth(self.patient)
        own = self.client.get(
            reverse("medication-detail", args=[self.medication.pk])
        )
        other = self.client.get(
            reverse("medication-detail", args=[self.other_medication.pk])
        )
        self.assertEqual(own.status_code, status.HTTP_200_OK)
        self.assertEqual(other.status_code, status.HTTP_404_NOT_FOUND)

    def test_linked_caregiver_can_read_but_not_edit_by_default(self):
        self.auth(self.caregiver)
        read = self.client.get(
            reverse("medication-detail", args=[self.medication.pk])
        )
        edit = self.client.patch(
            reverse("medication-detail", args=[self.medication.pk]),
            {"name": "Changed"},
            format="json",
        )
        self.assertEqual(read.status_code, status.HTTP_200_OK)
        self.assertEqual(edit.status_code, status.HTTP_403_FORBIDDEN)

    def test_caregiver_cannot_read_unlinked_patient_medication(self):
        self.auth(self.caregiver)
        response = self.client.get(
            reverse("medication-detail", args=[self.other_medication.pk])
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_caregiver_with_edit_permission_can_edit(self):
        self.link.can_edit_medications = True
        self.link.save(update_fields=["can_edit_medications"])
        self.auth(self.caregiver)

        response = self.client.patch(
            reverse("medication-detail", args=[self.medication.pk]),
            {"name": "Caregiver edited"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.medication.refresh_from_db()
        self.assertEqual(self.medication.name, "Caregiver edited")

    def test_caregiver_with_edit_permission_can_deactivate(self):
        self.link.can_edit_medications = True
        self.link.save(update_fields=["can_edit_medications"])
        self.auth(self.caregiver)

        response = self.client.post(
            reverse("medication-deactivate", args=[self.medication.pk])
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.medication.refresh_from_db()
        self.assertFalse(self.medication.is_active)

    def test_view_permission_can_be_revoked_immediately(self):
        self.auth(self.caregiver)
        before = self.client.get(
            reverse("medication-detail", args=[self.medication.pk])
        )
        self.link.is_active = False
        self.link.save(update_fields=["is_active"])
        after = self.client.get(
            reverse("medication-detail", args=[self.medication.pk])
        )

        self.assertEqual(before.status_code, status.HTTP_200_OK)
        self.assertEqual(after.status_code, status.HTTP_404_NOT_FOUND)

    def test_can_view_false_blocks_access_even_when_link_is_active(self):
        self.link.can_view = False
        self.link.save(update_fields=["can_view"])
        self.auth(self.caregiver)

        response = self.client.get(
            reverse("medication-detail", args=[self.medication.pk])
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class SchedulePermissionTests(PermissionTestBase):
    def test_caregiver_can_read_own_patients_schedule_only(self):
        self.auth(self.caregiver)
        own = self.client.get(
            reverse("schedule-detail", args=[self.schedule.pk])
        )
        other = self.client.get(
            reverse("schedule-detail", args=[self.other_schedule.pk])
        )
        self.assertEqual(own.status_code, status.HTTP_200_OK)
        self.assertEqual(other.status_code, status.HTTP_404_NOT_FOUND)

    def test_view_only_caregiver_cannot_edit_schedule(self):
        self.auth(self.caregiver)
        response = self.client.patch(
            reverse("schedule-detail", args=[self.schedule.pk]),
            {"times": ["09:00"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_editor_caregiver_can_create_and_edit_schedule(self):
        self.link.can_edit_medications = True
        self.link.save(update_fields=["can_edit_medications"])
        self.auth(self.caregiver)

        created = self.client.post(
            reverse("medication-schedule-list", args=[self.medication.pk]),
            {
                "schedule_type": "fixed_times",
                "times": ["09:00"],
                "timezone": "UTC",
            },
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)

        edited = self.client.patch(
            reverse("schedule-detail", args=[self.schedule.pk]),
            {"times": ["10:00"]},
            format="json",
        )
        self.assertEqual(edited.status_code, status.HTTP_200_OK)

    def test_view_only_caregiver_cannot_create_schedule(self):
        self.auth(self.caregiver)
        response = self.client.post(
            reverse("medication-schedule-list", args=[self.medication.pk]),
            {
                "schedule_type": "fixed_times",
                "times": ["09:00"],
                "timezone": "UTC",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class DosePermissionTests(PermissionTestBase):
    def test_caregiver_can_read_linked_doses_and_events(self):
        self.auth(self.caregiver)
        dose = self.client.get(reverse("dose-detail", args=[self.dose.pk]))
        events = self.client.get(
            reverse("dose-events", args=[self.dose.pk])
        )
        other = self.client.get(
            reverse("dose-detail", args=[self.other_dose.pk])
        )
        self.assertEqual(dose.status_code, status.HTTP_200_OK)
        self.assertEqual(events.status_code, status.HTTP_200_OK)
        self.assertEqual(other.status_code, status.HTTP_404_NOT_FOUND)

    def test_caregiver_cannot_confirm_even_with_edit_permission(self):
        self.link.can_edit_medications = True
        self.link.save(update_fields=["can_edit_medications"])
        self.auth(self.caregiver)

        response = self.client.post(
            reverse("dose-confirm", args=[self.dose.pk]),
            {"client_event_id": "caregiver-confirm"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_revoked_caregiver_loses_dose_access(self):
        self.link.is_active = False
        self.link.save(update_fields=["is_active"])
        self.auth(self.caregiver)

        response = self.client.get(
            reverse("dose-detail", args=[self.dose.pk])
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class WaterPermissionTests(PermissionTestBase):
    def test_caregiver_can_read_water_for_linked_patient(self):
        record_intake(self.patient, 250)
        self.auth(self.caregiver)

        settings_response = self.client.get(
            reverse("water:settings"), {"patient": str(self.patient.pk)}
        )
        intake = self.client.get(
            reverse("water:intake-list"),
            {"patient": str(self.patient.pk)},
        )
        summary = self.client.get(
            reverse("water:summary"), {"patient": str(self.patient.pk)}
        )
        self.assertEqual(
            settings_response.status_code,
            status.HTTP_200_OK,
            settings_response.data,
        )
        self.assertEqual(intake.status_code, status.HTTP_200_OK, intake.data)
        self.assertEqual(summary.status_code, status.HTTP_200_OK, summary.data)
        self.assertEqual(summary.data["total_ml"], 250)

    def test_caregiver_cannot_write_water(self):
        self.auth(self.caregiver)
        create = self.client.post(
            reverse("water:intake-list"),
            {"amount_ml": 250},
            format="json",
        )
        update = self.client.patch(
            reverse("water:settings"),
            {"daily_goal_ml": 3000},
            format="json",
        )
        self.assertEqual(create.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(update.status_code, status.HTTP_403_FORBIDDEN)

    def test_caregiver_cannot_read_unlinked_water(self):
        self.auth(self.caregiver)
        response = self.client.get(
            reverse("water:summary"),
            {"patient": str(self.other_patient.pk)},
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_patient_cannot_read_another_patients_intake(self):
        record_intake(self.other_patient, 300)
        self.auth(self.patient)
        response = self.client.get(
            reverse("water:intake-list"),
            {"patient": str(self.other_patient.pk)},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)


class DevicePermissionTests(PermissionTestBase):
    def setUp(self):
        super().setUp()
        self.other_device = register_device(
            self.other_patient,
            {
                "fcm_token": "other-token-0123456789abcdef",
                "platform": "android",
            },
        )

    def test_device_list_only_contains_own_devices(self):
        self.auth(self.patient)
        response = self.client.get(reverse("device-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

        self.auth(self.other_patient)
        response = self.client.get(reverse("device-list"))
        self.assertEqual(response.data["count"], 1)

    def test_user_cannot_retrieve_or_delete_another_users_device(self):
        self.auth(self.patient)
        detail = self.client.get(
            reverse("device-detail", args=[self.other_device.pk])
        )
        delete = self.client.delete(
            reverse("device-detail", args=[self.other_device.pk])
        )
        self.assertEqual(detail.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(delete.status_code, status.HTTP_404_NOT_FOUND)
        self.other_device.refresh_from_db()
        self.assertTrue(self.other_device.is_active)

    def test_device_response_never_exposes_raw_token(self):
        self.auth(self.patient)
        response = self.client.post(
            reverse("device-list"),
            {
                "fcm_token": "patient-token-0123456789abcdef",
                "platform": "ios",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        body = str(response.data)
        self.assertNotIn("patient-token-0123456789abcdef", body)
        self.assertNotIn("fcm_token", body)
        self.assertIn("token_preview", body)


class RevocationAuditTests(PermissionTestBase):
    def test_revoked_relationship_stops_all_read_endpoints(self):
        self.auth(self.caregiver)
        self.assertEqual(
            self.client.get(
                reverse("medication-detail", args=[self.medication.pk])
            ).status_code,
            status.HTTP_200_OK,
        )

        CaregiverPatientLink.objects.filter(pk=self.link.pk).update(
            is_active=False
        )

        for url in (
            reverse("medication-detail", args=[self.medication.pk]),
            reverse("schedule-detail", args=[self.schedule.pk]),
            reverse("dose-detail", args=[self.dose.pk]),
            reverse("dose-events", args=[self.dose.pk]),
        ):
            response = self.client.get(url)
            self.assertEqual(
                response.status_code,
                status.HTTP_404_NOT_FOUND,
                url,
            )

    def test_history_endpoint_is_scoped_to_accessible_patient(self):
        self.auth(self.caregiver)
        own = self.client.get(
            reverse("dose-events", args=[self.dose.pk])
        )
        other = self.client.get(
            reverse("dose-events", args=[self.other_dose.pk])
        )
        self.assertEqual(own.status_code, status.HTTP_200_OK)
        self.assertEqual(other.status_code, status.HTTP_404_NOT_FOUND)

    def test_water_history_is_scoped(self):
        record_intake(self.patient, 200)
        record_intake(self.other_patient, 400)
        self.auth(self.caregiver)

        response = self.client.get(reverse("water:intake-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            WaterIntakeLog.objects.filter(patient=self.patient).count(), 1
        )
