"""Exercise the real path guard with registered cross-lane schema owners."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "hepta_lane_b_path_guard", SCRIPTS / "hepta-lane-b-path-guard.py"
)
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)


class RegisteredDelegatePathTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.write("codex-rs/Cargo.toml", "[workspace]\n[workspace.dependencies]\n")
        self.write("codex-rs/consumer/Cargo.toml", '[package]\nname = "consumer"\n')
        self.write("codex-rs/consumer/src/lib.rs", "pub fn serve() {}\n")
        self.write("codex-rs/schema/Cargo.toml", '[package]\nname = "schema"\n')
        self.write("codex-rs/schema/src/lib.rs", "pub fn publish() {}\n")
        self.write(
            "codex-rs/foreign/Cargo.toml", '[package]\nname = "physical-owner"\n'
        )
        self.write("codex-rs/foreign/src/lib.rs", "pub fn publish() {}\n")
        self.write(
            "codex-rs/schema-alias/BINDING.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "module": "learning.owner",
                    "declared_root": "codex-rs/schema-alias",
                    "implementation_root": "codex-rs/schema",
                    "binding_mode": "canonical_alias",
                    "duplicate_cargo_package_created": False,
                    "model_authority": False,
                    "provider_authority": False,
                }
            ),
        )
        self.registry = {
            "modules": [
                {
                    "id": "runtime.owner",
                    "rootBindings": [{"path": "codex-rs/consumer"}],
                },
                {
                    "id": "learning.owner",
                    "rootBindings": [{"path": "codex-rs/schema-alias"}],
                },
            ]
        }
        self.delegate = {
            "role": "delegated_callee",
            "ownerModule": "learning.owner",
            "path": "codex-rs/schema/src/lib.rs",
            "symbol": "publish",
            "buildTarget": "schema",
        }
        self.mapping = {
            "module": "runtime.owner",
            "resolvedRoots": ["codex-rs/consumer"],
            "operations": [
                {
                    "ownerEntrypoint": {
                        "role": "owner_entrypoint",
                        "path": "codex-rs/consumer/src/lib.rs",
                        "symbol": "serve",
                        "buildTarget": "consumer",
                    },
                    "delegatedCallees": [self.delegate],
                    "tests": [
                        {
                            "path": "codex-rs/consumer/src/lib.rs",
                            "command": "just test -p consumer",
                        }
                    ],
                }
            ],
        }
        self.write(
            "qualification/lane-b/LANE_B_IMPLEMENTATION_TRUTH.json",
            json.dumps(
                {
                    "modules": [
                        {
                            "module": "runtime.owner",
                            "mapPath": "docs/modules/runtime.owner/IMPLEMENTATION_MAP.json",
                        }
                    ]
                }
            ),
        )

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def verify(self):
        self.write("docs/modules/MODULES.json", json.dumps(self.registry))
        self.write(
            "docs/modules/runtime.owner/IMPLEMENTATION_MAP.json",
            json.dumps(self.mapping),
        )
        with contextlib.redirect_stdout(io.StringIO()):
            return GUARD.verify(self.root)

    def outside_owner(self):
        self.delegate.update(
            path="codex-rs/foreign/src/lib.rs", buildTarget="physical-owner"
        )

    def test_registered_cross_lane_alias_owner_is_accepted(self):
        self.assertEqual(self.verify(), 0)

    def test_unregistered_schema_owner_is_rejected(self):
        self.delegate["ownerModule"] = "unregistered.owner"
        with self.assertRaisesRegex(GUARD.Invalid, "unregistered delegated owner"):
            self.verify()

    def test_foreign_source_without_direct_dependency_is_rejected(self):
        self.outside_owner()
        with self.assertRaisesRegex(GUARD.Invalid, "delegate-root escape"):
            self.verify()

    def test_lane_map_cannot_redeclare_a_foreign_owner_root(self):
        self.mapping["resolvedRoots"] = ["codex-rs/foreign"]
        with self.assertRaisesRegex(GUARD.Invalid, "do not match registered owner"):
            self.verify()

    def test_misbound_alias_is_rejected(self):
        path = self.root / "codex-rs/schema-alias/BINDING.json"
        binding = json.loads(path.read_text())
        binding["module"] = "runtime.owner"
        path.write_text(json.dumps(binding))
        with self.assertRaisesRegex(
            GUARD.Invalid, "alias identity or authority mismatch"
        ):
            self.verify()

    def test_nested_alias_is_rejected(self):
        self.write("codex-rs/schema/BINDING.json", "{}")
        with self.assertRaisesRegex(GUARD.Invalid, "nested source alias"):
            self.verify()

    def test_source_symlink_is_rejected(self):
        link = self.root / "codex-rs/schema/src/link.rs"
        try:
            link.symlink_to(self.root / "codex-rs/foreign/src/lib.rs")
        except OSError as error:
            self.skipTest(str(error))
        self.delegate["path"] = "codex-rs/schema/src/link.rs"
        with self.assertRaisesRegex(GUARD.Invalid, "symlink binding"):
            self.verify()

    def test_registered_root_symlink_is_rejected(self):
        link = self.root / "codex-rs/linked-owner"
        try:
            link.symlink_to(self.root / "codex-rs/schema", target_is_directory=True)
        except OSError as error:
            self.skipTest(str(error))
        self.registry["modules"][1]["rootBindings"][0]["path"] = "codex-rs/linked-owner"
        with self.assertRaisesRegex(GUARD.Invalid, "symlink binding"):
            self.verify()

    def test_path_alias_cannot_escape_into_a_sibling_package(self):
        self.delegate["path"] = "codex-rs/schema/../foreign/src/lib.rs"
        with self.assertRaisesRegex(GUARD.Invalid, "invalid repository-relative path"):
            self.verify()

    def test_named_direct_workspace_dependency_is_accepted(self):
        self.outside_owner()
        self.write(
            "codex-rs/Cargo.toml",
            '[workspace]\n[workspace.dependencies]\nphysical = { path = "foreign" }\n',
        )
        self.write(
            "codex-rs/schema/Cargo.toml",
            '[package]\nname = "schema"\n[dependencies]\nphysical = { workspace = true }\n',
        )
        self.assertEqual(self.verify(), 0)

    def test_direct_dependency_package_name_must_match_build_target(self):
        self.outside_owner()
        self.write(
            "codex-rs/schema/Cargo.toml",
            '[package]\nname = "schema"\n[dependencies]\nphysical = { path = "../foreign" }\n',
        )
        self.delegate["buildTarget"] = "wrong-package"
        with self.assertRaisesRegex(GUARD.Invalid, "delegate-root escape"):
            self.verify()

    def test_direct_dependency_path_cannot_hide_a_symlink(self):
        self.outside_owner()
        link = self.root / "codex-rs/linked-dependency"
        try:
            link.symlink_to(self.root / "codex-rs/foreign", target_is_directory=True)
        except OSError as error:
            self.skipTest(str(error))
        self.write(
            "codex-rs/schema/Cargo.toml",
            '[package]\nname = "schema"\n[dependencies]\nphysical = { path = "../linked-dependency" }\n',
        )
        with self.assertRaisesRegex(GUARD.Invalid, "symlink direct dependency path"):
            self.verify()

    def test_direct_dependency_manifest_cannot_be_a_symlink(self):
        self.outside_owner()
        manifest = self.root / "codex-rs/foreign/Cargo.toml"
        manifest.unlink()
        self.write("codex-rs/package-name.toml", '[package]\nname = "physical-owner"\n')
        try:
            manifest.symlink_to(self.root / "codex-rs/package-name.toml")
        except OSError as error:
            self.skipTest(str(error))
        self.write(
            "codex-rs/schema/Cargo.toml",
            '[package]\nname = "schema"\n[dependencies]\nphysical = { path = "../foreign" }\n',
        )
        with self.assertRaisesRegex(GUARD.Invalid, "symlink binding"):
            self.verify()

    def test_direct_dependency_parent_traversal_stays_inside_the_repository(self):
        self.outside_owner()
        self.write(
            "codex-rs/schema/Cargo.toml",
            '[package]\nname = "schema"\n[dependencies]\nphysical = { path = "../foreign" }\n',
        )
        self.assertEqual(self.verify(), 0)

    def test_absolute_direct_dependency_is_rejected(self):
        self.outside_owner()
        absolute = str(self.root / "codex-rs/foreign")
        self.write(
            "codex-rs/schema/Cargo.toml",
            f'[package]\nname = "schema"\n[dependencies]\nphysical = {{ path = {json.dumps(absolute)} }}\n',
        )
        with self.assertRaisesRegex(GUARD.Invalid, "invalid direct dependency path"):
            self.verify()

    def test_transitive_dependency_does_not_admit_foreign_source(self):
        self.outside_owner()
        self.write(
            "codex-rs/schema/Cargo.toml",
            '[package]\nname = "schema"\n[dependencies]\nmiddle = { path = "../middle" }\n',
        )
        self.write(
            "codex-rs/middle/Cargo.toml",
            '[package]\nname = "middle"\n[dependencies]\nphysical = { path = "../foreign" }\n',
        )
        with self.assertRaisesRegex(GUARD.Invalid, "delegate-root escape"):
            self.verify()

    def test_duplicate_registered_owner_is_rejected(self):
        self.registry["modules"].append(self.registry["modules"][1].copy())
        with self.assertRaisesRegex(GUARD.Invalid, "duplicate registered owner"):
            self.verify()

    def test_invalid_build_target_fails_closed_before_dependency_lookup(self):
        self.outside_owner()
        self.delegate["buildTarget"] = None
        with self.assertRaisesRegex(GUARD.Invalid, "build target"):
            self.verify()


class RealGuardCliTests(unittest.TestCase):
    def test_real_self_test_and_registered_repository_verify(self):
        for command, status in [
            ("self-test", "PASS_HEPTA_LANE_B_CANONICAL_PATH_GUARD_SELF_TEST"),
            ("verify", "PASS_HEPTA_LANE_B_CANONICAL_PATH_GUARD"),
        ]:
            with self.subTest(command=command):
                result = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPTS / "hepta-lane-b-path-guard.py"),
                        command,
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                self.assertEqual(json.loads(result.stdout)["status"], status)


if __name__ == "__main__":
    unittest.main()
