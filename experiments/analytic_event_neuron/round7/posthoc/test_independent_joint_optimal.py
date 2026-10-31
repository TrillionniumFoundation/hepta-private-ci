"""Separate post-freeze tests; these are not part of the original 45-test seal."""

import itertools
import math
import unittest
from unittest.mock import patch

import numpy as np
import torch

from ..joint_control import build_graph, evaluate_graph
from ..model import JointCell
from ..task import ACTIONS, Episode, TaskParameters, features, initial_state, legal_actions, step
from .independent_joint_optimal import (advantage_act, build_public_graph, forward_audit,
                                       network_greedy_actions, prepare_kernel, solve)


AUDIT_RECORDS = []


def fixture_model():
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(20261031)
        model = JointCell("first_passage", n_grid=5, hidden=6)
    with torch.no_grad():
        model.drive.weight.zero_()
        model.drive.bias.fill_(math.atanh(0.3 / 1.5))
        b = (0.65 - 0.35) / 1.65
        sigma = (0.6 - 0.05) / 0.75
        model.core.raw_boundary.fill_(math.log(b / (1 - b)))
        model.core.raw_diffusion.fill_(math.log(sigma / (1 - sigma)))
    return model


def private_worlds(parameters):
    """Independent evaluation only: all 16 worlds with one ordinary source."""
    for truth, ordinary, delayed, corrupt in itertools.product((-1, 1), (-1, 1), (-1, 1), (False, True)):
        probability = parameters.prior_probability if truth == 1 else 1 - parameters.prior_probability
        probability *= parameters.ordinary_reliability if ordinary == truth else 1 - parameters.ordinary_reliability
        probability *= parameters.delayed_reliability if delayed == truth else 1 - parameters.delayed_reliability
        probability *= parameters.corruption_probability if corrupt else 1 - parameters.corruption_probability
        yield probability, Episode(0, parameters, truth, (ordinary,), delayed, corrupt)


class IndependentJointOptimalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_full_cost_horizon_two_reference_against_explicit_private_worlds(self):
        p = TaskParameters(horizon=2, budget=2, ordinary_count=1, arrival_tick=3,
                           prior_probability=0.5, ordinary_reliability=0.72)
        model = fixture_model()
        graph = build_public_graph([p])
        kernel = prepare_kernel(model, graph)
        compute, event = 0.017, 2.0
        optimum = solve(graph, kernel, compute_price=compute, event_price=event)
        start, latent = graph.starts[0], model.core.n_states
        expected = np.zeros((latent, len(ACTIONS)), dtype=np.float64)
        with torch.no_grad():
            for probability, episode in private_worlds(p):
                state = initial_state(episode)
                for a, action in enumerate(ACTIONS):
                    if action not in legal_actions(state):
                        continue
                    first = step(state, action, episode)
                    values = np.full(latent, first.reward - compute)
                    if not first.state.terminated:
                        x = torch.from_numpy(features(first.state)[None, :])
                        _, drive = model.encode(x)
                        transition, _ = model.core.transition_matrix(drive)
                        matrix = transition[0].numpy()
                        new_events = np.zeros(latent)
                        new_events[:model.n_grid] = matrix[:model.n_grid, model.n_grid:].sum(-1)
                        last = step(first.state, "STOP", episode)
                        values += last.reward - compute - event * new_events
                    expected[:, a] += probability * values
        permitted = graph.legal[start]
        np.testing.assert_allclose(optimum.q_after[start, :, permitted].T,
                                   expected[:, permitted], atol=2e-12, rtol=2e-12)
        row = kernel.transition[start, model.n_grid // 2]
        best_after = expected[:, permitted].max(-1)
        correct = row @ best_after - event * kernel.events[start, model.n_grid // 2]
        self.assertAlmostEqual(optimum.initial_values[0], correct, delta=3e-12)
        value_of_observing_latent = row @ best_after - (row @ expected[:, permitted]).max()
        self.assertGreater(value_of_observing_latent, 1e-5)
        AUDIT_RECORDS.append({"test": "independent_16_world_H2_Q_star", "external_worlds": 16,
                              "Q_maximum_absolute_error": float(np.max(np.abs(
                                  optimum.q_after[start, :, permitted].T - expected[:, permitted]))),
                              "initial_value_absolute_error": abs(float(optimum.initial_values[0] - correct)),
                              "T_maxQ_minus_maxTQ": float(value_of_observing_latent)})

    def test_forced_STOP_current_fees_and_no_future_reset_effect(self):
        p = TaskParameters(horizon=1, budget=0, ordinary_count=1, prior_probability=0.7)
        graph, model = build_public_graph([p]), fixture_model()
        kernel = prepare_kernel(model, graph)
        compute, event = 0.017, 0.031
        optimum = solve(graph, kernel, compute_price=compute, event_price=event)
        expected = abs(2 * p.prior_probability - 1) - p.stop_cost - p.latency_cost - compute
        expected -= event * (kernel.initial @ kernel.events[0])
        self.assertAlmostEqual(float(optimum.initial_values[0]), expected, delta=3e-13)
        self.assertTrue(np.isnan(advantage_act(graph, optimum)).all())
        with torch.no_grad():
            model.core.raw_reset_plus.add_(0.4)
            model.core.raw_reset_minus.sub_(0.6)
            model.core.raw_recovery.add_(0.7)
        altered = solve(graph, prepare_kernel(model, graph), compute_price=compute, event_price=event)
        np.testing.assert_allclose(altered.initial_values, optimum.initial_values, atol=3e-13, rtol=0)
        AUDIT_RECORDS.append({"test": "H1_STOP_fees_causality", "return": float(optimum.initial_values[0]),
                              "closed_form_error": abs(float(optimum.initial_values[0] - expected)),
                              "future_parameter_perturbation_effect": float(np.max(np.abs(altered.initial_values - optimum.initial_values)))})

    def test_reference_is_head_independent_and_greedy_matches_frozen_evaluator(self):
        p = TaskParameters(horizon=4, budget=3, ordinary_count=1, arrival_tick=1,
                           prior_probability=0.58, corruption_probability=0.5)
        graph, model = build_public_graph([p]), fixture_model()
        kernel = prepare_kernel(model, graph)
        optimum = solve(graph, kernel)
        with patch.object(model, "state_action_values", side_effect=AssertionError("head accessed by reference")):
            repeated = solve(graph, prepare_kernel(model, graph))
        np.testing.assert_array_equal(repeated.q_after, optimum.q_after)
        actions = network_greedy_actions(model, graph)
        baseline = solve(graph, kernel, policy=actions)
        rows, _, _ = forward_audit(graph, kernel, optimum, baseline)
        with torch.no_grad():
            old_value, _ = evaluate_graph(model, build_graph([p]), policy="greedy")
            for parameter in model.readout.parameters():
                parameter.mul_(0).add_(3.1)
        changed_head_reference = solve(graph, prepare_kernel(model, graph))
        np.testing.assert_array_equal(changed_head_reference.q_after, optimum.q_after)
        self.assertAlmostEqual(float(baseline.initial_values[0]), float(old_value), delta=3e-12)
        AUDIT_RECORDS.append({"test": "head_independence_greedy_crosscheck_regret_identity",
                              "greedy_independent_minus_frozen": float(baseline.initial_values[0] - old_value),
                              "optimality_gap": rows[0]["optimal_minus_greedy"],
                              "performance_difference_identity_error": rows[0]["performance_difference_identity_error"]})

    def test_repeated_events_reset_recovery_and_full_fee_occupancy(self):
        p = TaskParameters(horizon=4, budget=0, ordinary_count=1, arrival_tick=2,
                           prior_probability=0.58, corruption_probability=0.3)
        graph, model = build_public_graph([p]), fixture_model()
        kernel = prepare_kernel(model, graph)
        compute, event = 0.017, 0.031
        policy = np.array([[ACTIONS.index("WAIT" if state.remaining_ticks > 1 else "STOP")] * model.core.n_states
                           for state in graph.states], dtype=np.int64)
        optimum = solve(graph, kernel, compute_price=compute, event_price=event)
        baseline = solve(graph, kernel, policy=policy, compute_price=compute, event_price=event)
        rows, _, _ = forward_audit(graph, kernel, optimum, baseline, compute_price=compute, event_price=event)
        explicit = np.zeros(3)
        with torch.no_grad():
            for probability, episode in private_worlds(p):
                state, mass = initial_state(episode), model.initial(1)[0].numpy().copy()
                total, events, decisions = 0.0, 0.0, 0
                while not state.terminated:
                    x = torch.from_numpy(features(state)[None, :])
                    _, drive = model.encode(x)
                    transition, _ = model.core.transition_matrix(drive)
                    matrix = transition[0].numpy()
                    new_event = mass[:model.n_grid] @ matrix[:model.n_grid, model.n_grid:].sum(-1)
                    mass = mass @ matrix
                    action = "WAIT" if state.remaining_ticks > 1 else "STOP"
                    outcome = step(state, action, episode)
                    total += outcome.reward - compute - event * new_event
                    events += new_event
                    decisions += 1
                    state = outcome.state
                explicit += probability * np.array([total, events, decisions])
        actual = [rows[0]["registered_return"], rows[0]["expected_events"], rows[0]["expected_decisions"]]
        np.testing.assert_allclose(actual, explicit, atol=3e-12, rtol=3e-12)
        effects = {}
        for name in ("raw_reset_plus", "raw_reset_minus", "raw_recovery"):
            parameter = getattr(model.core, name)
            with torch.no_grad():
                original = parameter.clone()
                parameter.add_(0.4)
            altered = solve(graph, prepare_kernel(model, graph), policy=policy,
                            compute_price=compute, event_price=event)
            effects[name] = float(altered.initial_values[0] - baseline.initial_values[0])
            self.assertGreater(abs(effects[name]), 1e-8)
            with torch.no_grad():
                parameter.copy_(original)
        AUDIT_RECORDS.append({"test": "H4_recurrent_world_sum_and_future_parameters",
                              "maximum_return_event_count_error": float(np.max(np.abs(np.array(actual) - explicit))),
                              "expected_decisions": float(explicit[2]), "expected_events": float(explicit[1]),
                              "future_parameter_perturbation_effects": effects,
                              "performance_difference_identity_error": rows[0]["performance_difference_identity_error"]})


if __name__ == "__main__":
    unittest.main(verbosity=2)
