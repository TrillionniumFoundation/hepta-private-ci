#!/usr/bin/env python3
"""Executable selection regressions. No Cargo downloads or network required."""
from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

from hepta_ci_scope import ScopeError, WorkspaceGraph, collect, select


class FixtureBase:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.write("codex-rs/Cargo.toml", '''[workspace]
members = ["leaf", "middle", "top", "unrelated"]
resolver = "2"
[workspace.dependencies]
leaf-alias = { package = "test-leaf", path = "leaf" }
''')
        self.pkg("leaf")
        self.pkg("middle", '[dependencies]\nleaf-alias = { workspace = true, optional = true }\n')
        self.pkg("top", '[target.\'cfg(windows)\'.dev-dependencies]\nrenamed = { package = "test-middle", path = "../middle" }\n')
        self.pkg("unrelated")

    def write(self, path, data):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(data, encoding="utf-8")

    def pkg(self, path, rest="", *, name=None):
        self.write(f"codex-rs/{path}/Cargo.toml", f'[package]\nname = "{name or "test-" + path.replace("/", "-")}"\nversion = "0.1.0"\nedition = "2024"\n{rest}')
        self.write(f"codex-rs/{path}/src/lib.rs", "pub fn value() -> u8 { 1 }\n")

    def graph(self):
        return WorkspaceGraph.load(self.root)

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], stderr=subprocess.PIPE).decode().strip()

    def init_git(self):
        self.git("init", "-q")
        self.git("config", "user.name", "Scope Test")
        self.git("config", "user.email", "scope-test@example.invalid")
        self.git("add", ".")
        self.git("commit", "-qm", "baseline")
        return self.git("rev-parse", "HEAD")

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-qm", "change")
        return self.git("rev-parse", "HEAD")


class ScopeTests(FixtureBase, unittest.TestCase):
    def test_optional_alias_target_dev_transitive(self):
        plan = select(self.graph(), ["codex-rs/leaf/src/lib.rs"])
        self.assertEqual(plan.rust_packages, ["test-leaf", "test-middle", "test-top"])
        self.assertFalse(plan.full_workspace)
        self.assertFalse(plan.engineering)
        self.assertFalse(plan.os_evidence)
        self.assertFalse(plan.ui_native)

    def test_leaf_of_dependency_graph_does_not_test_dependencies(self):
        self.assertEqual(select(self.graph(), ["codex-rs/top/src/lib.rs"]).rust_packages, ["test-top"])

    def test_unrelated_crate_is_isolated(self):
        self.assertEqual(select(self.graph(), ["codex-rs/unrelated/src/lib.rs"]).rust_packages, ["test-unrelated"])

    def test_build_dependencies_propagate(self):
        self.pkg("unrelated", '[build-dependencies]\nleaf = { path = "../leaf", package = "test-leaf" }\n')
        self.assertIn("test-unrelated", select(self.graph(), ["codex-rs/leaf/src/lib.rs"]).rust_packages)

    def test_implicit_path_member_owns_its_tests(self):
        self.pkg("middle", '[dev-dependencies]\nsupport = { path = "../support", package = "test-support" }\n')
        self.pkg("support")
        plan = select(self.graph(), ["codex-rs/support/src/lib.rs"])
        self.assertEqual(plan.rust_packages, ["test-middle", "test-support", "test-top"])

    def test_nested_package_not_parent_ownership(self):
        self.pkg("middle", '[dev-dependencies]\nsupport = { path = "tests/support", package = "test-support" }\n')
        self.pkg("middle/tests/support", name="test-support")
        graph = self.graph()
        self.assertEqual(graph.owners("codex-rs/middle/tests/support/src/lib.rs"),
                         {"codex-rs/middle/tests/support/Cargo.toml"})
        self.assertEqual(select(graph, ["codex-rs/middle/tests/support/src/lib.rs"]).rust_packages,
                         ["test-middle", "test-support", "test-top"])

    def test_path_patch_adds_reverse_edge(self):
        with (self.root / "codex-rs/Cargo.toml").open("a") as f:
            f.write('[patch.crates-io]\np = { package = "test-patched", path = "patched" }\n')
        self.pkg("patched")
        self.pkg("middle", '[dependencies]\npatch-alias = { package = "test-patched", version = "1" }\n')
        self.assertEqual(select(self.graph(), ["codex-rs/patched/src/lib.rs"]).rust_packages,
                         ["test-middle", "test-patched", "test-top"])

    def test_glob_exclude(self):
        self.write("codex-rs/Cargo.toml", '[workspace]\nmembers = ["*"]\nexclude = ["unrelated"]\n[workspace.dependencies]\nleaf-alias = { package = "test-leaf", path = "leaf" }\n')
        self.assertNotIn("test-unrelated", self.graph().member_names())

    def test_manifest_edit_forces_full(self):
        plan = select(self.graph(), ["codex-rs/leaf/Cargo.toml"])
        self.assertTrue(plan.full_workspace)
        self.assertEqual(plan.rust_packages, self.graph().member_names())

    def test_removed_manifest_forces_full(self):
        self.assertTrue(select(self.graph(), ["codex-rs/removed/Cargo.toml"]).full_workspace)

    def test_unknown_rust_path_forces_full(self):
        self.assertTrue(select(self.graph(), ["codex-rs/new-component/lib.rs"]).full_workspace)

    def test_shared_core_forces_full(self):
        self.assertTrue(select(self.graph(), ["codex-rs/core/src/lib.rs"]).full_workspace)

    def test_builder_configuration_forces_full(self):
        for path in (".cargo/config.toml", "codex-rs/Cargo.lock", "scripts/hepta_ci_scope.py"):
            with self.subTest(path=path):
                self.assertTrue(select(self.graph(), [path]).full_workspace)

    def test_unclassified_contract_change_forces_full(self):
        self.assertTrue(select(self.graph(), ["docs/readiness/PROTOCOLS.json"]).full_workspace)

    def test_document_prose_does_not_launch_native_build(self):
        plan = select(self.graph(), ["docs/guide.md", "README.md"])
        self.assertEqual(plan.rust_packages, [])
        self.assertFalse(plan.engineering)
        self.assertFalse(plan.source_owner)

    def test_python_owner_does_not_launch_rust(self):
        plan = select(self.graph(), ["tools/hepta-engineering-control/owner.py"])
        self.assertTrue(plan.engineering)
        self.assertFalse(plan.os_evidence)
        self.assertEqual(plan.rust_packages, [])

    def test_os_owner_is_independent(self):
        plan = select(self.graph(), ["tools/hepta-os-evidence/test_native.py"])
        self.assertTrue(plan.os_evidence)
        self.assertFalse(plan.engineering)
        self.assertEqual(plan.rust_packages, [])

    def test_ui_owner_is_independent(self):
        plan = select(self.graph(), ["apps/hepta-browser/src/browser.js"])
        self.assertTrue(plan.ui_browser)
        self.assertFalse(plan.ui_native)
        self.assertEqual(plan.rust_packages, [])

    def test_unknown_diff_never_skips(self):
        plan = select(self.graph(), [], unknown_diff=True)
        self.assertTrue(plan.full_workspace)
        self.assertTrue(plan.engineering and plan.os_evidence and plan.ui_browser and plan.ui_native)

    def test_empty_diff_is_empty(self):
        self.assertEqual(select(self.graph(), []).rust_packages, [])

    def test_missing_dependency_fails(self):
        (self.root / "codex-rs/leaf/Cargo.toml").unlink()
        with self.assertRaises(ScopeError):
            self.graph()

    def test_dependency_cycle_terminates(self):
        self.pkg("leaf", '[dev-dependencies]\nback = { package = "test-top", path = "../top" }\n')
        self.assertEqual(select(self.graph(), ["codex-rs/leaf/src/lib.rs"]).rust_packages,
                         ["test-leaf", "test-middle", "test-top"])

    def test_invalid_path_fails(self):
        for path in ("../outside", "/etc/passwd", "a/../outside", "a\\b"):
            with self.subTest(path=path), self.assertRaises(ScopeError):
                select(self.graph(), [path])

    def test_path_dependency_cannot_escape(self):
        self.pkg("leaf", '[dependencies]\nx = { path = "../../../outside" }\n')
        with self.assertRaises(ScopeError):
            self.graph()

    def test_real_git_rename_tests_both_owners(self):
        base = self.init_git()
        self.git("mv", "codex-rs/leaf/src/lib.rs", "codex-rs/unrelated/src/moved.rs")
        head = self.commit()
        paths, unknown, tracked = collect(self.root, base, head)
        self.assertFalse(unknown)
        self.assertIn("codex-rs/leaf/src/lib.rs", paths)
        self.assertIn("codex-rs/unrelated/src/moved.rs", paths)
        self.assertEqual(select(WorkspaceGraph.load(self.root, tracked), paths).rust_packages,
                         ["test-leaf", "test-middle", "test-top", "test-unrelated"])

    def test_dirty_tracked_source_rejected(self):
        head = self.init_git()
        self.write("codex-rs/leaf/src/lib.rs", "changed\n")
        with self.assertRaises(ScopeError):
            collect(self.root, head, head)

    def test_wrong_tested_identity_rejected(self):
        self.init_git()
        with self.assertRaises(ScopeError):
            collect(self.root, "0" * 40, "f" * 40)

    def test_initial_push_and_missing_base_are_conservative(self):
        head = self.init_git()
        for base in ("0" * 40, "f" * 40, ""):
            with self.subTest(base=base):
                self.assertTrue(collect(self.root, base, head)[1])

    def test_untracked_manifest_cannot_enter_graph(self):
        head = self.init_git()
        _, _, tracked = collect(self.root, head, head)
        tracked.remove("codex-rs/leaf/Cargo.toml")
        with self.assertRaises(ScopeError):
            WorkspaceGraph.load(self.root, tracked)

    def test_names_and_outputs_are_stable(self):
        a = select(self.graph(), ["codex-rs/top/src/lib.rs", "codex-rs/leaf/src/lib.rs"])
        b = select(self.graph(), reversed(a.changed_paths))
        self.assertEqual(a, b)
        self.assertEqual(a.outputs()["engineering"], "false")


if __name__ == "__main__":
    unittest.main()
