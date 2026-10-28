"""Exercise real pipe backpressure without suspending the owned command deadline."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


RUNNER = Path(__file__).with_name("hepta_ci_exec.py").resolve()


class ConsoleBackpressureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        for args in (
            ["init", "-q"],
            ["config", "user.name", "console fixture"],
            ["config", "user.email", "console@example.invalid"],
        ):
            subprocess.run(["git", "-C", str(self.repo), *args], check=True)
        (self.repo / "input").write_text("owned input\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "input"], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-qm", "fixture"], check=True
        )
        self.sha = subprocess.check_output(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True
        ).strip()

    def execute_with_unread_console(self, command):
        receipt = self.root / "receipt.json"
        process = subprocess.Popen(
            [
                sys.executable,
                str(RUNNER),
                "--output",
                str(receipt),
                "--timeout-seconds",
                "0.3",
                "--",
                sys.executable,
                "-c",
                command,
            ],
            cwd=self.repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={
                **os.environ,
                "SOURCE_SHA": self.sha,
                "TESTED_SHA": self.sha,
                "BASE_SHA": self.sha,
                "HEPTA_CI_LANE": "source-head",
            },
        )
        blocked = False
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            blocked = True
        finally:
            # Drain only after the observation so even the old failing owner
            # can run its own group cleanup and reap its actual direct child.
            stdout, stderr = process.communicate(timeout=5)
        record = json.loads(receipt.read_text())
        raw = (self.root / record["log_file"]).read_bytes()
        self.assertEqual(record["log_bytes"], len(raw))
        self.assertEqual(record["log_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(record["before"], record["after"])
        self.assertFalse(blocked, "unread console suspended the command owner")
        self.assertEqual(stderr, b"")
        return process.returncode, record, raw, stdout

    def test_unread_console_does_not_suspend_actual_timeout(self):
        code, record, raw, _ = self.execute_with_unread_console(
            "import sys,time; sys.stdout.write('x'*262144); "
            "sys.stdout.flush(); time.sleep(60)"
        )
        self.assertEqual(code, 124)
        self.assertEqual(record["status"], "failed")
        self.assertTrue(record["timed_out"])
        self.assertNotEqual(record["command_exit_code"], 0)
        self.assertEqual(raw, b"x" * 262144)

    def test_unread_console_preserves_complete_normal_output(self):
        code, record, raw, _ = self.execute_with_unread_console(
            "import sys; sys.stdout.write('x'*262144)"
        )
        self.assertEqual(code, 0)
        self.assertEqual(record["status"], "passed")
        self.assertFalse(record["timed_out"])
        self.assertEqual(raw, b"x" * 262144)

    def test_large_final_receipt_cannot_block_process_completion(self):
        code, record, raw, _ = self.execute_with_unread_console(
            "#" + "a" * 90000 + "\nprint('finished')"
        )
        self.assertEqual(code, 0)
        self.assertEqual(record["status"], "passed")
        self.assertFalse(record["timed_out"])
        self.assertEqual(raw, b"finished\n")


if __name__ == "__main__":
    unittest.main()
