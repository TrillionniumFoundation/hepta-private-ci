"""Model-free original-answer matching/score controls; no natural model results."""
from copy import deepcopy
import unittest

from amcn_core import Refused
from amcn_score import score_reader_quartets
from test_amcn import quartets, s


def records():
    requests = quartets("q1", "family-one", "future_a") + quartets("q2", "family-two", "future_b")
    raw, scores = [], []
    for r in requests:
        key = r["case_id"] + ":" + r["arm"]
        response = s("original-answer:" + key)
        raw.append({"case_id": r["case_id"], "arm": r["arm"],
                    "family": r["family"], "response_sha256": response,
                    "status": "success",
                    "emitted_evidence_ids": r["evidence_ids"][:1],
                    "input_tokens": 120, "output_tokens": 9,
                    "observed_wall_ms": 220,
                    "source_frontier_sha256": r["source_frontier_sha256"]})
        scores.append({"case_id": r["case_id"], "arm": r["arm"],
                       "response_sha256": response, "score": float(r["arm"] == "human_sufficient"),
                       "metric": "externally_scored_binary_success_v1",
                       "score_receipt_sha256": s("separate-scoring:"+key)})
    return requests, raw, scores


class OriginalAnswerControls(unittest.TestCase):
    def test_original_pair_cost_and_family_interval_nonpromotion(self):
        req, raw, scores = records()
        result = score_reader_quartets(req, raw, scores, evaluator_receipt_sha256=s("evaluator"))
        self.assertFalse(result["production_accepted"])
        self.assertEqual(result["metrics"]["families_upper_bound"], 2)
        self.assertEqual(result["metrics"]["executed_answers"], 8)
        self.assertEqual(result["metrics"]["observed_costs"]["human_sufficient"]["input"], 240)
        self.assertIsNone(result["metrics"]["semantic_citation_precision"])
        self.assertEqual(result["metrics"]["comparisons"]
                         ["human_sufficient-minus-ordinary_retrieval"]["mean_delta"], 1.0)

    def test_tampered_original_missing_answer_and_extra_citation(self):
        req, raw, scores = records()
        broken = deepcopy(raw)
        broken[0]["response_sha256"] = s("forgery")
        with self.assertRaises(Refused):
            score_reader_quartets(req, broken, scores, evaluator_receipt_sha256=s("evaluator"))
        with self.assertRaises(Refused):
            score_reader_quartets(req, raw[:-1], scores, evaluator_receipt_sha256=s("evaluator"))
        malicious = deepcopy(raw)
        malicious[0]["emitted_evidence_ids"] = ["not-delivered"]
        report = score_reader_quartets(req, malicious, scores,
                                       evaluator_receipt_sha256=s("evaluator"))
        self.assertEqual(report["metrics"]["undelivered_citation_labels"]["no_evidence"], 1)
        self.assertIsNone(report["metrics"]["semantic_citation_precision"])

    def test_failed_original_must_be_charged_not_imputed_to_win(self):
        req, raw, scores = records()
        raw[1]["status"] = "failed"
        raw[1]["response_sha256"] = None
        scores[1]["response_sha256"] = None
        scores[1]["score"] = 1.0
        with self.assertRaises(Refused):
            score_reader_quartets(req, raw, scores, evaluator_receipt_sha256=s("evaluator"))
        scores[1]["score"] = 0.0
        result = score_reader_quartets(req, raw, scores, evaluator_receipt_sha256=s("evaluator"))
        self.assertEqual(result["metrics"]["observed_costs"][raw[1]["arm"]]["failed"], 1)


if __name__ == "__main__":
    unittest.main()
