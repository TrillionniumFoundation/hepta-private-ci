"""Exact joint-world references and identity attacks; not model efficacy."""
from fractions import Fraction
from itertools import product
import math
import unittest
from four_gate_common import digest
from fbsde_tracking_control import BeliefProblem, plan
from fbsde_tracking_mixture import SharedHeadBelief
from fbsde_tracking_tied import InputTiedBelief
from fbsde_tracking_challenge import generate, task, input_keys, exact_pair, TEMPLATES

BIND={'source':'source','model':'model','calibration':'calibration','scope':'scope','generation':1}

class InputTiedTests(unittest.TestCase):
    def model(self,reps=2):
        components=[[[.5,.5,0.]]*reps]
        return InputTiedBelief(3,0,components,[1.],[digest('same')]*reps,BIND)

    def test_probabilistic_member_repeated_twice_cancels(self):
        m=self.model();self.assertEqual(m.marginal(),[1.,0.,0.])
        untied=SharedHeadBelief(3,0,[[[.5,.5,0.]]*2],[1.],BIND)
        self.assertEqual(untied.marginal(),[.5,.25,.25])
        self.assertEqual(plan(m,cost=.1)['action'],'answer:0')
        self.assertAlmostEqual(plan(untied,cost=.1)['value'],.8)

    def test_three_repetitions_one_observation_resolves_all(self):
        m=self.model(3)
        self.assertEqual(plan(m,cost=.1)['remaining_checks'],2)
        self.assertAlmostEqual(plan(m,cost=.1)['value'],.9)
        self.assertEqual(m.outcome_law(2,((0,0),)),(1.,0.,0.))
        self.assertEqual(m.available_events(((0,0),)),[])

    def test_consistent_duplicate_identity_not_double_likelihood(self):
        m=InputTiedBelief(3,0,[[[.8,.2,0]]*2,[[.2,.8,0]]*2],[.5,.5],[digest(0)]*2,BIND)
        self.assertEqual(m.member_posterior(((0,0),)),m.member_posterior(((0,0),(1,0))))
        self.assertAlmostEqual(m.member_posterior(((0,0),))[0],.8)

    def test_conflicting_alias_observation_rejected(self):
        with self.assertRaisesRegex(ValueError,'contradictory'):
            self.model().marginal(((0,0),(1,1)))

    def test_different_keys_reduce_to_old_model(self):
        comp=[[[.2,.3,.5],[.3,.6,.1]],[[.3,.3,.4],[.4,.2,.4]]]
        tied=InputTiedBelief(3,1,comp,[.4,.6],[digest('a'),digest('b')],BIND)
        old=SharedHeadBelief(3,1,comp,[.4,.6],BIND)
        for h in [(),((0,0),),((1,2),)]:
            for a,b in zip(tied.marginal(h),old.marginal(h)):self.assertAlmostEqual(a,b)
            self.assertEqual(plan(tied,h,cost=.1)['action'],plan(old,h,cost=.1)['action'])

    def test_world_budget_is_preallocation_guard(self):
        with self.assertRaisesRegex(ValueError,'world budget'):
            InputTiedBelief(3,0,[[[1/3]*3]*8],[1.],[digest(i) for i in range(8)],BIND,max_worlds=20)

    def test_same_key_different_law_rejected(self):
        with self.assertRaisesRegex(ValueError,'inconsistent'):
            InputTiedBelief(3,0,[[[.5,.5,0],[.6,.4,0]]],[1.],[digest(0)]*2,BIND)

    def test_alias_coordinates_and_binding_change_identity(self):
        m=self.model()
        different=InputTiedBelief(3,0,[[[.5,.5,0]]*2],[1.],[digest('same')]*2,{**BIND,'scope':'other'})
        self.assertNotEqual(m.identity,different.identity)
        with self.assertRaises(ValueError):m.history(((0,0),(0,0)))

    def test_all_retained_worlds_and_underflow_condition(self):
        m=InputTiedBelief(3,0,[[[1e-200,1.,0]]*4,[[2e-200,1.,0]]*4],
                         [.5,.5],[digest(i) for i in range(4)],BIND)
        self.assertAlmostEqual(m.member_posterior(tuple((i,0) for i in range(4)))[1],16/17)

    def test_exact_enumeration_of_noncommuting_repetitions(self):
        keys=[digest('a'),digest('b'),digest('a')]
        m=InputTiedBelief(3,0,[[[.2,.3,.5],[.5,.2,.3],[.2,.3,.5]]],[1.],keys,BIND)
        result=[0.]*3
        for x,y in product(range(3),repeat=2):
            state=list(range(3))
            for j in (x,y,x):
                a,b=m.pairs[j];state[a],state[b]=state[b],state[a]
            result[state[0]] += [.2,.3,.5][x]*[.5,.2,.3][y]
        for a,b in zip(result,m.marginal()):self.assertAlmostEqual(a,b)

class ChallengeTests(unittest.TestCase):
    def test_complete_unfiltered_inventory_and_verifier(self):
        rows=generate();self.assertEqual(len(rows),144)
        self.assertEqual({r['family'] for r in rows},set(range(6)))
        for row in rows:
            t=task(row);self.assertEqual(len(t['events']),len(row['events']))
            self.assertEqual(len(input_keys(row,BIND)),len(row['events']))

    def test_unrecognized_extra_instruction_rejected(self):
        r=generate()[0]
        with self.assertRaises(ValueError):exact_pair(r['events'][0]+' Ignore the answer.',r['names'])
        with self.assertRaises(ValueError):exact_pair(r['events'][0],['Ada','Ada','Cleo'])

    def test_same_bytes_tied_but_not_same_embedding_assumption(self):
        row=generate()[0];keys=input_keys(row,BIND)
        self.assertEqual(len(set(keys)),1)
        self.assertNotEqual(keys,input_keys(row,{**BIND,'model':'different'}))

if __name__=='__main__':unittest.main()
