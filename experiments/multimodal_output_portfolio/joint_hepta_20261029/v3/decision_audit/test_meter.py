"""Real short subprocesses exercise containment, never model execution."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from . import meter


execute = meter.execute
EXIT_ZERO_ON_TERM = "import os, signal, sys, time\nsignal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n"


def descendant_command(pid_path, wait):
    descendant = ("import os, signal, sys, time\nfrom pathlib import Path\n"
                  "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                  "Path(sys.argv[1]).write_text(str(os.getpid()))\ntime.sleep(30)")
    return [sys.executable, "-c", EXIT_ZERO_ON_TERM +
            "import subprocess\nfrom pathlib import Path\n" +
            f"p = Path({str(pid_path)!r})\n" +
            f"subprocess.Popen([sys.executable, '-c', {descendant!r}, str(p)])\n" +
            "while not p.exists(): time.sleep(.01)\n" + ("time.sleep(30)" if wait else "")]


def running(pid):
    try:
        os.kill(pid, 0)
        stat = Path(f"/proc/{pid}/stat")
        if stat.exists() and stat.read_text().rsplit(")", 1)[1].split()[0] == "Z":
            return False  # A killed orphan may await its host reaper.
        return True
    except ProcessLookupError:
        return False
    except FileNotFoundError:
        return False


class PhysicalCommandMeter(unittest.TestCase):
    def test_failed_command_keeps_its_physical_attempt_and_cost(self):
        with tempfile.TemporaryDirectory(dir="/dev/shm") as folder:
            path = Path(folder) / "cost.json"
            row = execute([sys.executable, "-c", "raise SystemExit(7)"], path)
            self.assertEqual(row["return_code"], 7)
            self.assertEqual(row["status"], "failed")
            self.assertEqual(json.loads(path.read_text()), row)
            self.assertGreater(row["wall_seconds"], 0)
            self.assertGreaterEqual(row["child_cpu_seconds"], 0)
            self.assertTrue(row["do_not_add_to_nested_costs"])
            with self.assertRaises(FileExistsError):
                execute([sys.executable, "-c", "pass"], path)

    def test_successful_command_is_separately_metered(self):
        with tempfile.TemporaryDirectory(dir="/dev/shm") as folder:
            row = execute([sys.executable, "-c", "sum(range(10000))"], Path(folder) / "cost.json",
                          wall_timeout_seconds=2)
            self.assertEqual(row["status"], "completed")
            self.assertEqual(row["return_code"], 0)
            self.assertEqual(row["child_return_code"], 0)
            self.assertFalse(row["cancelled"])
            self.assertFalse(row["timed_out"])

    def test_deadline_cannot_become_success_when_child_handles_term(self):
        with tempfile.TemporaryDirectory(dir="/dev/shm") as folder:
            path = Path(folder) / "cost.json"
            row = execute([sys.executable, "-c", EXIT_ZERO_ON_TERM + "time.sleep(30)"], path,
                          wall_timeout_seconds=.4, termination_grace_seconds=.15)
            self.assertEqual((row["status"], row["return_code"], row["child_return_code"]),
                             ("timed_out", 124, 0))
            self.assertTrue(row["timed_out"])
            self.assertGreaterEqual(row["wall_seconds"], .4)
            self.assertLess(row["wall_seconds"], 3)
            self.assertEqual(json.loads(path.read_text()), row)

    def check_descendant(self, wait):
        with tempfile.TemporaryDirectory(dir="/dev/shm") as folder:
            pid_path = Path(folder) / "descendant.pid"
            try:
                row = execute(descendant_command(pid_path, wait), Path(folder) / "cost.json",
                              wall_timeout_seconds=1, termination_grace_seconds=.15)
                pid = int(pid_path.read_text())
                deadline = time.perf_counter() + 1
                while running(pid) and time.perf_counter() < deadline:
                    time.sleep(.01)
                self.assertFalse(running(pid), "A live descendant survived group cleanup")
                self.assertEqual(row["child_return_code"], 0)
                self.assertEqual(row["status"], "timed_out" if wait else "failed")
                self.assertNotEqual(row["return_code"], 0)
                self.assertIn(signal.SIGKILL, row["termination"]["signals_sent"])
                self.assertIn("descendant_usage_not_reaped_by_command_leader", row["unknown_outer_costs"])
                self.assertLess(row["wall_seconds"], 3)
            finally:
                if pid_path.exists() and running(int(pid_path.read_text())):
                    os.kill(int(pid_path.read_text()), signal.SIGKILL)

    def test_timeout_kills_ignoring_descendant_after_leader_exits_zero(self):
        self.check_descendant(wait=True)

    def test_successful_leader_cannot_abandon_live_descendant(self):
        self.check_descendant(wait=False)

    def test_sigterm_finalizes_costs_and_restores_handlers(self):
        prior = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
        called = []
        handler = lambda *args: called.append(args)
        try:
            signal.signal(signal.SIGTERM, handler)
            with tempfile.TemporaryDirectory(dir="/dev/shm") as folder:
                path = Path(folder) / "cost.json"
                row = execute([sys.executable, "-c", EXIT_ZERO_ON_TERM +
                               "os.kill(os.getppid(), signal.SIGTERM)\ntime.sleep(30)"], path,
                              wall_timeout_seconds=2, termination_grace_seconds=.15)
                self.assertEqual((row["status"], row["return_code"], row["child_return_code"]),
                                 ("cancelled", 143, 0))
                self.assertTrue(row["cancelled"])
                self.assertEqual(row["cancellation_signal"], signal.SIGTERM)
                self.assertEqual(json.loads(path.read_text()), row)
                self.assertGreater(row["wall_seconds"], 0)
                self.assertGreaterEqual(row["child_cpu_seconds"], 0)
            self.assertIs(signal.getsignal(signal.SIGTERM), handler)
            self.assertIs(signal.getsignal(signal.SIGINT), prior[signal.SIGINT])
            self.assertEqual(called, [])
        finally:
            for signum, old in prior.items():
                signal.signal(signum, old)

    def cli(self, path, code, deadline):
        try:
            return subprocess.run([sys.executable, "-B", "-m", meter.__name__, "--output", str(path),
                                   "--wall-timeout-seconds", str(deadline),
                                   "--termination-grace-seconds", ".15", "--", sys.executable, "-c", code],
                                  capture_output=True, text=True, timeout=5)
        finally:
            if path.exists():
                pid = json.loads(path.read_text()).get("child_pid")
                if pid:
                    try:
                        os.killpg(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_cli_timeout_has_terminal_receipt_and_nonzero_exit(self):
        with tempfile.TemporaryDirectory(dir="/dev/shm") as folder:
            path = Path(folder) / "cost.json"
            result = self.cli(path, EXIT_ZERO_ON_TERM + "time.sleep(30)", .4)
            self.assertEqual(result.returncode, 124, result.stderr)
            self.assertEqual(json.loads(path.read_text())["status"], "timed_out")

    def test_cli_sigterm_and_sigint_cannot_become_success(self):
        for signum in (signal.SIGTERM, signal.SIGINT):
            with self.subTest(signal=signum), tempfile.TemporaryDirectory(dir="/dev/shm") as folder:
                path = Path(folder) / "cost.json"
                result = self.cli(path, EXIT_ZERO_ON_TERM +
                                  f"os.kill(os.getppid(), {int(signum)})\ntime.sleep(30)", 2)
                row = json.loads(path.read_text())
                self.assertEqual(result.returncode, 128 + signum, result.stderr)
                self.assertEqual(row["status"], "cancelled")
                self.assertEqual(row["child_return_code"], 0)
                self.assertGreaterEqual(row["child_cpu_seconds"], 0)

    def test_spawn_failure_keeps_terminal_receipt(self):
        with tempfile.TemporaryDirectory(dir="/dev/shm") as folder:
            path = Path(folder) / "cost.json"
            row = execute([str(Path(folder) / "missing-command")], path, wall_timeout_seconds=1)
            self.assertEqual(row["status"], "failed")
            self.assertIsNone(row["child_return_code"])
            self.assertEqual(row["error"]["type"], "FileNotFoundError")
            self.assertEqual(json.loads(path.read_text()), row)

    def test_invalid_limits_are_rejected_before_command_or_receipt(self):
        with tempfile.TemporaryDirectory(dir="/dev/shm") as folder:
            path = Path(folder) / "cost.json"
            for name in ("wall_timeout_seconds", "termination_grace_seconds"):
                for value in (0, -1, float("nan"), float("inf"), True):
                    with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                        execute([sys.executable, "-c", "pass"], path, **{name: value})
            self.assertFalse(path.exists())

    def test_sigterm_during_cost_collection_is_not_lost(self):
        original, calls = meter.resource.getrusage, []

        def usage(kind):
            calls.append(kind)
            if len(calls) == 2:
                os.kill(os.getpid(), signal.SIGTERM)
            return original(kind)

        with tempfile.TemporaryDirectory(dir="/dev/shm") as folder:
            path = Path(folder) / "cost.json"
            with patch.object(meter.resource, "getrusage", side_effect=usage):
                row = execute([sys.executable, "-c", "pass"], path, wall_timeout_seconds=2)
            self.assertEqual((row["status"], row["return_code"], row["child_return_code"]),
                             ("cancelled", 143, 0))
            self.assertEqual(json.loads(path.read_text()), row)

    def test_sigterm_during_receipt_commit_is_reconciled(self):
        original, calls = meter._write_receipt, []

        def write(path, row):
            original(path, row)
            calls.append(row["status"])
            if row["status"] == "completed":
                os.kill(os.getpid(), signal.SIGTERM)

        with tempfile.TemporaryDirectory(dir="/dev/shm") as folder:
            path = Path(folder) / "cost.json"
            with patch.object(meter, "_write_receipt", side_effect=write):
                row = execute([sys.executable, "-c", "pass"], path, wall_timeout_seconds=2)
            self.assertEqual(row["return_code"], 143)
            self.assertEqual(row["status"], "cancelled")
            self.assertEqual(calls[-1], "cancelled")
            self.assertEqual(json.loads(path.read_text()), row)

    def test_cleanup_error_cannot_claim_complete_descendant_cost(self):
        with tempfile.TemporaryDirectory(dir="/dev/shm") as folder:
            path = Path(folder) / "cost.json"
            with patch.object(meter, "_group_exists", side_effect=PermissionError("cleanup unavailable")):
                row = execute([sys.executable, "-c", "pass"], path, wall_timeout_seconds=2)
            self.assertEqual(row["status"], "failed")
            self.assertIn("descendant_usage_not_reaped_by_command_leader", row["unknown_outer_costs"])
            self.assertEqual(row["child_return_code"], 0)


if __name__ == "__main__":
    unittest.main()
