"""V15 arithmetic fixtures and separately provisioned exact-original tests."""
import ast
from copy import deepcopy
import os
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np
import torch

import stem_stable_router_v15 as p
import stem_stable_router_v15_review as r


class Mechanism(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def fixture(self):
        rng = np.random.default_rng(15)
        x = torch.from_numpy(rng.standard_normal((64, 384)).astype('float32'))
        return x, p.normalized(x, x[:32].mean(0))

    def test_normalized_unit_budget(self):
        _, z = self.fixture()
        self.assertTrue(bool((z.norm(dim=1) <= 1.000001).all()))

    def test_positive_scale_invariance(self):
        x, z = self.fixture()
        self.assertTrue(torch.allclose(p.normalized(x * 60, x[:32].mean(0) * 60), z, atol=1e-6))

    def test_zero_residual_is_finite(self):
        z = p.normalized(torch.ones(4, 384), torch.ones(384))
        self.assertTrue(torch.equal(z, torch.zeros_like(z)))

    def test_nonfinite_rejected(self):
        x, _ = self.fixture()
        for mean in (torch.full((384,), float('nan')), torch.ones(383), torch.ones(384).double()):
            with self.assertRaises(ValueError):
                p.normalized(x, mean)

    def test_fold_coverage_and_exclusion(self):
        folds = p.partition([f'group-{i}' for i in range(64)])
        self.assertEqual([len(x) for x in folds], [16] * 4)
        self.assertEqual(sorted(sum(folds, [])), list(range(64)))
        for excluded in folds:
            train = [i for i in range(64) if i not in excluded]
            self.assertFalse(set(train) & set(excluded))
            self.assertTrue(len([i for i in train if i < 32]) >= 16)

    def test_duplicate_group_denied(self):
        with self.assertRaises(ValueError):
            p.partition(['same'] * 64)

    def test_split_and_wide_inherit(self):
        _, z = self.fixture()
        parent = p.linear(41)
        split = p.old.Split(parent, p.centers_for(z))
        wide = p.Wide(parent, 41)
        self.assertTrue(torch.allclose(split(z), parent(z), atol=2e-6))
        self.assertTrue(torch.equal(wide(z), parent(z)))
        self.assertNotEqual(split.heads[0].weight.data_ptr(), split.heads[1].weight.data_ptr())

    def test_budget_is_physical(self):
        _, z = self.fixture()
        parent = p.linear(41)
        split = p.old.Split(parent, p.centers_for(z))
        gate = p.linear(41, 1)
        self.assertEqual(sum(x.numel() for x in split.parameters()), 3080)
        self.assertEqual(sum(x.numel() for x in split.buffers()), 768)
        self.assertEqual(sum(x.numel() for x in gate.parameters()), 385)
        self.assertEqual(sum(x.numel() for x in p.Wide(parent, 41).parameters()), 4267)

    def test_physically_selected_rows(self):
        _, z = self.fixture()
        split = p.old.Split(p.linear(41), p.centers_for(z))
        actual = [0, 0]
        def hook(k):
            def count(_m, inputs):
                actual[k] += len(inputs[0])
            return count
        handles = [h.register_forward_pre_hook(hook(k)) for k, h in enumerate(split.heads)]
        try:
            split(z, torch.ones(64, dtype=torch.long))
        finally:
            for handle in handles:
                handle.remove()
        self.assertEqual(actual, [0, 64])

    def test_measured_train_counts_only_optimizer_rows(self):
        _, z = self.fixture()
        split = p.old.Split(p.linear(41), p.centers_for(z))
        result = p.measured_fit(split, z, torch.arange(64) % 4, [list(range(16))] * 3)
        self.assertEqual(result['selected_head_rows'], 48)
        self.assertEqual(result['examples'], 48)

    def test_selector_nochange_and_margin(self):
        cal = dict.fromkeys(p.ARMS, .5)
        self.assertEqual(p.choose(cal, cal), 'frozen')
        cal.update(continued=.4, wide=.398, centroid=.396, task=.395)
        self.assertEqual(p.choose(cal, dict.fromkeys(p.ARMS, .5)), 'continued')

    def test_selector_old_fit_veto(self):
        cal = dict.fromkeys(p.ARMS, .6)
        cal.update(task=.2, continued=.4)
        old = dict.fromkeys(p.ARMS, .5)
        old['task'] = .8
        self.assertEqual(p.choose(cal, old), 'continued')

    def test_bad_selector_fields(self):
        for x in (float('nan'), -1, 3, True):
            d = dict.fromkeys(p.ARMS, .5)
            d['task'] = x
            with self.assertRaises(ValueError):
                p.choose(d, d)

    def test_numpy_normalization_and_routes(self):
        x, z = self.fixture()
        nz = r.norm(x.numpy(), x[:32].numpy().mean(0))
        self.assertLess(float(np.max(np.abs(nz - z.numpy()))), 1e-6)
        centers = p.centers_for(z)
        self.assertTrue(np.array_equal(p.old.assign(z, centers).numpy(), r.assign(nz, centers.numpy())))

    def test_reviewer_import_is_separate(self):
        tree = ast.parse(Path(r.__file__).read_text())
        names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.extend(x.name for x in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.append(node.module or '')
        self.assertFalse(any(x.startswith('torch') or 'stem_' in x for x in names))

    def test_corrupt_input_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'input.json').write_text('{}')
            with self.assertRaises(ValueError):
                p.run(root, root / 'result')
            self.assertFalse((root / 'result').exists())


@unittest.skipUnless(os.environ.get('HEPTA_V14_ORIGINAL_ZIP'), 'original archive not provisioned')
class Original(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.inputs, cls.out = cls.root / 'inputs', cls.root / 'result'
        p.old.prepare(os.environ['HEPTA_V14_ORIGINAL_ZIP'], cls.inputs, cls.root / 'held-private.json')
        # Delete the separate held-label file before the actual V15 run.
        (cls.root / 'held-private.json').unlink()
        p.run(cls.inputs, cls.out)
        cls.payload = p.old.read_json(cls.out / 'sealed.json')
        cls.review = r.review(cls.inputs, cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def mutate(self, fn):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / 'copy'
            shutil.copytree(self.out, out)
            value = deepcopy(self.payload)
            fn(value, out)
            (out / 'sealed.json').write_bytes(p.old.canonical(value))
            with self.assertRaises((ValueError, KeyError)):
                r.review(self.inputs, out)

    def test_actual_complete_replay(self):
        self.assertEqual(self.review['model_files_replayed'], 58)
        self.assertEqual(self.review['learned_parameter_bundles'], 45)
        self.assertEqual(self.review['oof_teacher_logits_replayed'], 1536)
        self.assertLess(self.review['max_numeric_error'], 5e-5)

    def test_held_labels_absent_and_unscored(self):
        self.assertFalse((self.root / 'held-private.json').exists())
        self.assertIsNone(self.review['held_scores'])
        self.assertFalse(self.payload['held_labels_read'])
        self.assertFalse(self.review['production_authorized'])

    def test_stable_parent_finite_diagnostic(self):
        for row in self.payload['seeds'].values():
            self.assertTrue(np.isfinite(row['work']['parent']['loss_after']))
            self.assertEqual(sum(w['steps'] for w in row['work'].values()), 1200)

    def test_wrong_protocol(self):
        self.mutate(lambda x, _: x['protocol'].__setitem__('learning_rate', 100))

    def test_fake_authority(self):
        self.mutate(lambda x, _: x.__setitem__('production_authorized', True))

    def test_fake_future_efficacy(self):
        self.mutate(lambda x, _: x.__setitem__('prospective_efficacy_verified', True))

    def test_fake_held_score(self):
        self.mutate(lambda x, _: x.__setitem__('held_scores', {'accuracy': 1}))

    def test_fake_teacher_logits(self):
        self.mutate(lambda x, _: x['seeds']['41']['oof_logits'][0][0].__setitem__(0, 999))

    def test_teacher_target_tamper(self):
        self.mutate(lambda x, _: x['seeds']['41']['oof_targets'].__setitem__(0, 2))

    def test_folds_reassigned(self):
        self.mutate(lambda x, _: x['folds'].reverse())

    def test_fake_selected_rows(self):
        self.mutate(lambda x, _: x['seeds']['41']['work']['centroid'].__setitem__('selected_head_rows', 2560))

    def test_fake_calibration(self):
        self.mutate(lambda x, _: x['seeds']['41']['calibration']['task'].__setitem__('correct', 32))

    def test_wrong_route(self):
        self.mutate(lambda x, _: x['seeds']['41']['blind_routes']['task'].__setitem__(0, 2))

    def test_wrong_prediction(self):
        self.mutate(lambda x, _: x['seeds']['41']['blind_probabilities']['task'].__setitem__(0, [1, 0, 0, 0]))

    def test_wrong_selector(self):
        self.mutate(lambda x, _: x['seeds']['41'].__setitem__('selected_research_candidate', 'task'))

    def test_mutated_weights(self):
        def change(_x, out):
            f = out / '41-gate.safetensors'
            b = bytearray(f.read_bytes())
            b[-1] ^= 1
            f.write_bytes(b)
        self.mutate(change)

    def test_false_scalars(self):
        self.mutate(lambda x, _: x['models']['41-wide'].__setitem__('scalars', 100))

    def test_extra_file(self):
        self.mutate(lambda _x, out: (out / 'unaudited.json').write_text('{}'))

    def test_normalizer_rehashed_leak(self):
        def change(x, out):
            name = '41-fold0-normalizer'
            data = p.save({'mean': torch.zeros(384)})
            (out / (name + '.safetensors')).write_bytes(data)
            x['models'][name]['sha256'] = p.old.sha(data)
        self.mutate(change)

    def test_source_hash_drift(self):
        self.mutate(lambda x, _: x.__setitem__('producer_sha256', '0' * 64))


if __name__ == '__main__':
    unittest.main()
