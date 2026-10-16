"""Exact Cell interface/whole-tree regression and adversarial handoff tests."""

from dataclasses import replace
from fractions import Fraction as Q
import unittest

from e12_nonlinear_cert import Law, solve
from e12_cell_boundary import CellSegment, split_result, review_segments, _nonlinear

SCOPE = "a" * 64


class CellBoundaryTest(unittest.TestCase):
    def sample(self, law=Law()):
        original = solve(law)
        return original, split_result(law, original, SCOPE)

    def test_all_six_original_e12_stochastic_laws(self):
        for depth in (1, 2, 3):
            for coupling in ("0", "1/3"):
                with self.subTest(depth=depth, coupling=coupling):
                    law = Law(depth=depth, a=coupling)
                    source, bundle = self.sample(law)
                    review = review_segments(law, source, bundle, SCOPE)
                    self.assertEqual(review.checked_internal_cells, 2**depth - 1)
                    self.assertEqual(review.checked_terminal_cells, 2**depth)
                    self.assertEqual(review.certified_discrete_global_error_bound,
                                     source.fixed_point_error_bound)
                    self.assertTrue(review.exact_backward_interfaces)
                    self.assertFalse(review.continuous_time_fbsde_proven)
                    self.assertFalse(review.natural_reasoning_gain_proven)
                    self.assertFalse(review.production_accepted)
                    self.assertEqual(review.authority, "DENY_ALL")

    def test_actual_nonzero_random_driver_and_martingale_z(self):
        law = Law(depth=3, a="1/3")
        source, bundle = self.sample(law)
        self.assertNotEqual(bundle.segments[0].x_left, bundle.segments[0].x_right)
        self.assertTrue(any(segment.z != "0" for segment in bundle.segments))
        self.assertTrue(review_segments(law, source, bundle, SCOPE).exact_conditional_martingale_z)

    def test_cross_cell_backward_continuation_jump_rejected(self):
        law = Law(depth=2)
        source, bundle = self.sample(law)
        forged = replace(bundle.segments[1], y_start="0")
        with self.assertRaises(ValueError):
            review_segments(law, source,
                            replace(bundle, segments=(bundle.segments[0], forged, bundle.segments[2])),
                            SCOPE)

    def test_cross_cell_forward_state_jump_rejected(self):
        law = Law(depth=2)
        source, bundle = self.sample(law)
        altered = replace(bundle.segments[1], x_start="3")
        with self.assertRaises(ValueError):
            review_segments(law, source,
                            replace(bundle, segments=(bundle.segments[0], altered, bundle.segments[2])),
                            SCOPE)

    def test_local_exact_equations_do_not_prove_global_validity(self):
        law = Law(depth=1, a="1/3")
        params = law.values()
        x = params["x0"]
        # This local segment has exactly zero forward/backward/Z residuals,
        # but it fabricates child continuation values unrelated to their true
        # terminal law. An isolated one-step solver could accept it.
        yl, yr = Q(0), Q(0)
        y = (params["beta"]*params["h"]*_nonlinear(x)) / (1+params["lam"]*params["h"])
        center = x + params["a"]*params["h"]*_nonlinear(y)
        xl, xr = center-params["sigma"]*params["s"], center+params["sigma"]*params["s"]
        node = CellSegment("", SCOPE, str(x), str(y), str(xl), str(xr),
                           str(yl), str(yr), "0")
        self.assertEqual(Q(node.x_left), x+params["a"]*params["h"]*_nonlinear(y)
                         -params["sigma"]*params["s"])
        self.assertEqual((1+params["lam"]*params["h"])*Q(node.y_start),
                         (yl+yr)/2+params["beta"]*params["h"]*_nonlinear(x))
        self.assertEqual(Q(node.z), (yr-yl)/(2*params["s"]))
        # But both independently correct terminal leaves require nonzero Y.
        self.assertNotEqual(yl, params["g"]*_nonlinear(xl))
        source, bundle = self.sample(law)
        with self.assertRaises(ValueError):
            review_segments(law, source, replace(bundle, segments=(node,)), SCOPE)

    def test_z_replaced_even_when_terminal_unchanged(self):
        law = Law()
        source, bundle = self.sample(law)
        forged = replace(bundle.segments[0], z="0")
        with self.assertRaisesRegex(ValueError, "martingale"):
            review_segments(law, source,
                            replace(bundle, segments=(forged,)+bundle.segments[1:]), SCOPE)

    def test_leaf_with_forged_independently_observed_value_rejected(self):
        law = Law()
        source, bundle = self.sample(law)
        bad = replace(bundle.terminals[0], y="0")
        with self.assertRaises(ValueError):
            review_segments(law, source,
                            replace(bundle, terminals=(bad,)+bundle.terminals[1:]), SCOPE)

    def test_missing_duplicate_reordered_and_noncanonical_paths_rejected(self):
        law = Law()
        source, bundle = self.sample(law)
        variants = (
            bundle.segments[:-1],
            (bundle.segments[0],)+bundle.segments[:-1],
            tuple(reversed(bundle.segments)),
            (replace(bundle.segments[0], path="LL"),)+bundle.segments[1:],
        )
        for segments in variants:
            with self.subTest(segments=segments[:2]), self.assertRaises(ValueError):
                review_segments(law, source, replace(bundle, segments=segments), SCOPE)

    def test_exact_source_receipt_scope_and_cross_epoch_mixing(self):
        law = Law()
        source, bundle = self.sample(law)
        mutations = (
            replace(bundle, scope_digest="b"*64),
            replace(bundle, original_receipt_sha256="0"*64),
            replace(bundle, segments=(replace(bundle.segments[0], scope_digest="b"*64),)
                    +bundle.segments[1:]),
        )
        for wrong in mutations:
            with self.subTest(mutation=wrong.scope_digest), self.assertRaises(ValueError):
                review_segments(law, source, wrong, SCOPE)
        with self.assertRaises(ValueError):
            review_segments(law, source, bundle, "b"*64)

    def test_contraction_bounds_cannot_be_forged_smaller(self):
        law = Law()
        source, bundle = self.sample(law)
        for key in ("claimed_residual", "claimed_global_error_bound", "claimed_contraction"):
            with self.subTest(field=key), self.assertRaises(ValueError):
                review_segments(law, source, replace(bundle, **{key: "0"}), SCOPE)

    def test_mutation_of_original_source_receipt_cannot_be_hidden(self):
        law = Law()
        source, bundle = self.sample(law)
        with self.assertRaises(ValueError):
            review_segments(law, replace(source, mapped_residual="0"), bundle, SCOPE)
        with self.assertRaises(ValueError):
            review_segments(Law(depth=1), source, bundle, SCOPE)

    def test_rational_boundary_parser_rejects_ambiguous_numbers(self):
        law = Law()
        source, bundle = self.sample(law)
        for bad in ("01", "-0", "0/2", "1.0", "NaN", "inf", "2/4", "-", "9"*2600):
            with self.subTest(bad=bad[:25]), self.assertRaises(ValueError):
                changed = replace(bundle.segments[0], x_start=bad)
                review_segments(law, source,
                                replace(bundle, segments=(changed,)+bundle.segments[1:]), SCOPE)

    def test_authority_and_unproven_capacity_flags_fail_closed(self):
        law = Law()
        source, bundle = self.sample(law)
        for key, val in (("authority", "ALLOW"), ("production_accepted", True),
                         ("general_fbsde_wellposedness_proven", True),
                         ("natural_reasoning_gain_proven", True)):
            with self.subTest(flag=key), self.assertRaises(ValueError):
                review_segments(law, source, replace(bundle, **{key: val}), SCOPE)


if __name__ == "__main__":
    unittest.main()
