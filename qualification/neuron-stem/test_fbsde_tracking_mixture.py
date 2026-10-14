"""Whole-world controls for shared model dependence; no learned-model efficacy."""
from collections import defaultdict
from itertools import product
import math
import random
import unittest
from unittest.mock import patch

from four_gate_common import digest
from fbsde_tracking_control import BeliefProblem, plan
from fbsde_tracking_mixture import SharedHeadBelief

B = {'source':'fixture','model':'ensemble','calibration':'simulator','scope':'test','generation':1}


def enumerate_reference(problem, known=(), horizon=2, cost=.1):
    """One shared member is selected outside the product over event outcomes."""
    rows = []
    for weight, member in zip(problem.weights, problem.members):
        for sequence in product(range(len(problem.pairs)), repeat=len(problem.laws)):
            mass = weight*math.prod(member.laws[i][j] for i,j in enumerate(sequence))
            if not mass or any(sequence[i] != j for i,j in known):
                continue
            state = list(range(problem.actors))
            for j in sequence:
                a,b = problem.pairs[j]; state[a],state[b] = state[b],state[a]
            rows.append((sequence,state[problem.query],mass))
    def visit(worlds, seen, depth):
        mass = math.fsum(r[2] for r in worlds)
        p = [math.fsum(r[2] for r in worlds if r[1] == j)/mass for j in range(problem.actors)]
        label = max(range(problem.actors), key=lambda j:(p[j],-j))
        best = max(0.,2*p[label]-1);action = 'abstain' if best==0 else f'answer:{label}'
        if depth:
            for event in range(len(problem.laws)):
                if event in seen:continue
                groups = defaultdict(list)
                for row in worlds:groups[row[0][event]].append(row)
                value = math.fsum(math.fsum(r[2] for r in g)/mass*visit(g,seen|{event},depth-1)[0]
                                  for g in groups.values())-cost
                if value > best+1e-12:best,action = value,f'verify:{event}'
        return best,action,p
    return visit(rows,{i for i,_ in known},horizon)


class SharedHeadTests(unittest.TestCase):
    def repeated(self, steps=2):
        return SharedHeadBelief(3,0,[[[1.,0.,0.]]*steps,[[0.,1.,0.]]*steps],[.5,.5],B)

    def test_same_marginals_different_joint_answer_and_checks(self):
        joint=self.repeated();independent=BeliefProblem(3,0,joint.laws,B)
        self.assertEqual(joint.outcome_law(0),independent.outcome_law(0))
        self.assertEqual(joint.marginal(),[1.,0.,0.])
        self.assertEqual(independent.marginal(),[.5,.25,.25])
        self.assertEqual(plan(joint,cost=.1)['action'],'answer:0')
        self.assertEqual(plan(independent,cost=.1)['action'],'verify:0')
        self.assertAlmostEqual(plan(independent,cost=.1)['value'],.8)

    def test_check_updates_other_event_without_counting_as_another_check(self):
        p=self.repeated(3); h=((0,0),)
        self.assertEqual(p.member_posterior(h),(1.,0.))
        self.assertEqual(p.outcome_law(1,h),(1.,0.,0.))
        self.assertEqual(p.marginal(h),[0.,1.,0.])
        self.assertEqual(plan(p,horizon=1,cost=.1)['action'],'verify:0')
        self.assertAlmostEqual(plan(p,horizon=1,cost=.1)['value'],.9)
        self.assertEqual(plan(p,h,horizon=0)['action'],'answer:1')

    def test_joint_impossible_history_not_admitted_by_positive_marginals(self):
        p=self.repeated()
        self.assertGreater(p.laws[0][0]*p.laws[1][1],0)
        with self.assertRaisesRegex(ValueError,'joint model support'):p.marginal(((0,0),(1,1)))

    def test_soft_bayes_update_and_path_order_invariance(self):
        p=SharedHeadBelief(3,0,[[[.8,.1,.1],[.7,.2,.1]],[[.2,.3,.5],[.1,.4,.5]]],[.25,.75],B)
        self.assertAlmostEqual(p.member_posterior(((0,0),))[0],.2/.35)
        self.assertEqual(p.member_posterior(((0,0),(1,1))),p.member_posterior(((1,1),(0,0))))
        self.assertEqual(p.member_posterior(((0,0),)),p.member_posterior(((0,0),)))

    def test_log_conditioning_does_not_underflow_all_members(self):
        p=SharedHeadBelief(3,0,[[[1e-100,.5,.5]]*8,[[2e-100,.5,.5]]*8],[.5,.5],B)
        posterior=p.member_posterior(tuple((i,0) for i in range(8)))
        self.assertAlmostEqual(posterior[0],1/257,places=13)

    def test_single_member_matches_original_model(self):
        rows=[[.2,.3,.5],[.4,.1,.5],[.1,.8,.1]]
        p=SharedHeadBelief(3,1,[rows],[1.],B);q=BeliefProblem(3,1,rows,B)
        for h in ((),((0,2),)):
            a=plan(p,h,cost=.1);b=plan(q,h,cost=.1)
            self.assertEqual(a['action'],b['action']);self.assertAlmostEqual(a['value'],b['value'])
            self.assertEqual(p.marginal(h),q.marginal(h))

    def test_mixture_order_does_not_change_observations(self):
        p=self.repeated();q=SharedHeadBelief(3,0,[m.laws for m in reversed(p.members)],[.5,.5],B)
        self.assertEqual(p.marginal(),q.marginal())
        self.assertEqual(p.outcome_law(1,((0,0),)),q.outcome_law(1,((0,0),)))

    def test_reference_for_random_nonuniform_shared_models(self):
        rng=random.Random(179)
        for _ in range(8):
            members=[]
            for _ in range(3):
                rows=[]
                for _ in range(3):
                    xs=[rng.random()+.1 for _ in range(3)];rows.append([x/sum(xs) for x in xs])
                members.append(rows)
            p=SharedHeadBelief(3,1,members,[.2,.3,.5],B)
            for h in ((),((0,1),)):
                for depth in (0,1,2):
                    value,action,dist=enumerate_reference(p,h,depth,.1)
                    got=plan(p,h,horizon=depth,cost=.1)
                    self.assertEqual(got['action'],action);self.assertAlmostEqual(got['value'],value,places=12)
                    for a,b in zip(got['probabilities'],dist):self.assertAlmostEqual(a,b,places=12)

    def test_all_known_gives_deterministic_holder(self):
        p=self.repeated();self.assertEqual(p.outcome_law(0,((0,0),)),(1.,0.,0.))
        self.assertEqual(p.marginal(((0,0),(1,0))),[1.,0.,0.])

    def test_budget_remains_finite_and_no_unresolved_action(self):
        with self.assertRaisesRegex(ValueError,'node budget'):plan(self.repeated(3),max_nodes=1)
        self.assertEqual(plan(self.repeated(3),horizon=0)['action'],'abstain')
        self.assertEqual(plan(self.repeated(3),cost=1.)['action'],'abstain')

    def test_cpu_rejection_has_cost_but_no_action(self):
        from fbsde_tracking_control import PlanningBudgetError
        with patch('fbsde_tracking_control.time.process_time_ns',side_effect=[0,100_000_001,100_000_002]):
            with self.assertRaises(PlanningBudgetError) as caught:plan(self.repeated(3))
        self.assertFalse(caught.exception.evidence['returned'])
        self.assertNotIn('action',caught.exception.evidence)
        self.assertEqual(caught.exception.evidence['cpu_ns'],100_000_002)

    def test_mutating_inputs_does_not_rewrite_model(self):
        rows=[[[1.,0.,0.]]];p=SharedHeadBelief(3,0,rows,[1.],B);identity=p.identity
        rows[0][0].reverse();self.assertEqual(p.marginal(),[0.,1.,0.]);self.assertEqual(p.identity,identity)
        q=SharedHeadBelief(3,0,[[[1.,0.,0.]]],[1.],{**B,'generation':2})
        self.assertNotEqual(p.identity,q.identity)

    def test_malformed_components_and_prior_reject(self):
        for weights in ([1.,1.],[True,0.],[float('nan'),0.],[-.1,1.1]):
            with self.assertRaises(ValueError):SharedHeadBelief(3,0,[[[1.,0.,0.]]]*2,weights,B)
        for components in ([],[[[1.,0.,0.]]]*5,[[[1.,0.,0.]],[[1.,0.,0.]]*2]):
            with self.assertRaises(ValueError):SharedHeadBelief(3,0,components,[1/len(components)]*len(components) if components else [],B)
        p=self.repeated()
        for h in (((0,0),(0,0)),((5,0),),((0,True),)):
            with self.assertRaises(ValueError):p.marginal(h)


if __name__=='__main__':unittest.main()
