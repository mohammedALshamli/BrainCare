import importlib

from django.conf import settings
from django.test import SimpleTestCase


class CeleryBeatScheduleTests(SimpleTestCase):
    def test_required_tasks_are_scheduled_exactly_once(self):
        entries = settings.CELERY_BEAT_SCHEDULE
        task_paths = [entry["task"] for entry in entries.values()]

        self.assertEqual(len(task_paths), len(set(task_paths)))
        self.assertIn(
            "apps.medications.tasks.generate_rolling_dose_occurrences",
            task_paths,
        )
        self.assertIn("apps.medications.tasks.mark_overdue_doses", task_paths)
        self.assertIn(
            "apps.notifications.tasks.dispatch_pending_notifications_task",
            task_paths,
        )
        self.assertIn(
            "apps.accounts.tasks.cleanup_pairing_codes",
            task_paths,
        )

    def test_scheduled_task_paths_are_importable(self):
        for entry in settings.CELERY_BEAT_SCHEDULE.values():
            module_path, function_name = entry["task"].rsplit(".", 1)
            module = importlib.import_module(module_path)
            self.assertTrue(
                hasattr(module, function_name),
                f"{entry['task']} is not importable",
            )

    def test_celery_late_acknowledgement_is_enabled(self):
        self.assertTrue(settings.CELERY_TASK_ACKS_LATE)
        self.assertTrue(settings.CELERY_TASK_REJECT_ON_WORKER_LOST)
        self.assertEqual(settings.CELERY_WORKER_PREFETCH_MULTIPLIER, 1)
        self.assertGreater(
            settings.CELERY_VISIBILITY_TIMEOUT,
            settings.CELERY_TASK_TIME_LIMIT,
        )

    def test_failure_sensitive_jobs_run_frequently(self):
        entries = settings.CELERY_BEAT_SCHEDULE
        by_task = {entry["task"]: entry for entry in entries.values()}

        self.assertLessEqual(
            by_task["apps.medications.tasks.mark_overdue_doses"]["schedule"],
            300,
        )
        self.assertLessEqual(
            by_task[
                "apps.notifications.tasks.dispatch_pending_notifications_task"
            ]["schedule"],
            60,
        )
        self.assertLessEqual(
            by_task["apps.accounts.tasks.cleanup_pairing_codes"]["schedule"],
            3600,
        )
