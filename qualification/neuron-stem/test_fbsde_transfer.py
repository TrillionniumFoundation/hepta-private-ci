"""Selected interventions, finite-domain identification and scoped reuse."""
import unittest
from unittest.mock import patch
from dataclasses import FrozenInstanceError
from four_gate_common import digest
from fbsde_transfer import TransferProblem,TransferTable,execute,OPS
from fbsde_transfer_reference import tables,choose,source_effect,fixed_pair


def fixture():
    public=dict(source_id='trial',names=['Mira','Nolan','Orla'],event='Mira, Nolan and Orla execute the registered operation.')
    context=dict(scope='transfer-research',generation=1,environment='reset-simulator')
    p=TransferProblem.build(public,context)
    return public,context,p


class TransferTests(unittest.TestCase):
    def test_independent_tables_and_actions(self):
        _,_,p=fixture();self.assertEqual(p.table,tables());self.assertEqual(p.best_fixed(),fixed_pair())
        histories=[()]+[((s,row[s]),) for s in range(6) for row in tables()]
        for h in set(histories):
            for horizon in (0,1,2):
                got=p.choose(h,horizon);value,action=choose(h,horizon)
                self.assertAlmostEqual(got['value'],float(value),places=12)
                self.assertEqual(got['state_index'],action)

    def test_same_current_answer_can_have_different_transition(self):
        _,_,p=fixture();s=p.support(((0,2),(2,0)))
        self.assertGreater(len(s),1)
        with self.assertRaisesRegex(ValueError,'unresolved'):
            TransferTable.from_support(p,((0,2),(2,0)),dict(binding=p.binding,scope='transfer-research',generation=1,environment='reset-simulator'))

    def test_contradictory_and_bad_histories_reject(self):
        _,_,p=fixture()
        for h in (((0,0),(0,1)),((True,1),),((0,False),),((6,0),)):
            with self.assertRaises(ValueError):p.support(h)
        self.assertEqual(p.support(((0,0),)),p.support(((0,0),(0,0))))

    def test_full_domain_compilation_is_exact_for_all_33(self):
        public,context,p=fixture();ctx=dict(binding=p.binding,**context)
        for i,row in enumerate(tables()):
            h=tuple(enumerate(row));table=TransferTable.from_support(p,h,ctx)
            for state in OPS:
                got=table.apply(public['event'],public['names'],state,ctx)
                effect=source_effect(i,state)
                self.assertEqual(got,tuple(state[j] for j in effect))
            with self.assertRaises(FrozenInstanceError):table.effects=(0,)*6

    def test_transfer_scope_generation_frame_and_domain_reject(self):
        public,ctx,p=fixture();context=dict(binding=p.binding,**ctx)
        table=TransferTable.from_support(p,tuple(enumerate(tables()[2])),context)
        for key,value in [('scope','other'),('generation',2),('environment','other')]:
            with self.assertRaises(ValueError):table.apply(public['event'],public['names'],OPS[0],{**context,key:value})
            with self.assertRaises(ValueError):TransferTable.from_support(p,tuple(enumerate(tables()[2])),{**context,key:value})
        with self.assertRaises(ValueError):table.apply(public['event']+' Later.',public['names'],OPS[0],context)
        with self.assertRaises(ValueError):table.apply(public['event'],public['names'],(0,0,2),context)

    def test_only_selected_reset_is_executed_and_budget_does_not_reset(self):
        _,_,p=fixture();requests=[]
        def reveal(r):
            requests.append(r)
            return dict(request_sha256=digest(r),effect=source_effect(12,r['state']))
        out=execute(p,'active_two',reveal)
        self.assertLessEqual(len(requests),2)
        self.assertEqual([r['sequence'] for r in requests],list(range(len(requests))))
        self.assertEqual(len(out['records']),len(requests))
        self.assertFalse(out['semantic_certificate'])

    def test_bad_receipt_and_outside_effect_are_not_projected(self):
        _,_,p=fixture()
        with self.assertRaises(ValueError):execute(p,'fixed_two',lambda r:{'request_sha256':digest(r),'effect':(0,1,2),'true_rule':0})
        out=execute(p,'fixed_two',lambda r:dict(request_sha256=digest(r),effect=(1,1,2)))
        self.assertEqual(out['failure'],'unsupported_nonbijective_effect')
        self.assertFalse(out['identified']);self.assertEqual(len(out['records']),1)
        self.assertEqual(out['predictions'],(None,)*6)

    def test_no_budget_failure_returns_selected_action(self):
        _,_,p=fixture()
        with self.assertRaisesRegex(ValueError,'budget'):p.choose((),2,max_nodes=1)
        with patch('fbsde_transfer.time.process_time_ns',side_effect=[0,100_000_001]):
            with self.assertRaisesRegex(ValueError,'budget'):p.choose((),2)

    def test_unseen_generation_is_not_authenticated_by_a_complete_table(self):
        public,ctx,p=fixture();context=dict(binding=p.binding,**ctx)
        table=TransferTable.from_support(p,tuple((s,0) for s in range(6)),context)
        predicted=table.apply(public['event'],public['names'],OPS[0],context)
        # An unobserved clock-dependent environment can agree on ALL acquisition
        # inputs and change afterward. In-domain agreement cannot certify absence.
        self.assertNotEqual(predicted,(1,0,2))
        self.assertEqual(predicted,(0,1,2))

    def test_reloaded_table_cannot_claim_another_rule(self):
        _,context,p=fixture();ctx=dict(binding=p.binding,**context);h=tuple(enumerate(tables()[2]))
        table=TransferTable.from_support(p,h,ctx);saved=table.snapshot()
        self.assertEqual(TransferTable.restore(saved,p,h,ctx),table)
        saved['effects'][0]=0
        with self.assertRaisesRegex(ValueError,'reconstruction'):TransferTable.restore(saved,p,h,ctx)

    def test_two_probe_ceiling_counts_every_path_not_one_policy(self):
        from fbsde_transfer_reference import identification_ceiling
        result=identification_ceiling();_,_,p=fixture()
        for r,row in enumerate(tables()):
            witnessed=any(len(p.support(((a,row[a]),(b,row[b]))))==1 for a in range(6) for b in range(6))
            self.assertEqual(witnessed,r in result['two_probe_identifiable_rules'])
        self.assertEqual(result['two_probe_identifiable_rules'],[1,2,3,4,5])

    def test_name_permutation_does_not_change_role_rule(self):
        _,context,p=fixture();ctx=dict(binding=p.binding,**context)
        from itertools import permutations
        table=TransferTable.from_support(p,tuple(enumerate(tables()[12])),ctx)
        names=['Ari','Bea','Cora']
        for roles in permutations(range(3)):
            text=', '.join(names[i] for i in roles[:2])+' and '+names[roles[2]]+' execute the registered operation.'
            for state in OPS:
                norm=tuple(state[i] for i in roles);op=source_effect(12,norm)
                expected=tuple(state[roles[op[roles.index(i)]]] for i in range(3))
                self.assertEqual(table.apply(text,names,state,ctx),expected)


if __name__=='__main__':unittest.main()
