#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).with_name("hepta-lane-b-truth.py")
SPEC = importlib.util.spec_from_file_location("hepta_lane_b_truth", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class LaneBTruthTests(unittest.TestCase):
    def test_duplicate_json_keys_fail(self) -> None:
        with self.assertRaises(MODULE.Invalid):
            json.loads('{"a":1,"a":2}', object_pairs_hook=MODULE.pairs)

    def test_path_envelope_is_prefix_bounded(self) -> None:
        self.assertTrue(
            MODULE.path_allowed(
                "qualification/lane-b/a.json", ["qualification/lane-b/"]
            )
        )
        self.assertFalse(
            MODULE.path_allowed(
                "qualification/lane-c/a.json", ["qualification/lane-b/"]
            )
        )

    def test_closed_module_and_operation_sets(self) -> None:
        self.assertEqual(11, len(MODULE.EXPECTED_MODULES))
        self.assertEqual(39, sum(map(len, MODULE.EXPECTED_OPERATIONS.values())))
        self.assertEqual(
            len(MODULE.EXPECTED_MODULES), len(set(MODULE.EXPECTED_MODULES))
        )

    def test_owner_anchor_cannot_escape_resolved_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "foreign" / "source.rs"
            source.parent.mkdir()
            source.write_text("pub fn run() {}\n", encoding="utf-8")
            anchor = {
                "role": "owner_entrypoint",
                "path": "foreign/source.rs",
                "symbol": "pub fn run(",
                "buildTarget": "fixture",
            }
            with mock.patch.object(MODULE, "ROOT", root):
                with self.assertRaisesRegex(MODULE.Invalid, "escapes resolved roots"):
                    MODULE.verify_anchor("fixture", ["owned"], anchor, True)

    def test_generated_map_preserves_external_claim_boundary(self) -> None:
        truth = {
            "sourceBase": {"commit": "a" * 40, "tree": "b" * 40},
            "laneId": "LANE-B-RUNTIME",
            "moduleOrder": ["fixture"],
        }
        row = {
            "module": "fixture",
            "sourceMaturity": "boundary",
            "declaredRoots": ["fixture"],
            "resolvedRoots": ["fixture"],
            "stateOwnerDisposition": "state remains bounded to the fixture owner",
            "terminalObserverDisposition": "terminal truth remains externally observed",
            "operations": [],
            "repositoryControlledGaps": [],
            "externalEvidenceGates": ["external target"],
        }
        projection = MODULE.module_map(truth, row)
        self.assertTrue(
            projection["claimBoundary"]["repositoryControlledGapsClosed"]
        )
        self.assertFalse(projection["claimBoundary"]["productExecutionComplete"])
        self.assertEqual(["external target"], projection["externalEvidenceGates"])


if __name__ == "__main__":
    unittest.main()
