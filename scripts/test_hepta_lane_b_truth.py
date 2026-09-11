#!/usr/bin/env python3
"""Compatibility tests for the unified Lane B v3 verifier."""

from __future__ import annotations

import unittest

from scripts import hepta_lane_b_schema as schema


class LaneBTruthCompatibilityTests(unittest.TestCase):
    def test_single_schema_version(self) -> None:
        bundle = schema.load_bundle()
        self.assertEqual("hepta.lane-b-implementation-truth-index.v3", bundle["index"]["schema"])
        self.assertEqual("hepta.lane-b-candidate-manifest.v3", bundle["manifest"]["schema"])

    def test_all_operations_are_mapped_and_traced(self) -> None:
        bundle = schema.load_bundle()
        operations = [o for m in bundle["modules"] for o in m["operations"]]
        self.assertEqual(39, len(operations))
        self.assertTrue(all(o["mappingState"] == "closed" and
                            o["repositoryImplementationState"] == "implemented" and o["testIds"]
                            for o in operations))

    def test_companions_bind_exact_truth(self) -> None:
        bundle = schema.load_bundle()
        self.assertEqual(4, schema.verify_companions(bundle))


if __name__ == "__main__":
    unittest.main()
