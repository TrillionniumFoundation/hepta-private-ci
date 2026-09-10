#!/usr/bin/env python3
"""Unit tests for the Lane B implementation-truth validator."""

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

    def test_unresolved_operation_cannot_invent_mapping(self) -> None:
        operation = {
            "designOperation": "run",
            "state": "planned",
            "path": "invented.rs",
            "symbol": "run",
            "callerClass": "none",
        }
        with self.assertRaisesRegex(MODULE.Invalid, "must not invent"):
            MODULE.verify_operation(operation, "fixture")

    def test_mapped_operation_requires_real_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.rs"
            source.write_text("pub fn actual() {}\n", encoding="utf-8")
            operation = {
                "designOperation": "run",
                "state": "implemented",
                "path": "source.rs",
                "symbol": "pub fn missing(",
                "callerClass": "library_only",
            }
            with mock.patch.object(MODULE, "ROOT", root):
                with self.assertRaisesRegex(MODULE.Invalid, "missing symbol"):
                    MODULE.verify_operation(operation, "fixture")

    def test_native_anchor_requires_declared_export(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.rs"
            source.write_text("pub struct Present;\n", encoding="utf-8")
            native = {"path": "source.rs", "exports": ["Absent"]}
            with mock.patch.object(MODULE, "ROOT", root):
                with self.assertRaisesRegex(MODULE.Invalid, "missing native export"):
                    MODULE.verify_native_anchor("fixture", native)

    def test_expected_lane_is_closed_and_ordered(self) -> None:
        self.assertEqual(11, len(MODULE.EXPECTED_MODULES))
        self.assertEqual(11, len(set(MODULE.EXPECTED_MODULES)))
        self.assertEqual("runtime.supervisor", MODULE.EXPECTED_MODULES[0])
        self.assertEqual("ui.native", MODULE.EXPECTED_MODULES[-1])

    def test_scaffolds_are_not_runtime_maturity(self) -> None:
        self.assertIn("boundary_scaffold", MODULE.NO_RUNTIME_MATURITY)
        self.assertIn("presentation_core", MODULE.NO_RUNTIME_MATURITY)
        self.assertNotIn("partial_runtime", MODULE.NO_RUNTIME_MATURITY)


if __name__ == "__main__":
    unittest.main()
