"""Catch Cargo inheritance failures before a resolver or build script runs."""

import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from hepta_workspace import verify_workspace


class WorkspaceInheritanceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.workspace()
        self.package()
        self.write("app/src/lib.rs", "pub fn answer() -> u8 { 42 }\n")

    def write(self, path, text):
        destination = self.root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")

    def workspace(self, extra=""):
        self.write("Cargo.toml", '[workspace]\nmembers = ["app"]\n' + extra)

    def package(self, edition='edition = "2024"', extra=""):
        self.write(
            "app/Cargo.toml",
            '[package]\nname = "app"\nversion = "1.0.0"\n' + edition + "\n" + extra,
        )

    def errors(self):
        return verify_workspace(self.root)[1]

    def test_2024_rejects_ineffective_default_features_for_every_dependency_kind(self):
        for kind in (
            "dependencies",
            "build-dependencies",
            "dev-dependencies",
            "target.'cfg(unix)'.dependencies",
            "target.'cfg(windows)'.build-dependencies",
            "target.'cfg(unix)'.dev-dependencies",
        ):
            for inherited in (
                '"1"',
                '{ version = "1" }',
                '{ version = "1", default-features = true }',
            ):
                with self.subTest(kind=kind, inherited=inherited):
                    self.workspace(
                        "[workspace.dependencies]\nhelper = " + inherited + "\n"
                    )
                    self.package(
                        extra=f"[{kind}]\nhelper = {{ workspace = true, default-features = false }}\n"
                    )
                    errors = self.errors()
                    self.assertEqual(len(errors), 1, errors)
                    self.assertIn("default-features", errors[0])
                    self.assertIn("workspace.dependencies.helper", errors[0])

    def test_inherited_edition_uses_the_workspace_edition(self):
        self.workspace(
            '[workspace.package]\nedition = "2024"\n[workspace.dependencies]\nhelper = "1"\n'
        )
        self.package(
            "edition.workspace = true",
            "[dependencies]\nhelper = { workspace = true, default-features = false }\n",
        )
        self.assertTrue(any("default-features" in error for error in self.errors()))

    def test_pre_2024_warning_is_not_upgraded_to_an_error(self):
        self.workspace(
            '[workspace.package]\nedition = "2024"\n[workspace.dependencies]\nhelper = "1"\n'
        )
        for edition in ('edition = "2015"', 'edition = "2018"', 'edition = "2021"', ""):
            with self.subTest(edition=edition):
                self.package(
                    edition,
                    "[dependencies]\nhelper = { workspace = true, default-features = false }\n",
                )
                self.assertEqual(self.errors(), [])

    def test_workspace_disabled_defaults_permit_member_selection(self):
        self.workspace(
            '[workspace.dependencies]\nhelper = { version = "1", default-features = false }\n'
        )
        for flags in ("", ", default-features = false", ", default-features = true"):
            with self.subTest(flags=flags):
                self.package(
                    extra=f"[dependencies]\nhelper = {{ workspace = true{flags} }}\n"
                )
                self.assertEqual(self.errors(), [])

    def test_renamed_dependency_uses_the_inherited_alias(self):
        self.workspace(
            '[workspace.dependencies]\nalias = { version = "1", package = "helper" }\n'
        )
        self.package(
            extra="[dependencies]\nalias = { workspace = true, default-features = false }\n"
        )
        self.assertTrue(
            any("workspace.dependencies.alias" in error for error in self.errors())
        )

    def test_noninherited_dependency_may_disable_defaults(self):
        self.package(
            extra='[dependencies]\nhelper = { version = "1", default-features = false }\n'
        )
        self.assertEqual(self.errors(), [])

    def test_missing_dependency_is_not_reported_as_a_feature_error(self):
        self.package(
            extra="[dependencies]\nhelper = { workspace = true, default-features = false }\n"
        )
        errors = self.errors()
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("workspace.dependencies.helper is missing", errors[0])

    def test_workspace_optional_dependency_is_rejected_even_when_unused(self):
        self.workspace(
            '[workspace.dependencies]\nhelper = { version = "1", optional = true }\n'
        )
        self.assertTrue(
            any(
                "workspace.dependencies.helper" in error and "optional" in error
                for error in self.errors()
            )
        )

    def test_member_optional_and_additive_features_remain_valid(self):
        self.workspace(
            '[workspace.dependencies]\nhelper = { version = "1", optional = false, features = ["a"] }\n'
        )
        self.package(
            extra='[dependencies]\nhelper = { workspace = true, optional = true, features = ["b"] }\n'
        )
        self.assertEqual(self.errors(), [])

    def test_missing_workspace_lints_is_reported(self):
        self.package(extra="[lints]\nworkspace = true\n")
        self.assertTrue(
            any("workspace.lints is missing" in error for error in self.errors())
        )

    def test_empty_or_populated_workspace_lints_can_be_inherited(self):
        for lints in (
            "[workspace.lints]\n",
            '[workspace.lints.rust]\nunsafe_code = "forbid"\n',
        ):
            with self.subTest(lints=lints):
                self.workspace(lints)
                self.package(extra="[lints]\nworkspace = true\n")
                self.assertEqual(self.errors(), [])

    def test_member_lints_cannot_override_inherited_lints(self):
        self.workspace('[workspace.lints.rust]\nunsafe_code = "forbid"\n')
        self.package(
            extra='[lints]\nworkspace = true\n[lints.rust]\nunsafe_code = "allow"\n'
        )
        self.assertTrue(
            any("cannot override workspace.lints" in error for error in self.errors())
        )

    def test_local_lints_without_inheritance_do_not_need_a_workspace_table(self):
        self.package(extra='[lints.rust]\nunsafe_code = "forbid"\n')
        self.assertEqual(self.errors(), [])

    def test_bad_inheritance_in_unreachable_fixture_is_not_a_global_gate(self):
        self.write(
            "app/tests/fixture/Cargo.toml",
            '[package]\nname = "fixture"\nedition.workspace = true\n[lints]\nworkspace = true\n',
        )
        self.assertEqual(self.errors(), [])

    def test_failure_is_read_only_and_does_not_execute_build_scripts(self):
        self.package(
            extra="[dependencies]\nhelper = { workspace = true }\n[lints]\nworkspace = true\n"
        )
        self.write(
            "app/build.rs",
            'compile_error!("the structural preflight must not execute me");\n',
        )

        def inventory():
            return {
                str(path.relative_to(self.root)): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                for path in self.root.rglob("*")
                if path.is_file()
            }

        before = inventory()
        command = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).with_name("hepta_workspace.py")),
                "--workspace",
                str(self.root),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(command.returncode, 1)
        self.assertIn("workspace.lints is missing", command.stderr)
        self.assertNotIn("Traceback", command.stderr)
        self.assertIn("no code executed", command.stdout)
        self.assertEqual(before, inventory())


if __name__ == "__main__":
    unittest.main()
