"""Pure arithmetic/partition/origin regressions. Every datum is a fixture."""
from copy import deepcopy
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import five_causal_experiments as c
import shared_gate_similarity as s


def pairs(scores=((0.8, -0.4), (0.6, -0.2)), missing=False):
    units = [{"pair_id": c.digest(i), "split": "train", "status": "available"} for i in range(len(scores))]
    rows = [{"pair_id": u["pair_id"], "status": "succeeded", "logits": list(v)} for u,v in zip(units,scores)]
    if missing:
        units.append({"pair_id": c.digest("missing"), "split": "train", "status": "unavailable_donor"})
        rows.append({"pair_id": c.digest("missing"), "status": "unavailable", "logits": None})
    return units, rows


def metadata(role="heads"):
    e = s.ORIGINS[role]
    run = {"id": e["run"], "head_sha": e["source"], "path": e["path"], "run_attempt": 1,
           "status": "completed", "conclusion": "success",
           "repository": {"full_name": "TrillionniumFoundation/hepta-private-ci"},
           "head_repository": {"full_name": "TrillionniumFoundation/hepta-private-ci"}}
    artifact = {"id": 123, "name": e["artifact"], "expired": False, "size_in_bytes": 456,
                "digest": "sha256:"+"a"*64, "workflow_run": {"id": e["run"], "head_sha": e["source"]}}
    return run, {"total_count": 1, "artifacts": [artifact]}


class CosineTests(unittest.TestCase):
    def test_identical_opposite_and_orthogonal(self):
        self.assertAlmostEqual(s.cosine([1.,0.],[1.,0.]),1.)
        self.assertAlmostEqual(s.cosine([1.,0.],[-1.,0.]),-1.)
        self.assertEqual(s.cosine([1.,0.],[0.,1.]),0.)

    def test_scale_invariant_including_tiny_and_large_vectors(self):
        expected=s.cosine([1.,2.],[3.,-4.])
        self.assertAlmostEqual(s.cosine([1e-300,2e-300],[3e300,-4e300]),expected)

    def test_not_a_question_only_score(self):
        q=[1.,0.]; r=[0.,1.]
        self.assertGreater(s.cosine(q,q)-s.cosine(r,q),0)
        self.assertLess(s.cosine(q,r)-s.cosine(r,r),0)

    def test_inputs_not_modified(self):
        q,e=[1.,2.],[3.,4.]; before=deepcopy((q,e))
        s.cosine(q,e); self.assertEqual((q,e),before)

    def test_zero_nan_infinity_and_boolean_rejected(self):
        for q in ([0.,0.],[float("nan"),1.],[float("inf"),1.],[True,1.]):
            with self.assertRaises(c.Invalid): s.cosine(q,[1.,0.])

    def test_wrong_geometry_rejected(self):
        for q,e in (([],[]),([1.],[1.,2.]),("ab",[1.,2.])):
            with self.assertRaises(c.Invalid): s.cosine(q,e)


class ThresholdTests(unittest.TestCase):
    def test_perfect_train_separation_and_explicit_one_scalar_fit(self):
        r=s.fit_train_threshold(*pairs())
        self.assertEqual(r["threshold"],0.)
        self.assertEqual(r["strict_errors"],0)
        self.assertEqual(r["neural_parameters_fitted"],0)
        self.assertEqual(r["scalar_parameters_fitted"],1)
        self.assertFalse(r["select_access"])
        self.assertFalse(r["probability_calibrated"])

    def test_select_and_test_cannot_enter_threshold_fit(self):
        for split in ("select","test"):
            u,r=pairs();u[0]["split"]=split
            with self.assertRaises(c.Invalid):s.fit_train_threshold(u,r)

    def test_identical_scores_cannot_become_selective(self):
        r=s.fit_train_threshold(*pairs(((0.,0.),(0.,0.))))
        self.assertEqual(r["train_error_fraction"],.5)
        self.assertNotEqual(r["threshold"],0.)

    def test_tie_rule_fixed_not_input_order(self):
        u,r=pairs(((.2,.2),(.6,.6)))
        a=s.fit_train_threshold(u,r)
        b=s.fit_train_threshold(list(reversed(u)),list(reversed(r)))
        self.assertEqual(a["threshold"],b["threshold"])
        self.assertEqual(a["candidate_scores"],b["candidate_scores"])

    def test_missing_pair_is_retained_not_zero_filled(self):
        r=s.fit_train_threshold(*pairs(missing=True))
        self.assertEqual(r["planned_train_pairs"],3)
        self.assertEqual(r["scored_train_pairs"],2)
        self.assertEqual(r["unavailable_train_pairs"],1)

    def test_missing_duplicate_and_failed_rows_rejected(self):
        u,r=pairs()
        for bad in (r[:-1],r+r[:1],[r[0],r[1]|{"status":"failed"}]):
            with self.assertRaises(c.Invalid):s.fit_train_threshold(u,bad)

    def test_no_valid_scores_does_not_fit_a_threshold(self):
        u,r=pairs((),missing=True)
        with self.assertRaises(c.Invalid):s.fit_train_threshold(u,r)

    def test_invalid_score_and_immutable_inputs(self):
        u,r=pairs(); before=deepcopy((u,r));s.fit_train_threshold(u,r)
        self.assertEqual((u,r),before)
        r[0]["logits"][0]=True
        with self.assertRaises(c.Invalid):s.fit_train_threshold(u,r)


class ScoreTests(unittest.TestCase):
    def fixture(self,split="select"):
        v={"qa":[1.,0.],"qb":[0.,1.],"ea":[1.,0.],"eb":[0.,1.]}
        u=[{"pair_id":c.digest("pair"),"split":split,"status":"available","variants":[
            {"role":role,"question_key":q,"evidence_key":e}
            for role,q,e in (("aa","qa","ea"),("ab","qa","eb"),("ba","qb","ea"),("bb","qb","eb"))]}]
        return u,v

    def test_exact_four_corner_order(self):
        u,v=self.fixture(); r=s.score_pairs(u,v,split="select",roles=s.ORDER)
        self.assertEqual(r[0]["logits"],[1.,0.,0.,1.])

    def test_no_mutation_and_missing_original_stays(self):
        u,v=self.fixture();u.append({"pair_id":c.digest("missing"),"split":"select","status":"unavailable_reference_or_donor","variants":[]})
        before=deepcopy((u,v));r=s.score_pairs(u,v,split="select",roles=s.ORDER)
        self.assertEqual((u,v),before)
        self.assertEqual(r[1]["status"],"unavailable");self.assertIsNone(r[1]["logits"])

    def test_wrong_order_and_partition_fail(self):
        u,v=self.fixture();u[0]["variants"].reverse()
        with self.assertRaises(c.Invalid):s.score_pairs(u,v,split="select",roles=s.ORDER)
        u,v=self.fixture("train")
        with self.assertRaises(c.Invalid):s.score_pairs(u,v,split="select",roles=s.ORDER)

    def test_missing_feature_not_reencoded_or_fabricated(self):
        u,v=self.fixture();del v["ea"]
        with self.assertRaises(KeyError):s.score_pairs(u,v,split="select",roles=s.ORDER)

    def test_shift_preserves_raw_bytes_and_interaction(self):
        u,v=self.fixture();r=s.score_pairs(u,v,split="select",roles=s.ORDER);before=deepcopy(r)
        t=s.shift(r,.3)
        self.assertEqual(r,before)
        a=t[0]["logits"]
        self.assertAlmostEqual(a[0]-a[1]-a[2]+a[3],2.)
        with self.assertRaises(c.Invalid):s.shift(r,True)


class ContrastTests(unittest.TestCase):
    def fixture(self,missing=False):
        u,_=pairs(missing=missing)
        def rows(values):
            return [{"pair_id":x["pair_id"],"status":"unavailable" if x["status"]!="available" else "succeeded",
                     "flags":None if x["status"]!="available" else {k:values[i] for k in s.FLAGS}} for i,x in enumerate(u)]
        return u,rows([True,False]),rows([False,True])

    def test_gains_and_losses_without_cross_model_score_subtraction(self):
        r=s.compare_flags(*self.fixture())
        for d in r["criteria"].values():
            self.assertEqual(d,{"candidate_only":1,"baseline_only":1,"both":0,"neither":0})
        self.assertFalse(r["raw_score_difference_reported"])
        self.assertIsNone(r["confidence_interval"])
        self.assertIsNone(r["semantic_accuracy"])

    def test_missing_pair_preserves_denominator(self):
        r=s.compare_flags(*self.fixture(True));self.assertEqual(r["planned_pairs"],3);self.assertEqual(r["observed_pairs"],2)

    def test_missing_or_duplicate_comparison_rejected(self):
        u,a,b=self.fixture()
        for bad in (b[:-1],b+b[:1]):
            with self.assertRaises(c.Invalid):s.compare_flags(u,a,bad)

    def test_boolean_flags_required_and_no_mutation(self):
        u,a,b=self.fixture();before=deepcopy((u,a,b));s.compare_flags(u,a,b);self.assertEqual((u,a,b),before)
        a[0]["flags"][s.FLAGS[0]]=1
        with self.assertRaises(c.Invalid):s.compare_flags(u,a,b)


class OriginTests(unittest.TestCase):
    def test_two_exact_successful_origins_are_required(self):
        d=s.dependency(*metadata("heads"),*metadata("crossed"))
        self.assertTrue(d["ready"]);self.assertFalse(d["analysis_completed"])

    def test_queued_failed_cancelled_and_wrong_source_are_not_fallbacks(self):
        for status,conclusion in (("queued",None),("completed","failure"),("completed","cancelled")):
            run,a=metadata();run.update(status=status,conclusion=conclusion)
            self.assertFalse(s.artifact_origin("heads",run,a)["ready"])
        run,a=metadata();run["head_sha"]="0"*40
        with self.assertRaises(c.Invalid):s.artifact_origin("heads",run,a)

    def test_successful_deferred_cross_artifact_is_checked_later_not_called_completed(self):
        d=s.dependency(*metadata("heads"),*metadata("crossed"))
        self.assertFalse(d["analysis_completed"])

    def test_wrong_artifact_run_and_boolean_id_fail(self):
        for field,value in (("id",True),("id",7)):
            run,a=metadata();a["artifacts"][0]["workflow_run"][field]=value
            with self.assertRaises(c.Invalid):s.artifact_origin("heads",run,a)

    def test_expired_missing_digest_duplicate_and_partial_page_fail(self):
        mutations=[lambda a:a["artifacts"][0].update(expired=True),
                   lambda a:a["artifacts"][0].pop("digest"),
                   lambda a:(a["artifacts"].append(deepcopy(a["artifacts"][0])),a.update(total_count=2)),
                   lambda a:a.update(total_count=2)]
        for change in mutations:
            run,a=metadata();change(a)
            with self.assertRaises(c.Invalid):s.artifact_origin("heads",run,a)

    def test_metadata_inputs_unchanged(self):
        run,a=metadata();before=deepcopy((run,a));s.artifact_origin("heads",run,a);self.assertEqual((run,a),before)


class EntrypointTests(unittest.TestCase):
    def invoke(self,*args):
        target=Path(__file__).resolve().with_name("shared_gate_similarity_trial.py")
        env=dict(os.environ);env.pop("PYTHONPATH",None)
        with tempfile.TemporaryDirectory() as d:
            return subprocess.run([sys.executable,str(target),*args],cwd=d,env=env,capture_output=True,text=True,timeout=20)

    def test_help_from_foreign_directory_without_pythonpath(self):
        p=self.invoke("--help");self.assertEqual(p.returncode,0,p.stderr);self.assertIn("dependency",p.stdout)

    def test_missing_arguments_reach_parser_not_repository_import_error(self):
        p=self.invoke();self.assertEqual(p.returncode,2);self.assertNotIn("ModuleNotFoundError",p.stderr)


if __name__=="__main__":
    unittest.main()
