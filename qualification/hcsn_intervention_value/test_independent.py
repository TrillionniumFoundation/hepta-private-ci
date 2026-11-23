import copy
import math
import unittest

import numpy as np

from .independent import (CausalChooser, FRONTENDS, READ, STOP, WAIT, _contrast,
                          evaluate, fit_causal, opportunity, outcome, select_frontend)


def fixture():
    n=8
    y=np.arange(n)%2
    correct=(np.eye(2)[y]*2-1)[:,None,:]*np.ones((n,6,1))
    s={"scores":-correct.copy(), "read_scores":correct.copy(),
       "target":y, "dt":np.full((n,6),.48), "query_id":np.array([f"q{i}" for i in range(n)]),
       "group":np.array([f"creator{i}" for i in range(n)]), "source":np.array([f"file{i}" for i in range(n)]),
       "x":np.zeros((n,6,2))}
    return s


class ExactIntervention(unittest.TestCase):
    def test_paid_structure_and_utility(self):
        s=fixture()
        d=opportunity(s)
        self.assertTrue(d["eligible"])
        self.assertFalse(d["wait_gate_pass"])
        self.assertAlmostEqual(d["paid_gain_mean"],.7)
        self.assertEqual(d["n_paid_positive_queries"],8)
        self.assertEqual(d["per_prefix_change"][0]["corrected"],8)
        t=np.full(8,2,dtype=int)
        r=outcome(s,t,np.full(8,READ,dtype=int))
        expected=.7*math.exp(-.2*.96)-.4/.2*(1-math.exp(-.2*.96))
        self.assertAlmostEqual(r["utility"],expected)
        self.assertEqual(r["read_after_wait"],8)
        self.assertEqual(r["reads_change_at_same_prefix"]["corrected"],8)
        self.assertAlmostEqual(outcome(s,t,np.full(8,READ,dtype=int),rho=0)["utility"],.7-.4*.96)

    def test_audio_oracle_gets_later_free_information(self):
        s=fixture()
        s["scores"][:,1:,:]=s["read_scores"][:,1:,:]
        d=opportunity(s)
        # The free stop at t=1 beats the paid immediate result. Comparing only with
        # the first free STOP would incorrectly qualify the visual frontend.
        self.assertEqual(d["paid_gain_mean"],0.)
        self.assertGreater(d["wait_gain_mean"],0.)
        self.assertFalse(d["eligible"])

    def test_same_prefix_broken_counts_and_zero_gain_on_expensive_reads(self):
        s=fixture()
        s["scores"][::2]*=-1
        s["read_scores"][::2]*=-1
        d=opportunity(s,price=1.,rho=0.)
        self.assertFalse(d["eligible"])
        self.assertEqual(d["per_prefix_change"][0]["broken"],4)
        self.assertEqual(d["per_prefix_change"][0]["corrected"],4)

    def test_source_equal_weights_and_roster(self):
        s=fixture()
        s["group"][:6]="actor1"
        s["group"][6:]="actor2"
        s["scores"][:6]*=-1
        d=opportunity(s)
        self.assertAlmostEqual(d["paid_gain_mean"],.35)
        self.assertEqual(d["paid_positive_groups"],1)
        self.assertFalse(d["eligible"])
        s["source"][7]=s["source"][0]
        with self.assertRaises(ValueError):
            opportunity(s)

    def test_policy_lock_and_no_hidden_inputs(self):
        s=fixture()
        trained=fit_causal(s)
        a=trained.acts(s["scores"])
        rec=CausalChooser.from_state_dict(trained.state_dict())
        for u,v in zip(a,rec.acts(s["scores"])):
            np.testing.assert_array_equal(u,v)
        self.assertTrue((a[0]==0).all() and (a[1]==READ).all())
        t,act=rec.acts(s["scores"],"refit_no_read")
        self.assertTrue((act==STOP).all())
        test=copy.deepcopy(s)
        test["read_scores"]*=-1
        test["target"][:]=0
        np.testing.assert_array_equal(rec.acts(test["scores"])[1],a[1])
        dev=evaluate(rec,s)
        self.assertEqual(dev["immediate_baseline"],"immediate")
        self.assertFalse(dev["development_practical_pass"])
        with self.assertRaises(ValueError):
            evaluate(rec,test,stage="confirmation")
        fixed=evaluate(rec,test,stage="confirmation",immediate_baseline="immediate")
        self.assertEqual(fixed["immediate_baseline"],"immediate")

    def test_sign_test_typical_source_and_interesting_policy(self):
        a={"per_source":{str(i):1. for i in range(6)}}
        b={"per_source":{str(i):0. for i in range(6)}}
        d=_contrast(a,b,.975)
        self.assertEqual(d["exact_one_sided_sign_p"],1/64.)
        self.assertEqual(d["one_sided_median_lower"],1.)
        a["per_source"]["0"]=0.
        self.assertEqual(_contrast(a,b,.975)["exact_one_sided_sign_p"],7/64.)

    def test_select_qualifying_frontend_by_deployed_value_not_oracle(self):
        def panel(no_read,immediate,utility,eligible=True):
            return {"train":{"eligible":eligible}, "dev":{"eligible":eligible},
                    "dev_policy":{"stage":"development","primary_comparators":["refit_no_read","immediate"],
                                  "policies":{"full":{"utility":utility}},
                                  "contrasts":{k:{"mean_paired_source_gain":v} for k,v in
                                               (("immediate",immediate),("refit_no_read",no_read))}}}
        p={FRONTENDS[0]:panel(.1,.1,.6),FRONTENDS[1]:panel(.2,-.1,.8),
           FRONTENDS[2]:panel(1.,1.,1.,False),FRONTENDS[3]:{"available":False}}
        self.assertEqual(select_frontend(p),FRONTENDS[0])
        p[FRONTENDS[0]]["train"]["eligible"]=False
        self.assertEqual(select_frontend(p),FRONTENDS[1])
        p[FRONTENDS[1]]["dev"]["eligible"]=False
        self.assertIsNone(select_frontend(p))


if __name__=="__main__":
    unittest.main()
