import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.hepta_ci_scope import GROUPS, changed_paths, select


class ScopeTests(unittest.TestCase):
    def test_readme_and_ordinary_prose_do_not_prepare_native_dependencies(self):
        scope = select(["README.md", "docs/modules/inference.control/TECHNICAL.md"])
        self.assertFalse(scope["native"])
        self.assertFalse(scope["full_repo"])

    def test_inference_local_change_is_module_scoped(self):
        scope = select(["codex-rs/hepta-infer-core/src/durable_control.rs"])
        self.assertTrue(scope["inference"])
        self.assertFalse(scope["full_repo"])
        for group in GROUPS - {"inference"}:
            self.assertFalse(scope[group])

    def test_shared_hepta_types_and_agentd_are_cross_domain_but_not_full_repo(self):
        for path in ["codex-rs/hepta-types/src/lib.rs", "codex-rs/hepta-agentd/src/state.rs"]:
            with self.subTest(path=path):
                scope = select([path])
                self.assertTrue(all(scope[key] for key in GROUPS))
                self.assertFalse(scope["full_repo"])

    def test_workspace_lock_retains_full_repository_fallback(self):
        scope = select(["codex-rs/Cargo.lock"])
        self.assertTrue(scope["full_repo"])
        self.assertTrue(all(scope[key] for key in GROUPS))

    def test_runtime_consumed_module_registry_selects_lifecycle_only(self):
        scope = select(["docs/modules/MODULES.json"])
        self.assertTrue(scope["derived"])
        self.assertTrue(scope["lifecycle"])
        self.assertFalse(scope["full_repo"])
        for group in GROUPS - {"lifecycle"}:
            self.assertFalse(scope[group])

    def test_generated_views_are_derived_without_native_fanout(self):
        for path in ["docs/modules/SOURCE_BINDINGS.json", "docs/modules/MODULE_DOCS.json", "docs/STATUS.md"]:
            with self.subTest(path=path):
                scope = select([path])
                self.assertTrue(scope["derived"])
                self.assertFalse(scope["native"])
                self.assertFalse(scope["full_repo"])

    def test_unknown_hepta_package_stays_architecture_scoped(self):
        scope = select(["codex-rs/hepta-new/src/lib.rs"])
        self.assertTrue(scope["native"])
        self.assertFalse(scope["full_repo"])
        self.assertTrue(all(scope[key] for key in GROUPS))

    def test_unknown_shared_source_or_workflow_selects_full_repo(self):
        for path in ["codex-rs/core/src/new.rs", ".github/workflows/new.yml", "scripts/hepta_ci_scope.py"]:
            with self.subTest(path=path):
                scope = select([path])
                self.assertTrue(scope["full_repo"])
                self.assertTrue(all(scope[key] for key in GROUPS))

    def test_code_owned_markdown_is_not_assumed_pure_prose(self):
        self.assertTrue(select(["codex-rs/core/prompt.md"])["full_repo"])

    def test_rename_keeps_source_and_destination_groups(self):
        scope = select(["codex-rs/hepta-infer-core/src/old.rs", "codex-rs/hepta-learning-ledger/src/new.rs"])
        self.assertTrue(scope["inference"] and scope["learning"])
        self.assertFalse(scope["full_repo"])

    def test_effectful_retirement_keeps_lifecycle_and_effect_tests(self):
        scope = select(["codex-rs/hepta-automation/src/timer_lifecycle.rs"])
        self.assertTrue(scope["effects"] and scope["lifecycle"])
        self.assertFalse(scope["full_repo"])

    def test_manual_full_keeps_every_boolean_true(self):
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
                return subprocess.check_output(
                    ["git", "-C", directory, *args], stderr=subprocess.DEVNULL
                ).decode().strip()

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
