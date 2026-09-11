#!/usr/bin/env python3
"""Unit tests for the Lane B repository-closure validator."""

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

    def test_closed_sets_are_stable(self) -> None:
        self.assertEqual(11, len(MODULE.MODULES))
        self.assertEqual(39, sum(map(len, MODULE.OPERATIONS.values())))
        self.assertEqual("runtime.supervisor", MODULE.MODULES[0])
        self.assertEqual("ui.native", MODULE.MODULES[-1])

    def test_owner_mapping_must_stay_in_implementation_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "owner").mkdir()
            (root / "foreign").mkdir()
            (root / "foreign/source.rs").write_text("pub fn mapped() {}\n", encoding="utf-8")
            mapping = {"path":"foreign/source.rs","symbol":"pub fn mapped(","callerClass":"runtime","buildTarget":"target"}
            with mock.patch.object(MODULE.CORE, "ROOT", root):
                with self.assertRaisesRegex(MODULE.Invalid, "outside implementation roots"):
                    MODULE.verify_mapping("fixture", mapping, ["owner"])

    def test_mapped_symbol_must_exist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "owner").mkdir()
            (root / "owner/source.rs").write_text("pub fn actual() {}\n", encoding="utf-8")
            mapping = {"path":"owner/source.rs","symbol":"pub fn missing(","callerClass":"runtime","buildTarget":"target"}
            with mock.patch.object(MODULE.CORE, "ROOT", root):
                with self.assertRaisesRegex(MODULE.Invalid, "missing symbol"):
                    MODULE.verify_mapping("fixture", mapping, ["owner"])

    def test_test_only_source_cannot_be_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "owner/tests").mkdir(parents=True)
            (root / "owner/tests/mapped.rs").write_text("pub fn mapped() {}\n", encoding="utf-8")
            mapping = {"path":"owner/tests/mapped.rs","symbol":"pub fn mapped(","callerClass":"runtime","buildTarget":"target"}
            with mock.patch.object(MODULE.CORE, "ROOT", root):
                with self.assertRaisesRegex(MODULE.Invalid, "test-only"):
                    MODULE.verify_mapping("fixture", mapping, ["owner"])

    def test_module_projection_is_deterministic(self) -> None:
        truth = {"lineageAnchor": {"commit": "a" * 40, "tree": "b" * 40}}
        row = {
            "module":"fixture","maturity":"partial_runtime","ownerRoots":["owner"],
            "implementationRoots":["owner"],"aliasResolution":[],"operations":[],
            "productionCallerState":"unproved","productExecutionState":"unproved",
            "residualGaps":[{"class":"external_evidence","gap":"z" * 40}],
        }
        first = MODULE.map_projection(truth, row)
        self.assertEqual(first, MODULE.map_projection(truth, row))
        self.assertEqual("hepta.lane-b-module-implementation-map.v2", first["schema"])
        self.assertTrue(first["generatedProjection"])

    def test_delegation_is_explicit_and_planned_is_forbidden(self) -> None:
        self.assertIn("delegated_partial", MODULE.ALLOWED_STATES)
        self.assertNotIn("planned", MODULE.ALLOWED_STATES)


if __name__ == "__main__":
    unittest.main()
