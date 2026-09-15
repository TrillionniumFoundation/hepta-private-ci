"""Real child-process diagnostics stay bounded and do not change test outcomes."""

import contextlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest

import hepta_ci_exec as runner


class CommandOutputTests(unittest.TestCase):
    def execute(self, code):
        record = {}
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = runner.execute([sys.executable, "-c", code], record)
        return status, record, output.getvalue()

    def test_streams_stdout_and_stderr_and_preserves_failure(self):
        status, record, output = self.execute(
            "import os; os.write(1, b'out\\n'); os.write(2, b'error\\n'); raise SystemExit(17)"
        )
        self.assertEqual(status, 17)
        self.assertEqual(output, "out\nerror\n")
        self.assertEqual(record["output_tail"], output)
        self.assertEqual(record["output_bytes"], len(output))
        self.assertFalse(record["output_truncated"])

    def test_tail_is_bounded_without_truncating_console_output(self):
        size = runner.MAX_OUTPUT_TAIL_BYTES * 4
        status, record, output = self.execute(
            f"import os; os.write(1, b'x' * {size}); os.write(1, b'END')"
        )
        self.assertEqual(status, 0)
        self.assertEqual(len(output), size + 3)
        self.assertEqual(len(record["output_tail"]), runner.MAX_OUTPUT_TAIL_BYTES)
        self.assertTrue(record["output_tail"].endswith("END"))
        self.assertEqual(record["output_bytes"], size + 3)
        self.assertTrue(record["output_truncated"])

    def test_invalid_utf8_does_not_hide_exit_status(self):
        status, record, _ = self.execute("import os; os.write(2, b'\\xff'); raise SystemExit(9)")
        self.assertEqual(status, 9)
        self.assertEqual(record["output_bytes"], 1)
        self.assertEqual(record["output_tail"], "\ufffd")
        json.dumps(record)

    @unittest.skipUnless(os.name == "posix", "POSIX child signals")
    def test_signal_is_not_relabelled_as_success(self):
        status, record, _ = self.execute("import os, signal; os.kill(os.getpid(), signal.SIGTERM)")
        self.assertEqual(status, -signal.SIGTERM)
        self.assertEqual(record["output_bytes"], 0)

    def test_missing_executable_still_raises_and_retains_empty_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            record = {}
            with self.assertRaises(OSError):
                runner.execute([str(Path(directory) / "missing")], record)
            self.assertEqual(record["output_tail"], "")
            self.assertEqual(record["output_bytes"], 0)

    def test_real_record_retains_diagnostics_and_rejects_source_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            def git(*args):
                return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()
            git("init", "-q")
            git("config", "user.name", "test")
            git("config", "user.email", "test@example.invalid")
            (repo / "input").write_text("base")
            git("add", ".")
            git("commit", "-qm", "base")
            sha = git("rev-parse", "HEAD")
            result = root / "result.json"
            run = subprocess.run(
                [sys.executable, str(Path(runner.__file__).resolve()),
                 "--output", str(result), "--", sys.executable, "-c",
                 "from pathlib import Path; print('diagnostic'); Path('input').write_text('changed')"],
                cwd=repo,
                env={**os.environ, "SOURCE_SHA": sha, "TESTED_SHA": sha,
                     "HEPTA_CI_LANE": "source-head"},
                capture_output=True, text=True, timeout=10,
            )
            record = json.loads(result.read_text())
            self.assertEqual(run.returncode, 1, run.stderr)
            self.assertEqual(record["status"], "failed")
            self.assertEqual(record["command_exit_code"], 0)
            self.assertEqual(record["output_tail"], "diagnostic\n")
            self.assertTrue(record["after"]["dirty"])


if __name__ == "__main__":
    unittest.main()
