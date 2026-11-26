"""Reject noncanonical identity fields in the read-only 1+2+7 declaration gate."""

from dataclasses import replace
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hepta_cells.lineage_policy import COST_AXES, LineagePolicyError, review_update
from test_hepta_cells_lineage_policy import enrollment, evidence, roster


class SpoofedEnum(str):
    """Different text with attacker-selected hash and equality behavior."""

    def __new__(cls, text, pretends_to_be):
        obj = super().__new__(cls, text)
        obj.pretends_to_be = pretends_to_be
        return obj

    def __hash__(self):
        return hash(self.pretends_to_be)

    def __eq__(self, other):
        return self.pretends_to_be == other


class CellCanonicalEnumTests(unittest.TestCase):
    def test_lineage_is_exact_builtin_string(self):
        original = enrollment("PRED", scope="kernel_and_heads")
        spoof = SpoofedEnum("not-pred", "PRED")
        self.assertIn(spoof, {"PRED"})
        with self.assertRaisesRegex(LineagePolicyError, "unknown lineage or kernel"):
            replace(original, lineage=spoof)

    def test_kernel_is_exact_builtin_string(self):
        original = enrollment("PRED", scope="kernel_and_heads")
        spoof = SpoofedEnum("not-temporal", "stateful_temporal")
        self.assertIn(spoof, {"stateful_temporal"})
        with self.assertRaisesRegex(LineagePolicyError, "unknown lineage or kernel"):
            replace(original, kernel=spoof)

    def test_training_scope_is_exact_builtin_string(self):
        original = enrollment("VERIFY", scope="heads")
        spoof = SpoofedEnum("not-heads", "heads")
        self.assertIn(spoof, {"heads"})
        with self.assertRaisesRegex(LineagePolicyError, "requested fields"):
            replace(original, trainable_scope=spoof)

    def test_cost_axis_names_cannot_substitute_equal_python_objects(self):
        r = roster()
        verify = next(c for c in r.cells if c.lineage == "VERIFY")
        ev = evidence(verify)
        costs = dict(ev.costs)
        costs.pop("transport_bytes")
        costs[SpoofedEnum("not-transport-bytes", "transport_bytes")] = 0
        self.assertEqual(set(costs), COST_AXES)
        with self.assertRaisesRegex(LineagePolicyError, "eight real-cost axes"):
            review_update(r, replace(ev, costs=costs))

    def test_regular_enrollment_and_evidence_remain_review_only(self):
        r = roster()
        for lineage in ("PRED", "VERIFY"):
            cell = next(c for c in r.cells if c.lineage == lineage)
            result = review_update(r, evidence(cell))
            self.assertEqual(result.status, "REVIEW_ONLY")
            self.assertFalse(result.adoption_authorized)


if __name__ == "__main__":
    unittest.main()
