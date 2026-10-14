"""Actual additive learning, independent Cell targets and saved-candidate replay."""
from copy import deepcopy
import subprocess
import sys
import unittest
from unittest.mock import patch

import torch
from torch.nn import functional as F

from experiments.shared_stem_cell import consolidation as c, execution as e, residual_consolidation as rc


class ResidualTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(137)
        self.x = torch.randn(20, 8)
        self.r = torch.arange(20) % 2
        self.y = (self.x[:, 0] > 0).long()
        self.teachers = tuple(e.Head(8, 2, 'gated', 4).eval().requires_grad_(False) for _ in range(2))
        self.shared = e.Head(10, 2, 'gated', 4).eval().requires_grad_(False)

    def fit(self, **kw):
        return rc.fit_residuals(self.teachers, self.shared, self.x[:12], self.r[:12], self.y[:12],
                               self.x[12:], self.r[12:], self.y[12:], steps=3, **kw)

    def test_additive_kl_matches_manual_adamw_and_detaches_baseline(self):
        initial = e.Head(8, 2, 'linear', 4)
        baseline = torch.randn(20, 2, requires_grad=True)
        target = torch.randn(20, 2).softmax(-1).requires_grad_(True)
        expected = deepcopy(initial)
        opt = torch.optim.AdamW(expected.parameters(), lr=0.01, weight_decay=0)
        ids = torch.randint(20, (16,), generator=torch.Generator().manual_seed(17))
        p = expected(self.x[ids]) + baseline[ids].detach()
        loss = F.kl_div((p/2).log_softmax(-1), target[ids].detach(), reduction='batchmean')*4
        loss.backward(); torch.nn.utils.clip_grad_norm_(expected.parameters(), 1.0); opt.step()
        actual, _ = e.fit(initial, self.x, self.y, steps=1, soft_targets=target, soft_weight=1, base_logits=baseline)
        self.assertEqual(e.parameters(actual), e.parameters(expected))
        self.assertIsNone(baseline.grad); self.assertIsNone(target.grad)

    def test_none_offset_preserves_original_fitter(self):
        initial = e.Head(8, 2, 'gated', 4)
        a, ac = e.fit(initial, self.x, self.y, steps=3)
        b, bc = e.fit(initial, self.x, self.y, steps=3, base_logits=None)
        self.assertEqual(e.parameters(a), e.parameters(b))
        self.assertEqual(ac['minibatch_sha256'], bc['minibatch_sha256'])

    def test_invalid_baseline_precedes_optimizer(self):
        initial = e.Head(8, 2, 'linear', 4)
        for value in (torch.zeros(19, 2), torch.zeros(20, 3), torch.zeros(20, 2).double(),
                      torch.full((20, 2), float('nan')), ['not a tensor']):
            with patch.object(torch.optim, 'AdamW') as opt, self.assertRaises(e.InputError):
                e.fit(initial, self.x, self.y, base_logits=value)
            opt.assert_not_called()

    def test_zero_corrections_exactly_preserve_shared_function(self):
        corrections = tuple(e.Head(8, 2, 'linear', 4).eval() for _ in range(2))
        with torch.no_grad():
            for m in corrections:
                for p in m.parameters(): p.zero_()
            expected = self.shared(c.augment(self.x, self.r, 2))
        actual, calls = rc.corrected_logits(self.shared, corrections, self.x, self.r, 2)
        self.assertTrue(torch.equal(actual, expected))
        self.assertEqual(len(calls), 3)
        self.assertEqual(sum(len(v['rows']) for v in calls), 40)

    def test_actual_optimizer_work_and_paired_sample_streams(self):
        count = 0; original = torch.optim.AdamW.step
        def counted(opt, *a, **kw):
            nonlocal count
            count += 1
            return original(opt, *a, **kw)
        with patch.object(torch.optim.AdamW, 'step', counted):
            _, receipt = self.fit()
        self.assertEqual(count, 12)
        self.assertEqual(receipt['executed_optimizer_steps'], count)
        for a, b in zip(*(receipt['training'][m] for m in rc.MODES)):
            self.assertEqual(a['minibatch_sha256'], b['minibatch_sha256'])
            self.assertEqual(a['parameters'], b['parameters'])

    def test_teacher_shared_rng_and_inputs_immutable(self):
        ids = [e.parameters(m) for m in (*self.teachers, self.shared)]
        before_x = self.x.clone(); rng = torch.get_rng_state().clone()
        fitted, receipt = self.fit()
        rc.predict(self.teachers, self.shared, fitted, receipt, self.x, self.r)
        self.assertEqual(ids, [e.parameters(m) for m in (*self.teachers, self.shared)])
        self.assertTrue(torch.equal(self.x, before_x))
        self.assertTrue(torch.equal(torch.get_rng_state(), rng))

    def test_calibration_changes_do_not_change_fitted_parameters(self):
        fitted, _ = self.fit()
        other, _ = rc.fit_residuals(self.teachers, self.shared, self.x[:12], self.r[:12], self.y[:12],
                                   self.x[12:]*3, self.r[12:], 1-self.y[12:], steps=3)
        self.assertEqual({k:[e.parameters(m) for m in v] for k,v in fitted.items()},
                         {k:[e.parameters(m) for m in v] for k,v in other.items()})

    def test_pure_distillation_ignores_training_hard_labels(self):
        fitted, _ = self.fit()
        other, _ = rc.fit_residuals(self.teachers, self.shared, self.x[:12], self.r[:12], 1-self.y[:12],
                                   self.x[12:], self.r[12:], self.y[12:], steps=3)
        self.assertEqual({k:[e.parameters(m) for m in v] for k,v in fitted.items()},
                         {k:[e.parameters(m) for m in v] for k,v in other.items()})

    def test_changing_one_teacher_only_changes_its_correction(self):
        fitted, _ = self.fit()
        with torch.no_grad(): self.teachers[1].base.bias.add_(torch.tensor([4., -4.]))
        other, _ = self.fit()
        for mode in rc.MODES:
            self.assertEqual(e.parameters(fitted[mode][0]), e.parameters(other[mode][0]))
            self.assertNotEqual(e.parameters(fitted[mode][1]), e.parameters(other[mode][1]))

    def test_missing_coverage_and_budget_reject_before_teacher_calls(self):
        with patch.object(c, 'bank_logits') as calls, self.assertRaises(e.InputError):
            rc.fit_residuals(self.teachers, self.shared, self.x[:12], self.r[:12], self.y[:12],
                            self.x[12:], torch.zeros(8, dtype=torch.long), self.y[12:], steps=3)
        calls.assert_not_called()
        with patch.object(c, 'MAX_BYTES', 1), patch.object(c, 'bank_logits') as calls, self.assertRaises(e.InputError):
            self.fit()
        calls.assert_not_called()

    def test_receipt_and_late_head_drift_rejected_before_any_inference(self):
        fitted, receipt = self.fit()
        for field, value in (('parameter_counts', {}), ('production_accepted', True), ('selected', 'missing')):
            bad = deepcopy(receipt); bad[field] = value
            with patch.object(c, 'augment') as aug, self.assertRaises(e.InputError):
                rc.predict(self.teachers, self.shared, fitted, bad, self.x, self.r)
            aug.assert_not_called()
        with torch.no_grad(): fitted['linear_distilled'][-1].base.bias.add_(1)
        with patch.object(c, 'augment') as aug, self.assertRaises(e.InputError):
            rc.predict(self.teachers, self.shared, fitted, receipt, self.x, self.r)
        aug.assert_not_called()

    def test_exact_correction_forward_counts_not_hidden_teacher_fallback(self):
        fitted, receipt = self.fit()
        counts = {}; hooks = []
        for name, model in [('shared', self.shared), *[(f'cell-{i}', m) for i,m in enumerate(fitted[rc.MODES[0]])]]:
            def hook(m, inputs, output, key=name): counts[key] = len(inputs[0])
            hooks.append(model.register_forward_hook(hook))
        with patch.object(c, 'bank_logits', side_effect=AssertionError('hidden bank')):
            _, calls = rc.corrected_logits(self.shared, fitted[rc.MODES[0]], self.x, self.r, 2)
        for h in hooks: h.remove()
        self.assertEqual(counts, {'shared':20, 'cell-0':10, 'cell-1':10})
        self.assertEqual(sum(len(v['rows']) for v in calls), 40)
        output = rc.predict(self.teachers, self.shared, fitted, receipt, self.x, self.r)
        self.assertEqual(output['inference_costs']['residual_corrected']['head_rows_processed'],40)

    def test_calibration_selection_must_pass_all_cell_floor_and_charge_shared(self):
        _, rec = self.fit()
        self.assertEqual(rec['parameter_counts']['residual_corrected'], rec['parameter_counts']['shared']+36)
        for k in rec['eligible']:
            self.assertTrue(all(a['correct'] >= b['correct'] for a,b in
                zip(rec['calibration_scores'][k]['per_cell'],rec['calibration_scores']['bank']['per_cell'])))
        self.assertFalse(rec['retention_certified'])

    def test_existing_study_exports_reopens_and_seals_before_prediction(self):
        from experiments.shared_stem_cell.test_feature_replay import FeatureReplayTests
        from experiments.shared_stem_cell.consolidation_study import study
        fixture = FeatureReplayTests('test_exact_tensor_roundtrip_without_raw_text_or_labels'); fixture.setUp()
        try:
            _, digest = fixture.producer(); out = fixture.root/'correction'
            before = {p:p.read_bytes() for p in fixture.root.rglob('*') if p.is_file()}
            original = rc.predict
            def guarded(*args):
                self.assertTrue((out/'residual-selection.json').is_file())
                return original(*args)
            with patch.object(rc, 'predict', guarded), patch.object(e, 'LocalEncoder') as encoder:
                result = study(fixture.root/'manifest.json',fixture.root/'producer',digest,out,partial=True,residual=True)
            encoder.assert_not_called()
            self.assertEqual(result['encoder_calls'],0)
            self.assertEqual(len(list((out/'residual-heads').rglob('weights.safetensors'))),4)
            self.assertTrue(all(p.read_bytes()==raw for p,raw in before.items()))
            self.assertTrue(set(rc.MODES)<=set(result['scores']['holdout']))
        finally: fixture.tearDown()

    def test_fresh_process_uses_no_encoder_dependencies(self):
        from experiments.shared_stem_cell.test_feature_replay import FeatureReplayTests
        fixture = FeatureReplayTests('test_exact_tensor_roundtrip_without_raw_text_or_labels'); fixture.setUp()
        try:
            _, digest = fixture.producer()
            code = """import sys, importlib.abc
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self, fullname, *args):
  if fullname.split('.')[0] in {'transformers','tokenizers','huggingface_hub'}:
   raise AssertionError('unexpected Encoder dependency')
sys.meta_path.insert(0,Block())
from pathlib import Path
import torch
from experiments.shared_stem_cell.consolidation_study import study
torch.set_num_threads(1)
r=Path(sys.argv[1]);study(r/'manifest.json',r/'producer',sys.argv[2],r/'fresh-residual',residual=True)
"""
            done = subprocess.run([sys.executable,'-c',code,str(fixture.root),digest],capture_output=True,timeout=30)
            self.assertEqual(done.returncode,0,done.stderr.decode())
        finally: fixture.tearDown()


if __name__ == '__main__':
    unittest.main()
