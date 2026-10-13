"""Observed execution-count and information-boundary regressions."""

from copy import deepcopy
from dataclasses import replace
import unittest

import torch

from development_ablation import RecurrentClassifier
from development_stopping import (ContinuationCritic, collect_training_trace, fit_continuation,
                                  run_stopping)
from development_tensors import parameter_digest


class StoppingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.threads = torch.get_num_threads()
        torch.set_num_threads(1)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.threads)

    def setUp(self):
        self.rng = torch.random.fork_rng(devices=[])
        self.rng.__enter__()
        torch.manual_seed(731)
        self.model = RecurrentClassifier(8, 2, depth=4)
        self.tokens = torch.randn(8, 3, 8)

    def tearDown(self):
        self.rng.__exit__(None, None, None)

    def critic(self, value):
        weights = torch.zeros(3, 11, dtype=torch.float64)
        weights[:, -1] = value
        return ContinuationCritic(weights, parameter_digest(self.model), .02)

    def test_immediate_stop_executes_one_actual_transition_per_row(self):
        batches = []
        handle = self.model.recurrence.cell.register_forward_hook(lambda _m, a, _r: batches.append(len(a[0])))
        try:
            out = run_stopping(self.model, self.tokens, horizon=4, mode='learned', critic=self.critic(-1))
        finally:
            handle.remove()
        self.assertEqual(batches, [8])
        self.assertEqual(out['cell_transitions'], 8)
        self.assertEqual(out['depths'].tolist(), [1]*8)
        self.assertTrue(torch.allclose(out['logits'], self.model(self.tokens, depth=1), atol=1e-6))

    def test_continue_reuses_prefix_and_matches_full_horizon(self):
        out = run_stopping(self.model, self.tokens, horizon=4, mode='learned', critic=self.critic(1))
        self.assertEqual(out['cell_transitions'], 32)
        self.assertEqual(out['critic_rows'], 24)
        self.assertTrue(torch.allclose(out['logits'], self.model(self.tokens), atol=1e-6))

    def test_mixed_early_exits_never_reenter_later_batch(self):
        trace = collect_training_trace(self.model, self.tokens, horizon=4)
        critic = self.critic(1)
        critic.weights[0].zero_()
        critic.weights[0, 0] = 1
        critic.weights[0, -1] = -trace.states[:, 0, 0].double().median()
        out = run_stopping(self.model, self.tokens, horizon=4, mode='learned', critic=critic)
        self.assertTrue(8 < out['cell_transitions'] < 32)
        for earlier, later in zip(out['executed_rows_by_depth'], out['executed_rows_by_depth'][1:]):
            self.assertTrue(set(later) <= set(earlier))
        for i, depth in enumerate(out['depths'].tolist()):
            self.assertTrue(torch.allclose(out['logits'][i], trace.logits[i, depth-1], atol=1e-6))

    def test_stale_model_refused_before_recurrent_execution(self):
        critic = self.critic(1)
        with torch.no_grad():
            self.model.output.bias.add_(1)
        observed = []
        handle = self.model.recurrence.cell.register_forward_hook(lambda *_: observed.append(True))
        try:
            with self.assertRaises(ValueError):
                run_stopping(self.model, self.tokens, horizon=4, mode='learned', critic=critic)
        finally:
            handle.remove()
        self.assertEqual(observed, [])

    def test_stopping_depends_only_on_current_features(self):
        critic = self.critic(0)
        critic.weights[:, 0] = 1
        trace = collect_training_trace(self.model, self.tokens, horizon=4)
        altered = deepcopy(trace)
        altered.states[:, 1:] += 100
        altered.logits[:, 1:] *= -1
        self.assertTrue(torch.equal(critic(trace.states[:, 0], trace.logits[:, 0], depth=1),
                                    critic(altered.states[:, 0], altered.logits[:, 0], depth=1)))

    def test_real_fit_backward_targets_and_input_parameter_immutability(self):
        trace = collect_training_trace(self.model, self.tokens, horizon=4)
        before = parameter_digest(self.model)
        states, logits = trace.states.clone(), trace.logits.clone()
        labels = (self.tokens[:, :, 0].sum(1) > 0).long()
        critic, report = fit_continuation(trace, labels, unit_cost=.02)
        self.assertEqual(report['fits'], 3)
        self.assertEqual(report['training_examples'], 8)
        self.assertEqual(before, parameter_digest(self.model))
        self.assertTrue(torch.equal(states, trace.states))
        self.assertTrue(torch.equal(logits, trace.logits))
        self.assertTrue(torch.isfinite(critic.weights).all())
        self.assertIsNone(self.model.output.weight.grad)

    def test_cost_can_change_fitted_continuation(self):
        trace = collect_training_trace(self.model, self.tokens, horizon=4)
        labels = trace.logits[:, -1].argmax(-1)
        cheap, _ = fit_continuation(trace, labels, unit_cost=0)
        expensive, _ = fit_continuation(trace, labels, unit_cost=1)
        self.assertNotEqual(cheap.identity(), expensive.identity())
        out = run_stopping(self.model, self.tokens, horizon=4, mode='learned', critic=expensive)
        self.assertEqual(out['depths'].tolist(), [1]*8)

    def test_invalid_envelopes_and_labels(self):
        for horizon in (True, 0, 33):
            with self.assertRaises(ValueError):
                run_stopping(self.model, self.tokens, horizon=horizon, mode='fixed')
        for threshold in (True, float('nan'), 2):
            with self.assertRaises(ValueError):
                run_stopping(self.model, self.tokens, horizon=4, mode='confidence', threshold=threshold)
        trace = collect_training_trace(self.model, self.tokens, horizon=4)
        with self.assertRaises(ValueError):
            fit_continuation(trace, torch.full((8,), 2, dtype=torch.long), unit_cost=.1)
        with self.assertRaises(ValueError):
            fit_continuation(replace(trace, logits=trace.logits[:, :2]), torch.zeros(8, dtype=torch.long), unit_cost=.1)

    def test_confidence_endpoints_and_fixed_equal_cost(self):
        early = run_stopping(self.model, self.tokens, horizon=4, mode='confidence', threshold=.5)
        full = run_stopping(self.model, self.tokens, horizon=4, mode='confidence', threshold=1)
        fixed = run_stopping(self.model, self.tokens, horizon=4, mode='fixed')
        self.assertEqual(early['depths'].tolist(), [1]*8)
        self.assertEqual(full['cell_transitions'], fixed['cell_transitions'])
        self.assertTrue(torch.equal(full['logits'], fixed['logits']))


if __name__ == '__main__':
    unittest.main()
