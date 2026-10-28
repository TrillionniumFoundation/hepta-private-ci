"""Behavioral tests of aggregation, execution costs and finite optimal control."""

from dataclasses import FrozenInstanceError, replace
from fractions import Fraction
import json
import math
import unittest

from .objective_oracle import exact_ce, validate_oracle
from .profile import (CostEvent, DeliveredOutcome, JointBranch, NduProfile, aggregate,
                      backup, certainty_equivalent, digest, log_moment, moment_cost,
                      net_return, summarize_outcomes, total_cost)


def profile(**changes):
    result = NduProfile(digest("external-task-and-cost-definition"),
                        digest("frozen-post-codec-observer"),
                        digest("actual-continuation-code"))
    return replace(result, **changes)


def outcome(p, **changes):
    result = DeliveredOutcome("task-a", "draw-1", "source-1", 0.8,
                              (CostEvent("actual-execute", 0.1),),
                              (("text", digest("serialized-utf8")),
                               ("image", digest("reopened-png"))),
                              p.observer_sha256, p.objective_sha256,
                              p.continuation_sha256)
    return replace(result, **changes)


class UnifiedProfileTests(unittest.TestCase):
    def test_profile_roundtrip_and_semantic_identity(self):
        p = profile()
        self.assertEqual(NduProfile.from_dict(json.loads(json.dumps(p.to_dict()))), p)
        for changed in (replace(p, aggregation="conditional"), replace(p, gamma=0.0),
                        replace(p, continuation_sha256=digest("changed-policy")),
                        replace(p, observer_sha256=digest("changed-observer"))):
            self.assertNotEqual(p.digest, changed.digest)
        with self.assertRaises(FrozenInstanceError):
            p.gamma = 3.0
        for key, value in (("time_discount", 0.9), ("time_discount", True),
                           ("cost_treatment", "mean_cost")):
            wire = p.to_dict()
            wire[key] = value
            with self.assertRaises(ValueError):
                NduProfile.from_dict(wire)

    def test_risk_neutral_continuity_against_decimal(self):
        values, probabilities = (-10, -3), (0.4, 0.6)
        law = ((Fraction(2, 5), Fraction(-10)), (Fraction(3, 5), Fraction(-3)))
        for gamma in (0, 1e-18, 1e-16, 1e-12, 1e-8, 0.001, 2, 100):
            expected = float(exact_ce(law, gamma))
            self.assertAlmostEqual(certainty_equivalent(values, gamma, probabilities),
                                   expected, delta=2e-14)
        self.assertEqual(log_moment(values, 0, probabilities), 0.0)
        self.assertAlmostEqual(moment_cost(0.7, 1e-18), -0.7, delta=1e-15)

    def test_log_domain_large_tail_and_translation(self):
        p, values, gamma = (0.999, 0.001), (1.0, -1000.0), 2.0
        actual = certainty_equivalent(values, gamma, p)
        self.assertTrue(math.isfinite(actual))
        self.assertAlmostEqual(log_moment(values, gamma, p), -gamma * actual, places=11)
        shifted = certainty_equivalent([v + 7 for v in values], gamma, p)
        self.assertAlmostEqual(shifted, actual + 7, places=11)
        with self.assertRaises(ValueError):
            moment_cost(-1000.0, gamma)

    def test_conditional_and_population_are_different_objectives(self):
        values = {"easy": [1.0, 1.0], "hard": [-1.0, -1.0]}
        cond = aggregate(profile(aggregation="conditional"), values)
        pop = aggregate(profile(), values)
        self.assertEqual(cond["value"], 0.0)
        self.assertLess(pop["value"], -0.6)
        self.assertEqual(cond["population_ce"], pop["value"])
        replicated = aggregate(profile(), {"easy": [1.0] * 7, "hard": [-1.0]})
        self.assertAlmostEqual(pop["value"], replicated["value"], places=14)
        weighted = aggregate(profile(), values, {"easy": 0.9, "hard": 0.1})
        self.assertGreater(weighted["value"], pop["value"])
        with self.assertRaises(ValueError):
            aggregate(profile(), values, {"easy": 1.0})

    def test_random_cost_stays_inside_joint_expectation(self):
        p = profile()
        # Same marginal future utility and cost, different coupling: replacing
        # cost by its mean would make the two distinct controls appear equal.
        coupled = [JointBranch(.5, 0, 0, 0, p.continuation_sha256),
                   JointBranch(.5, 0, 1, 1, p.continuation_sha256)]
        anticoupled = [JointBranch(.5, 0, 1, 0, p.continuation_sha256),
                      JointBranch(.5, 0, 0, 1, p.continuation_sha256)]
        self.assertAlmostEqual(backup(p, coupled), 0.0, places=15)
        self.assertLess(backup(p, anticoupled), -0.6)
        stale = [replace(coupled[0], continuation_sha256=digest("oracle-not-deployed")),
                 coupled[1]]
        with self.assertRaises(ValueError):
            backup(p, stale)

    def test_real_cost_events_are_idempotent_and_conflicts_reject(self):
        p = profile()
        event = CostEvent("owner-tick-1", .1)
        self.assertEqual(total_cost(p, [event, event]), .1)
        self.assertEqual(total_cost(p, [event, replace(event, event_id="owner-tick-2")]), .2)
        with self.assertRaises(ValueError):
            total_cost(p, [event, replace(event, amount=.2)])
        for invalid in (replace(event, amount=-.1), replace(event, amount=float("nan")),
                        replace(event, unit="raw-milliseconds")):
            with self.assertRaises(ValueError):
                total_cost(p, [invalid])

    def test_outcome_binds_actual_observer_and_complete_terminal_bundle(self):
        p = profile()
        original = outcome(p)
        self.assertAlmostEqual(net_return(p, original), .7)
        for changed in (replace(original, observer_sha256=digest("self-label")),
                        replace(original, objective_sha256=digest("easier-objective")),
                        replace(original, artifact_sha256=(("text", digest("text")),)),
                        replace(original, delivered_utility=2.0)):
            with self.assertRaises(ValueError):
                net_return(p, changed)
        refusal = replace(original, terminal_kind="refused", delivered_utility=-1.,
                          artifact_sha256=())
        self.assertAlmostEqual(net_return(p, refusal), -1.1)
        with self.assertRaises(ValueError):
            summarize_outcomes(p, [original, original])

    def test_complete_finite_policy_oracle_with_stopping(self):
        result = validate_oracle(cases=5)
        self.assertTrue(result["all_passed"], result)
        self.assertGreater(max(x["policies"] for x in result["records"]), 100)
        self.assertLess(result["max_value_error"], 3e-13)

    def test_invalid_probability_support_is_not_silently_normalized(self):
        for probabilities in ([.2, .2], [1.1, -.1], [float("nan"), 1.0]):
            with self.assertRaises(ValueError):
                certainty_equivalent([0, 1], 2., probabilities)
        with self.assertRaises(ValueError):
            certainty_equivalent([], 2.)
        with self.assertRaises(ValueError):
            certainty_equivalent([0, 1], -1.)

    def test_sample_moment_gradient_has_correct_direction(self):
        # Analytic Bernoulli emission: the actual outcome is discontinuous in
        # the sampled token, while the probability score derivative is exact.
        q, gamma = 0.3, 2.0
        low, high = -0.5, 0.8
        derivative_m = math.exp(-gamma * high) - math.exp(-gamma * low)
        expected = -(derivative_m / (gamma * ((1-q)*math.exp(-gamma*low)
                                             + q*math.exp(-gamma*high))))
        step = 1e-6
        plus = certainty_equivalent([low, high], gamma, [1-q-step, q+step])
        minus = certainty_equivalent([low, high], gamma, [1-q+step, q-step])
        self.assertAlmostEqual(expected, (plus-minus)/(2*step), delta=1e-9)
        self.assertGreater(expected, 0)


if __name__ == "__main__":
    unittest.main()
