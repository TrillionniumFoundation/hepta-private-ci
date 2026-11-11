"""Lost result records must not turn attempted model work into zero cost."""

import unittest
from unittest.mock import patch

import run_loop
from loop_common import read
import loop_tests


class AttemptAccounting(unittest.TestCase):
    def test_lost_completed_receipt_preserves_unknown_prior_cost(self):
        with loop_tests.ResumeBoundary().fixture() as (run, args):
            run_loop.main(args)
            (run / "phase_results/bootstrap.json").unlink()
            args.resume = True
            with patch.object(run_loop.subprocess, "run", wraps=run_loop.subprocess.run) as launch:
                with self.assertRaisesRegex(ValueError, "no implicit retry"):
                    run_loop.main(args)
                launch.assert_not_called()
            cost = read(run / "FAILED-02.json")["measured_cost"]
            for field in ("worker_cpu_user_seconds", "worker_cpu_system_seconds",
                          "worker_wall_seconds", "peak_worker_rss_bytes"):
                self.assertIsNone(cost[field], field)

    def test_unvisited_attempt_is_reconciled_before_any_phase_dispatch(self):
        with loop_tests.ResumeBoundary().fixture() as (run, args):
            run_loop.main(args)
            attempted = run / "attempts/feedback"
            attempted.mkdir()
            (attempted / "stdout.txt").write_bytes(b"unsettled worker output")
            args.resume = True
            with patch.object(run_loop.subprocess, "run", wraps=run_loop.subprocess.run) as launch:
                with self.assertRaisesRegex(ValueError, "no implicit retry"):
                    run_loop.main(args)
                launch.assert_not_called()
            summary = read(run / "FAILED-02.json")
            self.assertFalse(summary["engineering_passed"])
            self.assertEqual(summary["completed_phases"], ["bootstrap"])
            self.assertIn("feedback", summary["unverified_phase_receipts"])
            self.assertIsNone(summary["measured_cost"]["worker_wall_seconds"])
            self.assertEqual((attempted / "stdout.txt").read_bytes(), b"unsettled worker output")

    def test_unknown_attempt_roster_prevents_later_model_work(self):
        with loop_tests.ResumeBoundary().fixture() as (run, args):
            run_loop.main(args)
            (run / "attempts/unregistered").mkdir()
            args.resume = True
            args.stop_after = "feedback"
            with patch.object(run_loop.subprocess, "run", wraps=run_loop.subprocess.run) as launch:
                with self.assertRaisesRegex(ValueError, "no implicit retry"):
                    run_loop.main(args)
                launch.assert_not_called()
            summary = read(run / "FAILED-02.json")
            self.assertIn("unregistered", summary["unverified_phase_receipts"])
            self.assertIsNone(summary["measured_cost"]["worker_cpu_user_seconds"])

    def test_dispatch_exception_leaves_attempt_cost_unknown(self):
        with loop_tests.ResumeBoundary().fixture() as (run, args):
            with patch.object(run_loop.subprocess, "run", side_effect=OSError("dispatch outcome unavailable")):
                with self.assertRaises(OSError):
                    run_loop.main(args)
            summary = read(run / "FAILED-01.json")
            self.assertFalse(summary["engineering_passed"])
            self.assertIn("bootstrap", summary["unverified_phase_receipts"])
            self.assertIsNone(summary["measured_cost"]["worker_cpu_system_seconds"])
            self.assertIsNone(summary["measured_cost"]["worker_wall_seconds"])

    def test_linked_attempt_inventory_is_not_traversed_or_costed(self):
        with loop_tests.ResumeBoundary().fixture() as (run, args):
            run_loop.main(args)
            target = run.parent / "external"
            target.mkdir()
            (target / "kept").write_bytes(b"preserve")
            (run / "attempts/feedback").symlink_to(target, target_is_directory=True)
            args.resume = True
            with patch.object(run_loop.subprocess, "run", wraps=run_loop.subprocess.run) as launch:
                with self.assertRaisesRegex(ValueError, "no implicit retry"):
                    run_loop.main(args)
                launch.assert_not_called()
            summary = read(run / "FAILED-02.json")
            self.assertIn("feedback", summary["unverified_phase_receipts"])
            self.assertIsNone(summary["measured_cost"]["worker_wall_seconds"])
            self.assertEqual((target / "kept").read_bytes(), b"preserve")


if __name__ == "__main__":
    unittest.main()
