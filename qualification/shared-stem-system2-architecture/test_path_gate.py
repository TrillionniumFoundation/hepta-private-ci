"""Exact rational global-path controls, not neural FBSDE success receipts."""
import unittest
from path_gate import Edge, check_two_sided_path


class GlobalPathTest(unittest.TestCase):
    def test_true_global_trajectory(self):
        # x0=1, g=1, T=1/2 -> Y=2, X_T=2
        edges = [
            Edge("1/4", "1", "3/2", "2", "2"),
            Edge("1/4", "3/2", "2", "2", "2"),
        ]
        result = check_two_sided_path(edges, x0="1", terminal_gain="1")
        self.assertTrue(result.globally_consistent)
        self.assertEqual(result.authority, "DENY_ALL")

    def test_local_unique_wrong_reset_is_not_global(self):
        # Two individually solved intervals; Y jumps at internal boundary.
        edges = [
            Edge("1/4", "1", "1", "0", "0"),
            Edge("1/4", "1", "4/3", "4/3", "4/3"),
        ]
        result = check_two_sided_path(edges, x0="1", terminal_gain="1")
        self.assertFalse(result.globally_consistent)
        self.assertEqual(result.reason, "two_sided_or_terminal_residual")
        self.assertEqual(result.max_residual, "4/3")

    def test_wrong_final_terminal(self):
        result = check_two_sided_path(
            [Edge("1/4", "1", "1", "0", "0")],
            x0="1", terminal_gain="1",
        )
        self.assertFalse(result.globally_consistent)

    def test_zero_dynamics_negative_gain(self):
        # Y=-1/(1+1/4)=-4/5 and X_T=4/5.
        result = check_two_sided_path(
            [Edge("1/4", "1", "4/5", "-4/5", "-4/5")],
            x0="1", terminal_gain="-1",
        )
        self.assertTrue(result.globally_consistent)

    def test_pole_rejected(self):
        result = check_two_sided_path(
            [Edge("1", "0", "0", "0", "0")], x0="0", terminal_gain="1"
        )
        self.assertFalse(result.globally_consistent)
        self.assertEqual(result.reason, "nonregular_or_nonunique_global_boundary")

    def test_algebraic_unique_but_nonregular(self):
        # Zero path trivially solves endpoint relation but field crosses pole.
        result = check_two_sided_path(
            [Edge("2", "0", "0", "0", "0")], x0="0", terminal_gain="1"
        )
        self.assertFalse(result.globally_consistent)
        self.assertEqual(result.reason, "regular_field_crosses_pole")

    def test_forward_discontinuity(self):
        result = check_two_sided_path(
            [Edge("1/4", "1", "1", "0", "0"),
             Edge("1/4", "5/4", "5/4", "0", "0")],
            x0="1", terminal_gain="0",
        )
        self.assertFalse(result.globally_consistent)

    def test_bad_inputs_fail_closed(self):
        cases = [
            ([Edge("0", "1", "1", "0", "0")], {}),
            ([Edge("-1", "1", "1", "0", "0")], {}),
            ([Edge("5", "1", "1", "0", "0")], {}),
            ([Edge("1/4", "NaN", "1", "0", "0")], {}),
            ([Edge("1/4", "1", "1", "0", "0")], {"x0": "not-number"}),
        ]
        for edges, overrides in cases:
            with self.subTest(edges=edges, overrides=overrides):
                with self.assertRaises(ValueError):
                    check_two_sided_path(edges, x0="1", terminal_gain="1",
                                         **overrides) if not overrides else check_two_sided_path(
                                             edges, terminal_gain="1", **overrides)

    def test_excessive_length(self):
        with self.assertRaises(ValueError):
            check_two_sided_path([Edge("1/8", "1", "1", "0", "0")] * 33,
                                 x0="1", terminal_gain="0")


if __name__ == "__main__":
    unittest.main()
