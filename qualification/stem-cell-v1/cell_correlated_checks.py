"""Synthetic covariance and paired-study checks, not pretrained efficacy claims."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import torch

from cell_correlated_geometry import correlated_fit, fit_envelope
from cell_prototype_gate import geometry_fit, fit_geometry_candidates
from cell_prototype_study import (ALL_ARMS, CORRELATED_ARMS, execute, fit_profile, review)
import cell_prototype_checks as prototype_fixtures
from cell_consolidation_checks import fixture
from cell_consolidation import ConsolidationConfig
from cell_consolidation_study import execute as base_execute
from cell_anchor_study import execute as anchor_execute
from cell_conditional_study import execute as conditional_execute
from development_study_data import canonical, phase


class CovarianceMath(unittest.TestCase):
    def setUp(self):
        threads = torch.get_num_threads(); torch.set_num_threads(1)
        self.addCleanup(torch.set_num_threads, threads)
        self.x = torch.randn(32, 6, generator=torch.Generator().manual_seed(731))
        self.y = torch.arange(4).repeat_interleave(8)
        self.groups = [str(i) for i in range(32)]

    def fit(self, x=None, shrinkage=.1, **kwargs):
        return correlated_fit(self.x if x is None else x, self.y, self.groups, 4, shrinkage, **kwargs)

    def test_independent_numpy_pooled_covariance_solve(self):
        x = self.x.double().numpy(); mus = np.stack([x[i:i+8].mean(0) for i in range(0,32,8)])
        s = sum((x[i:i+8]-mu).T@(x[i:i+8]-mu)/8 for i,mu in zip(range(0,32,8),mus))/4
        cov = .9*s + max(.1*np.trace(s)/6,1e-8)*np.eye(6)
        expected = np.linalg.solve(cov,(mus-mus.mean(0)).T).T
        w,b,c = self.fit()
        np.testing.assert_allclose(w.numpy(),expected,atol=1e-12)
        np.testing.assert_allclose(b.numpy(),-.5*((mus-mus.mean(0))*expected).sum(1),atol=1e-12)
        np.testing.assert_allclose(c.numpy(),mus.mean(0),atol=1e-12)

    def test_spherical_case_matches_original_geometry(self):
        actual = self.fit(shrinkage=1.0)
        expected = geometry_fit(self.x,self.y,self.groups,4,1.0)
        self.assertTrue(all(torch.allclose(a,b,atol=1e-12) for a,b in zip(actual,expected)))

    def test_spherical_path_skips_dense_allocation_and_factorization(self):
        with patch('torch.linalg.cholesky',side_effect=AssertionError('no factor needed')):
            values=self.fit(shrinkage=1.0,maximum_fit_elements=fit_envelope(32,6,4,1.0))
        expected=geometry_fit(self.x,self.y,self.groups,4,1.0)
        self.assertTrue(all(torch.equal(a,b) for a,b in zip(values,expected)))

    def test_correlated_metric_is_not_the_diagonal_ablation(self):
        w,_,_ = self.fit()
        diagonal,_,_ = geometry_fit(self.x,self.y,self.groups,4,.1)
        self.assertGreater(float((w-diagonal).abs().max()),.01)

    def test_orthogonal_change_of_coordinates_preserves_scores(self):
        q,_ = torch.linalg.qr(torch.randn(6,6,generator=torch.Generator().manual_seed(5)).double())
        rotated = (self.x.double()@q).float()
        a,b,c = self.fit(); w,v,u = self.fit(rotated)
        expected = (self.x.double()-c)@a.T+b
        actual = (rotated.double()-u)@w.T+v
        self.assertTrue(torch.allclose(actual,expected,atol=2e-6))

    def test_duplicate_identical_sources_do_not_change_fit(self):
        a=self.fit()
        b=correlated_fit(torch.cat((self.x,self.x[:8])),torch.cat((self.y,self.y[:8])),self.groups+self.groups[:8],4,.1)
        self.assertTrue(all(torch.equal(v,w) for v,w in zip(a,b)))

    def test_input_permutation_does_not_change_fit(self):
        order=torch.arange(31,-1,-1)
        a=self.fit(); b=correlated_fit(self.x[order],self.y[order],[self.groups[i] for i in order],4,.1)
        self.assertTrue(all(torch.equal(v,w) for v,w in zip(a,b)))

    def test_zero_variance_and_rank_deficiency_have_explicit_ridge(self):
        x=torch.nn.functional.one_hot(self.y,4).float()
        result=correlated_fit(x,self.y,self.groups,4,.1)
        self.assertTrue(all(torch.isfinite(t).all() for t in result))
        self.assertTrue(torch.equal(((x.double()-result[2])@result[0].T+result[1]).argmax(1),self.y))

    def test_fitting_budget_rejected_before_matrix_factorization(self):
        cap=fit_envelope(32,6,4)
        with patch('torch.linalg.cholesky',side_effect=AssertionError('must not dispatch')):
            with self.assertRaises(ValueError): self.fit(maximum_fit_elements=cap-1)
        self.fit(maximum_fit_elements=cap)

    def test_nonfinite_and_wrong_dtype_refused(self):
        for x in (self.x.double(),self.x.clone().fill_(float('nan')),self.x.clone().fill_(float('inf'))):
            with self.subTest(dtype=x.dtype),self.assertRaises(ValueError): self.fit(x)

    def test_unregistered_shrinkage_and_budget_refused(self):
        for shrinkage in (0.,2.,True):
            with self.assertRaises(ValueError): self.fit(shrinkage=shrinkage)
        for cap in (False,0,8_388_609):
            with self.assertRaises(ValueError): self.fit(maximum_fit_elements=cap)

    def test_conflicting_training_group_refused(self):
        groups=self.groups.copy();groups[-1]=groups[0]
        with self.assertRaises(ValueError): correlated_fit(self.x,self.y,groups,4,.1)

    def test_corrupt_solver_cannot_pass_finite_but_wrong_result(self):
        with patch('torch.cholesky_solve',return_value=torch.zeros(6,4,dtype=torch.float64)):
            with self.assertRaisesRegex(ValueError,'residual'): self.fit()

    def test_fit_detaches_training_inputs(self):
        x=self.x.clone().requires_grad_(True); original=x.detach().clone()
        outputs=self.fit(x)
        self.assertFalse(any(v.requires_grad for v in outputs))
        self.assertTrue(torch.equal(x,original)); self.assertIsNone(x.grad)


class CovarianceIsolation(unittest.TestCase):
    def setUp(self):
        # Reuse data/teacher construction, not inherited test cases.
        self.fixture = prototype_fixtures.PrototypeMath('test_parameter_size_and_standalone_control')
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)

    def fit(self, x=None):
        f=self.fixture
        return fit_profile(f.inputs,f.truth,f.x if x is None else x,f.config,f.teachers,'paired-full')

    def test_diagonal_candidates_remain_byte_exact_and_full_same_size(self):
        f=self.fixture; original=deepcopy(f.teachers)
        both,_,_,costs=self.fit()
        diagonal=fit_profile(f.inputs,f.truth,f.x,f.config,f.teachers,'diagonal')[0]
        for name,t in diagonal.items():
            self.assertTrue(all(torch.equal(v,both[name][k]) for k,v in t.items()))
            self.assertEqual(sum(v.numel() for v in t.values()),sum(v.numel() for v in both['full_'+name].values()))
        for n,t in original.items(): self.assertTrue(all(torch.equal(v,f.teachers[n][k]) for k,v in t.items()))
        for name in ('full_memory','full_all_old'):
            self.assertEqual(costs['arms'][name]['factorization_calls'],4+int(costs['arms'][name]['grid'][costs['arms'][name]['selected']]['shrinkage']<1))
            self.assertEqual(costs['arms'][name]['covariance_matrix_bytes'],8*8*8)
        self.assertEqual(costs['current_encoder_calls'],0)

    def test_calibration_and_test_features_do_not_fit_geometry(self):
        f=self.fixture; x=f.x.clone()
        for i,row in enumerate(f.inputs):
            if row['phase'] not in ('base','adapt'): x[i]=1000
        a=self.fit()[0];b=self.fit(x)[0]
        for n,t in a.items(): self.assertTrue(all(torch.equal(v,b[n][k]) for k,v in t.items()))

    def test_profile_and_extra_truth_rejected(self):
        f=self.fixture
        with self.assertRaises(ValueError): fit_profile(f.inputs,f.truth,f.x,f.config,f.teachers,'oracle')
        truth=dict(f.truth);truth[next(r['sample_id'] for r in f.inputs if r['phase']=='held_out')]=0
        with self.assertRaises(ValueError): fit_geometry_candidates(f.inputs,truth,f.x,f.config,f.teachers,covariance='full')


class CovarianceStudy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.threads=torch.get_num_threads();torch.set_num_threads(1)
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name)
        cls.rows,cls.x=fixture();cls.origin={'synthetic_only':True}
        cfg=ConsolidationConfig(classes=4,old_classes=(0,1),steps=12,memory_per_class=8)
        cls.base,cls.anchor,cls.conditional,cls.initial=[cls.root/n for n in ('base','anchor','conditional','paired')]
        base_execute(cls.rows,cls.x,cls.origin,cls.base,cfg)
        anchor_execute(cls.rows,cls.x,cls.origin,cls.base,cls.anchor)
        conditional_execute(cls.rows,cls.x,cls.origin,cls.base,cls.anchor,cls.conditional)
        execute(cls.rows,cls.x,cls.origin,cls.base,cls.anchor,cls.conditional,cls.initial,profile='paired-full')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup();torch.set_num_threads(cls.threads)

    def setUp(self):
        self.case=tempfile.TemporaryDirectory();self.addCleanup(self.case.cleanup)
        self.folder=Path(self.case.name)/'copy';shutil.copytree(self.initial,self.folder)

    def verify(self): return review(self.rows,self.x,self.origin,self.base,self.anchor,self.conditional,self.folder)

    def rewrite(self,name,obj,field):
        raw=canonical(obj);(self.folder/name).write_bytes(raw)
        run=json.loads((self.folder/'run.json').read_text());run[field]=hashlib.sha256(raw).hexdigest()
        (self.folder/'run.json').write_bytes(canonical(run))

    def test_twenty_two_controls_reconstruct(self):
        result=self.verify()
        self.assertEqual(set(result['scores']['held_out']),set(ALL_ARMS+CORRELATED_ARMS))
        self.assertEqual(result['prediction_rows'],64*22)
        self.assertEqual(result['argmax_reversals'],0)
        self.assertFalse(result['production_authorized'])

    def test_absent_heldout_labels_leave_params_predictions_selection_unchanged(self):
        rows=deepcopy(self.rows)
        for r in rows:
            if phase(r)=='held_out': r.pop('label')
        out=Path(self.case.name)/'hidden'
        execute(rows,self.x,self.origin,self.base,self.anchor,self.conditional,out,profile='paired-full')
        for p in self.initial.glob('*.safetensors'): self.assertEqual(p.read_bytes(),(out/p.name).read_bytes())
        for name in ('predictions.json','selection.json'): self.assertEqual((self.initial/name).read_bytes(),(out/name).read_bytes())

    def test_rehashed_prediction_tampering_refused(self):
        p=json.loads((self.folder/'predictions.json').read_text());p[-1]['logits'][0]+=.1
        self.rewrite('predictions.json',p,'predictions_sha256')
        with self.assertRaises(ValueError): self.verify()

    def test_rehashed_cost_or_covariance_family_refused(self):
        original=json.loads((self.folder/'training.json').read_text())
        for key,val in (('factorization_calls',0),('covariance_matrix_bytes',0),('covariance_family','diagonal')):
            cost=deepcopy(original);cost['arms']['full_memory'][key]=val
            self.rewrite('training.json',cost,'training_sha256')
            with self.subTest(key=key),self.assertRaises(ValueError): self.verify()

    def test_rehashed_profile_downgrade_refused(self):
        p=json.loads((self.folder/'plan.json').read_text());p['covariance_profile']='diagonal'
        self.rewrite('plan.json',p,'plan_sha256')
        with self.assertRaises(ValueError): self.verify()

    def test_no_overwrite_failed_run_or_symlinked_checkpoint(self):
        with self.assertRaises(FileExistsError):
            execute(self.rows,self.x,self.origin,self.base,self.anchor,self.conditional,self.folder,profile='paired-full')
        target=self.folder/'full_prototype_memory.safetensors';target.unlink();target.symlink_to(self.initial/target.name)
        with self.assertRaises(ValueError): self.verify()
        (self.folder/'FAILED.json').write_text('{}')
        with self.assertRaises(ValueError): self.verify()


if __name__=='__main__': unittest.main()
