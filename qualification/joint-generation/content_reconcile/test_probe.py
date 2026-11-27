from fractions import Fraction
import unittest

import numpy as np

from content_reconcile.policy import compile_joint, greedy, repair
from content_reconcile.scoring import ce_rows, metrics, greedy_metrics
from content_reconcile.service import PROFILES, IDENTITY_ALIASES, execute
from data import DecodedObserver, outcome_from_observations
from independent.accounting import BudgetExceeded, WorkLedger
from independent.inference import FrozenGenerator
from model import JointModel
from utility import certainty_equivalent


def pad(values):
    out=np.zeros((1,12));out[0,:len(values)]=values;return out


def exact_action(p,q,t,i,k):
    a=Fraction(float(p[t]))*Fraction(float(q[t]))
    b=Fraction(float(p[i]))*Fraction(float(q[i]))
    return 1 if a>k*b else (2 if b>k*a else 0)


class ReconciliationTests(unittest.TestCase):
    def test_diagonal_joint_rule_differs_from_old_head_ratio(self):
        p,q=pad([.6,.35,.05]),pad([.05,.4,.55])
        pair,action=repair(p,q,np.array([[0,1]]),"log2")
        self.assertGreater(p[0,0],q[0,1])
        np.testing.assert_array_equal(pair,[[1,1]])
        np.testing.assert_array_equal(action,[2])

    def test_ties_exact_factor_two_and_adjacent_float(self):
        p,q=pad([.5,.25,.25]),pad([.25,.25,.5])
        _,action=repair(p,q,np.array([[0,1]]),"log2")
        self.assertEqual(int(action[0]),0)
        p[0,0]=np.nextafter(.5,1.);p[0,2]=1-p[0,0]-.25
        _,action=repair(p,q,np.array([[0,1]]),"log2")
        self.assertEqual(int(action[0]),1)
        p,q=pad([.4,.1,.3,.2]),pad([.1,.4,.3,.2])
        _,action=repair(p,q,np.array([[0,1]]),"zero")
        self.assertEqual(int(action[0]),0)

    def test_zero_and_underflow_products_use_exact_support(self):
        p,q=pad([1.,1e-200,3e-200,0.]),pad([0.,1e-200,1e-200,1.])
        for tau,k in (("zero",1),("log2",2)):
            ledger=WorkLedger("boundary")
            _,action=repair(p,q,np.array([[1,2]]),tau,ledger)
            self.assertEqual(int(action[0]),exact_action(p[0],q[0],1,2,k))
            self.assertEqual(int(action[0]),2)
            self.assertEqual(ledger.totals["exact_support_comparisons"],1)
        _,action=repair(p,q,np.array([[0,3]]),"zero")
        self.assertEqual(int(action[0]),0)

    def test_joint_pushforward_matches_independent_exact_loop(self):
        cases=((pad([.4,.1,.3,.2]),pad([.1,.4,.3,.2])),
               (pad([.75,.25]),pad([.125,.875])))
        for p,q in cases:
            for tau in ("zero","log2","infinity"):
                actual,original,_,_=compile_joint(p,q,tau)
                expected=np.zeros((12,12))
                for t in range(12):
                    for i in range(12):
                        action=0 if t==i or tau=="infinity" else exact_action(p[0],q[0],t,i,1 if tau=="zero" else 2)
                        a,b=(t,t) if action==1 else ((i,i) if action==2 else (t,i))
                        expected[a,b]+=float(Fraction(float(p[0,t]))*Fraction(float(q[0,i])))
                np.testing.assert_allclose(actual[0],expected,rtol=0,atol=1e-15)
                self.assertAlmostEqual(float(actual.sum()),1.)
                self.assertTrue(np.all(actual>=0))
                if tau=="infinity":np.testing.assert_array_equal(actual,original)

    def test_original_greedy_is_not_joint_or_marginal_map(self):
        p,q=pad([.4,.1,.3,.2]),pad([.1,.4,.3,.2])
        original,repaired,_=greedy(p,q,"log2")
        joint,_,_,_=compile_joint(p,q,"log2")
        np.testing.assert_array_equal(original,[[0,1]])
        np.testing.assert_array_equal(repaired,[[0,1]])
        self.assertEqual(int(joint.reshape(-1).argmax()),26)
        self.assertEqual(int(joint.sum(1).argmax()),2)
        self.assertEqual(int(joint.sum(2).argmax()),2)

    def test_requestwise_CE_pushforward_with_asymmetric_rewards(self):
        p,q=pad([.4,.1,.3,.2]),pad([.1,.4,.3,.2])
        joint,original,destination,_=compile_joint(p,q,"log2")
        reward=(np.arange(12)[:,None]*.03+np.arange(12)[None,:]*.01)[None,:,:]
        ledger=WorkLedger("CE")
        ce,_=ce_rows(reward.reshape(1,144),joint.reshape(1,144),ledger,"score")
        path_reward=np.take_along_axis(reward.reshape(1,144),destination,axis=1)
        expected=certainty_equivalent(path_reward,original.reshape(1,144),1.5,axis=1)
        np.testing.assert_allclose(ce,expected,rtol=0,atol=1e-15)
        wrong=joint.sum(2)[:,:,None]*joint.sum(1)[:,None,:]
        self.assertGreater(abs(float(ce[0]-certainty_equivalent(reward.reshape(1,144),wrong.reshape(1,144),1.5,axis=1)[0])),1e-5)
        value=np.vstack((path_reward,path_reward+1))
        probability=np.vstack((original.reshape(1,144),original.reshape(1,144)))
        individual=certainty_equivalent(value,probability,1.5,axis=1).mean()
        pooled=certainty_equivalent(value.reshape(1,-1),(probability/2).reshape(1,-1),1.5,axis=1)[0]
        self.assertGreater(abs(float(individual-pooled)),.01)

    def test_joint_success_and_greedy_use_decoded_semantics(self):
        p,q=pad([.4,.1,.3,.2]),pad([.1,.4,.3,.2])
        joint,_,_,_=compile_joint(p,q,"log2")
        distances=np.arange(144).reshape(12,12)/1000
        observer=DecodedObserver((np.arange(12),np.arange(12),np.zeros((12,192)),distances),np.zeros((12,12,12)))
        result=metrics(joint,np.zeros((1,12,12)),np.array([2]),observer,WorkLedger("metrics"),"score")
        self.assertAlmostEqual(float(result["joint_success"][0]),.51)
        original,repaired,_=greedy(p,q,"log2")
        result=greedy_metrics(repaired,np.array([2]),observer,WorkLedger("g"),"score")
        self.assertEqual(float(result["joint_success"][0]),0)
        self.assertEqual(float(result["pixel_mse"][0]),distances[1,2])

    def test_both_CE_helper_branches_match_original(self):
        p,q=pad([.4,.1,.3,.2]),pad([.1,.4,.3,.2])
        joint,_,_,_=compile_joint(p,q,"log2")
        for multiplier,large in ((.1,0),(10.,1)):
            reward=(np.arange(12)[:,None]*.03+np.arange(12)[None,:]*.01)[None,:,:]*multiplier
            ledger=WorkLedger("branch")
            observed,_=ce_rows(reward.reshape(1,144),joint.reshape(1,144),ledger,"score")
            expected=certainty_equivalent(reward.reshape(1,144),joint.reshape(1,144),1.5,axis=1)
            np.testing.assert_array_equal(observed,expected)
            self.assertEqual(ledger.totals["ce_large_branch"],large)

    def test_wrong_agreement_reward_and_correctness_partition_are_visible(self):
        distances=np.full((12,12),.2);np.fill_diagonal(distances,0)
        observations=(np.arange(12),np.arange(12),np.zeros((12,192)),distances)
        reward=outcome_from_observations(observations)
        self.assertAlmostEqual(float(reward[1,0,0]-reward[1,1,0]),.05)
        observer=DecodedObserver(observations,reward)
        law=np.zeros((1,12,12));law[0,0,0]=.4;law[0,1,0]=.2;law[0,0,1]=.1;law[0,1,1]=.3
        scored=metrics(law,reward[[1]],np.array([1]),observer,WorkLedger("partition"),"score")
        for key,expected in (("both_wrong",.4),("wrong_agreement",.4),("text_only_correct",.2),
                             ("image_only_correct",.1),("joint_success",.3)):
            self.assertAlmostEqual(float(scored[key][0]),expected)

    def test_runtime_profiles_aliases_and_one_final_render(self):
        self.assertEqual(len(PROFILES),6)
        self.assertEqual(len(IDENTITY_ALIASES),3)
        model=JointModel(202,12,192,seed=101)
        generator=FrozenGenerator(model,prepare_low=False)
        x=np.zeros((1,202))
        for profile in (PROFILES[0],PROFILES[3],PROFILES[5]):
            report=execute(generator,x,profile,77)
            self.assertEqual(report["ledger"]["totals"]["png_renders"],1)
            self.assertEqual(report["ledger"]["totals"]["model_forward_rows"],1)
            self.assertEqual(report["cap_violations"],0)
            if profile[2]=="compiled":self.assertIsNone(report["original_pairs"])
            if profile[0]=="identity":self.assertEqual(report["aliases"],list(IDENTITY_ALIASES))

    def test_budget_rejects_and_invalid_policy_is_not_repaired(self):
        p,q=pad([.4,.1,.3,.2]),pad([.1,.4,.3,.2])
        with self.assertRaises(BudgetExceeded):compile_joint(p,q,"log2",WorkLedger("none",total_cap=0))
        with self.assertRaises(ValueError):repair(p*2,q,np.array([[0,1]]),"zero")

    def test_generated_call_grid_has_unique_profiles_and_no_alias_executions(self):
        from content_reconcile.run import make_calls
        manifest=make_calls()
        keys=[(r["family"],r["model_seed"],r["profile"]) for r in manifest["calls"]]
        self.assertEqual(len(keys),len(set(keys)))
        for family in ("H","A"):
            rows=[r for r in manifest["calls"] if r["family"]==family]
            self.assertEqual(sum(r["requests"] for r in rows),manifest["requests_per_family"])
            self.assertEqual(sum(bool(r["aliases"]) for r in rows),3)
            self.assertTrue(all(r["profile"]=="identity" for r in rows if r["aliases"]))


if __name__=="__main__":unittest.main()
