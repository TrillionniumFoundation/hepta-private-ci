#!/usr/bin/env python3
"""Independent real-SQLite controls for the pilot's durable return boundaries.

Child outputs below are declared fixtures. This verifies ledger admission and
replay, not real model quality, global rollback resistance or independent custody.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import llm_runtime_assessment as assessment
import llm_runtime_pilot as runtime
import llm_runtime_trial_ledger as trial
from test_llm_runtime_assessment import fixture


class TrialLedgerReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'authority.sqlite3'
        self.init = trial.initialize(self.path, 2)
        self.owner = trial.TrialLedger(self.path, self.init['policy_id'])
        self.attempt = '1' * 64
        self.plan, self.roster, self.scores, self.records, self.receipts = fixture()
        self.plan = runtime.registered_plan(self.plan, self.init['policy_id'], self.attempt)
        self.roster['experiment'] = runtime.identity(self.plan)
        for name, receipt in self.receipts.items():
            actual = dict(self.plan, threads=1) if name == 'loader-1thread' else self.plan
            receipt['experiment'] = runtime.identity(actual)
        self.owner.reserve(self.plan, self.attempt, self.init['checkpoint'], 'cooperating-key')

    def add_phase(self, index, *, receipt=True):
        row = self.records[index]
        observation = {k: v for k, v in row.items() if k != 'name'}
        self.owner.phase(self.attempt, row['name'], observation)
        if receipt:
            self.owner.child_receipt(self.attempt, row['name'], self.receipts[row['name']])

    def trained(self):
        for index in range(7):
            self.add_phase(index)

    def evaluated(self):
        self.trained()
        self.owner.freeze_roster(self.attempt, self.roster)
        for index in range(7, 12):
            self.add_phase(index)
        return assessment.build_assessment(self.plan, self.roster, self.scores, self.records, self.receipts)

    def abort_record(self):
        state = self.owner.inspect()['attempts'][self.attempt]
        return dict(outcome='aborted', experiment=state['reservation']['plan_id'],
                    phases=[dict(name=p['name'], **p['observation']) for p in state['phases']],
                    no_update=False, adoption=False, reward=False,
                    **{flag: False for flag in runtime.QUALIFICATIONS})

    def test_abort_cannot_carry_a_successful_or_ambiguous_no_update(self):
        for value in (True, 1, 0, None, 'false'):
            record = self.abort_record()
            record['no_update'] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, '^TRIAL_TERMINAL_AUTHORITY$'):
                self.owner.finish(self.attempt, 'aborted', record)
        record = self.abort_record()
        del record['no_update']
        with self.assertRaisesRegex(ValueError, '^TRIAL_TERMINAL_AUTHORITY$'):
            self.owner.finish(self.attempt, 'aborted', record)
        self.owner.finish(self.attempt, 'aborted', self.abort_record())
        self.assertEqual(self.owner.inspect()['attempts'][self.attempt]['state'], 'aborted')

    def test_frozen_roster_must_match_every_already_loaded_training_artifact(self):
        self.trained()
        for role in runtime.PARTICIPANTS:
            changed = copy.deepcopy(self.roster)
            changed['artifacts'][role] = 'e' * 64
            with self.subTest(role=role), self.assertRaisesRegex(ValueError, '^TRIAL_TRAINED_ROSTER_BINDING$'):
                self.owner.freeze_roster(self.attempt, changed)
        changed = copy.deepcopy(self.roster)
        changed['contract'] = 'f' * 64
        with self.assertRaisesRegex(ValueError, '^TRIAL_TRAINED_ROSTER_BINDING$'):
            self.owner.freeze_roster(self.attempt, changed)
        self.assertEqual(self.owner.inspect()['attempts'][self.attempt]['state'], 'reserved')
        self.owner.freeze_roster(self.attempt, self.roster)
        self.assertEqual(self.owner.inspect()['attempts'][self.attempt]['roster'], self.roster)

    def test_evaluation_receipt_cannot_switch_the_already_frozen_model(self):
        self.trained()
        self.owner.freeze_roster(self.attempt, self.roster)
        self.add_phase(7, receipt=False)
        name = self.records[7]['name']
        for field in ('artifact', 'contract'):
            changed = copy.deepcopy(self.receipts[name])
            changed[field] = 'f' * 64
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, '^TRIAL_EVALUATED_ROSTER_BINDING$'):
                self.owner.child_receipt(self.attempt, name, changed)
        state = self.owner.inspect()['attempts'][self.attempt]
        self.assertNotIn(name, state['receipts'])
        with self.assertRaisesRegex(ValueError, '^TRIAL_MISSING_CHILD_RECEIPT$'):
            self.add_phase(8, receipt=False)
        self.owner.child_receipt(self.attempt, name, self.receipts[name])
        self.add_phase(8)

    def test_sqlite_like_wildcard_names_cannot_hide_executable_schema(self):
        # '_' in LIKE is a wildcard: sqliteX is legal, while sqlite_ is reserved.
        # No custom SQL function is needed to exercise this actual SQLite name.
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TRIGGER sqliteXhidden AFTER INSERT ON events BEGIN SELECT 1; END')
        with self.assertRaisesRegex(ValueError, '^TRIAL_SCHEMA$'):
            self.owner.inspect()
        with self.assertRaisesRegex(ValueError, '^TRIAL_SCHEMA$'):
            self.owner.phase(self.attempt, trial.PHASES[0], {'outcome': 'failed'})
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0], 1)
            db.execute('DROP TRIGGER sqliteXhidden')
        self.assertEqual(self.owner.inspect()['spent'], 1)

    def test_equivalent_view_cannot_replace_the_events_table(self):
        with sqlite3.connect(self.path) as db:
            db.execute('ALTER TABLE events RENAME TO original_events')
            db.execute('CREATE VIEW events AS SELECT * FROM original_events')
        with self.assertRaisesRegex(ValueError, '^TRIAL_SCHEMA$'):
            self.owner.inspect()

    def test_missing_or_aliased_rss_child_receipt_cannot_admit_next_phase(self):
        self.add_phase(0, receipt=False)
        name = self.records[0]['name']
        for value in (None, True, 0, -1):
            changed = copy.deepcopy(self.receipts[name])
            changed['process_peak_rss_bytes'] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, '^RUNTIME_COST_RSS$'):
                self.owner.child_receipt(self.attempt, name, changed)
        with self.assertRaisesRegex(ValueError, '^TRIAL_MISSING_CHILD_RECEIPT$'):
            self.add_phase(1, receipt=False)
        state = self.owner.inspect()['attempts'][self.attempt]
        self.assertEqual((len(state['phases']), len(state['receipts'])), (1, 0))
        self.owner.child_receipt(self.attempt, name, self.receipts[name])
        self.add_phase(1)

    def test_rehashed_child_record_still_has_to_pass_local_observation_semantics(self):
        self.add_phase(0)
        with sqlite3.connect(self.path) as db:
            row = db.execute('SELECT seq, trial, kind, payload, previous FROM events ORDER BY seq DESC LIMIT 1').fetchone()
            seq, attempt, kind, raw, previous = row
            self.assertEqual(kind, 'child-receipt')
            value = json.loads(raw)
            value['receipt']['process_peak_rss_bytes'] = None
            root = trial._event_root(seq, attempt, kind, value, previous)
            db.execute('UPDATE events SET payload=?, root=? WHERE seq=?',
                       (runtime.canonical(value).decode(), root, seq))
        # The self-consistent hash is not proof that a cost was observed.
        with self.assertRaisesRegex(ValueError, '^RUNTIME_COST_RSS$'):
            self.owner.inspect()

    def test_terminal_costs_are_recomputed_from_retained_phase_receipts(self):
        result = self.evaluated()
        for field, value in [('no_update', True), ('decision', 'no-update'),
                             ('local_process_channels_complete', False),
                             ('net_benefit_lower_bound', [1, 1])]:
            changed = copy.deepcopy(result)
            changed[field] = value
            code = '^TRIAL_TERMINAL_AUTHORITY$' if field == 'no_update' else '^TRIAL_TERMINAL_COST_BINDING$'
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, code):
                self.owner.finish(self.attempt, 'complete-unqualified', changed)
        changed = copy.deepcopy(result)
        changed['aggregate_observed_costs']['max_waited_child_peak_rss_bytes'] = 0
        with self.assertRaisesRegex(ValueError, '^TRIAL_TERMINAL_COST_BINDING$'):
            self.owner.finish(self.attempt, 'complete-unqualified', changed)
        self.owner.finish(self.attempt, 'complete-unqualified', result)
        self.assertEqual(self.owner.inspect()['attempts'][self.attempt]['terminal']['record'], result)

    def test_lost_terminal_ack_does_not_allow_abort_or_second_completion(self):
        result = self.evaluated()
        connect = sqlite3.connect
        class LostAcknowledgement:
            def __init__(self, connection):
                self.connection = connection
            def __getattr__(self, name):
                return getattr(self.connection, name)
            def execute(self, sql, *args):
                answer = self.connection.execute(sql, *args)
                if sql == 'COMMIT':
                    raise OSError('injected lost terminal acknowledgement')
                return answer
        with patch.object(sqlite3, 'connect', side_effect=lambda *a, **k: LostAcknowledgement(connect(*a, **k))):
            with self.assertRaisesRegex(OSError, 'lost terminal acknowledgement'):
                self.owner.finish(self.attempt, 'complete-unqualified', result)
        state = self.owner.inspect()['attempts'][self.attempt]
        self.assertEqual(state['state'], 'complete-unqualified')
        self.assertEqual(state['terminal']['record'], result)
        with self.assertRaisesRegex(ValueError, '^TRIAL_TERMINAL_IMMUTABLE$'):
            self.owner.finish(self.attempt, 'complete-unqualified', result)
        with self.assertRaisesRegex(ValueError, '^TRIAL_TERMINAL_IMMUTABLE$'):
            self.owner.finish(self.attempt, 'aborted', self.abort_record())
        self.assertEqual(self.owner.inspect()['spent'], 1)


if __name__ == '__main__':
    unittest.main()
