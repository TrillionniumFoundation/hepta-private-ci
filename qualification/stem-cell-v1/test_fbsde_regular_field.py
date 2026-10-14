import unittest

from fbsde_regular_field import NoRegularGlobalField, examine


class RegularFieldTests(unittest.TestCase):
    def test_true_global_slope_and_all_short_boundaries(self):
        for segments in (1, 2, 4, 16, 64, 128):
            with self.subTest(segments=segments):
                result = examine(x0=1, c=1, g=.3, horizon=.6, segments=segments)
                self.assertLess(result["max_global_interface_residual"], 1e-9)
                self.assertLess(result["terminal_residual"], 1e-9)
                self.assertAlmostEqual(result["whole_interval_field"], result["first_field"])
                self.assertFalse(result["general_stochastic_fbsde_solved"])

    def test_wrong_local_terminal_reset_can_pass_segments_but_break_interface(self):
        result = examine(x0=1, c=1, g=.3, horizon=.6, segments=4)
        self.assertLess(result["wrong_reset_local_terminal_residual"], 1e-9)
        self.assertGreater(result["wrong_reset_max_jump"], 1e-3)

    def test_global_pole_not_cured_by_refining_short_intervals(self):
        for segments in (1, 4, 16, 512):
            with self.subTest(segments=segments), self.assertRaisesRegex(
                NoRegularGlobalField, "global regularity"
            ):
                examine(x0=1, c=0, g=2, horizon=.5, segments=segments)

    def test_global_field_limit_cannot_be_hidden_behind_local_small_steps(self):
        with self.assertRaisesRegex(NoRegularGlobalField, "global field slope"):
            examine(x0=1, c=0, g=2, horizon=.499, segments=512, max_slope=100)

    def test_zero_curvature_and_terminal_slope_has_exact_limit(self):
        r = examine(x0=1, c=0, g=0, horizon=10, segments=16)
        self.assertEqual(r["whole_interval_field"], 0)
        self.assertIsNone(r["global_regular_until"])

    def test_invalid_parameters_and_nonfinite_bounds_reject(self):
        for bad in ({"x0": float("nan")}, {"c": -1}, {"g": -1}, {"segments": True},
                    {"segments": 0}, {"horizon": 0}, {"pole_margin": .2}):
            with self.subTest(bad=bad), self.assertRaises(NoRegularGlobalField):
                examine(**bad)

    def test_beyond_first_regular_pole_not_claimed_globally_wellposed(self):
        with self.assertRaisesRegex(NoRegularGlobalField, "global regularity"):
            examine(x0=1, c=1, g=.3, horizon=3, segments=128)


if __name__ == "__main__":
    unittest.main()
