"""Preserve real lock-check command outcomes; a probe is not a Bazel build."""

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

import test_run_bazel_ci as original


ROOT = Path(__file__).resolve().parents[2]
PROBE = """import json
import os
import sys
from pathlib import Path

with Path(os.environ['BAZEL_PROBE_LOG']).open('a', encoding='utf-8') as output:
    output.write(json.dumps(sys.argv[1:]) + '\\n')
print(os.environ['LOCK_PROBE_STDOUT'])
print(os.environ['LOCK_PROBE_STDERR'], file=sys.stderr)
sys.exit(int(os.environ['LOCK_PROBE_EXIT']))
"""


class BazelLockCheckOutcomeTests(unittest.TestCase):
    setUp = original.RunBazelCiIntegrationTest.setUp

    def observe(self, code, diagnostic):
        (self.root / "probe.py").write_text(PROBE, encoding="utf-8")
        self.env.update(
            LOCK_PROBE_STDOUT="original dependency observation",
            LOCK_PROBE_STDERR=diagnostic,
            LOCK_PROBE_EXIT=str(code),
        )
        if os.name == "nt":
            # Exercise the actual Windows recipe with its native shell, not a
            # Python reimplementation. The private PATH selects only the probe.
            recipe = (ROOT / "justfile").read_text(encoding="utf-8")
            start = recipe.index("[windows]\nbazel-lock-check:\n")
            command = recipe[start:].splitlines()[2].strip()
            powershell = shutil.which("pwsh") or shutil.which("powershell")
            self.assertIsNotNone(powershell, "PowerShell is required on Windows")
            argv = [powershell, "-NoProfile", "-NonInteractive", "-Command", command]
            self.env["PATH"] = str(self.root) + os.pathsep + self.env["PATH"]
        else:
            argv = [self.bash, str(ROOT / "scripts/check-module-bazel-lock.sh")]
        result = subprocess.run(
            argv,
            cwd=self.root,
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        self.assertTrue(self.log.exists(), result.stdout + result.stderr)
        calls = [
            json.loads(line)
            for line in self.log.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(len(calls), 1, "a failed check must not be retried")
        args = calls[0]
        index = args.index("mod")
        self.assertEqual(args[index : index + 2], ["mod", "deps"])
        self.assertIn("--lockfile_mode=error", args)
        self.assertNotIn("--lockfile_mode=update", args)
        self.assertNotIn("--lockfile_mode=off", args)
        self.assertIn(self.env["LOCK_PROBE_STDOUT"], result.stdout)
        self.assertIn(diagnostic, result.stderr)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        if code:
            self.assertIn("could not verify MODULE.bazel.lock", result.stderr)
            self.assertNotIn("MODULE.bazel.lock is out of date.", result.stderr)
            self.assertNotIn("MODULE.bazel.lock is out of date.", result.stdout)
        else:
            self.assertNotIn("could not verify", result.stdout + result.stderr)
        self.assertFalse((self.root / "MODULE.bazel.lock").exists())

    def test_success_keeps_original_observation(self):
        self.observe(0, "dependency evaluation completed")

    def test_download_failure_does_not_assert_lockfile_drift(self):
        self.observe(37, "ERROR: dependency download: GET returned 500")

    def test_lockfile_error_remains_a_failure_with_original_diagnostic(self):
        self.observe(48, "ERROR: lockfile is no longer up-to-date")

    def test_interruption_retains_original_status(self):
        self.observe(130, "dependency evaluation interrupted")

    def test_unclassified_error_is_not_promoted_or_relabelled(self):
        self.observe(2, "ERROR: invalid Bazel configuration")

    def test_ordinary_one_failure_remains_nonzero(self):
        self.observe(1, "ERROR: dependency checksum mismatch")


if __name__ == "__main__":
    unittest.main()
