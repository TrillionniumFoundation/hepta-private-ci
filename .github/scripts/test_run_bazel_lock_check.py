#!/usr/bin/env python3
"""Exercise the real lock-check shell with a recording dependency resolver.

The resolver is a fixture, not a Bazel execution or dependency-security verdict.
"""

import os
import shlex
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/check-module-bazel-lock.sh"


class BazelLockFailureIdentityTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix="lock check source ")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.script = self.root / "scripts/check-module-bazel-lock.sh"
        self.script.parent.mkdir()
        shutil.copyfile(SCRIPT, self.script)
        self.driver = self.root / ".github/scripts/run_bazel_with_buildbuddy.py"
        self.driver.parent.mkdir(parents=True)
        self.calls = self.root / "calls.txt"
        self.arguments = self.root / "arguments.txt"
        self.workdir = self.root / "caller directory"
        self.workdir.mkdir()
        git_bash = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe"
        self.bash = str(git_bash) if os.name == "nt" and git_bash.is_file() else shutil.which("bash")
        self.assertIsNotNone(self.bash, "Bash is required for the real shell wrapper")

    def execute(self, status, diagnostic):
        self.driver.write_text(
            "#!/usr/bin/env bash\n"
            "set -eu\n"
            'root="$(cd "$(dirname "$0")/../.." && pwd)"\n'
            'printf "call\\n" >> "$root/calls.txt"\n'
            'printf "%s\\n" "$@" > "$root/arguments.txt"\n'
            'printf "resolver stdout\\n"\n'
            f"printf '%s\\n' {shlex.quote(diagnostic)} >&2\n"
            f"exit {status}\n",
            encoding="utf-8",
        )
        self.driver.chmod(0o755)
        result = subprocess.run(
            [self.bash, str(self.script)], cwd=self.workdir, capture_output=True,
            text=True, timeout=10,
        )
        self.assertEqual(self.calls.read_text().splitlines(), ["call"])
        self.assertEqual(self.arguments.read_text().splitlines(),
                         ["mod", "deps", "--lockfile_mode=error"])
        self.assertEqual(result.returncode, status)
        self.assertEqual(result.stdout, "resolver stdout\n")
        self.assertEqual(result.stderr, diagnostic + "\n")

    def test_success_retains_exact_resolver_call(self):
        self.execute(0, "resolver completed")

    def test_real_lock_drift_retains_original_diagnostic(self):
        self.execute(1, "ERROR: MODULE.bazel.lock is no longer up-to-date")

    def test_http_500_does_not_become_lock_drift(self):
        self.execute(37, "ERROR: toml2json download: GET returned 500 Internal Server Error")

    def test_integrity_failure_does_not_become_lock_drift(self):
        self.execute(32, "ERROR: repository archive checksum mismatch")

    def test_configuration_failure_does_not_become_lock_drift(self):
        self.execute(2, "ERROR: invalid module extension configuration")

    def test_interrupt_status_is_not_relabelled_or_retried(self):
        self.execute(130, "dependency resolver interrupted")

    def test_success_does_not_depend_on_diagnostic_keywords(self):
        self.execute(0, "INFO: no lockfile update required; cached previous error cleared")

    def test_missing_resolver_remains_execution_failure(self):
        result = subprocess.run(
            [self.bash, str(self.script)], cwd=self.workdir, capture_output=True,
            text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 127)
        self.assertNotIn("out of date", result.stdout + result.stderr)
        self.assertFalse(self.calls.exists())


if __name__ == "__main__":
    unittest.main()
