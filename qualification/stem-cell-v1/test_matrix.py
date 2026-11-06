"""No-weights L1 checks for exactly pinned scheduling and no-change isolation."""

import json
import tempfile
import unittest
from pathlib import Path

from matrix import build_plan, execute_arm, load_plan, plan_id, write_plan
from model_runner import snapshot_digest


class MatrixTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.protocol = json.loads(Path(__file__).with_name('protocol.json').read_text())
        self.dataset_path = self.root / 'dataset.jsonl'
        rows = []
        for label in (0, 1):
            for i in range(8):
                rows.append({'sample_id': f'train-{label}-{i}', 'split': 'train',
                             'source_group': f'train-{label}-{i}', 'episode_id': f'train-{label}-{i}',
                             'label': label, 'language': 'zh', 'scope': 'test-scope',
                             'state': 'state', 'question': 'choice?', 'options': ['a', 'b']})
        for split in ('calibration', 'held_out', 'future_1', 'future_2', 'ood'):
            rows.append({'sample_id': split, 'split': split, 'source_group': split,
                         'episode_id': split, 'label': 0, 'language': 'en', 'scope': 'test-scope',
                         'state': 'state', 'question': 'choice?', 'options': ['a', 'b']})
        self.dataset_path.write_text(''.join(json.dumps(x) + '\n' for x in rows))
        self.descriptors = {}
        for model, profile in self.protocol['model_candidates'].items():
            folder = self.root / model
            folder.mkdir()
            (folder / 'config.json').write_text(json.dumps({'fixture': model}))
            self.descriptors[model] = {'snapshot_path': str(folder),
                                       'source': profile['source'],
                                       'upstream_revision': 'a' * 40,
                                       'sha256': snapshot_digest(folder),
                                       'license_approved': True,
                                       'custom_code_reviewed': model == 'jina_zh'}

    def plan(self):
        return build_plan(self.dataset_path, self.descriptors, self.protocol,
                          device='cpu', train_steps=2, seed=7347, shots=[0, 8])

    def test_full_finite_grid_and_explicit_no_change(self):
        plan = self.plan()
        self.assertEqual(5 * 4 * 6 * 4, len(plan['arms']))
        self.assertTrue(all(x['shots_per_class'] == 8 for x in plan['arms']))
        self.assertEqual(['no_change', 'laya_421m', 'laya_multilingual_322m'],
                         plan['external_baselines'])
        self.assertEqual('unexecuted', plan['execution_status'])
        self.assertFalse(plan['production_authorized'])
        self.assertEqual(len({x['arm'] for x in plan['arms']}), len(plan['arms']))

    def test_snapshot_drift_and_unapproved_code_fail_closed(self):
        (self.root / 'jina_zh' / 'config.json').write_text('changed bytes')
        with self.assertRaisesRegex(ValueError, 'snapshot bytes drifted'):
            self.plan()
        (self.root / 'jina_zh' / 'config.json').write_text(json.dumps({'fixture': 'jina_zh'}))
        self.descriptors['jina_zh']['custom_code_reviewed'] = False
        with self.assertRaisesRegex(ValueError, 'source-reviewed'):
            self.plan()

    def test_invalid_snapshots_and_unregistered_shots_refused(self):
        del self.descriptors['modernbert_base']
        with self.assertRaisesRegex(ValueError, 'all candidate'):
            self.plan()
        self.descriptors['modernbert_base'] = dict(self.descriptors['mmbert_small'])
        with self.assertRaisesRegex(ValueError, 'source mismatch'):
            self.plan()
        self.descriptors['modernbert_base']['source'] = self.protocol['model_candidates']['modernbert_base']['source']
        with self.assertRaisesRegex(ValueError, 'not preregistered'):
            build_plan(self.dataset_path, self.descriptors, self.protocol,
                       device='cpu', train_steps=2, seed=7347, shots=[17])

    def test_frozen_plan_resists_tampering_and_overwrite(self):
        out = self.root / 'plan.json'
        plan = self.plan()
        signed = write_plan(out, plan)
        self.assertEqual(plan_id(plan), signed['plan_sha256'])
        self.assertEqual(plan_id(plan), load_plan(out)[1])
        with self.assertRaises(FileExistsError):
            write_plan(out, plan)
        doc = json.loads(out.read_text())
        doc['train_steps'] = 2000
        out.write_text(json.dumps(doc))
        with self.assertRaisesRegex(ValueError, 'modified'):
            load_plan(out)

    def test_unsupported_arm_cannot_launch_model(self):
        out = self.root / 'plan.json'
        write_plan(out, self.plan())
        with self.assertRaisesRegex(ValueError, 'not part of frozen plan'):
            execute_arm(out, 'fake_arm', self.root / 'predictions.jsonl')


if __name__ == '__main__':
    unittest.main()

class ShotIsolationTests(unittest.TestCase):
    def test_shots_are_globally_group_distinct_across_classes(self):
        from model_runner import select_shots
        rows = [
            {'label': 0, 'source_group': 'shared', 'sample_id': 'a'},
            {'label': 1, 'source_group': 'shared', 'sample_id': 'b'},
            {'label': 1, 'source_group': 'distinct', 'sample_id': 'c'},
        ]
        chosen = select_shots(rows, 1, 7347)
        self.assertEqual(2, len(chosen))
        self.assertEqual(2, len({x['source_group'] for x in chosen}))
