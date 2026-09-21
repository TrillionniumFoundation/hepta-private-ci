"""Manifest preflight reads only the actual local Cargo dependency graph."""

import tempfile
import unittest
from pathlib import Path

from hepta_workspace import verify_workspace


class WorkspacePreflightTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.write(
            "Cargo.toml",
            '[workspace]\nmembers = ["app"]\n[workspace.package]\nversion = "1.0.0"\n',
        )
        self.write(
            "app/Cargo.toml", '[package]\nname = "app"\nversion.workspace = true\n'
        )

    def write(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def test_valid_graph_ignores_unreferenced_broken_fixture_workspaces(self):
        self.write("app/tests/fixtures/broken/Cargo.toml", "not TOML")
        self.assertEqual(verify_workspace(self.root), (1, []))

    def test_missing_workspace_inheritance_is_reported_before_build(self):
        with (self.root / "app/Cargo.toml").open("a") as stream:
            stream.write("[dependencies]\nmissing.workspace = true\n")
        count, errors = verify_workspace(self.root)
        self.assertEqual(count, 1)
        self.assertTrue(
            any("workspace.dependencies.missing" in error for error in errors)
        )

    def test_workspace_paths_are_relative_to_workspace_not_member(self):
        with (self.root / "Cargo.toml").open("a") as stream:
            stream.write(
                '[workspace.dependencies]\nalias = { path = "helper", package = "real" }\n'
            )
        with (self.root / "app/Cargo.toml").open("a") as stream:
            stream.write(
                "[target.'cfg(unix)'.build-dependencies]\nalias.workspace = true\n"
            )
        self.write("helper/Cargo.toml", '[package]\nname = "real"\n')
        self.assertEqual(verify_workspace(self.root), (2, []))

    def test_local_transitive_dev_dependencies_are_checked(self):
        with (self.root / "app/Cargo.toml").open("a") as stream:
            stream.write('[dev-dependencies]\nhelper = { path = "../helper" }\n')
        self.write(
            "helper/Cargo.toml",
            '[package]\nname = "helper"\n[dependencies]\nmissing.workspace = true\n',
        )
        self.assertTrue(
            any(
                "workspace.dependencies.missing" in error
                for error in verify_workspace(self.root)[1]
            )
        )

    def test_wrong_package_name_and_missing_local_path_are_errors(self):
        with (self.root / "app/Cargo.toml").open("a") as stream:
            stream.write(
                '[dependencies]\nhelper = { path = "../helper" }\nabsent = { path = "../absent" }\n'
            )
        self.write("helper/Cargo.toml", '[package]\nname = "wrong"\n')
        errors = verify_workspace(self.root)[1]
        self.assertTrue(any("expects helper" in error for error in errors))
        self.assertTrue(any("absent/Cargo.toml" in error for error in errors))

    def test_path_cycle_is_bounded(self):
        with (self.root / "app/Cargo.toml").open("a") as stream:
            stream.write('[dev-dependencies]\nhelper = { path = "../helper" }\n')
        self.write(
            "helper/Cargo.toml",
            '[package]\nname = "helper"\n[dev-dependencies]\napp = { path = "../app" }\n',
        )
        self.assertEqual(verify_workspace(self.root), (2, []))

    def test_unmatched_member_and_missing_inherited_package_field_fail(self):
        self.write("Cargo.toml", '[workspace]\nmembers = ["app", "missing"]\n')
        errors = verify_workspace(self.root)[1]
        self.assertTrue(any("member not found" in error for error in errors))
        self.assertTrue(any("workspace.package.version" in error for error in errors))

    def test_execution_core_rejects_direct_product_dependency(self):
        for name in ("codex-core", "codex-extension-api"):
            for kind in (
                "dependencies",
                "build-dependencies",
                "target.'cfg(unix)'.dependencies",
            ):
                with self.subTest(name=name, kind=kind):
                    self.write(
                        "app/Cargo.toml",
                        f'[package]\nname = "{name}"\n[{kind}]\ncodex-hepta-memory = "0.0.0"\n',
                    )
                    errors = verify_workspace(self.root)[1]
                    self.assertTrue(
                        any("execution boundary" in error for error in errors)
                    )

    def test_execution_core_rejects_inherited_renamed_product_dependency(self):
        with (self.root / "Cargo.toml").open("a") as stream:
            stream.write(
                '[workspace.dependencies]\ninnocent = { package = "codex-hepta-memory", path = "memory" }\n'
            )
        self.write("memory/Cargo.toml", '[package]\nname = "codex-hepta-memory"\n')
        self.write(
            "app/Cargo.toml",
            '[package]\nname = "codex-core"\n[dependencies]\ninnocent.workspace = true\n',
        )
        errors = verify_workspace(self.root)[1]
        self.assertTrue(any("execution boundary" in error for error in errors))

    def test_test_only_fixture_dependency_does_not_widen_product_graph(self):
        self.write(
            "app/Cargo.toml",
            '[package]\nname = "codex-core"\n[dev-dependencies]\ncodex-hepta-memory = "0.0.0"\n',
        )
        self.assertEqual(verify_workspace(self.root), (1, []))

    def test_host_composition_can_depend_on_product_implementations(self):
        self.write(
            "app/Cargo.toml",
            '[package]\nname = "codex-hepta-agentd"\n[dependencies]\ncodex-hepta-memory = "0.0.0"\n',
        )
        self.assertEqual(verify_workspace(self.root), (1, []))

    def test_invalid_dependency_package_name_fails_without_execution(self):
        self.write(
            "app/Cargo.toml",
            '[package]\nname = "codex-core"\n[dependencies]\nwrong = { package = 3, version = "0.0.0" }\n',
        )
        self.assertTrue(
            any(
                "invalid package name" in error
                for error in verify_workspace(self.root)[1]
            )
        )

    def helper_chain(self, root_kind="dependencies", helper_kind="dependencies"):
        self.write(
            "app/Cargo.toml",
            f'[package]\nname = "codex-core"\n[{root_kind}]\nhelper = {{ path = "../helper" }}\n',
        )
        self.write(
            "helper/Cargo.toml",
            f'[package]\nname = "helper"\n[{helper_kind}]\n'
            'renamed = { package = "codex-hepta-memory", path = "../memory", optional = true }\n',
        )
        self.write("memory/Cargo.toml", '[package]\nname = "codex-hepta-memory"\n')

    def test_transitive_product_dependency_reports_the_route(self):
        self.helper_chain()
        count, errors = verify_workspace(self.root)
        self.assertEqual(count, 3)
        self.assertEqual(len(errors), 1)
        self.assertIn(
            "codex-core --dependencies--> helper --dependencies--> codex-hepta-memory",
            errors[0],
        )

    def test_transitive_build_and_target_optional_edges_are_not_loopholes(self):
        for root_kind in ("dependencies", "build-dependencies", "target.'cfg(windows)'.dependencies"):
            for helper_kind in ("dependencies", "build-dependencies", "target.'cfg(unix)'.build-dependencies"):
                with self.subTest(root_kind=root_kind, helper_kind=helper_kind):
                    self.helper_chain(root_kind, helper_kind)
                    self.assertTrue(any("execution boundary" in e for e in verify_workspace(self.root)[1]))

    def test_transitive_test_only_edges_do_not_contaminate_shipped_graph(self):
        for root_kind, helper_kind in (("dev-dependencies", "dependencies"), ("dependencies", "dev-dependencies")):
            with self.subTest(root_kind=root_kind, helper_kind=helper_kind):
                self.helper_chain(root_kind, helper_kind)
                self.assertEqual(verify_workspace(self.root), (3, []))

    def test_inherited_transitive_alias_resolves_from_workspace(self):
        self.helper_chain()
        with (self.root / "Cargo.toml").open("a") as stream:
            stream.write('[workspace.dependencies]\nalias = { package = "codex-hepta-memory", path = "memory" }\n')
        self.write("helper/Cargo.toml", '[package]\nname = "helper"\n[dependencies]\nalias.workspace = true\n')
        self.assertTrue(any("execution boundary" in e for e in verify_workspace(self.root)[1]))

    def test_local_patch_cannot_hide_a_transitive_product_edge(self):
        self.helper_chain()
        self.write("app/Cargo.toml", '[package]\nname = "codex-core"\n[dependencies]\nhelper = "1.0"\n')
        with (self.root / "Cargo.toml").open("a") as stream:
            stream.write('[patch.crates-io]\nhelper = { path = "helper" }\n')
        self.assertTrue(any("helper --dependencies--> codex-hepta-memory" in e for e in verify_workspace(self.root)[1]))

    def test_patch_rename_and_wrong_package_identity_are_checked(self):
        self.helper_chain()
        self.write("app/Cargo.toml", '[package]\nname = "codex-extension-api"\n[dependencies]\nhelper = "1.0"\n')
        with (self.root / "Cargo.toml").open("a") as stream:
            stream.write('[patch.crates-io]\ninnocent = { package = "helper", path = "helper" }\n')
        self.assertTrue(any("execution boundary" in e for e in verify_workspace(self.root)[1]))
        self.write("helper/Cargo.toml", '[package]\nname = "different"\n')
        self.assertTrue(any("must name helper" in e for e in verify_workspace(self.root)[1]))

    def test_patch_used_only_in_tests_does_not_widen_boundary(self):
        self.helper_chain()
        self.write("app/Cargo.toml", '[package]\nname = "codex-core"\n[dev-dependencies]\nhelper = "1.0"\n')
        with (self.root / "Cargo.toml").open("a") as stream:
            stream.write('[patch.crates-io]\nhelper = { path = "helper" }\n')
        self.assertEqual(verify_workspace(self.root), (3, []))

    def test_runtime_cycle_has_a_finite_deterministic_diagnostic(self):
        self.helper_chain()
        with (self.root / "helper/Cargo.toml").open("a") as stream:
            stream.write('codex-core = { path = "../app" }\n')
        result = verify_workspace(self.root)
        self.assertEqual(len(result[1]), 1)
        self.assertEqual(result, verify_workspace(self.root))

    def test_transitive_secret_product_name_is_also_blocked(self):
        self.helper_chain()
        self.write("helper/Cargo.toml", '[package]\nname = "helper"\n[dependencies]\ncodex-heptabao = "1.0"\n')
        self.assertTrue(any("codex-heptabao" in e for e in verify_workspace(self.root)[1]))

    def test_shared_helper_is_checked_for_each_execution_boundary(self):
        self.helper_chain()
        self.write("Cargo.toml", '[workspace]\nmembers = ["app", "extension"]\n')
        self.write("extension/Cargo.toml", '[package]\nname = "codex-extension-api"\n[dependencies]\nhelper = { path = "../helper" }\n')
        errors = verify_workspace(self.root)[1]
        self.assertEqual(len(errors), 2)
        self.assertTrue(any("codex-core --" in e for e in errors))
        self.assertTrue(any("codex-extension-api --" in e for e in errors))

    def test_shared_kernel_contracts_are_not_product_implementations(self):
        self.write("app/Cargo.toml", '[package]\nname = "codex-core"\n[dependencies]\ncodex-hepta-contracts = { path = "../contracts" }\n')
        self.write("contracts/Cargo.toml", '[package]\nname = "codex-hepta-contracts"\n')
        self.assertEqual(verify_workspace(self.root), (2, []))

    def test_shared_contracts_cannot_hide_product_implementation(self):
        self.test_shared_kernel_contracts_are_not_product_implementations()
        with (self.root / "contracts/Cargo.toml").open("a") as stream:
            stream.write('[dependencies]\ncodex-hepta-memory = "1.0"\n')
        self.assertTrue(any("codex-hepta-contracts --dependencies--> codex-hepta-memory" in e for e in verify_workspace(self.root)[1]))

    def test_malformed_manifest_is_reported_without_execution(self):
        self.write("app/Cargo.toml", "this is not valid = TOML")
        self.assertTrue(verify_workspace(self.root)[1])


if __name__ == "__main__":
    unittest.main()
