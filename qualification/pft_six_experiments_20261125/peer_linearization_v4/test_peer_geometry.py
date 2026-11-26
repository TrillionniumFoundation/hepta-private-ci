"""Deterministic sufficient-statistic validation; no model, data, or training."""
import unittest

import numpy as np

from profile_io import canonical, sha
from peer_equations import COMMON_SCHEMA, OBJECTIVE, solve_common


class PeerGeometryTests(unittest.TestCase):
    def common(self, ridge=.25):
        layout = [{"name": "geometry_fixture", "flat_index": i, "scale": 1.,
                   "shape": [2], "dtype": "float64"} for i in range(2)]
        return {"schema": COMMON_SCHEMA, "round": "synthetic-geometry-regression",
                "roster": ["fixture_a", "fixture_b"], "profile_sha256": "1" * 64,
                "candidate_sha256": "2" * 64, "source_binding_sha256": "3" * 64,
                "runtime": {"fixture": "pure algebra; no physical model or participant"},
                "linearization": {"parent_state_sha256": "4" * 64,
                    "coordinate_sha256": sha(canonical(layout)), "coordinate_layout": layout,
                    "objective_state": "known matrix fixture", "output": "matrix product",
                    "derivative": "exact given matrix", "second_order_autograd": False},
                "objective": OBJECTIVE, "ridge": ridge}

    def row(self, common, node, gram, moment, square, count=1):
        body = {"schema": "hepta.smallhcsn.normal-equation-contribution.v1",
                "common_sha256": sha(canonical(common)), "node": node,
                "batch_sha256": sha(canonical({"batch": node})),
                "local_linearization_sha256": sha(canonical({"linearization": node})),
                "observation_count": count, "gram": gram,
                "moment": moment, "residual_square": square}
        return {"body": body, "sha256": sha(canonical(body))}

    def same_rows(self, common, gram, moment, square, count=1):
        return [self.row(common, node, gram, moment, square, count)
                for node in common["roster"]]

    def valid_rows(self, common, scale):
        return [self.row(common, "fixture_a", [[scale, 0.], [0., 0.]],
                         [scale, 0.], scale),
                self.row(common, "fixture_b", [[0., 0.], [0., 4 * scale]],
                         [0., -2 * scale], scale)]

    def test_original_small_scale_impossible_moment_is_refused(self):
        # Exact parent counterexample: delta=[2e16,0], data=-400,
        # regularized=-199.99999999999997 on the retained f9b4cdb source.
        common = self.common(ridge=1e-30)
        rows = self.same_rows(common, [[0., 0.], [0., 0.]], [1e-14, 0.], 0.)
        with self.assertRaisesRegex(ValueError, "zero residual energy"):
            solve_common(common, rows)

    def test_valid_uniform_extreme_scaling_preserves_solution(self):
        expected = np.array([.8, -2. / 4.25])
        objective = None
        for scale in (1., 1e-250, 1e250):
            with self.subTest(scale=scale):
                common = self.common(ridge=.25 * scale)
                rows = self.valid_rows(common, scale)
                result = solve_common(common, rows)
                np.testing.assert_allclose(result["delta"], expected, rtol=1e-12, atol=1e-12)
                self.assertEqual(result["gram_rank_estimate"], 2)
                self.assertEqual(result["ridge_applications"], 1)
                self.assertEqual(result["observation_count"], 2)
                self.assertEqual(result, solve_common(common, list(reversed(rows))))
                self.assertGreaterEqual(result["linearized_data_objective"], 0.)
                self.assertLessEqual(result["regularized_objective"], result["objective_at_zero"])
                scaled_objective = result["regularized_objective"] / scale
                if objective is None:
                    objective = scaled_objective
                else:
                    self.assertAlmostEqual(scaled_objective, objective, places=12)

    def test_zero_statistics_are_valid_at_extreme_ridge_scales(self):
        for ridge in (.25, 1e-250, 1e250):
            with self.subTest(ridge=ridge):
                common = self.common(ridge)
                rows = self.same_rows(common, [[0., 0.], [0., 0.]], [0., 0.], 0.)
                result = solve_common(common, rows)
                self.assertEqual(result["delta"], [0., 0.])
                self.assertEqual(result["gram_rank_estimate"], 0)
                self.assertEqual(result["linearized_data_objective"], 0.)
                self.assertEqual(result["regularized_objective"], 0.)

    def test_non_psd_geometry_is_refused_at_every_scale(self):
        for scale in (1., 1e-250, 1e250):
            with self.subTest(scale=scale):
                common = self.common(ridge=.25 * scale)
                rows = self.same_rows(common, [[scale, 0.], [0., -.01 * scale]],
                                      [0., 0.], scale, count=2)
                with self.assertRaisesRegex(ValueError, "geometry"):
                    solve_common(common, rows)

    def test_unresolved_null_range_and_nonconvex_operator_are_refused(self):
        common = self.common(ridge=1e-30)
        rows = self.same_rows(common, [[1., 0.], [0., 0.]], [0., 1e-14], 1., count=2)
        with self.assertRaisesRegex(ValueError, "range"):
            solve_common(common, rows)
        common = self.common(ridge=1e-16)
        rows = self.same_rows(common, [[1., 0.], [0., -1e-15]], [0., 0.], 1., count=2)
        with self.assertRaisesRegex(ValueError, "positive definite"):
            solve_common(common, rows)
        common = self.common(ridge=1e-30)
        rows = self.same_rows(common, [[1., 0.], [0., 0.]], [0., 0.], 1., count=2)
        with self.assertRaisesRegex(ValueError, "positive definite"):
            solve_common(common, rows)

    def test_finite_inputs_that_overflow_aggregation_are_refused(self):
        common = self.common()
        rows = self.same_rows(common, [[9e307, 0.], [0., 0.]], [0., 0.], 0.)
        with self.assertRaises(ValueError):
            solve_common(common, rows)
        common = self.common(ridge=1e308)
        rows = self.same_rows(common, [[6e307, 0.], [0., 0.]], [0., 0.], 0.)
        with self.assertRaises(ValueError):
            solve_common(common, rows)
        common = self.common()
        rows = self.same_rows(common, [[0., 0.], [0., 0.]], [0., 0.], 9e307)
        with self.assertRaises(ValueError):
            solve_common(common, rows)


    def test_cross_block_scale_cannot_hide_impossible_geometry(self):
        cases = (
            # A: each peer has a negative Gram masked by large residual energy.
            ("negative diagonal", 2., [[-.5, 0.], [0., 0.]], [0., 0.], 5e14),
            # B: total b^2 exceeds G*c despite positive G and c.
            ("Cauchy-Schwarz", 1e30, [[.5e15, 0.], [0., 0.]], [.5, 0.], .5e-20),
            # Independent root example: total G=1e-30,b=100,c=1e30.
            ("Cauchy-Schwarz", 1., [[.5e-30, 0.], [0., 0.]], [50., 0.], .5e30),
        )
        for reason, ridge, gram, moment, square in cases:
            with self.subTest(reason=reason, gram=gram, square=square):
                common = self.common(ridge)
                rows = self.same_rows(common, gram, moment, square)
                with self.assertRaisesRegex(ValueError, reason):
                    solve_common(common, rows)

    def test_valid_subnormal_objective_is_refused_instead_of_reported_zero(self):
        # Total G=ridge=2^-1060, b=2^-500, c=2^60 is valid rank-one data.
        # Its exact delta=2^559; data=penalty=2^57 and total=2^58.
        # This implementation conservatively refuses its lossy normalization.
        gram = float.fromhex("0x1p-1060")
        moment = float.fromhex("0x1p-500")
        square = float.fromhex("0x1p+60")
        self.assertGreater(gram, 0.)
        common = self.common(gram)
        rows = self.same_rows(common, [[gram / 2, 0.], [0., 0.]],
                              [moment / 2, 0.], square / 2)
        with self.assertRaisesRegex(ValueError, "underflow"):
            solve_common(common, rows)



if __name__ == "__main__":
    unittest.main()
