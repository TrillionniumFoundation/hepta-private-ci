"""Run the PRED workflow shell and real identity guard in disposable Git trees.

The stand-in just executable exercises dispatch and receipt handling. Its
summaries are fixtures, not evidence that any native Rust test ran.
"""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/hepta-pred-native-feedback.yml"
RUNNER = ROOT / "scripts/hepta_ci_exec.py"


@unittest.skipUnless(os.name == "posix", "the native workflow uses a POSIX host")
class NativeWorkflowIdentityTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="pred-native-workflow-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.repo = self.root / "repo"
        (self.repo / "scripts").mkdir(parents=True)
        shutil.copyfile(RUNNER, self.repo / "scripts/hepta_ci_exec.py")
        self.git("init", "-q")
        self.git("config", "user.name", "workflow-test")
        self.git("config", "user.email", "workflow-test@example.invalid")
        self.git("add", ".")
        self.git("commit", "-qm", "source")
        self.source = self.git("rev-parse", "HEAD")
        self.calls = self.root / "calls.json"
        binaries = self.root / "bin"
        binaries.mkdir()
        command = binaries / "just"
        command.write_text(
            f"#!{sys.executable}\n"
            "import json, os, pathlib, sys\n"
            "pathlib.Path(os.environ['CALLS']).write_text(json.dumps({\n"
            "  'command': ['just', *sys.argv[1:]], 'cwd': os.getcwd(),\n"
            "  'source': os.environ['SOURCE_SHA'],\n"
            "  'tested': os.environ['TESTED_SHA'],\n"
            "  'lane': os.environ['HEPTA_CI_LANE']}))\n"
            "count = int(os.environ.get('STANDIN_PASSES', '8'))\n"
            "print(f'Summary [0.001s] {count} tests run: {count} passed, 0 skipped')\n"
            "raise SystemExit(int(os.environ.get('STANDIN_EXIT', '0')))\n"
        )
        command.chmod(0o755)
        self.env = {
            key: value
            for key, value in os.environ.items()
            if key not in ("SOURCE_SHA", "TESTED_SHA", "BASE_SHA", "HEPTA_CI_LANE")
        }
        self.env.update(
            PATH=str(binaries) + os.pathsep + os.environ["PATH"],
            CALLS=str(self.calls),
            GITHUB_SHA=self.source,
            PYTHONDONTWRITEBYTECODE="1",
        )
        workflow = WORKFLOW.read_text()
        job = workflow.split("\n  native:\n", 1)[1]
        environment = job.split("    env:\n", 1)[1].split("    steps:\n", 1)[0]
        for line in environment.splitlines():
            match = re.fullmatch(r"      ([A-Z_][A-Z_0-9]*): (.+)", line)
            self.assertIsNotNone(match, f"unsupported job environment: {line!r}")
            value = match[2].replace("${{ github.sha }}", self.source)
            self.assertNotIn("${{", value, "unresolved workflow expression")
            self.env[match[1]] = value
        block = job.split(
            "      - name: Test native capture and original authorized effect host\n", 1
        )[1].split("        run: |\n", 1)[1]
        lines = []
        for line in block.splitlines():
            if line and not line.startswith("          "):
                break
            lines.append(line[10:])
        self.script = "\n".join(lines)
        self.attempt = 0

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.repo), *args], text=True, stderr=subprocess.PIPE
        ).strip()

    def execute(self, **environment):
        self.attempt += 1
        runner_temp = self.root / f"attempt-{self.attempt}"
        self.result_path = runner_temp / "pred-native-feedback/tests.json"
        self.calls.unlink(missing_ok=True)
        return subprocess.run(
            ["bash", "-c", self.script],
            cwd=self.repo,
            env={**self.env, "RUNNER_TEMP": str(runner_temp), **environment},
            text=True,
            capture_output=True,
            timeout=10,
        )

    def receipt(self):
        return json.loads(self.result_path.read_text())

    def test_yaml_identity_reaches_real_guard_and_preserves_native_selection(self):
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = self.receipt()
        expected_command = [
            "just",
            "test",
            "--locked",
            "-p",
            "codex-hepta-agentd",
            "--lib",
            "-E",
            "test(automation_predispatch_export) | test(automation_effect_host::tests)",
            "--no-tests",
            "fail",
            "--retries",
            "0",
        ]
        self.assertEqual(
            json.loads(self.calls.read_text()),
            {
                "command": expected_command,
                "cwd": str(self.repo),
                "source": self.source,
                "tested": self.source,
                "lane": "source-head",
            },
        )
        self.assertEqual(receipt["command"], expected_command)
        self.assertEqual(receipt["source_sha"], self.source)
        self.assertEqual(receipt["tested_sha"], self.source)
        self.assertEqual(receipt["lane"], "source-head")
        self.assertEqual(receipt["before"], receipt["after"])
        self.assertEqual(receipt["status"], "passed")

    def test_missing_identity_never_starts_native_command(self):
        for name in ("SOURCE_SHA", "TESTED_SHA", "HEPTA_CI_LANE"):
            with self.subTest(name=name):
                result = self.execute(**{name: ""})
                self.assertEqual(result.returncode, 2)
                self.assertEqual(self.receipt()["status"], "rejected")
                self.assertIsNone(self.receipt()["command_exit_code"])
                self.assertFalse(self.calls.exists())

    def test_mismatched_source_or_checkout_never_starts_native_command(self):
        for identity in (
            {"SOURCE_SHA": "f" * 40},
            {"TESTED_SHA": "f" * 40},
        ):
            with self.subTest(identity=identity):
                result = self.execute(**identity)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(self.receipt()["status"], "rejected")
                self.assertIsNone(self.receipt()["command_exit_code"])
                self.assertFalse(self.calls.exists())

    def test_native_command_failure_remains_failed(self):
        result = self.execute(STANDIN_EXIT="23")
        self.assertEqual(result.returncode, 23)
        self.assertEqual(self.receipt()["command_exit_code"], 23)
        self.assertEqual(self.receipt()["status"], "failed")

    def test_zero_or_incomplete_native_test_count_cannot_pass(self):
        for count in (0, 7):
            with self.subTest(count=count):
                result = self.execute(STANDIN_PASSES=str(count))
                self.assertEqual(result.returncode, 1)
                receipt = self.receipt()
                self.assertEqual(receipt["command_exit_code"], 0)
                self.assertEqual(receipt["observed_passed_tests"], count)
                self.assertEqual(receipt["status"], "failed")


if __name__ == "__main__":
    unittest.main()
