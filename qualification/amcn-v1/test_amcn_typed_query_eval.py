"""Adversarial whole-question, zero-hit, original-source test for typed recall."""
from copy import deepcopy
import unittest

from amcn_core import Refused, digest
from amcn_typed_query_eval import PROFILE, ARMS, score_question_recall


def setup():
    questions, preds, publisher = [], [], {}
    for split in ("select", "future_a", "future_b", "retention"):
        for kind in ("semantic", "episodic"):
            qid = f"{split}:{kind}"
            supports = [f"{qid}/s2"] if qid != "future_b:episodic" else []
            publisher[qid] = supports
            candidates = []
            for idx in range(3):
                sid, rid = f"{qid}/s{idx}", f"{qid}/r{idx}"
                inp = digest(f"feature/{rid}")
                candidates.append({"row_id": rid, "source_id": sid,
                                   "source_sha256": digest(sid),
                                   "source_revision": 1, "input_sha256": inp})
                # Deliberately query-level type signal: typed retrieves support
                # even though raw per-candidate accuracy need not reflect it.
                preds.append({"row_id": rid, "family": f"family/{split}",
                              "split": split, "memory_type": kind,
                              "input_sha256": inp,
                              "probabilities": {
                                  "frozen": 0.1,
                                  "single_shared": 0.2,
                                  "untyped_equal_budget": 0.3,
                                  "typed_equal_budget": 0.95 if idx == 2 else 0.05,
                                  "typed_swapped_negative": 0.4}})
            questions.append({"question_id": qid, "family": f"family/{split}",
                              "split": split, "memory_type": kind,
                              "scope": "lab", "generation": "g1",
                              "label_blind": True, "candidate_rows": candidates})
    return {"schema": PROFILE + ".plan", "questions": questions}, preds, publisher


def evaluate(plan, predictions, publisher):
    return score_question_recall(plan, predictions, publisher,
        expected_plan_sha256=digest(plan),
        expected_predictions_sha256=digest(predictions),
        expected_support_sha256=digest(publisher))


class TypedQuestionEvalTests(unittest.TestCase):
    def setUp(self):
        self.plan, self.pred, self.publisher = setup()

    def test_real_question_not_per_row_relevance_metric(self):
        result = evaluate(self.plan, self.pred, self.publisher)
        m = result["metrics"]
        self.assertEqual(m["complete_question_count"], 8)
        self.assertEqual(m["complete_candidate_count"], 24)
        self.assertEqual(m["zero_support_or_zero_hit_questions"], 1)
        typed = [r for r in m["source_first_weak_support"]
                 if r["arm"] == "typed_equal_budget"]
        lexical = [r for r in m["source_first_weak_support"]
                   if r["arm"] == "lexical_top1"]
        self.assertEqual(sum(x["hit1"] for x in typed), 7)
        self.assertEqual(sum(x["hit1"] for x in lexical), 0)
        self.assertFalse(result["production_accepted"])
        self.assertIsNone(m["original_reader_answers"])
        self.assertEqual(m["independent_future_calendar_windows"], 0)

    def test_perfect_negative_predictions_cannot_mint_source_support(self):
        self.pred = deepcopy(self.pred)
        for x in self.pred:
            x["probabilities"]["typed_equal_budget"] = 0.0
        result = evaluate(self.plan, self.pred, self.publisher)
        self.assertEqual(result["metrics"]["zero_support_or_zero_hit_questions"], 1)

    def test_duplicate_or_missing_question_rejected(self):
        self.plan["questions"].pop()
        with self.assertRaises(Refused):
            evaluate(self.plan, self.pred, self.publisher)
        self.plan, self.pred, self.publisher = setup()
        self.plan["questions"].append(deepcopy(self.plan["questions"][0]))
        with self.assertRaises(Refused):
            evaluate(self.plan, self.pred, self.publisher)

    def test_plan_must_be_pinned_before_opening_labels(self):
        with self.assertRaises(Refused):
            score_question_recall(self.plan, self.pred, self.publisher,
                expected_plan_sha256=digest("fake"),
                expected_predictions_sha256=digest(self.pred),
                expected_support_sha256=digest(self.publisher))

    def test_missing_or_modified_publisher_annotation_refused(self):
        self.publisher.pop("future_a:semantic")
        with self.assertRaises(Refused):
            evaluate(self.plan, self.pred, self.publisher)
        self.plan, self.pred, self.publisher = setup()
        self.publisher["future_a:semantic"] = ["repeat", "repeat"]
        with self.assertRaises(Refused):
            evaluate(self.plan, self.pred, self.publisher)

    def test_missing_or_duplicate_prediction_refused(self):
        self.pred.pop()
        with self.assertRaises(Refused):
            evaluate(self.plan, self.pred, self.publisher)
        self.plan, self.pred, self.publisher = setup()
        self.pred.append(deepcopy(self.pred[0]))
        with self.assertRaises(Refused):
            evaluate(self.plan, self.pred, self.publisher)

    def test_candidate_exact_source_and_input_mismatch_refused(self):
        self.plan["questions"][0]["candidate_rows"][0]["input_sha256"] = digest("other")
        with self.assertRaises(Refused):
            evaluate(self.plan, self.pred, self.publisher)
        self.plan, self.pred, self.publisher = setup()
        self.plan["questions"][0]["candidate_rows"][0]["source_revision"] = 0
        with self.assertRaises(Refused):
            evaluate(self.plan, self.pred, self.publisher)

    def test_foreign_scope_changed_family_and_label_blindness(self):
        self.plan["questions"][0]["label_blind"] = False
        with self.assertRaises(Refused):
            evaluate(self.plan, self.pred, self.publisher)
        self.plan, self.pred, self.publisher = setup()
        self.plan["questions"][0]["family"] = "forged"
        with self.assertRaises(Refused):
            evaluate(self.plan, self.pred, self.publisher)

    def test_nan_and_arm_omissions_fail(self):
        self.pred[0]["probabilities"]["typed_equal_budget"] = float("nan")
        with self.assertRaises(ValueError):
            evaluate(self.plan, self.pred, self.publisher)
        self.plan, self.pred, self.publisher = setup()
        del self.pred[0]["probabilities"]["frozen"]
        with self.assertRaises(Refused):
            evaluate(self.plan, self.pred, self.publisher)

    def test_no_unregistered_fields_or_extra_support_question(self):
        self.plan["questions"][0]["gold"] = "leak"
        with self.assertRaises(Refused):
            evaluate(self.plan, self.pred, self.publisher)
        self.plan, self.pred, self.publisher = setup()
        self.publisher["extra"] = []
        with self.assertRaises(Refused):
            evaluate(self.plan, self.pred, self.publisher)

    def test_missing_future_a_and_b_cannot_be_accepted(self):
        self.plan["questions"] = [r for r in self.plan["questions"]
                                  if r["split"] not in ("future_a", "future_b")]
        held = {r["row_id"] for q in self.plan["questions"]
                for r in q["candidate_rows"]}
        self.pred = [r for r in self.pred if r["row_id"] in held]
        self.publisher = {q["question_id"]: self.publisher[q["question_id"]]
                          for q in self.plan["questions"]}
        with self.assertRaises(Refused):
            evaluate(self.plan, self.pred, self.publisher)

    def test_mixed_source_scope_or_unhashable_support_rejected(self):
        self.plan["questions"][0]["scope"] = "foreign"
        with self.assertRaises(Refused):
            evaluate(self.plan, self.pred, self.publisher)
        self.plan, self.pred, self.publisher = setup()
        self.publisher["future_a:semantic"] = [["unhashable"]]
        with self.assertRaises(Refused):
            evaluate(self.plan, self.pred, self.publisher)

    def test_physical_head_identity_not_invented(self):
        verdict = evaluate(self.plan, self.pred, self.publisher)
        self.assertFalse(verdict["metrics"]["physical_head_bank_independently_replayed"])
        self.assertFalse(verdict["metrics"]["source_owner_and_external_issuers_verified"])

if __name__ == "__main__":
    unittest.main()
