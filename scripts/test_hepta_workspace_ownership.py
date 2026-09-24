"""Regression coverage for the actual workspace owner of local dependencies."""

import tempfile
import unittest
from pathlib import Path

from hepta_workspace import verify_workspace


class WorkspaceOwnershipTests(unittest.TestCase):
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

    def test_nested_workspace_uses_its_own_inheritance(self):
        with (self.root / "app/Cargo.toml").open("a") as stream:
            stream.write('[dependencies]\nhelper = { path = "../nested/helper" }\n')
        self.write(
            "nested/Cargo.toml",
            '[workspace]\nmembers = ["helper"]\n[workspace.package]\nversion = "2.0.0"\n[workspace.dependencies]\nleaf = { path = "leaf" }\n',
        )
        self.write(
            "nested/helper/Cargo.toml",
            '[package]\nname = "helper"\nversion.workspace = true\n[dependencies]\nleaf.workspace = true\n',
        )
        self.write(
            "nested/leaf/Cargo.toml",
            '[package]\nname = "leaf"\nversion.workspace = true\n',
        )
        self.assertEqual(verify_workspace(self.root), (3, []))

    def test_nested_workspace_cannot_borrow_parent_package_fields(self):
        with (self.root / "app/Cargo.toml").open("a") as stream:
            stream.write('[dependencies]\nhelper = { path = "../nested/helper" }\n')
        self.write("nested/Cargo.toml", '[workspace]\nmembers = ["helper"]\n')
        self.write(
            "nested/helper/Cargo.toml",
            '[package]\nname = "helper"\nversion.workspace = true\n',
        )
        errors = verify_workspace(self.root)[1]
        self.assertTrue(
            any("workspace.package.version is missing" in error for error in errors)
        )

    def test_explicit_workspace_path_is_relative_to_package(self):
        self.write(
            "app/Cargo.toml",
            '[package]\nname = "app"\nworkspace = ".."\nversion.workspace = true\n',
        )
        self.assertEqual(verify_workspace(self.root), (1, []))

    def test_explicit_missing_workspace_fails(self):
        self.write(
            "app/Cargo.toml",
            '[package]\nname = "app"\nworkspace = "../absent"\nversion.workspace = true\n',
        )
        self.assertTrue(
            any(
                "package.workspace has no" in error
                for error in verify_workspace(self.root)[1]
            )
        )

    def test_excluded_dependency_cannot_inherit_parent_workspace(self):
        with (self.root / "app/Cargo.toml").open("a") as stream:
            stream.write('[dependencies]\nhelper = { path = "../helper" }\n')
        self.write(
            "Cargo.toml",
            '[workspace]\nmembers = ["app"]\nexclude = ["helper"]\n[workspace.package]\nversion = "1.0.0"\n',
        )
        self.write(
            "helper/Cargo.toml",
            '[package]\nname = "helper"\nversion.workspace = true\n',
        )
        self.assertTrue(
            any(
                "workspace.package.version is missing" in error
                for error in verify_workspace(self.root)[1]
            )
        )

    def test_preflight_never_mutates_manifests(self):
        before = {path: path.read_bytes() for path in self.root.rglob("Cargo.toml")}
        self.assertEqual(verify_workspace(self.root), (1, []))
        self.assertEqual(
            before, {path: path.read_bytes() for path in self.root.rglob("Cargo.toml")}
        )


if __name__ == "__main__":
    unittest.main()
