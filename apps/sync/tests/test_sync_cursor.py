import threading
import time as time_module
import uuid
from unittest import skipUnless

from django.db import connection, connections, transaction
from django.test import TestCase, TransactionTestCase

from apps.medications.tests.utils import create_patient
from apps.sync.models import SyncChange, SyncCursor
from apps.sync.services import get_changes, record_change

requires_postgresql = skipUnless(
    connection.vendor == "postgresql",
    "Commit-order concurrency requires PostgreSQL row locks.",
)


class SyncCursorAllocationTests(TestCase):
    def setUp(self):
        self.patient = create_patient()

    def test_record_change_allocates_monotonic_sequences(self):
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

        self.assertEqual(second.sequence, first.sequence + 1)
        cursor = SyncCursor.objects.get(pk=1)
        self.assertEqual(cursor.last_sequence, second.sequence)

    def test_rollback_does_not_lose_or_skip_a_sequence(self):
        try:
            with transaction.atomic():
                record_change(
                    self.patient.pk,
                    SyncChange.EntityType.WATER_SETTINGS,
                    uuid.uuid4(),
                )
                raise RuntimeError("rollback")
        except RuntimeError:
            pass

        self.assertEqual(SyncChange.objects.count(), 0)
        self.assertEqual(SyncCursor.objects.get(pk=1).last_sequence, 0)

        committed = record_change(
            self.patient.pk,
            SyncChange.EntityType.WATER_SETTINGS,
            uuid.uuid4(),
        )
        self.assertEqual(committed.sequence, 1)

    def test_resuming_from_saved_cursor_returns_every_committed_change(self):
        changes = [
            record_change(
                self.patient.pk,
                SyncChange.EntityType.WATER_SETTINGS,
                uuid.uuid4(),
            )
            for _ in range(3)
        ]

        first_page = get_changes(self.patient, cursor=0, limit=2)
        self.assertEqual(
            [row["cursor"] for row in first_page["changes"]],
            [changes[0].sequence, changes[1].sequence],
        )
        second_page = get_changes(
            self.patient,
            cursor=first_page["next_cursor"],
            limit=2,
        )
        self.assertEqual(
            [row["cursor"] for row in second_page["changes"]],
            [changes[2].sequence],
        )


@requires_postgresql
class SyncCursorConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def test_commit_order_prevents_skipping_an_uncommitted_change(self):
        patient = create_patient()
        first_locked = threading.Event()
        allow_first_commit = threading.Event()
        second_started = threading.Event()
        second_committed = threading.Event()
        sequences = {}
        errors = []

        def first_transaction():
            try:
                with transaction.atomic():
                    change = record_change(
                        patient.pk,
                        SyncChange.EntityType.WATER_SETTINGS,
                        uuid.uuid4(),
                    )
                    sequences["first"] = change.sequence
                    first_locked.set()
                    if not allow_first_commit.wait(timeout=15):
                        raise RuntimeError("first transaction timed out")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                connections.close_all()

        def second_transaction():
            try:
                if not first_locked.wait(timeout=15):
                    raise RuntimeError("first transaction did not start")
                second_started.set()
                with transaction.atomic():
                    change = record_change(
                        patient.pk,
                        SyncChange.EntityType.WATER_SETTINGS,
                        uuid.uuid4(),
                    )
                    sequences["second"] = change.sequence
                second_committed.set()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                connections.close_all()

        first = threading.Thread(target=first_transaction)
        second = threading.Thread(target=second_transaction)
        first.start()
        second.start()

        self.assertTrue(first_locked.wait(timeout=15))
        self.assertTrue(second_started.wait(timeout=15))
        time_module.sleep(0.5)
        self.assertFalse(
            second_committed.is_set(),
            "second transaction must wait for the cursor lock",
        )

        allow_first_commit.set()
        first.join(timeout=20)
        second.join(timeout=20)

        self.assertEqual(errors, [])
        self.assertLess(sequences["first"], sequences["second"])
        self.assertTrue(second_committed.is_set())

        payload = get_changes(patient, cursor=0, limit=10)
        returned = [row["cursor"] for row in payload["changes"]]
        self.assertEqual(
            returned,
            [sequences["first"], sequences["second"]],
        )

    def test_rolled_back_transaction_does_not_hide_later_changes(self):
        patient = create_patient()
        sequences = {}
        errors = []

        def rolled_back_transaction():
            try:
                with transaction.atomic():
                    record_change(
                        patient.pk,
                        SyncChange.EntityType.WATER_SETTINGS,
                        uuid.uuid4(),
                    )
                    raise RuntimeError("rollback")
            except RuntimeError:
                pass
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                connections.close_all()

        def committed_transaction():
            try:
                change = record_change(
                    patient.pk,
                    SyncChange.EntityType.WATER_SETTINGS,
                    uuid.uuid4(),
                )
                sequences["committed"] = change.sequence
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                connections.close_all()

        first = threading.Thread(target=rolled_back_transaction)
        first.start()
        first.join(timeout=20)
        second = threading.Thread(target=committed_transaction)
        second.start()
        second.join(timeout=20)

        self.assertEqual(errors, [])
        payload = get_changes(patient, cursor=0, limit=10)
        self.assertEqual(
            [row["cursor"] for row in payload["changes"]],
            [sequences["committed"]],
        )
        self.assertEqual(
            SyncCursor.objects.get(pk=1).last_sequence,
            sequences["committed"],
        )


@requires_postgresql
class SyncCursorIsolationTests(TransactionTestCase):
    def test_patient_feed_never_exposes_another_patient(self):
        first_patient = create_patient()
        second_patient = create_patient(email="second@example.com")
        own = record_change(
            first_patient.pk,
            SyncChange.EntityType.WATER_SETTINGS,
            uuid.uuid4(),
        )
        record_change(
            second_patient.pk,
            SyncChange.EntityType.WATER_SETTINGS,
            uuid.uuid4(),
        )

        payload = get_changes(first_patient, cursor=0, limit=10)
        self.assertEqual(
            [row["cursor"] for row in payload["changes"]],
            [own.sequence],
        )
        self.assertEqual(
            payload["changes"][0]["patient"], first_patient.pk
        )
