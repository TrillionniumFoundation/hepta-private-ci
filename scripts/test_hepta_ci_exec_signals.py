"""Exercise actual runner cancellation and owned process-group cleanup."""

from __future__ import annotations

import hashlib
import contextlib
import io
import json
import os
from pathlib import Path
import signal
import select
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import hepta_ci_exec as executor

from test_hepta_ci_exec import GitExecutionFixture, RUNNER


@unittest.skipUnless(sys.platform == "linux", "Linux process-state observation")
class CommandSignalTests(GitExecutionFixture):
    def assert_not_running(self, pid):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                state = (
                    Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
                )
            except FileNotFoundError:
                return
            if state == "Z":
                return
            time.sleep(0.01)
        self.fail(f"owned process {pid} survived runner cancellation")

    def cancel(self, signum, *, parent_exits=False):
        ready = self.root / "child-ready.json"
        grandchild = self.root / "grandchild-ready"
        child_code = (
            "import os,time; from pathlib import Path; "
            f"Path({str(grandchild)!r}).write_text(str(os.getpid())); "
            "time.sleep(60)"
        )
        command_code = (
            "import json,os,subprocess,sys,time; from pathlib import Path\n"
            f"child=subprocess.Popen([sys.executable, '-c', {child_code!r}])\n"
            f"while not Path({str(grandchild)!r}).exists(): time.sleep(0.01)\n"
            "print('before cancellation', flush=True)\n"
            f"Path({str(ready)!r}).write_text(json.dumps([os.getpid(),child.pid]))\n"
            + ("raise SystemExit(0)\n" if parent_exits else "time.sleep(60)\n")
        )
        process = subprocess.Popen(
            [
                sys.executable,
                str(RUNNER),
                "--output",
                str(self.result),
                "--timeout-seconds",
                "30",
                "--",
                sys.executable,
                "-c",
                command_code,
            ],
            cwd=self.repo,
            env={
                **os.environ,
                "PYTHONDONTWRITEBYTECODE": "1",
                "SOURCE_SHA": self.source,
                "TESTED_SHA": self.source,
                "BASE_SHA": self.source,
                "HEPTA_CI_LANE": "source-head",
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        pids = []
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if ready.exists():
                    try:
                        pids = json.loads(ready.read_text())
                        break
                    except json.JSONDecodeError:
                        pass
                self.assertIsNone(process.poll(), "runner exited before dispatch")
                time.sleep(0.01)
            self.assertEqual(len(pids), 2, "owned process pair never became ready")
            if parent_exits:
                self.assert_not_running(pids[0])
            readable, _, _ = select.select([process.stdout], [], [], 5)
            self.assertTrue(readable, "runner never retained the child's output")
            self.assertEqual(process.stdout.readline(), "before cancellation\n")
            process.send_signal(signum)
            stdout, stderr = process.communicate(timeout=10)
            record = self.receipt()
            self.assertEqual(process.returncode, 128 + signum, stderr + stdout)
            self.assertEqual(record["status"], "interrupted")
            self.assertEqual(record["interrupted_signal"], signum)
            self.assertEqual(record["exit_code"], 128 + signum)
            self.assertFalse(record["timed_out"])
            self.assertFalse(record["output_limit_exceeded"])
            self.assertEqual(record["before"], record["after"])
            data = (self.root / record["log_file"]).read_bytes()
            self.assertIn(b"before cancellation", data)
            self.assertEqual(record["log_bytes"], len(data))
            self.assertEqual(record["log_sha256"], hashlib.sha256(data).hexdigest())
            self.assertEqual(record["observed_passed_tests"], 0)
            if parent_exits:
                self.assertEqual(record["command_exit_code"], 0)
            for pid in pids:
                self.assert_not_running(pid)
        finally:
            # Cleanup owns only processes created by this test, including on the
            # deliberately red old implementation that abandons its session.
            if process.poll() is None:
                process.kill()
            if pids:
                try:
                    os.killpg(pids[0], signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.communicate(timeout=10)

    def test_cli_restores_handlers_after_actual_command_and_rejection(self):
        previous = {
            number: signal.getsignal(number)
            for number in (signal.SIGINT, signal.SIGTERM)
        }
        for tested, expected in [(self.source, 0), ("f" * 40, 2)]:
            with self.subTest(tested=tested):
                self.result.unlink(missing_ok=True)
                argv = [
                    str(RUNNER),
                    "--output",
                    str(self.result),
                    "--",
                    sys.executable,
                    "-c",
                    "print('finished')",
                ]
                with (
                    patch.object(sys, "argv", argv),
                    patch.dict(
                        os.environ,
                        {
                            "SOURCE_SHA": self.source,
                            "TESTED_SHA": tested,
                            "HEPTA_CI_LANE": "source-head",
                        },
                    ),
                    contextlib.chdir(self.repo),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    self.assertEqual(executor.main(), expected)
                self.assertEqual(
                    {number: signal.getsignal(number) for number in previous}, previous
                )

    def test_cancellation_during_reaping_preserves_real_exit_and_log(self):
        cancellation = executor.CommandCancellation()
        wait = subprocess.Popen.wait

        def cancel_then_reap(process, *args, **kwargs):
            cancellation.request(signal.SIGTERM, None)
            cancellation.request(signal.SIGINT, None)
            return wait(process, *args, **kwargs)

        log = self.root / "late-cancellation.log"
        with (
            patch.object(subprocess.Popen, "wait", cancel_then_reap),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            record = executor.execute_logged(
                [sys.executable, "-c", "print('finished')"],
                log,
                cancellation=cancellation,
            )
        self.assertEqual(record["returncode"], 0)
        self.assertEqual(record["interrupted_signal"], signal.SIGTERM)
        self.assertEqual(
            record["log_sha256"], hashlib.sha256(log.read_bytes()).hexdigest()
        )

    def test_sigterm_retains_terminal_record_and_reaps_owned_processes(self):
        self.cancel(signal.SIGTERM)

    def test_sigint_preserves_log_identity_and_reaps_owned_processes(self):
        self.cancel(signal.SIGINT)

    def test_sigterm_is_not_success_when_parent_exited_but_pipe_is_held(self):
        self.cancel(signal.SIGTERM, parent_exits=True)


if __name__ == "__main__":
    unittest.main()
