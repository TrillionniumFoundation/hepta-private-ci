"""Real bounded child processes; no encoder, model, or optimizer calls."""

import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from phase_process import complete_cpu_total, run_phase


class PhaseProcessTests(unittest.TestCase):
    def invoke(self, script, *, deadline=2):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "worker.log"
            result = run_phase(
                [sys.executable, "-B", "-c", script], log, dict(os.environ),
                wall_seconds=deadline, cleanup_seconds=1,
            )
            return result, log.read_bytes()

    def test_success_retains_exact_output_and_waited_cost(self):
        result, output = self.invoke('print("complete", flush=True)')
        self.assertEqual(output, b"complete\n")
        self.assertEqual(result["exit_code"], 0)
        self.assertTrue(result["direct_child_reaped"])
        self.assertFalse(result["timed_out"])
        self.assertFalse(result["termination_requested"])
        self.assertGreaterEqual(result["cpu_user_seconds"], 0)
        self.assertGreater(result["peak_rss_bytes"], 0)

    def test_failure_keeps_exit_and_stderr(self):
        result, output = self.invoke('import sys; print("failed", file=sys.stderr); sys.exit(7)')
        self.assertEqual((result["exit_code"], output), (7, b"failed\n"))
        self.assertTrue(result["direct_child_reaped"])

    def test_sleeping_child_times_out_and_is_reaped(self):
        result, _ = self.invoke('import time; time.sleep(120)', deadline=0.15)
        self.assertTrue(result["timed_out"])
        self.assertTrue(result["termination_requested"])
        self.assertTrue(result["direct_child_reaped"])
        self.assertEqual(result["exit_code"], -signal.SIGKILL)
        self.assertLess(result["wall_seconds"], 2)
        with self.assertRaises(ChildProcessError):
            os.waitpid(result["pid"], os.WNOHANG)

    def test_unknown_wait_result_is_not_zero_cost(self):
        class Child:
            pid = 123456789
            returncode = None

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(subprocess, "Popen", return_value=Child()):
                with patch("phase_process.os.wait4", return_value=(0, 0, None)):
                    with patch("phase_process.os.killpg") as kill:
                        result = run_phase(
                            ["not-executed"], Path(directory) / "unknown.log", {},
                            wall_seconds=0.01, cleanup_seconds=0.01,
                        )
            kill.assert_called_once_with(Child.pid, signal.SIGKILL)
        self.assertTrue(result["timed_out"])
        self.assertFalse(result["direct_child_reaped"])
        for field in ("exit_code", "cpu_user_seconds", "cpu_system_seconds", "peak_rss_bytes"):
            self.assertIsNone(result[field])
        self.assertIsNone(complete_cpu_total([{"process_metrics": result}], "cpu_user_seconds"))

    def test_lost_wait_ownership_never_signals_pid(self):
        class Child:
            pid = 123456789
            returncode = None

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(subprocess, "Popen", return_value=Child()):
                with patch("phase_process.os.wait4", side_effect=ChildProcessError("lost wait")):
                    with patch("phase_process.os.killpg") as kill:
                        result = run_phase(
                            ["not-executed"], Path(directory) / "lost.log", {},
                            wall_seconds=0.01, cleanup_seconds=0.01,
                        )
            kill.assert_not_called()
        self.assertEqual(result["wait_error"], "lost wait")
        self.assertFalse(result["direct_child_reaped"])

    def test_bad_deadline_rejects_before_spawn(self):
        for bad in (False, 0, -1, float("nan"), float("inf")):
            with self.subTest(deadline=bad), patch.object(subprocess, "Popen") as spawn:
                with self.assertRaises(ValueError):
                    run_phase([], "unused.log", {}, wall_seconds=bad, cleanup_seconds=1)
                spawn.assert_not_called()

    def test_success_observed_after_deadline_cannot_pass(self):
        class Child:
            pid = 123456789
            returncode = None

        usage = SimpleNamespace(ru_utime=0.1, ru_stime=0.2, ru_maxrss=64)
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(subprocess, "Popen", return_value=Child()):
                with patch("phase_process.os.wait4", return_value=(Child.pid, 0, usage)):
                    with patch("phase_process.time.monotonic", side_effect=[0, 2, 2]):
                        result = run_phase(
                            ["not-executed"], Path(directory) / "late.log", {},
                            wall_seconds=1, cleanup_seconds=1,
                        )
        self.assertEqual(result["exit_code"], 0)
        self.assertTrue(result["direct_child_reaped"])
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["cpu_user_seconds"], 0.1)

    def test_signal_failure_retains_unknown_cost(self):
        class Child:
            pid = 123456789
            returncode = None

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(subprocess, "Popen", return_value=Child()):
                with patch("phase_process.os.wait4", return_value=(0, 0, None)):
                    with patch("phase_process.os.killpg", side_effect=PermissionError("denied")):
                        result = run_phase(
                            ["not-executed"], Path(directory) / "denied.log", {},
                            wall_seconds=0.01, cleanup_seconds=0.01,
                        )
        self.assertEqual(result["termination_error"], "denied")
        self.assertFalse(result["direct_child_reaped"])
        self.assertIsNone(result["cpu_user_seconds"])

    def test_log_sync_failure_keeps_real_exit_and_cost(self):
        with patch("phase_process.os.fsync", side_effect=OSError("sync failed")):
            result, output = self.invoke('print("complete", flush=True)')
        self.assertEqual((result["exit_code"], output), (0, b"complete\n"))
        self.assertEqual(result["log_error"], "sync failed")
        self.assertTrue(result["direct_child_reaped"])
        self.assertGreaterEqual(result["cpu_user_seconds"], 0)


if __name__ == "__main__":
    unittest.main()
