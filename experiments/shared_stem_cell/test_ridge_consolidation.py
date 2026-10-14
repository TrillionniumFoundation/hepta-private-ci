"""Actual SVD/Head execution, independent normal equations and archive integration."""
from copy import deepcopy
import subprocess
import sys
import unittest
from unittest.mock import patch

import torch

from experiments.shared_stem_cell import consolidation as c, execution as e
from experiments.shared_stem_cell import ridge_consolidation as rg, residual_consolidation as rc


class RidgeTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(123)
        self.x = torch.randn(20, 8)
        self.routes = torch.arange(20) % 2
        self.y = torch.arange(20) % 2
        self.teachers = tuple(e.Head(8, 2, "gated", 4).eval().requires_grad_(False) for _ in range(2))
        self.shared = e.Head(10, 2, "gated", 4).eval().requires_grad_(False)

    def fit(self):
        return rg.fit_ridge(self.teachers, self.shared, self.x[:12], self.routes[:12],
                            self.x[12:], self.routes[12:], self.y[12:])

    def test_independent_regularized_normal_equations(self):
        t, b = torch.randn(20, 2), torch.randn(20, 2)
        heads, report = rg.solve_pair(self.x, t, b)
        z = torch.cat([self.x.double(), torch.ones(20, 1).double()], 1)
        target, base = t.double(), b.double()
        target -= target.mean(-1, keepdim=True); base -= base.mean(-1, keepdim=True)
        y = torch.cat([target-base, target], 1)
        alpha = rg.RHO * z.square().sum() / z.shape[1]
        expected = torch.linalg.solve(z.T @ z + alpha * torch.eye(9).double(), z.T @ y)
        for i, model in enumerate(heads):
            actual = torch.cat([model.base.weight.T, model.base.bias[None]], 0).double()
            self.assertTrue(torch.allclose(actual, expected[:, 2*i:2*i+2], atol=1e-7, rtol=1e-6))
            self.assertLess(report['solutions'][i]['normal_residual_float64'], 1e-10)
        self.assertEqual(report['svd_calls'], 1)

    def test_wide_rank_deficient_and_zero_design_are_finite(self):
        for x in (torch.zeros(4, 8), self.x[:4].repeat(2, 1)):
            heads, report = rg.solve_pair(x, torch.randn(len(x), 2), torch.zeros(len(x), 2))
            self.assertGreater(report['nullity_diagnostic'], 0)
            self.assertTrue(all(torch.isfinite(m(x)).all() for m in heads))
            self.assertGreater(report['alpha'], 0)

    def test_common_logit_shift_cannot_change_solved_head(self):
        t = torch.randint(-5, 6, (20, 2)).float(); b = torch.randint(-5, 6, (20, 2)).float()
        shifts = torch.arange(20).float()[:, None]
        a, _ = rg.solve_pair(self.x, t, b)
        other, _ = rg.solve_pair(self.x, t+shifts, b-2*shifts)
        self.assertEqual([e.parameters(m) for m in a], [e.parameters(m) for m in other])

    def test_row_permutation_preserves_solution_not_svd_vector_sign(self):
        t, b = torch.randn(20, 2), torch.randn(20, 2)
        ids = torch.arange(19, -1, -1)
        a, _ = rg.solve_pair(self.x, t, b); other, _ = rg.solve_pair(self.x[ids], t[ids], b[ids])
        for left, right in zip(a, other):
            self.assertTrue(torch.allclose(left(self.x), right(self.x), atol=1e-6, rtol=1e-6))

    def test_identical_teacher_and_base_give_zero_correction(self):
        t = torch.randn(20, 2)
        heads, _ = rg.solve_pair(self.x, t, t)
        self.assertTrue(torch.equal(heads[0](self.x), torch.zeros(20, 2)))
        heads, _ = rg.solve_pair(self.x, t, torch.zeros_like(t))
        self.assertEqual(e.parameters(heads[0]), e.parameters(heads[1]))

    def test_exactly_one_svd_per_cell_and_no_optimizer(self):
        with patch.object(torch.linalg, 'svd', wraps=torch.linalg.svd) as svd, \
             patch.object(torch.optim, 'AdamW', side_effect=AssertionError('optimizer used')), \
             patch.object(e, 'fit', side_effect=AssertionError('iterative fit used')):
            fitted, receipt = self.fit()
        self.assertEqual(svd.call_count, 2)
        self.assertEqual(receipt['executed_optimizer_steps'], 0)
        self.assertEqual(sum(r['rows'] for r in receipt['solves']), 12)
        self.assertEqual(set(fitted), set(rc.MODES))

    def test_calibration_cannot_change_fitted_parameters(self):
        a, _ = self.fit()
        other, _ = rg.fit_ridge(self.teachers, self.shared, self.x[:12], self.routes[:12],
                                self.x[12:]*5, self.routes[12:], 1-self.y[12:])
        self.assertEqual({k:[e.parameters(m) for m in v] for k,v in a.items()},
                         {k:[e.parameters(m) for m in v] for k,v in other.items()})

    def test_one_teacher_changes_only_its_own_cell_fit(self):
        a, _ = self.fit()
        with torch.no_grad(): self.teachers[1].base.bias.add_(torch.tensor([2., -2.]))
        other, _ = self.fit()
        for mode in rc.MODES:
            self.assertEqual(e.parameters(a[mode][0]), e.parameters(other[mode][0]))
            self.assertNotEqual(e.parameters(a[mode][1]), e.parameters(other[mode][1]))

    def test_sources_rng_and_gradient_graphs_are_unchanged(self):
        identities = [e.parameters(m) for m in (*self.teachers, self.shared)]
        original = self.x.clone(); rng = torch.get_rng_state().clone()
        self.x.requires_grad_(True)
        fitted, receipt = self.fit()
        rc.predict(self.teachers, self.shared, fitted, receipt, self.x, self.routes)
        self.assertTrue(torch.equal(rng, torch.get_rng_state()))
        self.assertTrue(torch.equal(original, self.x)); self.assertIsNone(self.x.grad)
        self.assertEqual(identities, [e.parameters(m) for m in (*self.teachers, self.shared)])

    def test_missing_coverage_and_capacity_fail_before_teacher_or_svd(self):
        with patch.object(c, 'bank_logits') as calls, self.assertRaises(e.InputError):
            rg.fit_ridge(self.teachers, self.shared, self.x[:12], self.routes[:12],
                          self.x[12:], torch.zeros(8, dtype=torch.long), self.y[12:])
        calls.assert_not_called()
        with patch.object(rg, 'workspace_bytes', return_value=c.MAX_BYTES+1), \
             patch.object(c, 'bank_logits') as calls, self.assertRaises(e.InputError):
            self.fit()
        calls.assert_not_called()

    def test_invalid_complete_inputs_reject_before_svd(self):
        for b in (torch.zeros(19, 2), torch.zeros(20, 2).double(), torch.full((20, 2), float('nan'))):
            with patch.object(torch.linalg, 'svd') as solve, self.assertRaises(e.InputError):
                rg.solve_pair(self.x, torch.zeros(20, 2), b)
            solve.assert_not_called()

    def test_bad_numeric_solver_is_not_published(self):
        real = torch.linalg.svd
        def wrong(x, **kwargs):
            u, s, vh = real(x, **kwargs)
            return u, s*2, vh
        with patch.object(torch.linalg, 'svd', wrong), self.assertRaisesRegex(e.InputError, 'stationarity'):
            rg.solve_pair(self.x, torch.randn(20, 2), torch.zeros(20, 2))

    def test_existing_predictor_checks_late_head_and_accounting(self):
        fitted, receipt = self.fit()
        bad = deepcopy(receipt); bad['parameter_counts']['residual_corrected'] -= 1
        with patch.object(c, 'augment') as call, self.assertRaises(e.InputError):
            rc.predict(self.teachers, self.shared, fitted, bad, self.x, self.routes)
        call.assert_not_called()
        with torch.no_grad(): fitted[rc.MODES[1]][-1].base.bias.add_(1)
        with patch.object(c, 'augment') as call, self.assertRaises(e.InputError):
            rc.predict(self.teachers, self.shared, fitted, receipt, self.x, self.routes)
        call.assert_not_called()

    def test_original_study_reloads_heads_and_seals_before_predictions(self):
        from experiments.shared_stem_cell.test_feature_replay import FeatureReplayTests
        from experiments.shared_stem_cell.consolidation_study import study
        fixture = FeatureReplayTests('test_exact_tensor_roundtrip_without_raw_text_or_labels'); fixture.setUp()
        try:
            _, digest = fixture.producer(); out = fixture.root/'ridge-run'
            original = rc.predict; before = {p:p.read_bytes() for p in fixture.root.rglob('*') if p.is_file()}
            def guard(*args):
                if args[3].get('fitting_profile') == 'centered_logit_ridge_v1':
                    self.assertTrue((out/'ridge-selection.json').is_file())
                return original(*args)
            with patch.object(e, 'LocalEncoder') as encoder, patch.object(rc, 'predict', guard):
                result = study(fixture.root/'manifest.json', fixture.root/'producer', digest, out,
                               partial=True, residual=True, ridge=True)
            encoder.assert_not_called()
            self.assertEqual(result['ridge']['svd_calls'], 2)
            self.assertEqual(len(list((out/'ridge-heads').rglob('weights.safetensors'))), 4)
            self.assertTrue(all(p.read_bytes()==value for p,value in before.items()))
            self.assertTrue({'ridge_residual_corrected','ridge_linear_distilled','ridge_selected'} <= set(result['scores']['holdout']))
        finally: fixture.tearDown()

    def test_fresh_process_replays_without_model_dependencies(self):
        from experiments.shared_stem_cell.test_feature_replay import FeatureReplayTests
        fixture = FeatureReplayTests('test_exact_tensor_roundtrip_without_raw_text_or_labels'); fixture.setUp()
        try:
            _, digest = fixture.producer()
            code = """import sys, importlib.abc
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self, fullname, *args):
  if fullname.split('.')[0] in {'transformers','tokenizers','huggingface_hub'}: raise AssertionError(fullname)
sys.meta_path.insert(0,Block())
from pathlib import Path
import torch
from experiments.shared_stem_cell.consolidation_study import study
torch.set_num_threads(1)
r=Path(sys.argv[1]);study(r/'manifest.json',r/'producer',sys.argv[2],r/'fresh-ridge',ridge=True)
"""
            done = subprocess.run([sys.executable,'-c',code,str(fixture.root),digest],capture_output=True,timeout=30)
            self.assertEqual(done.returncode, 0, done.stderr.decode())
        finally: fixture.tearDown()


if __name__ == '__main__':
    unittest.main()
