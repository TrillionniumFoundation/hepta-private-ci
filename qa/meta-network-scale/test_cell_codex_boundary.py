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
    def populate_local_source_tree(self, root: Path):
        for package, relative in checker.LOCAL_PACKAGE_DIRECTORIES.items():
            directory = root / "codex-rs" / relative
            directory.mkdir(parents=True, exist_ok=True)
            manifest = directory / "Cargo.toml"
            if not manifest.exists():
                manifest.write_text(
                    f'[package]\nname = "{package}"\n', encoding="utf-8"
                )

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

    def test_hepta_types_remains_minimal_and_execution_free(self):
        valid = self.make_manifest("""
[dependencies]
sha2 = { workspace = true }
""")
        self.assertEqual(checker.check_manifest(valid, "hepta-types"), [])
        forbidden = self.make_manifest("""
[dependencies]
codex-hepta-codex-adapter = { workspace = true }
codex-utils-absolute-path = { workspace = true }
serde = "1"
""")
        errors = checker.check_manifest(forbidden, "hepta-types")
        self.assertEqual(len(errors), 3, errors)
        self.assertTrue(any("codex-hepta-codex-adapter" in err for err in errors))
        self.assertTrue(any("codex-utils-absolute-path" in err for err in errors))
        self.assertTrue(any("serde" in err for err in errors))

    def test_unreviewed_native_runtime_and_async_process_clients_fail(self):
        data = self.make_manifest("""
[dependencies]
hepta-runtime = { version = "0.1.0" }
renamed_tool = { package = "hepta-runtime", version = "0.1.0" }
tokio = { version = "1.5", features = ["process"] }
""")
        errors = checker.check_manifest(data, "hepta-neuron")
        self.assertEqual(len(errors), 3, errors)
        self.assertTrue(any("hepta-runtime" in error for error in errors))
        self.assertTrue(any("tokio" in error for error in errors))

    def test_workspace_native_tool_alias_does_not_bypass_closed_allowlist(self):
        data = self.make_manifest("""
[dependencies]
masked_native = { workspace = true }
""")
        workspace = {"masked_native": {"package": "hepta-runtime", "version": "0.1"}}
        errors = checker.check_manifest(data, "hepta-neuron", workspace)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("hepta-runtime", errors[0])

    def test_existing_evaluation_only_dependencies_still_allowed(self):
        data = self.make_manifest("""
[dependencies]
codex-hepta-types = { path = "../hepta-types" }
serde = { workspace = true, features = ["derive"] }
serde_json = { workspace = true }
[dev-dependencies]
ed25519-dalek = { workspace = true }
pretty_assertions = { workspace = true }
tempfile = { workspace = true }
""")
        workspace = {
            "serde": "1",
            "serde_json": "1",
            "ed25519-dalek": "2",
            "pretty_assertions": "1",
            "tempfile": "3",
        }
        self.assertEqual(checker.check_manifest(data, "hepta-ndu", workspace), [])

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
            self.populate_local_source_tree(root)
            self.assertEqual(checker.check_workspace(root), [])
            (root / "codex-rs" / checker.CELL_CRATES[0] / "Cargo.toml").write_text(
                '[package]\nname = "codex-core"\n', encoding="utf-8"
            )
            errors = checker.check_workspace(root)
            self.assertEqual(len(errors), 2, errors)
            self.assertTrue(any("crate identity differs" in err for err in errors))
            self.assertTrue(any("wrong package identity" in err for err in errors))


    def test_internal_allowlisted_name_cannot_point_to_git_or_other_path(self):
        data = self.make_manifest("""
[dependencies]
codex-hepta-types = { git = "https://example.invalid/fake.git" }
masked = { package = "codex-hepta-types", path = "../../unreviewed" }
""")
        errors = checker.check_manifest(data, "hepta-neuron")
        self.assertEqual(len(errors), 2, errors)
        self.assertTrue(all("source custody" in error for error in errors))

    def test_workspace_inherited_local_path_must_match_reviewed_directory(self):
        data = self.make_manifest("""
[dependencies]
codex-hepta-types = { workspace = true }
""")
        rejected = checker.check_manifest(
            data, "hepta-neuron",
            {"codex-hepta-types": {"path": "different-hepta-types"}},
        )
        self.assertEqual(len(rejected), 1, rejected)
        accepted = checker.check_manifest(
            data, "hepta-neuron",
            {"codex-hepta-types": {"path": "hepta-types"}},
        )
        self.assertEqual(accepted, [])

    def test_workspace_alias_cannot_rewrite_inherited_package_identity(self):
        data = self.make_manifest("""
[dependencies]
local = { package = "codex-hepta-types", workspace = true }
""")
        errors = checker.check_manifest(
            data, "hepta-neuron",
            {"local": {"package": "codex-hepta-contracts", "path": "hepta-contracts"}},
        )
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("package identity", errors[0])

    def test_allowlisted_external_package_cannot_rebind_source(self):
        data = self.make_manifest("""
[dependencies]
serde = { path = "../rogue" }
serde_json = { registry = "unreviewed", version = "1" }
sha2 = { git = "https://example.invalid/sha2" }
""")
        errors = checker.check_manifest(data, "hepta-neuron")
        self.assertEqual(len(errors), 3, errors)
        self.assertTrue(all("source custody" in error for error in errors))

    def test_workspace_external_package_git_override_is_denied(self):
        data = self.make_manifest("""
[dependencies]
serde = { workspace = true, features = ["derive"] }
""")
        errors = checker.check_manifest(
            data, "hepta-neuron",
            {"serde": {"git": "https://example.invalid/serde.git"}},
        )
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("unreviewed source", errors[0])

    def test_approved_workspace_utility_and_external_registry_still_pass(self):
        data = self.make_manifest("""
[dependencies]
codex-utils-absolute-path = { workspace = true }
serde = { workspace = true, features = ["derive"] }
""")
        errors = checker.check_manifest(
            data, "hepta-neuron",
            {
                "codex-utils-absolute-path": {"path": "utils/absolute-path"},
                "serde": {"version": "1", "features": ["rc"]},
            },
        )
        self.assertEqual(errors, [])

    def test_windows_target_dependency_cannot_redirect_approved_package(self):
        data = self.make_manifest("""
[target.'cfg(windows)'.dependencies]
types_alias = { package = "codex-hepta-types", path = "../wrong-owner" }
""")
        errors = checker.check_manifest(data, "hepta-neuron")
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("source custody", errors[0])

    def test_patch_can_not_rebind_approved_external_or_local_crate(self):
        root = tomllib.loads("""
[patch.crates-io]
serde = { path = "vendored/other-serde" }
masked_sha2 = { package = "sha2", git = "https://example.invalid/fork" }
codex-hepta-types = { path = "wrong-dir" }
""")
        errors = checker.check_root_source_overrides(root)
        self.assertEqual(len(errors), 3, errors)
        self.assertTrue(all("overrides approved" in error for error in errors))

    def test_replace_can_not_rebind_approved_external_crate(self):
        root = {"replace": {"serde:1.0.0": {"path": "vendored/fork"}}}
        errors = checker.check_root_source_overrides(root)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("replace.serde:1.0.0", errors[0])

    def test_unrelated_pinned_cargo_patches_are_preserved(self):
        root = tomllib.loads("""
[patch.crates-io]
imbl = { path = "third_party/imbl-6.1.0" }
crossterm = { git = "https://example.invalid/pin", rev = "abc123" }
""")
        self.assertEqual(checker.check_root_source_overrides(root), [])

    def test_local_source_identity_and_manifest_symlinks_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.populate_local_source_tree(root)
            self.assertEqual(checker.check_local_source_directories(root), [])
            source = root / "codex-rs" / "hepta-types"
            manifest = source / "Cargo.toml"
            valid = manifest.read_text(encoding="utf-8")
            manifest.write_text('[package]\nname = "codex-core"\n', encoding="utf-8")
            errors = checker.check_local_source_directories(root)
            self.assertEqual(len(errors), 1, errors)
            self.assertIn("wrong package identity", errors[0])
            manifest.write_text(valid, encoding="utf-8")
            original = root / "original-hepta-types"
            source.rename(original)
            source.symlink_to(original, target_is_directory=True)
            errors = checker.check_local_source_directories(root)
            self.assertEqual(len(errors), 1, errors)
            self.assertIn("symbolic link", errors[0])

    def test_missing_local_source_manifest_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.populate_local_source_tree(root)
            missing = root / "codex-rs" / "hepta-contracts" / "Cargo.toml"
            missing.unlink()
            errors = checker.check_local_source_directories(root)
            self.assertEqual(len(errors), 1, errors)
            self.assertIn("cannot read reviewed", errors[0])

    def test_pure_contract_is_present_and_free_of_codex_imports(self):
        root = Path(__file__).resolve().parents[2]
        self.assertEqual(checker.check_pure_cell_contract(root), [])

    def test_pure_contract_rejects_renamed_target_dependency_and_codex_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "codex-rs/hepta-types/src").mkdir(parents=True)
            (root / "codex-rs/hepta-codex-adapter/src").mkdir(parents=True)
            (root / "codex-rs/Cargo.toml").write_text(
                '[workspace]\n[workspace.dependencies]\nsha2 = "0.10"\n', encoding="utf-8"
            )
            manifest = root / "codex-rs/hepta-types/Cargo.toml"
            manifest.write_text(
                '[package]\nname = "codex-hepta-types"\n'
                '[dependencies]\nsha2 = { workspace = true }\n'
                '[target."cfg(unix)".build-dependencies]\n'
                'innocent = { package = "codex-core", version = "1" }\n',
                encoding="utf-8",
            )
            (root / "codex-rs/hepta-types/src/execution_contract.rs").write_text(
                'use codex_core::Codex;\npub trait NativeExecutionAdapter {}\n',
                encoding="utf-8",
            )
            (root / "codex-rs/hepta-codex-adapter/src/execution_contract.rs").write_text(
                "".join(f"pub use codex_hepta_types::{name};\n" for name in checker.PURE_NATIVE_EXPORTS), encoding="utf-8"
            )
            errors = checker.check_pure_cell_contract(root)
            self.assertEqual(len(errors), 2, errors)
            self.assertTrue(any("non-pure dependency" in error for error in errors))
            self.assertTrue(any("imports a Codex crate" in error for error in errors))

    def test_codex_facade_cannot_create_second_contract_definition(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "codex-rs/hepta-types/src").mkdir(parents=True)
            (root / "codex-rs/hepta-codex-adapter/src").mkdir(parents=True)
            (root / "codex-rs/Cargo.toml").write_text(
                '[workspace]\n[workspace.dependencies]\nsha2 = "0.10"\n', encoding="utf-8"
            )
            (root / "codex-rs/hepta-types/Cargo.toml").write_text(
                '[package]\nname = "codex-hepta-types"\n'
                '[dependencies]\nsha2 = { workspace = true }\n',
                encoding="utf-8",
            )
            (root / "codex-rs/hepta-types/src/execution_contract.rs").write_text(
                'pub trait NativeExecutionAdapter {}\n', encoding="utf-8"
            )
            (root / "codex-rs/hepta-codex-adapter/src/execution_contract.rs").write_text(
                "".join(f"pub use codex_hepta_types::{name};\n" for name in checker.PURE_NATIVE_EXPORTS) + 'pub struct RuntimeReceiptV1 {}\n',
                encoding="utf-8",
            )
            errors = checker.check_pure_cell_contract(root)
            self.assertEqual(len(errors), 1, errors)
            self.assertIn("duplicate execution contract", errors[0])


    def test_native_facade_requires_every_direct_pure_reexport(self):
        canonical = "".join(
            f"pub use codex_hepta_types::{name};\n"
            for name in checker.PURE_NATIVE_EXPORTS
        )
        self.assertEqual(checker.check_native_facade_exports(canonical), [])
        for name in checker.PURE_NATIVE_EXPORTS:
            with self.subTest(name=name):
                removed = canonical.replace(
                    f"pub use codex_hepta_types::{name};\n", ""
                )
                errors = checker.check_native_facade_exports(removed)
                self.assertTrue(any(name in err for err in errors), errors)

    def test_native_facade_rejects_private_alias_and_shadowed_struct(self):
        canonical = "".join(
            f"pub use codex_hepta_types::{name};\n"
            for name in checker.PURE_NATIVE_EXPORTS
        )
        for injection in (
            "pub type RuntimeToolIntentV1 = u32;\n",
            "pub(crate) struct GenerationFenceWitnessV1;\n",
            "enum ToolOutcomeV1 { Unreviewed }\n",
            "pub const EXECUTION_CONTRACT_VERSION_V1: u8 = 255;\n",
        ):
            with self.subTest(injection=injection):
                errors = checker.check_native_facade_exports(canonical + injection)
                self.assertEqual(len(errors), 1, errors)
                self.assertIn("duplicate execution contract", errors[0])

    def test_native_facade_rejects_wrong_module_and_renamed_exports(self):
        canonical = "".join(
            f"pub use codex_hepta_types::{name};\n"
            for name in checker.PURE_NATIVE_EXPORTS
        )
        spoofed = canonical.replace(
            "pub use codex_hepta_types::RuntimeReceiptV1;",
            "pub use codex_core::RuntimeReceiptV1;",
        )
        errors = checker.check_native_facade_exports(spoofed)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("RuntimeReceiptV1", errors[0])

    def test_pure_contract_source_changes_trigger_exact_ci(self):
        workflow = (
            Path(__file__).resolve().parents[2] / ".github/workflows/hepta-cell-codex-boundary.yml"
        ).read_text(encoding="utf-8")
        for required in (
            "codex-rs/hepta-types/Cargo.toml",
            "codex-rs/hepta-types/src/**",
            "codex-rs/hepta-codex-adapter/src/execution_contract.rs",
        ):
            self.assertIn(required, workflow)


if __name__ == "__main__":
    unittest.main()
