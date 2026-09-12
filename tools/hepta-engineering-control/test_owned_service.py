"""Actual child, SQLite commit, lost acknowledgement and restart observations."""

import os
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

    def target(self, generation=1, minimum_counter=0):
        service = DisposableCounterService(self.root, generation, minimum_counter)
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


if __name__ == "__main__":
    unittest.main()
