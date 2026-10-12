"""Role hypotheses, selected evidence and nonanticipative planning contracts."""
from itertools import permutations
import unittest
from unittest.mock import patch
from four_gate_common import digest
from fbsde_role_program import RoleProgramBelief, describe, PAIRS
from fbsde_role_data import FRAMES, operation
from fbsde_role_audit import reference
from fbsde_role_study import probe
from fbsde_tracking_control import plan, PlanningBudgetError
from fbsde_outcome_policy import execute

NAMES=('Gina','Hugo','Iris')
BINDING=dict(source='s',model='m',calibration='c',scope='unit',generation=3)


class RoleTests(unittest.TestCase):
    def problem(self,frames=None,prior='uniform',max_worlds=8192):
        texts=frames or [FRAMES[2].format(a='Gina',b='Iris',c='Hugo'),FRAMES[2].format(a='Hugo',b='Iris',c='Gina')]
        desc=[describe(t,NAMES) for t in texts]
        return RoleProgramBelief(2,desc,[(.2,.3,.5)]*len(desc),BINDING,prior=prior,max_worlds=max_worlds),texts,desc

    def test_all_role_permutations_share_rule_but_not_actor_pair(self):
        for frame in FRAMES:
            descriptors=[describe(frame.format(a=NAMES[a],b=NAMES[b],c=NAMES[c]),NAMES) for a,b,c in permutations(range(3))]
            self.assertEqual(len({d['key'] for d in descriptors}),1)
            rules=[d['emissions'].index(PAIRS.index(tuple(sorted((a,b))))) for d,(a,b,c) in zip(descriptors,permutations(range(3)))]
            self.assertEqual(len(set(rules)),1)
            for a,b,c in permutations(range(3)):
                self.assertEqual(operation(frame.format(a=NAMES[a],b=NAMES[b],c=NAMES[c]),NAMES),tuple(sorted((a,b))))

    def test_negation_and_extra_context_are_not_removed(self):
        a=describe('Gina trades with Hugo; Iris watches.',NAMES)
        b=describe('Gina does not trade with Hugo; Iris watches.',NAMES)
        self.assertNotEqual(a['key'],b['key'])
        self.assertEqual(describe('Gina trades with Hugo.',NAMES)['roles'],(0,1,2))

    def test_verification_transfers_rule_across_names(self):
        p,texts,d=self.problem(); o=PAIRS.index(operation(texts[0],NAMES));other=PAIRS.index(operation(texts[1],NAMES))
        self.assertNotEqual(o,other)
        self.assertEqual(p.outcome_law(1,((0,o),)),tuple(float(j==other) for j in range(3)))
        self.assertEqual(p.available_events(((0,o),)),[])
        self.assertEqual(p.marginal(((0,o),)),p.marginal(((0,o),(1,other))))

    def test_verified_contradiction_rejects(self):
        p,texts,d=self.problem();o=PAIRS.index(operation(texts[0],NAMES));correct=PAIRS.index(operation(texts[1],NAMES))
        with self.assertRaisesRegex(ValueError,'contradiction'):p.marginal(((0,o),(1,(correct+1)%3)))

    def test_joint_and_independent_models_share_initial_event_marginals(self):
        p,_,_=self.problem(prior='head')
        for i,law in enumerate(p.laws):
            for a,b in zip(law,p.outcome_law(i)):self.assertAlmostEqual(a,b)

    def test_original_planner_matches_independent_world_enumeration(self):
        for prior in ('uniform','head'):
            for n in (2,3,4):
                texts=[FRAMES[i%2].format(a=NAMES[i%3],b=NAMES[(i+1)%3],c=NAMES[(i+2)%3]) for i in range(n)]
                p,_,d=self.problem(texts,prior);st,choose=reference(p.query,d,p.priors)
                try:
                    for h in ((),((0,0),),((0,1),),((0,2),)):
                        for depth in range(3):
                            a=plan(p,h,horizon=depth);v,b=choose(h,depth)
                            self.assertEqual(a['action'],b);self.assertAlmostEqual(a['value'],v)
                finally:st.cache_clear();choose.cache_clear()

    def test_source_only_revealed_for_chosen_events(self):
        p,texts,_=self.problem();calls=[]
        def reveal(e):calls.append(e);return PAIRS.index(operation(texts[e],NAMES))
        r=execute(p,'two_step',reveal)
        self.assertEqual(calls,[x['event'] for x in r['checks']]);self.assertLessEqual(len(calls),2)
        self.assertIsNone(r['route'])

    def test_insufficient_cheap_probe_abstains_not_free_verification(self):
        texts=[FRAMES[i].format(a='Gina',b='Hugo',c='Iris') for i in range(3)]
        p,_,_=self.problem(texts);r=probe(p,lambda i:0)
        self.assertEqual(len(r['checks']),2);self.assertIsNone(r['holder'])

    def test_world_capacity_before_materialization(self):
        texts=[FRAMES[0].format(a='Gina',b='Hugo',c='Iris')+' '+str(i) for i in range(9)]
        with self.assertRaisesRegex(ValueError,'world budget'):self.problem(texts)

    def test_forged_descriptor_or_zero_prior_rejects(self):
        d=describe(FRAMES[0].format(a='Gina',b='Hugo',c='Iris'),NAMES)
        with self.assertRaisesRegex(ValueError,'emission identity'):
            RoleProgramBelief(2,[dict(d,key=digest('other'))],[(1/3,)*3],BINDING)
        with self.assertRaisesRegex(ValueError,'full prior support'):
            RoleProgramBelief(2,[d],[(1.,0.,0.)],BINDING)

    def test_no_aliasing_and_no_cross_generation_identity(self):
        p,_,desc=self.problem();before=p.marginal();desc[0]['emissions']=(2,1,0)
        self.assertEqual(p.marginal(),before)
        other=RoleProgramBelief(2,[describe(FRAMES[0].format(a='Gina',b='Hugo',c='Iris'),NAMES)],[(1/3,)*3],dict(BINDING,generation=4))
        self.assertNotEqual(p.binding,other.binding)

    def test_old_cpu_limit_still_rejects_before_reveal(self):
        p,_,_=self.problem();clock=iter([0,0,0,100_000_001,100_000_001,100_000_001,100_000_001])
        with patch('time.process_time_ns',side_effect=lambda:next(clock,100_000_001)):
            with self.assertRaises(PlanningBudgetError):plan(p)

if __name__=='__main__':unittest.main()
