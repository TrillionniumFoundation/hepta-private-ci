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

    def test_malformed_manifest_is_reported_without_execution(self):
        self.write("app/Cargo.toml", "this is not valid = TOML")
        self.assertTrue(verify_workspace(self.root)[1])


if __name__ == "__main__":
    unittest.main()
