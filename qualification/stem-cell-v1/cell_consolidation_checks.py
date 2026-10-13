"""Synthetic class-incremental mechanisms, not pretrained or prospective evidence."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import torch
from safetensors.torch import load, save

from cell_consolidation import (ARMS, ConsolidationConfig, fit_consolidation, metrics,
                                outputs, select_retained, training_partition)
from cell_consolidation_study import execute, review_rows, affine_logits
from development_study import prepare_views
from development_study_data import canonical, phase
from development_study_checks import fixture_rows
from development_tensors import parameter_digest


def fixture():
    rows = fixture_rows(32)[:160]
    for i, r in enumerate(rows):
        r.update(label=i % 4, options=['a', 'b', 'c', 'd'])
    rng = torch.Generator().manual_seed(112)
    x = torch.randn(len(rows), 8, generator=rng)*.1
    x[:, :4] += torch.nn.functional.one_hot(torch.tensor([r['label'] for r in rows]), 4)*2
    return rows, x


class ConsolidationChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.threads = torch.get_num_threads()
        torch.set_num_threads(1)
        cls.root = tempfile.TemporaryDirectory()
        cls.config = ConsolidationConfig(classes=4, old_classes=(0, 1), steps=12, memory_per_class=2)
        cls.rows, cls.features = fixture()
        cls.origin = {'fixture_only': True, 'current_encoder_calls': 0}
        cls.initial = Path(cls.root.name) / 'initial'
        execute(cls.rows, cls.features, cls.origin, cls.initial, cls.config)

    @classmethod
    def tearDownClass(cls):
        cls.root.cleanup()
        torch.set_num_threads(cls.threads)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'copy'
        shutil.copytree(self.initial, self.path)

    def rewrite(self, name, obj, field=None):
        raw = canonical(obj)
        (self.path/name).write_bytes(raw)
        if field:
            run = json.loads((self.path/'run.json').read_text())
            run[field] = hashlib.sha256(raw).hexdigest()
            (self.path/'run.json').write_bytes(canonical(run))

    def review(self):
        return review_rows(self.rows, self.features, self.origin, self.path)

    def test_all_six_controls_replay_on_same_inputs(self):
        r = self.review()
        self.assertEqual(set(r['scores']['held_out']), set(ARMS))
        self.assertEqual(r['prediction_rows'], 64*6)
        self.assertEqual(r['unique_held_out_inputs'], 32)
        self.assertEqual(r['argmax_reversals'], 0)
        self.assertFalse(r['production_authorized'])

    def test_held_out_label_permutation_cannot_change_training_or_selection(self):
        altered = deepcopy(self.rows)
        for r in altered:
            if phase(r) == 'held_out':
                r['label'] = (r['label']+1) % 4
        other = Path(self.temp.name)/'permuted'
        execute(altered, self.features, self.origin, other, self.config)
        for name in ('predictions.json', 'normalizer.safetensors', *[f'{a}.safetensors' for a in ARMS[:-1]]):
            self.assertEqual((other/name).read_bytes(), (self.path/name).read_bytes())
        a, b = [json.loads((p/'selection.json').read_text()) for p in (other, self.path)]
        for key in ('selected_arm', 'calibration_floors', 'calibration_metrics', 'partition', 'checkpoints'):
            self.assertEqual(a[key], b[key])

    def test_calibration_labels_never_enter_fitting(self):
        inputs, _ = prepare_views(self.rows)
        truth = {r['sample_id']: r['label'] for r in self.rows if phase(r) in ('base', 'adapt')}
        truth[next(r['sample_id'] for r in self.rows if phase(r) == 'calibration')] = 0
        with self.assertRaises(ValueError):
            fit_consolidation(inputs, truth, self.features, self.config)

    def test_memory_uses_only_old_base_and_distinct_groups(self):
        s = json.loads((self.path/'selection.json').read_text())
        ids = s['partition']['memory']
        self.assertEqual(len(ids), 4)
        self.assertTrue(all(phase(self.rows[i]) == 'base' and self.rows[i]['label'] in (0, 1) for i in ids))
        self.assertEqual(len({self.rows[i]['source_group'] for i in ids}), 4)

    def test_missing_replay_support_does_not_duplicate_rows(self):
        inputs, _ = prepare_views(self.rows)
        truth = {r['sample_id']: r['label'] for r in self.rows if phase(r) in ('base', 'adapt')}
        with self.assertRaises(ValueError):
            training_partition(inputs, truth, replace(self.config, memory_per_class=32))

    def test_config_refuses_bool_nan_bad_partition_or_budget(self):
        for args in ({'steps': True}, {'steps': 1001}, {'temperature': float('nan')},
                     {'old_classes': (1, 1)}, {'old_classes': (0, 4)}, {'memory_per_class': 0}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                replace(self.config, **args).validate()

    def test_training_does_not_change_inputs_or_rng(self):
        inputs, _ = prepare_views(self.rows)
        truth = {r['sample_id']: r['label'] for r in self.rows if phase(r) in ('base', 'adapt')}
        before, rng = self.features.clone(), torch.get_rng_state().clone()
        models, _, _, costs, _ = fit_consolidation(inputs, truth, self.features, self.config)
        self.assertTrue(torch.equal(self.features, before))
        self.assertTrue(torch.equal(torch.get_rng_state(), rng))
        self.assertNotEqual(parameter_digest(models['frozen']), parameter_digest(models['new_only']))
        self.assertEqual(costs['label_replay']['sample_presentations'], costs['distilled']['sample_presentations'])
        self.assertEqual(costs['label_replay']['old_replay_rows'], costs['distilled']['old_replay_rows'])

    def test_nonfinite_features_rejected(self):
        x = self.features.clone(); x[0, 0] = float('nan')
        with self.assertRaises(ValueError):
            execute(self.rows, x, self.origin, Path(self.temp.name)/'bad', self.config)
        self.assertTrue((Path(self.temp.name)/'bad/FAILED.json').exists())

    def test_create_only_outputs_and_failed_runs(self):
        with self.assertRaises(FileExistsError):
            execute(self.rows, self.features, self.origin, self.path, self.config)
        (self.path/'FAILED.json').write_text('{}')
        with self.assertRaises(ValueError):
            self.review()

    def test_rehashed_false_predictions_fail_formula_replay(self):
        p = json.loads((self.path/'predictions.json').read_text())
        p[0]['logits'][0] += .25
        self.rewrite('predictions.json', p, 'predictions_sha256')
        with self.assertRaises(ValueError): self.review()

    def test_duplicate_or_missing_predictions_fail(self):
        p = json.loads((self.path/'predictions.json').read_text())
        p[-1] = p[0]
        self.rewrite('predictions.json', p, 'predictions_sha256')
        with self.assertRaises(ValueError): self.review()

    def test_held_out_truth_field_in_prediction_refused(self):
        p = json.loads((self.path/'predictions.json').read_text())
        p[0]['label'] = 0
        self.rewrite('predictions.json', p, 'predictions_sha256')
        with self.assertRaises(ValueError): self.review()

    def test_rehashed_normalizer_cannot_include_test_data(self):
        raw = save({'mean': self.features.mean(0), 'scale': self.features.std(0, unbiased=False)})
        (self.path/'normalizer.safetensors').write_bytes(raw)
        s = json.loads((self.path/'selection.json').read_text())
        s['normalizer_sha256'] = hashlib.sha256(raw).hexdigest()
        self.rewrite('selection.json', s, 'selection_sha256')
        with self.assertRaises(ValueError): self.review()

    def test_checkpoint_changes_and_path_escape_refused(self):
        s = json.loads((self.path/'selection.json').read_text())
        s['checkpoints']['../escape'] = s['checkpoints'].pop('distilled')
        self.rewrite('selection.json', s, 'selection_sha256')
        with self.assertRaises(ValueError): self.review()

    def test_rehashed_winner_and_cost_changes_refused(self):
        s = json.loads((self.path/'selection.json').read_text())
        s['selected_arm'] = 'not-an-arm'
        self.rewrite('selection.json', s, 'selection_sha256')
        with self.assertRaises(ValueError): self.review()
        s = json.loads((self.initial/'selection.json').read_text())
        s['costs']['single_head_weight_bytes'] = 0
        self.rewrite('selection.json', s, 'selection_sha256')
        with self.assertRaises(ValueError): self.review()

    def test_changed_origin_and_fresh_encoder_claim_refused(self):
        with self.assertRaises(ValueError):
            review_rows(self.rows, self.features, {'different': True}, self.path)
        r = json.loads((self.path/'run.json').read_text()); r['current_encoder_calls'] = 1
        self.rewrite('run.json', r)
        with self.assertRaises(ValueError): self.review()

    def test_independent_affine_rejects_unexpected_tensors(self):
        t = load((self.path/'frozen.safetensors').read_bytes()); t['extra'] = torch.ones(1)
        with self.assertRaises(ValueError): affine_logits(t, self.features, 4)

    def test_supported_consolidation_can_pass_not_reject_all(self):
        y = torch.tensor([0, 1, 2, 3]*4)
        full = torch.nn.functional.one_hot(y, 4).float()*9
        old = full.clone(); old[y >= 2] = torch.tensor([9., 0., 0., 0.])
        groups = [str(i) for i in range(len(y))]
        scores = {n: metrics(old if n == 'frozen' else full, y, groups, self.config) for n in ARMS}
        self.assertNotEqual(select_retained(scores, self.config)['selected_arm'], 'frozen')

    def test_overall_gain_cannot_hide_one_old_class_regression(self):
        y = torch.tensor([0, 1, 2, 3]*4)
        old = torch.nn.functional.one_hot(y, 4).float()*9; old[y >= 2] = torch.tensor([9., 0., 0., 0.])
        candidate = torch.nn.functional.one_hot(y, 4).float()*9; candidate[0] = torch.tensor([0., 9., 0., 0.])
        groups = [str(i) for i in range(len(y))]
        scores = {n: metrics(old if n == 'frozen' else candidate, y, groups, self.config) for n in ARMS}
        self.assertEqual(select_retained(scores, self.config)['selected_arm'], 'frozen')

    def test_group_duplication_does_not_create_support(self):
        y = torch.tensor([0, 1, 2, 3])
        logits = torch.nn.functional.one_hot(y, 4).float()*2
        a = metrics(logits, y, list('abcd'), self.config)
        b = metrics(logits.repeat(3, 1), y.repeat(3), list('abcd')*3, self.config)
        self.assertEqual(a, b)


if __name__ == '__main__':
    unittest.main()
