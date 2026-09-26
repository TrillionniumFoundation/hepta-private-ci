#!/usr/bin/env python3
"""Regression tests for source finalization; no compiler or repository writes."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location(
    "kg_finalize", Path(__file__).with_name("hepta-kg-convergence-finalize.py")
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def fixture() -> str:
    call = (
        "    let (edges, omitted) = collect_relation_query_edges(\n"
        "        generation.edges.iter(),\n"
        "        generation.edges.len(),\n"
        + MODULE.OLD_ARGUMENTS + "    );\n"
    )
    return (
        MODULE.OLD_ADJACENCY + "\n" + call + call
        + MODULE.OLD_SIGNATURE
        + "\n    if measure_work { work.omitted_edges += 1; }\n"
        + "    (Vec::new(), 0)\n}\n\nfn saturating_u64(value: usize) -> u64 { value as u64 }\n"
    )


class FinalizeTests(unittest.TestCase):
    def test_success_preserves_name_but_replaces_complete_signature(self) -> None:
        result = MODULE.finalize(fixture())
        self.assertIn(MODULE.NEW_SIGNATURE, result)
        self.assertEqual(result.count("collect_relation_query_edges::<MEASURE_WORK>("), 2)
        self.assertNotIn(MODULE.OLD_SIGNATURE, result)
        self.assertNotIn("if measure_work", result)
        self.assertIn("if MEASURE_WORK", result)
        self.assertNotIn("#[allow", result)

    def test_missing_signature_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.finalize(fixture().replace(MODULE.OLD_SIGNATURE, ""))

    def test_duplicate_signature_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.finalize(fixture() + MODULE.OLD_SIGNATURE)

    def test_missing_call_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.finalize(fixture().replace(MODULE.OLD_ARGUMENTS, "", 1))

    def test_unexpected_extra_call_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.finalize(fixture() + "collect_relation_query_edges(\n")

    def test_changed_adjacency_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.finalize(fixture().replace(MODULE.OLD_ADJACENCY, ""))

    def test_repeated_application_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.finalize(MODULE.finalize(fixture()))


if __name__ == "__main__":
    unittest.main()
