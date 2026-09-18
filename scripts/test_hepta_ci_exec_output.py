"""Behavioral tests of retained diagnostics and mandatory libtest execution."""

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from hepta_ci_exec import execute_logged

RUNNER = Path(__file__).with_name("hepta_ci_exec.py").resolve()


class CommandOutputTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "user.name", "fixture")
        (self.repo / "input").write_text("owned source\n")
        self.git("add", "input")
        self.git("commit", "-qm", "fixture")
        self.sha = self.git("rev-parse", "HEAD")
        self.receipt = self.root / "result.json"

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.repo), *args], text=True, stderr=subprocess.PIPE
        ).strip()

    def execute(self, code, minimum=1, **environment):
        result = subprocess.run(
            [sys.executable, str(RUNNER), "--output", str(self.receipt),
             "--minimum-tests", str(minimum), "--", sys.executable, "-c", code],
            cwd=self.repo, capture_output=True, text=True, timeout=10,
            env={**os.environ, "SOURCE_SHA": self.sha, "TESTED_SHA": self.sha,
                 "BASE_SHA": self.sha, "HEPTA_CI_LANE": "source-head", **environment},
        )
        return result, json.loads(self.receipt.read_text())

    def test_zero_tests_is_failure_even_with_process_success(self):
        result, record = self.execute(
            "print('test result: ok. 0 passed; 0 failed; 0 ignored; 27 filtered out;')"
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(record["command_exit_code"], 0)
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["observed_passed_tests"], 0)

    def test_ignored_tests_are_not_executed_tests(self):
        result, record = self.execute(
            "print('test result: ok. 0 passed; 0 failed; 3 ignored; 0 filtered out;')"
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(record["status"], "failed")

    def test_compile_only_success_does_not_satisfy_test_gate(self):
        result, record = self.execute("print('Finished test profile successfully')")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(record["observed_passed_tests"], 0)

    def test_empty_other_test_binaries_do_not_invalidate_real_selected_tests(self):
        result, record = self.execute(
            "print('test result: ok. 2 passed; 0 failed; 0 ignored; 0 filtered out;'); "
            "print('test result: ok. 0 passed; 0 failed; 0 ignored; 5 filtered out;')"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(record["observed_passed_tests"], 2)

    def test_real_failure_output_and_digest_are_retained(self):
        result, record = self.execute(
            "import sys; print('compiler diagnostic', file=sys.stderr); raise SystemExit(101)"
        )
        self.assertEqual(result.returncode, 101)
        self.assertEqual(record["status"], "failed")
        log = (self.root / record["log_file"]).read_bytes()
        self.assertIn(b"compiler diagnostic", log)
        self.assertEqual(record["log_sha256"], hashlib.sha256(log).hexdigest())
        self.assertEqual(record["log_bytes"], len(log))

    def test_no_test_requirement_keeps_existing_non_test_commands_compatible(self):
        result, record = self.execute("print('format check')", minimum=0)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(record["status"], "passed")

    def test_wrong_source_never_creates_a_command_log(self):
        result, record = self.execute("print('must not execute')", TESTED_SHA="f" * 40)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(record["status"], "rejected")
        self.assertEqual(list(self.root.glob("result.json*.log")), [])

    def test_successful_source_mutation_is_still_rejected(self):
        result, record = self.execute(
            "from pathlib import Path; Path('input').write_text('changed'); "
            "print('test result: ok. 1 passed; 0 failed; 0 ignored;')"
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(record["status"], "failed")
        self.assertTrue(record["after"]["dirty"])

    def test_bounded_output_kills_command_and_preserves_bounded_prefix(self):
        log = self.root / "bounded.log"
        with contextlib.redirect_stdout(io.StringIO()):
            record = execute_logged(
                [sys.executable, "-c", "import sys; sys.stdout.write('x'*100000)"],
                log, maximum_bytes=100,
            )
        self.assertTrue(record["output_limit_exceeded"])
        self.assertEqual(log.stat().st_size, 100)
        self.assertEqual(record["log_bytes"], 100)

    def test_deleted_receipt_does_not_allow_overwriting_an_earlier_log(self):
        first, record = self.execute("print('first')", minimum=0)
        self.assertEqual(first.returncode, 0)
        old_log = self.root / record["log_file"]
        self.receipt.unlink()
        second, next_record = self.execute("print('second')", minimum=0)
        self.assertEqual(second.returncode, 0)
        self.assertNotEqual(record["log_file"], next_record["log_file"])
        self.assertEqual(old_log.read_bytes(), b"first\n")

    def test_existing_log_cannot_be_reused(self):
        log = self.root / "retained.log"
        log.write_bytes(b"older run")
        with self.assertRaises(FileExistsError):
            execute_logged([sys.executable, "-c", "raise SystemExit(0)"], log)
        self.assertEqual(log.read_bytes(), b"older run")


if __name__ == "__main__":
    unittest.main()
