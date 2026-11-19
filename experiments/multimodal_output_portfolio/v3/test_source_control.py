"""Small hand-specified fixtures: information flow, joint CE and real MACs.

No trained confirmation checkpoint or registered evaluation worlds are used.
All four fixture modalities use the 40-dimensional synthetic text format.
"""

import inspect
import math
import unittest
from unittest.mock import patch

import numpy as np
import torch

from control import portfolio_grid
from model import MODALITIES, OutputModel, encode
from source_control import (PaidWitness, compile_source_policy, observed_reports,
                            report_indices, source_inputs, source_rollout)
from world import render


class LinearMeter:
    def __init__(self, model):
        self.total, self.examples, self.handles = 0, {}, []
        for name, module in model.named_modules():
            if isinstance(module, torch.nn.Linear):
                def record(layer, inputs, output, name=name):
                    batch = inputs[0].numel() // layer.in_features
                    self.total += batch * layer.in_features * layer.out_features
                    self.examples[name] = self.examples.get(name, 0) + batch
                self.handles.append(module.register_forward_hook(record))

    def __enter__(self):
        return self

    def __exit__(self, *_):
        for handle in self.handles:
            handle.remove()


def fixture_worlds(count, seed, namespace, scenario):
    truth = np.arange(count, dtype=np.int64) % 8
    reports = np.repeat(truth[:, None], 4, axis=1)
    if scenario == 'correlation_shift':
        reports[:, [0, 1, 3]] = (truth[:, None] + 1) % 8
    elif scenario == 'all_shared_wrong':
        reports[:] = (truth[:, None] + 1) % 8
    else:
        reports[::5, 3] = -1
    raw = {name: render(reports[:, column], seed + column)['text']
           for column, name in enumerate(MODALITIES)}
    return {'truth': truth, 'raw': raw, 'ids': np.arange(count), 'scenario': scenario}


class SourceControlTests(unittest.TestCase):
    def setUp(self):
        self.targets = {name: render(np.arange(8), 0, nuisance=False)['text'] for name in MODALITIES}
        self.model = OutputModel({name: 40 for name in MODALITIES})
        with torch.no_grad():
            for parameter in self.model.parameters():
                parameter.zero_()
            for name in MODALITIES:
                first, last = self.model.encoders[name][0], self.model.encoders[name][2]
                for concept in range(8):
                    first.weight[concept, concept // 2] = 2
                    first.weight[concept, 24 + concept % 2] = 2
                    first.bias[concept] = -3
                    last.weight[concept, concept] = 1
                self.model.decoders[name][0].weight[:8, :8] = torch.eye(8)
                scale = torch.nn.functional.gelu(torch.tensor(1.)).item()
                self.model.decoders[name][2].weight[:, :8] = torch.tensor(self.targets[name].T / scale)
            self.model.initial_latent.weight[:8] = torch.eye(8)
        self.model.eval().requires_grad_(False)
        self.settings = {'scenarios': ['iid', 'correlation_shift', 'all_shared_wrong'],
                         'calibration_worlds_per_regime': 16, 'validation_worlds': 16,
                         'independent_verifier_error': .02, 'verifier_proxy_cost': 5,
                         'verifier_utility_penalty': .025}

    def compile(self):
        with patch('source_control.sample_worlds', side_effect=fixture_worlds):
            return compile_source_policy(self.model, self.targets, 3, self.settings, 'unit-fixture-only')

    def assert_joint_query_value(self, policy, history):
        index = int(report_indices(np.asarray([history]))[0])
        channel = np.asarray(policy['receipt']['effective_witness_channel'])
        values = []
        for joint in policy['joint']:
            mass = joint[(slice(None),) + tuple(history)]
            posterior = mass / math.fsum(mass)
            exponential = math.fsum(float(posterior[truth]) * float(channel[truth, witness])
                                   * math.exp(2 * float(policy['losses'][policy['vertices'][witness], truth]))
                                   for truth in range(8) for witness in range(8))
            values.append(-math.log(exponential) / 2)
        cost = self.settings['verifier_proxy_cost'] * self.settings['verifier_utility_penalty']
        self.assertAlmostEqual(policy['query_values'][index], min(values) - cost, places=12)

    def test_compilation_joint_axes_query_expectation_and_actual_offline_macs(self):
        with LinearMeter(self.model) as meter:
            policy = self.compile()
        self.assertEqual(policy['receipt']['offline_forward_linear_macs'], meter.total)
        self.assertEqual(policy['joint'].shape, (3, 8, 9, 9, 9, 9))
        self.assertEqual(policy['losses'].shape, (331, 8))
        np.testing.assert_array_equal(policy['receipt']['witness_encoder_channel'], np.eye(8))
        for history in ((0, 0, 0, 0), (1, 1, 0, 1), (1, 1, 1, 1), (8, 8, 8, 8)):
            index = int(report_indices(np.asarray([history]))[0])
            laws = []
            for joint in policy['joint']:
                mass = joint[(slice(None),) + tuple(history)]
                laws.append(mass / math.fsum(mass))
            direct = [[-math.log(math.fsum(float(p) * math.exp(2 * float(loss))
                                          for p, loss in zip(law, losses))) / 2
                       for losses in policy['losses']] for law in laws]
            worst = np.min(direct, axis=0)
            self.assertAlmostEqual(worst[policy['robust'][index]], max(worst), places=12)
            self.assertAlmostEqual(direct[0][policy['nominal'][index]], max(direct[0]), places=12)
            self.assertAlmostEqual(policy['stop_values'][index], max(worst), places=12)
            self.assert_joint_query_value(policy, history)
            self.assertEqual(bool(policy['query'][index]),
                             bool(policy['query_values'][index] > max(worst) + 1e-12))

    def test_witness_channel_includes_actual_encoder_mistakes(self):
        with torch.no_grad():
            last = self.model.encoders['text'][2]
            last.weight.zero_()
            for concept in range(8):
                last.weight[(concept + 1) % 8, concept] = 1
        policy = self.compile()
        permutation = np.roll(np.eye(8), 1, axis=1)
        np.testing.assert_array_equal(policy['receipt']['witness_encoder_channel'], permutation)
        semantic = np.full((8, 8), .02 / 7)
        np.fill_diagonal(semantic, .98)
        np.testing.assert_allclose(policy['receipt']['effective_witness_channel'], semantic @ permutation,
                                   rtol=0, atol=1e-15)
        self.assert_joint_query_value(policy, (1, 0, 0, 0))

    def test_online_work_queries_and_all_outputs_match_actual_linear_calls(self):
        grid = portfolio_grid()
        vertices = np.array([np.flatnonzero(np.all(grid == row, axis=1))[0] for row in np.eye(8)])
        raw = {name: render(np.arange(4), 20)['text'] for name in MODALITIES}
        raw['image'][1] = 0
        histories, _ = observed_reports(self.model, raw)
        indices = report_indices(histories)
        query = np.zeros(9 ** 4, dtype=bool)
        query[indices[[0, 2]]] = True
        policy = {'grid': grid, 'vertices': vertices, 'query': query,
                  'nominal': np.full(9 ** 4, vertices[0]), 'robust': np.full(9 ** 4, vertices[1])}
        raw_witness = render(np.array([7, 6, 5, 4]), 30)['text']
        for arm in ('nominal', 'robust', 'robust_verified', 'verifier_only'):
            witness = PaidWitness(raw_witness)
            with LinearMeter(self.model) as meter:
                outputs, portfolios, chosen, receipt = source_rollout(self.model, raw, witness, policy, arm)
            self.assertEqual(receipt['forward_linear_macs'], meter.total)
            self.assertEqual(set(outputs), set(MODALITIES))
            self.assertTrue(receipt['all_four_outputs'])
            self.assertEqual(meter.examples['initial_latent'], 4)
            self.assertFalse(any(name.startswith('refinement') for name in meter.examples))
            np.testing.assert_array_equal(chosen, witness.queried)
            self.assertEqual(int(chosen.sum()), 4 if arm == 'verifier_only' else 2 if arm == 'robust_verified' else 0)
            self.assertEqual(meter.examples.get('encoders.text.0', 0), 4 + (2 if arm == 'robust_verified' else 0))
            if arm == 'verifier_only':
                self.assertFalse(any(name.startswith(('encoders.audio', 'encoders.image', 'encoders.video'))
                                     for name in meter.examples))
            if chosen.any():
                np.testing.assert_array_equal(portfolios[chosen], vertices[np.array([7, 6, 5, 4])[chosen]])

    def test_paid_witness_copy_nonrepeat_and_model_api_has_no_truth_argument(self):
        original = render(np.array([2, 3]), 99)['text']
        expected = original.copy()
        witness = PaidWitness(original)
        original[:] = 0
        selected = np.array([True, False])
        np.testing.assert_array_equal(witness.query(selected), expected[:1])
        with self.assertRaises(ValueError):
            witness.query(selected)
        with self.assertRaises(ValueError):
            witness.query(np.array([1, 0]))
        parameters = tuple(inspect.signature(source_rollout).parameters)
        self.assertEqual(parameters, ('model', 'raw', 'witness', 'policy', 'arm'))

    def test_rollout_does_not_read_metadata_or_call_world_renderer(self):
        class PublicOnly(dict):
            def __getitem__(self, key):
                if key not in MODALITIES:
                    raise AssertionError('controller attempted to read evaluator metadata')
                return super().__getitem__(key)

        raw = PublicOnly({name: render(np.array([2, 3]), 4)['text'] for name in MODALITIES})
        raw.update(truth=np.array([7, 0]), scenario='forbidden', ids=np.array([8, 9]))
        grid = portfolio_grid()
        policy = {'grid': grid, 'nominal': np.zeros(9 ** 4, dtype=np.int64)}
        witness = PaidWitness(np.zeros((2, 40), dtype=np.float32))
        with patch('source_control.render', side_effect=AssertionError('inference rendered labels')), \
                patch('source_control.sample_worlds', side_effect=AssertionError('inference queried a world')):
            first = source_rollout(self.model, raw, witness, policy, 'nominal')
            raw.update(truth=np.array([1, 6]), scenario='different', ids=np.array([3, 2]))
            second = source_rollout(self.model, raw, witness, policy, 'nominal')
        np.testing.assert_array_equal(first[1], second[1])
        for name in MODALITIES:
            np.testing.assert_array_equal(first[0][name], second[0][name])
        self.assertFalse(witness.queried.any())

    def test_witness_is_new_information_and_error_channel_is_evaluator_only(self):
        with patch('source_control.sample_worlds', side_effect=fixture_worlds):
            clean_world, clean = source_inputs(16, 19, 'unit-only', 'all_shared_wrong', 0)
            wrong_world, wrong = source_inputs(16, 19, 'unit-only', 'all_shared_wrong', 1)
        np.testing.assert_array_equal(encode(self.model, 'text', clean)[0], clean_world['truth'])
        self.assertTrue(np.all(encode(self.model, 'text', wrong)[0] != wrong_world['truth']))
        for name in MODALITIES:
            np.testing.assert_array_equal(clean_world['raw'][name], wrong_world['raw'][name])
        reports, _ = observed_reports(self.model, clean_world['raw'])
        self.assertTrue(np.all(reports != clean_world['truth'][:, None]))


if __name__ == '__main__':
    unittest.main()
