"""Supplementary checks against canonical select_question_relevance, not a second runner.

These fixtures do not grade real answers or certify independent relevance.
"""
from copy import deepcopy
import unittest
import five_causal_experiments as c
import select_question_relevance as q
import select_content_inventory as inventory
from test_select_content_inventory import fixture,cases


def make_plan(missing=False):
    b=fixture()
    if missing:b.targets["qa0"].answer=None
    i=inventory.build_plan(b,cases(b))
    return q.build_plan(i,i["public_cases"]),i


def output(answer,status="succeeded"):
    return {"answer":answer,"status":status}


class CanonicalBehaviorChecks(unittest.TestCase):
    def test_all_refuse_never_passes_joint_behavior(self):
        self.assertFalse(q.behavior(output(q.REFUSAL),output(q.REFUSAL))["weak_selective_behavior"])
    def test_all_answer_never_passes_joint_behavior(self):
        self.assertFalse(q.behavior(output("fixture answer"),output("fixture answer"))["weak_selective_behavior"])
    def test_blank_matched_output_stays_observed_but_fails(self):
        for s in (""," \n\t"):
            r=q.behavior(output(s),output(q.REFUSAL))
            self.assertTrue(r["jointly_observed"]);self.assertFalse(r["weak_selective_behavior"])
    def test_conditional_fixture_is_not_semantic_accuracy(self):
        r=q.behavior(output("fixture answer"),output(q.REFUSAL))
        self.assertTrue(r["weak_selective_behavior"]);self.assertIsNone(r["semantic_accuracy"])
    def test_timeout_with_text_remains_unobserved(self):
        r=q.behavior(output("fixture answer","timeout_with_observed_output"),output(q.REFUSAL))
        self.assertFalse(r["jointly_observed"]);self.assertIsNone(r["weak_selective_behavior"])
    def test_null_or_unavailable_does_not_become_refusal(self):
        for status in ("failed","unavailable_source_or_donor","blocked_model"):
            r=q.behavior(output(None,status),output(q.REFUSAL))
            self.assertFalse(r["jointly_observed"])
    def test_syntactically_nonrefusing_nonsense_does_not_get_semantic_grade(self):
        r=q.behavior(output("meaningless fixture"),output(q.REFUSAL))
        self.assertTrue(r["weak_selective_behavior"]);self.assertIsNone(r["semantic_accuracy"])


class CanonicalPreferenceChecks(unittest.TestCase):
    def test_nonempty_only_score_cannot_satisfy_both_questions(self):
        for a,b in ((-1.,-3.),(-3.,-1.),(-2.,-2.)):
            r=q.preference([a,b,a,b])
            self.assertEqual(r["question_interaction"],0.)
            self.assertFalse(r["both_weak_preferences_positive"])
    def test_positive_interaction_is_not_both_preferences(self):
        r=q.preference([-1.,-5.,-1.,-2.])
        self.assertGreater(r["question_interaction"],0.)
        self.assertFalse(r["both_weak_preferences_positive"])
    def test_common_answer_only_bias_cancels_in_interaction(self):
        r=q.preference([-2.,-4.,-3.,-1.])
        t=q.preference([-3.,-4.,-4.,-1.])
        self.assertEqual(r["question_interaction"],t["question_interaction"])
    def test_finite_reference_pair_directions(self):
        r=q.preference([-1.,-3.,-4.,-1.])
        self.assertEqual(r["matched_answer_margin"],2.)
        self.assertEqual(r["mismatched_refusal_margin"],3.)
    def test_nonfinite_boolean_and_positive_scores_rejected(self):
        for x in (float("inf"),float("nan"),True,.01):
            with self.assertRaises(c.Invalid):q.preference([x,-1.,-2.,-1.])


class CanonicalInventoryChecks(unittest.TestCase):
    def test_same_evidence_and_target_suffix_for_real_question_change(self):
        p,_=make_plan()
        for unit in p["units"]:
            a,b=unit["matched_request"],unit["mismatched_request"]
            self.assertEqual(a["evidence"],b["evidence"])
            self.assertNotEqual(a["question"],b["question"])
            self.assertTrue(unit["response"].endswith(" ".join("["+e["id"]+"]" for e in a["evidence"])))
    def test_missing_original_recipient_is_not_replaced(self):
        p,_=make_plan(True)
        self.assertEqual(p["planned_recipients"],2);self.assertEqual(p["available_pairs"],1)
        missing=next(x for x in p["units"] if x["status"]!="available")
        self.assertIsNone(missing["matched_request"]);self.assertIsNone(missing["response"])
    def test_new_generation_requests_do_not_expose_targets(self):
        p,_=make_plan()
        for row in p["public_requests"]:
            self.assertEqual(set(row),{"request_id","request"})
            self.assertEqual(row["request_id"],c.digest(row["request"]))
            self.assertEqual(set(row["request"]),{"question","options","evidence"})
    def test_input_dictionary_not_mutated(self):
        _,i=make_plan();before=c.digest(i)
        q.build_plan(i,i["public_cases"])
        self.assertEqual(c.digest(i),before)
    def test_counterpart_sources_and_dates_are_not_rewritten(self):
        p,i=make_plan();cmp={x["question_id"]:x for x in i["comparisons"]}
        for u in p["units"]:
            self.assertEqual(u["mismatched_request"],cmp[u["question_id"]]["requests"]["donor_sources"])
    def test_wrong_old_question_or_source_rejected(self):
        _,i=make_plan()
        donor=next(x for x in i["public_cases"] if x["condition"]=="donor_sources")
        donor["request"]["question"]="changed"
        with self.assertRaises(c.Invalid):q.build_plan(i,i["public_cases"])
    def test_no_qualification_from_plan(self):
        p,_=make_plan()
        self.assertFalse(p["production_accepted"]);self.assertFalse(p["independent_confirmation"])
        self.assertEqual(p["new_optimizer_updates"],0)


if __name__=="__main__":unittest.main()
