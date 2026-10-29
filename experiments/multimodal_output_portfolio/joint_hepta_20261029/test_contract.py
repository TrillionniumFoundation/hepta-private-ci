"""Independent numerical and executed-chain checks for the new joint contract."""

from dataclasses import replace
import json
import math
import unittest

from ..unified_20261028.profile import aggregate, certainty_equivalent
from .contract import (
    CostEvent, DecisionEvent, DeliveredOutcome, GenerationState, JointGenerationProfile,
    NduProfile, digest, validate_episode, validate_runtime_features,
)
from .oracle import (
    Branch, brute_force_optimum, entropic_gradient, policy_gradient, policy_value,
    softmax_policy, solve_risk_dp, validate_problem,
)


def fixture():
    identity = lambda value: digest(value)
    ndu = NduProfile(identity("objective"), identity("observer"), identity("continuation"))
    profile = JointGenerationProfile(ndu, *(identity(v) for v in ("input", "noise", "cost", "port")))
    initial = GenerationState(
        profile.digest, "context-1", identity("input bytes"), identity("checkpoint"),
        identity("policy"), identity("hidden0"), (("text", identity("text0")), ("image", identity("image0"))),
        (), (("text", 0), ("image", 0)), (("text", 0), ("image", 0)), 0, 0, 1.0,
    )
    artifacts = (("text", identity("actual text bytes")), ("image", identity("actual image bytes")))
    final = replace(initial, event_index=1, elapsed_us=25, remaining_budget=0.9,
                    shared_state_sha256=identity("hidden1"), committed_artifact_sha256=artifacts,
                    generation_steps=(("text", 1), ("image", 1)), media_positions=(("text", 3), ("image", 0)))
    costs = (CostEvent("physical-work-1", 0.1),)
    event = DecisionEvent("event-1", profile.digest, initial.digest, final.digest, "deliver",
                          (("continue", 0.25), ("deliver", 0.75)), identity("draw-key-1"), costs, "delivered")
    outcome = DeliveredOutcome("context-1", "draw-1", "independent-source-1", 0.7, costs, artifacts,
                               ndu.observer_sha256, ndu.objective_sha256, ndu.continuation_sha256)
    return profile, initial, final, event, outcome


def tiny_problem():
    return {
        "start": {
            "deliver": (Branch(0.5, 0.02, terminal_utility=0.65), Branch(0.5, 0.05, terminal_utility=0.35)),
            "refine": (Branch(0.7, 0.03, "good"), Branch(0.3, 0.08, "bad")),
        },
        "good": {
            "deliver": (Branch(1.0, 0.02, terminal_utility=0.85),),
            "verify": (Branch(0.8, 0.06, terminal_utility=1.0), Branch(0.2, 0.09, terminal_utility=0.75)),
        },
        "bad": {
            "deliver": (Branch(1.0, 0.02, terminal_utility=0.15),),
            "repair": (Branch(0.75, 0.12, terminal_utility=0.7), Branch(0.25, 0.18, terminal_utility=-0.2)),
        },
    }


class ExecutedContractTests(unittest.TestCase):
    def test_profile_roundtrip_rejects_semantic_changes(self):
        profile = fixture()[0]
        encoded = json.loads(json.dumps(profile.to_dict()))
        self.assertEqual(JointGenerationProfile.from_dict(encoded), profile)
        encoded["compute_clock"] = "diffusion_noise_time"
        with self.assertRaisesRegex(ValueError, "semantics"):
            JointGenerationProfile.from_dict(encoded)

    def test_actual_terminal_readback_and_budget(self):
        profile, initial, final, event, outcome = fixture()
        self.assertAlmostEqual(validate_episode(profile, (initial, final), (event,), outcome), 0.6)
        with self.assertRaisesRegex(ValueError, "budget"):
            bad = replace(final, remaining_budget=0.99)
            validate_episode(profile, (initial, bad), (replace(event, successor_sha256=bad.digest),), outcome)

    def test_no_label_or_mid_episode_parameter_change(self):
        profile, initial, final, event, outcome = fixture()
        with self.assertRaisesRegex(ValueError, "future"):
            validate_runtime_features(profile, {"terminal_score": 1.0})
        changed = replace(final, parameter_snapshot_sha256=digest("another checkpoint"))
        with self.assertRaisesRegex(ValueError, "snapshot"):
            validate_episode(profile, (initial, changed), (replace(event, successor_sha256=changed.digest),), outcome)

    def test_selected_joint_propensity_and_cost_identity(self):
        profile, initial, final, event, outcome = fixture()
        for bad in (replace(event, joint_action_probabilities=(("continue", 1.0), ("deliver", 0.0))),
                    replace(event, costs=event.costs * 2)):
            with self.assertRaises(ValueError):
                validate_episode(profile, (initial, final), (bad,), outcome)

    def test_no_silent_committed_rewrite_or_fake_terminal(self):
        profile, initial, final, event, outcome = fixture()
        initial = replace(initial, committed_artifact_sha256=(("text", digest("published prefix")),))
        with self.assertRaisesRegex(ValueError, "committed"):
            validate_episode(profile, (initial, final), (replace(event, predecessor_sha256=initial.digest),), outcome)
        profile, initial, final, event, outcome = fixture()
        with self.assertRaisesRegex(ValueError, "independent outcome"):
            validate_episode(profile, (initial, final), (event,))
        with self.assertRaises(ValueError):
            validate_episode(profile, (initial, final), (event,), replace(outcome, observer_sha256=digest("critic")))


class RiskOracleTests(unittest.TestCase):
    def test_dp_matches_policy_enumeration_and_complete_path_law(self):
        nodes = tiny_problem()
        dp, brute = solve_risk_dp(nodes, "start"), brute_force_optimum(nodes, "start")
        self.assertAlmostEqual(dp["value"], brute["value"], places=13)
        policy = {s: {a: float(a == dp["policy"][s]) for a in nodes[s]} for s in nodes}
        self.assertAlmostEqual(dp["value"], policy_value(nodes, "start", policy), places=13)
        self.assertEqual(brute["policies"], 8)

    def test_joint_cost_cannot_be_replaced_by_mean_cost(self):
        joint = certainty_equivalent([0.9 - 0.01, 0.0 - 0.4], 2.0)
        incorrect = certainty_equivalent([0.9, 0.0], 2.0) - 0.205
        self.assertGreater(abs(joint - incorrect), 0.1)

    def test_population_and_conditional_aggregation_are_distinct(self):
        profile = fixture()[0].ndu
        result = aggregate(profile, {"easy": [0.9, 0.8], "hard": [-0.6, -0.8]})
        self.assertAlmostEqual(result["value"], certainty_equivalent([0.9, 0.8, -0.6, -0.8], 2))
        self.assertGreater(result["conditional_ce"] - result["population_ce"], 0.1)

    def test_policy_score_gradient_matches_centered_finite_difference(self):
        nodes = tiny_problem()
        logits = {s: {a: 0.1 * i for i, a in enumerate(sorted(nodes[s]))} for s in nodes}
        exact = policy_gradient(nodes, "start", logits)
        epsilon = 1e-5
        for state in nodes:
            for action in nodes[state]:
                plus = {s: dict(row) for s, row in logits.items()}
                minus = {s: dict(row) for s, row in logits.items()}
                plus[state][action] += epsilon
                minus[state][action] -= epsilon
                finite = (policy_value(nodes, "start", softmax_policy(nodes, plus))
                          - policy_value(nodes, "start", softmax_policy(nodes, minus))) / (2 * epsilon)
                self.assertAlmostEqual(exact["gradient"][state][action], finite, places=9)

    def test_risk_gradient_includes_direct_return_and_correct_score_sign(self):
        z = 0.3

        def objective(theta):
            probability = 1 / (1 + math.exp(-theta))
            return certainty_equivalent([theta + 0.5, -0.2], 2.0, [probability, 1 - probability])

        p = 1 / (1 + math.exp(-z))
        gradient = entropic_gradient([z + 0.5, -0.2], [p, 1 - p], [(1 - p,), (-p,)],
                                     return_gradients=[(1.0,), (0.0,)])[0]
        self.assertAlmostEqual(gradient, (objective(z + 1e-5) - objective(z - 1e-5)) / 2e-5, places=9)

    def test_missing_failure_mass_and_infinite_loop_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "mass"):
            validate_problem({"s": {"go": (Branch(0.9, terminal_utility=1.0),)}}, "s", 2)
        with self.assertRaisesRegex(ValueError, "cyclic"):
            validate_problem({"s": {"go": (Branch(1.0, next_state="s"),)}}, "s", 2)


if __name__ == "__main__":
    unittest.main()
