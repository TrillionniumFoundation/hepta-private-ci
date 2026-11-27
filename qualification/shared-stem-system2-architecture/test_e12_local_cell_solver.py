"""Oracle-free local computation vs independent E12 verification and cheap control."""
from dataclasses import replace
from fractions import Fraction as Q
from unittest.mock import patch
import unittest

from e12_nonlinear_cert import Law, operator, solve
from e12_independent_audit import audit
from e12_cell_boundary import review_segments, split_result
from e12_local_cell_solver import (
    _cell_backward, _cell_forward, _local_sweep, _round_even, solve_local_cells,
)


class LocalCellSolverTest(unittest.TestCase):
    def test_six_stochastic_laws_exact_reference_parity_and_audit(self):
        for depth in (1, 2, 3):
            for a in ("0", "1/3"):
                with self.subTest(depth=depth, a=a):
                    law = Law(depth=depth, a=a)
                    proposal = solve_local_cells(law)
                    baseline = solve(law)
                    # Ignore observed runtime, retain exact mathematical shape.
                    ours = replace(proposal.result, cpu_ns=baseline.cpu_ns,
                                   wall_ns=baseline.wall_ns)
                    self.assertEqual(ours, baseline)
                    self.assertTrue(audit(law, proposal.result).certified)
                    scope = "a" * 64
                    self.assertEqual(
                        review_segments(law, proposal.result,
                                        split_result(law, proposal.result, scope), scope)
                        .exact_backward_interfaces, True)
                    self.assertEqual(proposal.forward_cell_invocations,
                                     proposal.backward_cell_invocations)
                    self.assertEqual(proposal.reference_operator_calls, 0)
                    self.assertEqual(proposal.authority, "DENY_ALL")

    def test_forward_solver_does_not_call_reference_solver_or_operator(self):
        with patch("e12_nonlinear_cert.solve", side_effect=RuntimeError("oracle")), \
             patch("e12_nonlinear_cert.operator", side_effect=RuntimeError("oracle")), \
             patch("e12_nonlinear_cert.build_trace", side_effect=RuntimeError("oracle")):
            result = solve_local_cells(Law(depth=3, a="1/3"))
        self.assertLessEqual(Q(result.result.fixed_point_error_bound), Q(1, 10000))
        self.assertGreater(result.forward_cell_invocations, 7)

    def test_one_message_sees_only_local_values(self):
        law = Law(depth=1)
        p = law.values()
        message = _cell_forward("", Q(1), Q(1, 4), p)
        self.assertEqual(message.x_left, Q(1) + p["a"] * p["h"] * Q(4, 17) - p["sigma"] * p["s"])
        self.assertEqual(message.x_right - message.x_left, 2 * p["sigma"] * p["s"])
        backwards = _cell_backward("", Q(1), Q(2, 7), Q(3, 7), p)
        self.assertEqual(backwards.z * 2 * p["s"], Q(1, 7))

    def test_local_sweep_identical_to_mathematical_operator_but_independent(self):
        law = Law(depth=3)
        p = law.values()
        guess = (Q(1, 16),) * 7
        self.assertEqual(_local_sweep(law, guess, p).mapped_y, operator(law, guess))

    def test_zero_coupling_has_one_direct_map_and_positive_coupling_does_not(self):
        for a in ("0", "1/3"):
            law = Law(depth=3, a=a)
            p = law.values()
            zeros = (Q(0),) * 7
            first = _local_sweep(law, zeros, p).mapped_y
            next_map = _local_sweep(law, first, p).mapped_y
            residual = max(abs(v - w) for v, w in zip(first, next_map))
            if a == "0":
                self.assertEqual(residual, 0)
            else:
                self.assertGreater(residual / (1 - p["q"]), Q(1, 10000))

    def test_rejected_invalid_precision_and_nonconvergent_budget(self):
        for kwargs in ({"max_calls": 0}, {"max_calls": True},
                       {"bits": True}, {"bits": 6},
                       {"tolerance": "0"}, {"tolerance": "1/2"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                solve_local_cells(Law(), **kwargs)
        with self.assertRaises(ValueError):
            solve_local_cells(Law(depth=3), max_calls=1)

    def test_global_contraction_obstruction_not_bypassed_by_short_cells(self):
        with self.assertRaises(ValueError):
            solve_local_cells(Law(depth=3, a="1", g="1", beta="1", horizon="2"))

    def test_exact_round_even_positive_and_negative_ties(self):
        self.assertEqual(_round_even(Q(1, 131072), 16), Q(0))
        self.assertEqual(_round_even(Q(3, 131072), 16), Q(1, 32768))
        self.assertEqual(_round_even(Q(-3, 131072), 16), Q(-1, 32768))

    def test_reviewer_rejects_forged_local_z_or_terminal(self):
        law = Law(depth=3)
        r = solve_local_cells(law).result
        scope = "b" * 64
        bundle = split_result(law, r, scope)
        wrong_z = list(bundle.segments)
        wrong_z[0] = replace(wrong_z[0], z="0")
        with self.assertRaises(ValueError):
            review_segments(law, r, replace(bundle, segments=tuple(wrong_z)), scope)
        bad_leaf = list(bundle.terminals)
        bad_leaf[0] = replace(bad_leaf[0], y="0")
        with self.assertRaises(ValueError):
            review_segments(law, r, replace(bundle, terminals=tuple(bad_leaf)), scope)

    def test_quantization_exhaustion_does_not_publish_fake_solution(self):
        with self.assertRaises(ValueError):
            solve_local_cells(Law(depth=3), bits=12, tolerance="1/1000000", max_calls=2)


if __name__ == "__main__":
    unittest.main()
