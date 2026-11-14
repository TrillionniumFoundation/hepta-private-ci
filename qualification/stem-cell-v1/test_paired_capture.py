import copy
import json
import tempfile
import time
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import torch

from empirical_continuation import case_fingerprint
from execution_meter import WorkLedger
from matrix_materials import strict_json
from next_round_matrix import _digest
from paired_capture import (PROFILE, PairedStart, PairCollector, create_capture, freeze_capture,
                            read_task, validate_capture)
from paired_capture_export import read_pair
from paired_critic import freeze_protocol
from paired_execution import PHASES
from system2_execution import PublicTask, Verification, run_reasoning
from test_execution_meter import policy


class Clock:
    def __init__(self):
        self.now, self.started = 1000, time.perf_counter_ns()
    def __call__(self):
        self.now += 100_000_000
        return self.now + time.perf_counter_ns() - self.started


class Callbacks:
    def __init__(self, fail=False, wrong=False):
        self.calls, self.fail, self.wrong, self.accept_all = [], fail, wrong, False
        self.extra_work = 0
    def propose(self, task, previous, feedback):
        self.calls.append(('propose', task.prompt, previous, feedback))
        torch.ones(3).add(1)
        if self.extra_work: torch.ones(self.extra_work).add(1)
        if self.fail: raise RuntimeError('explicit test provider failure')
        if previous is None: return '0'
        return '-1' if self.wrong else str(sum(map(int, task.observations[0][0].split(','))))
    def verify(self, task, candidate):
        self.calls.append(('verify', task.prompt, candidate))
        torch.ones(3).add(1)
        accepted = self.accept_all or int(candidate) == sum(map(int, task.observations[0][0].split(',')))
        return Verification(accepted, 'recompute both terms')  # NOT external objective truth.


def setup_capture(root, *, nfit=2, ncal=4, failure=False, wrong=False, cap=1000):
    fit = [f'f{i:03d}' for i in range(nfit)]; cal = [f'c{i:03d}' for i in range(ncal)]
    pairs, boundaries = [], []
    for i, group in enumerate(fit + cal):
        task = PublicTask(f'public arithmetic case {group}', 5, ((f'{i+1},2', 4),))
        public = json.loads(json.dumps(asdict(task)))
        candidate, feedback = '0', 'recompute both terms'
        pairs.append(dict(pair_id=group, group_id=group,
                          case_sha256=case_fingerprint(task, candidate, feedback),
                          candidate_bytes=len(candidate.encode()), feedback_bytes=len(feedback.encode())))
        boundaries.append(dict(pair_id=group, task=public, candidate=candidate, feedback=feedback,
                               available_at_ns=9, initial_verifier_accepted=False, origin_receipt_sha256=_digest(['fixture-origin', group])))
    p = freeze_protocol(objective_sha256='a'*64, subject_id='episode:captured-test',
                        callback_profile_sha256='b'*64, observer_sha256='c'*64,
                        registered_at_ns=10, cutoff_ns=10**12, expires_at_ns=10**15,
                        fit_groups=fit, calibration_groups=cal, pairs=pairs, candidate_edges=[32], feedback_edges=[32],
                        alpha=.05, minimum_groups=2, max_calibration_gap=.25,
                        duration_upper_ns=2_000_000_000, formula_work_upper=100,
                        coefficients=dict(discount_rate_per_second=0., cost_per_formula_flop=0., cost_per_latency_ns=0.))
    registration = freeze_capture(p, expected_protocol_id=p['protocol_id'], boundaries=boundaries,
                                   meter_policy=policy('strict'), phase_caps=dict.fromkeys(PHASES, cap))
    create_capture(root, registration)
    callbacks = Callbacks(failure, wrong)
    # Bound method objects are retained once, matching the eventual frozen critic.
    propose, verify = callbacks.propose, callbacks.verify
    collector = PairCollector(root, expected_capture_id=registration['capture_id'],
                              callback_profile_sha256='b'*64, propose=propose, verify=verify)
    return registration, callbacks, collector, propose, verify


class PairedCaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'capture'
        self.r, self.cb, self.collector, _, _ = setup_capture(self.root)
        self.clock = Clock()

    def test_actual_one_segment_reuses_candidate_and_feedback_without_critic(self):
        seal = self.collector.run_pair('f000', clock=self.clock)
        record, _ = read_pair(self.root, self.r, 0, seal['terminal_id'])
        self.assertEqual(self.cb.calls[0][2:], ('0', 'recompute both terms'))
        self.assertEqual([x[0] for x in self.cb.calls], ['propose', 'verify'])
        self.assertEqual(record['stop_candidate'], '0')
        self.assertEqual(record['continue_candidate'], '3')
        self.assertEqual(record['execution']['work_observation']['phase_flops']['search'], 6)
        self.assertFalse(record['utility_labels_loaded'])
        self.assertGreater(record['duration_ns'], 0)

    def test_failed_provider_retained_and_slot_cannot_retry(self):
        self.cb.fail = True
        seal = self.collector.run_pair('f000', clock=self.clock)
        record, _ = read_pair(self.root, self.r, 0, seal['terminal_id'])
        self.assertEqual(record['status'], 'failed')
        self.assertIsNone(record['continue_candidate'])
        self.assertIsNone(record['execution']['work_observation']['phase_flops']['search'])
        self.assertEqual(record['execution']['work_observation']['scopes'][0]['formula_flops'], 3)
        with self.assertRaises(FileExistsError): self.collector.run_pair('f000', clock=self.clock)
        self.assertEqual(len(self.cb.calls), 1)

    def test_partial_slot_is_not_restarted(self):
        (self.root / 'pairs' / '00000').mkdir()
        with self.assertRaises(FileExistsError): self.collector.run_pair('f000', clock=self.clock)
        self.assertEqual(self.cb.calls, [])

    def test_changed_descriptor_and_outcome_fields_rejected_before_calls(self):
        for key, value in (('candidate', 'different'), ('available_at_ns', 11), ('label', 1), ('initial_verifier_accepted', True)):
            b = copy.deepcopy(self.r['boundaries']); b[0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                freeze_capture(self.r['protocol'], expected_protocol_id=self.r['protocol']['protocol_id'],
                               boundaries=b, meter_policy=self.r['meter_policy'], phase_caps=self.r['phase_caps'])
        self.assertEqual(self.cb.calls, [])

    def test_registry_and_callback_profile_mutation_reject(self):
        with self.assertRaises(ValueError):
            PairCollector(self.root, expected_capture_id=self.r['capture_id'], callback_profile_sha256='d'*64,
                          propose=self.cb.propose, verify=self.cb.verify)
        path = self.root / 'REGISTRATION.json'
        data = strict_json(path); data['phase_caps']['search'] += 1
        path.write_text(json.dumps(data))
        with self.assertRaises(ValueError): self.collector.run_pair('f000', clock=self.clock)
        self.assertEqual(self.cb.calls, [])

    def test_public_task_mutation_is_rejected_without_corrupting_registration(self):
        def mutate(task, previous, feedback):
            object.__setattr__(task, 'prompt', 'changed by callback')
            return '4'
        collector = PairCollector(self.root, expected_capture_id=self.r['capture_id'], callback_profile_sha256='b'*64,
                                  propose=mutate, verify=self.cb.verify)
        seal = collector.run_pair('f000', clock=self.clock)
        record, _ = read_pair(self.root, self.r, 0, seal['terminal_id'])
        self.assertEqual(record['status'], 'failed')
        self.assertEqual(strict_json(self.root/'REGISTRATION.json'), self.r)
        self.assertEqual(self.cb.calls, [])

    def test_no_critic_can_select_which_registered_case_runs(self):
        task = read_task(self.r['boundaries'][0]['task'])
        start = PairedStart(self.r['capture_id'], _digest(asdict(task)), '0', 'feedback', 10**12,
                            self.r['meter_policy'], self.r['phase_caps'])
        m = WorkLedger(self.r['meter_policy'], self.r['phase_caps'])
        with self.assertRaises(ValueError):
            run_reasoning(task, propose=self.cb.propose, verify=self.cb.verify, continue_values=lambda *x: None,
                          value_profile=PROFILE, max_rounds=1, max_calls=2, meter=m, paired_start=start)
        self.assertEqual(self.cb.calls, [])

    def test_wrong_budget_or_horizon_cannot_enter_capture(self):
        task = read_task(self.r['boundaries'][0]['task'])
        start = PairedStart(self.r['capture_id'], _digest(asdict(task)), '0', 'feedback', 10**12,
                            self.r['meter_policy'], self.r['phase_caps'])
        for rounds, caps in ((2, self.r['phase_caps']), (1, dict.fromkeys(PHASES, 1))):
            m = WorkLedger(self.r['meter_policy'], caps)
            with self.subTest(rounds=rounds), self.assertRaises(ValueError):
                run_reasoning(task, propose=self.cb.propose, verify=self.cb.verify, continue_values=None,
                              value_profile=PROFILE, max_rounds=rounds, max_calls=2, meter=m, paired_start=start)
        self.assertEqual(self.cb.calls, [])

    def test_budget_stop_does_not_execute_verifier(self):
        other = Path(self.tmp.name) / 'limited'
        r, cb, collector, _, _ = setup_capture(other, cap=2)
        seal = collector.run_pair('f000', clock=self.clock)
        record, _ = read_pair(other, r, 0, seal['terminal_id'])
        self.assertEqual(record['execution']['status'], 'resource_budget_stop')
        self.assertEqual(len(cb.calls), 1)
        self.assertIsNone(record['execution']['work_observation']['phase_flops']['search'])

    def test_publication_failure_does_not_leave_consumable_terminal(self):
        from matrix_runtime import write_json_exclusive as write
        def fail(path, value):
            if Path(path).name == 'pair.json': raise OSError('test disk failure')
            return write(path, value)
        with patch('matrix_runtime.write_json_exclusive', side_effect=fail):
            with self.assertRaises(OSError): self.collector.run_pair('f000', clock=self.clock)
        self.assertTrue((self.root/'pairs/00000/FAILED_CAPTURE.json').exists())
        with self.assertRaises(ValueError): read_pair(self.root, self.r, 0, 'a'*64)

    def test_temporal_expiry_and_unregistered_pair_refuse_before_callbacks(self):
        with self.assertRaises(ValueError): self.collector.run_pair('unknown', clock=self.clock)
        with self.assertRaises(ValueError): self.collector.run_pair('f000', clock=lambda: 10**12)
        self.assertEqual(self.cb.calls, [])

    def test_source_mutation_invalidates_predeclared_capture(self):
        with patch('paired_capture.source_fingerprints', return_value={'changed': 'a'*64}):
            with self.assertRaises(ValueError): validate_capture(self.r, self.r['capture_id'])


if __name__ == '__main__':
    unittest.main()
