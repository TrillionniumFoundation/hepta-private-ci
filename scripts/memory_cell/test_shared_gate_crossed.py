"""Synthetic regression fixtures; not independent natural-task evidence."""
from copy import deepcopy
import unittest
import torch

import five_causal_experiments as c
import shared_question_gate as g
import shared_gate_crossed_evidence as x
from shared_gate_crossed_trial import dependency
from experiments.shared_stem_cell.execution import parameters
from test_shared_question_gate import inputs
from test_select_question_relevance import fixture
import select_question_relevance as q


def material(missing=False):
    inventory, cases, _ = fixture(missing)
    selected = q.build_plan(inventory, cases)
    train, _ = inputs()
    original = g.public_plan(train, selected)
    return original, selected, inventory


class PlanTests(unittest.TestCase):
    def test_four_corners_two_questions_two_evidence(self):
        plan = x.build_plan(*material())
        for unit in plan["units"]:
            aa, ab, ba, bb = unit["variants"]
            self.assertEqual([v["role"] for v in unit["variants"]], list(x.ORDER))
            self.assertEqual(aa["question_key"], ab["question_key"])
            self.assertEqual(ba["question_key"], bb["question_key"])
            self.assertEqual(aa["evidence_key"], ba["evidence_key"])
            self.assertEqual(ab["evidence_key"], bb["evidence_key"])
            self.assertNotEqual(aa["evidence_key"], ab["evidence_key"])

    def test_original_pair_scores_have_exact_references(self):
        a,b,d = material(); plan = x.build_plan(a,b,d)
        old = {u["pair_id"]:u for u in a["units"]}
        for unit in plan["units"]:
            ab, bb = unit["variants"][1], unit["variants"][3]
            self.assertEqual(bb["question_key"],old[unit["pair_id"]]["variants"][0]["question_key"])
            self.assertEqual(ab["question_key"],old[unit["pair_id"]]["variants"][1]["question_key"])

    def test_no_new_questions_or_donors(self):
        a,b,d = material(); plan = x.build_plan(a,b,d)
        self.assertEqual([(u["question_id"],u["donor_question_id"]) for u in plan["units"]],
                         [(u["question_id"],u["donor_question_id"]) for u in b["units"]])
        self.assertFalse(plan["new_donor_selection"])
        self.assertEqual(plan["new_optimizer_updates"],0)

    def test_missing_pair_retained_without_features(self):
        plan=x.build_plan(*material(True))
        self.assertEqual(len(plan["units"]),2)
        missing=[u for u in plan["units"] if u["status"]!="available"]
        self.assertEqual(len(missing),1); self.assertEqual(missing[0]["variants"],[])

    def test_additional_features_are_only_original_select_evidence(self):
        import json
        a,b,d=material(); plan=x.build_plan(a,b,d)
        self.assertTrue(plan["additional_features"])
        for f in plan["additional_features"]:
            self.assertEqual(f["scope"][0],"select"); self.assertEqual(f["scope"][2],"evidence")
            value=json.loads(f["text"])
            self.assertEqual(set(value),{"evidence"})
            self.assertTrue(all("1 January 2023" in e["text"] for e in value["evidence"]))

    def test_no_input_mutation(self):
        args=material(); before=c.digest(args); result=x.build_plan(*args)
        self.assertEqual(before,c.digest(args))
        result["units"][0]["variants"][0]["question_key"]="changed"
        self.assertEqual(before,c.digest(args))

    def test_reordered_feature_inventory_does_not_change_plan(self):
        a,b,d=material(); expected=x.build_plan(a,b,d)
        a["features"].reverse()
        got=x.build_plan(a,b,d)
        self.assertEqual(got["units"],expected["units"])
        self.assertEqual(got["additional_features"],expected["additional_features"])

    def reject(self, change):
        a,b,d=material(); change(a,b,d)
        with self.assertRaises((c.Invalid,KeyError)): x.build_plan(a,b,d)

    def test_duplicate_original_feature_rejected(self):
        self.reject(lambda a,b,d:a["features"].append(deepcopy(a["features"][0])))

    def test_missing_original_component_rejected(self):
        def change(a,b,d):
            key=next(u for u in a["units"] if u["split"]=="select")["variants"][0]["question_key"]
            a["features"]=[f for f in a["features"] if f["key"]!=key]
        self.reject(change)

    def test_changed_old_score_order_rejected(self):
        self.reject(lambda a,b,d:next(u for u in a["units"] if u["split"]=="select")["variants"].reverse())

    def test_changed_inventory_pin_rejected(self):
        self.reject(lambda a,b,d:d["pool"].reverse())

    def test_wrong_partition_rejected(self):
        self.reject(lambda a,b,d:b["units"][0].update(split="train"))

    def test_changed_question_rejected(self):
        self.reject(lambda a,b,d:b["units"][0]["matched_request"].update(question="replacement"))

    def test_changed_evidence_rejected(self):
        self.reject(lambda a,b,d:b["units"][0]["matched_request"]["evidence"][0].update(text="changed"))

    def test_missing_recipient_rejected(self):
        self.reject(lambda a,b,d:b["units"].pop())


class InteractionTests(unittest.TestCase):
    def test_arbitrary_additive_main_effects_cancel(self):
        for qa,qb,ea,eb,bias in ((3,8,7,-2,9),(-100,50,20,90,0),(1,1,1,1,1)):
            values=[qa+ea+bias,qa+eb+bias,qb+ea+bias,qb+eb+bias]
            self.assertEqual(x.interaction(values)["interaction"],0)
            self.assertFalse(x.interaction(values)["both_question_rankings"])

    def test_one_way_question_preference_not_crossed_relevance(self):
        r=x.interaction([1.,1.,2.,2.])
        self.assertGreater(r["donor_evidence_question_margin"],0)
        self.assertEqual(r["interaction"],0)
        self.assertFalse(r["both_question_rankings"])

    def test_positive_interaction_is_not_all_four_signs(self):
        r=x.interaction([3.,2.,1.,1.])
        self.assertGreater(r["interaction"],0)
        self.assertFalse(r["both_question_rankings"])
        self.assertFalse(r["all_four_threshold_directions"])

    def test_rankings_are_not_thresholds(self):
        r=x.interaction([3.,2.,2.,3.])
        self.assertTrue(r["both_question_rankings"] and r["both_evidence_rankings"])
        self.assertFalse(r["all_four_threshold_directions"])

    def test_four_opposite_signs_still_not_semantic_grade(self):
        r=x.interaction([1.,-1.,-1.,1.])
        self.assertTrue(r["all_four_threshold_directions"])
        self.assertIsNone(r["semantic_accuracy"])
        self.assertFalse(r["reader_adequacy_established"])

    def test_ties_and_constant_refusal_fail(self):
        for z in (0.,-2.,2.):
            r=x.interaction([z]*4)
            self.assertFalse(r["both_question_rankings"] or r["both_evidence_rankings"] or r["all_four_threshold_directions"])

    def test_nonfinite_boolean_and_bad_shape_rejected(self):
        for values in ([True,0.,0.,0.],[float("nan"),0.,0.,0.],[float("inf")]*4,[1.,2.],(1.,2.,3.,4.)):
            with self.assertRaises(c.Invalid):x.interaction(values)

    def test_saved_linear_head_has_zero_crossed_interaction(self):
        torch.manual_seed(3); model=g.QuestionGate(8,kind="linear")
        with torch.no_grad():
            for p in model.parameters():p.normal_()
            qa,qb,ea,eb=torch.randn(4,8)
            scores=model(torch.stack([qa,qa,qb,qb]),torch.stack([ea,eb,ea,eb])).tolist()
        self.assertAlmostEqual(x.interaction(scores)["interaction"],0,places=5)

    def test_gated_interaction_without_parameter_update(self):
        model=g.QuestionGate(8,rank=2)
        with torch.no_grad():
            model.q_down.weight.zero_();model.q_down.weight[:,0]=1
            model.e_gate.weight.zero_();model.e_gate.weight[0,0]=3;model.e_gate.weight[1,0]=-3
            model.read.copy_(torch.tensor([1.,-1.]))
        model.eval().requires_grad_(False); before=parameters(model)
        a=torch.zeros(8);a[0]=1;b=-a
        with torch.no_grad():scores=model(torch.stack([a,a,b,b]),torch.stack([a,b,a,b])).tolist()
        self.assertTrue(x.interaction(scores)["all_four_threshold_directions"])
        self.assertEqual(before,parameters(model))


class SummaryTests(unittest.TestCase):
    def fixture(self):
        units=[{"pair_id":"a","status":"available","family":"f"},
               {"pair_id":"b","status":"unavailable_reference_or_donor","family":"f"}]
        rows=[{"pair_id":"a","status":"succeeded","logits":[1.,-1.,-1.,1.]},
              {"pair_id":"b","status":"unavailable","logits":None}]
        return units,rows

    def test_missing_stays_in_denominator(self):
        r=x.summarize(*self.fixture())
        self.assertEqual((r["planned_pairs"],r["scored_pairs"],r["unavailable_pairs"]),(2,1,1))
        self.assertEqual(r["mean_interaction"],4.)

    def test_failure_is_unknown_not_zero_effect(self):
        u,r=self.fixture();r[0].update(status="failed",logits=None)
        out=x.summarize(u,r)
        self.assertEqual(out["failed_pairs"],1);self.assertIsNone(out["mean_interaction"])

    def test_missing_pair_cannot_become_observed(self):
        u,r=self.fixture();r[1].update(status="succeeded",logits=[1.,-1.,-1.,1.])
        with self.assertRaises(c.Invalid):x.summarize(u,r)

    def test_no_denominator_deletion_or_duplicates(self):
        u,r=self.fixture()
        for rows in (r[:1],r+r[:1]):
            with self.assertRaises(c.Invalid):x.summarize(u,rows)

    def test_unequal_family_sizes_report_family_macro(self):
        u,r=self.fixture();u=u[:1];r=r[:1]
        u.extend([{"pair_id":"c","status":"available","family":"g"},{"pair_id":"d","status":"available","family":"g"}])
        r.extend([{"pair_id":k,"status":"succeeded","logits":[0.,0.,0.,0.]} for k in ("c","d")])
        out=x.summarize(u,r)
        self.assertEqual(out["family_macro_interaction"],2.)
        self.assertAlmostEqual(out["mean_interaction"],4/3)


class DependencyTests(unittest.TestCase):
    def fixture(self):
        repository={"full_name":"TrillionniumFoundation/hepta-private-ci"}
        run={"id":x.GATE_RUN,"head_sha":x.GATE_SOURCE,"path":".github/workflows/hepta-shared-question-gate.yml",
             "repository":repository,"head_repository":repository,"run_attempt":1,"status":"completed","conclusion":"success"}
        artifact={"id":123,"name":x.GATE_ARTIFACT,"expired":False,"size_in_bytes":100,
                  "digest":"sha256:"+"a"*64,"workflow_run":{"id":x.GATE_RUN,"head_sha":x.GATE_SOURCE}}
        return run,{"total_count":1,"artifacts":[artifact]}

    def test_exact_complete_origin_selected(self):
        result=dependency(*self.fixture())
        self.assertTrue(result["ready"]);self.assertFalse(result["model_execution_completed"])

    def test_queued_or_failed_never_loads_candidate(self):
        for status,conclusion in (("queued",None),("in_progress",None),("completed","failure"),("completed","cancelled")):
            r,a=self.fixture();r.update(status=status,conclusion=conclusion)
            result=dependency(r,a)
            self.assertFalse(result["ready"]);self.assertNotIn("artifact_id",result)

    def test_other_source_run_or_repository_rejected(self):
        for field,value in (("id",1),("head_sha","b"*40),("repository",{"full_name":"other/repo"})):
            r,a=self.fixture();r[field]=value
            with self.assertRaises(c.Invalid):dependency(r,a)

    def test_incomplete_or_duplicate_artifact_list_rejected(self):
        r,a=self.fixture();a["total_count"]=2
        with self.assertRaises(c.Invalid):dependency(r,a)
        a["artifacts"].append(deepcopy(a["artifacts"][0]))
        with self.assertRaises(c.Invalid):dependency(r,a)

    def test_expiry_and_missing_digest_rejected(self):
        for field,value in (("expired",True),("digest",None),("size_in_bytes",0)):
            r,a=self.fixture();a["artifacts"][0][field]=value
            with self.assertRaises(c.Invalid):dependency(r,a)

    def test_artifact_run_binding_required(self):
        r,a=self.fixture();a["artifacts"][0]["workflow_run"]["id"]=1
        with self.assertRaises(c.Invalid):dependency(r,a)


if __name__ == "__main__":
    unittest.main()
