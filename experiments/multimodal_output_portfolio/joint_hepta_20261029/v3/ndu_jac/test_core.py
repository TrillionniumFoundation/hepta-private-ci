"""Independent differentiation and deliberate objective/credit counterexamples."""

from copy import deepcopy
from dataclasses import replace
import math
import random
import unittest

from .core import Outcome, evaluate, optimal_policy, policy_gradient, softmax_policy


def problem():
    return {
        "s0": {"STOP": (Outcome(1, reward=0.15),), "reconfigure": (
            Outcome(0.3, reward=0.2, cost=0.05, adjustment_cost=0.08,
                    duration=0.2, next_state="s1"),
            Outcome(0.7, reward=-0.1, cost=0.12, adjustment_cost=0.08,
                    duration=1.6, next_state="s2"))},
        "s1": {"STOP": (Outcome(1, reward=0.6),), "refine": (
            Outcome(0.75, reward=1.8, cost=0.12, duration=0.2),
            Outcome(0.25, reward=-0.6, cost=0.28, duration=2.0))},
        "s2": {"STOP": (Outcome(1, reward=-0.15),), "refine": (
            Outcome(0.85, reward=0.9, cost=0.1, duration=0.4),
            Outcome(0.15, reward=-0.8, cost=0.2, duration=1.2))},
    }


def independent_value(nodes, state, policy, eta, rho):
    """Direct nested exponential definition, independent of shifted core backup."""
    result = 0.0
    for action, law in nodes[state].items():
        moment = 0.0
        for o in law:
            future = independent_value(nodes, o.next_state, policy, eta, rho) if o.next_state else 0
            x = o.reward - o.cost - o.adjustment_cost + math.exp(-rho * o.duration) * future
            moment += o.probability * math.exp(-eta * x)
        result += policy[state][action] * -math.log(moment) / eta
    return result


class RecursiveControlTests(unittest.TestCase):
    def test_all_logits_match_independent_finite_differences(self):
        nodes, rng = problem(), random.Random(7291)
        worst = 0.0
        for eta in (0.15, 1.0, 3.0):
            for rho in (0.0, 0.17, 1.2):
                for _ in range(5):
                    logits = {s: {a: rng.uniform(-1.1, 1.1) for a in acts}
                              for s, acts in nodes.items()}
                    result = policy_gradient(nodes, "s0", logits, eta, rho)
                    self.assertAlmostEqual(result["value"], independent_value(
                        nodes, "s0", result["policy"], eta, rho), places=12)
                    for state, acts in nodes.items():
                        for action in acts:
                            plus, minus = deepcopy(logits), deepcopy(logits)
                            plus[state][action] += 1e-5
                            minus[state][action] -= 1e-5
                            high = independent_value(nodes, "s0", softmax_policy(nodes, plus), eta, rho)
                            low = independent_value(nodes, "s0", softmax_policy(nodes, minus), eta, rho)
                            error = abs((high - low) / 2e-5 - result["gradient"][state][action])
                            worst = max(worst, error)
                    for row in result["gradient"].values():
                        self.assertAlmostEqual(sum(row.values()), 0, places=12)
        self.assertLess(worst, 2e-9)

    def test_weights_affect_later_scores_not_current_scores(self):
        nodes = problem()
        logits = {s: {a: 0.0 for a in acts} for s, acts in nodes.items()}
        r = policy_gradient(nodes, "s0", logits, eta=2.0, rho=0.35)
        pi, q, v = r["policy"], r["action_values"], r["values"]
        local = pi["s1"]["refine"] * (q["s1"]["refine"] - v["s1"])
        ordinary_credit = 0.5 * 0.3 * math.exp(-0.35 * 0.2) * local
        self.assertGreater(abs(ordinary_credit - r["gradient"]["s1"]["refine"]), 1e-3)
        # An erroneous full w_(t+1) on the current score discounts each action
        # by its own duration. m_t alone has conditional expectation one, so
        # adding just m_t is NOT an expectation-level negative control here.
        wrong = 0.0
        for a, law in nodes["s0"].items():
            for o, tilt in zip(law, r["tilted_probabilities"]["s0"][a]):
                score = float(a == "reconfigure") - pi["s0"]["reconfigure"]
                wrong += pi["s0"][a] * tilt * math.exp(-0.35 * o.duration) * score * (q["s0"][a] - v["s0"])
        self.assertGreater(abs(wrong - r["gradient"]["s0"]["reconfigure"]), 1e-3)

    def test_action_randomization_outside_ce_is_a_different_objective(self):
        nodes = {"s": {"low": (Outcome(1, reward=-1),), "high": (Outcome(1, reward=1),)}}
        policy = {"s": {"low": 0.5, "high": 0.5}}
        outside = evaluate(nodes, "s", policy, eta=2)["value"]
        inside = -math.log(0.5 * math.exp(2) + 0.5 * math.exp(-2)) / 2
        self.assertAlmostEqual(outside, 0, places=14)
        self.assertGreater(outside - inside, 0.6)
        gradient = policy_gradient(nodes, "s", {"s": {"low": 0, "high": 0}}, eta=2)["gradient"]
        self.assertAlmostEqual(gradient["s"]["high"], 0.5, places=14)

    def test_deterministic_policy_matches_existing_undiscounted_oracle(self):
        from ...oracle import Branch, policy_value
        nodes = problem()
        # The inherited API forbids negative costs. Keep terminal reward as
        # terminal_utility and nonterminal rewards at zero in this comparison.
        nodes = {s: {a: tuple(replace(o, reward=o.reward if o.next_state is None else 0)
                              for o in law) for a, law in acts.items()}
                 for s, acts in nodes.items()}
        inherited = {s: {a: tuple(Branch(o.probability, o.cost + o.adjustment_cost,
                                         o.next_state, o.reward if o.next_state is None else None)
                                  for o in law) for a, law in acts.items()}
                     for s, acts in nodes.items()}
        for choice in ("STOP", "reconfigure"):
            policy = {s: {a: float(a == (choice if s == "s0" else "refine")) for a in acts}
                      for s, acts in nodes.items()}
            self.assertAlmostEqual(evaluate(nodes, "s0", policy, eta=2, rho=0)["value"],
                                   policy_value(inherited, "s0", policy, gamma=2), places=12)

    def test_optimum_against_all_deterministic_policies(self):
        from itertools import product
        nodes, states = problem(), ("s0", "s1", "s2")
        brute = []
        for choices in product(*(tuple(nodes[s]) for s in states)):
            policy = {s: {a: float(a == chosen) for a in nodes[s]} for s, chosen in zip(states, choices)}
            brute.append(independent_value(nodes, "s0", policy, 1.2, 0.3))
        result = optimal_policy(nodes, "s0", eta=1.2, rho=0.3)
        self.assertAlmostEqual(result["value"], max(brute), places=12)

    def test_reconverging_dag_adds_all_weighted_visits(self):
        nodes = {"a": {"go": (Outcome(0.4, next_state="b"), Outcome(0.6, next_state="c"))},
                 "b": {"go": (Outcome(1, next_state="d"),)},
                 "c": {"go": (Outcome(1, next_state="d"),)},
                 "d": {"STOP": (Outcome(1, reward=0),), "try": (Outcome(1, reward=1),)}}
        logits = {s: {a: 0 for a in acts} for s, acts in nodes.items()}
        result = policy_gradient(nodes, "a", logits)
        self.assertAlmostEqual(result["occupancy"]["d"], 1, places=14)
        self.assertAlmostEqual(result["gradient"]["d"]["try"], 0.25, places=14)

    def test_extreme_shift_avoids_exponential_overflow(self):
        nodes = {"s": {"STOP": (Outcome(0.3, reward=-10000), Outcome(0.7, reward=-9999))}}
        r = evaluate(nodes, "s", {"s": {"STOP": 1}}, eta=50)
        self.assertTrue(math.isfinite(r["value"]))
        self.assertAlmostEqual(sum(r["tilted_probabilities"]["s"]["STOP"]), 1)

    def test_tiny_risk_approaches_linear_mean_without_cancellation(self):
        nodes = {"s": {"STOP": (Outcome(0.3, reward=-0.4), Outcome(0.7, reward=0.9))}}
        r = evaluate(nodes, "s", {"s": {"STOP": 1}}, eta=1e-14)
        self.assertAlmostEqual(r["value"], 0.51, places=12)

    def test_rejects_invalid_cost_probability_duration_and_stop(self):
        bad = [Outcome(0.9), Outcome(1, cost=-1), Outcome(1, adjustment_cost=-1),
               Outcome(1, duration=-1), Outcome(1, reward=float("nan")),
               Outcome(True), Outcome(1, next_state="s")]
        for outcome in bad:
            with self.subTest(outcome=outcome), self.assertRaises(ValueError):
                evaluate({"s": {"STOP": (outcome,)}}, "s", {"s": {"STOP": 1}})
        with self.assertRaises(ValueError):
            evaluate({"s": {"go": (Outcome(1, next_state="s"),)}}, "s", {"s": {"go": 1}})

    def test_tolerated_mass_rounding_cannot_create_common_reward_gain(self):
        for perturbation in (-5e-13, 5e-13):
            with self.subTest(perturbation=perturbation):
                nodes = {"s": {"STOP": (Outcome(1 + perturbation, reward=1e12),)}}
                policy = {"s": {"STOP": 1 + perturbation}}
                result = evaluate(nodes, "s", policy)
                self.assertEqual(result["value"], 1e12)
                self.assertEqual(result["policy"], {"s": {"STOP": 1.0}})
                self.assertEqual(policy, {"s": {"STOP": 1 + perturbation}})
                self.assertEqual(result["advantages"], {"s": {"STOP": 0.0}})
                # Law and policy normalization apply only to already accepted
                # rounding tolerance, and must still reject missing mass.
                with self.assertRaises(ValueError):
                    evaluate(nodes, "s", {"s": {"STOP": 1 - 2e-12}})
                with self.assertRaises(ValueError):
                    evaluate({"s": {"STOP": (Outcome(1 - 2e-12),)}}, "s", {"s": {"STOP": 1}})

    def test_law_uses_same_normalized_probability_for_ce_and_tilts(self):
        nodes = {"s": {"STOP": (Outcome(0.4, reward=0.2), Outcome(0.6, reward=1.8))}}
        reference = evaluate(nodes, "s", {"s": {"STOP": 1}}, eta=1.3)
        for perturbation in (-5e-13, 5e-13):
            changed = {"s": {"STOP": tuple(replace(o, probability=o.probability * (1 + perturbation))
                                           for o in nodes["s"]["STOP"])}}
            result = evaluate(changed, "s", {"s": {"STOP": 1}}, eta=1.3)
            self.assertAlmostEqual(result["value"], reference["value"], places=14)
            for actual, expected in zip(result["tilted_probabilities"]["s"]["STOP"],
                                        reference["tilted_probabilities"]["s"]["STOP"]):
                self.assertAlmostEqual(actual, expected, places=14)

    def test_gradient_is_invariant_to_large_common_currency_offset(self):
        logits = {"s": {"low": 0.0, "high": math.log(1.5)}}
        for offset in (0, -1e12, 1e12):
            nodes = {"s": {"low": (Outcome(1, reward=offset),),
                           "high": (Outcome(1, reward=offset + 1),)}}
            result = policy_gradient(nodes, "s", logits)
            self.assertAlmostEqual(result["gradient"]["s"]["low"], -0.24, places=14)
            self.assertAlmostEqual(result["gradient"]["s"]["high"], 0.24, places=14)
            self.assertAlmostEqual(sum(result["gradient"]["s"].values()), 0, places=14)

    def test_rejects_policy_and_parameter_mismatch(self):
        nodes, pi = {"s": {"STOP": (Outcome(1),)}}, {"s": {"STOP": 1}}
        for eta, rho in ((0, 0), (-1, 0), (True, 0), (1, -1), (1, float("nan"))):
            with self.subTest(eta=eta, rho=rho), self.assertRaises(ValueError):
                evaluate(nodes, "s", pi, eta, rho)
        with self.assertRaises(ValueError):
            evaluate(nodes, "s", {"s": {"STOP": 0.5}})
        with self.assertRaises(ValueError):
            softmax_policy(nodes, {"s": {"STOP": float("inf")}})


if __name__ == "__main__":
    unittest.main()
