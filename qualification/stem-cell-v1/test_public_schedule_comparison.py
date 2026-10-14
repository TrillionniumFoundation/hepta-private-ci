import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import torch

from matrix_materials import file_sha256
from matrix_runtime import write_json_exclusive
from public_schedule_comparison import compare_schedules
from shared_learning_probe import fit_controls, freeze_study, score_sealed


class Encoder:
    def __init__(self):
        self.calls = 0

    def __call__(self, row):
        self.calls += 1
        value = int(row['state'].rsplit(' ', 1)[-1])
        with torch.inference_mode():
            x = torch.zeros(4, dtype=torch.float32)
            x[value] = 1.
        return x, 8


def rows(split):
    return [dict(sample_id=f'{split}:{i}', state=f'{split} class {i}',
                 question='Choose the topic.', options=['World','Sports','Business','Science'])
            for i in range(4)]


def build_experiment(root, study, *, snapshot='a'*64, material='b'*64):
    root = Path(root)
    root.mkdir()
    train, evaluation, labels = rows('train'), rows('eval'), [0, 1, 2, 3]
    marker = fit_controls(Encoder(), train, labels, evaluation, root/'controls',
                          dimension=4, study=study)
    score = score_sealed(root/'controls', labels, expected_seal_id=marker['seal_id'])
    score.update(model_snapshot_sha256=snapshot, selected_material_id=material)
    selection = dict(schema='test.selection.v1', train=[r['sample_id'] for r in train],
                     evaluation=[r['sample_id'] for r in evaluation])
    write_json_exclusive(root/'STUDY.json', study)
    write_json_exclusive(root/'selection.json', selection)
    write_json_exclusive(root/'source_files.json', {'test': 'c'*64})
    write_json_exclusive(root/'scores.json', score)
    write_json_exclusive(root/'COMMITTED.json', dict(seal_id=marker['seal_id'], files={
        name: file_sha256(root/name)
        for name in ('scores.json', 'selection.json', 'STUDY.json', 'source_files.json')}))
    return marker['seal_id'], labels


class PublicScheduleComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        base = Path(cls.tmp.name)
        cls.fixed_study = freeze_study(train_steps=3, batch_size=4, width_units=3)
        cls.budget_study = freeze_study(train_steps=3, batch_size=4, width_units=3,
                                        training_flops_budget=500_000, max_budget_steps=32)
        cls.fixed_seal, cls.labels = build_experiment(base/'fixed', cls.fixed_study)
        cls.budget_seal, _ = build_experiment(base/'budget', cls.budget_study)
        cls.base = base

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(self.base/'fixed', self.root/'fixed')
        shutil.copytree(self.base/'budget', self.root/'budget')

    def compare(self, labels=None):
        return compare_schedules(self.root/'fixed', self.root/'budget',
                                 self.labels if labels is None else labels,
                                 expected_fixed_seal_id=self.fixed_seal,
                                 expected_budget_seal_id=self.budget_seal)

    def test_actual_fixed_and_budget_training_are_paired_without_selection(self):
        report = self.compare()
        self.assertEqual(report['schema'], 'hepta.public-schedule-comparison.v1')
        self.assertEqual([a['topology'] for a in report['arms']], ['dense16', 'sparse16', 'direct32'])
        self.assertEqual([a['fixed_training']['steps'] for a in report['arms']], [3, 3, 3])
        self.assertTrue(all(a['budget_training']['steps'] >= 1 for a in report['arms']))
        self.assertTrue(all(a['paired_quality']['overall']['rows'] == 4 for a in report['arms']))
        self.assertFalse(report['causal_topology_effect_identified'])
        self.assertFalse(report['statistical_superiority_established'])

    def test_same_labels_rescore_both_without_any_training(self):
        with patch('shared_learning_probe.train_bank', side_effect=AssertionError('no training')), \
             patch('budgeted_learning.train_to_budget', side_effect=AssertionError('no training')):
            a = self.compare()
            b = self.compare([3, 2, 1, 0])
        self.assertNotEqual(a['labels_sha256'], b['labels_sha256'])
        self.assertEqual([x['fixed_training'] for x in a['arms']],
                         [x['fixed_training'] for x in b['arms']])

    def test_different_selection_feature_labels_or_snapshot_reject(self):
        for case in ('selection', 'feature', 'training_labels', 'snapshot', 'material'):
            with self.subTest(case=case):
                shutil.rmtree(self.root/'budget')
                shutil.copytree(self.base/'budget', self.root/'budget')
                if case == 'selection':
                    p = self.root/'budget'/'selection.json'
                    data = json.loads(p.read_text())
                    data['evaluation'].reverse()
                    p.write_text(json.dumps(data))
                    self.reseal_top('budget')
                elif case in ('feature', 'training_labels'):
                    p = self.root/'budget'/'controls'/'predictions.json'
                    data = json.loads(p.read_text())
                    key = 'feature_sha256' if case == 'feature' else 'training_labels_sha256'
                    data[key] = ['x'] if case == 'feature' else 'd'*64
                    p.write_text(json.dumps(data))
                    self.reseal_controls_and_top('budget')
                else:
                    p = self.root/'budget'/'scores.json'
                    data = json.loads(p.read_text())
                    data['model_snapshot_sha256' if case == 'snapshot' else 'selected_material_id'] = 'e'*64
                    p.write_text(json.dumps(data))
                    self.reseal_top('budget')
                with self.assertRaises(ValueError):
                    self.compare()

    def reseal_top(self, name):
        root = self.root/name
        marker = json.loads((root/'COMMITTED.json').read_text())
        marker['files'] = {n: file_sha256(root/n)
                           for n in ('scores.json', 'selection.json', 'STUDY.json', 'source_files.json')}
        (root/'COMMITTED.json').write_text(json.dumps(marker))

    def reseal_controls_and_top(self, name):
        root = self.root/name
        controls = root/'controls'
        marker = json.loads((controls/'COMMITTED.json').read_text())
        marker['predictions_sha256'] = file_sha256(controls/'predictions.json')
        from next_round_matrix import _digest
        marker['seal_id'] = _digest({k: v for k, v in marker.items() if k != 'seal_id'})
        (controls/'COMMITTED.json').write_text(json.dumps(marker))
        top = json.loads((root/'COMMITTED.json').read_text())
        top['seal_id'] = marker['seal_id']
        top['files'] = {n: file_sha256(root/n)
                        for n in ('scores.json', 'selection.json', 'STUDY.json', 'source_files.json')}
        (root/'COMMITTED.json').write_text(json.dumps(top))

    def test_wrong_external_seal_rejects_before_scoring(self):
        with self.assertRaises(ValueError):
            compare_schedules(self.root/'fixed', self.root/'budget', self.labels,
                              expected_fixed_seal_id='0'*64,
                              expected_budget_seal_id=self.budget_seal)

    def test_non_schedule_control_change_rejects_even_when_study_rehashed(self):
        p = self.root/'budget'/'STUDY.json'
        study = json.loads(p.read_text())
        study['batch_size'] = 2
        from next_round_matrix import _digest
        study['study_id'] = _digest({k: v for k, v in study.items() if k != 'study_id'})
        p.write_text(json.dumps(study))
        self.reseal_top('budget')
        with self.assertRaises(ValueError):
            self.compare()

    def test_mutated_bank_or_predictions_reject(self):
        for rel in ('controls/dense16/bank.safetensors', 'controls/predictions.json'):
            with self.subTest(rel=rel):
                shutil.rmtree(self.root/'fixed')
                shutil.copytree(self.base/'fixed', self.root/'fixed')
                p = self.root/'fixed'/rel
                p.write_bytes(p.read_bytes()+b' ')
                with self.assertRaises(ValueError):
                    self.compare()

    def test_failed_arm_is_retained_as_unavailable_not_zero_quality(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name, study in (('fixed', self.fixed_study), ('budget', self.budget_study)):
                with patch('shared_learning_probe.train_bank', side_effect=RuntimeError('fail')), \
                     patch('budgeted_learning.train_to_budget', side_effect=RuntimeError('fail')):
                    seal, _ = build_experiment(root/name, study)
                if name == 'fixed':
                    fixed = seal
                else:
                    budget = seal
            report = compare_schedules(root/'fixed', root/'budget', self.labels,
                                       expected_fixed_seal_id=fixed,
                                       expected_budget_seal_id=budget)
            self.assertTrue(all(a['fixed_accuracy'] is None and a['budget_accuracy'] is None
                                for a in report['arms']))
            self.assertTrue(all(a['paired_quality']['status'] == 'unavailable_failed_arm'
                                for a in report['arms']))


if __name__ == '__main__':
    unittest.main()
