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



class CargoConfigurationSourceTests(unittest.TestCase):
    """A manifest-pinned Cell dependency must not be rebound through Cargo config."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def add(self, data, sub="codex-rs", basename="config.toml"):
        folder = self.root / sub / ".cargo"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / basename
        target.write_text(data, encoding="utf-8")
        return target

    def test_approved_existing_windows_rustflags(self):
        # Byte/shape-equivalent to the real codex-rs/.cargo/config.toml.
        self.add('''[target.'cfg(all(windows, target_env = "msvc"))']
rustflags = ["-C", "link-arg=/STACK:8388608", "-C", "target-feature=+crt-static"]
[target.aarch64-pc-windows-msvc]
rustflags = ["-C", "link-arg=/STACK:8388608", "-C", "link-arg=/arm64hazardfree"]
[target.'cfg(all(windows, target_env = "gnu"))']
rustflags = ["-C", "link-arg=-Wl,--stack,8388608"]
''')
        self.assertEqual(checker.check_cargo_configuration_sources(self.root), [])

    def test_target_rustflags_cannot_override_reviewed_windows_or_linux_profiles(self):
        for triple, flags, sub in (
            ('x86_64-unknown-linux-gnu', '["-C", "link-arg=-Wl,-rpath,/tmp/rogue"]', 'codex-rs'),
            ('aarch64-pc-windows-msvc', '["-C", "link-arg=/arm64hazardfree"]', 'codex-rs'),
            ('aarch64-pc-windows-msvc', '["-C", "link-arg=/STACK:8388608", "-C", "link-arg=/arm64hazardfree"]', 'codex-rs/hepta-types'),
        ):
            with self.subTest(triple=triple, sub=sub):
                path = self.add(f'[target.{triple}]\nrustflags = {flags}\n', sub=sub)
                self.assertIn('rustflags', str(checker.check_cargo_configuration_sources(self.root)))
                path.unlink()

    def test_unreviewed_build_flags_and_target_redirects_denied(self):
        for entry in ('rustflags = ["--cfg", "bypass_auth"]',
                      'rustdocflags = ["--cfg", "bypass_auth"]',
                      'target = "unexpected-triple"',
                      'target-dir = "/tmp/unreviewed"',
                      'jobs = 1024'):
            with self.subTest(entry=entry):
                self.add('[build]\n' + entry + '\n')
                self.assertIn('[build]', str(checker.check_cargo_configuration_sources(self.root)))

    def test_loader_and_compiler_environment_injection_denied(self):
        for key, value in (('LD_PRELOAD', '/tmp/evil.so'), ('PATH', '/tmp/malware'),
                           ('RUSTUP_TOOLCHAIN', 'nightly'), ('CC', 'malicious-cc')):
            with self.subTest(key=key):
                self.add(f'[env]\n{key} = "{value}"\n')
                self.assertIn(key, str(checker.check_cargo_configuration_sources(self.root)))

    def test_unknown_cargo_execution_and_transport_tables_denied(self):
        configs = (
            '[alias]\ncheck = "!./unreviewed-wrapper"\n',
            '[credential-alias.custom]\nargs = ["/tmp/provider"]\n',
            '[credential]\nprovider = "cargo:token-from-stdout /tmp/provider"\n',
            '[http]\nproxy = "http://proxy.example.invalid"\n',
            '[net]\ngit-fetch-with-cli = true\n',
            '[unstable]\nunstable-options = true\n',
        )
        for config in configs:
            with self.subTest(config=config):
                self.add(config)
                self.assertIn('unreviewed Cargo configuration',
                              str(checker.check_cargo_configuration_sources(self.root)))

    def test_unreviewed_target_fields_denied(self):
        for config in ('[target.x86_64-unknown-linux-gnu]\nar = "/tmp/rogue"\n',
                       '[target.aarch64-pc-windows-msvc]\nunknown = "not-reviewed"\n'):
            with self.subTest(config=config):
                self.add(config)
                self.assertIn('unreviewed target', str(checker.check_cargo_configuration_sources(self.root)))

    def test_source_replacement_rejected(self):
        self.add('''[source.crates-io]
replace-with = "shadow"
[source.shadow]
directory = "/unsafe"
''')
        self.assertIn("[source]", str(checker.check_cargo_configuration_sources(self.root)))

    def test_registry_default_rejected(self):
        self.add('''[registry]
default = "malicious"
''')
        self.assertIn("[registry]", str(checker.check_cargo_configuration_sources(self.root)))

    def test_other_registries_rejected(self):
        self.add('''[registries.shadow]
index = "https://example.invalid/index"
''')
        self.assertIn("[registries]", str(checker.check_cargo_configuration_sources(self.root)))

    def test_root_and_member_configs_rejected(self):
        self.add('[source.crates-io]\nreplace-with = "shadow"\n', sub="")
        self.add('[source.crates-io]\nreplace-with = "shadow"\n',
                 sub="codex-rs/hepta-types", basename="config")
        self.assertEqual(len(checker.check_cargo_configuration_sources(self.root)), 2)

    def test_redirected_cargo_home_rejected(self):
        self.add('''[env]
CARGO_HOME = "/tmp/fake-registry"
''')
        self.assertIn("CARGO_HOME", str(checker.check_cargo_configuration_sources(self.root)))

    def test_tool_wrapper_rejected(self):
        self.add('''[build]
rustc-wrapper = "./tool"
''')
        self.assertIn("rustc-wrapper", str(checker.check_cargo_configuration_sources(self.root)))

    def test_target_runner_rejected(self):
        self.add('''[target.x86_64-unknown-linux-gnu]
runner = "/tmp/shadow"
''')
        self.assertIn("runner", str(checker.check_cargo_configuration_sources(self.root)))

    def test_target_linker_rejected(self):
        self.add('''[target.aarch64-unknown-linux-gnu]
linker = "/tmp/shadow"
''')
        self.assertIn("linker", str(checker.check_cargo_configuration_sources(self.root)))

    def test_invalid_toml_refused(self):
        self.add("[source\n")
        self.assertIn("unreadable Cargo configuration",
                      str(checker.check_cargo_configuration_sources(self.root)))

    def test_symlink_file_refused(self):
        outside = self.root / "outside"
        outside.write_text('''[source.crates-io]
replace-with = "shadow"
''')
        folder = self.root / "codex-rs" / ".cargo"
        folder.mkdir(parents=True)
        (folder / "config.toml").symlink_to(outside)
        self.assertIn("symbolic link",
                      str(checker.check_cargo_configuration_sources(self.root)))

    def test_symlink_dir_refused(self):
        outside = self.root / "outside"
        outside.mkdir()
        inside = self.root / "codex-rs" / "hepta-types"
        inside.mkdir(parents=True)
        (inside / ".cargo").symlink_to(outside, target_is_directory=True)
        self.assertIn("symbolic link",
                      str(checker.check_cargo_configuration_sources(self.root)))

    def test_malformed_target_refused(self):
        self.add('[target]\nx = "non-table"\n')
        self.assertIn("malformed target",
                      str(checker.check_cargo_configuration_sources(self.root)))

    def test_source_config_path_changes_trigger_exact_head_gate(self):
        workflow = (
            Path(__file__).resolve().parents[2] / ".github" /
            "workflows" / "hepta-cell-codex-boundary.yml"
        ).read_text(encoding="utf-8")
        for trigger in ('      - ".cargo/**"', '      - "codex-rs/.cargo/**"',
                        '      - "codex-rs/hepta-*/.cargo/**"'):
            self.assertIn(trigger, workflow)


if __name__ == "__main__":
    unittest.main()
