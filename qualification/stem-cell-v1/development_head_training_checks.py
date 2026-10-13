"""Independent scalar/training controls; ordinary Torch, no pretrained claim."""

from copy import deepcopy
from unittest.mock import patch
import unittest

import torch
from torch import nn

from development_ablation import fit_candidate
from development_head_training import fit_linear_cells
from development_learning import run_shared_learning
from development_learning_checks import TensorBackend, census
from development_tensors import parameter_digest
from shared_encoder_batch import SharedStemEngine


class BatchedHeadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.threads = torch.get_num_threads()
        torch.set_num_threads(1)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.threads)

    def setUp(self):
        self.context = torch.random.fork_rng(devices=[])
        self.context.__enter__()
        torch.manual_seed(997)
        self.x = torch.randn(40, 8)
        self.heads = tuple(nn.Linear(8, 3) for _ in range(3))
        self.rows = (torch.arange(7), torch.arange(19), torch.arange(40))
        self.gold = tuple(torch.randint(0, 3, (len(r),)) for r in self.rows)
        self.seeds = (71, 72, 73)

    def tearDown(self):
        self.context.__exit__(None, None, None)

    def run_group(self, **kw):
        options = dict(steps=7, group_size=3)
        options.update(kw)
        return fit_linear_cells(self.heads, self.x, self.rows, self.gold, seeds=self.seeds, **options)

    def test_matches_existing_independent_sgd_on_ragged_cells(self):
        candidates, report = self.run_group()
        for i, candidate in enumerate(candidates):
            reference, _ = fit_candidate(self.heads[i], self.x[self.rows[i]], self.gold[i], steps=7, seed=self.seeds[i])
            for a, b in zip(candidate.parameters(), reference.parameters()):
                torch.testing.assert_close(a, b, rtol=1e-6, atol=2e-7)
        self.assertEqual([r['examples_processed'] for r in report['cells']], [49, 133, 224])
        self.assertEqual(report['groups'][0]['physical_example_lanes'], 7*3*32)
        self.assertEqual(report['groups'][0]['useful_example_updates'], 406)

    def test_double_precision_same_objective(self):
        self.x = self.x.double()
        self.heads = tuple(h.double() for h in self.heads)
        candidates, _ = self.run_group()
        for i, candidate in enumerate(candidates):
            reference, _ = fit_candidate(self.heads[i], self.x[self.rows[i]], self.gold[i], steps=7, seed=self.seeds[i])
            for a, b in zip(candidate.parameters(), reference.parameters()):
                torch.testing.assert_close(a, b, rtol=1e-12, atol=1e-13)

    def test_large_peer_gradients_do_not_change_other_cell(self):
        self.x[:7] *= 100
        grouped, report = self.run_group(steps=3)
        alone, solo = fit_linear_cells((self.heads[1],), self.x, (self.rows[1],), (self.gold[1],),
                                       seeds=(self.seeds[1],), steps=3)
        for a, b in zip(grouped[1].parameters(), alone[0].parameters()):
            torch.testing.assert_close(a, b, rtol=1e-6, atol=2e-7)
        self.assertGreater(report['cells'][0]['clipped_steps'], 0)
        self.assertEqual(report['cells'][1]['minibatch_sha256'], solo['cells'][0]['minibatch_sha256'])

    def test_group_size_and_order_preserve_random_streams(self):
        a, ra = self.run_group(group_size=1)
        b, rb = self.run_group(group_size=2)
        order = (2, 0, 1)
        c, rc = fit_linear_cells(tuple(self.heads[i] for i in order), self.x,
                                 tuple(self.rows[i] for i in order), tuple(self.gold[i] for i in order),
                                 seeds=tuple(self.seeds[i] for i in order), steps=7)
        for i in range(3):
            for left, right in zip(a[i].parameters(), b[i].parameters()):
                torch.testing.assert_close(left, right, rtol=1e-6, atol=2e-7)
            for left, right in zip(a[i].parameters(), c[order.index(i)].parameters()):
                torch.testing.assert_close(left, right, rtol=1e-6, atol=2e-7)
            self.assertEqual(ra['cells'][i]['minibatch_sha256'], rb['cells'][i]['minibatch_sha256'])
            self.assertEqual(ra['cells'][i]['minibatch_sha256'], rc['cells'][order.index(i)]['minibatch_sha256'])

    def test_subset_training_leaves_source_peers_and_rng_unchanged(self):
        before = tuple(parameter_digest(h) for h in self.heads)
        original = self.x.clone()
        rng = torch.random.get_rng_state().clone()
        self.x.requires_grad_(True)
        trained, _ = fit_linear_cells((self.heads[0],), self.x, (self.rows[0],),
                                      (self.gold[0],), seeds=(71,), steps=4)
        self.assertEqual(before, tuple(parameter_digest(h) for h in self.heads))
        self.assertTrue(torch.equal(original, self.x))
        self.assertTrue(torch.equal(rng, torch.random.get_rng_state()))
        self.assertIsNone(self.x.grad)
        self.assertTrue(all(p.grad is None for h in self.heads for p in h.parameters()))
        self.assertNotEqual(before[0], parameter_digest(trained[0]))

    def test_frozen_replica_is_not_sharing_candidate_storage(self):
        out, _ = self.run_group(steps=1)
        originals = tuple(parameter_digest(h) for h in self.heads)
        with torch.no_grad():
            out[0].weight.add_(2)
        self.assertEqual(originals, tuple(parameter_digest(h) for h in self.heads))
        self.assertNotEqual(out[0].weight.data_ptr(), out[1].weight.data_ptr())

    def test_late_invalid_cell_rejected_before_optimizer(self):
        for bad in (torch.tensor([999]), torch.tensor([True]), torch.empty(0, dtype=torch.long)):
            with patch('development_head_training.torch.optim.SGD') as optimizer:
                with self.assertRaises(ValueError):
                    fit_linear_cells(self.heads, self.x, self.rows[:-1]+(bad,), self.gold, seeds=self.seeds)
                optimizer.assert_not_called()

    def test_bad_labels_and_mixed_heads_rejected_before_optimizer(self):
        for heads, gold in ((self.heads, self.gold[:-1]+(torch.full((40,), 3, dtype=torch.long),)),
                            (self.heads[:-1]+(nn.Linear(8, 4),), self.gold),
                            (self.heads[:-1]+(nn.Linear(8, 3, bias=False),), self.gold)):
            with patch('development_head_training.torch.optim.SGD') as optimizer:
                with self.assertRaises(ValueError):
                    fit_linear_cells(heads, self.x, self.rows, gold, seeds=self.seeds)
                optimizer.assert_not_called()

    def test_unsupported_resource_values(self):
        for options in ({'steps': True}, {'steps': 1001}, {'group_size': 0}, {'group_size': 33},
                        {'batch_size': True}, {'lr': float('nan')}, {'lr': float('inf')}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.run_group(**options)

    def test_nonfinite_input_and_weight(self):
        self.x[-1, -1] = float('nan')
        with self.assertRaises(ValueError):
            self.run_group()
        self.x[-1, -1] = 0
        with torch.no_grad():
            self.heads[-1].weight[0, 0] = float('inf')
        with self.assertRaises(ValueError):
            self.run_group()

    def test_duplicate_initial_head_still_yields_independent_candidates(self):
        out, _ = fit_linear_cells((self.heads[0], self.heads[0]), self.x,
                                  (self.rows[0], self.rows[0]), (self.gold[0], (self.gold[0]+1)%3),
                                  seeds=(71,71), steps=20)
        self.assertNotEqual(parameter_digest(out[0]), parameter_digest(out[1]))
        self.assertIsNone(self.heads[0].weight.grad)

    def test_end_to_end_shared_engine_same_predictions_and_less_tensor_storage(self):
        rows, labels = census()
        a_backend, b_backend = TensorBackend(), TensorBackend()
        a = run_shared_learning(SharedStemEngine(a_backend), rows, labels, classes=2, steps=100)
        b = run_shared_learning(SharedStemEngine(b_backend), rows, labels, classes=2, steps=100, head_batch_size=2)
        self.assertEqual(a['encoder_batch_widths'], b['encoder_batch_widths'])
        self.assertEqual(a['encoder_calls'], 1)
        self.assertEqual(b['materialized_feature_rows'], 12)
        self.assertEqual(a['materialized_feature_rows'], 24)
        for old, new in zip(a['predictions'], b['predictions']):
            self.assertEqual(old['request_id'], new['request_id'])
            torch.testing.assert_close(torch.tensor(old['trained_logits']), torch.tensor(new['trained_logits']),
                                       rtol=1e-6, atol=2e-6)
        self.assertEqual(len(b['grouped_training']['groups']), 1)
        self.assertTrue(b['simulated_encoder'])
        self.assertFalse(b['production_authorized'])

    def test_failure_mid_training_does_not_mutate_source(self):
        before = tuple(parameter_digest(h) for h in self.heads)
        with patch('development_head_training.torch.optim.SGD.step', side_effect=RuntimeError('injected')):
            with self.assertRaisesRegex(RuntimeError, 'injected'):
                self.run_group()
        self.assertEqual(before, tuple(parameter_digest(h) for h in self.heads))

    def test_all_clipped_cell_gradients_match_original_fitter(self):
        self.x *= 500
        grouped, report = self.run_group(steps=2)
        for i, head in enumerate(grouped):
            scalar, _ = fit_candidate(self.heads[i], self.x[self.rows[i]], self.gold[i], steps=2, seed=self.seeds[i])
            for a, b in zip(head.parameters(), scalar.parameters()):
                torch.testing.assert_close(a, b, rtol=2e-6, atol=2e-7)
            self.assertEqual(report['cells'][i]['clipped_steps'], 2)

    def test_empty_mismatched_and_noninteger_census_rejected(self):
        for initials, rows, labels, seeds in (((), (), (), ()),
            (self.heads, self.rows[:-1], self.gold, self.seeds),
            (self.heads, self.rows, self.gold, (True, 72, 73)),
            (self.heads, self.rows, self.gold, (-1, 72, 73))):
            with self.assertRaises(ValueError):
                fit_linear_cells(initials, self.x, rows, labels, seeds=seeds)

    def test_group_tail_and_example_counts_are_not_dropped(self):
        heads = tuple(deepcopy(self.heads[0]) for _ in range(33))
        models, report = fit_linear_cells(heads, self.x, (self.rows[0],)*33, (self.gold[0],)*33,
                                         seeds=tuple(range(33)), steps=2, group_size=32)
        self.assertEqual(len(models), 33)
        self.assertEqual([g['cells'] for g in report['groups']], [32, 1])
        self.assertEqual(sum(c['examples_processed'] for c in report['cells']), 33*7*2)
        self.assertEqual(sum(g['optimizer_steps'] for g in report['groups']), 4)

    def test_single_sample_and_unused_nan_labels_rejected(self):
        one, report = fit_linear_cells((self.heads[0],), self.x, (torch.tensor([4]),),
                                      (torch.tensor([1]),), seeds=(71,), steps=3)
        ref, _ = fit_candidate(self.heads[0], self.x[4:5], torch.tensor([1]), steps=3, seed=71)
        torch.testing.assert_close(one[0].weight, ref.weight, rtol=1e-6, atol=2e-7)
        self.assertEqual(report['cells'][0]['examples_processed'], 3)
        with self.assertRaises(ValueError):
            fit_linear_cells((self.heads[0],), self.x, (torch.tensor([4]),),
                             (torch.tensor([float('nan')]),), seeds=(71,))

    def test_aggregate_parameter_budget_precedes_optimizer(self):
        with patch('development_head_training.MAX_PARAMETERS', 1), \
                patch('development_head_training.torch.optim.SGD') as optimizer:
            with self.assertRaises(ValueError):
                self.run_group()
            optimizer.assert_not_called()

    def test_invalid_group_option_fails_before_encoder(self):
        rows, labels = census()
        for size in (True, 0, 33):
            backend = TensorBackend()
            with self.assertRaises(ValueError):
                run_shared_learning(SharedStemEngine(backend), rows, labels, classes=2, head_batch_size=size)
            self.assertEqual(backend.calls, 0)


if __name__ == '__main__':
    unittest.main()
