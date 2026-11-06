#!/usr/bin/env python3
"""Real SQLite histories read by fresh processes across copied-runner upgrades.

All model receipts are declared fixtures. These tests exercise durable history
compatibility and local validation, not model quality or independent custody.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest


FILES = (
    'llm_runtime_pilot.py', 'llm_runtime_trial_ledger.py',
    'llm_runtime_assessment.py', 'llm_parent_material.py', 'llm_base_material.py',
    'test_llm_runtime_assessment.py', 'test_llm_runtime_trial_replay.py',
)
FAMILY = 'config/pon/model-family-smollm2-135m-v1.json'


def _projection(owner):
    state = owner.inspect()
    return dict(policy=state['policy_id'], checkpoint=state['checkpoint'], spent=state['spent'],
        attempts={key: dict(state=value['state'], plan=value['reservation']['plan_id'],
            terminal=None if value['terminal'] is None else value['terminal']['record_id'],
            alpha=value['reservation']['alpha_per_comparison'])
            for key, value in state['attempts'].items()},
        scope=state['scope'])


def _worker(mode, database, *parameters):
    import llm_runtime_trial_ledger as trial
    if mode in ('_create', '_create_pending'):
        import llm_runtime_pilot as runtime
        from llm_runtime_assessment import build_assessment
        from test_llm_runtime_assessment import fixture
        init = trial.initialize(database, 2)
        owner = trial.TrialLedger(database, init['policy_id'])
        plan, roster, scores, records, receipts = fixture()
        plan = runtime.registered_plan(plan, init['policy_id'], '1' * 64)
        roster['experiment'] = runtime.identity(plan)
        for name, receipt in receipts.items():
            actual = dict(plan, threads=1) if name == 'loader-1thread' else plan
            receipt['experiment'] = runtime.identity(actual)
        owner.reserve(plan, '1' * 64, init['checkpoint'], 'first-related-key')
        for index, record in enumerate(records):
            if index == 7:
                owner.freeze_roster('1' * 64, roster)
            owner.phase('1' * 64, record['name'], {k: v for k, v in record.items() if k != 'name'})
            owner.child_receipt('1' * 64, record['name'], receipts[record['name']])
        result = build_assessment(plan, roster, scores, records, receipts)
        if mode == '_create':
            owner.finish('1' * 64, 'complete-unqualified', result)
    else:
        policy, *rest = parameters
        owner = trial.TrialLedger(database, policy)
        if mode == '_reserve':
            import llm_runtime_pilot as runtime
            checkpoint, attempt = rest
            plan = runtime.registered_plan(runtime.experiment_plan({'fixture': 'changed-recipe'},
                steps=11), policy, attempt)
            owner.reserve(plan, attempt, checkpoint, 'second-related-key-on-new-runner')
        elif mode == '_child_receipt':
            name, path = rest
            owner.child_receipt('1' * 64, name, json.loads(Path(path).read_text()))
        elif mode == '_next_phase':
            attempt = owner.inspect()['attempts']['1' * 64]
            owner.phase('1' * 64, trial.PHASES[len(attempt['phases'])], {'outcome': 'success'})
        elif mode == '_freeze':
            attempt = owner.inspect()['attempts']['1' * 64]
            roster = dict(experiment=attempt['reservation']['plan_id'],
                contract=attempt['receipts']['loader-reference']['contract'],
                artifacts={role: attempt['receipts']['train-' + role]['artifact']
                           for role in trial._PARTICIPANTS_V1},
                frozen_before_evaluation=True,
                scope='five-actual-local-artifacts-no-independent-authority')
            owner.freeze_roster('1' * 64, roster)
        elif mode in ('_complete_original', '_abort'):
            attempt = owner.inspect()['attempts']['1' * 64]
            plan = attempt['reservation']['plan']
            records = [dict(name=p['name'], **p['observation']) for p in attempt['phases']]
            if mode == '_complete_original':
                scores = {role: dict(calibration=[0, 1], evaluation=[0, 1])
                          for role in trial._PARTICIPANTS_V1}
                result = trial._profile_assessment(attempt['replay_profile'])(
                    plan, attempt['roster'], scores, records, attempt['receipts'])
                owner.finish('1' * 64, 'complete-unqualified', result)
            else:
                result = dict(outcome='aborted', experiment=attempt['reservation']['plan_id'],
                    phases=records, adoption=False, reward=False, no_update=False,
                    **{flag: False for flag in trial._QUALIFICATIONS_V1})
                owner.finish('1' * 64, 'aborted', result)
        elif mode != '_inspect':
            raise ValueError('TEST_MODE')
    print(json.dumps(_projection(owner), sort_keys=True))


class TrialLedgerReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Build one real committed SQLite history. Each adversarial reader gets
        # an independent byte copy; repeating 27 fsync transactions per case
        # adds no evidence and needlessly competes with model test IO.
        fixture = cls()
        directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(directory.cleanup)
        fixture.root = Path(directory.name)
        scripts = fixture.root / 'scripts'
        scripts.mkdir()
        repository = Path(__file__).resolve().parents[1]
        for name in FILES:
            shutil.copyfile(repository / 'scripts' / name, scripts / name)
        family = fixture.root / FAMILY
        family.parent.mkdir(parents=True)
        shutil.copyfile(repository / FAMILY, family)
        fixture.database = fixture.root / 'authority.sqlite3'
        cls.template_projection = fixture.worker('_create')
        cls.template = fixture.root

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(self.template, self.root, dirs_exist_ok=True)
        self.database = self.root / 'authority.sqlite3'
        self.before = copy.deepcopy(self.template_projection)
        self.assertEqual(self.before['spent'], 1)
        self.assertEqual(self.before['attempts']['1' * 64]['state'], 'complete-unqualified')

    def worker(self, mode, *parameters, error=None):
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        result = subprocess.run([sys.executable, '-B',
            str(self.root / 'scripts/test_llm_runtime_trial_replay.py'), mode,
            str(self.database), *parameters], cwd=self.root,
            capture_output=True, text=True, timeout=60, env=environment)
        if error is not None:
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn(error, result.stderr)
            return result
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def inspect(self):
        return self.worker('_inspect', self.before['policy'])

    def append_source(self, name, content):
        path = self.root / 'scripts' / name
        path.write_text(path.read_text() + '\n' + content + '\n')

    def rewrite_events(self, edit, *, limit=None):
        import llm_runtime_trial_ledger as trial
        with sqlite3.connect(self.database) as db:
            rows = db.execute('SELECT seq, trial, kind, payload FROM events ORDER BY seq').fetchall()
            rows = [[seq, attempt, kind, json.loads(raw)] for seq, attempt, kind, raw in rows]
            if limit is not None:
                rows = rows[:limit]
            edit(rows)
            db.execute('DELETE FROM events')
            previous = trial._genesis(self.before['policy'])
            for seq, attempt, kind, value in rows:
                root = trial._event_root(seq, attempt, kind, value, previous)
                db.execute('INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)',
                    (seq, attempt, kind, trial._canonical(value).decode('ascii'), previous, root))
                previous = root

    def legacy_history(self, *, contradictory_wall=False, contradictory_training=False):
        """Encode the original unversioned shape and original v2 assessment.

        The original source identity is an explicit historical fixture. No live
        code, keys, independent authority or real model execution is implied.
        """
        import llm_runtime_trial_ledger as trial
        def edit(rows):
            reservation = rows[0][3]
            self.assertEqual(rows[0][2], 'reserve-v2')
            rows[0][2] = 'reserve'
            del reservation['schema'], reservation['replay_profile']
            plan = reservation['plan']
            plan['run_components']['llm_runtime_assessment.py'] = (
                '133871703daf740c26cccb30e450cd90127d1ee206c75734929ddbf364602f5d')
            plan['run_components'].pop('llm_base_material.py')
            reservation['plan_id'] = trial._identity(plan)
            records, receipts, roster = [], {}, None
            for _, _, kind, value in rows[1:]:
                if kind == 'phase':
                    records.append(dict(name=value['name'], **value['observation']))
                elif kind == 'child-receipt':
                    name, receipt = value['name'], value['receipt']
                    actual = dict(plan, threads=1) if name == 'loader-1thread' else plan
                    receipt['experiment'] = trial._identity(actual)
                    if contradictory_wall and name == 'evaluate-candidate':
                        receipt['process_wall_ns'] = 5000
                    if contradictory_training and name == 'train-candidate':
                        receipt['training'].update(steps=0, loss=[], tokens=0, supervised_tokens=0,
                                                   supported_profile_flops=0)
                    if contradictory_training and name == 'train-current-backbone':
                        receipt['training']['steps'] = 99
                    receipts[name] = receipt
                elif kind == 'freeze-roster':
                    value['experiment'] = trial._identity(plan)
                    roster = value
                elif kind == 'terminal':
                    value['record'] = trial._build_assessment_v2(plan, roster,
                        value['record']['scores'], records, receipts)
                    value['record_id'] = trial._identity(value['record'])
        self.rewrite_events(edit)
        self.before = self.inspect()

    def test_family_formatting_upgrade_does_not_reinterpret_completed_history(self):
        path = self.root / FAMILY
        value = json.loads(path.read_text())
        path.write_text(json.dumps(value, separators=(',', ':'), sort_keys=True) + '\n')
        self.assertEqual(self.inspect(), self.before)

    def test_historical_family_source_need_not_exist_in_current_checkout(self):
        (self.root / FAMILY).unlink()
        self.assertEqual(self.inspect(), self.before)

    def test_assessment_upgrade_keeps_exact_terminal_bytes_and_remaining_allowance(self):
        self.legacy_history()
        self.append_source('llm_runtime_assessment.py',
            "MISSING_OBLIGATIONS += ('new-runner-obligation-description',)")
        self.assertEqual(self.inspect(), self.before)
        next_state = self.worker('_reserve', self.before['policy'], self.before['checkpoint'], '2' * 64)
        self.assertEqual(next_state['spent'], 2)
        self.assertEqual(next_state['attempts']['1' * 64], self.before['attempts']['1' * 64])
        self.assertEqual(next_state['attempts']['2' * 64]['state'], 'reserved')
        self.worker('_reserve', self.before['policy'], next_state['checkpoint'], '3' * 64,
                    error='TRIAL_ALLOWANCE_OR_REPLAY')
        self.assertEqual(self.inspect(), next_state)

    def test_pending_history_can_be_aborted_but_not_completed_with_changed_components(self):
        self.database = self.root / 'pending.sqlite3'
        self.before = self.worker('_create_pending')
        self.assertEqual(self.before['attempts']['1' * 64]['state'], 'evaluating')
        self.append_source('llm_runtime_assessment.py', '# upgraded runner source')
        self.assertEqual(self.inspect(), self.before)
        self.worker('_complete_original', self.before['policy'], error='RUNTIME_RUN_COMPONENTS_CHANGED')
        self.assertEqual(self.inspect(), self.before)
        state = self.worker('_abort', self.before['policy'])
        self.assertEqual(state['spent'], 1)
        self.assertEqual(state['attempts']['1' * 64]['state'], 'aborted')
        self.assertEqual(state['attempts']['1' * 64]['plan'], self.before['attempts']['1' * 64]['plan'])

    def test_future_runner_inventory_does_not_change_v1_policy_interpretation(self):
        self.append_source('llm_runtime_pilot.py',
            "CONTROLS.append('future-control')\nQUALIFICATIONS.append('future-qualification')\n"
            "PARTICIPANTS.reverse()\nPARTICIPANT_KINDS['candidate'] = 'full-tune'")
        self.assertEqual(self.inspect(), self.before)

    def test_current_assessment_module_is_not_imported_during_history_readback(self):
        self.append_source('llm_runtime_assessment.py',
            "raise RuntimeError('current assessment unavailable to historical reader')")
        self.assertEqual(self.inspect(), self.before)

    def test_rehashed_terminal_corruption_still_fails_after_assessment_upgrade(self):
        import llm_runtime_pilot as runtime
        import llm_runtime_trial_ledger as trial
        self.append_source('llm_runtime_assessment.py',
            "MISSING_OBLIGATIONS += ('new-runner-obligation-description',)")
        with sqlite3.connect(self.database) as db:
            seq, attempt, kind, raw, previous = db.execute(
                'SELECT seq, trial, kind, payload, previous FROM events ORDER BY seq DESC LIMIT 1').fetchone()
            self.assertEqual(kind, 'terminal')
            value = json.loads(raw)
            value['record']['aggregate_observed_costs']['max_waited_child_peak_rss_bytes'] = 0
            value['record_id'] = runtime.identity(value['record'])
            db.execute('UPDATE events SET payload=?, root=? WHERE seq=?',
                (runtime.canonical(value).decode('ascii'),
                 trial._event_root(seq, attempt, kind, value, previous), seq))
        self.worker('_inspect', self.before['policy'], error='TRIAL_TERMINAL_COST_BINDING')

    def test_rehashed_unavailable_historical_family_is_not_guessed_from_current_file(self):
        import llm_runtime_trial_ledger as trial
        def edit(rows):
            reservation = rows[0][3]
            reservation['plan']['model_family_configuration_sha256'] = 'f' * 64
            reservation['plan_id'] = trial._identity(reservation['plan'])
        self.rewrite_events(edit, limit=1)
        self.worker('_inspect', self.before['policy'], error='TRIAL_FAMILY_CONTEXT')

    def test_current_runner_module_is_not_imported_during_history_readback(self):
        self.append_source('llm_runtime_pilot.py',
            "raise RuntimeError('current runner unavailable to historical reader')")
        self.assertEqual(self.inspect(), self.before)

    def test_new_source_hash_gets_explicit_profile_before_a_second_upgrade(self):
        self.append_source('llm_runtime_assessment.py', '# next implementation, same admitted semantics')
        self.database = self.root / 'new-source.sqlite3'
        self.before = self.worker('_create')
        with sqlite3.connect(self.database) as db:
            kind, raw = db.execute('SELECT kind, payload FROM events WHERE seq=1').fetchone()
            reservation = json.loads(raw)
        self.assertEqual(kind, 'reserve-v2')
        self.assertEqual(reservation['schema'], 'llm-runtime-trial-reservation-v2')
        self.assertEqual(reservation['replay_profile'], 'llm-runtime-public-history-contained-v2')
        self.assertNotEqual(reservation['plan']['run_components']['llm_runtime_assessment.py'],
                           '133871703daf740c26cccb30e450cd90127d1ee206c75734929ddbf364602f5d')
        self.append_source('llm_runtime_assessment.py',
            "raise RuntimeError('later implementation unavailable')")
        self.assertEqual(self.inspect(), self.before)

    def test_legacy_validation_is_retained_without_upgrading_its_cost_claims(self):
        self.legacy_history(contradictory_wall=True)
        with sqlite3.connect(self.database) as db:
            raw = db.execute("SELECT payload FROM events WHERE kind='terminal'").fetchone()[0]
        record = json.loads(raw)['record']
        row = next(v for v in record['cost_observations'] if v['name'] == 'evaluate-candidate')
        self.assertGreater(row['child_reported_wall_ns'], row['observed_wall_ns'])
        self.assertFalse(record['complete_economic_cost'])
        self.assertFalse(record['adoption'])
        self.assertFalse(record['reward'])
        self.append_source('llm_runtime_assessment.py',
            "MISSING_OBLIGATIONS += ('later-stronger-current-gate',)")
        self.assertEqual(self.inspect(), self.before)
        self.assertEqual(self.before['spent'], 1)

    def test_unknown_legacy_assessment_source_is_not_assigned_current_semantics(self):
        self.legacy_history()
        def edit(rows):
            import llm_runtime_trial_ledger as trial
            reservation = rows[0][3]
            reservation['plan']['run_components']['llm_runtime_assessment.py'] = 'f' * 64
            reservation['plan_id'] = trial._identity(reservation['plan'])
        self.rewrite_events(edit, limit=1)
        self.worker('_inspect', self.before['policy'], error='TRIAL_LEGACY_REPLAY_SOURCE')

    def test_unknown_reservation_schema_or_replay_profile_is_not_guessed(self):
        original = self.database.read_bytes()
        for field in ('schema', 'replay_profile'):
            with self.subTest(field=field):
                self.database.write_bytes(original)
                self.rewrite_events(lambda rows: rows[0][3].update({field: 'unknown-future-v999'}), limit=1)
                self.worker('_inspect', self.before['policy'], error='TRIAL_REPLAY_PROFILE')

    def test_rehashed_reservation_keeps_immutable_plan_structure_and_context_checks(self):
        import llm_runtime_trial_ledger as trial
        original = self.database.read_bytes()
        cases = (
            ('unregistered-schema', lambda p: p.update(schema='llm-runtime-public-pilot-plan-v1'),
             'TRIAL_REGISTERED_PLAN'),
            ('wrong-policy', lambda p: p.update(trial_policy='f' * 64), 'TRIAL_REGISTERED_PLAN'),
            ('wrong-trial', lambda p: p.update(trial_id='2' * 64), 'TRIAL_REGISTERED_PLAN'),
            ('unknown-pilot-schema', lambda p: p.update(pilot_schema='future-v5'), 'TRIAL_PILOT_SCHEMA'),
            ('wrong-model', lambda p: p.update(model='another-family'), 'TRIAL_PLAN_CONTEXT'),
            ('wrong-revision', lambda p: p.update(revision='f' * 40), 'TRIAL_PLAN_CONTEXT'),
            ('aliased-budget', lambda p: p['training_budget'].update(wall_seconds=True), 'TRIAL_PLAN_BUDGET'),
            ('missing-component', lambda p: p['run_components'].pop('llm_parent_material.py'), 'TRIAL_COMPONENTS'),
            ('malformed-component-hash', lambda p: p['run_components'].update({'llm_parent_material.py': True}),
             'TRIAL_DIGEST'),
            ('detached-runtime-source', lambda p: p.update(runtime_source='f' * 64), 'TRIAL_COMPONENT_SOURCE'),
            ('missing-new-material-component', lambda p: p['run_components'].pop('llm_base_material.py'),
             'TRIAL_REPLAY_COMPONENTS'),
            ('wrong-recipe', lambda p: p['recipes']['candidate'].update(kind='immutable-backbone'), 'TRIAL_PLAN_RECIPE'),
            ('invalid-recipe-number', lambda p: p['recipes']['candidate'].update(learning_rate='nan'),
             'TRIAL_PLAN_RECIPE_NUMERIC'),
            ('changed-task-bytes', lambda p: p['tasks'][0].update(prompt='different prompt'), 'TRIAL_PLAN_TASK_BYTES'),
            ('aliased-task', lambda p: p['tasks'].append(copy.deepcopy(p['tasks'][0])), 'TRIAL_PLAN_TASK_ALIAS'),
            ('boolean-step-count', lambda p: p.update(training_steps=True), 'TRIAL_INTEGER'),
            ('raised-qualification', lambda p: p.update(public_network_ready=True), 'TRIAL_PLAN_QUALIFICATION'),
        )
        for name, action, error in cases:
            with self.subTest(name=name):
                self.database.write_bytes(original)
                def edit(rows):
                    reservation = rows[0][3]
                    action(reservation['plan'])
                    reservation['plan_id'] = trial._identity(reservation['plan'])
                self.rewrite_events(edit, limit=1)
                self.worker('_inspect', self.before['policy'], error=error)

    def test_rehashed_versioned_child_must_replay_all_six_cost_containment_checks(self):
        original = self.database.read_bytes()
        cases = (
            ('process_wall_ns', 5000, False, 'RUNTIME_COST_WALL_CONTAINMENT'),
            ('process_cpu_ns', 5000, False, 'RUNTIME_COST_CPU_CONTAINMENT'),
            ('wall_ns', 5000, True, 'RUNTIME_COST_STAGE_WALL_CONTAINMENT'),
            ('cpu_ns', 5000, True, 'RUNTIME_COST_STAGE_CPU_CONTAINMENT'),
            ('memory_peak_bytes', 1024 * 1024, True, 'RUNTIME_COST_STAGE_RSS_CONTAINMENT'),
            ('process_peak_rss_bytes', 1024 * 1024, False, 'RUNTIME_COST_RSS_CONTAINMENT'),
        )
        for field, value, stage, error in cases:
            with self.subTest(field=field, stage=stage):
                self.database.write_bytes(original)
                def edit(rows):
                    self.assertEqual(rows[2][2], 'child-receipt')
                    receipt = rows[2][3]['receipt']
                    target = receipt['cost_events'][0] if stage else receipt
                    target[field] = value
                self.rewrite_events(edit, limit=3)
                self.worker('_inspect', self.before['policy'], error=error)


    def test_live_training_refusal_keeps_debit_and_prevents_next_phase(self):
        with sqlite3.connect(self.database) as db:
            values = [json.loads(row[0]) for row in
                      db.execute("SELECT payload FROM events WHERE kind='child-receipt'")]
        receipt = next(row['receipt'] for row in values if row['name'] == 'train-candidate')
        receipt['training'].update(steps=0, loss=[], tokens=0, supervised_tokens=0, supported_profile_flops=0)
        path = self.root / 'contradictory-training-receipt.json'
        path.write_text(json.dumps(receipt))
        self.rewrite_events(lambda rows: None, limit=6)  # debit + two loaders + returned training phase
        before = self.inspect()
        self.assertEqual(before['spent'], 1)
        self.worker('_child_receipt', self.before['policy'], 'train-candidate', str(path),
                    error='RUNTIME_TRAINING_STEPS')
        self.worker('_next_phase', self.before['policy'], error='TRIAL_MISSING_CHILD_RECEIPT')
        self.assertEqual(self.inspect(), before)
        after = self.worker('_abort', self.before['policy'])
        self.assertEqual(after['spent'], 1)
        self.assertEqual(after['attempts']['1' * 64]['state'], 'aborted')

    def test_live_and_rehashed_roster_freeze_require_matching_training_totals(self):
        roster = []
        def mismatch(rows):
            for row in rows:
                if row[2] == 'freeze-roster':
                    roster.append(copy.deepcopy(row))
                if row[2] == 'child-receipt' and row[3]['name'] == 'train-fresh-budget-matched-lora':
                    row[3]['receipt']['training']['tokens'] += 1
            del rows[15:]
        self.rewrite_events(mismatch)
        before = self.inspect()
        self.assertEqual(before['attempts']['1' * 64]['state'], 'reserved')
        self.worker('_freeze', self.before['policy'], error='RUNTIME_MATCHED_TRAINING_BUDGET')
        self.assertEqual(self.inspect(), before)
        self.rewrite_events(lambda rows: rows.append(roster[0]))
        self.worker('_inspect', self.before['policy'], error='RUNTIME_MATCHED_TRAINING_BUDGET')

    def test_rehashed_training_metadata_cannot_bypass_frozen_v3_validation(self):
        original = self.database.read_bytes()
        cases = (
            ('candidate', lambda r: r.pop('training'), 'RUNTIME_TRAINING_FIELDS'),
            ('candidate', lambda r: r['training'].pop('loss'), 'RUNTIME_TRAINING_FIELDS'),
            ('candidate', lambda r: r['training'].update(steps=False), 'RUNTIME_TRAINING_NUMBER'),
            ('candidate', lambda r: r['training'].update(steps=9), 'RUNTIME_TRAINING_STEPS'),
            ('candidate', lambda r: r['training'].update(tokens=-1), 'RUNTIME_TRAINING_NUMBER'),
            ('candidate', lambda r: r['training'].update(tokens=0, supervised_tokens=0), 'RUNTIME_TRAINING_TOKENS'),
            ('candidate', lambda r: r['training']['loss'].__setitem__(0, 'nan'), 'RUNTIME_TRAINING_LOSS'),
            ('candidate', lambda r: r['training']['loss'].__setitem__(0, '-1e-999'), 'RUNTIME_TRAINING_LOSS'),
            ('current-backbone', lambda r: r['training'].update(steps=99), 'RUNTIME_TRAINING_STEPS'),
            ('current-backbone', lambda r: r['training'].update(tokens=False), 'RUNTIME_TRAINING_NUMBER'),
            ('randomized-rank-matched-lora', lambda r: r['training'].update(supported_profile_flops=1),
             'RUNTIME_TRAINING_ZERO_ROLE'),
        )
        for role, action, error in cases:
            with self.subTest(role=role, error=error):
                self.database.write_bytes(original)
                def edit(rows):
                    for index, row in enumerate(rows):
                        if row[2] == 'child-receipt' and row[3]['name'] == 'train-' + role:
                            action(row[3]['receipt'])
                            del rows[index + 1:]
                            return
                    self.fail('missing fixture training receipt')
                self.rewrite_events(edit)
                self.worker('_inspect', self.before['policy'], error=error)

    def test_rehashed_v3_terminal_cannot_claim_actual_schedule_or_reuse_v2_claim(self):
        import llm_runtime_trial_ledger as trial
        original = self.database.read_bytes()
        cases = (
            lambda record: record.update(actual_token_schedule_verified=True),
            lambda record: record.update(training_budget_matched_by_steps_and_token_schedule=True),
            lambda record: record.update(schema='llm-runtime-actual-pilot-assessment-v2'),
            lambda record: record.pop('actual_token_schedule_verified'),
        )
        for index, action in enumerate(cases):
            with self.subTest(attack=index):
                self.database.write_bytes(original)
                def edit(rows):
                    self.assertEqual(rows[-1][2], 'terminal')
                    terminal = rows[-1][3]
                    self.assertEqual(terminal['record']['schema'], 'llm-runtime-actual-pilot-assessment-v3')
                    action(terminal['record'])
                    terminal['record_id'] = trial._identity(terminal['record'])
                self.rewrite_events(edit)
                self.worker('_inspect', self.before['policy'], error='TRIAL_TERMINAL_COST_BINDING')

    def test_legacy_training_contradiction_stays_original_v2_history(self):
        self.legacy_history(contradictory_training=True)
        with sqlite3.connect(self.database) as db:
            record = json.loads(db.execute("SELECT payload FROM events WHERE kind='terminal'").fetchone()[0])['record']
        self.assertEqual(record['schema'], 'llm-runtime-actual-pilot-assessment-v2')
        self.assertTrue(record['training_budget_matched_by_steps_and_token_schedule'])
        self.assertNotIn('training_steps_and_reported_token_counts_matched', record)
        self.assertNotIn('actual_token_schedule_verified', record)
        self.append_source('llm_runtime_assessment.py', "raise RuntimeError('new v3 builder unavailable')")
        self.assertEqual(self.inspect(), self.before)
        self.assertEqual(self.before['spent'], 1)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1].startswith('_'):
        _worker(*sys.argv[1:])
    else:
        unittest.main()
