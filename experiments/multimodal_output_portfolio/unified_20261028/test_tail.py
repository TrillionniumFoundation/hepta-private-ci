"""Statistical regression checks for selected-policy and source independence."""

from dataclasses import replace
import math
import unittest

from .profile import CostEvent, DeliveredOutcome, NduProfile, digest
from .tail import JointEvent, calibrate_selected, success_lower_bound


class SelectedTailTests(unittest.TestCase):
    def setUp(self):
        self.profile = NduProfile(digest("objective"), digest("observer"), digest("actual-continuation"),
                                  utility_bounds=(-2.0, 1.0))
        self.policy = digest("frozen-policy-before-independent-calibration")

    def event(self, i, utility=1.0, cost=0.002, terminal="delivered"):
        outcome = DeliveredOutcome("public-context", f"draw-{i}", f"source-{i}", utility,
            (CostEvent(f"cost-{i}", cost),), (("text", digest(f"text-{i}")), ("image", digest(f"image-{i}"))),
            self.profile.observer_sha256, self.profile.objective_sha256,
            self.profile.continuation_sha256, terminal)
        return JointEvent(f"event-{i}", (f"source-{i}",), "swap", "swap", -1, outcome,
                          self.policy, self.profile.digest, digest(f"executed-{i}"))

    def fit(self, events, **kwargs):
        return calibrate_selected(events, self.profile, policy_sha256=self.policy,
                                  net_return_bounds=(-2.002, 0.998), excluded_source_ids=("training-1",),
                                  **kwargs)

    def test_seventy_successes_do_not_certify_entropic_commit(self):
        result = self.fit([self.event(i) for i in range(70)], method="two_point")
        self.assertAlmostEqual(result["success_probability_lower"], 0.9581066559669077)
        # A mean-probability rule historically accepted this cohort; the tail
        # upper bound must refuse comparison with the zero-return stop action.
        jeffreys_mean = 70.5 / 71
        old_moment = jeffreys_mean * math.exp(-1.996) + (1 - jeffreys_mean) * math.exp(4.004)
        self.assertLess(old_moment, 1)
        self.assertGreater(result["moment_upper"], 1)
        self.assertLess(result["ce_lower"], 0)

    def test_duplicate_event_is_idempotent_but_shared_source_is_not_independent(self):
        event = self.event(1)
        self.assertEqual(self.fit([event]), self.fit([event, event]))
        with self.assertRaisesRegex(ValueError, "sources overlap"):
            self.fit([event, replace(self.event(2), source_ids=event.source_ids)])
        with self.assertRaisesRegex(ValueError, "sources overlap"):
            self.fit([replace(event, source_ids=("training-1",))])
        with self.assertRaisesRegex(ValueError, "Conflicting repeated event"):
            self.fit([event, replace(event, feedback=1)])
        reused_cluster = self.event(2)
        reused_cluster = replace(reused_cluster, outcome=replace(
            reused_cluster.outcome, source_cluster_id=event.outcome.source_cluster_id))
        with self.assertRaisesRegex(ValueError, "source clusters overlap"):
            self.fit([event, reused_cluster])

    def test_failure_and_variable_cost_stay_in_selected_action_law(self):
        events = [self.event(1), self.event(2, utility=-1.0, cost=0.4, terminal="failed")]
        result = self.fit(events)
        expected = (math.exp(-2 * 0.998) + math.exp(-2 * -1.4)) / 2
        self.assertAlmostEqual(result["empirical_moment"], expected)
        self.assertEqual(result["terminal_counts"], {"delivered": 1, "failed": 1, "refused": 0})
        with self.assertRaisesRegex(ValueError, "two-point"):
            self.fit(events, method="two_point")

    def test_stale_policy_profile_or_action_selection_is_rejected(self):
        event = self.event(1)
        for changed in (replace(event, policy_sha256=digest("new-policy")),
                        replace(event, profile_sha256=digest("new-objective")),
                        replace(event, selection_key="post-hoc-good-rows")):
            with self.assertRaisesRegex(ValueError, "differs from execution"):
                self.fit([changed])

    def test_conditional_risk_cannot_pool_opposite_public_contexts(self):
        # Deterministic opposite-context payoffs have an average conditional CE
        # different from their pooled entropic CE, even with equal task weights.
        easy, hard = self.event(1), self.event(2, utility=-1.0)
        hard = replace(hard, outcome=replace(hard.outcome, context_id="hard-context"))
        self.assertEqual(self.fit([easy, hard])["independent_events"], 2)
        self.profile = replace(self.profile, aggregation="conditional")
        easy, hard = (replace(event, profile_sha256=self.profile.digest) for event in (easy, hard))
        with self.assertRaisesRegex(ValueError, "Conditional calibration cannot pool"):
            self.fit([easy, hard])
        same_context = replace(hard, outcome=replace(hard.outcome, context_id=easy.outcome.context_id))
        self.assertEqual(self.fit([easy, same_context])["independent_events"], 2)

    def test_declared_support_and_family_correction(self):
        with self.assertRaisesRegex(ValueError, "exceeds declared"):
            self.fit([self.event(1, utility=-2, cost=1)])
        events = [self.event(i) for i in range(100)]
        self.assertGreaterEqual(self.fit(events, family_size=8)["moment_upper"],
                                self.fit(events)["moment_upper"])
        empty = self.fit([], method="two_point")
        self.assertEqual(empty["independent_events"], 0)
        self.assertAlmostEqual(empty["ce_lower"], -2.002)

    def test_zero_risk_limit_and_nontrivial_exact_binomial_bound(self):
        self.profile = replace(self.profile, gamma=0)
        result = self.fit([self.event(i) for i in range(10000)], method="two_point")
        self.assertGreater(result["ce_lower"], 0.99)
        self.assertAlmostEqual(success_lower_bound(5, 10, 0.05), 0.222441101008129)

    def test_near_zero_risk_empty_evidence_retains_worst_case(self):
        for gamma in (0.0, 1e-18, 1e-16, 1e-12):
            self.profile = replace(self.profile, gamma=gamma)
            self.assertAlmostEqual(self.fit([])["ce_lower"], -2.002, places=12)


if __name__ == "__main__":
    unittest.main()
