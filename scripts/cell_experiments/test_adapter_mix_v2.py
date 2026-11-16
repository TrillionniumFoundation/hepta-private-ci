"""A factor mixture must reproduce weighted adapter outputs, not cross terms."""

import unittest
import numpy as np
from .adapter_mix_v2 import concatenate_pairs


class MixtureTests(unittest.TestCase):
    def test_combined_adapter_matches_two_separate_deltas(self):
        rng = np.random.default_rng(81)
        pairs = [(rng.normal(size=(r, 5)), rng.normal(size=(7, r))) for r in (2, 3)]
        inputs = rng.normal(size=(5, 4))
        a, b = concatenate_pairs(pairs, [2.0, 3.0], [0.25, 0.75], np)
        reference = sum(
            w * s * bb @ aa @ inputs
            for (aa, bb), s, w in zip(pairs, [2.0, 3.0], [0.25, 0.75])
        )
        np.testing.assert_allclose(b @ a @ inputs, reference, atol=1e-12)
        self.assertEqual((a.shape, b.shape), ((5, 5), (7, 5)))

    def test_mixture_rejects_incompatible_base_shapes(self):
        with self.assertRaisesRegex(ValueError, "base shapes"):
            concatenate_pairs(
                [
                    (np.ones((2, 5)), np.ones((7, 2))),
                    (np.ones((2, 6)), np.ones((7, 2))),
                ],
                [1, 1],
                [0.5, 0.5],
                np,
            )
