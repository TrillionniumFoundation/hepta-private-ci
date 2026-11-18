"""Loss, replay, cold interruption and legitimate history for trial budgets."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from hepta_cells.research_trial import TrialLedger, canonical, sha256


class TrialIntegrityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.plan = {
            "schema": "hepta.development-trial.v1",
            "mode": "development",
            "runtime": {
                "executable": str(Path(sys.executable).resolve()),
                "sha256": "a" * 64,
                "version": sys.version,
            },
            "files": {"tool.py": "b" * 64},
            "tasks": {
                "task": {
                    "source_groups": ["one_template"],
                    "phase": "development",
                    "exposure": "synthetic_development",
                }
            },
            "tools": {"tool": ["{python}", "-I", "-B", "tool.py"]},
            "oracle": ["{python}", "-I", "-B", "tool.py"],
            "arms": ["arm"],
            "schedule": [
                dict(attempt_id=a, task_id="task", arm="arm", tool_id="tool")
                for a in ("one", "two")
            ],
            "attempt_limit_per_arm": 2,
            "timeout_seconds": 1,
            "catalog_scope": "Synthetic development; no new research sources",
        }
        self.digest = sha256(canonical(self.plan).encode())

    def ledger(self, name):
        return TrialLedger.create(self.root / (name + ".sqlite"), self.plan)

    def reject_unchanged(self, path, reason):
        original = path.read_bytes()
        with self.assertRaisesRegex(ValueError, reason):
            TrialLedger(path, expected_plan_sha256=self.digest)
        self.assertEqual(path.read_bytes(), original)

    def test_deleted_pending_or_terminal_attempt_cannot_refund_charge(self):
        for state in ("pending", "terminal"):
            with self.subTest(state=state):
                ledger = self.ledger(state)
                ledger.claim("one")
                if state == "terminal":
                    ledger.settle("one", {"outcome": "failed"})
                with sqlite3.connect(ledger.path) as db:
                    db.execute("DELETE FROM attempts WHERE id='one'")
                self.reject_unchanged(ledger.path, "attempts differ")

    def test_every_live_operation_checks_history_before_mutation(self):
        for operation in ("claim", "settle", "report"):
            with self.subTest(operation=operation):
                ledger = self.ledger(operation)
                ledger.claim("one")
                with sqlite3.connect(ledger.path) as db:
                    db.execute("DELETE FROM attempts")
                original = ledger.path.read_bytes()
                with self.assertRaisesRegex(ValueError, "attempts differ"):
                    if operation == "claim":
                        ledger.claim("one")
                    elif operation == "settle":
                        ledger.settle("one", {"outcome": "success"})
                    else:
                        ledger.report()
                self.assertEqual(ledger.path.read_bytes(), original)

    def test_terminal_projection_and_original_receipt_cannot_be_replaced(self):
        for mutation in (
            "UPDATE attempts SET state='pending',receipt=NULL",
            "UPDATE attempts SET receipt='{}'",
            "DELETE FROM events WHERE kind='terminal'",
        ):
            with self.subTest(mutation=mutation):
                ledger = self.ledger(str(len(list(self.root.iterdir()))))
                ledger.claim("one")
                ledger.settle("one", {"outcome": "unknown"})
                with sqlite3.connect(ledger.path) as db:
                    db.execute(mutation)
                self.reject_unchanged(ledger.path, "attempts differ")

    def test_missing_table_and_interior_event_are_rejected_without_repair(self):
        for table in ("attempts", "events"):
            ledger = self.ledger(table)
            ledger.claim("one")
            with sqlite3.connect(ledger.path) as db:
                db.execute("DROP TABLE " + table)
            self.reject_unchanged(ledger.path, "schema is incomplete")
        ledger = self.ledger("gap")
        ledger.claim("one")
        ledger.settle("one", {"outcome": "failed"})
        with sqlite3.connect(ledger.path) as db:
            db.execute("DELETE FROM events WHERE seq=1")
        self.reject_unchanged(ledger.path, "sequence gap")

    def test_reordered_or_excess_charges_fail_even_with_matching_projection(self):
        for mode in ("order", "budget"):
            with self.subTest(mode=mode):
                if mode == "budget":
                    self.plan["attempt_limit_per_arm"] = 1
                    self.digest = sha256(canonical(self.plan).encode())
                ledger = self.ledger(mode)
                if mode == "budget":
                    ledger.claim("one")
                with sqlite3.connect(ledger.path) as db:
                    db.execute("INSERT INTO attempts VALUES ('two','pending',NULL)")
                    db.execute(
                        "INSERT INTO events(id,kind,detail) VALUES ('two','charged',?)",
                        (canonical(self.plan["schedule"][1]),),
                    )
                self.reject_unchanged(ledger.path, "order or budget")

    def test_public_plan_race_cannot_increase_budget_during_claim(self):
        self.plan["attempt_limit_per_arm"] = 1
        self.digest = sha256(canonical(self.plan).encode())
        ledger = self.ledger("budget_race")
        ledger.claim("one")
        reached, changed = threading.Event(), threading.Event()
        connect = sqlite3.connect

        def traced_connect(*args, **kwargs):
            db = connect(*args, **kwargs)

            def trace(statement):
                if statement == "SELECT id,state FROM attempts":
                    reached.set()
                    changed.wait(timeout=5)

            db.set_trace_callback(trace)
            return db

        def mutate():
            self.assertTrue(reached.wait(timeout=5))
            try:
                ledger.plan["attempt_limit_per_arm"] = 2
                ledger.plan["schedule"][1]["tool_id"] = "replacement"
            finally:
                changed.set()

        with ThreadPoolExecutor(max_workers=1) as pool:
            mutation = pool.submit(mutate)
            with patch("hepta_cells.research_trial.sqlite3.connect", traced_connect):
                with self.assertRaisesRegex(ValueError, "budget exhausted"):
                    ledger.claim("two")
            mutation.result(timeout=10)
        recovered = TrialLedger(ledger.path, expected_plan_sha256=self.digest)
        self.assertEqual(recovered.report()["charged"], 1)
        self.assertEqual(recovered.plan, self.plan)
        for attribute, value in (
            ("plan", {}),
            ("raw", "{}"),
            ("plan_sha256", "f" * 64),
        ):
            with self.assertRaises(AttributeError):
                setattr(ledger, attribute, value)

    def test_rebuilt_schema_cannot_hide_a_duplicate_pending_projection(self):
        ledger = self.ledger("duplicate_projection")
        ledger.claim("one")
        receipt = {"outcome": "failed"}
        ledger.settle("one", receipt)
        with sqlite3.connect(ledger.path) as db:
            db.execute("DROP TABLE attempts")
            db.execute("CREATE TABLE attempts (id TEXT,state TEXT,receipt TEXT)")
            db.execute("INSERT INTO attempts VALUES ('one','pending',NULL)")
            db.execute(
                "INSERT INTO attempts VALUES ('one','terminal',?)",
                (canonical(receipt),),
            )
        self.reject_unchanged(ledger.path, "schema is incomplete or changed")

    def test_cold_process_crash_preserves_consumed_pending_opportunity(self):
        ledger = self.ledger("crash")
        code = (
            "import os,sys;sys.path.insert(0,sys.argv[1]);"
            "from hepta_cells.research_trial import TrialLedger;"
            "TrialLedger(sys.argv[2],expected_plan_sha256=sys.argv[3]).claim('one');"
            "os._exit(23)"
        )
        child = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                "-c",
                code,
                str(Path(__file__).parent),
                str(ledger.path),
                self.digest,
            ],
            capture_output=True,
            timeout=10,
        )
        self.assertEqual((child.returncode, child.stdout, child.stderr), (23, b"", b""))
        recovered = TrialLedger(ledger.path, expected_plan_sha256=self.digest)
        with self.assertRaisesRegex(ValueError, "already consumed"):
            recovered.claim("one")
        report = recovered.report()
        self.assertEqual(
            (report["charged"], report["pending"], report["unsubmitted"]), (1, 1, 1)
        )

    def test_concurrent_claim_and_legitimate_rejections_keep_one_charge(self):
        ledger = self.ledger("concurrent")
        barrier = threading.Barrier(2)

        def claim():
            peer = TrialLedger(ledger.path, expected_plan_sha256=self.digest)
            barrier.wait(timeout=10)
            try:
                peer.claim("one")
                return "charged"
            except ValueError as error:
                self.assertIn("already consumed", str(error))
                return "rejected"

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(
                sorted(pool.map(lambda _: claim(), range(2))), ["charged", "rejected"]
            )
        ledger.settle("one", {"outcome": "failed"})
        with self.assertRaisesRegex(ValueError, "immutable"):
            ledger.settle("one", {"outcome": "success"})
        ledger.claim("two")
        with self.assertRaisesRegex(ValueError, "unscheduled"):
            ledger.claim("unknown")
        recovered = TrialLedger(ledger.path, expected_plan_sha256=self.digest)
        report = recovered.report()
        self.assertEqual(
            (report["charged"], report["pending"], report["unsubmitted"]), (2, 1, 0)
        )
        self.assertEqual(report["attempts"]["one"]["receipt"], {"outcome": "failed"})
        self.assertEqual(
            [e["kind"] for e in report["events"]],
            [
                "charged",
                "rejected",
                "terminal",
                "settle_rejected",
                "charged",
                "rejected",
            ],
        )


if __name__ == "__main__":
    unittest.main()
