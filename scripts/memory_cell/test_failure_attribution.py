import copy
import unittest

from failure_attribution import ABSTAIN, attribute


def target(unanswerable=False, evidence=("scope/good",)):
    return {"unanswerable": unanswerable, "evidence": list(evidence)}


def base(**updates):
    row = {
        "question_id": "q",
        "arm": "candidate",
        "phase": "test",
        "family": "f",
        "status": "succeeded",
        "candidate_source_ids": ["scope/good", "scope/bad"],
        "selected": 0,
        "answer": "right",
        "f1": 1.0,
        "receipt": {
            "delivered_evidence": [
                {"original_id": "scope/good", "observed_at": "2024-01-01"}
            ]
        },
    }
    row.update(updates)
    return row


class FailureAttributionTests(unittest.TestCase):
    def test_stage_order_and_complete_denominators(self):
        rows = [
            base(),
            base(arm="ranking", selected=1, answer="wrong", f1=0.0),
            base(arm="generation", answer="almost", f1=0.4),
            base(arm="abstain", answer=ABSTAIN, f1=0.0),
            base(
                arm="retrieval",
                candidate_source_ids=[],
                selected=None,
                answer="wrong",
                f1=0.0,
            ),
            base(
                question_id="negative",
                arm="negative",
                candidate_source_ids=[],
                selected=None,
                answer=ABSTAIN,
                f1=1.0,
            ),
            base(
                question_id="negative",
                arm="negative-wrong",
                candidate_source_ids=[],
                selected=None,
                answer="invented",
                f1=0.0,
            ),
            base(
                question_id="failed",
                arm="failed",
                status="failed",
                stage="native-history-ingress",
                receipt={"delivered_evidence": []},
            ),
        ]
        targets = {"q": target(), "negative": target(True, ()), "failed": target()}
        result = attribute(
            rows,
            targets,
            planned=[(r["question_id"], r["arm"]) for r in rows],
        )
        self.assertEqual(result["denominators"]["planned"], 8)
        self.assertEqual(result["denominators"]["failed"], 1)
        self.assertEqual(result["denominators"]["unanswerable"], 2)
        self.assertEqual(result["denominators"]["empty_evidence"], 1)
        by_arm = {r["arm"]: r for r in result["records"]}
        self.assertEqual(by_arm["ranking"]["failure_stages"], ["ranking"])
        self.assertEqual(by_arm["generation"]["failure_stages"], ["generation"])
        self.assertEqual(by_arm["abstain"]["failure_stages"], ["abstention"])
        self.assertEqual(by_arm["retrieval"]["failure_stages"], [])
        self.assertEqual(by_arm["negative"]["failure_stages"], [])
        self.assertEqual(by_arm["negative-wrong"]["failure_stages"], ["abstention"])
        self.assertIn("history_ingress", by_arm["failed"]["failure_stages"])
        self.assertIsNone(result["semantic_citation_precision"])

    def test_time_and_structural_citation_are_observable_only(self):
        row = base(
            question_time="2024-01-01",
            receipt={
                "delivered_evidence": [
                    {"original_id": "scope/good", "observed_at": "2025-01-01"}
                ]
            },
            citation_audit={
                "request": {
                    "query_id": "wrong",
                    "answer": "different",
                    "sources": [],
                }
            },
        )
        result = attribute([row], {"q": target()})
        self.assertEqual(
            result["records"][0]["failure_stages"], ["citation_structure", "time"]
        )
        self.assertIsNone(
            result["stage_counts"]["citation_structure"]["semantic_citation_precision"]
        )
        self.assertIsNone(result["stage_counts"]["time"]["semantic_citation_precision"])

    def test_missing_structural_evidence_remains_unattributed(self):
        receipt_only = base(
            arm="receipt-only",
            candidate_source_ids=None,
            selected=None,
            receipt={"delivered_evidence": [{"original_id": "scope/good"}]},
            answer="almost",
            f1=0.4,
        )
        missing_target = base(
            question_id="missing-target-evidence",
            arm="missing-target-evidence",
            selected=0,
        )
        result = attribute(
            [receipt_only, missing_target],
            {"q": target(), "missing-target-evidence": {"unanswerable": False}},
        )
        by_arm = {r["arm"]: r for r in result["records"]}
        self.assertEqual(by_arm["receipt-only"]["failure_stages"], [])
        self.assertEqual(by_arm["missing-target-evidence"]["failure_stages"], [])
        self.assertEqual(result["stage_counts"]["ranking"]["eligible"], 0)

    def test_missing_or_duplicate_planned_attempts_reject(self):
        row = base()
        with self.assertRaises(ValueError):
            attribute([row, copy.deepcopy(row)], {"q": target()})
        with self.assertRaises(ValueError):
            attribute(
                [row],
                {"q": target()},
                planned=[("q", "candidate"), ("q", "other")],
            )

    def test_success_receipt_and_score_must_be_structurally_valid(self):
        with self.assertRaises(ValueError):
            attribute([base(receipt=[])], {"q": target()})
        with self.assertRaises(ValueError):
            attribute([base(f1=float("nan"))], {"q": target()})

    def test_missing_support_does_not_masquerade_as_ranking_failure(self):
        row = base(answer="almost", f1=0.4)
        result = attribute([row], {"q": target(evidence=())})
        self.assertEqual(result["records"][0]["failure_stages"], ["generation"])


if __name__ == "__main__":
    unittest.main()
