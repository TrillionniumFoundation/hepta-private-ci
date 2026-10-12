"""Actual gated gradients and scalar equivalence; no pretrained/model promotion."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
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
from shared_encoder_batch import SharedStemEngine


class GatedTrainingTests(unittest.TestCase):
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
        torch.manual_seed(411)
        self.x = torch.randn(64, 8)
        self.heads = tuple(SwiGLUCellHead(8, 6, 3) for _ in range(3))
        self.rows = (torch.arange(7), torch.arange(11, 34), torch.arange(24, 64))
        self.gold = tuple(torch.arange(len(r)).remainder(3) for r in self.rows)
        self.seeds = (71, 72, 73)

    def tearDown(self):
        self.rng.__exit__(None, None, None)

    def run_group(self, **kwargs):
        return fit_gated_cells(self.heads, self.x, self.rows, self.gold, seeds=self.seeds,
                               **({'steps': 7} | kwargs))

    def compare(self, left, right, *, atol=2e-6, rtol=2e-5):
        self.assertEqual(tuple(dict(left.named_parameters())), tuple(dict(right.named_parameters())))
        for a, b in zip(left.parameters(), right.parameters()):
            torch.testing.assert_close(a, b, atol=atol, rtol=rtol)

    def test_same_six_parameter_updates_as_scalar_ragged_sgd(self):
        models, result = self.run_group()
        for i, head in enumerate(models):
            scalar, receipt = fit_candidate(self.heads[i], self.x[self.rows[i]], self.gold[i],
                                            steps=7, seed=self.seeds[i])
            self.compare(head, scalar)
            self.assertEqual(result['cells'][i]['examples_processed'], receipt['examples_processed'])
            torch.testing.assert_close(head(self.x), scalar(self.x), atol=2e-6, rtol=2e-5)
        self.assertEqual(result['head_family'], 'swiglu')
        self.assertFalse(result['production_authorized'])

    def test_double_precision_equivalence(self):
        self.x = self.x.double()
        self.heads = tuple(h.double() for h in self.heads)
        models, _ = self.run_group()
        for i, h in enumerate(models):
            scalar, _ = fit_candidate(self.heads[i], self.x[self.rows[i]], self.gold[i],
                                       steps=7, seed=self.seeds[i])
            self.compare(h, scalar, atol=2e-13, rtol=2e-11)

    def test_input_dependent_gate_is_nonaffine(self):
        head = SwiGLUCellHead(1, 1, 2)
        with torch.no_grad():
            for p in head.parameters(): p.fill_(1)
        x, y = torch.tensor([[.3]]), torch.tensor([[.8]])
        self.assertFalse(torch.allclose(head(x+y)-head(torch.zeros_like(x)),
                                       head(x)+head(y)-2*head(torch.zeros_like(x))))

    def test_gate_value_and_readout_all_learn(self):
        output, _ = self.run_group(steps=20)
        for layer in ('gate', 'value', 'readout'):
            self.assertFalse(torch.equal(getattr(output[0], layer).weight,
                                         getattr(self.heads[0], layer).weight))

    def test_large_peer_gradients_do_not_clip_other_cell(self):
        self.x[:7] *= 100
        together, report = self.run_group(steps=3)
        alone, solo = fit_gated_cells((self.heads[1],), self.x, (self.rows[1],), (self.gold[1],),
                                      seeds=(72,), steps=3)
        self.compare(together[1], alone[0])
        self.assertGreater(report['cells'][0]['clipped_steps'], 0)
        self.assertEqual(report['cells'][1]['minibatch_sha256'], solo['cells'][0]['minibatch_sha256'])

    def test_full_head_clipping_matches_scalar(self):
        self.x *= 100
        output, report = self.run_group(steps=2)
        for i in range(3):
            ref, _ = fit_candidate(self.heads[i], self.x[self.rows[i]], self.gold[i],
                                   seed=self.seeds[i], steps=2)
            self.compare(output[i], ref)
            self.assertEqual(report['cells'][i]['clipped_steps'], 2)

    def test_grouping_and_order_preserve_minibatch_streams(self):
        a, ar = self.run_group(group_size=1)
        b, br = self.run_group(group_size=2)
        order = (2, 0, 1)
        c, cr = fit_gated_cells(tuple(self.heads[i] for i in order), self.x,
                                tuple(self.rows[i] for i in order), tuple(self.gold[i] for i in order),
                                seeds=tuple(self.seeds[i] for i in order), steps=7)
        for i in range(3):
            self.compare(a[i], b[i]); self.compare(a[i], c[order.index(i)])
            self.assertEqual(ar['cells'][i]['minibatch_sha256'], br['cells'][i]['minibatch_sha256'])
            self.assertEqual(ar['cells'][i]['minibatch_sha256'], cr['cells'][order.index(i)]['minibatch_sha256'])

    def test_parent_and_global_rng_unchanged(self):
        before = tuple(parameter_digest(h) for h in self.heads)
        self.x.requires_grad_(True)
        x = self.x.clone()
        rng = torch.random.get_rng_state().clone()
        self.run_group()
        self.assertEqual(before, tuple(parameter_digest(h) for h in self.heads))
        self.assertTrue(torch.equal(x, self.x)); self.assertIsNone(self.x.grad)
        self.assertTrue(torch.equal(rng, torch.random.get_rng_state()))
        self.assertTrue(all(p.grad is None for h in self.heads for p in h.parameters()))

    def test_inherited_parent_can_diverge_without_storage_alias(self):
        source = self.heads[0]
        output, _ = fit_gated_cells((source, source), self.x, (self.rows[0],)*2,
                                    (self.gold[0], (self.gold[0]+1)%3), seeds=(71,71), steps=15)
        self.assertNotEqual(parameter_digest(output[0]), parameter_digest(output[1]))
        for a,b,c in zip(source.parameters(), output[0].parameters(), output[1].parameters()):
            self.assertNotEqual(a.data_ptr(), b.data_ptr()); self.assertNotEqual(b.data_ptr(), c.data_ptr())

    def test_group_tail_and_padding_are_charged(self):
        output, report = fit_gated_cells((self.heads[0],)*33, self.x, (self.rows[0],)*33,
                                         (self.gold[0],)*33, seeds=tuple(range(33)), steps=2)
        self.assertEqual(len(output), 33)
        self.assertEqual([g['cells'] for g in report['groups']], [32,1])
        self.assertEqual(sum(g['useful_example_updates'] for g in report['groups']), 33*7*2)
        _, ragged = self.run_group(steps=2)
        self.assertGreater(ragged['groups'][0]['physical_example_lanes'], ragged['groups'][0]['useful_example_updates'])

    def test_late_bad_member_precedes_optimizer(self):
        with patch('development_head_training.torch.optim.SGD') as opt:
            with self.assertRaises(ValueError):
                fit_gated_cells(self.heads, self.x, self.rows[:-1]+(torch.tensor([999]),),
                                 self.gold, seeds=self.seeds)
            opt.assert_not_called()

    def test_frozen_wrong_and_extra_projection_rejected(self):
        for kind in ('frozen', 'shape', 'extra', 'linear'):
            hs = list(deepcopy(self.heads))
            if kind == 'frozen': hs[-1].gate.requires_grad_(False)
            if kind == 'shape': hs[-1].value = nn.Linear(8,5)
            if kind == 'extra': hs[-1].extra = nn.Linear(1,1)
            if kind == 'linear': hs[-1] = nn.Linear(8,3)
            with self.subTest(kind=kind), patch('development_head_training.torch.optim.SGD') as opt:
                with self.assertRaises(ValueError):
                    fit_gated_cells(tuple(hs), self.x, self.rows, self.gold, seeds=self.seeds)
                opt.assert_not_called()
        with self.assertRaises(ValueError):
            fit_linear_cells(self.heads, self.x, self.rows, self.gold, seeds=self.seeds)

    def test_bad_numeric_and_resource_inputs_rejected(self):
        for options in ({'steps':True},{'group_size':33},{'lr':float('nan')},{'batch_size':0}):
            with self.subTest(options=options), self.assertRaises(ValueError): self.run_group(**options)
        with torch.no_grad(): self.heads[-1].gate.weight[0,0] = float('nan')
        with self.assertRaises(ValueError): self.run_group()

    def test_aggregate_bound_before_optimizer(self):
        with patch('development_head_training.MAX_PARAMETERS',1), patch('development_head_training.torch.optim.SGD') as opt:
            with self.assertRaises(ValueError): self.run_group()
            opt.assert_not_called()

    def test_training_failure_preserves_originals(self):
        before = tuple(parameter_digest(h) for h in self.heads)
        with patch('development_head_training.torch.optim.SGD.step', side_effect=RuntimeError('injected')):
            with self.assertRaisesRegex(RuntimeError,'injected'): self.run_group()
        self.assertEqual(before, tuple(parameter_digest(h) for h in self.heads))

    def test_single_example_and_invalid_labels(self):
        one, _ = fit_gated_cells((self.heads[0],), self.x, (torch.tensor([4]),),
                                 (torch.tensor([1]),), seeds=(71,), steps=3)
        ref, _ = fit_candidate(self.heads[0], self.x[4:5], torch.tensor([1]), steps=3, seed=71)
        self.compare(one[0],ref)
        with self.assertRaises(ValueError):
            fit_gated_cells(self.heads, self.x, self.rows, self.gold[:-1]+(self.gold[-1]+3,), seeds=self.seeds)

    def test_real_consumer_separate_heads_shared_encoding(self):
        rows, labels = census()
        a = run_shared_learning(SharedStemEngine(TensorBackend()), rows, labels, classes=2,
                                 steps=60, head_kind='swiglu', head_hidden_size=8)
        b = run_shared_learning(SharedStemEngine(TensorBackend()), rows, labels, classes=2,
                                 steps=60, head_kind='swiglu', head_hidden_size=8, head_batch_size=2)
        self.assertEqual(a['encoder_batch_widths'], b['encoder_batch_widths'])
        self.assertEqual(b['encoder_calls'],1)
        self.assertEqual(b['materialized_feature_rows'],12)
        self.assertEqual(b['grouped_training']['head_family'],'swiglu')
        for left,right in zip(a['predictions'], b['predictions']):
            self.assertEqual(left['request_id'], right['request_id'])
            torch.testing.assert_close(torch.tensor(left['trained_logits']),torch.tensor(right['trained_logits']),
                                       atol=2e-6,rtol=2e-5)
        self.assertTrue(b['simulated_encoder']); self.assertFalse(b['production_authorized'])

    def test_invalid_consumer_options_before_encoding(self):
        rows, labels = census()
        for opts in ({'head_kind':'unknown'}, {'head_hidden_size':0}, {'head_hidden_size':True}):
            backend=TensorBackend()
            with self.assertRaises(ValueError): run_shared_learning(SharedStemEngine(backend),rows,labels,classes=2,**opts)
            self.assertEqual(backend.calls,0)

    def test_preload_cli_options_fail_before_model_import(self):
        rows, labels = census()
        with TemporaryDirectory() as directory:
            p=Path(directory)
            a,b=json.dumps([asdict(r) for r in rows]).encode(),json.dumps(labels).encode()
            (p/'rows').write_bytes(a); (p/'labels').write_bytes(b)
            args=SimpleNamespace(rows=p/'rows',rows_sha256=hashlib.sha256(a).hexdigest(),
                                 labels=p/'labels',labels_sha256=hashlib.sha256(b).hexdigest(),classes=2,
                                 steps=5,parameter_budget=16384,max_tokens=512,head_kind='swiglu',head_hidden_size=0)
            with self.assertRaisesRegex(ValueError,'pre-load'): run_local(args)

    def test_constructor_and_budget_bounds(self):
        for dims in ((True,2,2),(513,2,2),(8,257,2),(8,2,1)):
            with self.assertRaises(ValueError): SwiGLUCellHead(*dims)
        rows, labels = census()
        with self.assertRaisesRegex(ValueError,'budget'):
            run_shared_learning(SharedStemEngine(TensorBackend()),rows,labels,classes=2,
                                head_kind='swiglu',head_hidden_size=8,parameter_budget=20)


if __name__=='__main__': unittest.main()
