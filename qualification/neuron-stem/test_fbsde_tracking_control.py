"""Same-law complete-world references, no model needed."""
from collections import defaultdict
from itertools import combinations, product
import math
import unittest
from fbsde_tracking_control import BeliefProblem, fit_temperature, pair_law, plan

BINDING={'source':'fixture','model':'gate','calibration':'separate-fit','scope':'test','generation':1}


def world_reference(problem, known=(), horizon=2, cost=.02):
    worlds=[]
    for indices in product(range(len(problem.pairs)),repeat=len(problem.laws)):
        mass=math.prod(problem.laws[i][j] for i,j in enumerate(indices))
        if not mass or any(indices[i]!=j for i,j in known):continue
        state=list(range(problem.actors))
        for j in indices:
            a,b=problem.pairs[j];state[a],state[b]=state[b],state[a]
        worlds.append((indices,state[problem.query],mass))
    def terminal(rows):
        z=sum(w for _,_,w in rows);p=[sum(w for _,y,w in rows if y==i)/z for i in range(problem.actors)]
        return max(0.,2*max(p)-1)
    def value(rows,seen,depth):
        best=terminal(rows)
        if depth:
            for event in range(len(problem.laws)):
                if event in seen:continue
                groups=defaultdict(list)
                for row in rows:groups[row[0][event]].append(row)
                z=sum(w for _,_,w in rows)
                v=sum(sum(w for _,_,w in g)/z*value(g,seen|{event},depth-1) for g in groups.values())-cost
                best=max(best,v)
        return best
    return value(worlds,{i for i,_ in known},horizon)


class VerificationControlTests(unittest.TestCase):
    def parity(self):
        pairs=list(combinations(range(4),2));q=[0.]*6
        q[pairs.index((0,1))]=.5;q[pairs.index((2,3))]=.5
        return BeliefProblem(4,0,[q,q],BINDING)

    def test_complementary_checks_are_not_myopic(self):
        p=self.parity()
        one=plan(p,horizon=1,cost=.1);two=plan(p,horizon=2,cost=.1)
        self.assertEqual(one['action'],'abstain');self.assertEqual(one['value'],0)
        self.assertEqual(two['action'],'verify:0');self.assertAlmostEqual(two['value'],.8)
        self.assertAlmostEqual(two['value'],world_reference(p,cost=.1))

    def test_expensive_complementary_work_is_declined(self):
        self.assertEqual(plan(self.parity(),horizon=2,cost=.6)['action'],'abstain')

    def test_full_world_reference_for_nonuniform_model(self):
        p=BeliefProblem(3,1,[[.2,.3,.5],[.5,.4,.1],[.1,.3,.6]],BINDING)
        for h in ((),((1,2),)):
            for depth in (0,1,2):
                with self.subTest(history=h,depth=depth):
                    self.assertAlmostEqual(plan(p,h,horizon=depth)['value'],world_reference(p,h,depth),places=12)

    def test_unresolved_budget_returns_no_decision(self):
        with self.assertRaisesRegex(ValueError,'node budget'):
            plan(self.parity(),max_nodes=1)

    def test_certain_terminal_uses_valid_upper_bound(self):
        p=BeliefProblem(3,0,[[1.,0.,0.]],BINDING)
        r=plan(p)
        self.assertEqual(r['nodes'],1);self.assertTrue(r['upper_bound_stop'])
        self.assertEqual(r['action'],'answer:1')

    def test_order_is_not_erased_by_feature_reuse(self):
        p=BeliefProblem(3,0,[[1.,0.,0.],[0.,1.,0.]],BINDING)
        reverse=BeliefProblem(3,0,list(reversed(p.laws)),BINDING)
        self.assertNotEqual(p.marginal(),reverse.marginal())

    def test_pair_law_uses_all_logits_and_is_shift_invariant(self):
        a,p=pair_law([1.,2.,3.],1);b,q=pair_law([101.,102.,103.],1)
        self.assertEqual(a,b);self.assertEqual(p,q);self.assertAlmostEqual(sum(p),1)
        self.assertTrue(all(0<x<1 for x in p))

    def test_calibration_selected_without_final_labels(self):
        rows=[{'scores':[5.,5.,-5.],'pair':[0,1]}]*4
        r=fit_temperature(rows)
        self.assertEqual(r['selected'],.25);self.assertFalse(r['risk_certified'])
        with self.assertRaisesRegex(ValueError,'fields'):
            fit_temperature([{**rows[0],'test_target':0}])

    def test_invalid_probabilities_and_identities(self):
        for row in ([float('nan'),0.,1.],[-.1,.6,.5],[.1,.2,.2]):
            with self.assertRaises(ValueError):BeliefProblem(3,0,[row],BINDING)
        with self.assertRaises(ValueError):BeliefProblem(3,0,[[1.,0.,0.]],{**BINDING,'generation':True})

    def test_repeated_or_future_verification_rejected(self):
        p=self.parity()
        for h in (((0,0),(0,1)),((2,0),),((0,6),)):
            with self.assertRaises(ValueError):p.marginal(h)

    def test_nonfinite_and_overflowing_logits_rejected(self):
        for s in ([float('nan'),1.,2.],[1e308,1e308,1e308],[True,0.,1.]):
            with self.assertRaises(ValueError):pair_law(s,.25)

    def test_refinement_budget_is_not_reset(self):
        p=self.parity()
        known=(); remaining=2; observed=[]
        while True:
            r=plan(p,known,horizon=remaining,cost=.02);observed.append(remaining)
            if not r['action'].startswith('verify:'):break
            i=int(r['action'].split(':')[1]);known=tuple(sorted(known+((i,0),)));remaining-=1
        self.assertEqual(observed,[2,1,0]);self.assertEqual(r['action'],'answer:0')

    def test_tiny_nll_is_not_silently_zero(self):
        r=fit_temperature([{'scores':[8.,8.,-8.],'pair':[0,1]}])
        self.assertGreater(r['losses'][0]['mean_nll'],0)

    def test_denied_planning_exposes_no_action(self):
        try:plan(self.parity(),max_nodes=1)
        except ValueError as error:
            self.assertFalse(error.evidence['returned'])
            self.assertNotIn('action',error.evidence)
        else:self.fail('must reject')

    def test_zero_support_observation_rejects(self):
        p=BeliefProblem(3,0,[[1.,0.,0.]],BINDING)
        with self.assertRaisesRegex(ValueError,'support'):p.marginal(((0,1),))

    def test_identity_changes_with_scope_or_generation(self):
        p=self.parity()
        other=BeliefProblem(4,0,p.laws,{**BINDING,'scope':'other'})
        self.assertNotEqual(p.identity,other.identity)

if __name__=='__main__':unittest.main()
