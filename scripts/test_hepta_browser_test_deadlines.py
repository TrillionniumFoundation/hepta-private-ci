"""Execute the Browser CI test command against successful and stuck fixtures.

Shorter probe deadlines keep the negative controls fast. The actual checked-in
runner command is retained, including its independent process watchdog.
"""

from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BrowserTestDeadlineTests(unittest.TestCase):
    def run_fixture(self, body):
        workflow = (ROOT / ".github/workflows/blocking-ci.yml").read_text()
        command = re.search(
            r"name: Run Browser state, journal, IPC and Agentd boundary regressions\n"
            r"\s+run: ([^\n]+)",
            workflow,
        ).group(1)
        arguments = shlex.split(command)
        # Exercise the installed CI command, shortening only its budgets.
        arguments[arguments.index("300s")] = "1s"
        arguments[arguments.index("--kill-after=10s")] = "--kill-after=1s"
        arguments[arguments.index("--test-timeout=30000")] = "--test-timeout=30"
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "deadline.test.cjs"
            fixture.write_text("const test = require('node:test');\n" + body)
            arguments[arguments.index("apps/hepta-browser/test/*.test.js")] = str(
                fixture
            )
            return subprocess.run(
                arguments, capture_output=True, text=True, timeout=5, check=False
            )

    def test_successful_test_remains_successful(self):
        result = self.run_fixture("test('successful control', () => {});\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_pending_async_test_fails_with_named_deadline(self):
        result = self.run_fixture(
            "test('pending async control', async (t) => {\n"
            "  const alive = setInterval(() => {}, 10);\n"
            "  t.after(() => clearInterval(alive));\n"
            "  await new Promise(() => {});\n"
            "});\n"
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("pending async control", result.stdout)
        self.assertIn("test timed out after 30ms", result.stdout)

    def test_blocked_event_loop_fails_at_independent_process_watchdog(self):
        result = self.run_fixture(
            "test('blocked sync control', () => {\n"
            "  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0);\n"
            "});\n"
        )
        self.assertEqual(result.returncode, 124, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
