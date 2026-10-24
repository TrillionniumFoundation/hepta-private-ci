"""Real no-model subprocess checks for hard timeout and restart accounting."""

from pathlib import Path
import sys
import tempfile
import unittest

from budget_ledger import BudgetLedger, GAUGES, METERS
from budget_process import run_job


@unittest.skipUnless(sys.platform == "linux", "Linux process enforcement")
class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.ledger = BudgetLedger(
            self.root / "ledger.sqlite3",
            arm="retrieval",
            protocol_sha256="a" * 64,
            limits={k: 10**12 for k in METERS},
            gauges={k: 10**12 for k in GAUGES},
            prices={k: 1 for k in METERS},
            cost_limit=10**13,
        )
        self.bound = dict(
            wall_ns=3_000_000_000, cpu_ns=2_000_000_000, write_bytes=2 * 1024 * 1024
        )

    def test_actual_command_is_reaped_measured_and_idempotently_reopened(self):
        args = dict(
            argv=[sys.executable, "-B", "-c", "print(sum(range(1000)))"],
            directory=self.root / "success",
            timeout_ns=1_000_000_000,
            upper_bound=self.bound,
        )
        first = run_job(self.ledger, "once", "index", **args)
        second = run_job(self.ledger, "once", "index", **args)
        self.assertEqual(first, second)
        self.assertEqual((first["returncode"], first["process_reaped"]), (0, True))
        self.assertGreater(first["actual"]["cpu_ns"], 0)
        self.assertEqual((self.root / "success/stdout.log").read_text(), "499500\n")

    def test_inflight_work_is_killed_at_deadline_and_remains_in_cost(self):
        receipt = run_job(
            self.ledger,
            "deadline",
            "infer",
            argv=[sys.executable, "-B", "-c", "while True: pass"],
            directory=self.root / "timeout",
            timeout_ns=150_000_000,
            upper_bound=self.bound,
        )
        self.assertTrue(receipt["timed_out"])
        self.assertLess(receipt["returncode"], 0)
        self.assertGreater(self.ledger.snapshot()["used"]["cpu_ns"], 0)

    def test_no_opaque_model_counter_is_accepted_as_measured(self):
        with self.assertRaises(ValueError):
            run_job(
                self.ledger,
                "fake",
                "train",
                argv=[sys.executable, "-B", "-c", "pass"],
                directory=self.root / "fake",
                timeout_ns=10**8,
                upper_bound=self.bound,
                work_counters={"decoder_updates": 10},
            )
        self.assertEqual(self.ledger.snapshot()["events"], [])


if __name__ == "__main__":
    unittest.main()
