import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from v8_canary_changes import changed_files
from v8_canary_changes import canary_required
from v8_canary_changes import merge_base
from v8_canary_changes import resolved_v8_version
from v8_canary_changes import windows_source_required


class V8CanaryChangesTest(unittest.TestCase):
    def test_resolved_v8_version(self) -> None:
        cargo_lock = b"""\
[[package]]
name = "other"
version = "1.0.0"

[[package]]
name = "v8"
version = "149.2.0"
"""

        self.assertEqual(resolved_v8_version(cargo_lock), "149.2.0")

    def test_unrelated_cargo_manifest_change_does_not_require_source_build(
        self,
    ) -> None:
        self.assertFalse(
            windows_source_required(
                {"codex-rs/Cargo.toml"},
                "149.2.0",
                "149.2.0",
            )
        )

    def test_v8_version_change_requires_source_build(self) -> None:
        self.assertTrue(windows_source_required(set(), "149.2.0", "150.0.0"))

    def test_module_helper_change_requires_source_build(self) -> None:
        self.assertTrue(
            windows_source_required(
                {".github/scripts/rusty_v8_module_bazel.py"},
                "149.2.0",
                "149.2.0",
            )
        )

    def test_shared_ci_setup_changes_require_canary_and_source_build(self) -> None:
        for path in (
            ".github/actions/setup-ci/action.yml",
            ".github/scripts/setup-dev-drive.ps1",
        ):
            with self.subTest(path=path):
                changed_files = {path}
                self.assertTrue(canary_required(changed_files, "149.2.0", "149.2.0"))
                self.assertTrue(
                    windows_source_required(changed_files, "149.2.0", "149.2.0")
                )

    def test_manual_dispatch_requires_source_build(self) -> None:
        self.assertTrue(
            windows_source_required(
                set(),
                "149.2.0",
                "149.2.0",
                force=True,
            )
        )

    def test_changed_files_excludes_changes_made_only_on_base_branch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.run_git(root, "init", "--initial-branch=main")
            self.run_git(root, "config", "user.name", "Test User")
            self.run_git(root, "config", "user.email", "test@example.com")

            self.write_and_commit(root, "initial", "initial.txt")
            common = self.run_git(root, "rev-parse", "HEAD")
            self.run_git(root, "switch", "-c", "feature")
            self.run_git(root, "switch", "main")
            self.write_and_commit(root, "base-only", "base-only.txt")
            base = self.run_git(root, "rev-parse", "HEAD")

            self.run_git(root, "switch", "feature")
            self.write_and_commit(root, "feature-only", "feature-only.txt")
            head = self.run_git(root, "rev-parse", "HEAD")

            self.assertEqual(
                changed_files(base, head, root=root),
                {"feature-only.txt"},
            )
            self.assertEqual(merge_base(base, head, root=root), common)

    def test_shallow_pr_history_recovers_three_dot_merge_base(self) -> None:
        # Reproduce the original CI failure: each exact SHA object exists,
        # but a depth-one fetch has no ancestor for three-dot comparison.
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            source = workspace / "source"
            source.mkdir()
            origin = workspace / "origin.git"
            shallow = workspace / "shallow"

            self.run_git(workspace, "init", "--bare", "--initial-branch=main", str(origin))
            self.run_git(source, "init", "--initial-branch=main")
            self.run_git(source, "config", "user.name", "Test User")
            self.run_git(source, "config", "user.email", "test@example.com")
            self.write_and_commit(source, "common", "common.txt")
            common = self.run_git(source, "rev-parse", "HEAD")
            self.run_git(source, "branch", "feature")
            self.write_and_commit(source, "base-only", "base-only.txt")
            base = self.run_git(source, "rev-parse", "HEAD")
            self.run_git(source, "switch", "feature")
            self.write_and_commit(source, "feature-only", "feature-only.txt")
            head = self.run_git(source, "rev-parse", "HEAD")
            self.run_git(source, "remote", "add", "origin", origin.as_uri())
            self.run_git(source, "push", "origin", "main", "feature")

            subprocess.check_call(
                ["git", "clone", "--quiet", "--depth=1", "--branch=feature", origin.as_uri(), str(shallow)],
                cwd=workspace,
            )
            self.run_git(shallow, "fetch", "--no-tags", "--depth=1", "origin", base, head)
            self.assertEqual(self.run_git(shallow, "rev-parse", "--is-shallow-repository"), "true")
            with self.assertRaises(subprocess.CalledProcessError):
                merge_base(base, head, root=shallow)

            script = Path(__file__).resolve().parents[2] / "scripts" / "hepta_ci_history.py"
            environment = os.environ.copy()
            environment.pop("GH_TOKEN", None)
            subprocess.check_call(
                [sys.executable, str(script), "--commit", base, "--commit", head, "--full-history"],
                cwd=shallow,
                env=environment,
            )
            self.assertEqual(self.run_git(shallow, "rev-parse", "--is-shallow-repository"), "false")
            self.assertEqual(merge_base(base, head, root=shallow), common)
            self.assertEqual(changed_files(base, head, root=shallow), {"feature-only.txt"})

    def write_and_commit(self, root: Path, contents: str, path: str) -> None:
        (root / path).write_text(contents)
        self.run_git(root, "add", path)
        self.run_git(root, "commit", "-m", contents)

    def run_git(self, root: Path, *args: str) -> str:
        return subprocess.check_output(
            ["git", *args],
            cwd=root,
            stderr=subprocess.PIPE,
            text=True,
        ).strip()


if __name__ == "__main__":
    unittest.main()
