"""Actual independent-teacher distillation and offline producer integration."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch
from torch.nn import functional as F

from experiments.shared_stem_cell import consolidation as c, consolidation_study as s, execution as e


class ConsolidationTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(47)
        self.x = torch.randn(16, 8)
        self.r = torch.arange(16) % 2
        self.y = ((self.x[:, 0] > 0).long() ^ self.r)
        self.teachers = tuple(e.Head(8, 2, 'gated', 4).eval().requires_grad_(False) for _ in range(2))

    def fit(self, **kwargs):
        return c.fit_students(self.teachers, self.x[:12], self.r[:12], self.y[:12],
                              self.x[12:], self.r[12:], self.y[12:], steps=3, **kwargs)

    def test_each_row_uses_its_own_teacher_not_average(self):
        with torch.no_grad():
            for i, t in enumerate(self.teachers):
                for p in t.parameters(): p.zero_()
                t.base.bias[i] = 4.0
        actual = c.bank_logits(self.teachers, self.x, self.r)
        self.assertEqual(actual.argmax(-1).tolist(), self.r.tolist())
        self.assertTrue(torch.equal(c.bank_logits(self.teachers, self.x.flip(0), self.r.flip(0)), actual.flip(0)))
        self.assertFalse(torch.equal(actual, actual.mean(0).expand_as(actual)))

    def test_identical_features_keep_distinct_observed_cell_identity(self):
        x = torch.zeros(2, 8); routes = torch.tensor([0, 1])
        z = c.augment(x, routes, 2)
        self.assertTrue(torch.equal(z[:, :8], x))
        self.assertTrue(torch.equal(z[:, 8:], torch.eye(2)))

    def test_actual_three_equal_budget_objectives(self):
        count = 0
        original = torch.optim.AdamW.step
        def counted(optimizer, *args, **kwargs):
            nonlocal count
            count += 1
            return original(optimizer, *args, **kwargs)
        with patch.object(torch.optim.AdamW, 'step', counted):
            models, receipt = self.fit()
        self.assertEqual(count, 9)
        self.assertEqual(receipt['executed_student_steps'], 9)
        self.assertEqual(len({v['minibatch_sha256'] for v in receipt['training'].values()}), 1)
        self.assertEqual(len({v['parameters'] for v in receipt['training'].values()}), 1)
        self.assertEqual(set(models), {'shared_frozen', *c.STUDENTS})
        self.assertEqual(receipt['teacher_target_generation']['rows'], 12)
        self.assertEqual(receipt['teacher_target_generation']['forward_calls'], 2)

    def test_zero_soft_weight_is_exact_original_supervision(self):
        model = e.Head(8, 2, 'gated', 4)
        targets = torch.tensor([[0.2, 0.8]]).expand(16, 2)
        a, ac = e.fit(model, self.x, self.y, steps=4)
        b, bc = e.fit(model, self.x, self.y, steps=4, soft_targets=targets, soft_weight=0.0)
        self.assertEqual(e.parameters(a), e.parameters(b))
        self.assertEqual(ac['minibatch_sha256'], bc['minibatch_sha256'])

    def test_pure_kl_ignores_hard_labels_and_detaches_teacher(self):
        model = e.Head(8, 2, 'linear', 4)
        target = torch.full((16, 2), 0.5, requires_grad=True)
        a, _ = e.fit(model, self.x, self.y, steps=2, soft_targets=target, soft_weight=1.0)
        b, _ = e.fit(model, self.x, 1-self.y, steps=2, soft_targets=target, soft_weight=1.0)
        self.assertEqual(e.parameters(a), e.parameters(b))
        self.assertIsNone(target.grad)

    def test_temperature_batchmean_kl_matches_manual_update(self):
        model = e.Head(8, 2, 'linear', 4)
        q = torch.softmax(torch.randn(16, 2)/2, -1)
        expected = deepcopy(model)
        opt = torch.optim.AdamW(expected.parameters(), lr=0.01, weight_decay=0)
        ids = torch.randint(16, (16,), generator=torch.Generator().manual_seed(17))
        loss = F.kl_div((expected(self.x[ids])/2).log_softmax(-1), q[ids], reduction='batchmean') * 4
        loss.backward(); torch.nn.utils.clip_grad_norm_(expected.parameters(), 1.0); opt.step()
        actual, _ = e.fit(model, self.x, self.y, steps=1, soft_targets=q, soft_weight=1)
        self.assertEqual(e.parameters(actual), e.parameters(expected))

    def test_invalid_soft_targets_precede_optimizer(self):
        model = e.Head(8, 2, 'linear', 4)
        for bad in (torch.ones(16, 2), torch.full((16, 2), float('nan')), torch.ones(15, 2)/2):
            with patch.object(torch.optim, 'AdamW') as opt, self.assertRaises(e.InputError):
                e.fit(model, self.x, self.y, soft_targets=bad, soft_weight=1)
            opt.assert_not_called()
        for args in ({'soft_weight': 0.5}, {'temperature': float('nan')}, {'soft_weight': True}):
            with patch.object(torch.optim, 'AdamW') as opt, self.assertRaises(e.InputError):
                e.fit(model, self.x, self.y, **args)
            opt.assert_not_called()

    def test_calibration_coverage_and_labels_precede_teacher_forward(self):
        for routes, y in ((torch.zeros(4, dtype=torch.long), self.y[12:]),
                          (self.r[12:], torch.full((4,), 8, dtype=torch.long))):
            with patch.object(c, 'bank_logits') as forward, self.assertRaises(e.InputError):
                c.fit_students(self.teachers, self.x[:12], self.r[:12], self.y[:12],
                               self.x[12:], routes, y, steps=2)
            forward.assert_not_called()

    def test_budget_preflight_rejects_before_one_hot(self):
        with patch.object(c, 'MAX_BYTES', 16), patch.object(c, 'augment') as aug, self.assertRaises(e.InputError):
            self.fit()
        aug.assert_not_called()

    def test_caller_rng_features_and_teachers_are_unchanged(self):
        rng = torch.get_rng_state().clone(); x = self.x.clone(); ids = [e.parameters(m) for m in self.teachers]
        models, rec = self.fit()
        self.assertTrue(torch.equal(rng, torch.get_rng_state()))
        self.assertTrue(torch.equal(x, self.x))
        self.assertEqual(ids, [e.parameters(m) for m in self.teachers])
        self.assertTrue(all(not m.training and all(not p.requires_grad for p in m.parameters()) for m in models.values()))
        c.predict(self.teachers, models, rec, self.x, self.r)
        self.assertEqual(ids, [e.parameters(m) for m in self.teachers])

    def test_selection_preserves_bank_per_cell_calibration_floor(self):
        _, rec = self.fit()
        floors = rec['calibration_scores']['bank']['per_cell']
        for name in rec['eligible']:
            self.assertTrue(all(a['correct'] >= b['correct'] for a,b in
                                zip(rec['calibration_scores'][name]['per_cell'], floors)))
        expected = min(rec['eligible'], key=lambda k: (-rec['calibration_scores'][k]['correct'],
                       rec['parameter_counts'][k], rec['calibration_scores'][k]['nll'], k))
        self.assertEqual(expected, rec['selected'])
        self.assertFalse(rec['production_accepted'])

    def test_calibration_changes_do_not_change_training(self):
        models, _ = self.fit()
        other, _ = c.fit_students(self.teachers, self.x[:12], self.r[:12], self.y[:12],
                                  self.x[12:]*2, self.r[12:], 1-self.y[12:], steps=3)
        self.assertEqual({k:e.parameters(v) for k,v in models.items()}, {k:e.parameters(v) for k,v in other.items()})

    def test_changed_model_and_invalid_late_route_rejected(self):
        models, rec = self.fit()
        with torch.no_grad(): models['mixed'].base.bias.add_(1)
        with self.assertRaises(e.InputError): c.predict(self.teachers, models, rec, self.x, self.r)
        bad = self.r.clone(); bad[-1] = 2
        with patch.object(c, 'augment') as aug, self.assertRaises(e.InputError):
            c.predict(self.teachers, models, rec, self.x, bad)
        aug.assert_not_called()

    def test_actual_producer_to_consolidation_seals_before_heldout(self):
        from experiments.shared_stem_cell.test_feature_replay import FeatureReplayTests
        fixture = FeatureReplayTests('test_exact_tensor_roundtrip_without_raw_text_or_labels')
        fixture.setUp()
        try:
            _, digest = fixture.producer()
            source_before = {p: p.read_bytes() for p in fixture.root.rglob('*') if p.is_file()}
            output = fixture.root/'consolidation'
            original = c.predict
            def guarded(teachers, models, receipt, x, routes):
                self.assertTrue((output/'selection.json').is_file())
                return original(teachers, models, receipt, x, routes)
            with patch.object(c, 'predict', guarded), patch.object(e, 'LocalEncoder') as encoder:
                result = s.study(fixture.root/'manifest.json', fixture.root/'producer', digest, output)
            encoder.assert_not_called()
            self.assertEqual(set(result['scores']['holdout']), set(c.ARMS))
            self.assertEqual(result['encoder_calls'], 0)
            self.assertTrue(result['source_simulated_encoder'])
            self.assertFalse(result['new_holdout'])
            self.assertTrue(all(p.read_bytes() == raw for p,raw in source_before.items()))
            for name in ('selection.json', 'predictions.json', 'report.json'):
                self.assertTrue((output/name).is_file())
        finally:
            fixture.tearDown()

    def test_fresh_process_never_imports_model_dependencies(self):
        import subprocess
        import sys
        from experiments.shared_stem_cell.test_feature_replay import FeatureReplayTests
        fixture = FeatureReplayTests('test_exact_tensor_roundtrip_without_raw_text_or_labels')
        fixture.setUp()
        try:
            _, digest = fixture.producer()
            code = """import sys, importlib.abc
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self, fullname, *args):
  if fullname.split('.')[0] in {'transformers','tokenizers','huggingface_hub'}:
   raise AssertionError('consolidation imported a model dependency')
sys.meta_path.insert(0, Block())
from pathlib import Path
import torch
from experiments.shared_stem_cell.consolidation_study import study
torch.set_num_threads(1)
root=Path(sys.argv[1])
study(root/'manifest.json',root/'producer',sys.argv[2],root/'fresh')
"""
            result = subprocess.run([sys.executable, '-c', code, str(fixture.root), digest],
                                    capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            report = e.decode((fixture.root/'fresh/report.json').read_bytes())
            self.assertEqual(report['encoder_calls'], 0)
        finally:
            fixture.tearDown()

    def test_serialized_route_profile_or_claim_drift_rejected(self):
        models, receipt = self.fit()
        for field, value in (('production_accepted', True), ('selected', 'unknown'),
                             ('route_profile', {'kind': 'averaged_teachers'})):
            changed = deepcopy(receipt); changed[field] = value
            with patch.object(c, 'augment') as aug, self.assertRaises(e.InputError):
                c.predict(self.teachers, models, changed, self.x, self.r)
            aug.assert_not_called()

    def test_wrong_external_producer_hash_fails_before_fitting(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root/'manifest.json').write_text('{}'); (root/'report.json').write_text('{}')
            with patch.object(c, 'fit_students') as train, self.assertRaises(e.InputError):
                s.study(root/'manifest.json', root, '0'*64, root/'result')
            train.assert_not_called()


if __name__ == '__main__':
    unittest.main()
