import itertools
import math
import unittest
from scipy.optimize import linprog
from scipy.stats import binom

from ..ndu_jac.core import Outcome, evaluate
from ..ndu_jac.policy_gate import guarded_update
from .confidence import (Atom, structural_support, probability_boxes, box_expectation,
    policy_intervals, certified_update, propagated_gain_lower)


class ConfidenceTests(unittest.TestCase):
    def test_box_moment_matches_independent_lp_including_zero_atoms(self):
        bounds=((0.,.4),(.1,.8),(.2,.9))
        weights=(.003,.4,1.4)
        for maximize in (False,True):
            solution=linprog([(-1 if maximize else 1)*x for x in weights],
                A_eq=[[1,1,1]],b_eq=[1],bounds=bounds,method='highs')
            self.assertTrue(solution.success)
            self.assertAlmostEqual(box_expectation(weights,bounds,maximize),
                (-1 if maximize else 1)*solution.fun,places=12)

    def test_fixed_sample_binomial_coverage_by_exhaustive_count_enumeration(self):
        support={'s':{'a':(Atom(1.,0.,0.,0.,None),Atom(0.,0.,0.,0.,None))}}
        n=8
        intervals=[probability_boxes(support,{'s':{'a':[k,n-k]}},alpha=.2)[0]['s']['a']
                   for k in range(n+1)]
        # Each coordinate gets .1 two-sided error; event is both coordinates.
        for j in range(101):
            p=j/100
            covered=sum(binom.pmf(k,n,p) for k,b in enumerate(intervals)
                if b[0][0]-1e-14<=p<=b[0][1]+1e-14 and b[1][0]-1e-14<=1-p<=b[1][1]+1e-14)
            self.assertGreaterEqual(covered,.8-1e-12)

    def test_same_bank_policy_selection_has_uniform_value_coverage(self):
        atoms=(Atom(1.,0.,0.,0.,None),Atom(-.4,0.,0.,0.,None))
        support={'s':{'a':atoms,'b':(Atom(.2,0.,0.,0.,None),)}}
        boxes={'s':{'a':((.2,.8),(.2,.8)),'b':((1.,1.),)}}
        for p in (.2,.35,.5,.65,.8):
            truth={'s':{'a':(Outcome(p,reward=1.),Outcome(1-p,reward=-.4)),
                        'b':(Outcome(1.,reward=.2),)}}
            for mix in (0.,.1,.3,.7,1.):
                policy={'s':{'a':mix,'b':1-mix}}
                lower,upper=policy_intervals(support,'s',policy,boxes)['root']
                v=evaluate(truth,'s',policy,eta=2.,rho=.17)['value']
                self.assertLessEqual(lower,v+1e-12)
                self.assertGreaterEqual(upper,v-1e-12)

    def test_delayed_gain_propagates_through_unchanged_root(self):
        truth={'r':{'go':(Outcome(1.,duration=1.,next_state='s'),)},
               's':{'good':(Outcome(1.,reward=1.),),'bad':(Outcome(1.,reward=0.),)}}
        base={'r':{'go':1.},'s':{'good':.5,'bad':.5}}
        proposal={'r':{'go':1.},'s':{'good':1.,'bad':0.}}
        support=structural_support(truth)
        boxes={s:{a:((1.,1.),) for a in row} for s,row in support.items()}
        result=certified_update(support,'r',base,proposal,boxes,fee=.01)
        self.assertEqual(result['decision'],'adopt')
        self.assertEqual(result['root_local_advantage_lower'],0.)
        actual=evaluate(truth,'r',result['policy'],eta=2.,rho=.17)['value']-evaluate(truth,'r',base,eta=2.,rho=.17)['value']
        self.assertAlmostEqual(actual,result['proposed_gain_lower'],places=12)
        old=guarded_update(base,proposal,result['baseline_bounds']['q'],'r',.01)
        self.assertEqual(old['decision'],'no-update')

    def test_gain_bound_survives_uncertain_laws_and_mixed_terminal_branches(self):
        support={'r':{'go':(Atom(0.,.01,0.,1.,'s'),Atom(.2,0.,0.,2.,None)),
                      'stop':(Atom(0.,0.,0.,0.,None),)},
                 's':{'good':(Atom(1.,0.,0.,0.,None),Atom(.5,0.,0.,0.,None)),
                      'bad':(Atom(0.,0.,0.,0.,None),)}}
        boxes={'r':{'go':((.3,.7),(.3,.7)),'stop':((1.,1.),)},
               's':{'good':((.2,.8),(.2,.8)),'bad':((1.,1.),)}}
        base={'r':{'go':.8,'stop':.2},'s':{'good':.4,'bad':.6}}
        proposed={'r':{'go':1.,'stop':0.},'s':{'good':1.,'bad':0.}}
        result=certified_update(support,'r',base,proposed,boxes,fee=0.)
        self.assertGreater(result['proposed_gain_lower'],0.)
        for p,q in itertools.product((.3,.4,.5,.6,.7),(.2,.35,.5,.65,.8)):
            truth={'r':{'go':(Outcome(p,cost=.01,duration=1.,next_state='s'),Outcome(1-p,reward=.2,duration=2.)),
                        'stop':(Outcome(1.),)},
                   's':{'good':(Outcome(q,reward=1.),Outcome(1-q,reward=.5)),
                        'bad':(Outcome(1.),)}}
            gain=evaluate(truth,'r',result['policy'],eta=2.,rho=.17)['value']-evaluate(truth,'r',base,eta=2.,rho=.17)['value']
            self.assertGreaterEqual(gain+1e-12,result['proposed_gain_lower'])

    def test_false_candidate_rejected_and_paid_cost_preserved(self):
        truth={'s':{'a':(Outcome(1.,reward=1.),),'b':(Outcome(1.),)}}
        support=structural_support(truth)
        boxes={'s':{'a':((1.,1.),),'b':((1.,1.),)}}
        base={'s':{'a':1.,'b':0.}}
        proposed={'s':{'a':0.,'b':1.}}
        result=certified_update(support,'s',base,proposed,boxes,fee=.01)
        self.assertEqual(result['decision'],'no-update')
        self.assertEqual(result['policy'],base)
        self.assertEqual(result['returned_net_lower'],-.01)
        with self.assertRaises(ValueError):
            propagated_gain_lower(support,'s',result['baseline_bounds'],base,boxes,{'s':-.01})

if __name__=='__main__':
    unittest.main()
