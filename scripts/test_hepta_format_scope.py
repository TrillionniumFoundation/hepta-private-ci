"""Exercise formatter scope using real Git state and observable tool commands."""

import importlib.util
import os
from pathlib import Path
import shutil
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
SOURCE_ROOT = FMT.REPO_ROOT


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
        # Reproduce the immutable test-input inventory in this real Git fixture.
        for relative in (
            *FMT.VERBATIM_FIXTURES,
            *FMT.ORIGINAL_EVIDENCE_FILES,
            *FMT.retained_rust.INVENTORY["archived"],
            *FMT.retained_rust.INVENTORY["companions"],
            *set(FMT.retained_rust.INVENTORY["maintained_builders"].values()),
        ):
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(SOURCE_ROOT / relative, destination)
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

    def test_verbatim_inputs_are_unchanged_and_unregistered_sources_still_run(self):
        relative = f"{FMT.VERBATIM_FIXTURE_PREFIX}/issue28.rs"
        fixture = self.root / relative
        original = fixture.read_bytes()
        neighbor = self.write(
            f"{FMT.VERBATIM_FIXTURE_PREFIX}/new.rs", "fn original(){}\n"
        )
        vendor = str(Path(FMT.VERBATIM_FIXTURE_PREFIX).parent)
        implementation = self.write(f"{vendor}/src/lib.rs", "fn original(){}\n")
        test = self.write(f"{vendor}/tests/contract.rs", "fn original(){}\n")
        paths = [
            relative,
            *[
                str(path.relative_to(self.root))
                for path in (neighbor, implementation, test)
            ],
        ]
        groups = FMT.scoped_formatter_groups(paths, check=False)
        self.assertEqual([group.name for group in groups], ["Rust"])
        selected = {Path(command.args[-1]) for command in groups[0].commands}
        self.assertEqual(selected, {neighbor, implementation, test})
        formatter = self.write(
            "format_probe.py",
            "from pathlib import Path\nimport sys\np=Path(sys.argv[-1])\np.write_text(p.read_text()+'// formatted\\n')\n",
        )
        probe = FMT.FormatterGroup(
            "observable formatter",
            tuple(
                FMT.Command((sys.executable, str(formatter), str(path)), self.root)
                for path in selected
            ),
        )
        self.assertEqual(FMT.run_formatter_group(probe).returncode, 0)
        self.assertEqual(fixture.read_bytes(), original)
        for path in selected:
            self.assertTrue(path.read_text().endswith("// formatted\n"))

    def test_verbatim_single_byte_mutation_fails_before_full_or_scoped_format(self):
        relative = f"{FMT.VERBATIM_FIXTURE_PREFIX}/issue28.rs"
        fixture = self.root / relative
        original = fixture.read_bytes()
        fixture.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        with self.assertRaisesRegex(ValueError, "bytes changed"):
            FMT.scoped_formatter_groups([relative], check=False)
        with self.assertRaisesRegex(ValueError, "bytes changed"):
            FMT.formatter_groups(check=True)

    def test_missing_verbatim_input_is_an_error_even_without_local_source_edits(self):
        relative = next(iter(FMT.VERBATIM_FIXTURES))
        (self.root / relative).unlink()
        with self.assertRaisesRegex(ValueError, "cannot verify"):
            FMT.scoped_formatter_groups([], check=True)

    def test_verbatim_inventory_cannot_register_a_source_outside_its_fixed_prefix(self):
        digest = next(iter(FMT.VERBATIM_FIXTURES.values()))
        for relative in (
            "scripts/first.py",
            f"{FMT.VERBATIM_FIXTURE_PREFIX}/../src/lib.rs",
        ):
            with patch.object(FMT, "VERBATIM_FIXTURES", {relative: digest}):
                with self.assertRaisesRegex(ValueError, "fixed prefix"):
                    FMT.verified_verbatim_fixture_paths()

    @unittest.skipIf(os.name == "nt", "POSIX symlink creation")
    def test_verbatim_symlink_escape_is_rejected_even_with_identical_bytes(self):
        relative = f"{FMT.VERBATIM_FIXTURE_PREFIX}/issue28.rs"
        fixture = self.root / relative
        original = fixture.read_bytes()
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "same.rs"
            target.write_bytes(original)
            fixture.unlink()
            fixture.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "escapes"):
                FMT.verified_verbatim_fixture_paths()

    def test_rust_configuration_expansion_keeps_only_unregistered_source_inputs(self):
        self.write(f"{FMT.VERBATIM_FIXTURE_PREFIX}/rustfmt.toml", "max_width=88\n")
        neighbor = f"{FMT.VERBATIM_FIXTURE_PREFIX}/new.rs"
        self.write(neighbor, "fn original(){}\n")
        groups = FMT.scoped_formatter_groups(FMT.changed_paths(), check=True)
        self.assertEqual(
            [command.args[-1] for command in groups[0].commands],
            [str(self.root / neighbor)],
        )

    def test_exact_historical_rust_records_do_not_exempt_neighboring_source(self):
        records = list(FMT.ORIGINAL_EVIDENCE_FILES)
        neighbor = self.write(
            f"{FMT.ORIGINAL_EVIDENCE_PREFIX}/actual.rs", "fn original(){}\n"
        )
        groups = FMT.scoped_formatter_groups(
            [*records, str(neighbor.relative_to(self.root))], check=True
        )
        self.assertEqual([group.name for group in groups], ["Rust"])
        self.assertEqual(
            [command.args[-1] for command in groups[0].commands], [str(neighbor)]
        )
        self.assertEqual(FMT.verified_original_evidence_paths(), frozenset(records))

    def test_historical_rust_record_mutation_fails_before_format(self):
        relative = next(iter(FMT.ORIGINAL_EVIDENCE_FILES))
        source = self.root / relative
        raw = source.read_bytes()
        source.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
        with self.assertRaisesRegex(ValueError, "original evidence bytes changed"):
            FMT.scoped_formatter_groups([], check=True)
        with self.assertRaisesRegex(ValueError, "original evidence bytes changed"):
            FMT.formatter_groups(check=False)

    def test_historical_rust_inventory_cannot_register_production_source(self):
        digest = next(iter(FMT.ORIGINAL_EVIDENCE_FILES.values()))
        for relative in (
            "codex-rs/core/src/lib.rs",
            f"{FMT.ORIGINAL_EVIDENCE_PREFIX}/../actual.rs",
        ):
            with patch.object(FMT, "ORIGINAL_EVIDENCE_FILES", {relative: digest}):
                with self.assertRaisesRegex(ValueError, "fixed prefix"):
                    FMT.verified_original_evidence_paths()

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

    def test_build_metadata_is_preserved_while_starlark_sources_are_formatted(self):
        metadata = self.write("qualification/evidence/BUILD.json", '{"exit": 1}\n')
        original = metadata.read_bytes()
        self.write("WORKSPACE.json", '{"source": "original"}\n')
        sources = ["BUILD", "BUILD.bazel", "tools/BUILD.fixture", "tools/check.bzl"]
        for source in sources:
            self.write(source, "exports_files([])\n")
        self.git("add", ".")

        full = FMT.buildifier_formatter_group(check=True)
        scoped = FMT.scoped_formatter_groups(FMT.changed_paths(), check=True)
        self.assertEqual([group.name for group in scoped], ["Bazel/Starlark"])
        for group in (full, scoped[0]):
            self.assertEqual(list(group.commands[0].args[4:]), sorted(sources))
        self.assertEqual(metadata.read_bytes(), original)
        self.assertEqual(
            FMT.scoped_formatter_groups(
                ["qualification/evidence/BUILD.json", "WORKSPACE.json"], check=False
            ),
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

    def test_retained_rust_accounts_for_every_source_without_writing_it(self):
        inventory = FMT.retained_rust.INVENTORY
        names = sorted(inventory["archived"])
        self.assertEqual(len(names), 37)
        for check in (False, True):
            commands = FMT.scoped_formatter_groups(names, check=check)[0].commands
            self.assertEqual(
                [Path(c.args[-1]).relative_to(self.root).as_posix() for c in commands],
                names,
            )
            for c in commands:
                self.assertEqual(
                    c.args[:2], (sys.executable, FMT.retained_rust.__file__)
                )
        # Exercise each kind of recorded qualification through its normal process entry.
        for role in ("checked_original", "preformat", "identity_only"):
            name = next(n for n in names if inventory["archived"][n]["role"] == role)
            command = FMT.rust_file_command(name, check=False)
            result = subprocess.run(
                command.args, cwd=command.cwd, capture_output=True, text=True
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(role, result.stdout)
        neighbor = str(Path(names[0]).with_name("new.rs")).replace("\\", "/")
        self.write(neighbor, "fn sample() {}")
        with self.assertRaisesRegex(ValueError, "owning Rust workspace missing"):
            FMT.scoped_formatter_groups([neighbor], check=False)

    def test_changed_or_missing_archived_source_and_companion_stops_planning(self):
        inventory = FMT.retained_rust.INVENTORY
        for name in [*inventory["archived"], *inventory["companions"]]:
            path = self.root / name
            original = path.read_bytes()
            with self.subTest(name=name):
                path.write_bytes(original + b" ")
                with self.assertRaisesRegex(ValueError, "retained Rust source changed"):
                    FMT.formatter_groups(check=True)
                path.unlink()
                with self.assertRaisesRegex(ValueError, "cannot read retained Rust"):
                    FMT.scoped_formatter_groups([], check=False)
                path.write_bytes(original)

    @unittest.skipIf(os.name == "nt", "POSIX symlink creation")
    def test_retained_rust_rejects_same_bytes_behind_a_symlink(self):
        name = next(iter(FMT.retained_rust.INVENTORY["archived"]))
        source = self.root / name
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "same.rs"
            target.write_bytes(source.read_bytes())
            source.unlink()
            source.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "escapes or aliases"):
                FMT.scoped_formatter_groups([name], check=False)

    def test_generated_rust_inputs_remain_writable_and_use_the_builder_edition(self):
        owners = FMT.retained_rust.INVENTORY["maintained_builders"]
        self.assertEqual(len(owners), 7)
        for name in owners:
            write = FMT.rust_file_command(name, check=False)
            read = FMT.rust_file_command(name, check=True)
            self.assertEqual(write.args[:3], ("rustfmt", "--edition", "2024"))
            self.assertIn("skip_children=true", write.args)
            self.assertNotIn("--check", write.args)
            self.assertIn("--check", read.args)
        name = next(iter(owners))
        owner = self.root / owners[name]
        owner.write_text("options=['--edition=2021']")
        self.assertEqual(FMT.rust_file_command(name, check=False).args[2], "2021")
        owner.write_text("options=[]")
        with self.assertRaisesRegex(ValueError, "single Rust edition"):
            FMT.rust_file_command(name, check=True)

    def test_preformat_and_successor_roles_cannot_be_rebound(self):
        records = FMT.retained_rust
        import json

        receipt = json.loads((self.root / records.SUPERSESSION).read_bytes())
        source = (self.root / records.PREFORMAT).read_bytes()
        records.verify_preformat(source, receipt)
        forged = dict(receipt, final_source_sha256=receipt["preformat_source_sha256"])
        with self.assertRaisesRegex(ValueError, "identities differ"):
            records.verify_preformat(source, forged)

    def test_retained_policy_metadata_rejects_drift(self):
        records = FMT.retained_rust
        self.write("tampered-policy.json", records.POLICY.read_text() + " ")
        with (
            patch.object(records, "POLICY", self.root / "tampered-policy.json"),
            self.assertRaisesRegex(ValueError, "inventory changed"),
        ):
            records.read_policy()

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
