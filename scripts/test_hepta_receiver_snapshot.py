"""Receiver request/effect consistency across actual SQLite lock contention."""

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from hepta_cells.component_types import CellError
from hepta_cells.deterministic import ToolInvocation
from hepta_cells.receiver_handoff import ReceiverLease, ReceiverLedger


class ReceiverSnapshotTests(unittest.TestCase):
    def setUp(self):
        retained = os.environ.get("HEPTA_RECEIVER_SNAPSHOT_ARTIFACT_ROOT")
        self.temp = None if retained else tempfile.TemporaryDirectory()
        self.root = (
            Path(retained) / self._testMethodName if retained else Path(self.temp.name)
        )
        self.root.mkdir(parents=True, exist_ok=not bool(retained))
        self.path = self.root / "receiver.sqlite"
        self.lease = ReceiverLease("1" * 64, "source", 0, "a" * 64)
        ledger = ReceiverLedger.create(self.path, "7" * 64)
        try:
            ledger.provision(self.lease, "b" * 64, "c" * 64)
        finally:
            ledger.close()
        self.invocation = ToolInvocation(
            "2" * 64,
            "append_record",
            "c" * 64,
            self.lease.partition,
            "effect",
            "b" * 64,
            {"record": {"value": "original", "items": [1, 2]}},
            0,
            100,
            1000,
        )

    def tearDown(self):
        if self.temp is not None:
            self.temp.cleanup()

    def exercise_mutation(self, mutate):
        original = asdict(self.invocation)
        ready, start, began = (threading.Event() for _ in range(3))
        outcome = {}

        def invoke():
            ledger = None
            try:
                ledger = ReceiverLedger(self.path, "7" * 64)
                ready.set()
                if not start.wait(10):
                    raise RuntimeError("receiver dispatch was not released")
                ledger.db.set_trace_callback(
                    lambda sql: began.set() if sql == "BEGIN IMMEDIATE" else None
                )
                outcome["receipt"] = ledger.invoke(self.lease, self.invocation)
            except BaseException as error:
                outcome["error"] = f"{type(error).__name__}: {error}"
                ready.set()
            finally:
                if ledger is not None:
                    ledger.close()

        thread = threading.Thread(target=invoke)
        blocker = sqlite3.connect(self.path, isolation_level=None)
        thread.start()
        try:
            self.assertTrue(ready.wait(10), "receiver did not finish cold open")
            self.assertNotIn("error", outcome)
            blocker.execute("BEGIN IMMEDIATE")
            start.set()
            self.assertTrue(began.wait(10), "receiver did not reach the real lock")
            mutate(self.invocation.arguments)
        finally:
            blocker.rollback()
            blocker.close()
            start.set()
            thread.join(15)
        self.assertFalse(thread.is_alive(), "receiver failed to leave the lock wait")
        self.assertNotIn("error", outcome)

        ledger = ReceiverLedger(self.path, "7" * 64)
        try:
            row = dict(ledger.db.execute("SELECT * FROM effects").fetchone())
            receipt = outcome["receipt"]
            report = {
                "original_request": original,
                "caller_arguments_after_lock_wait": self.invocation.arguments,
                "receiver_row": row,
                "returned_receipt": receipt,
            }
            (self.root / "OBSERVATION.json").write_text(
                json.dumps(report, sort_keys=True, indent=2) + "\n"
            )
            self.assertEqual(json.loads(row["invocation"]), original)
            self.assertEqual(json.loads(row["record"]), original["arguments"]["record"])
            self.assertEqual(json.loads(row["receipt"]), receipt)
            self.assertEqual(
                receipt["record_sha256"],
                hashlib.sha256(row["record"].encode()).hexdigest(),
            )
            frozen = ToolInvocation(**original)
            self.assertEqual(ledger.readback(frozen), receipt)
            self.assertEqual(ledger.invoke(self.lease, frozen), receipt)
            with self.assertRaises(CellError):
                ledger.readback(self.invocation)
            self.assertEqual(
                ledger.db.execute("SELECT count(*) FROM effects").fetchone()[0], 1
            )
        finally:
            ledger.close()

    def test_nested_record_changes_during_lock_wait_keep_original_effect(self):
        def mutate(arguments):
            arguments["record"]["value"] = "changed"
            arguments["record"]["items"].append(3)

        self.exercise_mutation(mutate)

    def test_replaced_record_during_lock_wait_keeps_original_effect(self):
        self.exercise_mutation(lambda arguments: arguments.update(record="replacement"))

    def test_removed_record_during_lock_wait_keeps_original_effect(self):
        self.exercise_mutation(lambda arguments: arguments.clear())


if __name__ == "__main__":
    unittest.main()
