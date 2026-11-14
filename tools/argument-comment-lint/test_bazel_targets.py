#!/usr/bin/env python3
"""Run the discovery shell against representative native and cross query output."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class BazelTargetsTest(unittest.TestCase):
    def setUp(self) -> None:
        if os.name == "nt":
            # PATH may expose WSL's bash.exe before Git for Windows.
            candidates = [
                Path(os.environ[name]) / suffix / "bin/bash.exe"
                for name, suffix in (
                    ("ProgramFiles", "Git"),
                    ("ProgramFiles(x86)", "Git"),
                    ("LOCALAPPDATA", "Programs/Git"),
                )
                if os.environ.get(name)
            ]
            git = shutil.which("git")
            if git is not None:
                candidates.insert(0, Path(git).parent.parent / "bin/bash.exe")
            self.bash = next((str(path) for path in candidates if path.is_file()), None)
        else:
            self.bash = shutil.which("bash")
        if self.bash is None:
            raise RuntimeError("these shell fixtures require Git Bash on Windows, or Bash on Unix")
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.script = self.root / "tools/argument-comment-lint/list-bazel-targets.sh"
        self.script.parent.mkdir(parents=True)
        shutil.copyfile(Path(__file__).with_name("list-bazel-targets.sh"), self.script)
        query = self.root / ".github/scripts/run-bazel-query-ci.sh"
        query.parent.mkdir(parents=True)
        query.write_text(
            '#!/usr/bin/env bash\nset -euo pipefail\n'
            'case "$*" in\n'
            '  *\'"manual"\'*) printf "%s" "$FIXTURE_MANUAL_LABELS" ;;\n'
            '  *\'"no-argument-comment-lint"\'*) printf "%s" "$FIXTURE_EXCLUDED_LABELS" ;;\n'
            '  *) exit 23 ;;\nesac\n'
        )
        query.chmod(0o755)

    def discover(self, runner: str, terminator: str, *arguments: str) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env.update({
            "RUNNER_OS": runner,
            "FIXTURE_MANUAL_LABELS": terminator.join([
                "//codex-rs/core:core-unit-tests-bin",
                "//codex-rs/core:core-unit-tests-windows-cross-bin",
                "//codex-rs/core:core-all-test-bin",
                "//codex-rs/core:core-all-test-windows-cross-bin",
                "//codex-rs/utils/string:string-unit-tests-bin",
                "",
            ]),
            "FIXTURE_EXCLUDED_LABELS": "//codex-rs/core:semantic-wrapper" + terminator,
        })
        return subprocess.run(
            [self.bash, self.script.as_posix(), *arguments], cwd=self.root, env=env,
            capture_output=True, text=True, timeout=10,
        )

    def test_native_windows_keeps_native_tests_and_excludes_cross_helpers(self) -> None:
        result = self.discover("Windows", "\r\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [
            "//codex-rs/...",
            "-//codex-rs/core/tests/remote_env_windows:smoke-test",
            "-//codex-rs/core:semantic-wrapper",
            "//codex-rs/core:core-unit-tests-bin",
            "//codex-rs/core:core-all-test-bin",
            "//codex-rs/utils/string:string-unit-tests-bin",
        ])

    def test_explicit_windows_cross_keeps_cross_helpers(self) -> None:
        result = self.discover("Windows", "\r\n", "--windows-cross-compile")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [
            "//codex-rs/...",
            "-//codex-rs/core/tests/remote_env_windows:smoke-test",
            "-//codex-rs/core:semantic-wrapper",
            "//codex-rs/core:core-unit-tests-bin",
            "//codex-rs/core:core-unit-tests-windows-cross-bin",
            "//codex-rs/core:core-all-test-windows-cross-bin",
            "//codex-rs/utils/string:string-unit-tests-bin",
        ])

    def test_linux_discovery_preserves_native_test_coverage(self) -> None:
        result = self.discover("Linux", "\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [
            "//codex-rs/...",
            "-//codex-rs/core/tests/remote_env_windows:smoke-test",
            "-//codex-rs/core:semantic-wrapper",
            "//codex-rs/core:core-unit-tests-bin",
            "//codex-rs/core:core-all-test-bin",
            "//codex-rs/utils/string:string-unit-tests-bin",
        ])

    def test_unknown_option_fails_before_query(self) -> None:
        result = self.discover("Windows", "\r\n", "--windows-cross-compille")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
