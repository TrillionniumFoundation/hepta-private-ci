"""Exercise formatter scope using real Git state and observable tool commands."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "repo_format_tests_target", Path(__file__).with_name("format.py")
)
FMT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = FMT
SPEC.loader.exec_module(FMT)


class FormatterScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        patcher = patch.object(FMT, "REPO_ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.git("init", "-q")
        self.git("config", "user.name", "Scope Test")
        self.git("config", "user.email", "scope@localhost")
        self.write("scripts/first.py", "value = 1\n")
        self.write("scripts/delete.py", "value = 1\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD").strip()

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, text=True)

    def write(self, name, content="value = 2\n"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def test_real_staged_unstaged_new_and_deleted_paths(self):
        self.write("scripts/first.py")
        self.write("scripts/staged.py")
        self.git("add", "scripts/staged.py")
        self.write("scripts/new file.py")
        (self.root / "scripts/delete.py").unlink()
        self.assertEqual(
            FMT.changed_paths(),
            ["scripts/first.py", "scripts/new file.py", "scripts/staged.py"],
        )

    def test_exact_base_includes_committed_work_and_rejects_unknown_base(self):
        self.write("scripts/first.py")
        self.git("commit", "-qam", "change")
        self.assertEqual(FMT.changed_paths(), [])
        self.assertEqual(FMT.changed_paths(self.base), ["scripts/first.py"])
        with self.assertRaises(subprocess.CalledProcessError):
            FMT.changed_paths("missing-base")

    def test_python_only_does_not_construct_rust_bazel_sdk_or_just_commands(self):
        groups = FMT.scoped_formatter_groups(
            ["scripts/first.py", "README.md"], check=False
        )
        self.assertEqual([group.name for group in groups], ["Python scripts"])
        self.assertEqual(groups[0].commands[0].args[-1], "./scripts/first.py")
        self.assertIn("--frozen", groups[0].commands[0].args)
        self.assertNotIn("sdk/python", groups[0].commands[0].args)

    def test_sdk_scopes_both_lint_and_format_to_changed_files(self):
        groups = FMT.scoped_formatter_groups(["sdk/python/src/example.py"], check=True)
        self.assertEqual([group.name for group in groups], ["Python SDK"])
        for command in groups[0].commands:
            self.assertEqual(command.args[-1], "./sdk/python/src/example.py")
        self.assertIn("--diff", groups[0].commands[0].args)
        self.assertIn("--check", groups[0].commands[1].args)

    def test_rust_uses_own_edition_without_recursively_formatting_neighbors(self):
        self.write("codex-rs/Cargo.toml", '[workspace.package]\nedition = "2024"\n')
        self.write(
            "codex-rs/example/Cargo.toml",
            '[package]\nname = "example"\nedition.workspace = true\n',
        )
        groups = FMT.scoped_formatter_groups(
            ["codex-rs/example/src/lib.rs"], check=False
        )
        command = groups[0].commands[0]
        self.assertEqual(command.args[command.args.index("--edition") + 1], "2024")
        self.assertIn(
            "skip_children=true", command.args[command.args.index("--config") + 1]
        )
        self.assertEqual(command.args[-1], "./codex-rs/example/src/lib.rs")

    def test_nested_rust_config_limits_tools_to_existing_owner_sources(self):
        self.write("codex-rs/Cargo.toml", '[workspace.package]\nedition="2024"\n')
        for owner in ("first", "other"):
            self.write(
                f"codex-rs/{owner}/Cargo.toml",
                f'[package]\nname="{owner}"\nedition.workspace=true\n',
            )
            self.write(f"codex-rs/{owner}/src/lib.rs", "pub fn original() {}\n")
        removed = self.write("codex-rs/first/src/removed.rs", "pub fn removed() {}\n")
        self.git("add", ".")
        self.git("commit", "-qm", "Rust owners")
        self.write("codex-rs/first/rustfmt.toml", "max_width=88\n")
        self.write("codex-rs/first/src/new module.rs", "pub fn new() {}\n")
        removed.unlink()
        groups = FMT.scoped_formatter_groups(FMT.changed_paths(), check=True)
        self.assertEqual([group.name for group in groups], ["Rust"])
        self.assertEqual(
            [command.args[-1] for command in groups[0].commands],
            [
                "./codex-rs/first/src/lib.rs",
                "./codex-rs/first/src/new module.rs",
            ],
        )
        self.assertTrue(
            all("--check" in command.args for command in groups[0].commands)
        )

    def test_deleted_rust_configuration_rechecks_its_subtree_and_other_actual_edit(
        self,
    ):
        self.write("codex-rs/Cargo.toml", '[workspace.package]\nedition="2024"\n')
        for owner in ("first", "other"):
            self.write(
                f"codex-rs/{owner}/Cargo.toml",
                f'[package]\nname="{owner}"\nedition.workspace=true\n',
            )
            self.write(f"codex-rs/{owner}/src/lib.rs", "pub fn original() {}\n")
        config = self.write("codex-rs/first/.rustfmt.toml", "max_width=88\n")
        self.git("add", ".")
        self.git("commit", "-qm", "Rust config")
        config.unlink()
        self.write("codex-rs/other/src/lib.rs", "pub fn changed() {}\n")
        groups = FMT.scoped_formatter_groups(FMT.changed_paths(), check=False)
        self.assertEqual(
            [command.args[-1] for command in groups[0].commands],
            [
                "./codex-rs/first/src/lib.rs",
                "./codex-rs/other/src/lib.rs",
            ],
        )

    def test_independent_qualification_rust_edit_keeps_its_own_edition(self):
        self.write(
            "qualification/fixture/Cargo.toml",
            '[package]\nname="fixture"\nedition="2021"\n',
        )
        self.write("qualification/fixture/src/lib.rs", "pub fn entry() {}\n")
        groups = FMT.scoped_formatter_groups(
            ["qualification/fixture/src/lib.rs"], check=True
        )
        self.assertEqual([group.name for group in groups], ["Rust"])
        command = groups[0].commands[0]
        self.assertEqual(command.args[-1], "./qualification/fixture/src/lib.rs")
        self.assertEqual(command.args[command.args.index("--edition") + 1], "2021")

    def test_changed_ruff_configuration_checks_the_owning_python_tree(self):
        groups = FMT.scoped_formatter_groups(["scripts/ruff.toml"], check=True)
        self.assertEqual([group.name for group in groups], ["Python scripts"])
        self.assertEqual(groups[0].commands[0].args[-1], "scripts")

    def test_committed_ruff_config_change_uses_requested_base(self):
        self.write("scripts/pyproject.toml", '[project]\nname="fixture"\n')
        self.git("add", ".")
        self.git("commit", "-qm", "project")
        base = self.git("rev-parse", "HEAD").strip()
        self.write(
            "scripts/pyproject.toml",
            '[project]\nname="fixture"\n[tool.ruff]\nline-length=99\n',
        )
        self.git("commit", "-qam", "format rules")
        groups = FMT.scoped_formatter_groups(
            FMT.changed_paths(base), check=True, base=base
        )
        self.assertEqual([group.name for group in groups], ["Python scripts"])
        self.assertEqual(groups[0].commands[0].args[-1], "scripts")

    def test_dependency_only_pyproject_edit_does_not_reformat_untouched_tree(self):
        self.write("scripts/pyproject.toml", '[project]\nname="fixture"\n')
        self.git("add", ".")
        self.git("commit", "-qm", "project")
        self.write(
            "scripts/pyproject.toml",
            '[project]\nname="fixture"\ndependencies=["example"]\n',
        )
        self.assertEqual(
            FMT.scoped_formatter_groups(FMT.changed_paths(), check=False), ()
        )

    def test_python_310_python_only_scope_requires_no_toml_dependency(self):
        with patch.object(FMT, "tomllib", None):
            groups = FMT.scoped_formatter_groups(["scripts/first.py"], check=False)
            self.assertEqual([group.name for group in groups], ["Python scripts"])

    def test_clean_checkout_does_not_start_any_formatter(self):
        with (
            patch.object(sys, "argv", ["format.py"]),
            patch.object(FMT, "run_formatter_group") as runner,
        ):
            self.assertEqual(FMT.main(), 0)
            runner.assert_not_called()

    def test_all_remains_full_even_in_clean_checkout(self):
        groups = (FMT.FormatterGroup("explicit-all", (FMT.Command(("tool",)),)),)
        with patch.object(sys, "argv", ["format.py", "--all", "--check"]):
            with patch.object(FMT, "formatter_groups", return_value=groups) as full:
                with patch.object(
                    FMT,
                    "run_formatter_group",
                    return_value=FMT.FormatterResult("explicit-all", "", 0),
                ) as runner:
                    self.assertEqual(FMT.main(), 0)
                    full.assert_called_once_with(check=True)
                    runner.assert_called_once_with(groups[0])

    @unittest.skipIf(os.name == "nt", "POSIX literal paths")
    def test_newline_filename_is_not_split_and_symlink_escape_is_rejected(self):
        name = "scripts/line\nbreak.py"
        self.write(name)
        self.assertEqual(FMT.changed_paths(), [name])
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "outside.py"
            target.write_text("x = 1")
            (self.root / "scripts/link.py").symlink_to(target)
            with self.assertRaisesRegex(ValueError, "escapes"):
                FMT.changed_paths()

    def test_deleted_configuration_rechecks_owner_without_deleted_source(self):
        self.write("scripts/ruff.toml", "line-length = 99\n")
        self.git("add", ".")
        self.git("commit", "-qm", "format rules")
        (self.root / "scripts/ruff.toml").unlink()
        (self.root / "scripts/delete.py").unlink()
        paths = FMT.changed_paths()
        self.assertEqual(paths, ["scripts/ruff.toml"])
        groups = FMT.scoped_formatter_groups(paths, check=True)
        self.assertEqual([group.name for group in groups], ["Python scripts"])
        self.assertEqual(groups[0].commands[0].args[-1], "scripts")

    def test_nested_configuration_selects_subtree_and_other_actual_edits(self):
        self.write("scripts/nested/ruff.toml", "line-length = 99\n")
        self.write("scripts/nested/deeper/ruff.toml", "line-length = 88\n")
        self.write("scripts/first.py", "x=2\n")
        self.write("scripts/nested/child.py", "x=2\n")
        groups = FMT.scoped_formatter_groups(FMT.changed_paths(), check=False)
        self.assertEqual([group.name for group in groups], ["Python scripts"])
        self.assertEqual(
            groups[0].commands[0].args[-2:], ("scripts/nested", "./scripts/first.py")
        )

    def test_python_version_changes_affect_inferred_ruff_target(self):
        self.write("scripts/pyproject.toml", '[project]\nrequires-python=">=3.10"\n')
        self.git("add", ".")
        self.git("commit", "-qm", "Python version")
        self.write("scripts/pyproject.toml", '[project]\nrequires-python=">=3.12"\n')
        groups = FMT.scoped_formatter_groups(FMT.changed_paths(), check=True)
        self.assertEqual(groups[0].commands[0].args[-1], "scripts")

    def test_rust_edition_comes_from_nearest_or_explicit_workspace(self):
        self.write("codex-rs/Cargo.toml", '[workspace.package]\nedition="2024"\n')
        self.write(
            "codex-rs/nested/Cargo.toml", '[workspace.package]\nedition="2021"\n'
        )
        self.write(
            "codex-rs/nested/member/Cargo.toml",
            '[package]\nname="member"\nedition.workspace=true\n',
        )
        command = FMT.rust_file_command("codex-rs/nested/member/src/lib.rs", check=True)
        self.assertEqual(command.args[command.args.index("--edition") + 1], "2021")
        self.write(
            "codex-rs/explicit/Cargo.toml",
            '[package]\nname="explicit"\nworkspace="../nested"\nedition.workspace=true\n',
        )
        command = FMT.rust_file_command("codex-rs/explicit/src/lib.rs", check=False)
        self.assertEqual(command.args[command.args.index("--edition") + 1], "2021")

    def test_rust_does_not_guess_an_inherited_edition_without_its_owner(self):
        self.write("codex-rs/Cargo.toml", "[workspace]\nmembers=[]\n")
        self.write(
            "codex-rs/member/Cargo.toml",
            '[package]\nname="member"\nedition.workspace=true\n',
        )
        with self.assertRaisesRegex(ValueError, "workspace edition missing"):
            FMT.rust_file_command("codex-rs/member/src/lib.rs", check=True)


if __name__ == "__main__":
    unittest.main()
