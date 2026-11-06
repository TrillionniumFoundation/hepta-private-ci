#!/usr/bin/env python3
"""Real SQLite/process controls plus explicitly simulated pilot orchestration.

The control-flow doubles below do not run a model. The two-process reservation,
crash, stale-checkpoint and uncertain-COMMIT checks use real SQLite files.
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import llm_runtime_pilot as runtime
import llm_runtime_trial_ledger as trial


def plan(policy, attempt='1' * 64, **kwargs):
    return runtime.registered_plan(runtime.experiment_plan({'fixture': 'public-control-flow'}, **kwargs),
                                   policy, attempt)


class TrialLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'authority.sqlite3'
        self.init = trial.initialize(self.path, 2)
        self.owner = trial.TrialLedger(self.path, self.init['policy_id'])

    def reserve(self, attempt='1' * 64, checkpoint=None, subject='first-key', **kwargs):
        return self.owner.reserve(plan(self.init['policy_id'], attempt, **kwargs), attempt,
            self.init['checkpoint'] if checkpoint is None else checkpoint, subject)

    def abort(self, attempt='1' * 64):
        state = self.owner.inspect()['attempts'][attempt]
        record = dict(outcome='aborted', experiment=state['reservation']['plan_id'],
            phases=[dict(name=p['name'], **p['observation']) for p in state['phases']],
            adoption=False, reward=False, no_update=False, **{flag: False for flag in runtime.QUALIFICATIONS})
        return self.owner.finish(attempt, 'aborted', record)

    def test_existing_authority_is_required_and_new_database_cannot_reuse_pin(self):
        missing = trial.TrialLedger(self.root / 'missing', self.init['policy_id'])
        with self.assertRaises(FileNotFoundError): missing.inspect()
        self.assertFalse(missing.path.exists())
        with self.assertRaises(FileExistsError): trial.initialize(self.path, 2)
        other = self.root / 'other.sqlite3'
        trial.initialize(other, 2)
        with self.assertRaisesRegex(ValueError, 'POLICY_BINDING'):
            trial.TrialLedger(other, self.init['policy_id']).inspect()

    def test_every_authority_connection_requires_extra_rollback_journal_sync(self):
        connect = sqlite3.connect
        values = []
        class ObserveSync:
            def __init__(self, db): self.db = db
            def __getattr__(self, name): return getattr(self.db, name)
            def execute(self, sql, *args):
                if sql == 'COMMIT':
                    values.append(self.db.execute('PRAGMA synchronous').fetchone()[0])
                return self.db.execute(sql, *args)
        with patch.object(sqlite3, 'connect', side_effect=lambda *a, **k: ObserveSync(connect(*a, **k))):
            trial.initialize(self.root / 'new.sqlite3', 1)
            self.reserve()
            self.owner.inspect()
        self.assertEqual(values, [3, 3, 3])

    def test_symlink_and_corrupt_database_refuse(self):
        link = self.root / 'linked'; link.symlink_to(self.path)
        with self.assertRaisesRegex(ValueError, 'REGULAR_DATABASE'):
            trial.TrialLedger(link, self.init['policy_id']).inspect()
        self.path.write_bytes(b'not a sqlite authority')
        with self.assertRaises(sqlite3.DatabaseError): self.owner.inspect()

    def test_reopen_abort_and_changed_key_candidate_share_finite_allowance(self):
        first = self.reserve()
        self.assertEqual((first['spent'], first['alpha_per_comparison']), (1, [1, 160]))
        second = self.abort()
        self.owner = trial.TrialLedger(self.path, self.init['policy_id'])
        self.reserve('2' * 64, second['checkpoint'], 'other-related-key', steps=11)
        current = self.owner.inspect()
        self.assertEqual(current['spent'], 2)
        self.assertEqual(current['attempts']['1' * 64]['state'], 'aborted')
        self.assertEqual(current['attempts']['2' * 64]['state'], 'reserved')
        with self.assertRaisesRegex(ValueError, 'ALLOWANCE_OR_REPLAY'):
            self.reserve('3' * 64, current['checkpoint'], 'third-host-or-key', steps=12)

    def test_same_trial_cannot_rerun_even_with_current_checkpoint(self):
        self.reserve()
        with self.assertRaisesRegex(ValueError, 'ALLOWANCE_OR_REPLAY'):
            self.reserve(checkpoint=self.owner.inspect()['checkpoint'])

    def test_checkpoint_and_plan_binding_precede_debit(self):
        value = plan(self.init['policy_id'])
        for field in ('trial_id', 'trial_policy'):
            changed = copy.deepcopy(value); changed[field] = 'f' * 64
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'REGISTERED_PLAN'):
                self.owner.reserve(changed, '1' * 64, self.init['checkpoint'], 'key')
        changed = copy.deepcopy(value); changed['run_components']['llm_runtime_assessment.py'] = 'f' * 64
        with self.assertRaisesRegex(ValueError, 'COMPONENTS_CHANGED'):
            self.owner.reserve(changed, '1' * 64, self.init['checkpoint'], 'key')
        with self.assertRaisesRegex(ValueError, 'STALE_CHECKPOINT'):
            self.reserve(checkpoint='f' * 64)
        self.assertEqual(self.owner.inspect()['spent'], 0)

    def test_frozen_roster_and_phase_order_are_mandatory_and_terminal_is_immutable(self):
        self.reserve()
        with self.assertRaisesRegex(ValueError, 'PHASE_ORDER'):
            self.owner.phase('1' * 64, 'evaluate-candidate', {'outcome': 'success'})
        self.owner.phase('1' * 64, trial.PHASES[0], {'outcome': 'failed'})
        with self.assertRaisesRegex(ValueError, 'FAILED_PREDECESSOR'):
            self.owner.phase('1' * 64, trial.PHASES[1], {'outcome': 'success'})
        self.abort()
        with self.assertRaisesRegex(ValueError, 'TERMINAL_IMMUTABLE'): self.abort()
        self.assertEqual(self.owner.inspect()['spent'], 1)

    def test_complete_local_assessment_retains_debit_and_incomplete_economic_decision(self):
        from test_llm_runtime_assessment import fixture
        from llm_runtime_assessment import build_assessment
        value, roster, scores, records, receipts = fixture()
        value = runtime.registered_plan(value, self.init['policy_id'], '1' * 64)
        roster['experiment'] = runtime.identity(value)
        for name, receipt in receipts.items():
            actual = dict(value, threads=1) if name == 'loader-1thread' else value
            receipt['experiment'] = runtime.identity(actual)
        self.owner.reserve(value, '1' * 64, self.init['checkpoint'], 'key')
        for i, record in enumerate(records):
            if i == 7: self.owner.freeze_roster('1' * 64, roster)
            self.owner.phase('1' * 64, record['name'], {k: v for k, v in record.items() if k != 'name'})
            self.owner.child_receipt('1' * 64, record['name'], receipts[record['name']])
        result = build_assessment(value, roster, scores, records, receipts)
        self.owner.finish('1' * 64, 'complete-unqualified', result)
        state = self.owner.inspect()
        self.assertEqual(state['spent'], 1)
        retained = state['attempts']['1' * 64]['terminal']['record']
        self.assertEqual(retained['decision'], 'incomplete')
        self.assertIs(retained['no_update'], False)

    def test_lost_commit_acknowledgement_never_refunds_or_replays(self):
        connect = sqlite3.connect
        class LostAcknowledgement:
            def __init__(self, connection): self.connection = connection
            def __getattr__(self, name): return getattr(self.connection, name)
            def execute(self, sql, *args):
                result = self.connection.execute(sql, *args)
                if sql == 'COMMIT': raise OSError('injected lost COMMIT acknowledgement')
                return result
        with patch.object(sqlite3, 'connect', side_effect=lambda *a, **k: LostAcknowledgement(connect(*a, **k))):
            with self.assertRaisesRegex(OSError, 'lost COMMIT'): self.reserve()
        current = self.owner.inspect()
        self.assertEqual(current['spent'], 1)
        with self.assertRaisesRegex(ValueError, 'ALLOWANCE_OR_REPLAY'):
            self.reserve(checkpoint=current['checkpoint'])

    def test_old_database_refuses_current_externally_retained_checkpoint(self):
        before = self.path.read_bytes()
        receipt = self.reserve()
        self.path.write_bytes(before)
        with self.assertRaisesRegex(ValueError, 'STALE_CHECKPOINT'):
            self.reserve('2' * 64, receipt['checkpoint'])

    def test_restoring_database_and_old_checkpoint_is_outside_local_guarantee(self):
        # Retain this counterexample: two old local objects are not a monotonic root.
        before = self.path.read_bytes()
        first = self.reserve()
        self.path.write_bytes(before)
        replay = self.reserve()
        self.assertEqual((first['spent'], replay['spent']), (1, 1))
        self.assertFalse(replay['statistical_acceptance'])

    def test_two_real_processes_cannot_spend_one_checkpoint_twice(self):
        gate = self.root / 'start'
        processes = [subprocess.Popen([sys.executable, __file__, '_reserve', str(self.path),
            self.init['policy_id'], self.init['checkpoint'], str(i) * 64, str(gate)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in (1, 2)]
        try:
            gate.write_text('start')
            results = [p.communicate(timeout=20) for p in processes]
        finally:
            for p in processes:
                if p.poll() is None: p.kill(); p.wait()
        self.assertEqual(sorted(p.returncode for p in processes), [0, 3], results)
        self.assertEqual(self.owner.inspect()['spent'], 1)
        self.assertIn('TRIAL_STALE_CHECKPOINT', ''.join(r[1] for r in results))

    def test_process_exit_after_reservation_keeps_pending_allowance(self):
        gate = self.root / 'start'; gate.write_text('start')
        result = subprocess.run([sys.executable, __file__, '_reserve', str(self.path),
            self.init['policy_id'], self.init['checkpoint'], '1' * 64, str(gate), '_crash'],
            capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 23, result.stderr)
        state = self.owner.inspect()
        self.assertEqual(state['spent'], 1)
        self.assertEqual(state['attempts']['1' * 64]['state'], 'reserved')

    def test_journal_edit_cannot_masquerade_as_an_accepted_observation(self):
        self.reserve()
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE events SET payload = replace(payload, 'first-key', 'other-key')")
        with self.assertRaisesRegex(ValueError, 'JOURNAL_ROOT'): self.owner.inspect()

    def test_schema_or_trigger_substitution_is_rejected_before_reservation(self):
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TRIGGER discard BEFORE INSERT ON events BEGIN SELECT RAISE(IGNORE); END')
        with self.assertRaisesRegex(ValueError, 'TRIAL_SCHEMA'): self.reserve()
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0], 0)


class PilotRunAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'authority.sqlite3'
        self.init = trial.initialize(self.path, 1)
        self.owner = trial.TrialLedger(self.path, self.init['policy_id'])
        self.args = SimpleNamespace(output=str(self.root / 'run'), materials=str(self.root / 'materials'),
            backend='cpu', threads=4, steps=10, exit_observation_profile='strict-v1',
            trial_ledger=str(self.path), trial_policy=self.init['policy_id'],
            trial_checkpoint=self.init['checkpoint'], trial_id='1' * 64, related_identity='related-key')

    def invoke(self, supervisor):
        with patch.object(runtime, 'verify_materials', return_value=({'fixture': 'public-control-flow'}, {})), \
             patch.object(runtime, 'verify_family', side_effect=lambda value: value), \
             patch.object(runtime, 'supervise', side_effect=supervisor), \
             contextlib.redirect_stdout(io.StringIO()):
            runtime.run(self.args)

    def test_debit_is_committed_before_plan_or_first_child_and_failure_is_retained(self):
        def failed(*args, **kwargs):
            state = self.owner.inspect()
            self.assertEqual(state['spent'], 1)
            self.assertEqual(state['attempts']['1' * 64]['state'], 'reserved')
            self.assertTrue((Path(self.args.output) / 'experiment-plan.json').exists())
            return {'outcome': 'failed', 'exit_code': 17}
        with self.assertRaisesRegex(ValueError, 'REQUIRED_PHASE_ABORT'): self.invoke(failed)
        state = self.owner.inspect()
        self.assertEqual(state['attempts']['1' * 64]['state'], 'aborted')
        self.assertFalse((Path(self.args.output) / 'assessment.json').exists())
        self.args.output = str(self.root / 'second-run')
        self.args.trial_checkpoint = state['checkpoint']
        self.args.trial_id = '2' * 64; self.args.related_identity = 'different-key'
        with patch.object(runtime, 'supervise') as child:
            with self.assertRaisesRegex(ValueError, 'ALLOWANCE_OR_REPLAY'): self.invoke(child)
            child.assert_not_called()
        self.assertFalse((Path(self.args.output) / 'experiment-plan.json').exists())

    def test_missing_rss_or_failed_child_receipt_cannot_publish_assessment(self):
        from test_llm_runtime_assessment import fixture
        _, _, _, records, receipts = fixture()
        def run_child(command, directory, budget, **kwargs):
            directory.mkdir()
            value = runtime.read_json(command[command.index('--plan') + 1])
            receipt = copy.deepcopy(receipts['loader-1thread'])
            receipt.update(experiment=runtime.identity(value), runtime_source=value['runtime_source'])
            receipt['process_peak_rss_bytes'] = None
            runtime.save(directory / 'actual-receipt.json', receipt)
            return {k: v for k, v in records[0].items() if k != 'name'}
        with self.assertRaisesRegex(ValueError, 'RUNTIME_COST_RSS'): self.invoke(run_child)
        state = self.owner.inspect()['attempts']['1' * 64]
        self.assertEqual(state['state'], 'aborted')
        self.assertEqual(len(state['phases']), 1)
        self.assertFalse((Path(self.args.output) / 'assessment.json').exists())
        self.assertFalse(state['terminal']['record']['adoption'])

    def test_refused_ledger_never_calls_material_loader_or_child(self):
        self.args.trial_policy = 'f' * 64
        with patch.object(runtime, 'verify_materials') as materials, patch.object(runtime, 'supervise') as child:
            with self.assertRaisesRegex(ValueError, 'POLICY_BINDING'): runtime.run(self.args)
            materials.assert_not_called(); child.assert_not_called()
        self.assertFalse(Path(self.args.output).exists())

    def test_uncertain_debit_returns_before_plan_or_model_disclosure(self):
        original = trial.TrialLedger.reserve
        def lost_ack(owner, *args, **kwargs):
            original(owner, *args, **kwargs)
            raise OSError('lost reservation acknowledgement')
        with patch.object(trial.TrialLedger, 'reserve', lost_ack):
            with self.assertRaisesRegex(OSError, 'lost reservation'):
                self.invoke(lambda *a, **k: self.fail('child must not start'))
        self.assertEqual(self.owner.inspect()['spent'], 1)
        self.assertFalse((Path(self.args.output) / 'experiment-plan.json').exists())


def _worker():
    _, _, path, policy, checkpoint, attempt, gate, *mode = sys.argv
    deadline = time.monotonic() + 5
    while not Path(gate).exists():
        if time.monotonic() > deadline: raise RuntimeError('test start barrier timed out')
        time.sleep(0.005)
    try:
        receipt = trial.TrialLedger(path, policy).reserve(plan(policy, attempt), attempt, checkpoint, 'child-key')
        if mode: os._exit(23)
        print(json.dumps(receipt))
    except ValueError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(3)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '_reserve': _worker()
    else: unittest.main()
