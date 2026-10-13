"""Synthetic constrained-learning and adversarial replay checks, not real quality."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import torch
from safetensors.torch import load, save

from cell_anchor_consolidation import (ANCHOR_TOLERANCE, EXTRA_ARMS, anchor_basis,
                                      fit_anchors, fold_film, train_affine)
from cell_anchor_study import ALL_ARMS, execute, review
from cell_consolidation import ARMS, ConsolidationConfig, select_retained, training_partition
from cell_consolidation_checks import fixture
from cell_consolidation_study import execute as execute_base, review_rows, affine_logits
from development_study import prepare_views
from development_study_data import canonical, phase
from model_runner import build_head


class AnchorMathChecks(unittest.TestCase):
    def setUp(self):
        self.previous_threads = torch.get_num_threads(); torch.set_num_threads(1)
        self.addCleanup(torch.set_num_threads, self.previous_threads)
        self.config = ConsolidationConfig(classes=4, old_classes=(0, 1), steps=12, memory_per_class=2)

    def test_fold_includes_scale_shift_and_bias(self):
        with torch.random.fork_rng():
            torch.manual_seed(8); m, _ = build_head(torch, 4, 4, 'film', 16384)
            with torch.no_grad(): m.gamma.fill_(1.7); m.beta.fill_(.3)
            x = torch.randn(12, 4)
        t = m.state_dict(); folded = fold_film(t, 4, 4)
        y = torch.cat((x.double(), torch.ones(12, 1)), 1) @ folded.T
        self.assertTrue(torch.allclose(m(x), y.float(), atol=1e-6))

    def test_rank_deficient_anchor_span_is_not_padded(self):
        a = torch.tensor([[1., 0., 1.], [1., 0., 1.]], dtype=torch.float64)
        q, _ = anchor_basis(a)
        self.assertEqual(q.shape, (1, 3))
        self.assertLess(float((a-(a@q.T)@q).abs().max()), 1e-10)

    def test_nonfinite_oversized_or_wrong_dtype_anchors_fail(self):
        for a in (torch.ones(2, 3), torch.ones(513, 3, dtype=torch.float64),
                  torch.full((2, 3), float('nan'), dtype=torch.float64)):
            with self.subTest(shape=a.shape), self.assertRaises(ValueError): anchor_basis(a)

    def test_project_actual_updates_and_learn_unconstrained_direction(self):
        base = torch.zeros(4, 3, dtype=torch.float64)
        memory = torch.tensor([[1., 0., 1.], [-1., 0., 1.]], dtype=torch.float64)
        new = torch.tensor([[0., 2., 1.], [0., 3., 1.]], dtype=torch.float64)
        p = torch.tensor([[.25]*4, [.25]*4, [.01, .01, .97, .01], [.01, .01, .97, .01]], dtype=torch.float64)
        out, report = train_affine(base, memory, new, p, memory, self.config)
        packed = torch.cat((out['weight'], out['bias'][:, None]), 1).double()
        self.assertLess(float((memory@packed.T).abs().max()), 1e-8)
        self.assertGreater(float((new@packed.T)[:, 2].mean()), .01)
        self.assertEqual(report['constraint_rank'], 2)
        self.assertEqual(report['free_input_dimensions'], 1)

    def test_full_rank_protection_prevents_any_affine_learning(self):
        a = torch.tensor([[1., 0., 1.], [0., 1., 1.], [0., 0., 1.]], dtype=torch.float64)
        base = torch.zeros(4, 3, dtype=torch.float64)
        p = torch.ones(6, 4, dtype=torch.float64)/4; p[3:] = torch.tensor([.01,.01,.97,.01])
        p /= p.sum(1, keepdim=True)
        out, r = train_affine(base, a, a, p, a, self.config)
        self.assertEqual(r['free_input_dimensions'], 0)
        self.assertLess(float(out['weight'].abs().max()), 1e-12)

    def test_unconstrained_comparator_uses_same_packed_size(self):
        a = torch.tensor([[1.,0.,1.], [0.,1.,1.]], dtype=torch.float64)
        base = torch.zeros(4,3,dtype=torch.float64)
        p = torch.tensor([[.01,.01,.97,.01]]*4, dtype=torch.float64)
        u, ru = train_affine(base,a,a,p,a[:0],self.config)
        c, rc = train_affine(base,a,a,p,a,self.config)
        self.assertEqual(ru['deployed_weight_bytes'],rc['deployed_weight_bytes'])
        self.assertEqual(ru['sample_presentations'],rc['sample_presentations'])
        self.assertGreater(float(u['bias'].abs().max()), float(c['bias'].abs().max()))

    def test_invalid_targets_rejected_before_optimizer(self):
        a = torch.ones(2,3,dtype=torch.float64)
        with self.assertRaises(ValueError):
            train_affine(torch.zeros(4,3,dtype=torch.float64),a,a,torch.ones(4,4,dtype=torch.float64),a,self.config)


class AnchorStudyChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous_threads = torch.get_num_threads(); torch.set_num_threads(1)
        cls.tmp = tempfile.TemporaryDirectory(); cls.root = Path(cls.tmp.name)
        cls.rows, cls.x = fixture()
        cls.config = ConsolidationConfig(classes=4, old_classes=(0,1), steps=12, memory_per_class=2)
        cls.origin = {'synthetic_fixture': True, 'current_encoder_calls': 0}
        cls.baseline, cls.initial = cls.root/'baseline', cls.root/'initial'
        execute_base(cls.rows, cls.x, cls.origin, cls.baseline, cls.config)
        execute(cls.rows, cls.x, cls.origin, cls.baseline, cls.initial)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup(); torch.set_num_threads(cls.previous_threads)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'copy'; shutil.copytree(self.initial,self.path)

    def check(self): return review(self.rows,self.x,self.origin,self.baseline,self.path)

    def rewrite(self, filename, obj, field):
        raw = canonical(obj); (self.path/filename).write_bytes(raw)
        run = json.loads((self.path/'run.json').read_text()); run[field] = hashlib.sha256(raw).hexdigest()
        (self.path/'run.json').write_bytes(canonical(run))

    def test_all_nine_controls_reconstruct_and_rank_is_checked(self):
        result = self.check()
        self.assertEqual(set(result['scores']['held_out']),set(ALL_ARMS))
        self.assertEqual(result['prediction_rows'],64*9)
        self.assertEqual(result['anchors']['anchor_memory']['rows'],4)
        self.assertFalse(result['production_authorized'])

    def test_no_held_out_label_needed_to_execute_or_verify_baseline(self):
        hidden = deepcopy(self.rows)
        for r in hidden:
            if phase(r)=='held_out': del r['label']
        report = review_rows(hidden,self.x,self.origin,self.baseline,score_held_out=False)
        self.assertEqual(set(report['scores']),{'calibration'})
        execute(hidden,self.x,self.origin,self.baseline,Path(self.tmp.name)/'no-truth')

    def test_test_label_permutation_preserves_weights_and_selection(self):
        altered = deepcopy(self.rows)
        for r in altered:
            if phase(r)=='held_out': r['label']=(r['label']+1)%4
        other=Path(self.tmp.name)/'permuted'; execute(altered,self.x,self.origin,self.baseline,other)
        for n in ('predictions.json',*[a+'.safetensors' for a in EXTRA_ARMS]):
            self.assertEqual((other/n).read_bytes(),(self.path/n).read_bytes())
        a,b=[json.loads((p/'selection.json').read_text()) for p in (other,self.path)]
        for n in ('selected_arm','calibration_metrics','calibration_floors','checkpoints','memory'):
            self.assertEqual(a[n],b[n])

    def test_calibration_truth_cannot_enter_fitting(self):
        inputs,_=prepare_views(self.rows)
        truth={r['sample_id']:r['label'] for r in self.rows if phase(r) in ('base','adapt')}
        truth[next(r['sample_id'] for r in self.rows if phase(r)=='calibration')]=0
        with self.assertRaises(ValueError): fit_anchors(inputs,truth,self.x,self.config,{})

    def test_teacher_and_features_not_mutated(self):
        inputs,_=prepare_views(self.rows)
        truth={r['sample_id']:r['label'] for r in self.rows if phase(r) in ('base','adapt')}
        teachers={n:load((self.baseline/f'{n}.safetensors').read_bytes()) for n in ('frozen','new_only')}
        before=deepcopy(teachers); x=self.x.clone(); rng=torch.get_rng_state().clone()
        fit_anchors(inputs,truth,self.x,self.config,teachers)
        self.assertTrue(torch.equal(x,self.x)); self.assertTrue(torch.equal(rng,torch.get_rng_state()))
        self.assertTrue(all(torch.equal(before[n][k],teachers[n][k]) for n in teachers for k in teachers[n]))

    def test_rehashed_changed_logits_rejected(self):
        p=json.loads((self.path/'predictions.json').read_text()); p[-1]['logits'][0]+=.1
        self.rewrite('predictions.json',p,'predictions_sha256')
        with self.assertRaises(ValueError): self.check()

    def test_rehashed_larger_memory_cost_rejected(self):
        s=json.loads((self.path/'selection.json').read_text());s['costs']['anchor_all_old']['anchor_tensor_bytes']=0
        self.rewrite('selection.json',s,'selection_sha256')
        with self.assertRaises(ValueError): self.check()

    def test_rehashed_rank_and_winner_refused(self):
        s=json.loads((self.path/'selection.json').read_text());s['costs']['anchor_memory']['constraint_rank']=0
        self.rewrite('selection.json',s,'selection_sha256')
        with self.assertRaises(ValueError): self.check()
        s=json.loads((self.initial/'selection.json').read_text());s['selected_arm']='unknown'
        self.rewrite('selection.json',s,'selection_sha256')
        with self.assertRaises(ValueError): self.check()

    def test_rehashed_bad_anchor_checkpoint_rejected(self):
        p=self.path/'anchor_memory.safetensors'; t=load(p.read_bytes());t['bias'][0]+=1
        raw=save(t);p.write_bytes(raw)
        s=json.loads((self.path/'selection.json').read_text());s['checkpoints']['anchor_memory']=hashlib.sha256(raw).hexdigest()
        self.rewrite('selection.json',s,'selection_sha256')
        with self.assertRaises(ValueError): self.check()

    def test_duplicate_missing_or_label_bearing_predictions_rejected(self):
        p=json.loads((self.path/'predictions.json').read_text());p[-1]=p[0]
        self.rewrite('predictions.json',p,'predictions_sha256')
        with self.assertRaises(ValueError): self.check()
        p=json.loads((self.initial/'predictions.json').read_text());p[0]['label']=0
        self.rewrite('predictions.json',p,'predictions_sha256')
        with self.assertRaises(ValueError): self.check()

    def test_failed_and_existing_output_never_reused(self):
        with self.assertRaises(FileExistsError): execute(self.rows,self.x,self.origin,self.baseline,self.path)
        (self.path/'FAILED.json').write_text('{}')
        with self.assertRaises(ValueError): self.check()

    def test_incomplete_or_path_escaping_checkpoint_name_rejected(self):
        s=json.loads((self.path/'selection.json').read_text());s['checkpoints']['../escape']=s['checkpoints'].pop('anchor_memory')
        self.rewrite('selection.json',s,'selection_sha256')
        with self.assertRaises(ValueError): self.check()

    def test_rehashed_calibration_metric_and_fresh_encoder_claim_rejected(self):
        s=json.loads((self.path/'selection.json').read_text())
        s['calibration_metrics']['anchor_memory']['old']['brier']+=.01
        self.rewrite('selection.json',s,'selection_sha256')
        with self.assertRaises(ValueError): self.check()
        s=json.loads((self.initial/'selection.json').read_text())
        self.rewrite('selection.json',s,'selection_sha256')
        r=json.loads((self.path/'run.json').read_text());r['current_encoder_calls']=1
        (self.path/'run.json').write_bytes(canonical(r))
        with self.assertRaises(ValueError): self.check()

    def test_changed_anchor_membership_rejected(self):
        s=json.loads((self.path/'selection.json').read_text())
        s['costs']['anchor_memory']['anchor_indices'][0]=next(i for i,r in enumerate(self.rows) if phase(r)=='held_out')
        self.rewrite('selection.json',s,'selection_sha256')
        with self.assertRaises(ValueError): self.check()

    def test_original_selector_still_requires_original_controls_by_default(self):
        scores=self.check()['scores']['calibration']
        with self.assertRaises(ValueError):select_retained(scores,self.config)
        self.assertIn(select_retained(scores,self.config,extra_arms=EXTRA_ARMS)['selected_arm'],ALL_ARMS)
        with self.assertRaises(ValueError):select_retained(scores,self.config,extra_arms=('frozen',))


if __name__=='__main__': unittest.main()
