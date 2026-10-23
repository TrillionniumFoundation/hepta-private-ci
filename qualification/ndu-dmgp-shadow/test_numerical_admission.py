"""Numerical and metering adversarial regressions: fail closed, never promote."""
import unittest
from dataclasses import replace

from reference import (
    Action, Freeze, GenerationState, Outcome, RiskEstimate, Unavailable,
    WorkReceipt, allocate, compare_work, recursive_stop_choice,
)

F = Freeze("fixed-objective", 3, "actor", "critic", "observer", "critic-digest", "feature-digest")
A = (Action("caption", "text", 100), Action("picture", "image", 200))
R = RiskEstimate((.3, .4), ((.1, .02), (.02, .2)), 32, "text-image", 4.0, 2)


class FailClosedNumericalTests(unittest.TestCase):
    def test_generation_cannot_be_boolean(self):
        for invalid in (True, 0, 1.5):
            with self.subTest(invalid=invalid), self.assertRaises(Unavailable):
                replace(F, generation=invalid).validate()

    def test_utility_cannot_be_boolean(self):
        outcome = Outcome("e", "A0", F.objective, F.generation, F.observer,
                          F.actor, F.critic_digest, "source", "future", .5,
                          100, 50, 10, "execution")
        with self.assertRaisesRegex(Unavailable, "unbounded"):
            replace(outcome, observed_utility=True).validate(F)

    def test_durations_are_exact_bounded_integers(self):
        outcome = Outcome("e", "A0", F.objective, F.generation, F.observer,
                          F.actor, F.critic_digest, "source", "future", .5,
                          100, 50, 10, "execution")
        for invalid in (True, 1.0, float("inf"), float("nan"), -1, 10**13):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(Unavailable, "invalid physical cost"):
                    replace(outcome, decoder_us=invalid).validate(F)

    def test_work_receipts_reject_invalid_host_metrics(self):
        b = (WorkReceipt("episode", "run-a", 100, 10, 10, 4096, True),)
        c = (WorkReceipt("episode", "run-b", 100, 10, 10, 4096, True),)
        for invalid in (True, 0.5, float("inf"), float("nan"), -1):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(Unavailable, "invalid metric"):
                compare_work(b, (replace(c[0], peak_rss_bytes=invalid),))
        with self.assertRaisesRegex(Unavailable, "invalid metric"):
            compare_work(b, (replace(c[0], measured_on_host=1),))

    def test_covariance_nonfinite_means_and_entries_rejected(self):
        for invalid in (float("nan"), float("inf"), True):
            with self.subTest(invalid=invalid), self.assertRaises(Unavailable):
                allocate(A, replace(R, means=(invalid, .4)), 300, 1.0, .01, (.5, .5))
            with self.subTest(entry=invalid), self.assertRaises(Unavailable):
                allocate(A, replace(R, covariance=((.1, invalid), (invalid, .2))),
                         300, 1.0, .01, (.5, .5))

    def test_covariance_wrong_shape_and_asymmetry_rejected(self):
        for r in (
            replace(R, covariance=((.1,),)),
            replace(R, covariance=((.1, .02), (.03, .2))),
            replace(R, covariance=((.1, .2), (.2, .1))),
        ):
            with self.subTest(cov=r.covariance), self.assertRaises(Unavailable):
                allocate(A, r, 300, 1.0, .01, (.5, .5))

    def test_covariance_support_and_conditional_profile_required(self):
        for r in (
            replace(R, sample_count=3),
            replace(R, condition_upper=float("nan")),
            replace(R, condition_upper=2e8),
            replace(R, rank_retained=10),
            replace(R, context=""),
        ):
            with self.subTest(profile=r), self.assertRaises(Unavailable):
                allocate(A, r, 300, 1.0, .01, (.5, .5))

    def test_invalid_routes_never_enter_optimizer(self):
        for actions in (
            (Action("x", "text", True),),
            (Action("x", "video", 1.5),),
            (Action("x", "unknown", 100),),
            (Action("x", "text", 100), Action("x", "image", 100)),
        ):
            with self.subTest(actions=actions), self.assertRaises(Unavailable):
                allocate(actions, None, 300, 1.0, .01, tuple([1/len(actions)] * len(actions)))

    def test_nonfinite_continuation_prices_rejected(self):
        state = GenerationState(3, 1000, 2, .4)
        for invalid in (float("inf"), float("nan"), True):
            with self.subTest(invalid=invalid), self.assertRaises(Unavailable):
                recursive_stop_choice(state, A, {"caption": .1, "picture": .2},
                                      cost_per_us=invalid)
        with self.assertRaises(Unavailable):
            recursive_stop_choice(state, (replace(A[0], work_us=True),),
                                  {"caption": .1})


if __name__ == "__main__":
    unittest.main()
