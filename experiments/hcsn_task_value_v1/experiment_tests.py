"""Behavioral checks of event-clock controls, AV supervision and state storage.

The AV check reads TRAIN only. Controlled weights test an information path,
not benchmark accuracy or a claim that a baseline has already learned it.
"""

import unittest
from pathlib import Path

import numpy as np
import torch
from torch import nn

from .experiment import ExternalClassifier, data, tensor_batch
from .model import Classifier
from .training import evaluate


MEASUREMENTS = {}


def information_probe(name):
    """Keep one observable recurrent channel for a first-event causal probe."""
    model = ExternalClassifier(name, 2, 2, 4, 73).double()
    with torch.no_grad():
        model.frontend[0].weight.zero_()
        model.frontend[0].weight[0, 0] = 3.
        model.frontend[0].bias.copy_(torch.tensor([0., 1., -1., 0.], dtype=torch.float64))
        if isinstance(model.backbone.input_proj, nn.Linear):
            model.backbone.input_proj.weight.zero_(); model.backbone.input_proj.bias.zero_()
            model.backbone.input_proj.weight[0, 0] = 1.
        if isinstance(model.backbone.output_proj, nn.Linear):
            model.backbone.output_proj.weight.zero_(); model.backbone.output_proj.bias.zero_()
            model.backbone.output_proj.weight[0, 0] = 1.
        cell = model.backbone.blocks[0].cell
        if name == 'lif_snn':
            cell.input.weight.zero_(); cell.input.bias.zero_()
            cell.input.weight[0, 0] = 1.5
            cell.recurrent.weight.zero_(); cell.recurrent.weight[0, 0] = 1.8
        else:
            for linear in (cell.candidate, cell.retention, cell.input_gate):
                linear.weight.zero_(); linear.bias.zero_()
            cell.candidate.weight[0, 0] = 1.
            cell.retention.bias.fill_(1.); cell.input_gate.bias.fill_(1.)
        model.readout.weight.zero_(); model.readout.bias.zero_()
        model.readout.weight[0, 0] = 1.
        model.readout.weight[1, 0] = -1.
    return model


def state_tensors(value):
    if torch.is_tensor(value):
        return [value]
    if isinstance(value, dict):
        return [tensor for item in value.values() for tensor in state_tensors(item)]
    if isinstance(value, (tuple, list)):
        return [tensor for item in value for tensor in state_tensors(item)]
    return []


class ExperimentContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous_threads = torch.get_num_threads()
        torch.set_num_threads(1)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.previous_threads)

    def test_first_event_at_zero_dt_reaches_last_output_and_gradient(self):
        rows = []
        for name in ('two_gates', 'lif_snn'):
            with self.subTest(name=name):
                model = information_probe(name)
                source = torch.zeros(1, 8, 2, dtype=torch.float64)
                source[0, 0, 0] = 1.
                source.requires_grad_(True)
                erased = torch.zeros_like(source)
                dt = torch.full((1, 8), .1, dtype=torch.float64)
                dt[:, 0] = 0.
                answer = model(source, dt)
                neutral = model(erased, dt)
                influence = float((answer[0, -1]-neutral[0, -1]).detach().abs().max())
                answer[0, -1, 0].backward()
                gradient = float(source.grad[0, 0].abs().max())
                self.assertGreater(influence, 1e-4)
                self.assertGreater(gradient, 1e-10)
                self.assertEqual(float(dt[0, 0]), 0.)
                rows.append({'architecture': name, 'first_dt': 0.,
                             'last_output_difference': influence,
                             'first_payload_gradient': gradient})
        MEASUREMENTS['zero_dt_information_path'] = rows

    def test_unobserved_payload_does_not_change_event_baseline_state(self):
        rows = []
        generator = torch.Generator().manual_seed(1810)
        x = torch.randn(2, 8, 2, generator=generator, dtype=torch.float64)
        observed = torch.tensor([[1, 0, 1, 0, 0, 1, 0, 1],
                                 [0, 1, 0, 0, 1, 0, 1, 0]], dtype=torch.bool)
        changed = x.clone(); changed[~observed] = 1000.
        dt = torch.full((2, 8), .1, dtype=torch.float64); dt[:, 0] = 0.
        for name in ('two_gates', 'lif_snn'):
            model = ExternalClassifier(name, 2, 2, 4, 74).double()
            with torch.no_grad():
                original, a = model(x, dt, observed, return_aux=True)
                altered, b = model(changed, dt, observed, return_aux=True)
            torch.testing.assert_close(original, altered, atol=0., rtol=0.)
            for first, second in zip(state_tensors(a['state']), state_tensors(b['state']), strict=True):
                torch.testing.assert_close(first, second, atol=0., rtol=0.)
            rows.append({'architecture': name, 'logits_and_state_bitwise_equal': True})
        MEASUREMENTS['missing_event_payload'] = rows

    def test_last_missing_av_acquisition_keeps_its_target_and_identity(self):
        root = Path(__file__).parent/'results/async_frontend001/data'
        witnesses = []

        class ConstantOutput(nn.Module):
            def forward(self, x, dt, observed):
                return torch.zeros(*x.shape[:2], 6)

        for modality in (0, 1):
            values = data('async_av', 'train', av_directory=root, missing_modality=modality)
            self.assertTrue(np.all(values['observed'] <= values['valid']))
            candidates = [i for i, length in enumerate(values['lengths'])
                          if not values['observed'][i, length-1]]
            for index in candidates[:1]:
                length = int(values['lengths'][index])
                item = tensor_batch(values, np.array([index]))
                self.assertEqual(item['x'].shape[1], length)
                self.assertFalse(bool(item['observed'][0, -1]))
                self.assertNotEqual(int(item['y'][0, -1]), -100)
                selected = {key: array[[index]] for key, array in values.items()}
                metrics, prediction = evaluate(ConstantOutput(), selected, batch_size=1)
                self.assertEqual(metrics['supervised_tokens'], 1)
                np.testing.assert_array_equal(prediction['token_index'], [length-1])
                np.testing.assert_array_equal(prediction['clip_ids'], selected['clip_ids'])
                self.assertEqual(str(prediction['actors'][0]), str(selected['clip_ids'][0]).split('_')[0])
                witnesses.append({'missing_modality': modality, 'clip_id': str(selected['clip_ids'][0]),
                                  'valid_length': length, 'supervised_token_index': length-1,
                                  'last_payload_observed': False})
        self.assertTrue(witnesses, 'TRAIN subset must contain a last-acquisition missing witness')
        MEASUREMENTS['av_last_valid_supervision'] = {'split': 'train', 'witnesses': witnesses}

    def test_no_grad_persistent_storage_is_independent_of_sequence_length(self):
        model = Classifier(input_dim=5, output_dim=3, width=8, physical=1, seed=75).double()
        generator = torch.Generator().manual_seed(1811)
        rows = []
        for length in (8, 32):
            x = torch.randn(2, length, 5, generator=generator, dtype=torch.float64)
            dt = torch.full((2, length), .1, dtype=torch.float64); dt[:, 0] = 0.
            with torch.no_grad():
                _, auxiliary = model(x, dt, return_aux=True)
            tensors = state_tensors(auxiliary['state'])
            self.assertTrue(all(t.grad_fn is None for t in tensors))
            storages = {t.untyped_storage().data_ptr(): t.untyped_storage().nbytes() for t in tensors}
            for tensor in tensors:
                self.assertEqual(tensor.untyped_storage().nbytes(), tensor.numel()*tensor.element_size())
            rows.append({'length': length, 'batch': 2,
                         'numeric_bytes': sum(t.numel()*t.element_size() for t in tensors),
                         'unique_backing_storage_bytes': sum(storages.values())})
        self.assertEqual(rows[0]['unique_backing_storage_bytes'], rows[1]['unique_backing_storage_bytes'])
        MEASUREMENTS['persistent_state'] = rows


if __name__ == '__main__':
    import argparse
    import hashlib
    import io
    import json
    import sys
    import time

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    arguments = parser.parse_args()
    arguments.output.mkdir(parents=True, exist_ok=True)
    stream = io.StringIO(); started = time.perf_counter()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ExperimentContractTests))
    parent = Path(__file__).parent
    receipt = {'passed': result.wasSuccessful(), 'tests_run': result.testsRun,
               'failure_count': len(result.failures), 'error_count': len(result.errors),
               'wall_seconds': time.perf_counter()-started, 'python': sys.version,
               'torch': torch.__version__, 'numpy': np.__version__, 'heldout_data_accessed': False,
               'measurements': MEASUREMENTS,
               'source_sha256': {name: hashlib.sha256((parent/name).read_bytes()).hexdigest()
                                 for name in ('experiment.py', 'model.py', 'training.py', 'experiment_tests.py')}}
    (arguments.output/'experiment_audit.log').write_text(stream.getvalue())
    (arguments.output/'experiment_audit.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(stream.getvalue()); print(json.dumps(receipt, indent=2))
    raise SystemExit(0 if result.wasSuccessful() else 1)
