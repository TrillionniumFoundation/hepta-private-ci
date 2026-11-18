"""Actual subprocess observations preserve queues, failures and missing tasks."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from hepta_cells.task_observation import TaskLedger, run_observed_task


CANDIDATE = "a" * 64
CLOCK = "test-host-same-boot-monotonic"


class TaskObservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "ledger.sqlite3"
        self.tasks = [
            dict(
                task_id=name,
                cell="MEM",
                phase="engineering",
                arm="fixture",
                source_group=name,
            )
            for name in ("one", "two", "absent")
        ]
        self.ledger = TaskLedger.create(
            self.path, candidate_sha256=CANDIDATE, clock_id=CLOCK, tasks=self.tasks
        )

    def receipt(self, name, payload):
        path = self.root / name
        with path.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        return path

    def test_real_work_includes_queue_and_keeps_unsubmitted_plan_denominator(self):
        self.ledger.accept("one")
        self.ledger.accept("two")
        receipt = self.root / "child.json"

        def work():
            subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import json,sys;open(sys.argv[1],'w').write(json.dumps({'sum':sum(range(10000))}))",
                    str(receipt),
                ],
                check=True,
            )
            self.assertEqual(json.loads(receipt.read_text()), {"sum": 49995000})
            return receipt, "success"

        run_observed_task(self.ledger, "one", work)
        self.ledger.start("two")
        self.ledger.finish(
            "two", self.receipt("failed.json", b'{"status":"failed"}'), outcome="failed"
        )
        report = self.ledger.report()
        self.assertEqual(
            {
                key: report[key]
                for key in (
                    "planned_count",
                    "accepted_count",
                    "started_count",
                    "final_count",
                    "missing_final_count",
                    "queue_peak_items",
                )
            },
            dict(
                planned_count=3,
                accepted_count=2,
                started_count=2,
                final_count=2,
                missing_final_count=1,
                queue_peak_items=2,
            ),
        )
        self.assertEqual(report["outcomes"], {"success": 1, "failed": 1})
        self.assertGreater(
            report["rows"][1]["queue_wait_ns"], report["rows"][0]["queue_wait_ns"]
        )
        self.assertGreaterEqual(
            report["rows"][1]["whole_task_ns"], report["rows"][1]["queue_wait_ns"]
        )
        distribution = report["distributions"][0]
        self.assertEqual(
            (
                distribution["count"],
                distribution["observed_count"],
                distribution["missing_count"],
            ),
            (3, 2, 1),
        )
        self.assertFalse(distribution["coverage_complete"])
        self.assertIsNone(report["physical_energy_joules"])
        self.assertIsNone(report["campaign_process_tree_peak_rss_bytes"])
        self.assertFalse(report["full_system_cost_known"])
        self.assertFalse(report["tail_improvement_qualified"])

    def test_child_failure_preserves_pending_and_original_exception(self):
        self.ledger.accept("one")

        def work():
            subprocess.run([sys.executable, "-c", "raise SystemExit(7)"], check=True)

        with self.assertRaises(subprocess.CalledProcessError) as raised:
            run_observed_task(self.ledger, "one", work)
        self.assertEqual(raised.exception.returncode, 7)
        report = self.ledger.report()
        self.assertEqual(report["final_count"], 0)
        self.assertIsNone(report["rows"][0]["whole_task_ns"])
        self.assertEqual(
            report["rows"][0]["interrupted"], {"error_type": "CalledProcessError"}
        )
        self.assertIsNone(report["external_business_effect_count"])
        with self.assertRaisesRegex(ValueError, "no automatic retry"):
            run_observed_task(
                self.ledger, "one", lambda: self.fail("must not redispatch")
            )

    def test_process_exit_does_not_erase_accepted_queue(self):
        code = """
import os,sys
from hepta_cells.task_observation import TaskLedger
ledger=TaskLedger(sys.argv[1],candidate_sha256=sys.argv[2],clock_id=sys.argv[3])
ledger.accept('one')
os._exit(23)
"""
        result = subprocess.run(
            [sys.executable, "-c", code, str(self.path), CANDIDATE, CLOCK]
        )
        self.assertEqual(result.returncode, 23)
        recovered = TaskLedger(self.path, candidate_sha256=CANDIDATE, clock_id=CLOCK)
        report = recovered.report()
        self.assertEqual(
            (
                report["accepted_count"],
                report["queue_remaining_items"],
                report["missing_final_count"],
            ),
            (1, 1, 3),
        )
        recovered.start("one")
        recovered.finish(
            "one", self.receipt("recovered.json", b"original"), outcome="unknown"
        )
        self.assertEqual(recovered.report()["outcomes"], {"unknown": 1})

    def test_concurrent_helpers_dispatch_only_once(self):
        self.ledger.accept("one")
        code = """
import sys
from pathlib import Path
from hepta_cells.task_observation import TaskLedger,run_observed_task
ledger=TaskLedger(sys.argv[1],candidate_sha256=sys.argv[2],clock_id=sys.argv[3])
def work():
    path=Path(sys.argv[4]);path.write_bytes(b'effect')
    return path,'success'
try:
    run_observed_task(ledger,'one',work)
except ValueError as error:
    if 'no automatic retry' not in str(error): raise
    raise SystemExit(17)
"""
        processes = [
            subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    code,
                    str(self.path),
                    CANDIDATE,
                    CLOCK,
                    str(self.root / (name + ".effect")),
                ]
            )
            for name in ("left", "right")
        ]
        self.assertEqual(
            sorted(process.wait(timeout=10) for process in processes), [0, 17]
        )
        self.assertEqual(len(list(self.root.glob("*.effect"))), 1)
        self.assertEqual(self.ledger.report()["final_count"], 1)

    def test_terminal_conflict_retains_original_and_duplicate_is_idempotent(self):
        self.ledger.accept("one")
        self.ledger.start("one")
        receipt = self.receipt("result.json", b"original")
        self.ledger.finish("one", receipt, outcome="success")
        original = self.ledger.report()
        self.ledger.finish("one", receipt, outcome="success")
        self.assertEqual(self.ledger.report(), original)
        receipt.write_bytes(b"replacement")
        with self.assertRaisesRegex(ValueError, "conflict"):
            self.ledger.finish("one", receipt, outcome="success")
        with self.assertRaisesRegex(ValueError, "receipt changed"):
            self.ledger.report()
        receipt.unlink()
        with self.assertRaisesRegex(ValueError, "receipt unavailable"):
            self.ledger.report()
        self.receipt("result.json", b"original")
        self.assertEqual(self.ledger.report(), original)

    def test_bound_plan_clock_and_acceptance_are_enforced(self):
        for candidate, clock in [("b" * 64, CLOCK), (CANDIDATE, "other-boot")]:
            with self.assertRaisesRegex(ValueError, "identity differs"):
                TaskLedger(self.path, candidate_sha256=candidate, clock_id=clock)
        with self.assertRaisesRegex(ValueError, "unplanned"):
            self.ledger.accept("invented")
        with self.assertRaisesRegex(ValueError, "acceptance"):
            self.ledger.start("one")
        self.ledger.accept("one")
        receipt = self.receipt("cancelled.json", b"cancelled")
        with self.assertRaisesRegex(ValueError, "start event"):
            self.ledger.finish("one", receipt, outcome="success")
        self.ledger.finish("one", receipt, outcome="cancelled")
        self.assertEqual(self.ledger.report()["queue_remaining_items"], 0)


if __name__ == "__main__":
    unittest.main()
