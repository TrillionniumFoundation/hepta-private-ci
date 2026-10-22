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
        self.assertEqual(len(errors), len(checker.CELL_CRATES))
        self.assertTrue(all("cannot parse" in error for error in errors))

    def test_identity_mismatch_fails_even_with_allowed_dependencies(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
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
