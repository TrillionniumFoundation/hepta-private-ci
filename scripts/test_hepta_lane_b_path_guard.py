"""Canonical Lane B paths retain global delegated ownership and local boundaries."""

import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).with_name("hepta-lane-b-path-guard.py")
SPEC = importlib.util.spec_from_file_location("lane_b_path_guard", SCRIPT)
assert SPEC and SPEC.loader
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)


class LaneBPathGuardTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for directory in ("owned", "foreign", "qualification/lane-b", "docs/modules"):
            (self.root / directory).mkdir(parents=True)
        for path in ("owned/source.rs", "foreign/source.rs"):
            (self.root / path).write_text("pub fn run() {}\n", encoding="utf-8")
        self.registry = {
            "modules": [
                {"id": "lane.b.owner", "rootBindings": [{"path": "owned"}]},
                {"id": "lane.e.delegate", "rootBindings": [{"path": "foreign"}]},
            ]
        }
        self.map = {
            "module": "lane.b.owner",
            "resolvedRoots": ["owned"],
            "operations": [
                {
                    "ownerEntrypoint": {
                        "role": "owner_entrypoint",
                        "path": "owned/source.rs",
                        "symbol": "pub fn run(",
                        "buildTarget": "owner",
                    },
                    "delegatedCallees": [
                        {
                            "role": "delegated_callee",
                            "ownerModule": "lane.e.delegate",
                            "path": "foreign/source.rs",
                            "symbol": "pub fn run(",
                            "buildTarget": "delegate",
                        }
                    ],
                    "tests": [{"path": "owned/source.rs", "command": "fixture check"}],
                }
            ],
        }
        self.write(
            "qualification/lane-b/LANE_B_IMPLEMENTATION_TRUTH.json",
            {"modules": [{"module": "lane.b.owner", "mapPath": "owned/map.json"}]},
        )

    def write(self, path, value):
        (self.root / path).write_text(json.dumps(value), encoding="utf-8")

    def verify(self):
        self.write("docs/modules/MODULES.json", self.registry)
        self.write("owned/map.json", self.map)
        with contextlib.redirect_stdout(io.StringIO()):
            return GUARD.verify(self.root)

    def test_registered_cross_lane_delegate_is_not_a_lane_b_owner(self):
        before = copy.deepcopy(self.map)
        self.assertEqual(self.verify(), 0)
        self.assertEqual(self.map, before)
        self.assertEqual(self.map["resolvedRoots"], ["owned"])
        self.assertEqual(
            self.map["operations"][0]["delegatedCallees"][0]["ownerModule"],
            "lane.e.delegate",
        )

    def test_delegate_cannot_be_relabelled_to_the_caller_or_unknown_owner(self):
        for owner in ("lane.b.owner", "unregistered.owner"):
            with self.subTest(owner=owner):
                self.map["operations"][0]["delegatedCallees"][0]["ownerModule"] = owner
                with self.assertRaises(GUARD.Invalid):
                    self.verify()

    def test_owned_entrypoint_cannot_escape_into_a_registered_delegate(self):
        self.map["operations"][0]["ownerEntrypoint"]["path"] = "foreign/source.rs"
        with self.assertRaisesRegex(GUARD.Invalid, "owner-root escape"):
            self.verify()

    def test_map_cannot_enlarge_its_own_roots(self):
        self.map["resolvedRoots"].append("foreign")
        with self.assertRaisesRegex(GUARD.Invalid, "registered owner roots mismatch"):
            self.verify()

    def test_duplicate_identity_and_ambiguous_roots_fail_closed(self):
        original = copy.deepcopy(self.registry)
        for module in (
            {"id": "lane.e.delegate", "rootBindings": [{"path": "foreign"}]},
            {"id": "another.owner", "rootBindings": [{"path": "foreign"}]},
        ):
            with self.subTest(module=module):
                self.registry = copy.deepcopy(original)
                self.registry["modules"].append(module)
                with self.assertRaisesRegex(GUARD.Invalid, "duplicate|ambiguous"):
                    self.verify()

    def test_alias_root_keeps_the_registered_delegate_identity(self):
        (self.root / "alias").mkdir()
        self.registry["modules"][1]["rootBindings"] = [{"path": "alias"}]
        binding = {
            "schema_version": 1,
            "module": "lane.e.delegate",
            "declared_root": "alias",
            "implementation_root": "foreign",
            "binding_mode": "canonical_alias",
            "duplicate_cargo_package_created": False,
            "model_authority": False,
            "provider_authority": False,
        }
        self.write("alias/BINDING.json", binding)
        self.assertEqual(self.verify(), 0)
        binding["provider_authority"] = True
        self.write("alias/BINDING.json", binding)
        with self.assertRaisesRegex(GUARD.Invalid, "authority mismatch"):
            self.verify()

    def test_two_aliases_cannot_claim_the_same_implementation(self):
        for alias, owner in (
            ("alias-one", "lane.e.delegate"),
            ("alias-two", "other.owner"),
        ):
            (self.root / alias).mkdir()
            self.write(
                f"{alias}/BINDING.json",
                {
                    "schema_version": 1,
                    "module": owner,
                    "declared_root": alias,
                    "implementation_root": "foreign",
                    "binding_mode": "canonical_alias",
                    "duplicate_cargo_package_created": False,
                    "model_authority": False,
                    "provider_authority": False,
                },
            )
        self.registry["modules"][1]["rootBindings"] = [{"path": "alias-one"}]
        self.registry["modules"].append(
            {"id": "other.owner", "rootBindings": [{"path": "alias-two"}]}
        )
        with self.assertRaisesRegex(GUARD.Invalid, "ambiguous registered source root"):
            self.verify()

    def test_repository_guard_accepts_actual_registered_cross_lane_delegates(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(GUARD.verify(), 0)


if __name__ == "__main__":
    unittest.main()
