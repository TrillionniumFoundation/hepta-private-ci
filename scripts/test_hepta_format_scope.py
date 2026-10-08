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
        self.root = Path(self.temp.name).resolve()
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

    def test_github_python_and_scripts_share_one_scoped_tool_invocation(self):
        self.write(".github/scripts/check.py")
        self.write("scripts/new.py")
        groups = FMT.scoped_formatter_groups(FMT.changed_paths(), check=True)
        self.assertEqual([group.name for group in groups], ["Python scripts"])
        (command,) = groups[0].commands
        self.assertEqual(
            command.args[-2:], ("./.github/scripts/check.py", "./scripts/new.py")
        )
        self.assertIn("--check", command.args)
        self.assertIn("--frozen", command.args)

    def test_github_ruff_configuration_affects_only_its_own_tree(self):
        groups = FMT.scoped_formatter_groups(
            [".github/ruff.toml", "scripts/first.py"], check=True
        )
        self.assertEqual([group.name for group in groups], ["Python scripts"])
        self.assertEqual(
            groups[0].commands[0].args[-2:], (".github", "./scripts/first.py")
        )

    def test_workflow_only_edit_does_not_start_python_tools(self):
        self.assertEqual(
            FMT.scoped_formatter_groups([".github/workflows/manual.yml"], check=True),
            (),
        )

    def test_explicit_full_python_scope_includes_github_helpers(self):
        group = FMT.python_scripts_formatter_group(check=True)
        self.assertEqual(group.commands[0].args[-2:], ("scripts", ".github"))

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
        self.assertEqual(
            command.args[-1], str(self.root / "codex-rs/example/src/lib.rs")
        )
        self.assertEqual(command.cwd, self.root / "codex-rs/example")

    @unittest.skipIf(FMT.tomllib is None, "requires Python TOML reader")
    def test_rust_batch_reuses_owner_edition_and_next_batch_sees_edits(self):
        workspace = self.write(
            "codex-rs/Cargo.toml", '[workspace.package]\nedition="2024"\n'
        )
        self.write(
            "codex-rs/owner/Cargo.toml",
            '[package]\nname="owner"\nedition.workspace=true\n',
        )
        self.write(
            "qualification/fixture/Cargo.toml",
            '[package]\nname="fixture"\nedition="2021"\n',
        )
        paths = [
            "codex-rs/owner/src/lib.rs",
            "codex-rs/owner/src/other.rs",
            "qualification/fixture/src/lib.rs",
        ]
        for path in paths:
            self.write(path, "pub fn entry() {}\n")
        expected = tuple(FMT.rust_file_command(path, check=True) for path in paths)
        original_read = Path.read_text
        reads = []

        def read(path, *args, **kwargs):
            reads.append(path)
            return original_read(path, *args, **kwargs)

        with patch.object(Path, "read_text", read):
            (group,) = FMT.scoped_formatter_groups(paths, check=True)
        self.assertEqual(group.commands, expected)
        self.assertEqual(reads.count(workspace), 1)

        workspace.write_text('[workspace.package]\nedition="2021"\n')
        (refreshed,) = FMT.scoped_formatter_groups(paths, check=True)
        self.assertEqual(
            refreshed.commands,
            tuple(FMT.rust_file_command(path, check=True) for path in paths),
        )
        self.assertNotEqual(refreshed.commands[0], group.commands[0])

    def test_rust_batch_fallback_runs_metadata_once_per_owner(self):
        import json

        paths = []
        manifests = []
        packages = []
        for owner, edition in (("first", "2024"), ("other", "2021")):
            manifest = self.write(
                f"codex-rs/{owner}/Cargo.toml", f'[package]\nname="{owner}"\n'
            )
            manifests.append(manifest)
            packages.append({"manifest_path": str(manifest), "edition": edition})
            for name in ("lib", "other"):
                path = f"codex-rs/{owner}/src/{name}.rs"
                self.write(path, "pub fn entry() {}\n")
                paths.append(path)
        with (
            patch.object(FMT, "tomllib", None),
            patch.object(
                FMT.subprocess,
                "check_output",
                return_value=json.dumps({"packages": packages}),
            ) as metadata,
        ):
            (group,) = FMT.scoped_formatter_groups(paths, check=True)
        self.assertEqual(metadata.call_count, 2)
        self.assertEqual(
            [Path(call.args[0][-1]) for call in metadata.call_args_list], manifests
        )
        self.assertEqual(
            [
                command.args[command.args.index("--edition") + 1]
                for command in group.commands
            ],
            ["2024", "2024", "2021", "2021"],
        )
        self.assertEqual(
            [command.cwd for command in group.commands],
            [manifest.parent for manifest in manifests for _ in range(2)],
        )

    @unittest.skipIf(os.name == "nt", "POSIX symlink fixture")
    def test_cached_rust_edition_still_checks_each_source_path(self):
        self.write(
            "codex-rs/owner/Cargo.toml", '[package]\nname="owner"\nedition="2024"\n'
        )
        self.write("codex-rs/owner/src/first.rs", "pub fn entry() {}\n")
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "outside.rs"
            target.write_text("pub fn outside() {}\n")
            (self.root / "codex-rs/owner/src/second.rs").symlink_to(target)
            with self.assertRaisesRegex(ValueError, "source escapes repository"):
                FMT.scoped_formatter_groups(
                    ["codex-rs/owner/src/first.rs", "codex-rs/owner/src/second.rs"],
                    check=True,
                )

    def test_rust_check_batches_sources_without_crossing_owner_or_config_context(self):
        for owner, edition in (("first", "2024"), ("other", "2021")):
            self.write(
                f"codex-rs/{owner}/Cargo.toml",
                f'[package]\nname="{owner}"\nedition="{edition}"\n',
            )
        paths = [
            "codex-rs/first/src/a.rs",
            "codex-rs/first/src/b.rs",
            "codex-rs/first/src/nested/c.rs",
            "codex-rs/other/src/d.rs",
        ]
        for path in paths:
            self.write(path, "pub fn entry() {}\n")
        (group,) = FMT.scoped_formatter_groups(paths, check=True)
        with patch.object(
            FMT.subprocess,
            "run",
            return_value=subprocess.CompletedProcess((), 0, stdout=""),
        ) as runner:
            self.assertEqual(
                FMT.run_formatter_group(group), FMT.FormatterResult("Rust", "", 0)
            )
        self.assertEqual(
            [(call.args[0], call.kwargs["cwd"]) for call in runner.call_args_list],
            [
                (
                    (*group.commands[0].args, group.commands[1].args[-1]),
                    self.root / "codex-rs/first",
                ),
                (group.commands[2].args, self.root / "codex-rs/first"),
                (group.commands[3].args, self.root / "codex-rs/other"),
            ],
        )

    def test_rust_check_splits_long_unicode_arguments_without_losing_inputs(self):
        self.write(
            "codex-rs/owner/Cargo.toml", '[package]\nname="owner"\nedition="2024"\n'
        )
        paths = [f"codex-rs/owner/src/{'界' * 30}{i:03}.rs" for i in range(100)]
        for path in paths:
            self.write(path, "pub fn entry() {}\n")
        (group,) = FMT.scoped_formatter_groups(paths, check=True)
        with patch.object(
            FMT.subprocess,
            "run",
            return_value=subprocess.CompletedProcess((), 0, stdout=""),
        ) as runner:
            self.assertEqual(FMT.run_formatter_group(group).returncode, 0)
        args = [call.args[0] for call in runner.call_args_list]
        self.assertGreater(len(args), 1)
        self.assertLess(len(args), len(paths))
        self.assertEqual(
            [path for command in args for path in command[command.index("--") + 1 :]],
            [command.args[-1] for command in group.commands],
        )
        for command in args:
            self.assertLessEqual(
                sum(2 * len(os.fsencode(arg)) + 3 for arg in command), 16000
            )

    def test_rust_check_batch_failure_is_reported(self):
        self.write(
            "codex-rs/owner/Cargo.toml", '[package]\nname="owner"\nedition="2024"\n'
        )
        paths = ["codex-rs/owner/src/a.rs", "codex-rs/owner/src/b.rs"]
        (group,) = FMT.scoped_formatter_groups(paths, check=True)
        with patch.object(
            FMT.subprocess,
            "run",
            return_value=subprocess.CompletedProcess((), 1, stdout="parse error\n"),
        ) as runner:
            result = FMT.run_formatter_group(group)
        self.assertEqual(runner.call_count, 1)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.name, "Rust")
        self.assertIn("parse error\n", result.output)
        for path in paths:
            self.assertIn(str(self.root / path), result.output)

    def test_rust_fix_preserves_per_file_stop_on_failure(self):
        self.write(
            "codex-rs/owner/Cargo.toml", '[package]\nname="owner"\nedition="2024"\n'
        )
        paths = [f"codex-rs/owner/src/{name}.rs" for name in ("a", "b", "c")]
        (group,) = FMT.scoped_formatter_groups(paths, check=False)
        with patch.object(
            FMT.subprocess,
            "run",
            side_effect=[
                subprocess.CompletedProcess((), 0, stdout=""),
                subprocess.CompletedProcess((), 1, stdout="parse error\n"),
            ],
        ) as runner:
            self.assertEqual(FMT.run_formatter_group(group).returncode, 1)
        self.assertEqual(
            [call.args[0] for call in runner.call_args_list],
            [command.args for command in group.commands[:2]],
        )

    def test_rust_formatter_executes_in_owner_context_without_touching_neighbor(self):
        import json

        owner = self.root / "codex-rs/owner"
        source = self.write("codex-rs/owner/src/lib.rs", "pub fn selected() {}\n")
        untouched = self.write("codex-rs/other/src/lib.rs", "pub fn unchanged() {}\n")
        self.write(
            "codex-rs/owner/Cargo.toml", '[package]\nname="owner"\nedition="2024"\n'
        )
        tool = self.write(
            "tool_probe.py",
            'import json,os,sys\nprint(json.dumps({"cwd":os.getcwd(),"args":sys.argv[1:]}))\n',
        )
        command = FMT.rust_file_command("codex-rs/owner/src/lib.rs", check=True)
        process = subprocess.run(
            [sys.executable, str(tool), *command.args[1:]],
            cwd=command.cwd,
            check=True,
            capture_output=True,
            text=True,
        )
        observed = json.loads(process.stdout)
        self.assertEqual(Path(observed["cwd"]), owner)
        self.assertEqual(Path(observed["args"][-1]), source)
        self.assertIn("--check", observed["args"])
        self.assertEqual(untouched.read_text(), "pub fn unchanged() {}\n")

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
                str(self.root / "codex-rs/first/src/lib.rs"),
                str(self.root / "codex-rs/first/src/new module.rs"),
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
                str(self.root / "codex-rs/first/src/lib.rs"),
                str(self.root / "codex-rs/other/src/lib.rs"),
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
        self.assertEqual(
            command.args[-1], str(self.root / "qualification/fixture/src/lib.rs")
        )
        self.assertEqual(command.cwd, self.root / "qualification/fixture")
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
