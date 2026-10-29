"""Small synthetic geometry/state tests; no A bank, scientific model or data."""

from copy import deepcopy
import unittest

import numpy as np

from .witness import codec, momentum_coordinates, orthogonal_reflection, ranking, replace_momentum


class ReflectionTests(unittest.TestCase):
    def test_projection_preserves_norm_and_all_retained_inner_products(self):
        rng = np.random.default_rng(449)
        rows, momentum = rng.normal(size=(4, 19)), rng.normal(size=19)
        reflected, info = orthogonal_reflection(momentum, rows)
        np.testing.assert_allclose(rows @ reflected, rows @ momentum, rtol=1e-12, atol=1e-12)
        self.assertAlmostEqual(np.linalg.norm(reflected), np.linalg.norm(momentum), places=12)
        original, _ = orthogonal_reflection(reflected, rows)
        np.testing.assert_allclose(original, momentum, rtol=1e-12, atol=1e-12)
        self.assertEqual(info['rank'], 4)
        self.assertGreater(info['orthogonal_residual_norm'], 0.)

    def test_known_rank_deficient_span_reflects_only_orthogonal_component(self):
        rows = np.asarray([[1., 0., 0., 0.], [0., 1., 0., 0.],
                           [2., 0., 0., 0.], [0., -3., 0., 0.]])
        reflected, info = orthogonal_reflection([1., -2., 3., 4.], rows)
        np.testing.assert_allclose(reflected, [1., -2., -3., -4.], atol=1e-14)
        self.assertEqual(info['rank'], 2)
        self.assertAlmostEqual(info['orthogonal_residual_norm'], 5.)

    def test_cutoff_uses_unscaled_relative_singular_values_and_keeps_degenerate_cases(self):
        rows = np.diag([1., 1e-11, 0., 0.])
        reflected, info = orthogonal_reflection([1., 2., 3., 4.], rows)
        self.assertEqual(info['rank'], 1)
        np.testing.assert_array_equal(reflected, [1., -2., -3., -4.])
        zero, info = orthogonal_reflection(np.zeros(6), np.zeros((4, 6)))
        np.testing.assert_array_equal(zero, np.zeros(6))
        self.assertEqual(info['rank'], 0)
        full, info = orthogonal_reflection([1., 2., 3., 4.], np.eye(4))
        np.testing.assert_array_equal(full, [1., 2., 3., 4.])
        self.assertEqual(info['orthogonal_residual_norm'], 0.)

    def test_h12_momentum_terms_preserved_when_direction_coordinates_are_active(self):
        rng = np.random.default_rng(72)
        directions, momentum = rng.normal(size=(4, 23)), rng.normal(size=23)
        reflected, _ = orthogonal_reflection(momentum, directions)
        g, probes = directions[0], directions[1:]
        def observed(m):
            return np.concatenate(([np.linalg.norm(m), np.dot(g, m) / (np.linalg.norm(g) * np.linalg.norm(m))],
                                   probes @ (.9 * m + g)))
        np.testing.assert_allclose(observed(momentum), observed(reflected), rtol=1e-12, atol=1e-12)
        stored = reflected.astype(np.float32).astype(np.float64)
        self.assertLess(float(np.abs(observed(stored) - observed(momentum)).max()), 1e-5)

    def test_invalid_geometry_is_rejected(self):
        for momentum, rows in (([1., 2.], np.ones((3, 2))), ([np.nan], np.ones((4, 1))),
                               ([1.], np.full((4, 1), np.inf)), ([], np.zeros((4, 0)))):
            with self.subTest(momentum=momentum), self.assertRaises(ValueError):
                orthogonal_reflection(momentum, rows)


class MomentumStateTests(unittest.TestCase):
    def record(self):
        return {'parameters': {'z': np.asarray([7.], dtype=np.float32), 'a': np.asarray([2., 3.], dtype=np.float32)},
                'optimizer_parameter_names': {0: 'z', 4: 'a'},
                'optimizer': {'kind': 'SGD', 'param_groups': [{'params': [0, 4], 'lr': .02, 'momentum': .9}],
                              'state': {4: {'momentum_buffer': np.asarray([1., 2.], dtype=np.float32)}}},
                'gradients': {'z': None, 'a': np.asarray([.1, .2], dtype=np.float32)},
                'cursor': {'clock': 48}, 'history': [{'already_observed': True}],
                'remaining_schedule': [{'future_seed': 991}], 'rng': {'untouched': np.asarray([1, 2], dtype=np.uint8)}}

    def test_name_mapping_and_float32_write_change_only_momentum(self):
        record = self.record()
        before = codec.dumps(record)
        vector, layout = momentum_coordinates(record, ['a', 'z'])
        np.testing.assert_array_equal(vector, [1., 2., 0.])
        changed, _, introduced = replace_momentum(record, ['a', 'z'], [-1., -2., 0.])
        self.assertEqual(introduced, [])
        self.assertNotIn(0, changed['optimizer']['state'])
        self.assertEqual(changed['optimizer']['state'][4]['momentum_buffer'].dtype, np.float32)
        self.assertEqual(codec.dumps(record), before)
        left, right = deepcopy(record), deepcopy(changed)
        left['optimizer']['state'], right['optimizer']['state'] = {}, {}
        self.assertEqual(codec.dumps(left), codec.dumps(right))
        self.assertEqual(layout[0]['optimizer_id'], 4)

    def test_nonzero_missing_momentum_is_explicitly_reported(self):
        record = self.record()
        changed, _, introduced = replace_momentum(record, ['a', 'z'], [1., 2., 5.])
        self.assertEqual(introduced, ['z'])
        np.testing.assert_array_equal(changed['optimizer']['state'][0]['momentum_buffer'], np.asarray([5.], dtype=np.float32))
        self.assertIsNone(changed['gradients']['z'])

    def test_ranking_preserves_exact_ties_without_selecting_a_favorable_action(self):
        self.assertEqual(ranking([.5, .7, .1, .7]), [[1, 3], [0], [2]])
        self.assertEqual(ranking([0., 0., 0., 0.]), [[0, 1, 2, 3]])
        with self.assertRaises(ValueError):
            ranking([0., np.nan, 0., 0.])


if __name__ == '__main__':
    unittest.main()
