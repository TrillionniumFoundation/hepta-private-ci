import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.hepta_ci_scope import GROUPS, changed_paths, select


class ScopeTests(unittest.TestCase):
    def test_readme_and_ordinary_prose_do_not_prepare_native_dependencies(self):
        self.assertFalse(select(["README.md", "docs/modules/inference.control/TECHNICAL.md"])["native"])

    def test_inference_local_change_does_not_run_browser_learning_or_objective(self):
        scope = select(["codex-rs/hepta-infer-core/src/durable_control.rs"])
        self.assertTrue(scope["inference"])
        for group in GROUPS - {"inference"}:
            self.assertFalse(scope[group])

    def test_shared_types_and_agentd_keep_cross_domain_coverage(self):
        for path in ["codex-rs/hepta-types/src/lib.rs", "codex-rs/hepta-agentd/src/state.rs", "codex-rs/Cargo.lock"]:
            with self.subTest(path=path):
                self.assertTrue(all(select([path])[key] for key in GROUPS))

    def test_registry_is_not_prose(self):
        scope = select(["docs/modules/MODULES.json"])
        self.assertTrue(scope["derived"])
        self.assertTrue(all(scope[key] for key in GROUPS))

    def test_unknown_or_executable_document_selects_full(self):
        for path in ["docs/check.rs", "scripts/new-verifier.py", "codex-rs/hepta-new/src/lib.rs", ".github/workflows/new.yml"]:
            with self.subTest(path=path):
                self.assertTrue(all(select([path])[key] for key in GROUPS))

    def test_code_owned_markdown_is_not_assumed_pure_prose(self):
        self.assertTrue(select(["codex-rs/core/prompt.md"])["native"])

    def test_rename_keeps_source_and_destination_groups(self):
        scope = select(["codex-rs/hepta-infer-core/src/old.rs", "codex-rs/hepta-learning-ledger/src/new.rs"])
        self.assertTrue(scope["inference"] and scope["learning"])

    def test_effectful_retirement_keeps_lifecycle_and_effect_tests(self):
        scope = select(["codex-rs/hepta-automation/src/timer_lifecycle.rs"])
        self.assertTrue(scope["effects"] and scope["lifecycle"])

    def test_manual_full_keeps_all_groups_even_with_no_paths(self):
        self.assertTrue(all(select([], force_full=True).values()))

    def test_bad_paths_fail_instead_of_selecting_nothing(self):
        for path in ["", "../README.md", "/README.md", "docs/../foo.md", "docs\\foo.md", "docs/a\0.md"]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                select([path])

    def test_commit_id_validation_precedes_subprocess(self):
        with patch("subprocess.run") as run, self.assertRaises(ValueError):
            changed_paths("--output=/tmp/file", "a" * 40)
        run.assert_not_called()

    def test_git_diff_covers_real_rename_and_deleted_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.check_output(["git", "-C", directory, *args], stderr=subprocess.DEVNULL).decode().strip()
            git("init", "-q")
            git("config", "user.name", "Scope Test")
            git("config", "user.email", "scope@localhost")
            old = root / "codex-rs/hepta-infer-core/src/old.rs"
            old.parent.mkdir(parents=True)
            old.write_text("fn original() {}\n")
            git("add", ".")
            git("commit", "-qm", "base")
            base = git("rev-parse", "HEAD")
            new = root / "docs/new name.md"
            new.parent.mkdir()
            old.rename(new)
            git("add", "-A")
            git("commit", "-qm", "renamed")
            head = git("rev-parse", "HEAD")
            previous = os.getcwd()
            try:
                os.chdir(directory)
                paths = changed_paths(base, head)
            finally:
                os.chdir(previous)
            self.assertIn("codex-rs/hepta-infer-core/src/old.rs", paths)
            self.assertIn("docs/new name.md", paths)
            self.assertTrue(select(paths)["inference"])


if __name__ == "__main__":
    unittest.main()
