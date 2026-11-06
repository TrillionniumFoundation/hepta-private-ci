"""Complete TCO assumptions cannot omit raw storage or unknown lifecycle costs."""

import math
import unittest
from copy import deepcopy

from lifecycle_accounting import complete_lifecycle_scenario


def fixture():
    baseline = {
        "receipt_sha256": "a" * 64,
        "fixed_usd": {"extraction": 1, "indexing": 1, "training": 0},
        "per_query_usd": {
            "retrieval": 2,
            "reader": 1,
            "tools": 0.5,
            "diagnostics": 0.5,
        },
        "per_window_usd": {
            "maintenance": 1,
            "revocation": 0.5,
            "recovery": 0.25,
        },
        "raw_evidence_bytes": 1024**3,
        "snapshot_and_index_bytes": 0,
    }
    learned = deepcopy(baseline)
    learned["receipt_sha256"] = "b" * 64
    learned["fixed_usd"]["training"] = 8
    learned["per_query_usd"].update(retrieval=0.5, reader=0.5)
    learned["per_window_usd"]["maintenance"] = 1.5
    return {"strong_rag": baseline, "candidate": learned}


class CompleteLifecycleScenarioTests(unittest.TestCase):
    def calculate(self, data=None, *, queries=(1, 4, 5, 8), price=0.1):
        return complete_lifecycle_scenario(
            fixture() if data is None else data,
            queries=queries,
            retention_days=5,
            price_usd_per_gib_day=price,
        )

    def test_conditional_crossover_counts_training_once_and_retains_raw_evidence(self):
        out = self.calculate()
        rows = out["horizons"]
        self.assertEqual(
            rows[1]["arms"]["strong_rag"]["complete_projected_cost_usd"], 20.25
        )
        self.assertEqual(
            rows[1]["arms"]["candidate"]["complete_projected_cost_usd"], 20.75
        )
        self.assertIs(
            rows[1]["arms"]["candidate_cheaper_on_supplied_assumptions"], False
        )
        self.assertIs(
            rows[2]["arms"]["candidate_cheaper_on_supplied_assumptions"], True
        )
        self.assertEqual(
            rows[3]["arms"]["candidate"]["raw_evidence_bytes_retained"], 1024**3
        )
        self.assertFalse(out["economic_superiority_established"])

    def test_unknown_maintenance_and_storage_price_never_become_zero(self):
        inputs = fixture()
        inputs["candidate"]["per_window_usd"]["revocation"] = None
        report = self.calculate(inputs, queries=(5,), price=None)
        strong = report["horizons"][0]["arms"]["strong_rag"]
        candidate = report["horizons"][0]["arms"]["candidate"]
        self.assertIsNone(strong["complete_projected_cost_usd"])
        self.assertIsNone(candidate["complete_projected_cost_usd"])
        self.assertIsNone(
            report["horizons"][0]["arms"]["candidate_cheaper_on_supplied_assumptions"]
        )
        self.assertIn("per_window_usd.revocation", candidate["unknown_cost_components"])

    def test_omitted_or_fake_zero_raw_source_storage_rejected(self):
        for bad in (0, True, -1, 1.0, 10**16):
            inputs = fixture()
            inputs["candidate"]["raw_evidence_bytes"] = bad
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.calculate(inputs)

    def test_negative_nonfinite_and_unbounded_assumptions_reject(self):
        for bad in (math.nan, math.inf, -1, True):
            inputs = fixture()
            inputs["candidate"]["per_query_usd"]["reader"] = bad
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.calculate(inputs)
        for queries in ((), (1, 1), (0,), (True,)):
            with self.assertRaises(ValueError):
                self.calculate(queries=queries)


if __name__ == "__main__":
    unittest.main()
