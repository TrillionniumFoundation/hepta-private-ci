"""Synthetic contract tests only. They do not rerun a pretrained model."""
import unittest
from v11_retention_gate import audit

def fixture():
    warm=[[arm,s,128,64] for arm in ("base","bridge","wide") for s in (41,47,53)]
    cont=[]
    for arm in ("natural_only","replay","contrastive"):
        for seed in (41,47,53):
            a,b=(104,41) if arm=="natural_only" else ((124,60) if (arm,seed)==("contrastive",41) else (128,64))
            cont.append([arm,seed,a,b,arm!="natural_only" and (arm,seed)!=("contrastive",41)])
    return dict(schema="hepta.bridge.result.v6",frozen_runtime_ref="7fe7e5ec7af93d2bd2645b2ac36ddb40f915ea3d",
        scope=dict(seeds=[41,47,53],train_candidates=128,paired_candidates=64,new_controlled_fresh_evaluated=False),
        warmup_columns=["arm","seed","candidate_correct_of_128","both_worlds_correct_of_64"],warmup_rows=warm,
        continuation_columns=["arm","seed","candidate_correct_of_128","both_worlds_correct_of_64","retention_passed"],continuation_rows=cont,
        gates=dict(contrastive_retention_all_seeds=False,feedback_executed=False,fresh_executed=False,ordinary_replay_substituted_for_primary=False))

class TestRetention(unittest.TestCase):
    def test_original_failure_shape(self):
        x=audit(fixture());self.assertEqual(x["status"],"NO_GO");self.assertEqual(x["seed41_paired_correct"],60)
    def test_missing_row(self):
        x=fixture();x["continuation_rows"].pop()
        with self.assertRaises(ValueError):audit(x)
    def test_fake_producer_pass(self):
        x=fixture();x["continuation_rows"][6][4]=True
        with self.assertRaises(ValueError):audit(x)
    def test_unauthorized_fresh(self):
        x=fixture();x["gates"]["fresh_executed"]=True
        with self.assertRaises(ValueError):audit(x)
    def test_bad_denominator(self):
        x=fixture();x["scope"]["paired_candidates"]=128
        with self.assertRaises(ValueError):audit(x)
    def test_primary_swapped(self):
        x=fixture();x["gates"]["ordinary_replay_substituted_for_primary"]=True
        with self.assertRaises(ValueError):audit(x)
    def test_duplicate(self):
        x=fixture();x["continuation_rows"][-1]=x["continuation_rows"][0]
        with self.assertRaises(ValueError):audit(x)
    def test_bad_seed(self):
        x=fixture();x["scope"]["seeds"]=[41,47,54]
        with self.assertRaises(ValueError):audit(x)
    def test_wrong_runtime(self):
        x=fixture();x["frozen_runtime_ref"]="substitute"
        with self.assertRaises(ValueError):audit(x)
    def test_exact_threshold(self):
        x=fixture();x["continuation_rows"][6][3]=61;x["continuation_rows"][6][4]=True;x["gates"]["contrastive_retention_all_seeds"]=True
        self.assertTrue(audit(x)["primary_retention_3seed_pass"])
    def test_negative_count(self):
        x=fixture();x["continuation_rows"][6][3]=-1
        with self.assertRaises(ValueError):audit(x)
    def test_bool_count(self):
        x=fixture();x["continuation_rows"][6][3]=True
        with self.assertRaises(ValueError):audit(x)
if __name__=="__main__":unittest.main()
