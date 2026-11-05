from dataclasses import replace
from fractions import Fraction
import unittest

from .stop_policy import Bound, Cohort, HardGate, Policy, Report


def fixture():
    cohort = Cohort("future-window-1", "a" * 64, "b" * 64, "c" * 64, "net-task-units", 7)
    policy = Policy(
        cohort, ("stop", "retrieve", "split"), "d" * 64, 5, ("split",), 2, (("cpu_us", 20), ("fee_micro", 8))
    )
    gates = (
        HardGate("stop", "admitted", (("cpu_us", 1), ("fee_micro", 0))),
        HardGate("retrieve", "admitted", (("cpu_us", 4), ("fee_micro", 2))),
        HardGate("split", "admitted", (("cpu_us", 10), ("fee_micro", 4))),
    )
    report = Report(
        cohort,
        "e" * 64,
        0,
        policy.support_sha256,
        (("stop", Bound(1, 2)), ("retrieve", Bound(3, 4)), ("split", None)),
        (("cpu_us", 100), ("fee_micro", 100)),
    )
    return policy, report, gates


class StopPolicyTests(unittest.TestCase):
    def test_reported_gain_is_also_rounded_outward(self):
        p, r, g = fixture()
        r = replace(r, bounds=(("stop", Bound(0.1, 0.1)), ("retrieve", Bound(1, 1)), ("split", None)))
        result = self.choose(p, r, g)
        self.assertLessEqual(Fraction(result.delta_lower), Fraction(1) - Fraction(0.1))

    def choose(self, policy, report, gates, allowance=None, available=None, **kwargs):
        return policy.propose(
            report,
            gates,
            report.available if available is None else available,
            policy.initial_allowance() if allowance is None else allowance,
            live_cohort=kwargs.get("live_cohort", policy.cohort),
            state_sha256=kwargs.get("state_sha256", report.state_sha256),
        )

    def test_uses_lower_action_minus_upper_stop_and_no_double_cost(self):
        p, r, g = fixture()
        result = self.choose(p, r, g)
        self.assertEqual((result.action, result.mode, result.delta_lower), ("retrieve", "supported_gain", 1))
        self.assertEqual(result.next_allowance.calls_left, 2)
        r = replace(r, bounds=(("stop", Bound(1, 4)), ("retrieve", Bound(3, 5)), ("split", Bound(-1, 0))))
        self.assertEqual(self.choose(p, r, g).action, "stop")

    def test_hard_permission_and_risk_denials_dominate_high_utility(self):
        p, r, g = fixture()
        r = replace(r, bounds=(("stop", Bound(1, 2)), ("retrieve", Bound(1e100, 1e101)), ("split", None)))
        g = (
            g[0],
            replace(g[1], status="rejected", reason="hard_risk"),
            replace(g[2], status="rejected", reason="no_permission"),
        )
        result = self.choose(p, r, g)
        self.assertEqual(result.action, "stop")
        self.assertEqual(result.rejected, (("retrieve", "hard_risk"), ("split", "no_permission")))

    def test_physical_cap_filters_before_scoring(self):
        p, r, g = fixture()
        r = replace(r, available=(("cpu_us", 3), ("fee_micro", 100)))
        result = self.choose(p, r, g)
        self.assertEqual(result.action, "stop")
        self.assertEqual(dict(result.rejected)["retrieve"], "resource_limit")
        with self.assertRaisesRegex(ValueError, "axes differ"):
            self.choose(p, r, g, available=(("cpu_us", 100),))

    def test_failed_research_attempts_exhaust_precommitted_calls_and_cost(self):
        p, r, g = fixture()
        r = replace(r, bounds=(("stop", Bound(1, 2)), ("retrieve", Bound(0, 1)), ("split", None)))
        first = self.choose(p, r, g)
        self.assertEqual((first.action, first.mode), ("split", "research"))
        # No success field can refund a failed training attempt.
        second = self.choose(p, replace(r, look=1), g, first.next_allowance)
        third = self.choose(p, replace(r, look=2), g, second.next_allowance)
        self.assertEqual((second.action, third.action), ("split", "stop"))
        self.assertEqual(second.next_allowance.resources_left, (("cpu_us", 0), ("fee_micro", 0)))

    def test_research_resources_can_exhaust_before_calls(self):
        p, r, g = fixture()
        p = replace(p, exploration_resources=(("cpu_us", 9), ("fee_micro", 100)))
        r = replace(r, bounds=(("stop", Bound(1, 2)), ("retrieve", None), ("split", None)))
        self.assertEqual(self.choose(p, r, g).action, "stop")

    def test_known_negative_is_not_explored_but_uncertainty_is(self):
        p, r, g = fixture()
        r = replace(r, bounds=(("stop", Bound(1, 2)), ("retrieve", Bound(0, 1)), ("split", Bound(-3, 1))))
        self.assertEqual(self.choose(p, r, g).action, "stop")
        r = replace(r, bounds=(r.bounds[0], r.bounds[1], ("split", Bound(-3, 3))))
        self.assertEqual(self.choose(p, r, g).mode, "research")

    def test_cohort_drift_state_and_support_substitution_reject(self):
        p, r, g = fixture()
        for changes in (
            {"critic_sha256": "f" * 64},
            {"unit": "USD"},
            {"generation": 8},
            {"objective_sha256": "f" * 64},
            {"continuation_sha256": "f" * 64},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.choose(p, r, g, live_cohort=replace(p.cohort, **changes))
        with self.assertRaisesRegex(ValueError, "state"):
            self.choose(p, r, g, state_sha256="f" * 64)
        with self.assertRaisesRegex(ValueError, "support"):
            self.choose(p, replace(r, support_sha256="f" * 64), g)

    def test_pinned_monitoring_horizon_and_caller_balance_reject_replay(self):
        p, r, g = fixture()
        result = self.choose(p, r, g)
        with self.assertRaisesRegex(ValueError, "replayed"):
            self.choose(p, r, g, result.next_allowance)
        with self.assertRaises(ValueError):
            self.choose(p, replace(r, look=5), g, replace(p.initial_allowance(), next_look=5))
        with self.assertRaisesRegex(ValueError, "other policy"):
            self.choose(p, r, g, replace(p.initial_allowance(), policy_sha256="f" * 64))

    def test_unknown_stop_or_inadmissible_stop_never_manufactures_a_gain(self):
        p, r, g = fixture()
        p = replace(p, exploration_calls=0)
        r = replace(r, bounds=(("stop", None), r.bounds[1], r.bounds[2]))
        self.assertEqual(self.choose(p, r, g).mode, "stop")
        with self.assertRaisesRegex(ValueError, "fallback"):
            self.choose(p, r, (replace(g[0], status="rejected", reason="delivery_forbidden"), *g[1:]))

    def test_missing_and_duplicate_action_rosters_reject(self):
        p, r, g = fixture()
        for malformed in (g[:-1], (g[0], g[1], g[1])):
            with self.assertRaises(ValueError):
                self.choose(p, r, malformed)
        with self.assertRaises(ValueError):
            self.choose(p, replace(r, bounds=(r.bounds[0], r.bounds[1], r.bounds[1])), g)

    def test_request_binding_changes_with_resource_observation(self):
        p, r, g = fixture()
        first = self.choose(p, r, g)
        self.assertEqual(first, self.choose(p, r, g))
        available = (("cpu_us", 50), ("fee_micro", 100))
        with self.assertRaisesRegex(ValueError, "stale resource"):
            self.choose(p, r, g, available=available)
        second = self.choose(p, replace(r, available=available), g)
        self.assertNotEqual(first.request_sha256, second.request_sha256)

    def test_nonfinite_bounds_and_unknown_resources_reject(self):
        for bounds in ((float("nan"), 1), (0, float("inf")), (2, 1), (True, 2)):
            with self.assertRaises(ValueError):
                Bound(*bounds)
        p, r, g = fixture()
        with self.assertRaises(ValueError):
            self.choose(p, r, (g[0], replace(g[1], envelope=(("cpu_us", 2),)), g[2]))

    def test_log_moment_conversion_reverses_endpoints_and_choice_order(self):
        p, r, g = fixture()
        stop, action = Bound.from_log_moment(2, 4, 2), Bound.from_log_moment(0, 1, 2)
        self.assertEqual((stop, action), (Bound(-2, -1), Bound(-0.5, 0)))
        r = replace(r, bounds=(("stop", stop), ("retrieve", action), ("split", None)))
        self.assertEqual(self.choose(p, r, g).delta_lower, 0.5)
        rounded = Bound.from_log_moment(1, 2, 3)
        self.assertLessEqual(Fraction(rounded.lower), Fraction(-2, 3))
        self.assertGreaterEqual(Fraction(rounded.upper), Fraction(-1, 3))
        for gamma in (0, -1, True, float("nan"), float("inf"), 1e-320):
            with self.subTest(gamma=gamma), self.assertRaises(ValueError):
                Bound.from_log_moment(1, 2, gamma)

    def test_finite_inputs_cannot_overflow_relative_gain(self):
        p, r, g = fixture()
        for stop, action in (
            (Bound(-1e308, -1e308), Bound(1e308, 1e308)),
            (Bound(-1e308, 0), Bound(0, 1e308)),
        ):
            r = replace(r, bounds=(("stop", stop), ("retrieve", action), ("split", None)))
            with self.assertRaisesRegex(ValueError, "nonfinite STOP"):
                self.choose(p, r, g)

    def test_threshold_is_strict_and_positive_ties_use_frozen_roster(self):
        p, r, g = fixture()
        r = replace(r, bounds=(*r.bounds[:2], ("split", Bound(3, 5))))
        self.assertEqual(self.choose(p, r, g).action, "retrieve")
        self.assertEqual(self.choose(replace(p, minimum_gain=1, exploration_calls=0), r, g).action, "stop")

    def test_malformed_identity_balances_and_mutable_vectors_reject(self):
        p, r, g = fixture()
        mutations = (
            lambda: replace(p.cohort, name=7),
            lambda: replace(p.cohort, unit=True),
            lambda: replace(p.cohort, unit=" "),
            lambda: replace(p, actions=(["stop"],)),
            lambda: replace(g[0], action=True),
            lambda: replace(g[0], status="rejected", reason=True),
            lambda: replace(g[0], envelope=(["cpu_us", 1],)),
            lambda: Bound(0, 10**1000),
        )
        for mutate in mutations:
            with self.assertRaises(ValueError):
                mutate()
        for look in (False, 0.0):
            with self.assertRaisesRegex(ValueError, "monitoring"):
                self.choose(p, r, g, replace(p.initial_allowance(), next_look=look))
        with self.assertRaisesRegex(ValueError, "immutable"):
            self.choose(p, replace(r, bounds=(["stop", Bound(1, 2)], *r.bounds[1:])), g)


if __name__ == "__main__":
    unittest.main()
