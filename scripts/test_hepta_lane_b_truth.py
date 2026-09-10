#!/usr/bin/env python3
"""Unit tests for the composed Lane B v2 truth validator."""

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


def planned_operation(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "designOperation": "run",
        "state": "planned",
        "path": None,
        "symbol": None,
        "callerClass": "none",
        "buildTarget": None,
    }
    value.update(overrides)
    return value


def mapped_operation(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "designOperation": "run",
        "state": "implemented",
        "path": "owner/source.rs",
        "symbol": "pub fn run(",
        "callerClass": "binary_entry",
        "buildTarget": "fixture",
    }
    value.update(overrides)
    return value


class LaneBTruthV2Tests(unittest.TestCase):
    def test_duplicate_json_keys_fail(self) -> None:
        with self.assertRaises(MODULE.Invalid):
            json.loads('{"a":1,"a":2}', object_pairs_hook=MODULE.pairs)

    def test_planned_operation_cannot_invent_mapping(self) -> None:
        with self.assertRaisesRegex(MODULE.Invalid, "invented source"):
            MODULE.verify_operation(
                "fixture",
                ["owner"],
                planned_operation(path="owner/invented.rs"),
            )

    def test_mapped_operation_requires_real_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "owner/source.rs"
            source.parent.mkdir(parents=True)
            source.write_text("pub fn actual() {}\n", encoding="utf-8")
            with mock.patch.object(MODULE.CORE, "ROOT", root):
                with self.assertRaisesRegex(MODULE.Invalid, "missing mapped symbol"):
                    MODULE.verify_operation(
                        "fixture",
                        ["owner"],
                        mapped_operation(symbol="pub fn missing("),
                    )

    def test_mapping_must_stay_inside_owner_root(self) -> None:
        with self.assertRaisesRegex(MODULE.Invalid, "owner-root escape"):
            MODULE.verify_operation(
                "fixture",
                ["owner"],
                mapped_operation(path="other/source.rs"),
            )

    def test_test_only_mapping_is_rejected_before_read(self) -> None:
        with self.assertRaisesRegex(MODULE.Invalid, "test-only mapping"):
            MODULE.verify_operation(
                "fixture",
                ["owner"],
                mapped_operation(path="owner/tests/source.rs"),
            )

    def test_symbol_count_is_declaration_shaped(self) -> None:
        text = "pub fn run() {}\nself.run();\npub fn runner() {}\n"
        self.assertEqual(1, MODULE.symbol_occurrences(text, "pub fn run("))

    def test_expected_lane_is_closed_and_ordered(self) -> None:
        self.assertEqual(11, len(MODULE.MODULES))
        self.assertEqual(11, len(set(MODULE.MODULES)))
        self.assertEqual(39, sum(map(len, MODULE.EXPECTED_OPERATIONS.values())))
        self.assertEqual("runtime.supervisor", MODULE.MODULES[0])
        self.assertEqual("ui.native", MODULE.MODULES[-1])


if __name__ == "__main__":
    unittest.main()
