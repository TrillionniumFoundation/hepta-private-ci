"""Independent exact-Fraction checks of the directed-rounding enclosure."""

from decimal import Decimal
from fractions import Fraction
import unittest

from .interval_replay import IntervalMemory, IntervalModel
from .hybrid_driver import MAXIMUM_ERROR
from .validate_q24 import SCALE


def fixture(prior=(1, 2), transition=((3, 7), (2, 9)), emission=((2, 3), (3, 4))):
    rows = ["HCSN_Q24_MODEL_V1", "a" * 64, "2 1 2 1 1", " ".join(map(str, prior)), "17"]
    rows += [" ".join(map(str, row)) for row in transition]
    rows += ["2"] + [" ".join(map(str, row)) for row in emission]
    return ("\n".join(rows) + "\n").encode()


class IntervalTests(unittest.TestCase):
    def test_exact_fraction_trajectory_stays_inside_every_enclosure(self):
        model = IntervalModel(fixture())
        state = IntervalMemory(model)
        exact = [Fraction(1, 3), Fraction(2, 3)]
        transition = [[Fraction(3, 10), Fraction(7, 10)], [Fraction(2, 11), Fraction(9, 11)]]
        emission = [[Fraction(2, 5), Fraction(3, 5)], [Fraction(3, 7), Fraction(4, 7)]]
        operations = ["T 0", "O 0 0 0", "T 0", "O 0 0 1"] * 16
        for operation in operations:
            state.apply(operation)
            if operation.startswith("T"):
                exact = [sum(exact[i] * transition[i][j] for i in range(2)) for j in range(2)]
            else:
                token = int(operation[-1])
                raw = [exact[i] * emission[i][token] for i in range(2)]
                exact = [value / sum(raw) for value in raw]
            for p, low, high in zip(exact, state.lower[0], state.upper[0]):
                self.assertLessEqual(Fraction(low), p)
                self.assertLessEqual(p, Fraction(high))
            q = state.quantized(MAXIMUM_ERROR)
            error = sum(abs(p - Fraction(count, SCALE)) for p, count in zip(exact, q["counts"][0]))
            self.assertLessEqual(error, Fraction(q["l1_bound_units"][0], SCALE))

    def test_rare_supported_observation_gets_exact_posterior_without_epsilon(self):
        source = fixture(prior=(2 ** 80 - 1, 1), emission=((1, 0), (0, 1)))
        state = IntervalMemory(IntervalModel(source))
        state.apply("O 0 0 1")
        self.assertEqual(state.lower, [[Decimal(0), Decimal(1)]])
        self.assertEqual(state.upper, state.lower)
        self.assertEqual(state.quantized(MAXIMUM_ERROR)["counts"], [[0, SCALE]])
        self.assertEqual(state.quantized(MAXIMUM_ERROR)["l1_bound_units"], [0])

    def test_restore_preserves_bounds_exactly_then_replays_identically(self):
        model = IntervalModel(fixture())
        original = IntervalMemory(model)
        for _ in range(11):
            original.apply("T 0")
            original.apply("O 0 0 0")
        payload = original.export()
        restored = IntervalMemory.restore(model, payload)
        self.assertEqual(payload, restored.export())
        for operation in ["T 0", "O 0 0 1", "W 0 1"] * 5:
            original.apply(operation)
            restored.apply(operation)
        self.assertEqual(original.export(), restored.export())

    def test_corrupt_or_other_model_cache_is_rejected(self):
        model = IntervalModel(fixture())
        payload = IntervalMemory(model).export()
        payload["completed"] = 5
        with self.assertRaisesRegex(ValueError, "checksum"):
            IntervalMemory.restore(model, payload)
        payload = IntervalMemory(model).export()
        other = IntervalModel(fixture() + b"\n")
        with self.assertRaisesRegex(ValueError, "model/schema/precision"):
            IntervalMemory.restore(other, payload)

    def test_wide_certificate_is_refused_and_zero_evidence_is_not_repaired(self):
        model = IntervalModel(fixture(emission=((1, 0), (0, 1))))
        state = IntervalMemory(model)
        state.lower, state.upper = [[Decimal(0), Decimal(0)]], [[Decimal(1), Decimal(1)]]
        with self.assertRaisesRegex(ArithmeticError, "fixed precision budget"):
            state.quantized(MAXIMUM_ERROR)
        with self.assertRaisesRegex(ArithmeticError, "positive interval lower bound"):
            state.apply("O 0 0 1")


if __name__ == "__main__":
    unittest.main()
