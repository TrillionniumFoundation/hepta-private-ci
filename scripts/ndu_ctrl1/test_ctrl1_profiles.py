"""Pin operator compatibility and the different deterministic numeric profile."""

from dataclasses import replace
from fractions import Fraction
import json
from pathlib import Path
import unittest

from ndu_real_runtime.objective import certainty_equivalent, edge_value
from .evaluation import evaluate
from .model import Profile, Scenario
from .policies import Controller


class ProfileCompatibilityTests(unittest.TestCase):
    def test_existing_native_shared_entropic_golden_vectors(self):
        path = (
            Path(__file__).parents[1] / "ndu_real_runtime/finite_entropic_golden.json"
        )
        goldens = json.loads(path.read_bytes())
        for case in goldens["certainty_equivalent"]:
            actual = certainty_equivalent(
                case["values"], case["probabilities"], case["risk"]
            )
            self.assertAlmostEqual(actual, case["expected"], places=13)
        case = goldens["duration_branch"]
        profile = Profile(
            risk=case["risk"],
            discount_per_second=case["discount_per_second"],
            latency_weight=case["latency_weight"],
        )
        edges = [
            edge_value(t, v, profile)
            for t, v in zip(case["durations_seconds"], case["continuations"])
        ]
        self.assertEqual(edges, case["edges"])
        self.assertAlmostEqual(
            certainty_equivalent(edges, case["probabilities"], profile.risk),
            case["expected"],
            places=13,
        )

    def test_separate_q32_reference_matches_pinned_deterministic_fixture(self):
        # Independent Python integer reference for the pinned Rust fixture,
        # not a claim that the Rust executable ran or that FP64 is byte-equal.
        q = 1 << 32

        def path(sign=1, discount=3_435_973_837, upper=8 * q):
            values = [sign * q]
            for instant in (sign * q // 4, sign * q // 2):
                value = instant + round(Fraction(discount * values[0], q))
                values.insert(0, max(-8 * q, min(upper, value)))
            return values

        self.assertEqual(path(), [5_755_256_177, 4_509_715_661, q])
        self.assertEqual(path(-1), [-5_755_256_177, -4_509_715_661, -q])
        self.assertEqual(path(discount=0), [q // 2, q // 4, q])
        self.assertEqual(path(discount=q)[0], 7 * q // 4)
        self.assertEqual(path(upper=q), [q, q, q])
        self.assertEqual(round(Fraction(1, 2)), 0)
        self.assertEqual(round(Fraction(-3, 2)), -2)
        with self.assertRaises(ValueError):
            replace(Profile(), discount_per_second=0)

    def test_compute_then_stop_regret_cannot_hide_exhausted_budget(self):
        scenario = Scenario(prior=Fraction(4, 5), budget=4, deadline=4, horizon=1)
        result = evaluate(scenario, Profile(), Controller("mpc", Profile()))
        self.assertEqual(result["stop_regret"], 0)
        self.assertGreater(result["compute_and_stop_regret"], 0.4)
        self.assertAlmostEqual(result["compute_and_stop_regret"], result["policy_gap"])


if __name__ == "__main__":
    unittest.main()
