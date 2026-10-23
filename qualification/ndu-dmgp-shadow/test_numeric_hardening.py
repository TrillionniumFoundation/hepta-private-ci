"""Adversarial numerical and accounting regressions for the A0-A5 shadow gate.

No test here authenticates external outcomes, physical metering or deployment.
The fixed toy cases exercise fail-closed source-level input admission.
"""
from dataclasses import replace
from math import cos, inf, nan, sin
import unittest

from reference import (
    Action, Freeze, GenerationState, JointSample, Outcome, RiskEstimate,
    Unavailable, WorkReceipt, allocate, compare_work, joint_covariance,
    recursive_stop_choice, symmetric_eigenvalues,
)

F = Freeze("objective-risk-adversarial-v1", 2, "actor", "critic", "observer",
           "critic-frozen", "encoder-frozen")
ACTIONS = (Action("text", "text", 100), Action("image", "image", 200))


class SpectralRiskAdmission(unittest.TestCase):
    def test_exact_symmetric_2x2_spectrum(self):
        self.assertEqual(symmetric_eigenvalues([[2.0, 1.0], [1.0, 2.0]]),
                         (1.0, 3.0))
        roots = symmetric_eigenvalues([[1.0, .99999], [.99999, 1.0]])
        self.assertAlmostEqual(roots[1] / roots[0], 199999.0, delta=.01)

    def test_near_collinear_raw_support_cannot_be_manufactured_by_shrinkage(self):
        # Cholesky pivot ratio ~435,633: below 1e6.
        # Actual eigenvalue ratio ~1,742,632: above 1e6.
        # Older code admitted this fabricated 'identified' matrix.
        eps = .0015
        rows = tuple(JointSample(
            str(i), "paired-realization", F.objective, F.observer,
            (.25 * sin(i * .7),
             .25 * (sin(i * .7) + eps * cos(i * .4))))
            for i in range(40))
        with self.assertRaisesRegex(Unavailable, "raw spectral condition"):
            joint_covariance(rows, F, "paired-realization", shrink=.7)

    def test_indefinite_matrix_rejected_even_if_all_simplex_variances_positive(self):
        # Every nonnegative simplex weight has positive quadratic score for
        # [[1,2],[2,1]], yet eigenvalue -1 makes this an invalid covariance.
        risk = RiskEstimate((.4, .5), ((1.0, 2.0), (2.0, 1.0)),
                            40, "task", 3.0, 2)
        with self.assertRaisesRegex(Unavailable, "spectrum"):
            allocate(ACTIONS, risk, 300, 1.0, .01, (.5, .5))
        self.assertEqual(allocate(ACTIONS, None, 300, 1.0, .01,
                                  (.5, .5)).profile, "deterministic-fallback")

    def test_asymmetry_and_nonfinite_covariance_rejected(self):
        for covariance, reason in [
            (((1.0, .2), (.3, 1.0)), "asymmetric"),
            (((1.0, nan), (nan, 1.0)), "nonfinite"),
            (((1.0, inf), (inf, 1.0)), "nonfinite"),
            (((1.0, 2.0), (2.0,)), "geometry"),
        ]:
            with self.subTest(covariance=covariance):
                with self.assertRaisesRegex(Unavailable, reason):
                    allocate(ACTIONS, RiskEstimate((.1, .2), covariance,
                             40, "task", 3.0, 2),
                             300, 1.0, .01, (.5, .5))

    def test_unproven_risk_source_rejected(self):
        valid = RiskEstimate((.3, .4), ((.3, 0.0), (0.0, .3)),
                             40, "task", 1.0, 2)
        self.assertAlmostEqual(sum(allocate(ACTIONS, valid, 300, 1.0, .01,
                                            (.5, .5)).weights), 1.0)
        for altered in (
            replace(valid, sample_count=1),
            replace(valid, context=""),
            replace(valid, condition_upper=inf),
            replace(valid, condition_upper=1e7),
            replace(valid, means=(nan, .4)),
            replace(valid, means=(True, .4)),
            replace(valid, rank_retained=5),
        ):
            with self.subTest(altered=altered):
                with self.assertRaises(Unavailable):
                    allocate(ACTIONS, altered, 300, 1.0, .01, (.5, .5))

    def test_discrete_action_identity_and_budget_types(self):
        risk = RiskEstimate((.3, .4), ((.3, 0.0), (0.0, .3)),
                            40, "task", 1.0, 2)
        for actions, budget in (
            ((ACTIONS[0], ACTIONS[0]), 300),
            ((replace(ACTIONS[0], work_us=True), ACTIONS[1]), 300),
            ((ACTIONS[0], replace(ACTIONS[1], work_us=nan)), 300),
            (ACTIONS, True),
            (ACTIONS, -1),
        ):
            with self.subTest(actions=actions, budget=budget):
                with self.assertRaisesRegex(Unavailable, "invalid or duplicated"):
                    allocate(actions, risk, budget, 1.0, .01, (.5, .5))


class ReceiptAndRecursionBounds(unittest.TestCase):
    def test_reward_receipt_costs_must_be_true_u64_not_caller_floats(self):
        good = Outcome("e1", "A5", F.objective, F.generation,
                       F.observer, F.actor, F.critic_digest, "source",
                       "future", .6, 100, 3, 4, "run")
        good.validate(F)
        for bad in (replace(good, controller_us=nan),
                    replace(good, decoder_us=True),
                    replace(good, verifier_us=1.5),
                    replace(good, decoder_us=2**64),
                    replace(good, controller_us=-1)):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(Unavailable, "invalid physical cost"):
                    bad.validate(F)
        with self.assertRaisesRegex(Unavailable, "unbound objective"):
            replace(F, generation=True).validate()

    def test_work_receipt_cannot_fake_boolean_or_nan_physical_cost(self):
        baseline = (WorkReceipt("episode", "physical1", 1000, 20, 5, 4096, True),)
        candidate = (WorkReceipt("episode", "physical2", 800, 40, 5, 4096, True),)
        self.assertFalse(compare_work(baseline, candidate)["production_efficiency_evidence"])
        for altered in (replace(candidate[0], controller_us=nan),
                        replace(candidate[0], decoder_us=1.5),
                        replace(candidate[0], peak_rss_bytes=True),
                        replace(candidate[0], measured_on_host="true")):
            with self.subTest(altered=altered):
                with self.assertRaisesRegex(Unavailable, "invalid metric"):
                    compare_work(baseline, (altered,))

    def test_recursive_search_has_bounded_fanout_and_checked_actions(self):
        state = GenerationState(2, 1200, 3, .5)
        actions = tuple(Action(f"a{i}", "text", 10) for i in range(7))
        predicted = {a.name: .01 for a in actions}
        with self.assertRaisesRegex(Unavailable, "unbounded"):
            recursive_stop_choice(state, actions, predicted)
        with self.assertRaisesRegex(Unavailable, "unbounded"):
            recursive_stop_choice(state, (ACTIONS[0], ACTIONS[0]),
                                  {"text": .1})
        with self.assertRaisesRegex(Unavailable, "unbounded"):
            recursive_stop_choice(state, (replace(ACTIONS[0], work_us=nan),),
                                  {"text": .1})
        legal = (ACTIONS[0], ACTIONS[1])
        result = recursive_stop_choice(state, legal, {"text": .2, "image": .1},
                                       cost_per_us=.0001)
        self.assertIn(result[0], {"stop", "text", "image"})


if __name__ == "__main__":
    unittest.main()
