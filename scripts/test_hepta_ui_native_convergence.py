from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_hepta_ui_native_convergence.py"
SPEC = importlib.util.spec_from_file_location(
    "check_hepta_ui_native_convergence", SCRIPT
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class UiNativeConvergenceTests(unittest.TestCase):
    def test_exact_source_contract_is_fail_closed(self) -> None:
        evidence = MODULE.check_repository()
        self.assertEqual(evidence["status"], "structural-pass")
        self.assertRegex(evidence["implementationSourceSha"], r"^[0-9a-f]{40}$")
        self.assertEqual(evidence["workflow"], "ui-native-qualification.yml")
        self.assertGreaterEqual(evidence["retiredWorkflowCount"], 16)

    def test_release_claims_remain_independently_gated(self) -> None:
        evidence = MODULE.check_repository()
        self.assertIn(
            "release flags remain false pending independent review",
            evidence["limitations"],
        )

    def test_job_environment_rejects_runner_in_each_actual_job(self) -> None:
        workflow = (ROOT / ".github/workflows/ui-native-qualification.yml").read_text()
        MODULE.check_job_environment_contexts(workflow)
        for job in ("qualify", "storage_scale"):
            offset = workflow.index("    env:\n", workflow.index(f"  {job}:\n"))
            offset += len("    env:\n")
            for expression in (
                "runner.temp",
                "runner['temp']",
                "toJSON(runner)",
                "format('}}', runner.temp)",
            ):
                with self.subTest(job=job, expression=expression):
                    changed = (
                        workflow[:offset]
                        + f"      FIXTURE: ${{{{ {expression} }}}}\n"
                        + workflow[offset:]
                    )
                    with self.assertRaisesRegex(
                        RuntimeError, f"job {job} env uses unavailable context 'runner'"
                    ):
                        MODULE.check_job_environment_contexts(changed)

    def test_actual_job_header_comments_cannot_hide_unavailable_contexts(self) -> None:
        workflow = (ROOT / ".github/workflows/ui-native-qualification.yml").read_text()
        for header in ("jobs: # qualification jobs", "jobs:   "):
            annotated = workflow.replace("jobs:\n", header + "\n", 1)
            MODULE.check_job_environment_contexts(annotated)
            for job in ("qualify", "storage_scale"):
                offset = annotated.index("    env:\n", annotated.index(f"  {job}:\n"))
                offset += len("    env:\n")
                with self.subTest(header=header, job=job):
                    invalid = (
                        annotated[:offset]
                        + "      FIXTURE: ${{ runner.temp }}\n"
                        + annotated[offset:]
                    )
                    with self.assertRaisesRegex(
                        RuntimeError, f"job {job} env uses unavailable context 'runner'"
                    ):
                        MODULE.check_job_environment_contexts(invalid)
                    quoted = (
                        annotated[:offset]
                        + "      FIXTURE: \"${{ format('literal # runner.temp', github.sha) }}\"\n"
                        + annotated[offset:]
                    )
                    MODULE.check_job_environment_contexts(quoted)

    def test_context_guard_preserves_step_contexts_and_literal_names(self) -> None:
        workflow = """name: context scope fixture
on: workflow_dispatch
jobs:
  qualified:
    env:
      SOURCE: ${{ github.sha }}
      OUTPUT: >-
        ${{ format('literal runner.temp with ''quotes''', needs.subject.outputs.candidate) }}
      SUBJECT: ${{ matrix.kind || inputs.kind || vars.kind }}
      TOKEN: ${{ secrets.fixture }}
      MATRIX: ${{ toJSON(strategy) }}
    steps:
      - env:
          OUTPUT: ${{ runner.temp }}
          PRIOR: ${{ steps.fixture.outputs.result }}
        if: runner.os == 'Linux'
        run: echo '${{ env.OUTPUT }}'
"""
        MODULE.check_job_environment_contexts(workflow)
        MODULE.check_job_environment_contexts(
            workflow.replace(
                "literal runner.temp with ''quotes''", "literal runner.temp }} {0}"
            )
        )
        changed = workflow.replace("github.sha", "env.SOURCE", 1)
        with self.assertRaisesRegex(
            RuntimeError, "job qualified env uses unavailable context 'env'"
        ):
            MODULE.check_job_environment_contexts(changed)


class FrozenImplementationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "--quiet")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "user.name", "fixture")
        self.path = self.root / "apps/hepta-native/portal/file_chooser.py"
        self.path.parent.mkdir(parents=True)
        self.path.write_text("original\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "frozen implementation")
        self.implementation = self.git("rev-parse", "HEAD").strip()

    def git(self, *args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=self.root, text=True)

    def check(self) -> None:
        with patch.object(MODULE, "ROOT", self.root):
            MODULE.check_frozen_implementation(self.implementation)

    def test_unchanged_source_and_metadata_only_commit_pass(self) -> None:
        (self.root / "review.json").write_text("{}\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "review metadata")
        self.check()

    def test_checkout_attributes_are_frozen_in_worktree_and_commits(self) -> None:
        attributes = (".gitattributes", "apps/hepta-native/.gitattributes")
        for relative in attributes:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("* text=auto eol=lf\n", encoding="utf-8", newline="\n")
        self.git("add", *attributes)
        self.git("commit", "--quiet", "-m", "freeze exact checkout bytes")
        self.implementation = self.git("rev-parse", "HEAD").strip()
        self.check()
        for relative in attributes:
            with self.subTest(attributes=relative):
                path = self.root / relative
                path.write_text(
                    "* text=auto eol=crlf\n", encoding="utf-8", newline="\n"
                )
                with self.assertRaisesRegex(RuntimeError, "working-tree drift"):
                    self.check()
                self.git("add", relative)
                self.git(
                    "commit", "--quiet", "-m", "change checkout bytes after freeze"
                )
                with self.assertRaisesRegex(RuntimeError, "after the frozen source"):
                    self.check()
                self.git("reset", "--hard", "--quiet", self.implementation)

    def test_committed_portal_drift_rejects(self) -> None:
        self.path.write_text("changed\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "changed product adapter")
        with self.assertRaisesRegex(RuntimeError, "after the frozen source"):
            self.check()

    def test_worktree_and_staged_drift_reject(self) -> None:
        self.path.write_text("changed\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "working-tree drift"):
            self.check()
        self.git("add", ".")
        with self.assertRaisesRegex(RuntimeError, "working-tree drift"):
            self.check()

    def test_untracked_product_source_rejects(self) -> None:
        self.path.with_name("extra.py").write_text("extra\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "untracked source"):
            self.check()

    def freeze_storage_budget(self) -> Path:
        path = self.root / "apps/hepta-native/STORAGE_BUDGETS.json"
        path.write_text(
            json.dumps(
                {
                    "implementationSourceSha": "1" * 40,
                    "implementationSourceTree": "2" * 40,
                    "performance": {"mutationP95Milliseconds": 100},
                    "structural": {"maxActiveRecords": 4096},
                    "productionQualified": False,
                }
            ),
            encoding="utf-8",
        )
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "freeze compiled storage budget contract")
        self.implementation = self.git("rev-parse", "HEAD").strip()
        return path

    def test_storage_budget_source_anchors_can_continue(self) -> None:
        path = self.freeze_storage_budget()
        budget = json.loads(path.read_text(encoding="utf-8"))
        budget.update(
            implementationSourceSha="3" * 40, implementationSourceTree="4" * 40
        )
        path.write_text(json.dumps(budget, indent=2), encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "source navigation anchors only")
        self.check()

    def test_committed_storage_budget_relaxation_rejects(self) -> None:
        path = self.freeze_storage_budget()
        budget = json.loads(path.read_text(encoding="utf-8"))
        budget["performance"]["mutationP95Milliseconds"] = 1000000
        path.write_text(json.dumps(budget), encoding="utf-8")
        self.git("add", ".")
        self.git(
            "commit", "--quiet", "-m", "relaxed ceiling without implementation freeze"
        )
        with self.assertRaisesRegex(RuntimeError, "budget contract changed"):
            self.check()

    def test_worktree_storage_budget_subject_drift_rejects(self) -> None:
        path = self.freeze_storage_budget()
        budget = json.loads(path.read_text(encoding="utf-8"))
        budget["structural"]["maxActiveRecords"] = 10
        path.write_text(json.dumps(budget), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "budget contract changed"):
            self.check()


class LocalCargoDependencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "--quiet")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "user.name", "fixture")
        self.write(
            "codex-rs/Cargo.toml",
            """[workspace]
members = ["hepta-native-gateway", "hepta-runtime", "leaf", "windows", "build-tool", "test-helper", "unbuilt-dev", "patched"]
[workspace.dependencies]
runtime-alias = { package = "real-runtime", path = "hepta-runtime" }
leaf = { path = "leaf" }
[patch.crates-io]
patched = { path = "patched" }
""",
        )
        self.crate(
            "apps/hepta-native",
            '[dependencies]\ngateway = { path = "../../codex-rs/hepta-native-gateway" }\n',
        )
        self.crate(
            "codex-rs/hepta-native-gateway",
            """[dependencies]
runtime-alias = { workspace = true }
[target.'cfg(windows)'.dependencies]
windows = { path = "../windows", optional = true }
[build-dependencies]
build-tool = { path = "../build-tool" }
[dev-dependencies]
test-helper = { path = "../test-helper" }
""",
        )
        self.crate(
            "codex-rs/hepta-runtime",
            """[dependencies]
leaf = { workspace = true }
[dev-dependencies]
unbuilt-dev = { path = "../unbuilt-dev" }
""",
        )
        for name in (
            "leaf",
            "windows",
            "build-tool",
            "test-helper",
            "unbuilt-dev",
            "patched",
        ):
            self.crate("codex-rs/" + name)
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "frozen dependency graph")
        self.implementation = self.git("rev-parse", "HEAD").strip()

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def crate(self, relative, dependencies=""):
        name = Path(relative).name
        self.write(
            relative + "/Cargo.toml",
            f'[package]\nname = "{name}"\nversion = "0.1.0"\nedition = "2024"\n'
            + dependencies,
        )
        self.write(relative + "/src/lib.rs", "pub fn original() {}\n")

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, text=True)

    def repository_root_with_ancestor_alias(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        alias = Path(temporary.name) / "parent-alias"
        try:
            alias.symlink_to(self.root.resolve().parent, target_is_directory=True)
        except OSError as error:
            if os.name == "nt" and getattr(error, "winerror", None) == 1314:
                self.skipTest("Windows token cannot create directory symlinks")
            raise
        return alias / self.root.resolve().name

    def test_ancestor_root_alias_preserves_inherited_dependencies_and_freeze(self):
        alias_root = self.repository_root_with_ancestor_alias()
        with patch.object(MODULE, "ROOT", self.root.resolve()):
            expected = MODULE.local_cargo_dependency_paths()
        with patch.object(MODULE, "ROOT", alias_root):
            self.assertEqual(MODULE.local_cargo_dependency_paths(), expected)
            MODULE.check_frozen_implementation(self.implementation)

    def test_ancestor_root_alias_cannot_hide_internal_dependency_symlink(self):
        alias_root = self.repository_root_with_ancestor_alias()
        (self.root / "codex-rs/linked").symlink_to(
            self.root / "codex-rs/leaf", target_is_directory=True
        )
        workspace = self.root / "codex-rs/Cargo.toml"
        workspace.write_text(
            workspace.read_text(encoding="utf-8").replace(
                'leaf = { path = "leaf" }', 'leaf = { path = "linked" }'
            ),
            encoding="utf-8",
        )
        for root in (self.root.resolve(), alias_root):
            with (
                self.subTest(root=root),
                patch.object(MODULE, "ROOT", root),
                self.assertRaisesRegex(RuntimeError, "uses a symlink"),
            ):
                MODULE.local_cargo_dependency_paths()

    def test_internal_parent_traversal_cannot_hide_a_dependency_symlink(self):
        alias_root = self.repository_root_with_ancestor_alias()
        (self.root / "codex-rs/linked").symlink_to(
            self.root / "codex-rs/leaf", target_is_directory=True
        )
        for root in (self.root.resolve(), alias_root):
            with (
                self.subTest(root=root),
                patch.object(MODULE, "ROOT", root),
                self.assertRaisesRegex(RuntimeError, "uses a symlink"),
            ):
                MODULE._repository_path(
                    self.root.resolve() / "codex-rs/linked/../leaf/Cargo.toml"
                )

    def test_outside_alias_cannot_reenter_the_repository(self):
        alias_root = self.repository_root_with_ancestor_alias()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        outside_alias = Path(temporary.name) / "leaf-alias"
        outside_alias.symlink_to(self.root / "codex-rs/leaf", target_is_directory=True)
        for root in (self.root.resolve(), alias_root):
            with self.subTest(root=root), patch.object(MODULE, "ROOT", root):
                with self.assertRaisesRegex(RuntimeError, "escapes the repository"):
                    MODULE._repository_path(
                        root / "codex-rs/../../" / root.name / "codex-rs/leaf"
                    )
                with self.assertRaisesRegex(RuntimeError, "escapes the repository"):
                    MODULE._repository_path(outside_alias)

    @unittest.skipUnless(os.name == "nt", "requires actual Windows NTFS junctions")
    def test_internal_junction_is_rejected_but_declared_root_alias_is_admitted(self):
        root = self.root.resolve()
        root_alias = root / "declared-root-alias"
        junction = root / "codex-rs/junction"
        target = root / "codex-rs/leaf"
        with patch.object(MODULE, "ROOT", root):
            expected = MODULE.local_cargo_dependency_paths()
        command = Path(os.environ["SystemRoot"]) / "System32/cmd.exe"
        for link, destination in ((root_alias, root), (junction, target)):
            completed = subprocess.run(
                [str(command), "/d", "/c", "mklink", "/J", str(link), str(destination)],
                text=True,
                errors="replace",
                capture_output=True,
                timeout=20,
            )
            self.assertEqual(
                completed.returncode,
                0,
                f"mklink /J failed for {link}: {completed.stdout} {completed.stderr}",
            )
            self.addCleanup(link.rmdir)
            self.assertEqual(link.resolve(), destination)
            self.assertTrue(
                link.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
            )
        self.assertFalse(junction.is_symlink())
        with patch.object(MODULE, "ROOT", root_alias):
            self.assertEqual(MODULE.local_cargo_dependency_paths(), expected)
        workspace = root / "codex-rs/Cargo.toml"
        workspace.write_text(
            workspace.read_text(encoding="utf-8").replace(
                'leaf = { path = "leaf" }', 'leaf = { path = "junction" }'
            ),
            encoding="utf-8",
        )
        for declared_root in (root, root_alias):
            with (
                self.subTest(root=declared_root),
                patch.object(MODULE, "ROOT", declared_root),
                self.assertRaisesRegex(RuntimeError, "symlink or reparse point"),
            ):
                MODULE.local_cargo_dependency_paths()

    def test_workspace_alias_target_build_and_root_dev_dependencies_are_frozen(self):
        with patch.object(MODULE, "ROOT", self.root):
            paths = MODULE.local_cargo_dependency_paths()
        for name in (
            "hepta-runtime",
            "leaf",
            "windows",
            "build-tool",
            "test-helper",
            "patched",
        ):
            self.assertIn("codex-rs/" + name, paths)
        self.assertNotIn("codex-rs/unbuilt-dev", paths)

    def test_actual_committed_transitive_runtime_change_is_rejected(self):
        self.write("codex-rs/hepta-runtime/src/lib.rs", "pub fn changed() {}\n")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "mutated transitive runtime")
        with (
            patch.object(MODULE, "ROOT", self.root),
            self.assertRaisesRegex(RuntimeError, "after the frozen source"),
        ):
            MODULE.check_frozen_implementation(self.implementation)

    def test_actual_untracked_transitive_source_is_rejected(self):
        self.write("codex-rs/leaf/src/injected.rs", "pub fn injected() {}\n")
        with (
            patch.object(MODULE, "ROOT", self.root),
            self.assertRaisesRegex(RuntimeError, "untracked source"),
        ):
            MODULE.check_frozen_implementation(self.implementation)

    def test_qualified_utility_tests_freeze_their_direct_dev_dependencies(self):
        self.crate(
            "codex-rs/utils/private-state",
            '[dev-dependencies]\nutility-test = { path = "../../utility-test" }\n',
        )
        self.crate("codex-rs/utility-test")
        with patch.object(MODULE, "ROOT", self.root):
            paths = MODULE.local_cargo_dependency_paths()
        self.assertIn("codex-rs/utils/private-state", paths)
        self.assertIn("codex-rs/utility-test", paths)

    def test_standalone_app_evidence_metadata_can_continue(self):
        self.write("apps/hepta-native/CANDIDATE.json", "{}\n")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "candidate evidence metadata")
        with patch.object(MODULE, "ROOT", self.root):
            MODULE.check_frozen_implementation(self.implementation)

    def test_workflow_missing_transitive_trigger_is_rejected(self):
        workflow = "    paths:\n      - apps/hepta-native/**\n      - codex-rs/hepta-native-gateway/**\n  workflow_dispatch:\n"
        with (
            patch.object(MODULE, "ROOT", self.root),
            self.assertRaisesRegex(RuntimeError, "does not trigger"),
        ):
            MODULE.check_dependency_workflow_filters(workflow)

    def test_workflow_complete_dependency_and_projection_triggers_pass(self):
        with patch.object(MODULE, "ROOT", self.root):
            paths = (
                *MODULE.local_cargo_dependency_paths(),
                "tools/ui-native-projections",
                ".cargo",
                "codex-rs/.cargo",
                ".gitattributes",
                "apps/hepta-native/.gitattributes",
            )
            workflow = (
                "    paths:\n"
                + "".join(
                    "      - "
                    + (
                        path
                        if path.endswith(("Cargo.toml", ".gitattributes"))
                        else path + "/**"
                    )
                    + "\n"
                    for path in paths
                )
                + "  workflow_dispatch:\n"
            )
            MODULE.check_dependency_workflow_filters(workflow)
            for replacement in ("", "      - .gitattributes/**\n"):
                with (
                    self.subTest(root_attributes_trigger=replacement),
                    self.assertRaisesRegex(RuntimeError, r"dependency \.gitattributes"),
                ):
                    MODULE.check_dependency_workflow_filters(
                        workflow.replace("      - .gitattributes\n", replacement)
                    )


if __name__ == "__main__":
    unittest.main()
