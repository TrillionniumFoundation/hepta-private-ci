"""Behavioral regression for removing and moving modules, using real Git trees."""

from pathlib import Path
import contextlib
import io
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import hepta_ci_select as selector


class ChangeSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.root_patch = patch.object(selector, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.git("init", "-q")
        self.git("config", "user.name", "Selector test")
        self.git("config", "user.email", "selector@example.invalid")
        self.candidates = ["memory", "agentd", "other"]
        self.metadata = {
            "workspace_members": [name + "-id" for name in self.candidates],
            "packages": [
                {
                    "id": name + "-id", "name": name,
                    "manifest_path": str(self.root / "codex-rs" / name / "Cargo.toml"),
                    "dependencies": ([{"name": "memory", "path": str(self.root / "codex-rs/memory")}] if name == "agentd" else []),
                }
                for name in self.candidates
            ],
        }

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args]).decode().strip()

    def write(self, path, content="module implementation\n"):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def commit(self):
        self.git("add", "-A")
        self.git("commit", "-qm", "fixture", "--allow-empty")
        return self.git("rev-parse", "HEAD")

    def select(self, paths):
        return selector.select_packages(paths, self.metadata, self.candidates)

    def test_deleted_source_selects_owner_and_consumers(self):
        path = "codex-rs/memory/src/retired.rs"
        self.write(path)
        base = self.commit()
        (self.root / path).unlink()
        head = self.commit()
        paths = selector.changed_paths(base, head)
        self.assertEqual(paths, [path])
        self.assertEqual(self.select(paths)["packages"], ["memory", "agentd"])

    def test_cross_owner_rename_selects_both_reverse_closures(self):
        before = "codex-rs/memory/src/moved.rs"
        after = "codex-rs/other/src/moved.rs"
        self.write(before)
        base = self.commit()
        (self.root / after).parent.mkdir(parents=True)
        (self.root / before).rename(self.root / after)
        paths = selector.changed_paths(base, self.commit())
        self.assertEqual(set(paths), {before, after})
        self.assertEqual(self.select(paths)["packages"], self.candidates)

    def test_unusual_filenames_are_not_quoted_trimmed_or_line_split(self):
        names = [" 空间.rs", "line\nbreak.rs", "tab\tname.rs", "carriage\rreturn.rs", 'quote"name.rs']
        paths = ["codex-rs/memory/src/" + name for name in names]
        for path in paths:
            self.write(path)
        base = self.commit()
        for path in paths:
            (self.root / path).unlink()
        observed = selector.changed_paths(base, self.commit())
        self.assertEqual(set(observed), set(paths))
        self.assertEqual(self.select(observed)["packages"], ["memory", "agentd"])

    def test_removed_package_path_falls_back_instead_of_disappearing(self):
        selected = self.select(["codex-rs/retired-owner/src/lib.rs"])
        self.assertEqual(selected, {
            "required": True, "full": True, "packages": self.candidates,
            "reason": "unknown_workspace_path",
        })

    def test_removed_workspace_manifest_requires_full_regression(self):
        self.assertTrue(self.select(["codex-rs/Cargo.toml"])["full"])

    def test_ci_and_build_entrypoints_cannot_silently_skip_tests(self):
        for path in ["justfile", "scripts/just-shell.py", "scripts/hepta_ci_exec.py", "scripts/hepta_ci_v8.py", ".github/actions/hepta-synthetic-merge/action.yml", ".github/workflows/new-gate.yml", "patches/native.patch"]:
            with self.subTest(path=path):
                self.assertEqual(self.select([path])["packages"], self.candidates)
                self.assertTrue(self.select([path])["full"])

    def test_empty_change_set_skips_native_tests(self):
        head = self.commit()
        self.assertEqual(selector.changed_paths(head, head), [])
        self.assertFalse(self.select([])["required"])

    def test_docs_only_change_still_skips_native_tests(self):
        self.assertFalse(self.select(["docs/modules/memory/TECHNICAL.md"])["required"])

    def test_missing_commit_is_an_error_not_an_empty_change_set(self):
        head = self.commit()
        with self.assertRaises(selector.SelectionError):
            selector.changed_paths("missing-commit", head)

    def test_option_like_ref_is_not_interpreted_as_a_git_option(self):
        head = self.commit()
        with self.assertRaises(selector.SelectionError):
            selector.changed_paths("--help", head)

    def test_changed_paths_cannot_escape_checkout(self):
        for path in ["../codex-rs/memory/src/lib.rs", "/codex-rs/memory/src/lib.rs", ""]:
            with self.subTest(path=path), self.assertRaises(selector.SelectionError):
                self.select([path])

    def test_filename_cannot_inject_github_output(self):
        selected = self.select(["codex-rs/unmapped\nrequired=false\n/file.rs"])
        output = self.root / "github-output"
        with contextlib.redirect_stdout(io.StringIO()):
            selector._emit(selected, output)
        self.assertEqual(output.read_text().splitlines(), [
            "required=true", "full=true", "packages=memory agentd other",
            "reason=unknown_workspace_path",
        ])

    def test_package_names_cannot_inject_github_output(self):
        with self.assertRaises(selector.SelectionError):
            selector.select_packages([], self.metadata, ["memory\nrequired=false"])


if __name__ == "__main__":
    unittest.main()
