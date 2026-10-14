"""Matched strong hybrid RAG comparisons are receipts, not synthetic wins."""
from copy import deepcopy
import unittest

from amcn_core import Refused
from amcn_routing_audit import ARMS, METRIC, compare_routing
from test_amcn import s


def material():
    runs, scores = [], []
    for case_id, family, split in [("q1", "future-one", "future_a"),
                                    ("q2", "future-two", "future_b")]:
        for arm in ARMS:
            rawsha = s(case_id + ":" + arm + ":original")
            runs.append({
                "case_id": case_id, "family": family, "split": split, "arm": arm,
                "question_sha256": s(case_id), "source_frontier_sha256": s("frontier"),
                "reader_sha256": s("reader"), "prompt_sha256": s("prompt"),
                "evidence_ids": ["external-source-1"], "raw_answer_sha256": rawsha,
                "status": "ok", "original_inference_receipt_sha256": s("generation-"+case_id+arm),
                "input_tokens": 40, "output_tokens": 10, "measured_wall_ms": 13,
            })
            scores.append({"case_id": case_id, "arm": arm,
                           "raw_answer_sha256": rawsha, "score": float(arm=="cell_fixed_graph"),
                           "metric": METRIC, "judgment_sha256": s("judgment-"+case_id+arm)})
    return runs, scores


class RoutingComparison(unittest.TestCase):
    def test_descriptive_family_95pct_and_actual_cost_envelope(self):
        runs, scored = material()
        r = compare_routing(runs, scored, scorer_pin=s("scorer"))
        self.assertFalse(r["production_accepted"])
        self.assertEqual(r["metrics"]["source_families_upper_bound"], 2)
        self.assertEqual(r["metrics"]["cost"]["strong_hybrid_rag"]["input_tokens"], 80)
        self.assertEqual(r["metrics"]["comparisons"]["cell_fixed_graph"]
                         ["mean_success_gain_vs_strong_rag"], 1.0)
        self.assertIsNone(r["metrics"]["semantic_citation_precision"])
        self.assertFalse(r["metrics"]["strong_hybrid_rag_really_executed_here"])

    def test_missing_strong_baseline_and_reader_drift_refused(self):
        runs, scored = material()
        with self.assertRaises(Refused):
            compare_routing(runs[:-1], scored, scorer_pin=s("scorer"))
        altered = deepcopy(runs)
        altered[3]["reader_sha256"] = s("new-reader")
        with self.assertRaises(Refused):
            compare_routing(altered, scored, scorer_pin=s("scorer"))
        edited = deepcopy(scored)
        edited[0]["raw_answer_sha256"] = s("edited-output")
        with self.assertRaises(Refused):
            compare_routing(runs, edited, scorer_pin=s("scorer"))

    def test_failure_is_charged_without_success_imputation(self):
        runs, scored = material()
        runs[0]["status"] = "failed"
        runs[0]["raw_answer_sha256"] = None
        scored[0]["raw_answer_sha256"] = None
        with self.assertRaises(Refused):
            compare_routing(runs, scored, scorer_pin=s("scorer"))
        scored[0]["score"] = 0
        r = compare_routing(runs, scored, scorer_pin=s("scorer"))
        self.assertEqual(r["metrics"]["cost"]["cell_independent"]["failed"], 1)


if __name__ == "__main__":
    unittest.main()
