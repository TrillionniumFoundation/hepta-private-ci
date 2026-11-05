"""Independent finite-model checks of the proved risk-occupancy lower bound."""
import math
import random
import unittest

from .core import Outcome, evaluate, policy_gradient, softmax_policy


def advantage_bound(nodes, root, baseline, candidate, rho, risk=True):
    occupancy = {s: float(s == root) for s in nodes}
    for state in reversed(candidate["order"]):
        for action, law in nodes[state].items():
            probabilities = (candidate["tilted_probabilities"][state][action] if risk
                             else tuple(o.probability for o in law))
            for outcome, probability in zip(law, probabilities):
                if outcome.next_state is not None:
                    occupancy[outcome.next_state] += (occupancy[state]
                        * candidate["policy"][state][action] * probability
                        * math.exp(-rho * outcome.duration))
    return math.fsum(occupancy[s] * math.fsum(
        (candidate["policy"][s][a] - baseline["policy"][s][a])
        * baseline["advantages"][s][a] for a in nodes[s]) for s in nodes)


class TheoryTests(unittest.TestCase):
    def test_fifty_random_dags_satisfy_candidate_risk_occupancy_bound(self):
        rng, slacks = random.Random(110507), []
        for trial in range(50):
            nodes, states = {}, [f"s{i}" for i in range(6)]
            for i, state in enumerate(states):
                nodes[state] = {"STOP": (Outcome(1, reward=rng.uniform(-1, 1)),)}
                for action in ("continue", "reconfigure"):
                    p = rng.uniform(0.15, 0.85)
                    successors = states[i + 1:] + [None]
                    nodes[state][action] = tuple(Outcome(prob, rng.uniform(-2, 2),
                        rng.uniform(0, 0.3), rng.uniform(0, 0.2), rng.uniform(0, 2),
                        successors[0] if j == 0 else rng.choice(successors))
                        for j, prob in enumerate((p, 1 - p)))
            eta, rho = rng.uniform(0.1, 3), rng.uniform(0, 0.6)
            policies = [softmax_policy(nodes, {s: {a: rng.uniform(-1.3, 1.3)
                for a in actions} for s, actions in nodes.items()}) for _ in range(2)]
            baseline, candidate = [evaluate(nodes, "s0", p, eta, rho) for p in policies]
            slack = candidate["value"] - baseline["value"] - advantage_bound(
                nodes, "s0", baseline, candidate, rho)
            with self.subTest(trial=trial):
                self.assertGreaterEqual(slack, -1e-11)
            slacks.append(slack)
        self.assertGreater(max(slacks), 0.01)  # Nonlinear, not only equality cases.

    def test_ordinary_occupancy_is_not_a_valid_substitute(self):
        nodes = {"r": {"go": (Outcome(0.5, next_state="low"),
                               Outcome(0.5, next_state="high"))},
                 "low": {"STOP": (Outcome(1, reward=-2),)},
                 "high": {"STOP": (Outcome(1, reward=2),), "revise": (Outcome(1, reward=3),)}}
        baseline = evaluate(nodes, "r", {"r": {"go": 1}, "low": {"STOP": 1},
                                         "high": {"STOP": 1, "revise": 0}})
        candidate = evaluate(nodes, "r", {"r": {"go": 1}, "low": {"STOP": 1},
                                          "high": {"STOP": 0, "revise": 1}})
        gain = candidate["value"] - baseline["value"]
        lower = advantage_bound(nodes, "r", baseline, candidate, 0)
        wrong = advantage_bound(nodes, "r", baseline, candidate, 0, risk=False)
        self.assertAlmostEqual(lower, 1 / (1 + math.exp(5)), places=14)
        self.assertLess(lower, gain)
        self.assertAlmostEqual(wrong, 0.5, places=14)
        self.assertGreater(wrong - gain, 0.48)

    def test_documented_shared_logit_gradient(self):
        nodes = {"r": {"go": (Outcome(0.5, next_state="a"),
                  Outcome(0.5, reward=-1, duration=math.log(2), next_state="b"))},
                 "a": {"good": (Outcome(1, reward=1),), "bad": (Outcome(1),)},
                 "b": {"good": (Outcome(1, reward=4),), "bad": (Outcome(1),)}}
        result = policy_gradient(nodes, "r", {s: {a: 0 for a in row}
                                             for s, row in nodes.items()}, rho=1)
        gradient = sum(result["gradient"][s]["good"] for s in ("a", "b"))
        def independent(theta):
            p = 1 / (1 + math.exp(-theta))
            return -math.log((math.exp(-p) + math.exp(1 - 2 * p)) / 2)
        self.assertAlmostEqual(gradient, 0.4056148328004636, places=13)
        self.assertAlmostEqual(gradient, (independent(1e-6) - independent(-1e-6)) / 2e-6, places=9)
        self.assertGreater(abs(gradient - 0.375), 0.03)

    def test_documented_action_mixture_values_and_derivatives(self):
        nodes = {"s": {"low": (Outcome(1),), "high": (Outcome(1, reward=2),)}}
        result = policy_gradient(nodes, "s", {"s": {"low": 0, "high": 0}})
        self.assertEqual(result["value"], 1.0)
        self.assertEqual(result["gradient"]["s"]["high"], 0.5)
        self.assertAlmostEqual(-math.log((1 + math.exp(-2)) / 2), 0.5662191695169727)
        self.assertAlmostEqual(0.5 * math.tanh(1), 0.3807970779778824)


if __name__ == "__main__":
    unittest.main()
