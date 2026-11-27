"""Synthetic behavioral checks only; never opens any actual trained checkpoint."""

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
import torch

from audit_io import (checkpoint_metadata, construction, read_dev, sha,
                      strict_best, validate_terminal, verify_files)
from independent_metrics import compare_metrics, metrics
from replay_fit import fresh_forward
from run_controller import classify, run_one


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return sha(path)


def report_fixture():
    plan = dict(arm='hcsn', width=16, seed=101, s4_repo=None, hcsn_grid_json={},
                train_shared=False, cache_frozen_tables=True, learn_core_adapter=True,
                batch_size=32, learning_rate=.001, manifest_sha256='data')
    report = dict(status='budget_exhausted', training_adequacy_established=False, confirmation_access=False,
                  source_unchanged=True, source_before={}, source_after={}, common_weights_unchanged=True,
                  arm='hcsn', seed=101, model_configuration=construction(plan), dtype='float64', device='cpu',
                  best_epoch=2, episodes_train=356, main_updates=40,
                  epochs=[dict(epoch=i, complete=True, development=dict(macro_f1_11_classes=score))
                          for i, score in enumerate((.1, .3, .3), 1)])
    outer = dict(name='hcsn-s101-lr0.001', status='failed', returncode=2,
                 fit_status='budget_exhausted', adequate=False)
    return report, outer, plan


class SelectionTests(unittest.TestCase):
    def test_first_strict_maximum_tie(self):
        report, _, _ = report_fixture()
        self.assertEqual(strict_best(report)['epoch'], 2)
        report['best_epoch'] = 3
        with self.assertRaises(ValueError):
            strict_best(report)

    def test_censored_report_needs_no_selected_logits(self):
        report, outer, plan = report_fixture()
        self.assertEqual(validate_terminal(report, outer, plan, outer['name'])['epoch'], 2)
        self.assertNotIn('selected_development', report)

    def test_hard_kill_and_false_adequacy_rejected(self):
        report, outer, plan = report_fixture()
        outer['returncode'] = -9
        with self.assertRaises(ValueError):
            validate_terminal(report, outer, plan, outer['name'])
        outer['returncode'] = 2
        report['training_adequacy_established'] = True
        with self.assertRaises(ValueError):
            validate_terminal(report, outer, plan, outer['name'])

    def test_last_checkpoint_substitution_rejected(self):
        report, _, plan = report_fixture()
        best = strict_best(report)
        checkpoint = dict(epochs_completed=2, main_updates=24, data_manifest_sha256='data',
                          model_configuration=construction(plan))
        checkpoint_metadata(checkpoint, report, plan, best)
        checkpoint.update(epochs_completed=3, main_updates=36)
        with self.assertRaises(ValueError):
            checkpoint_metadata(checkpoint, report, plan, best)

    def test_source_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'source.py'
            p.write_text('original')
            expected = {str(p): sha(p)}
            verify_files(expected)
            p.write_text('altered')
            with self.assertRaises(ValueError):
                verify_files(expected)


class MetricTests(unittest.TestCase):
    def test_uniform_logits_known_metrics(self):
        actual = metrics(np.zeros((11, 11)), np.arange(11))
        self.assertAlmostEqual(actual['accuracy'], 1 / 11)
        self.assertAlmostEqual(actual['macro_f1_11_classes'], 1 / 66)
        self.assertAlmostEqual(actual['nll'], math.log(11))
        self.assertAlmostEqual(actual['brier_half_sum'], 5 / 11)
        self.assertAlmostEqual(actual['brier_mean_classes'], 10 / 121)
        self.assertAlmostEqual(actual['ece_15_equal_width_bins'], 0)
        self.assertEqual(actual['confusion_matrix'], [[1] + [0] * 10 for _ in range(11)])

    def test_perfect_confident_boundary_bin_and_missing_classes(self):
        value = np.full((3, 11), -1000.)
        value[np.arange(3), [2, 2, 5]] = 0
        actual = metrics(value, np.array([2, 2, 5]))
        self.assertEqual(actual['accuracy'], 1)
        self.assertEqual(actual['macro_f1_present_classes'], 1)
        self.assertAlmostEqual(actual['macro_f1_11_classes'], 2 / 11)
        self.assertEqual(actual['ece_15_equal_width_bins'], 0)
        self.assertEqual(actual['nll'], 0)

    def test_changed_confusion_or_nll_is_rejected(self):
        a = metrics(np.zeros((11, 11)), np.arange(11))
        b = copy.deepcopy(a)
        b['confusion_matrix'][0][0] += 1
        with self.assertRaises(ValueError):
            compare_metrics(a, b, 2e-12)
        b = copy.deepcopy(a)
        b['nll'] += 1e-8
        with self.assertRaises(ValueError):
            compare_metrics(a, b, 2e-12)
        self.assertEqual(max(compare_metrics(a, a, 2e-12).values()), 0)

    def test_nonfinite_and_out_of_range_rejected(self):
        with self.assertRaises(ValueError):
            metrics(np.full((1, 11), np.nan), np.array([0]))
        with self.assertRaises(ValueError):
            metrics(np.zeros((1, 11)), np.array([11]))


class DataTests(unittest.TestCase):
    def fixture(self, root):
        feature = [0.] * 25
        feature[12] = 1.
        row = dict(id='D01-0', sequence='D01', start=0, partition='dev', source_rows=[20, 21],
                   delta_ticks=[0, 1000000], dt=[0, .1], x=[feature, feature], y=[0, 1])
        entry = dict(id=row['id'], partition='dev', path='episodes/D01-0.json', events=2,
                     sha256=write_json(root / 'episodes/D01-0.json', row))
        # Deliberately absent training file demonstrates this reader never opens ABC episodes.
        train = dict(id='A01-0', partition='train', path='episodes/ABSENT.json', events=1, sha256='unused')
        selected = [{key: row[key] for key in ('id', 'sequence', 'start', 'partition', 'source_rows', 'delta_ticks')},
                    dict(id='A01-0')]
        manifest = dict(mode='all-development', confirmation_access=False, episodes=[train, entry],
                        selection_sha256=write_json(root / 'selection.json', selected),
                        frontend_sha256=write_json(root / 'frontend.json', dict(test_used=False, fit_subjects=list('ABC'))))
        plan = dict(prepared=str(root), data_manifest_sha256=write_json(root / 'data-manifest.json', manifest),
                    dev_entries=[entry], expected_dev_episodes=1, expected_dev_events=2)
        return plan, row

    def test_D_only_exact_order_and_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            plan, row = self.fixture(Path(temp))
            inputs = {}
            self.assertEqual(read_dev(plan, inputs), [row])
            self.assertFalse(any('ABSENT' in path for path in inputs))
            row['y'].reverse()
            write_json(Path(temp) / 'episodes/D01-0.json', row)
            with self.assertRaises(ValueError):
                read_dev(plan, {})

    def test_wrong_declared_D_order_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            plan, _ = self.fixture(Path(temp))
            plan['dev_entries'][0]['id'] = 'D02-0'
            with self.assertRaises(ValueError):
                read_dev(plan, {})


class ForwardAndProcessTests(unittest.TestCase):
    def test_padded_no_grad_order_and_unchanged_tensors(self):
        model = torch.nn.Linear(25, 11, dtype=torch.float64)
        class Wrapper(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.linear = model
            def forward(self, x, dt):
                return self.linear(x)
        rows = [dict(id='D0', y=[1, 2]), dict(id='D1', y=[3])]
        def batches(rows, order, size):
            yield ['D0', 'D1'], torch.zeros(2, 2, 25, dtype=torch.float64), torch.zeros(2, 2), torch.tensor([[1, 2], [3, -1]])
        values, labels, _ = fresh_forward(Wrapper(), rows, 32, batches, lambda: None, lambda row: None)
        self.assertEqual(tuple(values.shape), (3, 11))
        self.assertEqual(labels.tolist(), [1, 2, 3])
        self.assertFalse(values.requires_grad)
        self.assertTrue(all(p.grad is None for p in model.parameters()))

    def test_forward_buffer_mutation_is_rejected(self):
        class Mutating(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.register_buffer('counter', torch.tensor(0.))
            def forward(self, x, dt):
                self.counter.add_(1)
                return torch.zeros(1, 1, 11, dtype=torch.float64)
        def batches(*args):
            yield ['D0'], torch.zeros(1, 1, 25), torch.zeros(1, 1), torch.tensor([[0]])
        with self.assertRaises(ValueError):
            fresh_forward(Mutating(), [dict(id='D0', y=[0])], 32, batches, lambda: None, lambda row: None)

    def test_missing_executable_keeps_failure_cost(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'launch'
            row = run_one(['/nonexistent/hcsn-replay-test'], out, 1., 2147483648, os.environ)
            self.assertFalse(row['process_started'])
            self.assertEqual(row['status'], 'launch_or_monitor_failed')
            self.assertTrue((out / 'outer.json').is_file())
            self.assertGreaterEqual(row['whole_child_wall_seconds'], 0)

    def test_rc0_without_artifact_is_HOLD(self):
        with tempfile.TemporaryDirectory() as temp:
            row = run_one([sys.executable, '-c', 'pass'], Path(temp) / 'launch', 5., 2147483648, os.environ)
            self.assertEqual(row['status'], 'completed')
            self.assertEqual(classify(row, None)[0], 'HOLD')

    def test_real_subprocess_timeout_is_retained(self):
        with tempfile.TemporaryDirectory() as temp:
            row = run_one([sys.executable, '-c', 'import time;time.sleep(2)'], Path(temp) / 'launch', .06, 2147483648, os.environ)
            self.assertEqual(row['status'], 'wall_capped')
            self.assertLess(row['returncode'], 0)
            self.assertEqual(classify(row, {})[0], 'HOLD')


if __name__ == '__main__':
    unittest.main()
