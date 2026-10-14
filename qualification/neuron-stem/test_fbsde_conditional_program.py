"""Stateful induction, actual-state leakage and family-coverage regressions."""
from itertools import permutations
import unittest
from unittest.mock import patch
from four_gate_common import digest
from fbsde_conditional_program import ConditionalProgramBelief, PROGRAMS, OPS, transition
from fbsde_conditional_data import generate, observe
from fbsde_conditional_execute import execute
from fbsde_effect_family import EffectFamily, ALL, FamilyConflict
from fbsde_tracking_control import plan, PlanningBudgetError


class ConditionalTests(unittest.TestCase):
    def public(self, n=3):
        return dict(source_id='unit',names=['Mira','Nolan','Orla'],query=0,
            events=['Mira exchanges with Nolan if Mira holds amber; Orla waits.']*n)

    def test_same_rule_can_change_realized_effect(self):
        p=self.public(); _,truth,effects,_=observe(p)
        self.assertNotEqual(effects[0],effects[1])
        h=tuple((i,OPS.index(e)) for i,e in enumerate(effects[:2]))
        model=ConditionalProgramBelief(p); self.assertEqual(model.history(h),h)
        self.assertEqual(model.marginal(h)[truth],1)
        old=EffectFamily(p,supports=(ALL,))
        with self.assertRaises(FamilyConflict): old.history(h)

    def test_more_instances_remain_informative_after_first_check(self):
        m=ConditionalProgramBelief(self.public())
        _,_,effects,_=observe(self.public()); h=((0,OPS.index(effects[0])),)
        self.assertIn(1,m.available_events(h))
        self.assertLess(m.posterior_summary(h)['compatible_worlds'],len(m.worlds))
        self.assertFalse(m.posterior_summary(h)['semantic_certificate'])

    def test_marginals_use_each_candidates_own_predecessor(self):
        m=ConditionalProgramBelief(self.public()); found=False
        for rules,effects,states in m.worlds:
            for i,d in enumerate(m.descriptions):
                op,nxt=transition(PROGRAMS[rules[0]],d['roles'],states[i])
                self.assertEqual((OPS.index(op),nxt),(effects[i],states[i+1]))
            blind=[OPS.index(transition(PROGRAMS[rules[0]],d['roles'],m.initial)[0]) for d in m.descriptions]
            found |= list(effects)!=blind
        self.assertTrue(found)

    def test_complete_history_keeps_every_covered_true_program(self):
        for initial in OPS:
            m=ConditionalProgramBelief(self.public(),initial=initial)
            for rule,effects,states in m.worlds:
                h=tuple(enumerate(effects)); self.assertEqual(m.marginal(h)[states[-1][m.query]],1)
                self.assertIn(rule[0],m.posterior_summary(h)['program_support'][0])

    def test_repeated_reads_do_not_add_likelihood(self):
        m=ConditionalProgramBelief(self.public()); r=plan(m,horizon=1)
        self.assertEqual(r['probabilities'],plan(m,horizon=1)['probabilities'])
        with self.assertRaisesRegex(ValueError,'unique'):m.history(((0,0),(0,0)))

    def test_observation_order_does_not_change_posterior(self):
        m=ConditionalProgramBelief(self.public());effects=m.worlds[9][1]
        h=((0,effects[0]),(2,effects[2]));self.assertEqual(m.information_state(h),m.information_state(h[::-1]))

    def test_impossible_history_is_not_normalized(self):
        m=ConditionalProgramBelief(self.public()); impossible=next(h for h in
            (((0,a),(1,b),(2,c)) for a in range(6) for b in range(6) for c in range(6))
            if not any(all(w[1][i]==o for i,o in h) for w in m.worlds))
        with self.assertRaisesRegex(ValueError,'outside conditional'):m.history(impossible)

    def test_family_caps_preflight(self):
        p=self.public();p['events']=[t+' '*i for i,t in enumerate(p['events'])]
        with self.assertRaisesRegex(ValueError,'world budget'):ConditionalProgramBelief(p)
        with self.assertRaisesRegex(ValueError,'world budget'):ConditionalProgramBelief(self.public(),max_worlds=32)

    def test_bindings_include_initial_scope_and_source(self):
        a=self.public();b={**a,'source_id':'different'}
        self.assertNotEqual(ConditionalProgramBelief(a).binding,ConditionalProgramBelief(b).binding)
        self.assertNotEqual(ConditionalProgramBelief(a).identity,ConditionalProgramBelief(a,initial=(1,0,2)).identity)

    def test_returned_marginal_cannot_mutate_model(self):
        m=ConditionalProgramBelief(self.public()); x=m.marginal();x[0]=100
        self.assertLessEqual(max(m.marginal()),1)

    def test_foreign_or_truth_bearing_observation_rejects(self):
        p=self.public();reveal,_,_,_=observe(p)
        def wrong(i,h):return {**reveal(i,h),'predecessor':[0,1,2]}
        with self.assertRaisesRegex(ValueError,'bound selected'):execute(p,'conditional_probe',wrong)

    def test_nonbijective_denial_keeps_check_and_no_answer(self):
        p=self.public();reveal,_,_,_=observe(p)
        r=execute(p,'conditional_probe',lambda i,h:{**reveal(i,h),'effect':(1,1,2)})
        self.assertEqual(r['reason'],'unsupported_nonbijective_effect');self.assertIsNone(r['holder'])
        self.assertEqual(len(r['checks']),1)

    def test_budget_error_cannot_return_action(self):
        m=ConditionalProgramBelief(self.public())
        with self.assertRaises(PlanningBudgetError) as c:plan(m,horizon=2,max_nodes=1)
        self.assertFalse(c.exception.evidence['returned']);self.assertNotIn('action',c.exception.evidence)

    def test_all_states_are_permutations_and_query_is_public(self):
        for row in generate()[::27]:
            m=ConditionalProgramBelief(row['public'])
            self.assertTrue(all(s in OPS for _,_,states in m.worlds for s in states))
        with self.assertRaises(ValueError):ConditionalProgramBelief({**self.public(),'truth':0})

    def test_typed_bounds(self):
        for state in ((0,0,2),(False,1,2),[0,1,2]):
            with self.assertRaises(ValueError):ConditionalProgramBelief(self.public(),initial=state)
        for h in (((True,1),),((0,False),),((4,1),)):
            with self.assertRaises(ValueError):ConditionalProgramBelief(self.public()).history(h)

    def test_independent_transition_table_and_value_reference(self):
        from fbsde_conditional_reference import Reference
        for row in generate()[::18]:
            public=row['public'];m=ConditionalProgramBelief(public);ref=Reference(public)
            for depth in range(3):
                got=plan(m,horizon=depth);value,action=ref.choose((),depth)
                self.assertEqual(got['action'],action);self.assertAlmostEqual(got['value'],value,places=12)

    def test_independent_source_interpretation(self):
        from fbsde_conditional_reference import actual
        for row in generate():
            observed=observe(row['public'])
            self.assertEqual(actual(row['public']),(observed[2],observed[1]))

    def test_answer_unanimity_does_not_identify_unseen_state_rule(self):
        p=self.public();m=ConditionalProgramBelief(p);effects=observe(p)[2]
        h=tuple((i,OPS.index(e)) for i,e in enumerate(effects[:2]))
        report=m.posterior_summary(h);rules=report['program_support'][0]
        self.assertEqual(max(m.marginal(h)),1)
        self.assertFalse(report['program_set_identified'])
        self.assertGreater(len({transition(PROGRAMS[i],(0,1,2),(0,2,1))[1] for i in rules}),1)

if __name__=='__main__':unittest.main()
