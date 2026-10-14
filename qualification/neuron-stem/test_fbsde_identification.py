"""Behavioral identification, exact reference, budget and source-interface tests."""
import unittest
from unittest.mock import patch
from four_gate_common import digest
from fbsde_transfer import TransferProblem, TransferTable, OPS
from fbsde_identification import IdentificationPolicy, IdentificationRejected, execute, best_fixed
from fbsde_identification_reference import Reference, source_effect


def problem():
    public=dict(source_id='test-environment',names=['Mira','Nolan','Orla'],event='Mira, Nolan and Orla execute the registered operation.')
    ctx=dict(scope='test-scope',generation=1,environment='test-environment')
    p=TransferProblem.build(public,ctx)
    return p,dict(binding=p.binding,**ctx)


class IdentificationTests(unittest.TestCase):
    def test_exact_bellman_values_and_actions_for_every_compiled_state(self):
        p,_=problem();ref=Reference()
        for budget in range(7):
            policy=IdentificationPolicy.prepare(p.table,budget)
            for (ids,remaining),(good,calls,state) in policy.nodes.items():
                q,c,s=ref.optimal(sum(1<<i for i in ids),remaining)
                self.assertEqual((good,calls,state),(q*len(ids),c*len(ids),s))

    def test_prepared_prior_fixed_control_matches_independent_enumeration(self):
        p,_=problem();ref=Reference()
        for b in range(7):
            found=best_fixed(p.table,b)
            self.assertEqual((found['order'],found['identified_mass'],found['query_mass']),ref.fixed_order(b))

    def test_actual_reset_paths_attain_compiled_objective_without_true_rule_input(self):
        p,ctx=problem()
        for b in range(7):
            policy=IdentificationPolicy.prepare(p.table,b);good=calls=0
            for hidden in range(33):
                requests=[]
                def reveal(req):
                    requests.append(req.copy())
                    self.assertEqual(req['remaining'],b-req['sequence'])
                    return dict(request_sha256=digest(req),effect=source_effect(hidden,req['state']))
                r=execute(p,'optimal',b,reveal,ctx,policy=policy)
                self.assertLessEqual(len(requests),b)
                self.assertEqual(requests,[r['request'] for r in r['records']])
                good+=r['identified'];calls+=len(requests)
                if r['snapshot']:
                    table=TransferTable.restore(r['snapshot'],p,r['history'],ctx)
                    self.assertEqual(table.effects,p.table[hidden])
            summary=policy.summary(p.table)
            self.assertEqual((good,calls),(summary['identified_mass'],summary['query_mass']))

    def test_two_queries_cannot_be_relabelled_full_identification(self):
        p,ctx=problem();policy=IdentificationPolicy.prepare(p.table,2)
        r=execute(p,'optimal',2,lambda q:dict(request_sha256=digest(q),effect=source_effect(7,q['state'])),ctx,policy=policy)
        self.assertFalse(r['identified']);self.assertIsNone(r['snapshot'])
        with self.assertRaises(ValueError):TransferTable.from_support(p,r['history'],ctx)

    def test_behaviorally_identical_program_ids_do_not_force_spurious_experiments(self):
        table=((0,1,2,3,4,5),)*3
        p=IdentificationPolicy.prepare(table,2)
        self.assertEqual((p.summary(table)['identified_mass'],p.summary(table)['query_mass']),(3,0))

    def test_preparation_node_cap_is_enforced_before_final_root_insertion(self):
        p,_=problem()
        with self.assertRaisesRegex(ValueError,'preparation budget'):IdentificationPolicy.prepare(p.table,3,max_nodes=2)

    def test_illegal_budget_including_bool_is_rejected(self):
        p,_=problem()
        for b in (-1,7,True,2.0):
            with self.assertRaises(ValueError):IdentificationPolicy.prepare(p.table,b)

    def test_compiled_nodes_are_readonly(self):
        p,_=problem();policy=IdentificationPolicy.prepare(p.table,1)
        with self.assertRaises(TypeError):policy.nodes[((),0)]=(99,0,0)

    def test_old_scope_cannot_reveal_an_experiment(self):
        p,ctx=problem();policy=IdentificationPolicy.prepare(p.table,2);ctx['generation']=2
        with self.assertRaisesRegex(ValueError,'context'):
            execute(p,'optimal',2,lambda _:self.fail('source called'),ctx,policy=policy)

    def test_receipt_mismatch_retains_attempt_and_returns_no_policy(self):
        p,ctx=problem();policy=IdentificationPolicy.prepare(p.table,1)
        with self.assertRaises(IdentificationRejected) as caught:
            execute(p,'optimal',1,lambda r:dict(request_sha256=digest('wrong'),effect=(0,1,2)),ctx,policy=policy)
        self.assertEqual(len(caught.exception.evidence['records']),1)
        self.assertFalse(caught.exception.evidence['returned'])
        self.assertNotIn('action',caught.exception.evidence)

    def test_source_exception_is_counted_as_an_attempt(self):
        p,ctx=problem();policy=IdentificationPolicy.prepare(p.table,1)
        def fail(_):raise RuntimeError('sensor unavailable')
        with self.assertRaises(IdentificationRejected) as caught:execute(p,'optimal',1,fail,ctx,policy=policy)
        self.assertEqual(caught.exception.evidence['records'][0]['error'],'sensor unavailable')

    def test_nonbijective_effect_cannot_export_a_fake_permutation(self):
        p,ctx=problem();policy=IdentificationPolicy.prepare(p.table,1)
        r=execute(p,'optimal',1,lambda q:dict(request_sha256=digest(q),effect=(0,0,1)),ctx,policy=policy)
        self.assertEqual(r['failure'],'unsupported_nonbijective_effect')
        self.assertEqual(len(r['records']),1);self.assertFalse(r['identified'])

    def test_decision_cpu_failure_returns_no_action(self):
        p,ctx=problem();policy=IdentificationPolicy.prepare(p.table,1)
        with patch('fbsde_identification.time.process_time_ns',side_effect=[0,0,100_000_001]):
            with self.assertRaises(IdentificationRejected) as caught:
                execute(p,'optimal',1,lambda _:self.fail('source called'),ctx,policy=policy)
        self.assertFalse(caught.exception.evidence['returned'])

    def test_complete_finite_table_does_not_attest_stationarity_outside_family(self):
        p,ctx=problem();policy=IdentificationPolicy.prepare(p.table,5)
        r=execute(p,'optimal',5,lambda q:dict(request_sha256=digest(q),effect=source_effect(7,q['state'])),ctx,policy=policy)
        self.assertTrue(r['identified']);self.assertFalse(r['family_coverage_authenticated'])
        # An environment may change after the last actual measurement. No claim
        # about unobserved changes follows from reconstructing these same receipts.
        self.assertNotEqual(p.table[7],p.table[0])

if __name__=='__main__':unittest.main()
