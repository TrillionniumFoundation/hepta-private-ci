"""Real subprocess regressions; synthetic commands are not native qualification."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
import unittest

from command_process import CaptureError, MAX_LOG_BYTES, capture_command, closed_capture
from run_qualification import run_check


@unittest.skipUnless(os.name == "posix", "selected qualification host is POSIX")
class CommandProcessTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def capture(self, program, maximum=MAX_LOG_BYTES, timeout=3):
        path = self.root / "command.log"
        result = capture_command([sys.executable, "-c", program], self.root, path, timeout, maximum)
        return result, path

    def test_normal_command_has_complete_stable_bytes(self):
        result = run_check("normal", [sys.executable, "-c", "print('complete')"], self.root, self.root)
        self.assertEqual(result["status"], "passed")
        self.assertTrue(closed_capture(result))
        self.assertEqual(result["log_bytes"], len(b"complete\n"))
        self.assertEqual(result["log_sha256"], hashlib.sha256(b"complete\n").hexdigest())

    def test_parent_exit_does_not_seal_a_live_descendant(self):
        marker = self.root / "late-side-effect"
        child = ("import time; from pathlib import Path; time.sleep(0.5); "
                 f"Path({str(marker)!r}).write_text('late'); print('late', flush=True)")
        parent = f"import subprocess,sys; subprocess.Popen([sys.executable,'-c',{child!r}])"
        result = run_check("residual", [sys.executable, "-c", parent], self.root, self.root)
        self.assertEqual(result["status"], "infrastructure_invalid")
        self.assertFalse(result["log_complete"])
        initial = (self.root / "residual.log").read_bytes()
        time.sleep(0.7)
        self.assertFalse(marker.exists())
        self.assertEqual((self.root / "residual.log").read_bytes(), initial)
        self.assertEqual(result["log_sha256"], hashlib.sha256(initial).hexdigest())

    def test_descendant_without_inherited_stdout_still_prevents_success(self):
        marker = self.root / "detached-output"
        child = f"import time; from pathlib import Path; time.sleep(0.4); Path({str(marker)!r}).touch()"
        parent = ("import subprocess,sys; subprocess.Popen([sys.executable,'-c',"
                  f"{child!r}], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)")
        result, _ = self.capture(parent)
        self.assertEqual(result["status"], "infrastructure_invalid")
        time.sleep(0.6)
        self.assertFalse(marker.exists())

    def test_waited_child_is_not_mistaken_for_a_residual_descendant(self):
        child = "print('child', flush=True)"
        parent = f"import subprocess,sys; subprocess.run([sys.executable,'-c',{child!r}],check=True)"
        result, path = self.capture(parent)
        self.assertEqual(result["status"], "passed")
        self.assertTrue(closed_capture(result))
        self.assertEqual(path.read_bytes(), b"child\n")

    def test_timeout_cleans_descendants_and_keeps_a_nonpassing_prefix(self):
        marker = self.root / "timeout-side-effect"
        child = f"import time; from pathlib import Path; time.sleep(2); Path({str(marker)!r}).touch()"
        parent = (f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); "
                  "print('before timeout',flush=True); time.sleep(5)")
        result, path = self.capture(parent, timeout=1)
        self.assertEqual(result["status"], "infrastructure_invalid")
        self.assertFalse(result["log_complete"])
        self.assertIn(b"before timeout", path.read_bytes())
        time.sleep(2.2)
        self.assertFalse(marker.exists())

    def test_exact_log_budget_preserves_all_bytes(self):
        result, path = self.capture("import os; os.write(1,b'x'*4096)", maximum=4096)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(path.read_bytes(), b"x" * 4096)
        self.assertTrue(result["log_complete"])

    def test_one_byte_over_budget_is_not_a_success(self):
        result, path = self.capture("import os; os.write(1,b'x'*4097)", maximum=4096)
        self.assertEqual(result["status"], "infrastructure_invalid")
        self.assertFalse(result["log_complete"])
        self.assertEqual(result["log_bytes"], 4096)
        self.assertEqual(path.read_bytes(), b"x" * 4096)

    def test_unbounded_writer_is_stopped_without_unbounded_disk_use(self):
        result, path = self.capture("import os\nwhile True: os.write(1,b'x'*65536)", maximum=4096)
        self.assertEqual(result["status"], "infrastructure_invalid")
        self.assertEqual(path.stat().st_size, 4096)

    def test_early_output_eof_does_not_hide_a_running_leader(self):
        result, _ = self.capture("import os,time; os.close(1); os.close(2); time.sleep(5)", timeout=0.15)
        self.assertEqual(result["status"], "infrastructure_invalid")
        self.assertFalse(result["log_complete"])

    def test_failure_and_signal_have_distinct_classification(self):
        result, path = self.capture("print('failure'); raise SystemExit(9)")
        self.assertEqual((result["status"], result["exit_code"]), ("failed", 9))
        self.assertTrue(closed_capture(result))
        path.unlink()
        result, _ = self.capture(f"import os; os.kill(os.getpid(), {int(signal.SIGTERM)})")
        self.assertEqual(result["status"], "infrastructure_invalid")
        self.assertEqual(result["exit_code"], -signal.SIGTERM)

    def test_missing_program_is_infrastructure_invalid(self):
        result = capture_command([str(self.root / "absent")], self.root, self.root / "missing.log", 3)
        self.assertEqual((result["status"], result["exit_code"]), ("infrastructure_invalid", None))
        self.assertFalse(closed_capture(result))

    def test_existing_and_symlinked_logs_are_not_overwritten(self):
        path = self.root / "command.log"
        path.write_bytes(b"historical evidence")
        with self.assertRaises(FileExistsError):
            self.capture("print('replacement')")
        self.assertEqual(path.read_bytes(), b"historical evidence")
        target = self.root / "target.log"
        path.rename(target)
        path.symlink_to(target)
        with self.assertRaises(FileExistsError):
            self.capture("print('replacement')")
        self.assertEqual(target.read_bytes(), b"historical evidence")

    def test_unsafe_names_and_invalid_limits_fail_before_execution(self):
        for name in ("../escape", "/absolute", "", "a/b"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                run_check(name, [sys.executable, "-c", "raise AssertionError()"], self.root, self.root)
        for timeout in (True, 0, -1, float("nan"), float("inf")):
            with self.subTest(timeout=timeout), self.assertRaises(CaptureError):
                self.capture("raise AssertionError()", timeout=timeout)
        for maximum in (True, 0, -1, MAX_LOG_BYTES + 1):
            with self.subTest(maximum=maximum), self.assertRaises(CaptureError):
                self.capture("raise AssertionError()", maximum=maximum)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_closure_facts_are_strict_not_truthy(self):
        record = {"capture_version": 1, "log_complete": True, "process_group_closed": True,
                  "log_limit_bytes": MAX_LOG_BYTES, "log_bytes": 0}
        self.assertTrue(closed_capture(record))
        for key, value in (("capture_version", True), ("log_complete", 1),
                           ("process_group_closed", "true"), ("log_bytes", False),
                           ("log_bytes", -1), ("log_bytes", MAX_LOG_BYTES + 1),
                           ("log_limit_bytes", MAX_LOG_BYTES * 2)):
            with self.subTest(key=key, value=value):
                self.assertFalse(closed_capture({**record, key: value}))
        for key in record:
            changed = dict(record)
            del changed[key]
            self.assertFalse(closed_capture(changed))


if __name__ == "__main__":
    unittest.main()
