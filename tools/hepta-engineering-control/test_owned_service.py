"""Actual child, SQLite commit, lost acknowledgement and restart observations."""

import os
from contextlib import closing
import sqlite3
from pathlib import Path
import tempfile
import unittest

from assimilation.owned_service import (
    DisposableCounterService,
    IndeterminateOperation,
    ServiceError,
)


class OwnedServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="hepta-owned-service-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def target(self, generation=1, minimum_counter=0, **profile):
        service = DisposableCounterService(self.root, generation, minimum_counter, **profile)
        self.addCleanup(service.close)
        return service

    def test_unprivileged_query_commit_restart_and_fenced_reconciliation(self):
        first = self.target()
        ready = first.start()
        self.assertNotEqual(ready["pid"], os.getpid())
        self.assertEqual(first.request("query"), {"generation": 1, "counter": 0})
        self.assertEqual(first.request("step", "operation1")["value"], 1)
        self.assertEqual(first.request("step", "operation1")["value"], 1)
        self.assertEqual(first.request("stop"), {"generation": 1, "stopped": True})
        first.close()
        second = self.target(2, 1)
        new = second.start()
        self.assertNotEqual(new["pid"], ready["pid"])
        self.assertEqual(new["counter"], 1)
        self.assertEqual(second.request("reconcile", "operation1")["value"], 1)
        self.assertIsNone(second.request("reconcile", "unknown")["value"])

    def test_commit_without_acknowledgement_is_not_retried(self):
        first = self.target()
        first.start()
        with self.assertRaises(IndeterminateOperation):
            first.request("commit_then_exit", "lostack")
        first.close()
        successor = self.target(2, 0)
        self.assertEqual(successor.start()["counter"], 1)
        self.assertEqual(successor.request("reconcile", "lostack")["value"], 1)
        self.assertEqual(successor.request("query")["counter"], 1)

    def test_second_writer_and_stale_restored_state_fail(self):
        first = self.target()
        first.start()
        with self.assertRaises(ServiceError):
            self.target(2, 0).start()
        first.close()
        with self.assertRaises(ServiceError):
            self.target(2, 1).start()

    def test_additive_migration_and_code_rollback_preserve_post_upgrade_writes(self):
        first = self.target()
        self.assertEqual(first.start()["schema_version"], 1)
        first.request("step", "before")
        first.close()
        second = self.target(2, 1, implementation_version=2)
        self.assertEqual(second.start()["schema_version"], 2)
        second.request("step", "after")
        second.close()
        # Roll back implementation, not history: generation must move forward.
        rollback = self.target(3, 2, implementation_version=1)
        self.assertEqual(rollback.start()["counter"], 2)
        self.assertEqual(rollback.request("reconcile", "after")["value"], 2)
        self.assertEqual(rollback.request("step", "rollbackwrite")["value"], 3)
        rollback.close()
        with closing(sqlite3.connect(f"file:{self.root / 'service.sqlite3'}?mode=ro", uri=True)) as observer:
            rows = observer.execute("SELECT id,value,origin_generation FROM operations ORDER BY value").fetchall()
            self.assertEqual(rows, [("before", 1, 0), ("after", 2, 2), ("rollbackwrite", 3, 0)])

    def test_migration_crash_before_commit_rolls_back_schema_and_fence(self):
        first = self.target()
        first.start()
        first.request("step", "retained")
        first.close()
        with self.assertRaises(ServiceError):
            self.target(2, 1, implementation_version=2, migration_fault="before_commit").start()
        restored = self.target(1, 1)
        self.assertEqual(restored.start()["schema_version"], 1)
        self.assertEqual(restored.request("reconcile", "retained")["value"], 1)

    def test_migration_commit_without_ready_requires_current_generation(self):
        first = self.target()
        first.start()
        first.request("step", "retained")
        first.close()
        with self.assertRaises(ServiceError):
            self.target(2, 1, implementation_version=2, migration_fault="after_commit").start()
        with self.assertRaises(ServiceError):
            self.target(1, 1).start()
        current = self.target(3, 1)
        self.assertEqual(current.start()["schema_version"], 2)
        self.assertEqual(current.request("reconcile", "retained")["value"], 1)

    def test_migration_cannot_run_while_predecessor_owns_writer(self):
        first = self.target()
        first.start()
        with self.assertRaises(ServiceError):
            self.target(2, 0, implementation_version=2).start()
        self.assertEqual(first.request("step", "stillowned")["value"], 1)

    def test_scope_and_unregistered_operations_reject(self):
        with self.assertRaises(ServiceError):
            DisposableCounterService(Path("/"), 1, 0)
        target = self.target()
        target.start()
        for operation in ("install_package", "register_peer", "start_systemd", "shell"):
            with self.subTest(operation=operation), self.assertRaises(ServiceError):
                target.request(operation)
        with self.assertRaises(ServiceError):
            target.request("step", "../../escape")
        self.assertEqual(target.request("query")["counter"], 0)

    def test_late_acknowledgement_poison_requires_new_client_and_reconciliation(self):
        from unittest.mock import patch
        import selectors

        first = self.target()
        first.start()

        def leave_committed_ack_unread():
            with selectors.DefaultSelector() as selector:
                selector.register(first.process.stdout, selectors.EVENT_READ)
                self.assertTrue(selector.select(2), "real child must publish after commit")
            raise ServiceError("response_timeout")

        with patch.object(first, "_read", side_effect=leave_committed_ack_unread):
            with self.assertRaises(IndeterminateOperation):
                first.request("step", "lateack")
        # An old response must never satisfy a different request on the pipe.
        with self.assertRaises(IndeterminateOperation):
            first.request("query")
        first.close()
        with self.assertRaises(IndeterminateOperation):
            first.start()
        successor = self.target(2)
        self.assertEqual(successor.start()["counter"], 1)
        self.assertEqual(successor.request("reconcile", "lateack")["value"], 1)
        self.assertEqual(successor.request("query")["counter"], 1)

    def test_same_generation_cannot_change_implementation_in_either_direction(self):
        first = self.target()
        first.start()
        first.request("step", "before")
        first.close()
        with self.assertRaises(ServiceError):
            self.target(1, 1, implementation_version=2).start()
        upgraded = self.target(2, 1, implementation_version=2)
        upgraded.start()
        upgraded.request("step", "after")
        upgraded.close()
        with self.assertRaises(ServiceError):
            self.target(2, 2, implementation_version=1).start()
        restarted = self.target(2, 2, implementation_version=2)
        self.assertEqual(restarted.start()["counter"], 2)
        self.assertEqual(restarted.request("reconcile", "after")["value"], 2)

    def test_invalid_request_identity_is_rejected_before_dispatch(self):
        target = self.target()
        target.start()
        for identity in (None, 1, True, [], {}, b"bytes"):
            with self.subTest(identity=identity), self.assertRaises(ServiceError):
                target.request("step", identity)
        self.assertEqual(target.request("query")["counter"], 0)

    def test_mismatched_acknowledgement_cannot_publish_or_reuse_channel(self):
        from unittest.mock import patch

        for response in (
            {"generation": 1, "sequence": 99, "counter": 0},
            {"generation": True, "sequence": 1, "counter": 0},
            {"generation": 1, "sequence": True, "counter": 0},
            {"generation": 1, "sequence": 1, "counter": True},
            {"generation": 1, "sequence": 1, "value": 0},
        ):
            with self.subTest(response=response):
                target = self.target()
                target.start()
                with patch.object(target, "_read", return_value=response):
                    with self.assertRaises(IndeterminateOperation):
                        target.request("query")
                with self.assertRaises(IndeterminateOperation):
                    target.request("query")
                target.close()

    def test_legacy_generation_without_profile_needs_explicit_new_generation(self):
        with closing(sqlite3.connect(self.root / "service.sqlite3")) as database:
            database.execute(
                "CREATE TABLE service_meta (singleton INTEGER PRIMARY KEY, "
                "generation INTEGER NOT NULL, schema_version INTEGER NOT NULL)"
            )
            database.execute("INSERT INTO service_meta VALUES (1, 5, 1)")
            database.execute("CREATE TABLE operations (id TEXT PRIMARY KEY, value INTEGER NOT NULL UNIQUE)")
            database.execute("INSERT INTO operations VALUES ('retained', 1)")
            database.commit()
        with self.assertRaises(ServiceError):
            self.target(5, 1).start()
        migrated = self.target(6, 1)
        self.assertEqual(migrated.start()["counter"], 1)
        self.assertEqual(migrated.request("reconcile", "retained")["value"], 1)

    def test_successful_restart_keeps_observed_counter_frontier(self):
        target = self.target()
        target.start()
        target.request("step", "observed")
        self.assertEqual(target.minimum_counter, 1)
        target.close()
        self.assertEqual(target.start()["counter"], 1)
        self.assertEqual(target.request("step", "observed") ["value"], 1)


    def test_ambiguous_request_cannot_commit_an_effect(self):
        target = self.target()
        target.start()
        process = target.process
        process.stdin.write(
            b'{"op":"query","op":"step","id":"ambiguous",'
            b'"generation":1,"sequence":1}\n'
        )
        process.stdin.close()
        code = process.wait(timeout=2)
        target.close()
        self.assertNotEqual(code, 0, "duplicate fields must reject, not pick the last value")
        recovered = self.target(2)
        self.assertEqual(recovered.start()["counter"], 0)
        self.assertIsNone(recovered.request("reconcile", "ambiguous")["value"])

    def test_ambiguous_response_poison_requires_reconciliation(self):
        from unittest.mock import patch

        target = self.target()
        target.start()
        read_fd, write_fd = os.pipe()
        with os.fdopen(read_fd, "rb", buffering=0) as response_pipe:
            with os.fdopen(write_fd, "wb", buffering=0) as peer:
                peer.write(
                    b'{"generation":1,"sequence":999,"sequence":1,"counter":0}\n'
                )
            # Inject bytes through a real pipe, not an already-decoded dict.
            with patch.object(target.process, "stdout", response_pipe):
                with self.assertRaises(IndeterminateOperation):
                    target.request("query")
        with self.assertRaises(IndeterminateOperation):
            target.request("query")

    def test_cancellation_after_dispatch_never_reuses_the_channel(self):
        from unittest.mock import patch
        import selectors

        target = self.target()
        target.start()

        def interrupted_after_real_commit():
            with selectors.DefaultSelector() as selector:
                selector.register(target.process.stdout, selectors.EVENT_READ)
                self.assertTrue(selector.select(2))
            raise KeyboardInterrupt()

        with patch.object(target, "_read", side_effect=interrupted_after_real_commit):
            with self.assertRaises(KeyboardInterrupt):
                target.request("step", "cancelled")
        self.assertTrue(target.channel_indeterminate)
        with self.assertRaises(IndeterminateOperation):
            target.request("query")
        target.close()
        successor = self.target(2)
        self.assertEqual(successor.start()["counter"], 1)
        self.assertEqual(successor.request("reconcile", "cancelled")["value"], 1)
        self.assertEqual(successor.request("query")["counter"], 1)

    def test_child_exit_race_during_close_still_reaps_and_closes(self):
        from unittest.mock import patch

        target = self.target()
        target.start()
        process = target.process
        real_killpg = os.killpg

        def exit_between_poll_and_signal(pid, signal):
            real_killpg(pid, signal)
            process.wait(timeout=2)
            raise ProcessLookupError("group exited before signal delivery")

        with patch("assimilation.owned_service.os.killpg", side_effect=exit_between_poll_and_signal):
            target.close()
        self.assertIsNotNone(process.returncode)
        self.assertTrue(process.stdin.closed)
        self.assertTrue(process.stdout.closed)
        target.close()

    def test_two_services_remain_isolated_across_crash_upgrade_and_code_rollback(self):
        # Same host, separate owned directories: not multi-host qualification.
        with tempfile.TemporaryDirectory(prefix="hepta-second-service-") as directory:
            other = DisposableCounterService(Path(directory), 1, 0)
            self.addCleanup(other.close)
            a = self.target()
            a_ready, b_ready = a.start(), other.start()
            self.assertNotEqual(a_ready["pid"], b_ready["pid"])
            a.request("step", "sharedid")
            other.request("step", "sharedid")
            other.request("step", "bonly")
            a.close()
            with self.assertRaises(ServiceError):
                self.target(2, 1, implementation_version=2, migration_fault="after_commit").start()
            # The other writer stays live while A's replacement is indeterminate.
            self.assertEqual(other.request("step", "bcontinues")["value"], 3)
            upgraded = self.target(2, 1, implementation_version=2)
            self.assertEqual(upgraded.start()["schema_version"], 2)
            self.assertEqual(upgraded.request("step", "afterupgrade")["value"], 2)
            upgraded.close()
            rollback = self.target(3, 2, implementation_version=1)
            self.assertEqual(rollback.start()["counter"], 2)
            self.assertEqual(rollback.request("reconcile", "afterupgrade")["value"], 2)
            self.assertIsNone(rollback.request("reconcile", "bonly")["value"])
            self.assertEqual(rollback.request("step", "afterrollback")["value"], 3)
            self.assertEqual(other.request("query")["counter"], 3)
            self.assertIsNone(other.request("reconcile", "afterupgrade")["value"])
            rollback.close()
            other.close()
            for service_root, expected in (
                (self.root, [("sharedid", 1), ("afterupgrade", 2), ("afterrollback", 3)]),
                (Path(directory), [("sharedid", 1), ("bonly", 2), ("bcontinues", 3)]),
            ):
                with closing(sqlite3.connect(
                    f"file:{service_root / 'service.sqlite3'}?mode=ro", uri=True
                )) as observer:
                    rows = observer.execute("SELECT id,value FROM operations ORDER BY value").fetchall()
                    self.assertEqual(rows, expected)


if __name__ == "__main__":
    unittest.main()
