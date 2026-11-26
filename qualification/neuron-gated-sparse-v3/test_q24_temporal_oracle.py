"""Independent arithmetic-only Q24 oracle tests, never performance evidence."""
import unittest

import q24_temporal_oracle as oracle


class TemporalOracleTests(unittest.TestCase):
    def test_frozen_vectors_stay_stable(self) -> None:
        oracle.check()
        self.assertEqual(len(oracle.generate()["rows"]), 5)

    def test_ties_to_even_for_both_signs(self) -> None:
        self.assertEqual(oracle.q24_mul(1, oracle.Q // 2), 0)
        self.assertEqual(oracle.q24_mul(3, oracle.Q // 2), 2)
        self.assertEqual(oracle.q24_mul(-3, oracle.Q // 2), -2)
        self.assertEqual(oracle.q24_mul(-1, oracle.Q // 2), 0)

    def test_time_scaling_uses_ceil_and_rejects_nonpositive_gap(self) -> None:
        self.assertEqual(oracle.ssm_step(0, oracle.Q, 100, 101)[0], 1)
        self.assertEqual(oracle.ssm_step(0, oracle.Q, 100, 200)[0], 1)
        self.assertEqual(oracle.ssm_step(0, oracle.Q, 100, 201)[0], 2)
        with self.assertRaises(AssertionError):
            oracle.ssm_step(0, oracle.Q, 100, 100)

    def test_gate_is_bounded_for_extreme_drive(self) -> None:
        for old in (-oracle.H, 0, oracle.H):
            for drive in (-oracle.H, 0, oracle.H):
                gate, state = oracle.gate_step(old, drive)
                self.assertGreaterEqual(gate, 0)
                self.assertLessEqual(gate, oracle.Q)
                self.assertGreaterEqual(state, -oracle.H)
                self.assertLessEqual(state, oracle.H)


if __name__ == "__main__":
    unittest.main()
