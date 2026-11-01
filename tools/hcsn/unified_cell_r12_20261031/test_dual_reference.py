import unittest

import numpy as np

from .cell import Cell
from .dual_reference import run_dual_reference


class DualReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = run_dual_reference(Cell())

    def test_anchor_values_and_local_slope_match(self):
        anchor = self.report["anchor"]
        np.testing.assert_allclose(anchor["A_B"], anchor["local_alpha_values"], rtol=0, atol=2e-12)
        self.assertLess(anchor["slope_max_error"], 2e-7)

    def test_fixed_margin_cannot_encode_other_changes(self):
        np.testing.assert_array_equal(self.report["margin_reference_fixed_margin_channel_range"], [0., 0.])
        self.assertGreater(max(self.report["exact_fixed_margin_channel_range"]), .01)

    def test_public_split_and_finite_heldout_scores(self):
        r = self.report
        self.assertFalse(set(r["train_indices"]) & set(r["test_indices"]))
        self.assertEqual(set(r["train_indices"]) | set(r["test_indices"]), set(range(len(r["grid"]))))
        self.assertTrue(np.isfinite(r["ordinary_independent_heads"]["heldout_channel_mse"]).all())


if __name__ == "__main__":
    unittest.main()
