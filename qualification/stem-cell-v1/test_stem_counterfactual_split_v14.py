"""Mechanism fixtures plus exact-original-archive integration when provisioned.

Synthetic unit tensors test arithmetic/contracts only, not task capability.
The optional original suite really trains 12 candidate models and replays their
predictions. Missing original material is an explicit skip, never efficacy PASS.
"""
import ast
from copy import deepcopy
import os
from pathlib import Path
import shutil
import tempfile
import unittest

import torch
from torch import nn

import stem_counterfactual_split_v14 as p
import stem_counterfactual_split_v14_review as r


def fixture():
    with torch.random.fork_rng():
        torch.manual_seed(19)
        x = torch.randn(32, 384)
        parent = nn.Linear(384, 4)
    return x, parent


class Mechanism(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_inheritance_and_distinct_storage(self):
        x, parent = fixture()
        split = p.Split(parent, p.fit_centers(x))
        wide = p.Wide(parent, 41)
        self.assertTrue(torch.allclose(split(x), parent(x), atol=2e-6, rtol=0))
        self.assertTrue(torch.equal(wide(x), parent(x)))
        pointers = [parent.weight.data_ptr(), *[h.weight.data_ptr() for h in split.heads]]
        self.assertEqual(len(set(pointers)), 3)

    def test_only_selected_head_is_executed(self):
        x, parent = fixture()
        split = p.Split(parent, p.fit_centers(x))
        calls = [0, 0]
        def counter(cell):
            def hook(_module, args):
                calls[cell] += len(args[0])
            return hook
        hooks = [h.register_forward_pre_hook(counter(i)) for i, h in enumerate(split.heads)]
        try:
            split(x, torch.zeros(32, dtype=torch.long))
        finally:
            for h in hooks:
                h.remove()
        self.assertEqual(calls, [32, 0])
        self.assertEqual(split.head_rows, 32)

    def test_sparse_dense_numerical_agreement(self):
        x, parent = fixture()
        split = p.Split(parent, p.fit_centers(x))
        with torch.no_grad():
            split.heads[1].bias.add_(0.2)
        route = torch.arange(32) % 2
        dense = torch.stack([h(x) for h in split.heads], 1)[torch.arange(32), route]
        self.assertTrue(torch.allclose(split(x, route), dense, atol=2e-6, rtol=0))
        self.assertEqual(split.head_rows, 32)

    def test_physical_parameter_budget(self):
        x, parent = fixture()
        split, wide = p.Split(parent, p.fit_centers(x)), p.Wide(parent, 41)
        self.assertEqual(sum(t.numel() for t in split.parameters()), 3080)
        self.assertEqual(sum(t.numel() for t in split.buffers()), 768)
        self.assertEqual(sum(t.numel() for t in wide.parameters()), 3878)

    def test_training_preserves_separate_parent(self):
        x, parent = fixture()
        split = p.Split(parent, p.fit_centers(x))
        before = p.parameter_sha(parent)
        p.fit(split, x, torch.arange(32) % 4, [list(range(16))] * 2)
        self.assertEqual(before, p.parameter_sha(parent))
        self.assertNotEqual(before, p.parameter_sha(split.heads[0]))

    def test_empty_child_denied(self):
        with self.assertRaisesRegex(ValueError, 'empty routing child'):
            p.fit_centers(torch.zeros(32, 384))

    def test_feature_contract(self):
        x, _ = fixture()
        bad = [x.double(), x[:, :383], x.repeat(5, 1), x * float('nan'), x * 1e8]
        for item in bad:
            with self.subTest(shape=item.shape):
                with self.assertRaises(ValueError):
                    p.checked_features(item)

    def test_route_contract(self):
        x, parent = fixture()
        split = p.Split(parent, p.fit_centers(x))
        for route in (torch.ones(32), torch.full((32,), 2), torch.ones(31, dtype=torch.long)):
            with self.assertRaises(ValueError):
                split(x, route)

    def test_nochange_wins_tie(self):
        values = dict.fromkeys(p.ARMS, .5)
        self.assertEqual(p.choose_candidate(values, values), 'frozen')

    def test_calibration_only_strong_split(self):
        cal = dict(zip(p.ARMS, (.8, .6, .55, .3)))
        old = dict.fromkeys(p.ARMS, .2)
        self.assertEqual(p.choose_candidate(cal, old), 'split')
        self.assertEqual(r.choose(cal, old), 'split')

    def test_old_training_regression_veto(self):
        cal = dict(zip(p.ARMS, (.8, .6, .55, .3)))
        old = dict.fromkeys(p.ARMS, .2)
        old['split'] = .3
        self.assertEqual(p.choose_candidate(cal, old), 'wide')

    def test_growth_margin_is_required(self):
        cal = dict(zip(p.ARMS, (.8, .4, .396, .395)))
        old = dict.fromkeys(p.ARMS, .2)
        self.assertEqual(p.choose_candidate(cal, old), 'continued')

    def test_bad_selector_scores_denied(self):
        for value in (float('nan'), float('inf'), -1, 3):
            cal = dict.fromkeys(p.ARMS, .5)
            cal['split'] = value
            with self.assertRaises(ValueError):
                p.choose_candidate(cal, dict.fromkeys(p.ARMS, .5))
        with self.assertRaises(ValueError):
            p.choose_candidate({'frozen': .5}, {'frozen': .5})

    def test_wrong_archive_creates_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            (td / 'wrong.zip').write_bytes(b'not the source')
            with self.assertRaises(ValueError):
                p.prepare(td / 'wrong.zip', td / 'out', td / 'labels.json')
            self.assertFalse((td / 'out').exists())
            self.assertFalse((td / 'labels.json').exists())

    def test_create_only_and_strict_json(self):
        with tempfile.TemporaryDirectory() as td:
            file = Path(td) / 'once.json'
            p.write_new(file, b'{}')
            with self.assertRaises(FileExistsError):
                p.write_new(file, b'{}')
            for raw in (b'{"x":1,"x":2}', b'{"x":NaN}'):
                file.write_bytes(raw)
                with self.assertRaises(ValueError):
                    p.read_json(file)

    def test_numpy_reviewer_has_no_producer_or_torch_import(self):
        tree = ast.parse(Path(r.__file__).read_text())
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports += [x.name for x in node.names]
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or '')
        self.assertFalse(any(x.startswith('torch') or x == p.__name__ for x in imports))


@unittest.skipUnless(os.environ.get('HEPTA_V14_ORIGINAL_ZIP'), 'exact original archive not provisioned')
class OriginalEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.archive = Path(os.environ['HEPTA_V14_ORIGINAL_ZIP'])
        cls.inputs, cls.results = cls.root / 'input', cls.root / 'results'
        p.prepare(cls.archive, cls.inputs, cls.root / 'held.json')
        p.run(cls.inputs, cls.results)
        cls.report = p.read_json(cls.results / 'predictions.json')
        cls.review = r.review(cls.archive, cls.inputs, cls.results)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def mutated(self, alter):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / 'copy'
            shutil.copytree(self.results, out)
            value = deepcopy(self.report)
            alter(value, out)
            (out / 'predictions.json').write_bytes(p.canonical(value))
            with self.assertRaises((ValueError, KeyError)):
                r.review(self.archive, self.inputs, out)

    def test_all_models_replayed(self):
        self.assertEqual(self.review['numeric_profiles_recomputed'], 18)
        self.assertLessEqual(self.review['max_probability_error'], 5e-5)
        self.assertEqual(self.review['unique_held_cases'], 32)
        self.assertEqual(self.review['optimizer_steps_executed_in_producer'], 960)
        self.assertFalse(self.review['prospective_efficacy_verified'])

    def test_trainer_has_no_held_labels(self):
        meta = p.read_json(self.inputs / 'input.json')
        self.assertTrue(set(map(str, meta['partitions']['holdout'])).isdisjoint(meta['labels']))
        self.assertTrue(all('text' not in row for row in meta['roster']))
        self.assertEqual(p.sha((self.inputs / 'input.json').read_bytes()), p.INPUT_SHA)

    def test_changed_predictions_denied(self):
        self.mutated(lambda x, _: x['seeds']['41']['held_predictions']['split'].__setitem__(0, [.25] * 4))

    def test_changed_model_denied(self):
        def alter(_report, out):
            file = out / '41-split.safetensors'
            data = bytearray(file.read_bytes())
            data[-1] ^= 1
            file.write_bytes(data)
        self.mutated(alter)

    def test_wrong_source_denied(self):
        self.mutated(lambda x, _: x.__setitem__('source_sha256', '0' * 64))

    def test_false_authority_denied(self):
        self.mutated(lambda x, _: x.__setitem__('production_authorized', True))

    def test_false_prospective_denied(self):
        self.mutated(lambda x, _: x.__setitem__('prospective_efficacy_verified', True))

    def test_missing_seed_denied(self):
        self.mutated(lambda x, _: x['seeds'].pop('47'))

    def test_selected_candidate_tamper_denied(self):
        self.mutated(lambda x, _: x['seeds']['41'].__setitem__('selected_research_candidate', 'split'))

    def test_fake_sparse_work_denied(self):
        self.mutated(lambda x, _: x['seeds']['41']['work']['split'].__setitem__('selected_head_rows', 2560))

    def test_false_parameter_count_denied(self):
        self.mutated(lambda x, _: x['seeds']['41']['models']['split'].__setitem__('resident_bytes', 100))

    def test_held_case_swap_denied(self):
        self.mutated(lambda x, _: x['case_ids'].reverse())

    def test_route_metadata_tamper_denied(self):
        self.mutated(lambda x, _: x['seeds']['41']['held_routes'].__setitem__(0, 2))

    def test_extra_candidate_denied(self):
        self.mutated(lambda x, _: x['seeds']['41']['models'].__setitem__('invented', {}))


if __name__ == '__main__':
    unittest.main()
