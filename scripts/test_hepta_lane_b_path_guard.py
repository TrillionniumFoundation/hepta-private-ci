from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("hepta-lane-b-path-guard.py")
SPEC = importlib.util.spec_from_file_location("hepta_lane_b_path_guard", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CrossLaneOwnerTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for name in ("owned", "foreign"):
            (self.root / name).mkdir()
            (self.root / name / "source.rs").write_text("pub fn run() {}\n")
        self.registry_path = self.root / "docs/modules/SOURCE_BINDINGS.json"
        self.registry_path.parent.mkdir(parents=True)
        self.binding = {"module": "learning.ledger", "declaredRoots": ["foreign"]}
        self.anchor = {
            "role": "delegated_callee",
            "ownerModule": "learning.ledger",
            "path": "foreign/source.rs",
            "symbol": "pub fn run(",
            "buildTarget": "fixture",
        }
        self.write_registry([self.binding])

    def write_registry(self, bindings: list[dict[str, object]]) -> None:
        self.registry_path.write_text(
            json.dumps(
                {
                    "schema": "hepta.module-source-binding.v2",
                    "schemaVersion": 2,
                    "bindings": bindings,
                }
            )
        )

    def verify(self) -> None:
        MODULE.verify_anchor(
            self.root,
            "runtime.agentd",
            {"runtime.agentd": ["owned"]},
            self.anchor,
            owner=False,
        )

    def test_declared_cross_lane_owner_is_accepted(self) -> None:
        self.verify()

    def test_unknown_owner_is_rejected(self) -> None:
        self.anchor["ownerModule"] = "unknown.owner"
        with self.assertRaisesRegex(MODULE.Invalid, "unknown or ambiguous"):
            self.verify()

    def test_duplicate_owner_is_rejected(self) -> None:
        self.write_registry([self.binding, self.binding])
        with self.assertRaisesRegex(MODULE.Invalid, "unknown or ambiguous"):
            self.verify()

    def test_evidence_root_does_not_transfer_ownership(self) -> None:
        self.binding.update(declaredRoots=["owned"], sourceEvidenceRoots=["foreign"])
        self.write_registry([self.binding])
        with self.assertRaisesRegex(MODULE.Invalid, "delegate-root escape"):
            self.verify()

    def test_noncanonical_declared_roots_are_rejected(self) -> None:
        for path in (".", "../foreign", "foreign/../owned", "/tmp"):
            with self.subTest(path=path):
                self.binding["declaredRoots"] = [path]
                self.write_registry([self.binding])
                with self.assertRaises(MODULE.Invalid):
                    self.verify()

    def test_source_cannot_escape_declared_owner(self) -> None:
        self.anchor["path"] = "owned/source.rs"
        with self.assertRaisesRegex(MODULE.Invalid, "delegate-root escape"):
            self.verify()

    def test_symlink_owner_root_is_rejected(self) -> None:
        try:
            (self.root / "linked").symlink_to(
                self.root / "foreign", target_is_directory=True
            )
        except OSError:
            self.skipTest("symlinks are unavailable")
        self.binding["declaredRoots"] = ["linked"]
        self.write_registry([self.binding])
        with self.assertRaisesRegex(MODULE.Invalid, "symlink binding"):
            self.verify()

    def test_unknown_registry_schema_is_rejected(self) -> None:
        value = json.loads(self.registry_path.read_text())
        value["schemaVersion"] = 99
        self.registry_path.write_text(json.dumps(value))
        with self.assertRaisesRegex(MODULE.Invalid, "source binding schema"):
            self.verify()
