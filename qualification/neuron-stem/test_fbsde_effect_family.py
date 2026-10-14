"""Family misspecification, exact worlds, replay and bounded selected evidence."""
from itertools import permutations
import unittest
from unittest.mock import patch
from four_gate_common import digest
from fbsde_effect_family import EffectFamily,FamilyConflict,EFFECTS,SWAPS,ALL
from fbsde_effect_execute import execute
from fbsde_effect_data import FRAMES,observe,operation
from fbsde_effect_audit import Reference,actual
from fbsde_role_program import RoleProgramBelief,describe
from fbsde_tracking_control import plan,PlanningBudgetError


def source(kind=0,length=2):
    text=FRAMES[kind].format(a='Jade',b='Kian',c='Lena')
    return dict(source_id='test',names=['Jade','Kian','Lena'],query=0,events=[text]*length)


class EffectTests(unittest.TestCase):
    def test_alpha_role_emissions_are_permutations(self):
        for names in permutations(['Jade','Kian','Lena']):
            p=source();p['names']=names;m=EffectFamily(p)
            self.assertEqual(sorted(m.emissions[0]),list(ALL))
            self.assertAlmostEqual(sum(m.laws[0]),1)

    def test_old_swap_model_and_existing_planner_unchanged(self):
        for k in (2,3,4):
            p=source(length=k);a=EffectFamily(p)
            b=RoleProgramBelief(0,[describe(t,p['names']) for t in p['events']],[(1/3,)*3]*k,
                dict(source=digest(p),model='test',calibration='uniform',scope='test',generation=1),prior='uniform')
            for h in (0,1,2):
                x,y=plan(a,horizon=h),plan(b,horizon=h)
                self.assertEqual(x['action'],y['action']);self.assertAlmostEqual(x['value'],y['value'])

    def test_consistent_duplicate_does_not_multiply_evidence(self):
        m=EffectFamily(source())
        self.assertEqual(m.marginal(((0,2),)),m.marginal(((0,2),(1,2))))
        self.assertEqual(m.available_events(((0,2),)),[])

    def test_expansion_preserves_all_observations(self):
        p=source();p['events'][1]=FRAMES[1].format(a='Jade',b='Kian',c='Lena')
        m=EffectFamily(p);h=((0,2),(1,0));new=m.revise(h)
        self.assertNotEqual(m.identity,new.identity);self.assertEqual(new.revision,1)
        self.assertEqual(new.supports,(SWAPS,ALL));self.assertEqual(new.history(h),h)
        with self.assertRaises(FamilyConflict):m.history(h)

    def test_conflicting_frame_requires_explicit_event_fallback(self):
        m=EffectFamily(source());h=((0,2),(1,5))
        with self.assertRaisesRegex(ValueError,'explicit fallback'):m.revise(h)
        new=m.revise(h,allow_event_split=True)
        self.assertEqual(new.grouping,'event');self.assertEqual(new.history(h),h)
        self.assertNotEqual(new.identity,m.identity)

    def test_no_evidence_no_arbitrary_expansion(self):
        with self.assertRaisesRegex(ValueError,'no evidence'):EffectFamily(source()).revise(((0,2),))

    def test_world_capacity_precedes_expansion(self):
        p=source(length=6)
        for i in range(6):p['events'][i]+=f' tag{i}'
        with self.assertRaisesRegex(ValueError,'world budget'):EffectFamily(p,supports=(ALL,)*6)
        with self.assertRaisesRegex(ValueError,'world budget'):EffectFamily(p,max_worlds=10)

    def test_expansion_does_not_raise_custom_capacity(self):
        m=EffectFamily(source(),max_worlds=3)
        with self.assertRaisesRegex(ValueError,'world budget'):m.revise(((0,3),))

    def test_fallback_does_not_raise_custom_capacity(self):
        m=EffectFamily(source(),supports=(ALL,),max_worlds=8)
        with self.assertRaisesRegex(ValueError,'world budget'):m.revise(((0,2),(1,5)),allow_event_split=True)

    def test_narrow_unanimity_can_be_confidently_wrong(self):
        p=source(2);reveal,truth,_=observe(p)
        old=execute(p,'swap_two',reveal)
        self.assertEqual(old['checks'],[]);self.assertNotEqual(old['holder'],truth)
        new=execute(p,'expand_two',reveal)
        self.assertEqual(new['holder'],truth);self.assertEqual(len(new['checks']),1)
        self.assertEqual(len(new['revisions']),1);self.assertFalse(new['semantic_certificate'])

    def test_nonbijective_observation_never_projected_to_a_swap(self):
        p=source(4);r=execute(p,'expand_two',observe(p)[0])
        self.assertIsNone(r['holder']);self.assertEqual(r['reason'],'unsupported_nonbijective_effect')
        self.assertEqual(len(r['checks']),1);self.assertEqual(r['revisions'],[])

    def test_state_dependent_frame_fallback_and_abstention(self):
        for n in (2,3,4):
            p=source(3,n);reveal,truth,_=observe(p);r=execute(p,'expand_audit',reveal)
            self.assertEqual(len(r['checks']),2);self.assertEqual(r['revisions'][-1]['grouping'],'event')
            self.assertEqual(r['revisions'][-1]['remaining_checks'],0)
            self.assertEqual(r['holder'],truth if n==2 else None)

    def test_matching_two_probes_cannot_authenticate_third_occurrence(self):
        p=source(length=3);obs=((0,2),(2,2))
        a=EffectFamily(p,supports=(ALL,));self.assertEqual(a.marginal(obs),[0.,1.,0.])
        b=EffectFamily(p,grouping='event',supports=(ALL,)*3)
        self.assertEqual(b.marginal(obs),[1/3]*3)
        # Either a swap or identity at the unobserved middle event matches both
        # observed effects but yields different final answers. No unseen truth
        # is supplied to either deployed model.
        states=[]
        for middle in (0,2):
            held=list(range(3))
            for j in (2,middle,2):held=[held[x] for x in EFFECTS[j]]
            states.append(held[0])
        self.assertNotEqual(*states)

    def test_source_binding_not_just_an_effect_value(self):
        p=source(2);reveal=observe(p)[0]
        def wrong(e,h):return {**reveal(e,h),'source_sha256':digest('other')}
        with self.assertRaisesRegex(ValueError,'bound selected'):execute(p,'expand_two',wrong)

    def test_no_labels_accepted_at_public_constructor(self):
        with self.assertRaisesRegex(ValueError,'public fields'):EffectFamily({**source(),'answer':0})

    def test_shared_two_check_budget_and_no_revelation_before_choice(self):
        p=source(3,4);seen=[];port=observe(p)[0]
        def reveal(e,h):
            self.assertEqual(len(h),len(seen));seen.append(e);return port(e,h)
        r=execute(p,'expand_audit',reveal);self.assertEqual(len(seen),2)
        self.assertEqual(r['final_known'],tuple(sorted((e,EFFECTS.index(tuple(port(e,())['effect']))) for e in seen)))

    def test_cpu_rejection_cannot_call_verifier(self):
        seen=[];ticks=iter(range(0,10**12,100_000_001))
        with patch('time.process_time_ns',side_effect=lambda:next(ticks)):
            with self.assertRaises(PlanningBudgetError):execute(source(),'expand_two',lambda e,h:seen.append(e))
        self.assertEqual(seen,[])

    def test_independent_source_and_world_reference(self):
        for kind in range(5):
            for length in (2,3,4):
                p=source(kind,length);_,target,effects=observe(p)
                self.assertEqual(actual(p),(effects,target))
                m=EffectFamily(p,supports=(ALL,));ref=Reference(p,'frame',[ALL],0)
                self.assertEqual(m.identity,ref.identity)
                for h in ((),((0,2),)):
                    self.assertEqual(m.marginal(h),ref.state(h)[0])
                    for depth in (0,1,2):
                        r=plan(m,h,horizon=depth);v,a=ref.choose(h,depth)
                        self.assertEqual(r['action'],a);self.assertAlmostEqual(r['value'],v)


if __name__=='__main__':unittest.main()
