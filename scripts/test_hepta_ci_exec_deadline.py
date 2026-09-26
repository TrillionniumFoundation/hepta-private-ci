"""Exercise actual process deadlines; no mocked process or fabricated test success."""

from __future__ import annotations

import contextlib
import hashlib
import io
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

import hepta_ci_exec as executor


class CommandDeadlineTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.log = self.root / "command.log"

    def execute(self, code, **kwargs):
        started = time.monotonic()
        with contextlib.redirect_stdout(io.StringIO()):
            record = executor.execute_logged(
                [sys.executable, "-c", code],
                self.log,
                timeout_seconds=0.75,
                **kwargs,
            )
        self.assertLess(
            time.monotonic() - started, 10, "command lifecycle did not converge"
        )
        data = self.log.read_bytes()
        self.assertEqual(record["log_bytes"], len(data))
        self.assertEqual(record["log_sha256"], hashlib.sha256(data).hexdigest())
        return record

    def test_silent_process_times_out(self):
        record = self.execute("import time; time.sleep(60)")
        self.assertTrue(record["timed_out"])
        self.assertNotEqual(record["returncode"], 0)
        self.assertEqual(record["observed_passed_tests"], 0)

    def test_diagnostics_before_timeout_survive(self):
        record = self.execute(
            "import time; print('before timeout', flush=True); time.sleep(60)"
        )
        self.assertTrue(record["timed_out"])
        self.assertEqual(self.log.read_bytes(), b"before timeout\n")

    @unittest.skipUnless(os.name == "posix", "POSIX process-group semantics")
    def test_eof_is_not_completion(self):
        record = self.execute(
            "import os,time; os.close(1); os.close(2); time.sleep(60)"
        )
        self.assertTrue(record["timed_out"])
        self.assertNotEqual(record["returncode"], 0)

    @unittest.skipUnless(sys.platform == "linux", "Linux process-state observation")
    def test_exited_parent_cannot_leave_a_running_pipe_holder(self):
        record = self.execute(
            "import subprocess,sys\n"
            "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\n"
            "print(child.pid, flush=True)\n"
        )
        self.assertTrue(record["timed_out"])
        self.assertEqual(
            record["returncode"], 0, "parent itself should have exited normally"
        )
        child_pid = int(self.log.read_text().strip())
        # An orphan may briefly remain a zombie until init reaps it. It must no
        # longer execute or retain a pipe after process-group cancellation.
        for _ in range(100):
            stat = Path(f"/proc/{child_pid}/stat")
            try:
                state = stat.read_text().rsplit(")", 1)[1].split()[0]
            except (FileNotFoundError, ProcessLookupError):
                # The process can disappear between resolving /proc and reading
                # stat. Vanishing is the successful terminal condition here.
                break
            if state == "Z":
                break
            time.sleep(0.01)
        else:
            os.kill(child_pid, signal.SIGKILL)
            self.fail("descendant survived process-group cancellation")

    @unittest.skipUnless(os.name == "posix", "POSIX session semantics")
    def test_detached_pipe_holder_does_not_deadlock_stream_close(self):
        child_pid = None
        try:
            record = self.execute(
                "import subprocess,sys\n"
                "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],"
                "start_new_session=True)\n"
                "print(child.pid, flush=True)\n"
            )
            child_pid = int(self.log.read_text().strip())
            self.assertTrue(record["timed_out"])
        finally:
            # Deliberately escaped sessions need a real sandbox in production;
            # the executor does not claim to own or terminate them.
            if child_pid is not None:
                try:
                    os.kill(child_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_normal_exit_is_not_a_timeout(self):
        record = self.execute("print('finished')")
        self.assertEqual(record["returncode"], 0)
        self.assertFalse(record["timed_out"])
        self.assertFalse(record["output_limit_exceeded"])

    def test_output_cap_remains_independent_of_deadline(self):
        record = self.execute(
            "import sys; sys.stdout.write('x'*100000)", maximum_bytes=73
        )
        self.assertTrue(record["output_limit_exceeded"])
        self.assertFalse(record["timed_out"])
        self.assertEqual(self.log.read_bytes(), b"x" * 73)

    def test_invalid_bounds_dispatch_nothing(self):
        for bound in (0, -1, True, float("nan"), float("inf")):
            with (
                self.subTest(bound=bound),
                patch.object(executor.subprocess, "Popen") as popen,
            ):
                with self.assertRaises(ValueError):
                    executor.execute_logged(
                        ["not-dispatched"], self.log, timeout_seconds=bound
                    )
                popen.assert_not_called()
        self.assertFalse(self.log.exists())

    def test_cli_retains_failed_receipt_instead_of_successful_parent_exit(self):
        repo = self.root / "repo"
        repo.mkdir()

        def git(*args):
            return subprocess.check_output(
                ["git", "-C", str(repo), *args], text=True, stderr=subprocess.PIPE
            ).strip()

        git("init", "-q")
        git("config", "user.name", "deadline fixture")
        git("config", "user.email", "deadline@example.invalid")
        (repo / "input").write_text("owned source\n")
        git("add", "input")
        git("commit", "-qm", "fixture")
        sha = git("rev-parse", "HEAD")
        output = self.root / "result.json"
        command = [
            sys.executable,
            str(Path(executor.__file__).resolve()),
            "--output",
            str(output),
            "--timeout-seconds",
            "0.5",
            "--",
            sys.executable,
            "-c",
            "import time; time.sleep(60)",
        ]
        result = subprocess.run(
            command,
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=10,
            env={
                **os.environ,
                "SOURCE_SHA": sha,
                "TESTED_SHA": sha,
                "BASE_SHA": sha,
                "HEPTA_CI_LANE": "source-head",
            },
        )
        record = json.loads(output.read_text())
        self.assertEqual(result.returncode, 124, result.stderr)
        self.assertEqual(record["status"], "failed")
        self.assertTrue(record["timed_out"])
        self.assertEqual(record["before"], record["after"])
        self.assertEqual(record["exit_code"], 124)


if __name__ == "__main__":
    unittest.main()
