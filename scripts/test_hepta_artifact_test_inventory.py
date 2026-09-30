"""Negative and positive tests for the machine-derived Cargo target inventory."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import hepta_artifact_test_inventory as inventory


def metadata() -> dict:
    return {
        "version": 1,
        "packages": [
            {
                "name": inventory.DEFAULT_PACKAGE,
                "id": "path+file:///repo/codex-rs/hepta-learning-artifacts#0.0.0",
                "manifest_path": "/repo/codex-rs/hepta-learning-artifacts/Cargo.toml",
                "targets": [
                    {
                        "name": "codex_hepta_learning_artifacts",
                        "kind": ["lib"],
                        "crate_types": ["lib"],
                        "required-features": [],
                        "src_path": "/repo/codex-rs/hepta-learning-artifacts/src/lib.rs",
                        "edition": "2024",
                        "test": True,
                        "doctest": False,
                        "doc": True,
                    },
                    {
                        "name": "artifact_store_conformance_proptests",
                        "kind": ["test"],
                        "crate_types": ["bin"],
                        "required-features": [],
                        "src_path": "/repo/codex-rs/hepta-learning-artifacts/tests/artifact_store_conformance_proptests.rs",
                        "edition": "2024",
                        "test": True,
                        "doctest": False,
                        "doc": False,
                    },
                ],
            }
        ],
    }


class CargoTargetInventoryTests(unittest.TestCase):
    def test_inventory_is_machine_derived_and_canonical(self):
        result = inventory.inventory_from_metadata(metadata(), inventory.DEFAULT_PACKAGE)
        self.assertEqual(result["targetCount"], 2)
        self.assertEqual(result["testCapableTargetCount"], 2)
        self.assertIn("artifact_store_conformance_proptests", {row["name"] for row in result["targets"]})
        self.assertEqual(inventory.canonical(result), inventory.canonical(json.loads(inventory.canonical(result))))

    def test_historical_stale_target_is_rejected_when_declared(self):
        with self.assertRaisesRegex(ValueError, "required Cargo targets are missing"):
            inventory.inventory_from_metadata(
                metadata(), inventory.DEFAULT_PACKAGE, ("artifact_store_conformance",)
            )

    def test_missing_or_duplicate_package_is_rejected(self):
        for change in ("missing", "duplicate"):
            value = metadata()
            if change == "missing":
                value["packages"] = []
            else:
                value["packages"].append(copy.deepcopy(value["packages"][0]))
            with self.subTest(change=change), self.assertRaises(ValueError):
                inventory.inventory_from_metadata(value, inventory.DEFAULT_PACKAGE)

    def test_missing_library_or_test_capability_is_rejected(self):
        for change in ("library", "tests"):
            value = metadata()
            if change == "library":
                value["packages"][0]["targets"][0]["kind"] = ["bin"]
            else:
                for target in value["packages"][0]["targets"]:
                    target["test"] = False
            with self.subTest(change=change), self.assertRaises(ValueError):
                inventory.inventory_from_metadata(value, inventory.DEFAULT_PACKAGE)

    def test_duplicate_target_and_non_boolean_capability_are_rejected(self):
        value = metadata()
        value["packages"][0]["targets"].append(copy.deepcopy(value["packages"][0]["targets"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate Cargo target"):
            inventory.inventory_from_metadata(value, inventory.DEFAULT_PACKAGE)
        value = metadata()
        value["packages"][0]["targets"][0]["test"] = 1
        with self.assertRaisesRegex(ValueError, "boolean capability"):
            inventory.inventory_from_metadata(value, inventory.DEFAULT_PACKAGE)

    def test_duplicate_json_fields_and_nonfinite_values_are_rejected(self):
        for value in ('{"version":1,"version":1}', '{"version":NaN}'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                inventory.strict_json(value)

    def test_existing_output_is_never_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "inventory.json"
            output.write_text("stale")
            with mock.patch.object(inventory, "cargo_metadata", return_value=metadata()), mock.patch(
                "sys.argv", ["inventory", "--out", str(output)]
            ):
                self.assertEqual(inventory.main(), 1)
            self.assertEqual(output.read_text(), "stale")


if __name__ == "__main__":
    unittest.main()
