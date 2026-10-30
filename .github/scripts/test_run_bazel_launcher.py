#!/usr/bin/env python3
"""Exercise the Unix test launcher with a real child and temporary root aliases."""

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


TEMPLATE = Path(__file__).resolve().parents[2] / "workspace_root_test_launcher.sh.tpl"


@unittest.skipIf(os.name == "nt", "native Windows tests use the batch launcher")
class WorkspaceRootLauncherTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory(prefix="launcher test ")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.physical = self.root / "physical temporary root"
        self.physical.mkdir()
        self.alias = self.root / "temporary alias"
        self.alias.symlink_to(self.physical, target_is_directory=True)
        self.result = self.root / "child.json"
        runfiles = self.root / "runfiles"
        marker = runfiles / "codex-rs/utils/cargo-bin/repo_root.marker"
        marker.parent.mkdir(parents=True)
        marker.write_text("", encoding="utf-8")
        child = runfiles / "child"
        child.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "Path(os.environ['LAUNCHER_RESULT']).write_text("
            "json.dumps({'tmpdir': os.environ.get('TMPDIR'), 'args': sys.argv[1:]}))\n",
            encoding="utf-8",
        )
        child.chmod(0o755)
        self.launcher = self.root / "launcher.sh"
        self.launcher.write_text(
            TEMPLATE.read_text(encoding="utf-8")
            .replace(
                "__WORKSPACE_ROOT_MARKER__", "codex-rs/utils/cargo-bin/repo_root.marker"
            )
            .replace("__TEST_BIN__", "child")
            .replace("__RUNFILE_ENV_EXPORTS__", "")
            .replace("__WORKSPACE_ROOT_SETUP__", ""),
            encoding="utf-8",
        )
        self.env = {
            key: value
            for key, value in os.environ.items()
            if key not in {"TMPDIR", "TEST_TMPDIR"}
            and not key.startswith(
                ("TEST_", "RULES_RUST_", "RUNFILES_", "CODEX_BAZEL_")
            )
        }
        self.env.update(RUNFILES_DIR=str(runfiles), LAUNCHER_RESULT=str(self.result))
        self.bash = shutil.which("bash")
        self.assertIsNotNone(self.bash)

    def run_launcher(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self.bash, str(self.launcher), "an argument", "--exact"],
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )

    def test_child_receives_canonical_tmpdir_and_original_arguments(self) -> None:
        self.env["TMPDIR"] = str(self.alias)
        result = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            json.loads(self.result.read_text(encoding="utf-8")),
            {"tmpdir": str(self.physical), "args": ["an argument", "--exact"]},
        )
        self.assertTrue(self.alias.is_symlink())
        self.assertTrue(self.physical.is_dir())

    def test_missing_tmpdir_uses_private_test_tmpdir(self) -> None:
        self.env["TEST_TMPDIR"] = str(self.alias)
        result = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            json.loads(self.result.read_text(encoding="utf-8"))["tmpdir"],
            str(self.physical),
        )

    def test_explicit_tmpdir_takes_precedence(self) -> None:
        other = self.root / "other temporary root"
        other.mkdir()
        self.env.update(TMPDIR=str(self.alias), TEST_TMPDIR=str(other))
        result = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            json.loads(self.result.read_text(encoding="utf-8"))["tmpdir"],
            str(self.physical),
        )

    def test_unavailable_explicit_root_fails_before_child(self) -> None:
        self.env.update(
            TMPDIR=str(self.root / "missing"), TEST_TMPDIR=str(self.physical)
        )
        result = self.run_launcher()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.result.exists())

    def test_missing_private_roots_fails_before_child(self) -> None:
        result = self.run_launcher()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.result.exists())


if __name__ == "__main__":
    unittest.main()
