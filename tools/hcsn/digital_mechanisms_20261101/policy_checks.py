"""Independent checks for the bounded autonomous policy path expectation."""
import argparse
import json
from pathlib import Path
import time
import unittest

import numpy as np
import torch

from ..digital_read_before_20261031.model import Policy
from .exact_policy import evaluate_exact, monte_carlo_reference
from .models import MechanismPolicy


def fixture_public():
    return dict(schema="digital-read-before-public-v1", id="exact-policy-witness",
                deadline=6, initial_budget=3, duration=[.25, 1.5, .5, 1., .5, 1.],
                reliability=[.95, .65, .85, .65, .85, .65],
                read_price=[.03, .12, .03, .12, .03, .12], read_delay=[1, 2, 1, 2, 1, 2],
                latency_price=.025, repair_price=.03, failure_probability=.08,
                packets=[f"packet_{i}.json" for i in range(6)], packet_sha256=["0" * 64] * 6)


def finite_difference(policy, parameter, index, public, confusion, epsilon=2e-5):
    with torch.no_grad():
        original = float(parameter[index])
        parameter[index] = original + epsilon
        plus = float(evaluate_exact(policy, public, confusion)["value"])
        parameter[index] = original - epsilon
        minus = float(evaluate_exact(policy, public, confusion)["value"])
        parameter[index] = original
    return (plus - minus) / (2 * epsilon)


class ExactPolicyChecks(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.public = fixture_public()
        self.confusion = np.asarray([[.94, .06], [.11, .89]])

    def test_joint_path_mass_and_transition_differentiation(self):
        policy = Policy("first_passage_bank", 809)
        exact = evaluate_exact(policy, self.public, self.confusion)
        self.assertAlmostEqual(float(exact["terminal_mass"]), 1., places=12)
        self.assertAlmostEqual(float(exact["terminal_action_mass"].sum()), 1., places=12)
        gradients = torch.autograd.grad(exact["value"], (policy.linear2.bias, policy.cell.raw))
        for parameter, index, gradient in ((policy.linear2.bias, 1, gradients[0][1]),
                                           (policy.cell.raw, 0, gradients[1][0]),
                                           (policy.cell.raw, 2, gradients[1][2])):
            numerical = finite_difference(policy, parameter, index, self.public, self.confusion)
            self.assertLess(abs(float(gradient) - numerical), 2e-7 + 2e-5 * abs(numerical))
        self.assertGreater(abs(float(gradients[0][1])), 1e-5)
        self.assertGreater(abs(float(gradients[1][0])), 1e-7)

    def test_action_probability_gradient_is_not_prefix_mass_gradient(self):
        policy = Policy("raw_history", 809)
        exact = evaluate_exact(policy, self.public, self.confusion)
        bad = evaluate_exact(policy, self.public, self.confusion, detach_action_probabilities=True)
        self.assertEqual(float(exact["value"]), float(bad["value"]))
        gradient = torch.autograd.grad(exact["value"], policy.linear2.bias)[0]
        bad_gradient = torch.autograd.grad(bad["value"], policy.linear2.bias, allow_unused=True)[0]
        self.assertTrue(bad_gradient is None or bool(torch.all(bad_gradient == 0)))
        self.assertGreater(float(gradient.abs().max()), .001)

    def test_structured_impulse_policy_uses_complete_joint_paths(self):
        policy = MechanismPolicy("first_passage_bank", 831, "structured", "impulse")
        result = evaluate_exact(policy, self.public, self.confusion)
        derivatives = torch.autograd.grad(result["value"], (policy.linear2.bias, policy.cell.raw))
        for parameter, index, derivative in ((policy.linear2.bias, 3, derivatives[0][3]),
                                             (policy.cell.raw, 2, derivatives[1][2])):
            numerical = finite_difference(policy, parameter, index, self.public, self.confusion)
            self.assertLess(abs(float(derivative) - numerical), 2e-7 + 2e-5 * abs(numerical))
        accumulator = MechanismPolicy("evidence_accumulator", 831, "structured", "accumulator")
        accumulated = evaluate_exact(accumulator, self.public, self.confusion)
        self.assertAlmostEqual(float(accumulated["terminal_mass"].detach()), 1., places=12)
        self.assertEqual(accumulated["cached_transitions"], 0)

    def test_expected_return_matches_hidden_class_rollouts(self):
        policy = Policy("clocked_bank", 823)
        with torch.no_grad():
            policy.linear2.bias[2] += .8
        exact = evaluate_exact(policy, self.public, self.confusion)
        sampled = monte_carlo_reference(policy, self.public, self.confusion, episodes=16000)
        self.assertLess(abs(sampled["mean"] - float(exact["value"])),
                        5 * sampled["standard_error"] + 1e-4)
        np.testing.assert_allclose(sampled["action_counts"], exact["action_counts"].detach().numpy(), atol=.018, rtol=0)

    def test_delayed_completion_and_failures_are_explicit(self):
        policy = Policy("raw_history", 827)
        with torch.no_grad():
            policy.linear2.weight.zero_()
            policy.linear2.bias.zero_()
            policy.linear2.bias[2] = 10.
        no_failure = dict(self.public, failure_probability=0.)
        always_failure = dict(self.public, failure_probability=1.)
        successful = evaluate_exact(policy, no_failure, self.confusion)
        failed = evaluate_exact(policy, always_failure, self.confusion)
        self.assertAlmostEqual(float(successful["terminal_mass"]), 1., places=12)
        self.assertAlmostEqual(float(failed["terminal_mass"]), 1., places=12)
        self.assertGreater(successful["task_state_nodes"], failed["task_state_nodes"])
        self.assertGreater(float(failed["action_counts"][3]), 0.)
        late = dict(self.public, read_delay=[2] * 6)
        horizon_one = evaluate_exact(policy, late, self.confusion, horizon=1)
        # No label information can arrive before forced termination, so only
        # the READ and elapsed-time charges contribute to expected utility.
        expected_fee = (.03 * float(horizon_one["action_counts"][2])
                        + .025 * .25 * float(horizon_one["action_counts"][1:4].sum()))
        self.assertAlmostEqual(float(horizon_one["value"]), -expected_fee, places=12)

    def test_restriction_and_probability_failures_are_rejected(self):
        policy = Policy("raw_history", 829)
        for kwargs in (dict(horizon=6), dict(temperature=0.), dict(max_nodes=1)):
            with self.assertRaises(ValueError):
                evaluate_exact(policy, self.public, self.confusion, **kwargs)
        with self.assertRaises(ValueError):
            evaluate_exact(policy, self.public, [[.8, .8], [.1, .9]])


def witness():
    """Machine-readable fixed diagnostic; never opens prior confirmation files."""
    torch.set_num_threads(1)
    started = time.process_time()
    public, confusion = fixture_public(), np.asarray([[.94, .06], [.11, .89]])
    rows = []
    for family in ("raw_history", "ordinary_bank", "clocked_bank", "first_passage_bank"):
        policy = Policy(family, 809)
        exact = evaluate_exact(policy, public, confusion)
        head = torch.autograd.grad(exact["value"], policy.linear2.bias, retain_graph=True)[0]
        numerical = finite_difference(policy, policy.linear2.bias, 1, public, confusion)
        detached = evaluate_exact(policy, public, confusion, detach_action_probabilities=True)
        sampled = monte_carlo_reference(policy, public, confusion, episodes=6000, seed=8800001)
        row = dict(family=family, expected_utility=float(exact["value"].detach()),
                   terminal_mass=float(exact["terminal_mass"].detach()),
                   expected_action_counts=exact["action_counts"].detach().tolist(),
                   head_wait_bias_gradient=float(head[1]), central_difference=numerical,
                   derivative_absolute_error=abs(float(head[1]) - numerical),
                   detached_forward_value=float(detached["value"].detach()),
                   task_state_nodes=exact["task_state_nodes"], monte_carlo=sampled)
        rows.append(row)
    return dict(schema="digital-autonomous-policy-witness-v1", horizon=2,
                inherited_task_deadline=6, temperature=.7, public=public,
                fitted_confusion=confusion.tolist(), rows=rows,
                cpu_seconds=time.process_time() - started,
                actual_content_execution=False, efficacy_confirmation=False,
                conclusion="Action probabilities are inside the joint task/cell path measure; finite differences verify the declared soft policy expectation.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    args, remainder = parser.parse_known_args()
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x") as stream:
            json.dump(witness(), stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
    else:
        unittest.main(argv=["policy_checks"] + remainder)
