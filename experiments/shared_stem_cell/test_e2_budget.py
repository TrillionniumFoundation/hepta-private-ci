"""Model-independent unit tests; physical source execution is a separate CI lane."""
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch
from safetensors.numpy import load

from experiments.shared_stem_cell.e2_budget_sweep import (
    BUDGETS, SEEDS, rank_for, train_one, produce,
)
from experiments.shared_stem_cell.e2_budget_review import independent_probabilities
from experiments.shared_stem_cell.preflight_review import PreflightError


class E2BudgetTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(2)

    def data(self):
        rng=np.random.default_rng(7)
        x=torch.tensor(rng.normal(size=(12,5)).astype(np.float32))
        y=torch.tensor([0,1,2,3,1,3,2,0,0,1,3,2],dtype=torch.long)
        eval_x=torch.tensor(rng.normal(size=(8,5)).astype(np.float32))
        return x,y,eval_x

    def test_head_fits_all_five_budgets_for_384_and_768(self):
        for width in (384,768):
            last=0
            for ceiling in BUDGETS:
                with self.subTest(width=width,ceiling=ceiling):
                    rank,params=rank_for(width,4,ceiling)
                    self.assertGreater(rank,0)
                    self.assertLessEqual(params,ceiling)
                    self.assertGreater(params,last)
                    last=params
        self.assertEqual(rank_for(768,4,2048),(2,1550))
        self.assertEqual(rank_for(384,4,2048),(5,1949))

    def test_real_train_changes_weights_and_same_initial_frozen(self):
        x,y,e=self.data()
        r=train_one(x,y,e,seed=11,cell=0,ceiling=2048)
        self.assertNotEqual(r['checkpoint']['trained'],r['checkpoint']['frozen'])
        self.assertEqual(r['examples_processed'],20*12)
        self.assertEqual(r['training_steps'],20)
        self.assertEqual(r['prediction']['trained'].shape,(8,4))
        self.assertTrue(np.allclose(r['prediction']['trained'].sum(axis=1),1,atol=1e-6))

    def test_real_optimizer_replays_bit_exact_checkpoint_with_seed(self):
        x,y,e=self.data()
        a=train_one(x,y,e,seed=11,cell=0,ceiling=8192)
        b=train_one(x,y,e,seed=11,cell=0,ceiling=8192)
        self.assertEqual(a['checkpoint'],b['checkpoint'])
        self.assertEqual(a['minibatch_sha256'],b['minibatch_sha256'])
        self.assertTrue(np.array_equal(a['prediction']['trained'],b['prediction']['trained']))

    def test_same_cell_train_stream_across_budgets_and_seeds(self):
        x,y,e=self.data()
        rows=[train_one(x,y,e,seed=seed,cell=0,ceiling=cap)['minibatch_sha256']
              for seed in SEEDS[:2] for cap in BUDGETS[:3]]
        self.assertEqual(len(set(rows)),1)
        other=train_one(x,y,e,seed=11,cell=1,ceiling=2048)['minibatch_sha256']
        self.assertNotEqual(rows[0],other)

    def test_numpy_predictions_match_torch_without_original_head_forward(self):
        x,y,e=self.data()
        for ceiling in BUDGETS[:3]:
            with self.subTest(ceiling=ceiling):
                r=train_one(x,y,e,seed=11,cell=0,ceiling=ceiling)
                t=load(r['checkpoint']['trained'])
                predicted=independent_probabilities(e.numpy(),t,5,4,r['rank'])
                self.assertTrue(np.allclose(predicted,r['prediction']['trained'],atol=2e-5))

    def test_rejects_invalid_labels_or_unknown_budget(self):
        x,y,e=self.data()
        with self.assertRaises(PreflightError):
            rank_for(384,4,9999)
        with self.assertRaises(PreflightError):
            train_one(x,torch.full_like(y,9),e,seed=11,cell=0,ceiling=2048)
        with self.assertRaises(PreflightError):
            train_one(x,y,e,seed=11,cell=0,ceiling=2048,steps=21)

    def test_original_source_missing_is_not_replaced_with_synthetic_features(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)
            with self.assertRaises((OSError,PreflightError)):
                produce(path/'none.json',path/'missing',path/'out',report_sha256='a'*64)
            self.assertFalse((path/'out/run.json').exists())

    def test_independent_numpy_rejects_wrong_tensors(self):
        x,y,e=self.data()
        r=train_one(x,y,e,seed=11,cell=0,ceiling=2048)
        t=load(r['checkpoint']['trained'])
        t['down.weight']=t['down.weight'][:,1:]
        with self.assertRaises(PreflightError):
            independent_probabilities(e.numpy(),t,5,4,r['rank'])


if __name__=='__main__': unittest.main()
