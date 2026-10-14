"""Pure same-source SELECT audit regressions. All examples and grades are fixtures."""
from copy import deepcopy
import unittest

import five_causal_experiments as c
import select_content_inventory as inventory
import select_question_relevance as q
import test_select_content_inventory as old


def fixture(missing=False):
    benchmark = old.fixture()
    if missing:
        benchmark.targets["qa0"].answer = None
    plan = inventory.build_plan(benchmark, old.cases(benchmark))
    cases = deepcopy(plan["public_cases"])
    raw = []
    for arm in q.ARMS:
        for slot, case in enumerate(cases):
            identity = {k: case[k] for k in ("question_id", "family", "split", "condition")}
            request = case["request"]
            row = identity | {"arm": arm, "trial_id": c.digest([arm, slot, identity]),
                              "status": "unavailable_source_or_donor" if request is None else "succeeded",
                              "answer": None if request is None else "FIXTURE answer",
                              "evidence_ids": [] if request is None else [e["id"] for e in request["evidence"]]}
            if request is not None: row["public_request_sha256"] = c.digest(request)
            raw.append(row)
    return plan, cases, raw


class PlanTests(unittest.TestCase):
    def test_identical_nonempty_sources_and_different_questions(self):
        p, cases, _ = fixture(); result = q.build_plan(p, cases)
        self.assertEqual(result["available_pairs"], 2)
        for unit in result["units"]:
            self.assertEqual(unit["matched_request"]["evidence"], unit["mismatched_request"]["evidence"])
            self.assertNotEqual(unit["matched_request"]["question"], unit["mismatched_request"]["question"])

    def test_original_donor_ids_are_reused_not_reselected(self):
        p, cases, _ = fixture(); result = q.build_plan(p, cases)
        self.assertEqual({u["question_id"]: u["donor_question_id"] for u in result["units"]},
                         {u["question_id"]: u["donor_question_id"] for u in p["recipients"]})
        self.assertFalse(result["donor_selection_changed"])

    def test_public_calls_have_no_answer_or_model_fields(self):
        p, cases, _ = fixture()
        for item in q.build_plan(p, cases)["public_requests"]:
            self.assertEqual(set(item), {"request_id", "request"})
            c.validate_public(item["request"])
            self.assertEqual(item["request_id"], c.digest(item["request"]))

    def test_inputs_are_never_modified(self):
        p, cases, _ = fixture(); before = c.digest([p, cases])
        r = q.build_plan(p, cases); self.assertEqual(c.digest([p, cases]), before)
        r["units"][0]["matched_request"]["question"] = "changed"
        self.assertEqual(c.digest([p, cases]), before)

    def test_donor_text_date_order_and_local_ids_unchanged(self):
        p, cases, _ = fixture(); result = q.build_plan(p, cases)
        for u in result["units"]:
            comparison = next(x for x in p["comparisons"] if x["question_id"] == u["question_id"])
            self.assertEqual(u["matched_request"]["evidence"], comparison["requests"]["donor_sources"]["evidence"])
            self.assertTrue(all("1 January 2023" in e["text"] for e in u["matched_request"]["evidence"]))

    def test_same_citation_suffix_used_for_both_questions(self):
        p, cases, _ = fixture()
        for u in q.build_plan(p, cases)["units"]:
            suffix = " " + " ".join("[" + e["id"] + "]" for e in u["matched_request"]["evidence"])
            self.assertTrue(u["response"].endswith(suffix))

    def test_missing_reference_remains_in_all_recipient_slots(self):
        p, cases, _ = fixture(True); r = q.build_plan(p, cases)
        self.assertEqual(r["planned_recipients"], 2)
        self.assertEqual(r["available_pairs"], 1)
        self.assertEqual(len(r["units"]), 2)
        self.assertIsNone(next(u for u in r["units"] if u["status"] != "available")["response"])

    def test_repeated_inventory_order_does_not_change_public_requests(self):
        p, cases, _ = fixture(); before = q.build_plan(p, cases)
        p["pool"].reverse(); p["comparisons"].reverse()
        self.assertEqual(before["public_requests"], q.build_plan(p, cases)["public_requests"])

    def reject(self, change):
        p, cases, _ = fixture(); change(p, cases)
        with self.assertRaises((c.Invalid, KeyError)): q.build_plan(p, cases)

    def test_nonselect_donor_rejected(self):
        self.reject(lambda p, cases: p["pool"][0].update(split="train"))

    def test_changed_previous_input_rejected(self):
        self.reject(lambda p, cases: cases[0]["request"].update(question="new question"))

    def test_changed_donor_identity_rejected(self):
        self.reject(lambda p, cases: p["recipients"][0].update(donor_question_id="0" * 64))

    def test_changed_donor_answer_rejected(self):
        self.reject(lambda p, cases: p["comparisons"][0]["answers"].__setitem__(1, "changed"))

    def test_changed_donor_context_rejected(self):
        self.reject(lambda p, cases: p["comparisons"][0]["requests"]["donor_sources"].update(evidence=[]))

    def test_duplicate_recipient_rejected(self):
        self.reject(lambda p, cases: p["recipients"].append(deepcopy(p["recipients"][0])))

    def test_duplicate_pool_rejected(self):
        self.reject(lambda p, cases: p["pool"].append(deepcopy(p["pool"][0])))


class SavedJoinTests(unittest.TestCase):
    def test_all_old_slots_join_and_answers_preserved(self):
        _, cases, raw = fixture(); original = c.digest(raw)
        result = q.join_previous(cases, raw)
        self.assertEqual(sum(len(v) for v in result.values()), len(raw))
        self.assertEqual(c.digest(raw), original)
        self.assertTrue(all(r["answer"] == "FIXTURE answer" for values in result.values() for r in values.values()))

    def test_raw_order_does_not_change_identity_join(self):
        _, cases, raw = fixture()
        self.assertEqual(q.join_previous(cases, raw), q.join_previous(cases, list(reversed(raw))))

    def test_missing_raw_slot_rejected(self):
        _, cases, raw = fixture()
        with self.assertRaises(c.Invalid): q.join_previous(cases, raw[:-1])

    def test_duplicate_raw_slot_rejected(self):
        _, cases, raw = fixture(); raw[-1] = deepcopy(raw[0])
        with self.assertRaises(c.Invalid): q.join_previous(cases, raw)

    def test_changed_public_hash_rejected(self):
        _, cases, raw = fixture(); raw[0]["public_request_sha256"] = "0" * 64
        with self.assertRaises(c.Invalid): q.join_previous(cases, raw)

    def test_changed_citation_list_rejected(self):
        _, cases, raw = fixture(); row = next(r for r in raw if r["evidence_ids"])
        row["evidence_ids"] = []
        with self.assertRaises(c.Invalid): q.join_previous(cases, raw)

    def test_failed_original_call_not_retried_or_used_as_answer(self):
        _, cases, raw = fixture(); raw[0]["status"] = "failed"
        with self.assertRaises(c.Invalid): q.join_previous(cases, raw)

    def test_unavailable_donor_cannot_become_success(self):
        _, cases, raw = fixture(True)
        row = next(r for r in raw if r["answer"] is None)
        row.update(status="succeeded", answer="invented")
        with self.assertRaises(c.Invalid): q.join_previous(cases, raw)


class ReadoutTests(unittest.TestCase):
    @staticmethod
    def answer(text, status="succeeded"):
        return {"status": status, "answer": text}

    def test_always_refuse_does_not_pass_joint_behavior(self):
        row = q.behavior(self.answer(q.REFUSAL), self.answer(q.REFUSAL))
        self.assertFalse(row["weak_selective_behavior"])
        self.assertIsNone(row["semantic_accuracy"])

    def test_always_answer_does_not_pass_joint_behavior(self):
        self.assertFalse(q.behavior(self.answer("x"), self.answer("y"))["weak_selective_behavior"])

    def test_expected_selectivity_is_still_not_correctness(self):
        row = q.behavior(self.answer("possibly wrong"), self.answer(q.REFUSAL))
        self.assertTrue(row["weak_selective_behavior"])
        self.assertIsNone(row["semantic_accuracy"])

    def test_failed_matched_side_remains_unknown(self):
        row = q.behavior(self.answer("x", "timeout"), self.answer(q.REFUSAL))
        self.assertFalse(row["jointly_observed"])
        self.assertIsNone(row["weak_selective_behavior"])

    def test_positive_interaction_is_not_two_correct_directions(self):
        r = q.preference([-4, -2, -7, -2])
        self.assertGreater(r["question_interaction"], 0)
        self.assertFalse(r["both_weak_preferences_positive"])

    def test_additive_answer_preference_cannot_satisfy_both(self):
        self.assertFalse(q.preference([-1, -2, -1, -2])["both_weak_preferences_positive"])
        self.assertEqual(q.preference([-1, -2, -1, -2])["question_interaction"], 0)

    def test_actual_opposite_preferences_detected(self):
        self.assertTrue(q.preference([-1, -3, -3, -1])["both_weak_preferences_positive"])

    def test_nonfinite_or_boolean_scores_rejected(self):
        for bad in ([True, -1, -2, -3], [float("nan"), -1, -2, -3], [1, -1, -2, -3], [-1, -2]):
            with self.assertRaises(c.Invalid): q.preference(bad)

    def test_missing_rows_stay_in_summary_denominator(self):
        rows = [{"question_id": "a", "family": "A", "status": "succeeded", "preference": q.preference([-1,-3,-3,-1]),
                 "behavior": q.behavior(self.answer("x"), self.answer(q.REFUSAL))},
                {"question_id": "b", "family": "B", "status": "unavailable", "preference": None}]
        r = q.summarize(rows)
        self.assertEqual((r["planned_pairs"], r["scored_pairs"], r["unavailable_or_failed"]), (2,1,1))
        self.assertEqual(r["weak_selective_generation_pairs"], 1)
        self.assertFalse(r["candidate_admitted"])

    def test_no_observations_have_null_mean(self):
        r = q.summarize([{"question_id": "a", "family": "A", "status": "unavailable", "preference": None}])
        self.assertIsNone(r["mean_interaction"])
        self.assertIsNone(r["family_macro_interaction"])

    def test_family_macro_not_task_mean(self):
        rows = [{"question_id": str(i), "family": family, "status": "succeeded",
                 "preference": q.preference([-1, -1-value, -1, -1])}
                for i, (family, value) in enumerate((("A",1),("A",1),("B",5)))]
        r = q.summarize(rows)
        self.assertAlmostEqual(r["mean_interaction"], 7/3)
        self.assertEqual(r["family_macro_interaction"], 3)


if __name__ == "__main__":
    unittest.main()
