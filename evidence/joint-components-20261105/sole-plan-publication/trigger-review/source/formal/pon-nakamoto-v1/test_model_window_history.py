"""Synthetic multi-window records; no model execution or independent custody."""
import copy
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

import model_window_history as window
from contract_wire import H, canonical
from llm_adapter_contract import freeze, validate_run_plan, evaluate_run_record, CONTROL_IDS
from model_acceptance import freeze_preregistration
from test_model_acceptance import fixture
from test_llm_adapter_contract import fixture_record, identity


def rebuild(data, *, gain=True):
    prereg, plan, receipt = data['prereg'], data['plan'], data['receipt']
    plan['tasks'].sort(key=lambda task: task['id'])
    _, pid = freeze(plan, validate_run_plan, 'target-decoder-evaluation-run-plan-v1')
    prereg['run_plan'] = pid
    prereg['future_groups'] = sorted({t['source_group'] for t in plan['tasks']
                                     if t['partition'] == 'evaluation'})
    record = fixture_record(plan, pid)
    if gain:
        for participant in record['participants'][1:]:
            for run in participant['runs']:
                run['outputs'] = {task: identity('incorrect-control') for task in run['outputs']}
    raw, aid = freeze_preregistration(prereg, plan, pid)
    receipt['preregistration'] = aid
    receipt['run_record'] = evaluate_run_record(plan, record, pid)['record']
    task = next(t for t in plan['tasks'] if t['partition'] == 'evaluation')
    receipt['consumers'][0].update(task=task['id'], candidate=plan['candidate'],
                                    output=task['target_output_sha256'])
    data.update(raw=raw, aid=aid, pid=pid, record=record)


def model_fixture(number):
    prereg, _, _, plan, _, _, receipt, material = fixture()
    for task in plan['tasks']:
        for field in ('id', 'prompt_sha256', 'source_group'):
            task[field] = identity(str(number) + ':' + task[field])
    prereg['training_groups'] = [identity('training:' + str(number))]
    for probe in prereg['probes']:
        probe['prompt'] = identity(str(number) + ':' + probe['prompt'])
    receipt['probes'] = [dict(id=p['id'], outputs={name: p['target']
                         for name in ('candidate', *CONTROL_IDS)}) for p in prereg['probes']]
    offset = (number - 1) * 50
    for field in ('registered_at', 'release_after', 'closes_at', 'retention_until'):
        prereg[field] += offset
    for field in ('observed_at', 'task_released_at'):
        receipt[field] += offset
    for use in receipt['consumers']:
        use['used_at'] += offset
    for row in receipt['retention']:
        for field in ('starts_at', 'ends_at', 'retrieved_at'):
            row[field] += offset
    data = dict(prereg=prereg, plan=plan, receipt=receipt, material=material)
    rebuild(data)
    return data


def initial_history(data):
    return window.empty_history(identity('external-series'), data['prereg']['owner'],
                                data['prereg']['governance'])


def bind(data, history):
    history_raw, hid = window.freeze_history(history)
    declaration = dict(schema='pon-model-window-preregistration-v1', scope=window.SCOPE,
        context=H(window.CONTEXT_DOMAIN, canonical(history['context'])).hex(),
        ordinal=len(history['entries']) + 1, previous=history['head'],
        preregistration=data['aid'], run_plan=data['pid'])
    raw, wid = window.freeze_window(declaration, history_raw, hid, data['raw'],
                                     data['aid'], data['plan'], data['pid'])
    return dict(window_raw=raw, expected_window=wid, history_raw=history_raw,
                expected_history=hid, preregistration_raw=data['raw'],
                expected_preregistration=data['aid'], plan=data['plan'],
                expected_plan=data['pid'], record=data['record'], receipt=data['receipt'],
                material=data['material'])


def complete(data, history):
    return window.verify_window(**bind(data, history))


class ModelWindowHistoryTests(unittest.TestCase):
    def setUp(self):
        self.first = model_fixture(1)
        self.genesis = initial_history(self.first)
        self.one = complete(self.first, self.genesis)
        self.history = self.one['history']
        self.second = model_fixture(2)

    def large_history(self):
        # Retained synthetic exposure summaries, not evidence of past training.
        # The original domain accepts this below its declared 16 MiB ceiling.
        history = copy.deepcopy(self.history)
        row = history['entries'][0]
        row['tasks'] = sorted((dict(id=identity('large-id:' + str(i)),
            prompt=identity('large-prompt:' + str(i)), group=identity('large-group:' + str(i)),
            partition='evaluation' if i % 2 else 'calibration') for i in range(10000)),
            key=lambda task: task['id'])
        history['head'] = window._identity(window.ENTRY_DOMAIN, row)
        return history

    def test_history_above_generic_manifest_limit_can_extend_without_changing_policy(self):
        from llm_adapter_contract import MAX_MANIFEST_BYTES, decode
        history = self.large_history()
        raw, hid = window.freeze_history(history)
        self.assertGreater(len(raw), MAX_MANIFEST_BYTES)
        self.assertLess(len(raw), window.MAX_HISTORY_BYTES)
        # The general decoder keeps the original manifest policy.
        with self.assertRaisesRegex(ValueError, 'LLM_MANIFEST_LIMIT'):
            decode(raw, hid, window._history, window.HISTORY_DOMAIN)
        self.assertEqual(window._decode_history(raw, hid), history)
        saved = canonical(history)
        rebuild(self.second, gain=False)
        result = complete(self.second, history)
        self.assertEqual(canonical(history), saved)
        self.assertTrue(result['window_consumed'])
        self.assertFalse(result['history']['entries'][-1]['reported_gates_passed'])
        self.assertEqual(len(result['history']['entries']), 2)
        for field in ('historical_execution_verified', 'hidden_windows_excluded',
                      'physical_custody_verified', 'prospective_accepted',
                      'independent_accepted', 'public_reward_eligible', 'production_activation'):
            self.assertIs(result[field], False)
        third = model_fixture(3)
        self.evaluation(third)['prompt_sha256'] = self.evaluation(self.second)['prompt_sha256']
        rebuild(third)
        with self.assertRaisesRegex(ValueError, 'WINDOW_REUSED_PROMPT'):
            bind(third, result['history'])

    def test_large_history_still_checks_pin_canonical_form_and_complete_linkage(self):
        from contract_wire import H
        raw, hid = window.freeze_history(self.large_history())
        with self.assertRaisesRegex(ValueError, 'LLM_MANIFEST_IDENTITY'):
            window._decode_history(raw, identity('wrong-pin'))
        noncanonical = raw + b'\n'
        with self.assertRaisesRegex(ValueError, 'LLM_MANIFEST_CANONICAL'):
            window._decode_history(noncanonical, H(window.HISTORY_DOMAIN, noncanonical).hex())
        broken = self.large_history()
        broken['entries'][0]['tasks'].pop()
        encoded = canonical(broken)
        with self.assertRaisesRegex(ValueError, 'WINDOW_HISTORY_HEAD'):
            window._decode_history(encoded, H(window.HISTORY_DOMAIN, encoded).hex())
        duplicate = b'{"head":"' + b'f'*64 + b'",' + raw[1:]
        with self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
            window._decode_history(duplicate, H(window.HISTORY_DOMAIN, duplicate).hex())
        self.assertEqual(window.freeze_history(window._decode_history(raw, hid))[1], hid)

    def test_history_size_limit_precedes_hash_or_json_and_invalid_byte_policies_reject(self):
        from llm_adapter_contract import decode
        over = b' ' * (window.MAX_HISTORY_BYTES + 1)
        with self.assertRaisesRegex(ValueError, 'WINDOW_HISTORY_BYTE_BOUND'):
            window._decode_history(over, identity('not-a-pin'))
        raw, hid = window.freeze_history(self.history)
        for bound in (False, True, 0, -1, 2.5, None):
            with self.subTest(bound=bound), self.assertRaisesRegex(ValueError, 'LLM_MANIFEST_LIMIT'):
                decode(raw, hid, window._history, window.HISTORY_DOMAIN, max_bytes=bound)
        self.assertEqual(decode(raw, hid, window._history, window.HISTORY_DOMAIN,
                                max_bytes=len(raw)), self.history)
        with self.assertRaisesRegex(ValueError, 'LLM_MANIFEST_LIMIT'):
            decode(raw, hid, window._history, window.HISTORY_DOMAIN, max_bytes=len(raw)-1)

    def evaluation(self, data):
        return next(t for t in data['plan']['tasks'] if t['partition'] == 'evaluation')

    def calibration(self, data):
        return next(t for t in data['plan']['tasks'] if t['partition'] == 'calibration')

    def test_three_windows_link_all_entries_and_keep_external_flags_false(self):
        original = copy.deepcopy(self.history)
        two = complete(self.second, self.history)
        three = complete(model_fixture(3), two['history'])
        self.assertEqual(original, self.history)
        self.assertEqual(len(three['history']['entries']), 3)
        self.assertEqual(two['previous_history'], self.one['next_history'])
        self.assertEqual(three['previous_history'], two['next_history'])
        self.assertEqual(window.freeze_history(three['history'])[1], three['next_history'])
        for result in (self.one, two, three):
            self.assertTrue(result['window_consumed'])
            self.assertTrue(result['assessment']['reported_gates_passed'])
            for field in ('historical_execution_verified', 'hidden_windows_excluded',
                          'physical_custody_verified', 'prospective_accepted',
                          'independent_accepted', 'public_reward_eligible', 'production_activation'):
                self.assertIs(result[field], False)

    def test_old_evaluation_id_rejects_with_new_prompt_and_group(self):
        self.evaluation(self.second)['id'] = self.evaluation(self.first)['id']
        rebuild(self.second)
        with self.assertRaisesRegex(ValueError, 'WINDOW_REUSED_TASK'):
            bind(self.second, self.history)

    def test_old_evaluation_prompt_rejects_after_id_and_group_relabel(self):
        self.evaluation(self.second)['prompt_sha256'] = self.evaluation(self.first)['prompt_sha256']
        rebuild(self.second)
        with self.assertRaisesRegex(ValueError, 'WINDOW_REUSED_PROMPT'):
            bind(self.second, self.history)

    def test_old_calibration_prompt_is_not_fresh_evaluation(self):
        self.evaluation(self.second)['prompt_sha256'] = self.calibration(self.first)['prompt_sha256']
        rebuild(self.second)
        with self.assertRaisesRegex(ValueError, 'WINDOW_REUSED_PROMPT'):
            bind(self.second, self.history)

    def test_old_probe_prompt_is_not_fresh_evaluation(self):
        self.evaluation(self.second)['prompt_sha256'] = self.first['prereg']['probes'][0]['prompt']
        rebuild(self.second)
        with self.assertRaisesRegex(ValueError, 'WINDOW_REUSED_PROMPT'):
            bind(self.second, self.history)

    def test_old_training_calibration_and_evaluation_groups_reject(self):
        groups = [self.first['prereg']['training_groups'][0],
                  self.calibration(self.first)['source_group'],
                  self.evaluation(self.first)['source_group']]
        for group in groups:
            data = model_fixture(2)
            self.evaluation(data)['source_group'] = group
            rebuild(data)
            with self.subTest(group=group), self.assertRaisesRegex(ValueError, 'WINDOW_REUSED_GROUP'):
                bind(data, self.history)

    def test_old_tasks_can_train_and_calibrate_when_future_evaluation_is_new(self):
        source = self.calibration(self.first)
        target = self.calibration(self.second)
        for field in ('id', 'prompt_sha256', 'source_group'):
            target[field] = source[field]
        self.second['prereg']['training_groups'] = [self.evaluation(self.first)['source_group']]
        self.second['prereg']['probes'] = copy.deepcopy(self.first['prereg']['probes'])
        rebuild(self.second)
        self.assertTrue(complete(self.second, self.history)['window_consumed'])

    def test_common_target_outputs_are_not_a_global_exclusion_set(self):
        self.assertEqual({t['target_output_sha256'] for t in self.first['plan']['tasks']},
                         {t['target_output_sha256'] for t in self.second['plan']['tasks']})
        self.assertTrue(complete(self.second, self.history)['window_consumed'])

    def test_candidate_may_change_within_fixed_owner_governance_context(self):
        self.second['plan']['candidate'] = identity('different-candidate')
        rebuild(self.second)
        self.assertTrue(complete(self.second, self.history)['window_consumed'])

    def test_zero_gain_consumes_window_and_cannot_retry_same_future_prompts(self):
        rebuild(self.second, gain=False)
        result = complete(self.second, self.history)
        self.assertFalse(result['assessment']['reported_gates']['reported_gain'])
        self.assertFalse(result['history']['entries'][-1]['reported_gates_passed'])
        third = model_fixture(3)
        self.evaluation(third)['prompt_sha256'] = self.evaluation(self.second)['prompt_sha256']
        rebuild(third)
        with self.assertRaisesRegex(ValueError, 'WINDOW_REUSED_PROMPT'):
            bind(third, result['history'])

    def test_malformed_current_record_does_not_advance_or_mutate_history(self):
        args = bind(self.second, self.history)
        saved = canonical(self.history)
        args['material'] = dict(args['material'])
        args['material'].pop(next(iter(args['material'])))
        with self.assertRaisesRegex(ValueError, 'MATERIAL_SET'):
            window.verify_window(**args)
        self.assertEqual(canonical(self.history), saved)
        self.assertEqual(window.freeze_history(self.history)[1], self.one['next_history'])

    def test_declared_over_budget_run_is_not_consumed_as_successful_evidence(self):
        args = bind(self.second, self.history)
        saved = canonical(self.history)
        args['record'] = copy.deepcopy(args['record'])
        args['record']['participants'][0]['runs'][0]['costs'][0]['cpu_ns'] = (1 << 63) - 1
        with self.assertRaisesRegex(ValueError, 'LLM_REPORTED_BUDGET_EXCEEDED'):
            window.verify_window(**args)
        self.assertEqual(canonical(self.history), saved)

    def test_external_history_and_window_identities_cannot_be_self_selected(self):
        for field in ('expected_history', 'expected_window'):
            args = bind(self.second, self.history)
            args[field] = identity('untrusted-replacement')
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'MANIFEST_IDENTITY'):
                window.verify_window(**args)

    def test_rewind_to_empty_history_fails_against_pinned_latest_identity(self):
        args = bind(self.second, self.history)
        args['history_raw'] = window.freeze_history(self.genesis)[0]
        with self.assertRaisesRegex(ValueError, 'MANIFEST_IDENTITY'):
            window.verify_window(**args)

    def test_omitted_entry_cannot_retain_its_chain_head(self):
        changed = copy.deepcopy(self.history)
        changed['entries'].clear()
        with self.assertRaisesRegex(ValueError, 'WINDOW_HISTORY_HEAD'):
            window.freeze_history(changed)

    def test_reordered_duplicate_and_modified_prior_entries_reject(self):
        history = complete(self.second, self.history)['history']
        variants = []
        changed = copy.deepcopy(history); changed['entries'].reverse(); variants.append(changed)
        changed = copy.deepcopy(history); changed['entries'][1] = copy.deepcopy(changed['entries'][0]); variants.append(changed)
        changed = copy.deepcopy(history); changed['entries'][0]['receipt'] = identity('substitute'); variants.append(changed)
        for changed in variants:
            with self.subTest(entries=changed['entries']), self.assertRaisesRegex(ValueError, 'WINDOW_HISTORY_LINK'):
                window.freeze_history(changed)

    def test_old_declared_identity_sets_are_rebuilt_not_supplied_as_authority(self):
        changed = copy.deepcopy(self.history)
        changed['exposed_prompts'] = []
        with self.assertRaisesRegex(ValueError, 'WINDOW_HISTORY_FIELDS'):
            window.freeze_history(changed)

    def test_owner_governance_or_series_change_requires_a_fresh_external_context(self):
        for field in ('owner', 'governance'):
            data = model_fixture(2)
            data['prereg'][field] = identity('changed-' + field)
            rebuild(data)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'WINDOW_OWNER_GOVERNANCE'):
                bind(data, self.history)
        args = bind(self.second, self.history)
        alternate = window.empty_history(identity('alternate-series'), self.second['prereg']['owner'],
                                         self.second['prereg']['governance'])
        args['history_raw'], args['expected_history'] = window.freeze_history(alternate)
        with self.assertRaisesRegex(ValueError, 'WINDOW_PREREGISTRATION_BINDING'):
            window.verify_window(**args)

    def test_later_window_registration_must_follow_prior_observed_record(self):
        self.second['prereg']['registered_at'] = self.first['receipt']['observed_at']
        rebuild(self.second)
        with self.assertRaisesRegex(ValueError, 'WINDOW_CHRONOLOGY'):
            bind(self.second, self.history)

    def test_history_gate_boolean_ordinal_and_unknown_field_boundaries(self):
        for value in (0, 1, None, 'true'):
            changed = copy.deepcopy(self.history)
            changed['entries'][0]['reported_gates_passed'] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'WINDOW_GATE_TYPE'):
                window.freeze_history(changed)
        changed = copy.deepcopy(self.history)
        changed['entries'][0]['window']['ordinal'] = True
        with self.assertRaisesRegex(ValueError, 'WINDOW_ORDINAL'):
            window.freeze_history(changed)
        changed = copy.deepcopy(self.history)
        changed['entries'][0]['production_activation'] = True
        with self.assertRaisesRegex(ValueError, 'WINDOW_ENTRY_FIELDS'):
            window.freeze_history(changed)

    def test_history_count_byte_and_cumulative_item_limits(self):
        with patch.object(window, 'MAX_WINDOWS', 1):
            with self.assertRaisesRegex(ValueError, 'WINDOW_HISTORY_FULL'):
                bind(self.second, self.history)
        raw, _ = window.freeze_history(self.history)
        with patch.object(window, 'MAX_HISTORY_BYTES', len(raw) - 1):
            with self.assertRaisesRegex(ValueError, 'WINDOW_HISTORY_BYTE_BOUND'):
                window.freeze_history(self.history)
        existing = sum(len(self.history['entries'][0][name])
                       for name in ('tasks', 'probe_prompts', 'training_groups'))
        with patch.object(window, 'MAX_ITEMS', existing):
            with self.assertRaisesRegex(ValueError, 'WINDOW_HISTORY_ITEM_BOUND'):
                bind(self.second, self.history)

    def test_preregistration_reserves_bytes_for_the_completed_window(self):
        result = complete(self.second, self.history)
        actual_bytes = len(window.freeze_history(result['history'])[0])
        # The current history fits. Its next result cannot fit, so do not admit
        # that evaluation window before its reported outcome can be retained.
        self.assertLess(len(window.freeze_history(self.history)[0]), actual_bytes - 1)
        with patch.object(window, 'MAX_HISTORY_BYTES', actual_bytes - 1):
            with self.assertRaisesRegex(ValueError, 'WINDOW_HISTORY_BYTE_BOUND'):
                bind(self.second, self.history)

    def test_exact_reserved_bytes_can_retain_a_late_false_gate_outcome(self):
        rebuild(self.second, gain=False)
        self.second['receipt']['observed_at'] = self.second['prereg']['closes_at']
        result = complete(self.second, self.history)
        exact_bytes = len(window.freeze_history(result['history'])[0])
        with patch.object(window, 'MAX_HISTORY_BYTES', exact_bytes):
            retained = complete(self.second, self.history)
            self.assertFalse(retained['history']['entries'][-1]['reported_gates_passed'])
            self.assertEqual(len(window.freeze_history(retained['history'])[0]), exact_bytes)

    def test_history_task_prompts_and_partition_coverage_match_v1_shape(self):
        changed = copy.deepcopy(self.history)
        tasks = changed['entries'][0]['tasks']
        tasks[1]['prompt'] = tasks[0]['prompt']
        with self.assertRaisesRegex(ValueError, 'WINDOW_TASK_PROMPT_ALIAS'):
            window.freeze_history(changed)
        changed = copy.deepcopy(self.history)
        changed['entries'][0]['tasks'] = [t for t in changed['entries'][0]['tasks']
                                          if t['partition'] == 'evaluation']
        with self.assertRaisesRegex(ValueError, 'WINDOW_PARTITION_COVERAGE'):
            window.freeze_history(changed)

    def test_noncanonical_and_duplicate_json_cannot_create_a_history_anchor(self):
        args = bind(self.second, self.history)
        args['history_raw'] += b'\n'
        args['expected_history'] = H(window.HISTORY_DOMAIN, args['history_raw']).hex()
        with self.assertRaisesRegex(ValueError, 'MANIFEST_CANONICAL'):
            window.verify_window(**args)
        args = bind(self.second, self.history)
        args['history_raw'] = b'{"schema":0,"schema":1}'
        args['expected_history'] = H(window.HISTORY_DOMAIN, args['history_raw']).hex()
        with self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
            window.verify_window(**args)


class ModelExposureAdmissionTests(unittest.TestCase):
    """Synthetic owner inputs, not model execution, custody or independence."""
    def setUp(self):
        self.first = model_fixture(1)
        self.legacy = initial_history(self.first)
        raw, pin = window.freeze_history(self.legacy)
        self.initial = window.upgrade_exposure_history(raw, pin)

    def admit(self, data, history):
        raw, pin = window.freeze_exposure_history(history)
        return window.admit_exposure_window(raw, pin, data['raw'], data['aid'],
                                             data['plan'], data['pid'])

    def pending_args(self, result):
        raw, pin = window.freeze_exposure_history(result['history'])
        self.assertEqual(pin, result['next_history'])
        return dict(history_raw=raw, expected_history=pin, expected_window=result['window'])

    def finish(self, data, result):
        return window.finish_exposure_window(**self.pending_args(result),
            preregistration_raw=data['raw'], expected_preregistration=data['aid'],
            plan=data['plan'], expected_plan=data['pid'], record=data['record'],
            receipt=data['receipt'], material=data['material'])

    def abort(self, result, observed_at=None):
        return window.abort_exposure_window(**self.pending_args(result),
            observed_at=self.first['receipt']['observed_at'] if observed_at is None else observed_at,
            failure_digest=identity('retained-failed-process-observation'))

    def test_admission_consumes_before_any_evaluator_or_complete_result(self):
        original = canonical(self.initial)
        with patch.object(window, 'verify_acceptance', side_effect=AssertionError('must not run')):
            start = self.admit(self.first, self.initial)
        row = start['history']['entries'][-1]
        self.assertEqual(row['status'], 'pending')
        self.assertIsNone(row['receipt'])
        self.assertIsNone(row['reported_gates_passed'])
        self.assertIsNone(start['assessment'])
        self.assertTrue(start['window_consumed'])
        self.assertTrue(start['owner_persistence_required'])
        self.assertEqual(canonical(self.initial), original)
        for flag in ('historical_execution_verified', 'hidden_windows_excluded',
                     'physical_custody_verified', 'prospective_accepted',
                     'independent_accepted', 'public_reward_eligible', 'production_activation'):
            self.assertIs(start[flag], False)

    def test_pending_blocks_even_an_unrelated_next_window(self):
        pending = self.admit(self.first, self.initial)
        for data in (self.first, model_fixture(2)):
            with self.assertRaisesRegex(ValueError, 'EXPOSURE_ALREADY_PENDING'):
                self.admit(data, pending['history'])

    def test_invalid_result_does_not_erase_the_original_pending_exposure(self):
        pending = self.admit(self.first, self.initial)
        saved = canonical(pending['history'])
        invalid = copy.deepcopy(self.first)
        invalid['record']['schema'] = 'not-a-run'
        with self.assertRaises(ValueError):
            self.finish(invalid, pending)
        self.assertEqual(canonical(pending['history']), saved)
        with self.assertRaisesRegex(ValueError, 'EXPOSURE_ALREADY_PENDING'):
            self.admit(model_fixture(2), pending['history'])
        self.assertEqual(self.abort(pending)['history']['entries'][-1]['status'], 'aborted')

    def test_aborted_window_prevents_task_prompt_and_group_relabelling(self):
        done = self.abort(self.admit(self.first, self.initial))
        first = next(t for t in self.first['plan']['tasks'] if t['partition'] == 'evaluation')
        for field, error in [('id', 'WINDOW_REUSED_TASK'), ('prompt_sha256', 'WINDOW_REUSED_PROMPT'),
                             ('source_group', 'WINDOW_REUSED_GROUP')]:
            data = model_fixture(2)
            task = next(t for t in data['plan']['tasks'] if t['partition'] == 'evaluation')
            task[field] = first[field]
            rebuild(data)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, error):
                self.admit(data, done['history'])
        self.assertEqual(self.admit(model_fixture(2), done['history'])['history']['entries'][-1]['status'],
                         'pending')

    def test_abort_retains_probe_and_training_exposures(self):
        done = self.abort(self.admit(self.first, self.initial))
        for field, value, error in [
            ('prompt_sha256', self.first['prereg']['probes'][0]['prompt'], 'WINDOW_REUSED_PROMPT'),
            ('source_group', self.first['prereg']['training_groups'][0], 'WINDOW_REUSED_GROUP')]:
            data = model_fixture(2)
            task = next(t for t in data['plan']['tasks'] if t['partition'] == 'evaluation')
            task[field] = value
            rebuild(data)
            with self.assertRaisesRegex(ValueError, error):
                self.admit(data, done['history'])

    def test_three_linked_windows_keep_abort_zero_gain_and_verified_outcome(self):
        first = self.abort(self.admit(self.first, self.initial))
        second_data = model_fixture(2)
        rebuild(second_data, gain=False)
        second = self.finish(second_data, self.admit(second_data, first['history']))
        third_data = model_fixture(3)
        third = self.finish(third_data, self.admit(third_data, second['history']))
        rows = third['history']['entries']
        self.assertEqual([row['status'] for row in rows], ['aborted', 'completed', 'completed'])
        self.assertEqual([row['reported_gates_passed'] for row in rows], [False, False, True])
        self.assertFalse(third['prospective_accepted'])
        self.assertFalse(third['production_activation'])
        self.assertEqual(rows[0], first['history']['entries'][0])
        self.assertEqual(rows[1], second['history']['entries'][1])
        self.assertEqual([r['window']['ordinal'] for r in rows], [1, 2, 3])

    def test_completed_and_aborted_windows_cannot_be_resettled_or_resurrected(self):
        pending = self.admit(self.first, self.initial)
        for done in (self.abort(pending), self.finish(self.first, pending)):
            with self.assertRaisesRegex(ValueError, 'EXPOSURE_NOT_PENDING'):
                self.abort(done)
            with self.assertRaisesRegex(ValueError, 'EXPOSURE_NOT_PENDING'):
                self.finish(self.first, done)
            args = self.pending_args(pending)
            args['history_raw'] = self.pending_args(done)['history_raw']
            with self.assertRaisesRegex(ValueError, 'MANIFEST_IDENTITY'):
                window.abort_exposure_window(**args, observed_at=1000,
                    failure_digest=identity('failed'))

    def test_settlement_binds_original_window_plan_and_preregistration(self):
        pending = self.admit(self.first, self.initial)
        with self.assertRaisesRegex(ValueError, 'EXPOSURE_RESULT_BINDING'):
            self.finish(model_fixture(2), pending)
        args = self.pending_args(pending)
        args['expected_window'] = identity('different-window')
        with self.assertRaisesRegex(ValueError, 'EXPOSURE_WINDOW_IDENTITY'):
            window.abort_exposure_window(**args, observed_at=1000, failure_digest=identity('failed'))
        changed = copy.deepcopy(self.first)
        changed['plan']['owner_record'] = identity('changed-plan')
        with self.assertRaises(ValueError):
            self.finish(changed, pending)

    def test_late_abort_stays_consumed_and_never_fabricates_a_model_result(self):
        pending = self.admit(self.first, self.initial)
        time = self.first['prereg']['closes_at'] + 5
        done = self.abort(pending, time)
        self.assertEqual(done['history']['entries'][-1]['observed_at'], time)
        self.assertIsNone(done['assessment'])
        for invalid in [0, self.first['prereg']['registered_at'], True, window.MAX_TIME + 1]:
            with self.subTest(time=invalid), self.assertRaises(ValueError):
                self.abort(pending, invalid)
        data = model_fixture(2)
        # No historical time rewind after a late failure.
        done = self.abort(pending, window.MAX_TIME)
        with self.assertRaisesRegex(ValueError, 'WINDOW_CHRONOLOGY'):
            self.admit(data, done['history'])

    def test_upgrade_preserves_complete_legacy_bytes_and_all_exposures(self):
        legacy = complete(self.first, self.legacy)['history']
        raw, pin = window.freeze_history(legacy)
        upgraded = window.upgrade_exposure_history(raw, pin)
        self.assertEqual(canonical(upgraded['prior_history']), raw)
        second = model_fixture(2)
        started = self.admit(second, upgraded)
        self.assertEqual(started['history']['entries'][0]['window']['ordinal'], 2)
        second['plan']['tasks'][0]['prompt_sha256'] = self.first['plan']['tasks'][0]['prompt_sha256']
        second['plan']['tasks'][0]['partition'] = 'evaluation'
        # Check legacy exclusion through the retained sets, without claiming
        # original v1 completed records were v2 pre-disclosure registrations.
        seen, _, _ = window._exposure_history(upgraded)
        self.assertIn(self.first['plan']['tasks'][0]['prompt_sha256'], seen['prompts'])
        with self.assertRaisesRegex(ValueError, 'MANIFEST_IDENTITY'):
            window.upgrade_exposure_history(raw, identity('old-anchor'))

    def test_old_and_new_parsers_and_domains_do_not_silently_upgrade(self):
        raw, pin = window.freeze_exposure_history(self.initial)
        with self.assertRaises(ValueError):
            window._decode_history(raw, H(window.HISTORY_DOMAIN, raw).hex())
        legacy, _ = window.freeze_history(self.legacy)
        with self.assertRaises(ValueError):
            window._decode_exposure_history(legacy, H(window.EXPOSURE_HISTORY_DOMAIN, legacy).hex())
        with self.assertRaisesRegex(ValueError, 'MANIFEST_IDENTITY'):
            window._decode_exposure_history(raw, H(window.HISTORY_DOMAIN, raw).hex())
        self.assertEqual(window._decode_exposure_history(raw, pin), self.initial)

    def test_tampered_head_order_status_and_noncanonical_bytes_refuse(self):
        pending = self.admit(self.first, self.initial)
        for field, value in [('head', identity('bad-head')), ('status', 'completed'),
                             ('receipt', identity('premature-result')), ('reported_gates_passed', True)]:
            changed = copy.deepcopy(pending['history'])
            if field == 'head':
                changed[field] = value
            else:
                changed['entries'][-1][field] = value
                changed['head'] = window._identity(window.EXPOSURE_ENTRY_DOMAIN, changed['entries'][-1])
            with self.subTest(field=field), self.assertRaises(ValueError):
                window.freeze_exposure_history(changed)
        raw, _ = window.freeze_exposure_history(pending['history'])
        for noncanonical in (raw + b'\n', b'{"head":"' + b'f'*64 + b'",' + raw[1:]):
            with self.assertRaises(ValueError):
                window._decode_exposure_history(noncanonical,
                    H(window.EXPOSURE_HISTORY_DOMAIN, noncanonical).hex())

    def test_both_terminal_shapes_are_reserved_before_disclosure(self):
        started = self.admit(self.first, self.initial)
        pending_bytes = len(canonical(started['history']))
        terminal = copy.deepcopy(started['history'])
        row = terminal['entries'][-1]
        row.update(status='aborted', receipt='f'*64, observed_at=window.MAX_TIME,
                   reported_gates_passed=False)
        terminal['head'] = window._identity(window.EXPOSURE_ENTRY_DOMAIN, row)
        terminal_bytes = len(window.freeze_exposure_history(terminal)[0])
        self.assertGreater(terminal_bytes, pending_bytes)
        with patch.object(window, 'MAX_HISTORY_BYTES', terminal_bytes - 1):
            with self.assertRaisesRegex(ValueError, 'WINDOW_HISTORY_BYTE_BOUND'):
                self.admit(self.first, self.initial)
        with patch.object(window, 'MAX_HISTORY_BYTES', terminal_bytes):
            pending = self.admit(self.first, self.initial)
            self.abort(pending, window.MAX_TIME)

    def test_item_and_window_capacity_are_reserved_before_admission(self):
        with patch.object(window, 'MAX_WINDOWS', 0):
            with self.assertRaisesRegex(ValueError, 'WINDOW_HISTORY_BOUND'):
                self.admit(self.first, self.initial)
        with patch.object(window, 'MAX_ITEMS', 1):
            with self.assertRaisesRegex(ValueError, 'WINDOW_HISTORY_ITEM_BOUND'):
                self.admit(self.first, self.initial)

    def test_wrong_owner_plan_and_cross_context_cannot_register_exposure(self):
        wrong = copy.deepcopy(self.initial)
        wrong['prior_history']['context']['owner'] = identity('foreign-owner')
        wrong['prior_history']['head'] = window._context(wrong['prior_history']['context'])
        wrong['head'] = window._identity(window.EXPOSURE_ANCHOR_DOMAIN, wrong['prior_history'])
        with self.assertRaisesRegex(ValueError, 'WINDOW_OWNER_CONTEXT'):
            self.admit(self.first, wrong)
        changed = copy.deepcopy(self.first)
        changed['pid'] = identity('not-the-plan')
        with self.assertRaises(ValueError):
            self.admit(changed, self.initial)


    def test_finish_rechecks_owner_even_for_a_resealed_foreign_history(self):
        pending = self.admit(self.first, self.initial)
        forged = copy.deepcopy(pending)
        prior = forged['history']['prior_history']
        prior['context']['owner'] = identity('foreign-durable-owner')
        prior['head'] = window._context(prior['context'])
        row = forged['history']['entries'][-1]
        row['window']['context'] = window._context(prior['context'])
        row['window']['previous'] = window._identity(window.EXPOSURE_ANCHOR_DOMAIN, prior)
        forged['history']['head'] = window._identity(window.EXPOSURE_ENTRY_DOMAIN, row)
        forged['window'] = window._identity(window.EXPOSURE_WINDOW_DOMAIN, row['window'])
        forged['next_history'] = window.freeze_exposure_history(forged['history'])[1]
        # Even a caller pinning this self-consistent foreign shape cannot bind
        # the current receipt to the wrong existing series authority.
        with self.assertRaisesRegex(ValueError, 'WINDOW_OWNER_CONTEXT'):
            self.finish(self.first, forged)


class ProspectiveGenerationLineageTests(unittest.TestCase):
    """Synthetic identity chain only; no model installation or benefit evidence."""

    def setUp(self):
        first = model_fixture(1)
        legacy = initial_history(first)
        raw, pin = window.freeze_history(legacy)
        self.initial = window.upgrade_exposure_history(raw, pin)

    def complete(self, data, history):
        raw, pin = window.freeze_exposure_history(history)
        pending = window.admit_exposure_window(raw, pin, data['raw'], data['aid'],
                                               data['plan'], data['pid'])
        pending_raw, pending_pin = window.freeze_exposure_history(pending['history'])
        return window.finish_exposure_window(
            pending_raw, pending_pin, pending['window'],
            data['raw'], data['aid'], data['plan'], data['pid'],
            data['record'], data['receipt'], data['material'])

    def three(self, gains=(True, True, True)):
        history = self.initial
        data = []
        for number, gain in enumerate(gains, 1):
            item = model_fixture(number)
            item['plan']['candidate'] = identity('prospective-candidate:' + str(number))
            rebuild(item, gain=gain)
            history = self.complete(item, history)['history']
            data.append(item)
        return history, data

    def rows(self, history, data, decisions=('adopted', 'adopted', 'adopted')):
        predecessor = identity('prospective-installed-parent')
        rows = []
        for retained, item, decision in zip(history['entries'][-3:], data, decisions):
            candidate = item['plan']['candidate']
            adopted = candidate if decision == 'adopted' else predecessor
            rows.append(dict(
                window=window._identity(window.EXPOSURE_WINDOW_DOMAIN, retained['window']),
                run_plan=item['pid'],
                predecessor_model=predecessor,
                candidate_model=candidate,
                adopted_model=adopted,
                decision=decision,
                consumer_receipt=identity('consumer:' + str(len(rows) + 1))))
            predecessor = adopted
        return rows

    def verify(self, history, rows):
        raw, pin = window.freeze_exposure_history(history)
        return window.verify_prospective_generation_chain(raw, pin, rows)

    def benefit(self, history, data, decisions=('adopted', 'adopted', 'adopted')):
        rows = self.rows(history, data, decisions)
        receipts = []
        for index, (generation, retained) in enumerate(
                zip(rows, history['entries'][-3:]), 1):
            adopted = generation['decision'] == 'adopted'
            receipt = dict(
                ordinal=index,
                consumer=identity('future-consumer:' + str(index)),
                controller=identity('future-controller:' + str(index)),
                task=identity('future-consumer-task:' + str(index)),
                input=identity('future-consumer-input:' + str(index)),
                predecessor_model=generation['predecessor_model'],
                candidate_model=generation['candidate_model'],
                adopted_model=generation['adopted_model'],
                baseline_output=identity('baseline-output:' + str(index)),
                candidate_output=identity('candidate-output:' + str(index)),
                metric='integer-loss-lower-is-better-v1',
                baseline_score=100,
                candidate_score=90 if adopted else 100,
                used_at=retained['observed_at'] + 1)
            generation['consumer_receipt'] = H(
                window.CONSUMER_BENEFIT_RECEIPT_DOMAIN, canonical(receipt)).hex()
            receipts.append(receipt)
        return rows, receipts

    def verify_benefit(self, history, rows, receipts):
        raw, pin = window.freeze_exposure_history(history)
        return window.verify_prospective_consumer_benefit(
            raw, pin, rows, receipts)

    def signed_benefit(self, history, data):
        rows, receipts = self.benefit(history, data)
        attestations = []
        for index, receipt in enumerate(receipts, 1):
            consumer = Ed25519PrivateKey.from_private_bytes(bytes([10 + index]) * 32)
            controller = Ed25519PrivateKey.from_private_bytes(bytes([20 + index]) * 32)
            consumer_public = consumer.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
            controller_public = controller.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
            receipt['consumer'] = H(window.CONSUMER_KEY_DOMAIN, consumer_public).hex()
            receipt['controller'] = H(window.CONTROLLER_KEY_DOMAIN, controller_public).hex()
            rows[index - 1]['consumer_receipt'] = H(
                window.CONSUMER_BENEFIT_RECEIPT_DOMAIN, canonical(receipt)).hex()
            message = H(window.CONSUMER_BENEFIT_ATTESTATION_DOMAIN, canonical(receipt))
            attestations.append(dict(
                ordinal=index,
                consumer_public_key=consumer_public.hex(),
                controller_public_key=controller_public.hex(),
                consumer_signature=consumer.sign(message).hex(),
                controller_signature=controller.sign(message).hex()))
        return rows, receipts, attestations

    def verify_signed_benefit(self, history, rows, receipts, attestations):
        raw, pin = window.freeze_exposure_history(history)
        return window.verify_signed_prospective_consumer_benefit(
            raw, pin, rows, receipts, attestations)

    def test_three_adopted_generations_form_exact_predecessor_chain_without_acceptance_upgrade(self):
        history, data = self.three()
        result = self.verify(history, self.rows(history, data))
        self.assertTrue(result['lineage_verified'])
        self.assertTrue(result['exposure_consumption_verified'])
        self.assertTrue(result['candidate_identity_externally_pinned'])
        self.assertEqual(len(result['generations']), 3)
        for left, right in zip(result['generations'], result['generations'][1:]):
            self.assertEqual(left['adopted_model'], right['predecessor_model'])
        for field in ('actual_model_installation_verified', 'new_consumer_benefit_verified',
                      'hidden_windows_excluded', 'physical_custody_verified',
                      'prospective_accepted', 'independent_accepted',
                      'public_reward_eligible', 'production_activation'):
            self.assertIs(result[field], False)

    def test_no_update_preserves_predecessor_and_next_generation_must_continue_from_it(self):
        history, data = self.three((True, False, True))
        rows = self.rows(history, data, ('adopted', 'no_update', 'adopted'))
        result = self.verify(history, rows)
        self.assertEqual(result['generations'][1]['adopted_model'],
                         result['generations'][1]['predecessor_model'])
        self.assertEqual(result['generations'][1]['adopted_model'],
                         result['generations'][2]['predecessor_model'])
        broken = copy.deepcopy(rows)
        broken[2]['predecessor_model'] = identity('wrong-predecessor')
        with self.assertRaisesRegex(ValueError, 'PROSPECTIVE_PREDECESSOR'):
            self.verify(history, broken)

    def test_failed_reported_gate_cannot_be_relabelled_as_adopted_model(self):
        history, data = self.three((True, False, True))
        rows = self.rows(history, data)
        with self.assertRaisesRegex(ValueError, 'PROSPECTIVE_ADOPTION_GATE'):
            self.verify(history, rows)

    def test_window_run_plan_and_decision_shapes_are_exact(self):
        history, data = self.three()
        rows = self.rows(history, data)
        changed = copy.deepcopy(rows)
        changed[1]['run_plan'] = identity('other-plan')
        with self.assertRaisesRegex(ValueError, 'PROSPECTIVE_WINDOW_BINDING'):
            self.verify(history, changed)
        changed = copy.deepcopy(rows)
        changed[0]['decision'] = 'rollback'
        with self.assertRaisesRegex(ValueError, 'PROSPECTIVE_DECISION'):
            self.verify(history, changed)
        changed = copy.deepcopy(rows)
        changed[0]['extra'] = True
        with self.assertRaisesRegex(ValueError, 'PROSPECTIVE_GENERATION_FIELDS'):
            self.verify(history, changed)

    def test_explicit_v2_hold_retains_improved_candidate_without_reinterpreting_v1(self):
        history, data = self.three()
        rows, receipts = self.benefit(history, data, ('adopted', 'no_update', 'adopted'))
        receipts[1]['candidate_score'] = 90
        for index, receipt in enumerate(receipts):
            receipt['decision_reason'] = 'safety_hold' if index == 1 else 'adopted_gain'
            receipt['owner_decision'] = identity('owner-decision:' + str(index))
            rows[index]['consumer_receipt'] = H(
                'model-consumer-decision-receipt-v2', canonical(receipt)).hex()
        raw, pin = window.freeze_exposure_history(history)
        result = window.verify_prospective_consumer_decisions_v2(raw, pin, rows, receipts)
        self.assertTrue(result['receipts'][1]['improved'])
        self.assertEqual(result['receipts'][1]['decision'], 'no_update')
        self.assertEqual(rows[2]['predecessor_model'], rows[1]['predecessor_model'])
        self.assertFalse(result['actual_model_installation_verified'])
        self.assertFalse(result['production_activation'])
        with self.assertRaisesRegex(ValueError, 'CONSUMER_BENEFIT_FIELDS'):
            window.verify_prospective_consumer_benefit(raw, pin, rows, receipts)
        changed = copy.deepcopy(receipts)
        changed[1]['decision_reason'] = 'no_gain'
        changed_rows = copy.deepcopy(rows)
        changed_rows[1]['consumer_receipt'] = H(
            'model-consumer-decision-receipt-v2', canonical(changed[1])).hex()
        with self.assertRaisesRegex(ValueError, 'CONSUMER_DECISION_NO_GAIN'):
            window.verify_prospective_consumer_decisions_v2(raw, pin, changed_rows, changed)
        changed[1]['decision_reason'] = 'adopted_gain'
        changed_rows[1]['consumer_receipt'] = H(
            'model-consumer-decision-receipt-v2', canonical(changed[1])).hex()
        with self.assertRaisesRegex(ValueError, 'CONSUMER_DECISION_BINDING'):
            window.verify_prospective_consumer_decisions_v2(raw, pin, changed_rows, changed)
        changed = copy.deepcopy(receipts)
        changed[1]['owner_decision'] = identity('substituted-owner-decision')
        with self.assertRaisesRegex(ValueError, 'CONSUMER_BENEFIT_RECEIPT_BINDING'):
            window.verify_prospective_consumer_decisions_v2(raw, pin, rows, changed)

    def test_explicit_v2_signatures_bind_hold_reason_and_reject_v1_domain_replay(self):
        history, data = self.three()
        rows, receipts, attestations = self.signed_benefit(history, data)
        for index, receipt in enumerate(receipts, 1):
            receipt['decision_reason'] = 'adopted_gain'
            receipt['owner_decision'] = identity('signed-owner-decision:' + str(index))
            rows[index - 1]['consumer_receipt'] = H(
                'model-consumer-decision-receipt-v2', canonical(receipt)).hex()
        raw, pin = window.freeze_exposure_history(history)
        with self.assertRaisesRegex(ValueError, 'CONSUMER_BENEFIT_CONSUMER_SIGNATURE'):
            window.verify_signed_prospective_consumer_decisions_v2(
                raw, pin, rows, receipts, attestations)
        for index, (receipt, attestation) in enumerate(zip(receipts, attestations), 1):
            consumer = Ed25519PrivateKey.from_private_bytes(bytes([10 + index]) * 32)
            controller = Ed25519PrivateKey.from_private_bytes(bytes([20 + index]) * 32)
            message = H('model-consumer-decision-attestation-v2', canonical(receipt))
            attestation['consumer_signature'] = consumer.sign(message).hex()
            attestation['controller_signature'] = controller.sign(message).hex()
        result = window.verify_signed_prospective_consumer_decisions_v2(
            raw, pin, rows, receipts, attestations)
        self.assertTrue(result['external_receipt_signatures_verified'])
        self.assertFalse(result['actual_model_installation_verified'])
        self.assertFalse(result['independent_controller_verified'])
        self.assertFalse(result['public_reward_eligible'])

    def test_post_window_consumer_gain_relation_is_exact_but_not_external_acceptance(self):
        history, data = self.three()
        rows, receipts = self.benefit(history, data)
        result = self.verify_benefit(history, rows, receipts)
        self.assertTrue(result['structural_consumer_benefit_verified'])
        self.assertTrue(result['future_use_after_window_verified'])
        self.assertTrue(result['distinct_consumer_relations_verified'])
        self.assertEqual([row['improved'] for row in result['receipts']],
                         [True, True, True])
        for field in ('actual_model_installation_verified',
                      'independent_controller_verified',
                      'new_consumer_benefit_verified', 'prospective_accepted',
                      'independent_accepted', 'public_reward_eligible',
                      'production_activation'):
            self.assertIs(result[field], False)

    def test_no_update_requires_no_structural_gain_and_adoption_requires_gain(self):
        history, data = self.three((True, False, True))
        rows, receipts = self.benefit(
            history, data, ('adopted', 'no_update', 'adopted'))
        result = self.verify_benefit(history, rows, receipts)
        self.assertFalse(result['receipts'][1]['improved'])

        gained = copy.deepcopy(receipts)
        gained[1]['candidate_score'] = 90
        rows_gain = copy.deepcopy(rows)
        rows_gain[1]['consumer_receipt'] = H(
            window.CONSUMER_BENEFIT_RECEIPT_DOMAIN, canonical(gained[1])).hex()
        with self.assertRaisesRegex(ValueError, 'CONSUMER_BENEFIT_NO_UPDATE'):
            self.verify_benefit(history, rows_gain, gained)

        gain_history, gain_data = self.three()
        rows, receipts = self.benefit(gain_history, gain_data)
        receipts[0]['candidate_score'] = receipts[0]['baseline_score']
        rows[0]['consumer_receipt'] = H(
            window.CONSUMER_BENEFIT_RECEIPT_DOMAIN, canonical(receipts[0])).hex()
        with self.assertRaisesRegex(ValueError, 'CONSUMER_BENEFIT_ADOPTED_GAIN'):
            self.verify_benefit(gain_history, rows, receipts)

    def test_external_consumer_and_controller_signatures_bind_exact_receipts_without_acceptance_upgrade(self):
        history, data = self.three()
        rows, receipts, attestations = self.signed_benefit(history, data)
        result = self.verify_signed_benefit(history, rows, receipts, attestations)
        self.assertTrue(result['external_receipt_signatures_verified'])
        self.assertTrue(result['disjoint_consumer_controller_keys_verified'])
        self.assertEqual(len(result['signed_receipt_attestations']), 3)
        for field in ('actual_model_installation_verified',
                      'independent_controller_verified', 'new_consumer_benefit_verified',
                      'prospective_accepted', 'independent_accepted',
                      'public_reward_eligible', 'production_activation'):
            self.assertIs(result[field], False)

    def test_external_receipt_signature_key_alias_tamper_and_relabel_fail_closed(self):
        history, data = self.three()
        rows, receipts, attestations = self.signed_benefit(history, data)

        changed = copy.deepcopy(attestations)
        changed[1]['consumer_public_key'] = changed[0]['consumer_public_key']
        with self.assertRaisesRegex(ValueError, 'CONSUMER_BENEFIT_KEY_ALIAS'):
            self.verify_signed_benefit(history, rows, receipts, changed)

        changed = copy.deepcopy(attestations)
        signature = bytearray.fromhex(changed[2]['controller_signature'])
        signature[-1] ^= 1
        changed[2]['controller_signature'] = bytes(signature).hex()
        with self.assertRaisesRegex(ValueError, 'CONSUMER_BENEFIT_CONTROLLER_SIGNATURE'):
            self.verify_signed_benefit(history, rows, receipts, changed)

        changed_receipts = copy.deepcopy(receipts)
        changed_receipts[0]['consumer'] = identity('self-relabelled-consumer')
        changed_rows = copy.deepcopy(rows)
        changed_rows[0]['consumer_receipt'] = H(
            window.CONSUMER_BENEFIT_RECEIPT_DOMAIN, canonical(changed_receipts[0])).hex()
        with self.assertRaisesRegex(ValueError, 'CONSUMER_BENEFIT_CONSUMER_KEY_BINDING'):
            self.verify_signed_benefit(history, changed_rows, changed_receipts, attestations)

    def test_consumer_receipts_require_fresh_future_identity_and_exact_pin(self):
        history, data = self.three()
        rows, receipts = self.benefit(history, data)

        reused = copy.deepcopy(receipts)
        reused[1]['consumer'] = reused[0]['consumer']
        rows_reused = copy.deepcopy(rows)
        rows_reused[1]['consumer_receipt'] = H(
            window.CONSUMER_BENEFIT_RECEIPT_DOMAIN, canonical(reused[1])).hex()
        with self.assertRaisesRegex(ValueError, 'CONSUMER_BENEFIT_FRESH_CONSUMER'):
            self.verify_benefit(history, rows_reused, reused)

        early = copy.deepcopy(receipts)
        early[0]['used_at'] = history['entries'][-3]['observed_at']
        rows_early = copy.deepcopy(rows)
        rows_early[0]['consumer_receipt'] = H(
            window.CONSUMER_BENEFIT_RECEIPT_DOMAIN, canonical(early[0])).hex()
        with self.assertRaisesRegex(ValueError, 'CONSUMER_BENEFIT_FUTURE_USE'):
            self.verify_benefit(history, rows_early, early)

        tampered = copy.deepcopy(receipts)
        tampered[2]['candidate_output'] = identity('tampered-output')
        with self.assertRaisesRegex(ValueError, 'CONSUMER_BENEFIT_RECEIPT_BINDING'):
            self.verify_benefit(history, rows, tampered)


if __name__ == '__main__':
    unittest.main(verbosity=2)