"""Real subprocess races/restarts for one-filesystem experiment reservations."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from admission import Case, MatchedEvaluator, Protocol, Run, budget_digest, digest
from admission_test_support import fixture_cost_protocol, fixture_ledger, fixture_registration
from durable_admission import DurableMatchedEvaluator
from experiment_ledger import ExperimentLedger, LedgerRejected, fingerprint


ROOT = Path(__file__).resolve().parent
CHILD = '''
import json,os,sys
from experiment_ledger import ExperimentLedger,LedgerRejected
path, fixture, operation, phase = sys.argv[1:]
p=json.load(open(fixture))
ledger=ExperimentLedger(path)
try:
 r=ledger.reserve('experiment',operation,p['family'],['new','old'],1,p['request'])
 if phase == 'race':
  print(json.dumps({'state':r['state'],'granted':r['dispatch_token'] is not None}),flush=True)
 else:
  if phase in ('running','completed'):
   ledger.start(operation,r['dispatch_token'])
  if phase == 'completed':
   ledger.finish(operation,r['dispatch_token'],{'test_result':True})
  os._exit(37)
except LedgerRejected as exc:
 print(json.dumps({'rejected':str(exc)}),flush=True)
'''


def good_predictor(query):
    return True


def bad_predictor(query):
    return False


def executor_factory():
    return lambda choice, payload: payload if choice else None


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'ledger.sqlite'
        self.ledger = ExperimentLedger(self.path)
        self.addCleanup(self.ledger.close)
        self.family = {'comparisons': [['new', 'old'], ['other', 'old']], 'planned_looks': 2,
                       'source_claims': [fingerprint(['source', 'one'])], 'frozen': 'protocol'}
        self.request = {'candidate': 'new', 'memory': 'memory', 'cost': 7}
        self.fixture = Path(self.temporary.name) / 'fixture.json'
        self.fixture.write_text(json.dumps({'family': self.family, 'request': self.request}))

    def reserve(self, operation='operation', **changes):
        args = dict(experiment='experiment', operation=operation, family=self.family,
                    comparison=['new', 'old'], look=1, request=self.request)
        args.update(changes)
        return self.ledger.reserve(**args)

    def test_duplicate_does_not_grant_new_dispatch(self):
        first, repeated = self.reserve(), self.reserve()
        self.assertIsNotNone(first['dispatch_token'])
        self.assertIsNone(repeated['dispatch_token'])
        self.assertEqual([{k:v for k,v in x.items() if k != 'dispatch_token'} for x in (first,repeated)][0],
                         {k:v for k,v in repeated.items() if k != 'dispatch_token'})
        self.assertEqual([r['state'] for r in self.ledger.history('operation')], ['reserved'])
        with self.assertRaisesRegex(LedgerRejected, 'already reserved'):
            self.reserve('another-operation')

    def test_rebinding_operation_request_or_frozen_family_rejects(self):
        self.reserve()
        with self.assertRaisesRegex(LedgerRejected, 'identity already bound'):
            self.reserve(request={**self.request, 'cost': 0})
        with self.assertRaisesRegex(LedgerRejected, 'family already frozen'):
            self.reserve('other', family={**self.family, 'planned_looks': 200}, look=2)
        with self.assertRaisesRegex(LedgerRejected, 'identity already bound'):
            self.reserve(experiment='renamed-experiment')

    def test_source_reuse_rejects_new_family_and_rolls_back_claims(self):
        self.reserve()
        with self.assertRaisesRegex(LedgerRejected, 'source cohort'):
            self.reserve('different', experiment='new-experiment')
        self.assertEqual(self.ledger.db.execute('SELECT COUNT(*) FROM experiments').fetchone()[0], 1)
        self.assertEqual(self.ledger.db.execute('SELECT COUNT(*) FROM operations').fetchone()[0], 1)

    def test_all_registered_comparison_look_slots_are_independent_but_bounded(self):
        for look in (1, 2):
            for i, pair in enumerate(self.family['comparisons']):
                self.assertIsNotNone(self.reserve(f'op-{i}-{look}', comparison=pair, look=look)['dispatch_token'])
        for look in (0,3,True):
            with self.assertRaises(LedgerRejected):
                self.reserve(f'invalid-{look}', look=look)
        with self.assertRaises(LedgerRejected):
            self.reserve('undeclared', comparison=['unregistered', 'old'])

    def test_completed_receipt_survives_reopen_and_cannot_be_replaced(self):
        first = self.reserve()
        token = first['dispatch_token']
        self.ledger.start('operation', token)
        terminal = self.ledger.finish('operation', token, {'accuracy': .9})
        reopened = ExperimentLedger(self.path)
        self.addCleanup(reopened.close)
        replay = reopened.reserve('experiment','operation',self.family,['new','old'],1,self.request)
        self.assertEqual(terminal, {k:v for k,v in replay.items() if k != 'dispatch_token'})
        self.assertIsNone(replay['dispatch_token'])
        self.assertEqual(self.ledger.finish('operation', token, {'accuracy': .9}), terminal)
        with self.assertRaises(LedgerRejected):
            self.ledger.finish('operation', token, {'accuracy': 1.})
        self.assertEqual(self.ledger.retain('operation', 'cancelled', 'late cancel'), terminal)

    def test_cancelled_unknown_never_release_slot_or_accept_late_result(self):
        for i, state in enumerate(('cancelled','unknown')):
            operation = f'op-{i}'
            first = self.reserve(operation,look=i+1)
            self.ledger.start(operation, first['dispatch_token'])
            kept = self.ledger.retain(operation,state,'supervisor observed interruption')
            self.assertEqual(kept['state'], state)
            with self.assertRaises(LedgerRejected):
                self.ledger.finish(operation,first['dispatch_token'],{'approved':True})
            with self.assertRaises(LedgerRejected):
                self.reserve(f'retry-{i}',look=i+1)
            self.assertEqual(self.reserve(operation,look=i+1)['state'], state)

    def test_token_forgery_and_second_start_fail(self):
        token=self.reserve()['dispatch_token']
        with self.assertRaisesRegex(LedgerRejected,'token mismatch'):
            self.ledger.start('operation','wrong')
        self.ledger.start('operation',token)
        with self.assertRaisesRegex(LedgerRejected,'dispatched again'):
            self.ledger.start('operation',token)

    def test_eight_independent_processes_only_one_gets_slot(self):
        processes=[subprocess.Popen([sys.executable,'-c',CHILD,str(self.path),str(self.fixture),f'race-{i}','race'],
                   cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for i in range(8)]
        results=[]
        for process in processes:
            out,err=process.communicate(timeout=30)
            self.assertEqual(process.returncode,0,err)
            results.append(json.loads(out))
        self.assertEqual(sum(row.get('granted',False) for row in results),1,results)
        self.assertEqual(sum('rejected' in row for row in results),7,results)

    def test_real_process_exit_in_each_phase_never_causes_redispatch(self):
        # Each subcase uses independent source/history, not a new DB to recover one run.
        for phase in ('reserved','running','completed'):
            path=Path(self.temporary.name)/f'{phase}.sqlite'
            process=subprocess.run([sys.executable,'-c',CHILD,str(path),str(self.fixture),'crashed',phase],
                                   cwd=ROOT,capture_output=True,text=True,timeout=30)
            self.assertEqual(process.returncode,37,process.stderr)
            ledger=ExperimentLedger(path)
            try:
                observed=ledger.reserve('experiment','crashed',self.family,['new','old'],1,self.request)
                self.assertIsNone(observed['dispatch_token'])
                self.assertEqual(observed['state'],phase)
                if phase == 'completed':
                    self.assertEqual(observed['result'],{'test_result':True})
                else:
                    self.assertEqual(ledger.retain('crashed','unknown','old process exited')['state'],'unknown')
                with self.assertRaises(LedgerRejected):
                    ledger.reserve('experiment','retry',self.family,['new','old'],1,self.request)
            finally:
                ledger.close()

    def test_reopening_does_not_change_live_owner_state(self):
        token=self.reserve()['dispatch_token']
        self.ledger.start('operation',token)
        other=ExperimentLedger(self.path)
        try:
            self.assertEqual(other.read('operation')['state'],'running')
            self.ledger.finish('operation',token,{'value':42})
            self.assertEqual(other.read('operation')['result'],{'value':42})
        finally:
            other.close()

    def test_corrupt_retained_payload_fails_readback(self):
        self.reserve()
        self.ledger.db.execute("UPDATE operations SET request='{}' WHERE id='operation'")
        with self.assertRaisesRegex(LedgerRejected,'corrupt request'):
            self.ledger.read('operation')


class DurableEvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path=Path(self.temporary.name)/'ledger.sqlite'
        self.ledger=ExperimentLedger(self.path)
        self.addCleanup(self.ledger.close)
        self.cases=[Case(str(i),str(i),'retained','query',i,i) for i in range(256)]
        self.protocol=fixture_cost_protocol(Protocol('durable-fixture',True,256,.05,1,.25,16,1.,('retained',),(),()))
        self.candidate=Run('new','memory','history','executor',budget_digest(self.protocol),good_predictor,
                           'encoder','decoder','tools')
        self.incumbent=replace(self.candidate,bundle='old',predict=bad_predictor)
        self.registration=fixture_registration(self.cases,self.protocol,self.candidate,self.incumbent)
        self.evaluator=self.make_evaluator()
        self.identity=digest({'fixed':'trusted-loader-source-runtime'})

    def make_evaluator(self):
        return MatchedEvaluator(self.cases,executor_factory,self.protocol,registration=self.registration)

    def run_evaluator(self, operation='operation', *, experiment='experiment', evaluator=None, candidate=None):
        evaluator=evaluator or self.evaluator
        candidate=candidate or self.candidate
        return DurableMatchedEvaluator(evaluator,self.ledger,experiment,self.identity,
            runs=(self.candidate,self.incumbent)).evaluate(
            operation,candidate,self.incumbent,fixture_ledger(evaluator,candidate),
            fixture_ledger(evaluator,self.incumbent),manifest={'bundle':'new','memory':'memory'})

    def test_actual_worker_terminal_cached_across_evaluator_recreation(self):
        first=self.run_evaluator()
        self.assertEqual(first['state'],'completed')
        self.assertTrue(first['result']['approved'],first['result']['reasons'])
        self.assertFalse(first['result']['production_authority'])
        second=self.run_evaluator(evaluator=self.make_evaluator())
        self.assertEqual(first,second)
        self.assertEqual([r['state'] for r in self.ledger.history('operation')],['reserved','running','completed'])

    def test_changed_predictor_same_bundle_cannot_replay_old_result(self):
        self.run_evaluator()
        with self.assertRaisesRegex(LedgerRejected,'callback changed'):
            self.run_evaluator(candidate=replace(self.candidate,predict=bad_predictor))

    def test_renamed_source_ids_still_cannot_recycle_exact_public_inputs(self):
        self.run_evaluator()
        self.cases=[replace(c,key='alias-'+c.key,cluster='alias-'+c.cluster) for c in self.cases]
        self.registration=fixture_registration(self.cases,self.protocol,self.candidate,self.incumbent)
        with self.assertRaisesRegex(LedgerRejected,'source cohort'):
            self.run_evaluator('another',experiment='renamed',evaluator=self.make_evaluator())

    def test_unregistered_or_changed_protocol_rejected_before_dispatch(self):
        self.evaluator.protocol=replace(self.protocol,planned_looks=100)
        with self.assertRaisesRegex(LedgerRejected,'changed after freeze'):
            self.run_evaluator()
        self.assertEqual(self.ledger.db.execute('SELECT COUNT(*) FROM operations').fetchone()[0],0)

    def test_changed_predictor_in_next_planned_look_rejects_before_run(self):
        self.protocol=replace(self.protocol,planned_looks=2)
        self.registration=fixture_registration(self.cases,self.protocol,self.candidate,self.incumbent)
        self.evaluator=self.make_evaluator()
        self.run_evaluator()
        self.registration['look_index']=2
        self.candidate=replace(self.candidate,predict=bad_predictor)
        with self.assertRaisesRegex(LedgerRejected,'family already frozen'):
            self.run_evaluator('look-two',evaluator=self.make_evaluator())
        self.assertEqual(self.ledger.db.execute('SELECT COUNT(*) FROM operations').fetchone()[0],1)

    def test_full_roster_freezes_unused_candidate_before_first_comparison(self):
        self.protocol=replace(self.protocol,comparisons=2)
        other=replace(self.candidate,bundle='other',predict=bad_predictor)
        self.registration=fixture_registration(self.cases,self.protocol,self.candidate,self.incumbent)
        self.registration['comparisons'].append(['other','old'])
        self.registration['arms']['other']=deepcopy(self.registration['arms']['new'])
        evaluator=self.make_evaluator()
        initial=DurableMatchedEvaluator(evaluator,self.ledger,'experiment',self.identity,
                                         runs=(self.candidate,self.incumbent,other))
        def assess(wrapper,operation,candidate):
            return wrapper.evaluate(operation,candidate,self.incumbent,fixture_ledger(evaluator,candidate),
                fixture_ledger(evaluator,self.incumbent),manifest={'bundle':candidate.bundle,'memory':'memory'})
        assess(initial,'first',self.candidate)
        changed=replace(other,predict=good_predictor)
        adaptive=DurableMatchedEvaluator(evaluator,self.ledger,'experiment',self.identity,
                                          runs=(self.candidate,self.incumbent,changed))
        with self.assertRaisesRegex(LedgerRejected,'family already frozen'):
            assess(adaptive,'adaptive',changed)
        self.assertEqual(assess(initial,'second',other)['state'],'completed')
        with self.assertRaisesRegex(LedgerRejected,'complete registered callback roster'):
            DurableMatchedEvaluator(evaluator,self.ledger,'experiment',self.identity,
                                      runs=(self.candidate,self.incumbent))

    def test_executor_changed_after_full_roster_freeze_rejects(self):
        wrapper=DurableMatchedEvaluator(self.evaluator,self.ledger,'experiment',self.identity,
                                         runs=(self.candidate,self.incumbent))
        self.evaluator.executor_factory=lambda: (lambda choice,payload: payload)
        with self.assertRaisesRegex(LedgerRejected,'callback changed'):
            wrapper.evaluate('changed',self.candidate,self.incumbent,fixture_ledger(self.evaluator,self.candidate),
                fixture_ledger(self.evaluator,self.incumbent),manifest={'bundle':'new','memory':'memory'})
        self.assertEqual(self.ledger.db.execute('SELECT COUNT(*) FROM operations').fetchone()[0],0)

    def test_evaluator_exception_is_retained_and_never_replayed(self):
        def broken(*args,**kwargs):
            raise RuntimeError('failure after dispatch')
        self.evaluator.evaluate=broken
        with self.assertRaises(RuntimeError):
            self.run_evaluator()
        self.assertEqual(self.ledger.read('operation')['state'],'unknown')
        self.assertEqual(self.run_evaluator()['state'],'unknown')

    def test_keyboard_interrupt_is_retained_as_cancelled(self):
        def interrupted(*args,**kwargs):
            raise KeyboardInterrupt()
        self.evaluator.evaluate=interrupted
        with self.assertRaises(KeyboardInterrupt):
            self.run_evaluator()
        self.assertEqual(self.ledger.read('operation')['state'],'cancelled')
        self.assertEqual(self.run_evaluator()['state'],'cancelled')


if __name__=='__main__':
    unittest.main()
