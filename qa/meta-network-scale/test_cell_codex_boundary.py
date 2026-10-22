"""Fail-closed fixtures for the Hepta Cell/Codex dependency gate."""
import importlib.util
from pathlib import Path
import tempfile
import tomllib
import unittest

SOURCE = Path(__file__).with_name("check_cell_codex_boundary.py")
spec = importlib.util.spec_from_file_location("check_cell_codex_boundary", SOURCE)
assert spec is not None and spec.loader is not None
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class CellCodexBoundaryTests(unittest.TestCase):
    def make_manifest(self, dependencies: str) -> dict:
        return tomllib.loads('[package]\nname = "codex-hepta-neuron"\n' + dependencies)

    def test_allowed_hepta_contracts_and_pure_utilities(self):
        data = self.make_manifest('''
[dependencies]
codex-hepta-types = { path = "../hepta-types" }
codex-utils-absolute-path = { workspace = true }
serde = "1"
''')
        self.assertEqual(checker.check_manifest(data, "hepta-neuron"), [])

    def test_bare_core_and_renamed_harness_dependencies_fail(self):
        data = self.make_manifest('''
[dependencies]
codex-core = { workspace = true }
innocent = { package = "codex-app-server-client", workspace = true }
other = { package = "codex_tools", version = "1" }
''')
        errors = checker.check_manifest(data, "hepta-neuron")
        self.assertEqual(len(errors), 3)
        for package in ("codex-core", "codex-app-server-client", "codex_tools"):
            self.assertTrue(any(package in value for value in errors), errors)

    def test_hepta_effect_owner_and_nonpure_codex_utils_are_forbidden(self):
        data = self.make_manifest('''
[dependencies]
codex-hepta-agentd = { workspace = true }
codex-utils-pty = { workspace = true }
''')
        errors = checker.check_manifest(data, "hepta-neuron")
        self.assertEqual(len(errors), 2)

    def test_target_dev_and_build_tables_cannot_bypass_gate(self):
        data = self.make_manifest('''
[target.'cfg(windows)'.dependencies]
window_api = { package = "codex-app-server-protocol", workspace = true }
[target.'cfg(unix)'.dev-dependencies]
local = { package = "codex-core", workspace = true }
[build-dependencies]
builder = { package = "codex-sandboxing", workspace = true }
''')
        errors = checker.check_manifest(data, "hepta-neuron")
        self.assertEqual(len(errors), 3)
        self.assertTrue(any("cfg(windows)" in value for value in errors))
        self.assertTrue(any("dev-dependencies" in value for value in errors))
        self.assertTrue(any("build-dependencies" in value for value in errors))

    def test_missing_manifest_is_a_failure_not_a_skip(self):
        with tempfile.TemporaryDirectory() as temp:
            errors = checker.check_workspace(Path(temp))
        self.assertEqual(len(errors), 1)
        self.assertIn("workspace: cannot resolve", errors[0])

    def test_root_workspace_alias_updates_trigger_boundary_ci(self):
        workflow = (
            Path(__file__).resolve().parents[2]
            / ".github"
            / "workflows"
            / "hepta-cell-codex-boundary.yml"
        ).read_text(encoding="utf-8")
        paths = workflow.partition("  workflow_dispatch:")[0]
        self.assertIn('      - "codex-rs/Cargo.toml"', paths)
        for name in checker.CELL_CRATES:
            self.assertIn(f'      - "codex-rs/{name}/Cargo.toml"', paths)

    def test_p3_p5_claim_changes_trigger_fresh_cell_codex_proof(self):
        # Cell/Codex proof is source-specific, not transferable from the
        # earlier qualification SHA after scale or NDU evidence changes.
        workflow = (
            Path(__file__).resolve().parents[2]
            / ".github"
            / "workflows"
            / "hepta-cell-codex-boundary.yml"
        ).read_text(encoding="utf-8")
        paths = workflow.partition("  workflow_dispatch:")[0]
        for source in (
            "qa/meta-network-scale/scale_matrix.py",
            "qa/meta-network-scale/test_scale_matrix.py",
            "docs/learning/CELL_EXECUTION_BENCHMARK_MATRIX.json",
            "codex-rs/hepta-ndu/src/output_portfolio.rs",
            "codex-rs/hepta-ndu/src/output_portfolio_types.rs",
            "codex-rs/hepta-ndu/src/output_portfolio_tests.rs",
        ):
            with self.subTest(source=source):
                self.assertIn(f'      - "{source}"', paths)

    def test_workspace_renamed_core_cannot_bypass_gate(self):
        # A harmless-looking member alias inherits an actual codex-core crate.
        data = self.make_manifest('''
[dependencies]
innocent = { workspace = true }
''')
        workspace = {"innocent": {"package": "codex-core", "path": "core"}}
        errors = checker.check_manifest(data, "hepta-neuron", workspace)
        self.assertEqual(len(errors), 1)
        self.assertIn("codex-core", errors[0])

    def test_workspace_member_cannot_override_package_to_codex_core(self):
        data = self.make_manifest('''
[dependencies]
innocent = { workspace = true, package = "codex-core" }
''')
        workspace = {"innocent": {"package": "codex-hepta-types"}}
        errors = checker.check_manifest(data, "hepta-neuron", workspace)
        self.assertEqual(len(errors), 1)
        self.assertIn("codex-core", errors[0])

    def test_workspace_unknown_dependency_fails_closed(self):
        data = self.make_manifest('''
[dependencies]
missing = { workspace = true }
''')
        self.assertEqual(len(checker.check_manifest(data, "hepta-neuron", {})), 1)

    def test_identity_mismatch_fails_even_with_allowed_dependencies(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "codex-rs").mkdir()
            (root / "codex-rs" / "Cargo.toml").write_text(
                "[workspace]\n[workspace.dependencies]\n", encoding="utf-8"
            )
            for name in checker.CELL_CRATES:
                target = root / "codex-rs" / name
                target.mkdir(parents=True)
                (target / "Cargo.toml").write_text(
                    f'[package]\nname = "codex-{name}"\n', encoding="utf-8"
                )
            self.assertEqual(checker.check_workspace(root), [])
            (root / "codex-rs" / checker.CELL_CRATES[0] / "Cargo.toml").write_text(
                '[package]\nname = "codex-core"\n', encoding="utf-8"
            )
            self.assertEqual(len(checker.check_workspace(root)), 1)


if __name__ == "__main__":
    unittest.main()
