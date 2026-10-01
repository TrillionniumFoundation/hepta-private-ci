"""Canonical Lane A order must preserve exact, unique module membership."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lane_a_foundation_core as lane_a


class LaneARegistryOrderTests(unittest.TestCase):
    def setUp(self):
        self.matrix = lane_a.read_json(lane_a.MATRIX_PATH)
        self.registry = lane_a.read_json(lane_a.ROOT / "docs/modules/MODULES.json")

    def test_truth_projection_matches_registered_order(self):
        lane_a.validate_module_order(self.matrix["modules"])
        expected = [
            row["id"]
            for row in self.registry["modules"]
            if row["id"] in lane_a.EXPECTED_MODULES
        ]
        self.assertEqual([row["module"] for row in self.matrix["modules"]], expected)

    def test_missing_extra_duplicate_reordered_and_malformed_rows_fail(self):
        for mutation in ("missing", "extra", "duplicate", "reordered", "malformed"):
            rows = copy.deepcopy(self.matrix["modules"])
            if mutation == "missing":
                rows.pop()
            elif mutation == "extra":
                rows.append({"module": "runtime.agentd"})
            elif mutation == "duplicate":
                rows.append(copy.deepcopy(rows[-1]))
            elif mutation == "reordered":
                rows[-2], rows[-1] = rows[-1], rows[-2]
            else:
                rows.append(None)
            with (
                self.subTest(mutation=mutation),
                self.assertRaises(lane_a.VerificationError),
            ):
                lane_a.validate_module_order(rows)

    def test_canonical_registry_must_be_versioned_unique_and_complete(self):
        for mutation in ("version", "duplicate", "missing", "reordered"):
            registry = copy.deepcopy(self.registry)
            if mutation == "version":
                registry["schemaVersion"] = 8
            elif mutation == "duplicate":
                registry["modules"].append(copy.deepcopy(registry["modules"][0]))
            elif mutation == "missing":
                registry["modules"] = [
                    row for row in registry["modules"] if row["id"] != "auth.authbus"
                ]
            else:
                ids = [row["id"] for row in registry["modules"]]
                first, second = ids.index("auth.authbus"), ids.index("secrets.heptabao")
                registry["modules"][first], registry["modules"][second] = (
                    registry["modules"][second],
                    registry["modules"][first],
                )
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = root / "docs/modules/MODULES.json"
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps(registry))
                with (
                    self.subTest(mutation=mutation),
                    self.assertRaises(lane_a.VerificationError),
                ):
                    lane_a.validate_module_order(self.matrix["modules"], root)

    def test_current_types_contract_keeps_its_actual_source_and_evidence_boundaries(
        self,
    ):
        row = next(
            row for row in self.matrix["modules"] if row["module"] == "platform.types"
        )
        current = (lane_a.ROOT / row["currentSpecification"]).read_text()
        lane_a.validate_current_contract("platform.types", current)
        for clause in (
            "## Q32 semantic split",
            "stateless and has no durability",
            "`not_composed`",
            "`SensorCalibrationManifestV1`",
        ):
            with (
                self.subTest(clause=clause),
                self.assertRaises(lane_a.VerificationError),
            ):
                lane_a.validate_current_contract(
                    "platform.types",
                    current.replace(clause, "unregistered replacement"),
                )

    def test_operation_component_and_reference_boundaries_are_both_source_pinned(self):
        lane_a.validate_source_specific()
        read = lane_a.read_text
        for token in (
            "pub use durable_store::DurableOperationStore;",
            "pub use durable_model::OperationIntentV1 as DurableOperationIntentV1;",
        ):

            def changed(path):
                value = read(path)
                return (
                    value.replace(token, "unregistered replacement")
                    if path.as_posix().endswith("hepta-operations/src/lib.rs")
                    else value
                )

            with (
                self.subTest(token=token),
                mock.patch.object(lane_a, "read_text", side_effect=changed),
                self.assertRaises(lane_a.VerificationError),
            ):
                lane_a.validate_source_specific()


if __name__ == "__main__":
    unittest.main()
