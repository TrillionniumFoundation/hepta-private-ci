"""Physical training-budget execution, not a learned allocator or live Cell owner."""
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import torch
from torch import nn

from development_ablation import fit_candidate
from development_head_training import SwiGLUCellHead, fit_gated_cells, fit_linear_cells
from development_learning import run_local, run_shared_learning
from development_learning_checks import TensorBackend, census
from development_tensors import parameter_digest
from shared_encoder_batch import FrozenFeature, SharedStemEngine


class TrainingPlanTests(unittest.TestCase):
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
        self.addCleanup(self.rng.__exit__, None, None, None)
        torch.manual_seed(818)
        self.x = torch.randn(8, 4, requires_grad=True)
        self.heads = tuple(SwiGLUCellHead(4, 3, 2) for _ in range(4))
        self.rows = tuple(torch.arange(n) for n in (1, 8, 4, 2))
        self.gold = tuple((self.x[r, 0] > 0).long() for r in self.rows)
        self.seeds = (31, 32, 33, 34)
        self.limits = (0, 1, 3, 4)

    def fit(self, **kwargs):
        options = dict(steps=4, group_size=4, step_counts=self.limits)
        options.update(kwargs)
        return fit_gated_cells(self.heads, self.x, self.rows, self.gold, seeds=self.seeds, **options)

    def compare(self, a, b):
        for key, value in a.state_dict().items():
            torch.testing.assert_close(value, b.state_dict()[key], atol=2e-6, rtol=2e-5)

    def test_gated_results_match_independent_original_fitter(self):
        trained, receipt = self.fit()
        for i, limit in enumerate(self.limits):
            expected = self.heads[i] if limit == 0 else fit_candidate(
                self.heads[i], self.x[self.rows[i]], self.gold[i], steps=limit, seed=self.seeds[i])[0]
            self.compare(trained[i], expected)
        self.assertEqual([c['steps'] for c in receipt['cells']], list(self.limits))
        self.assertEqual(receipt['groups'][0]['useful_example_updates'], 28)
        self.assertEqual(receipt['groups'][0]['active_cell_steps'], 8)

    def test_actual_matrix_batches_shrink_and_ignore_zero_step_cell(self):
        bmm = torch.bmm
        calls = []
        def observe(a, b):
            calls.append(tuple(a.shape[:2]))
            return bmm(a, b)
        with patch('development_head_training.torch.bmm', side_effect=observe):
            _, receipt = self.fit()
        self.assertEqual(calls, [(3, 8)] * 3 + [(2, 4)] * 6 + [(1, 2)] * 3)
        self.assertEqual(receipt['groups'][0]['physical_example_lanes'], 42)
        self.assertEqual([s['cell_indices'] for s in receipt['groups'][0]['segments']],
                         [[1, 2, 3], [2, 3], [3]])

    def test_all_zero_budget_never_constructs_optimizer_or_runs_matrix(self):
        with patch('development_head_training.torch.optim.SGD') as optimizer, \
                patch('development_head_training.torch.bmm') as matrix:
            trained, receipt = self.fit(step_counts=(0, 0, 0, 0))
            optimizer.assert_not_called()
            matrix.assert_not_called()
        self.assertEqual(receipt['groups'][0]['optimizer_steps'], 0)
        self.assertEqual(receipt['groups'][0]['physical_example_lanes'], 0)
        for a, b, row in zip(trained, self.heads, receipt['cells']):
            self.assertEqual(parameter_digest(a), parameter_digest(b))
            self.assertIsNot(a, b)
            self.assertIsNone(row['last_training_loss'])

    def test_linear_schedule_uses_same_independent_updates(self):
        heads = tuple(nn.Linear(4, 2) for _ in self.heads)
        trained, _ = fit_linear_cells(heads, self.x, self.rows, self.gold, seeds=self.seeds,
                                      steps=4, step_counts=self.limits)
        for i, n in enumerate(self.limits):
            ref = heads[i] if n == 0 else fit_candidate(heads[i], self.x[self.rows[i]], self.gold[i],
                                                       steps=n, seed=self.seeds[i])[0]
            self.compare(trained[i], ref)

    def test_default_and_explicit_uniform_budget_match(self):
        implicit, _ = self.fit(step_counts=None)
        explicit, _ = self.fit(step_counts=(4,) * 4)
        self.assertEqual(tuple(map(parameter_digest, implicit)), tuple(map(parameter_digest, explicit)))

    def test_partition_order_does_not_reassign_random_streams(self):
        expected, first = self.fit()
        for size in (1, 2, 3):
            actual, receipt = self.fit(group_size=size)
            for a, b in zip(expected, actual):
                self.compare(a, b)
            self.assertEqual([c['minibatch_sha256'] for c in first['cells']],
                             [c['minibatch_sha256'] for c in receipt['cells']])

    def test_input_and_original_parameters_stay_unchanged(self):
        before = tuple(map(parameter_digest, self.heads))
        x = self.x.detach().clone()
        self.fit()
        self.assertEqual(before, tuple(map(parameter_digest, self.heads)))
        self.assertTrue(torch.equal(x, self.x))
        self.assertIsNone(self.x.grad)

    def test_float64_and_large_peer_gradient_preserve_per_cell_clipping(self):
        self.x = (self.x.detach().double() * 100).requires_grad_()
        self.heads = tuple(h.double() for h in self.heads)
        trained, _ = self.fit()
        for i in (1, 2, 3):
            expected, _ = fit_candidate(self.heads[i], self.x[self.rows[i]], self.gold[i],
                                        steps=self.limits[i], seed=self.seeds[i])
            self.compare(trained[i], expected)

    def test_wrong_budget_rejected_before_optimizer_or_candidate_copy(self):
        for bad in ((0, 1), [0, 1, 3, 4], (0, True, 3, 4), (0, -1, 3, 4),
                    (0, 1, 3, 5), (0, 1.0, 3, 4)):
            with self.subTest(bad=bad), patch('development_head_training.torch.optim.SGD') as opt, \
                    patch('development_head_training.deepcopy') as copy:
                with self.assertRaises(ValueError):
                    self.fit(step_counts=bad)
                opt.assert_not_called()
                copy.assert_not_called()

    def test_zero_budget_is_not_permission_to_skip_validation(self):
        self.gold = self.gold[:-1] + (torch.tensor([2, 2]),)
        with patch('development_head_training.torch.optim.SGD') as opt:
            with self.assertRaises(ValueError):
                self.fit(step_counts=(0,) * 4)
            opt.assert_not_called()

    def test_failure_after_first_cell_finishes_returns_no_partial_candidates(self):
        before = tuple(map(parameter_digest, self.heads))
        step = torch.optim.SGD.step
        calls = 0
        def fail_second(opt, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError('injected second-step failure')
            return step(opt, *args, **kwargs)
        with patch('development_head_training.torch.optim.SGD.step', new=fail_second):
            with self.assertRaisesRegex(RuntimeError, 'second-step'):
                self.fit()
        self.assertEqual(calls, 2)
        self.assertEqual(before, tuple(map(parameter_digest, self.heads)))

    def test_optimizer_compaction_is_explicitly_stateless_sgd(self):
        sgd = torch.optim.SGD
        with patch('development_head_training.torch.optim.SGD', wraps=sgd) as constructed:
            self.fit()
        self.assertEqual(constructed.call_count, 3)
        for call in constructed.call_args_list:
            self.assertEqual(call.kwargs['momentum'], 0)
            self.assertEqual(call.kwargs['weight_decay'], 0)

    def test_consumer_respects_cell_keys_and_shared_encoder_path(self):
        rows, gold = census()
        plan = {'b': 4, 'a': 0}
        reports = [run_shared_learning(SharedStemEngine(TensorBackend()), rows, gold, classes=2,
                                       steps=4, head_kind='swiglu', head_batch_size=g,
                                       training_steps_by_cell=plan) for g in (1, 2)]
        self.assertEqual(reports[0]['encoder_calls'], reports[1]['encoder_calls'])
        for report in reports:
            self.assertEqual(report['planned_training_steps'], plan)
            self.assertEqual(report['cells']['a']['training']['examples_processed'], 0)
            self.assertEqual(report['cells']['b']['training']['steps'], 4)
            for row in report['predictions']:
                if row['cell_id'] == 'a':
                    self.assertEqual(row['trained_logits'], row['frozen_logits'])
        for a, b in zip(reports[0]['predictions'], reports[1]['predictions']):
            torch.testing.assert_close(torch.tensor(a['trained_logits']), torch.tensor(b['trained_logits']),
                                       atol=2e-6, rtol=2e-5)

    def test_plan_is_snapshotted_before_backend_can_mutate_caller_mapping(self):
        rows, gold = census()
        plan = {'a': 0, 'b': 4}
        class Mutating(TensorBackend):
            def encode_many(self, texts, representation):
                plan['b'] = 0
                return super().encode_many(texts, representation)
        result = run_shared_learning(SharedStemEngine(Mutating()), rows, gold, classes=2,
                                     steps=4, head_batch_size=2, training_steps_by_cell=plan)
        self.assertEqual(plan['b'], 0)
        self.assertEqual(result['planned_training_steps'], {'a': 0, 'b': 4})
        self.assertEqual(result['cells']['b']['training']['steps'], 4)

    def test_nonfinite_finished_cell_rejected_before_next_segment(self):
        original_step = torch.optim.SGD.step
        calls = 0
        def poison(opt, *args, **kwargs):
            nonlocal calls
            calls += 1
            result = original_step(opt, *args, **kwargs)
            with torch.no_grad():
                opt.param_groups[0]['params'][0][0, 0, 0] = float('nan')
            return result
        with patch('development_head_training.torch.optim.SGD.step', new=poison):
            with self.assertRaisesRegex(ValueError, 'nonfinite trained bank'):
                self.fit()
        self.assertEqual(calls, 1)
        self.assertTrue(all(torch.isfinite(p).all() for h in self.heads for p in h.parameters()))

    def test_bad_consumer_plan_fails_before_encoder(self):
        rows, gold = census()
        for plan in ({'a': 1}, {'a': 1, 'b': 1, 'c': 1}, {'a': 1, 'b': True}, {'a': 0, 'b': 5}):
            backend = TensorBackend()
            with self.assertRaises(ValueError):
                run_shared_learning(SharedStemEngine(backend), rows, gold, classes=2,
                                    steps=4, training_steps_by_cell=plan)
            self.assertEqual(backend.calls, 0)

    def test_scalar_cannot_evade_aggregate_head_limit(self):
        rows, _ = census()
        expanded, labels = [], {}
        for i in range(64):
            for row in (rows[0], rows[-2]):
                request = replace(row.request, cell_id=f'c{i}', request_id=f'{i}-{row.split}')
                expanded.append(replace(row, request=request))
                if row.split == 'train':
                    labels[request.request_id] = 0
        class Wide(TensorBackend):
            def encode_many(self, texts, representation):
                self.calls += 1
                return [FrozenFeature.from_values((1.,) * 512, 1, representation) for _ in texts]
        for grouping in (1, 32):
            with patch('development_learning.nn.Linear') as allocation:
                with self.assertRaisesRegex(ValueError, 'physical Head budget'):
                    run_shared_learning(SharedStemEngine(Wide()), tuple(expanded), labels,
                                        classes=128, steps=1, parameter_budget=262144,
                                        head_batch_size=grouping)
                allocation.assert_not_called()

    def test_cli_plan_pair_and_census_checked_before_loader_import(self):
        rows, labels = census()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = SimpleNamespace(classes=2, steps=4, parameter_budget=16384, max_tokens=128)
            for name, data in (('rows', [asdict(r) for r in rows]), ('labels', labels)):
                raw = json.dumps(data).encode()
                (root/name).write_bytes(raw)
                setattr(args, name, root/name)
                setattr(args, name+'_sha256', hashlib.sha256(raw).hexdigest())
            args.training_plan = root/'plan'
            with self.assertRaisesRegex(ValueError, 'together'):
                run_local(args)
            raw = b'{"a":1,"b":5}'
            args.training_plan.write_bytes(raw)
            args.training_plan_sha256 = hashlib.sha256(raw).hexdigest()
            with self.assertRaisesRegex(ValueError, 'Cell training plan'):
                run_local(args)


if __name__ == '__main__':
    unittest.main()
