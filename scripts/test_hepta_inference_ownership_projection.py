from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "inference_ownership",
    Path(__file__).with_name("hepta-inference-control-ownership.py"),
)
assert SPEC and SPEC.loader
OWN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OWN)


class OwnershipProjectionTests(unittest.TestCase):
    def test_real_registries_are_idempotent_and_worker_is_not_control_owned(self):
        for path in OWN.FILES:
            with self.subTest(path=path.name):
                original = OWN.load(path)
                projected, changed = OWN.transform(original, path.name)
                self.assertEqual(projected, original)
                self.assertEqual(changed, 0)

    def test_legacy_duplicate_is_removed_without_losing_caller_evidence(self):
        path = OWN.ROOT / "docs/modules/MODULES.json"
        value = OWN.load(path)
        control = next(
            row for row in value["modules"] if row["id"] == "inference.control"
        )
        control["rootBindings"].append({"path": OWN.WORKER, "mode": "exclusive"})
        before = copy.deepcopy(value)
        result, changes = OWN.transform(value, path.name)
        self.assertEqual(value, before)
        row = next(row for row in result["modules"] if row["id"] == "inference.control")
        self.assertNotIn(OWN.WORKER, [root["path"] for root in row["rootBindings"]])
        self.assertIn(OWN.WORKER, row["sourceEvidenceRoots"])
        self.assertEqual(changes, 1)

    def test_ambiguous_root_modes_and_duplicates_are_rejected(self):
        original = OWN.load(OWN.ROOT / "docs/modules/MODULES.json")
        for mode in ("shared", "exclusive"):
            value = copy.deepcopy(original)
            control = next(
                row for row in value["modules"] if row["id"] == "inference.control"
            )
            if mode == "shared":
                control["rootBindings"][0]["mode"] = mode
            else:
                control["rootBindings"].append(
                    copy.deepcopy(control["rootBindings"][0])
                )
            with self.assertRaisesRegex(ValueError, "root bindings"):
                OWN.transform(value, "MODULES.json")

    def test_source_binding_third_owner_cannot_claim_worker(self):
        for field in ("declaredRoots", "existingDeclaredRoots"):
            value = OWN.load(OWN.ROOT / "docs/modules/SOURCE_BINDINGS.json")
            third = next(
                row for row in value["bindings"] if row["module"] == "platform.types"
            )
            third[field].append(OWN.WORKER)
            with self.assertRaisesRegex(ValueError, "another module"):
                OWN.transform(value, "SOURCE_BINDINGS.json")

    def test_nonobject_registry_rows_fail_intentionally(self):
        for path in OWN.FILES:
            value = OWN.load(path)
            key = {
                "MODULES.json": "modules",
                "SOURCE_BINDINGS.json": "bindings",
                "CARGO_BINDINGS.json": "bindings",
                "PATH_OWNERSHIP.json": "moduleNamespaces",
            }[path.name]
            value[key].append("unknown row")
            with self.assertRaisesRegex(ValueError, "invalid"):
                OWN.transform(value, path.name)

    def test_cargo_owner_conflict_is_not_silently_reassigned(self):
        value = OWN.load(OWN.ROOT / "docs/modules/CARGO_BINDINGS.json")
        row = next(row for row in value["bindings"] if row["packagePath"] == OWN.WORKER)
        row["module"] = "inference.control"
        with self.assertRaisesRegex(ValueError, "registered owner"):
            OWN.transform(value, "CARGO_BINDINGS.json")

    def test_unknown_schema_and_duplicate_owner_fail_closed(self):
        value = OWN.load(OWN.ROOT / "docs/modules/MODULES.json")
        unknown = copy.deepcopy(value)
        unknown["schema"] = "future"
        with self.assertRaisesRegex(ValueError, "schema"):
            OWN.transform(unknown, "MODULES.json")
        value["modules"].append(
            copy.deepcopy(
                next(row for row in value["modules"] if row["id"] == "inference.worker")
            )
        )
        with self.assertRaisesRegex(ValueError, "duplicated owner"):
            OWN.transform(value, "MODULES.json")


if __name__ == "__main__":
    unittest.main()
