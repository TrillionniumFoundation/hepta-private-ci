"""Audit full-return gradients and explicit private-world path expectations.

Private worlds are used only in this independent evaluation test. The policy
receives public State features, and the training graph never receives Episode.
"""

import argparse
from datetime import datetime, timezone
import itertools
import json
import math
from pathlib import Path
import unittest

import numpy as np
import torch

from .joint_control import build_graph, evaluate_graph
from .model import JointCell
from .task import ACTIONS, Episode, TaskParameters, features, initial_state, legal_actions, step


torch.set_num_threads(1)
AUDIT_RECORDS = []


def sensitive_model(mode):
    """A fixed non-saturated fixture with both event channels reachable."""
    torch.manual_seed(20261030)
    model = JointCell(mode, n_grid=5, hidden=6)
    with torch.no_grad():
        model.drive.weight.zero_()
        model.drive.bias.fill_(math.atanh(0.3 / 1.5))
        boundary_fraction = (0.65 - 0.35) / 1.65
        diffusion_fraction = (0.60 - 0.05) / 0.75
        model.core.raw_boundary.fill_(math.log(boundary_fraction / (1.0 - boundary_fraction)))
        model.core.raw_diffusion.fill_(math.log(diffusion_fraction / (1.0 - diffusion_fraction)))
        model.readout[0].weight[0, -4] = 0.8
        model.readout[0].weight[1, -3] = 0.5
        model.readout[0].weight[2, -2] = 0.9
        model.readout[0].weight[3, -1] = -0.7
        model.readout[2].weight[4, 0] = 0.25
        model.readout[2].weight[5, 0] = -0.15
        model.readout[2].weight[6, 3] = 0.20
        model.readout[2].weight[7, 0] = -0.10
        model.readout[2].weight[4, 2] = -0.20
        model.readout[2].weight[7, 2] = 0.15
    return model


def explicit_world_path_sum(model, parameters, temperature, compute_price, event_price):
    """Sum every H=2 external world, internal-state and soft-action path.

    This does not call oracle.transition_distribution, oracle rewards, or the
    graph's layers. Each public transition and actual terminal quality comes
    from task.step with an explicitly enumerated latent truth/evidence world.
    """
    if parameters.horizon != 2 or parameters.ordinary_count != 1:
        raise ValueError("the explicit finite-world fixture is H=2 with one ordinary source")
    totals = np.zeros(4, dtype=np.float64)  # mass, reward, decisions, events
    leaves = 0
    public_cache = {}

    def public_policy(state):
        if state not in public_cache:
            inputs = torch.from_numpy(features(state)[None, :])
            content, drive = model.encode(inputs)
            transition, _ = model.core.transition_matrix(drive)
            values = model.state_action_values(inputs, content)[0, :, 1, :]
            permitted = torch.tensor([action in legal_actions(state) for action in ACTIONS])
            probabilities = torch.softmax(values.masked_fill(~permitted[None, :], -1e9) / temperature, dim=-1)
            public_cache[state] = transition[0].detach().numpy(), probabilities.detach().numpy()
        return public_cache[state]

    def path(episode, state, before, probability, reward_so_far, decisions, events_so_far):
        nonlocal leaves
        if state.terminated:
            totals[:] += probability * np.array([1.0, reward_so_far, decisions, events_so_far])
            leaves += 1
            return
        transition, policy = public_policy(state)
        for after in range(model.core.n_states):
            transition_probability = transition[before, after]
            if transition_probability <= 0.0:
                continue
            # Entering refractory from an active source is a new event. Staying
            # refractory is not another event and is not charged again.
            event = int(before < model.n_grid and after >= model.n_grid)
            charge = compute_price + event_price * event
            for a, action in enumerate(ACTIONS):
                action_probability = policy[after, a]
                if action_probability == 0.0:
                    continue
                result = step(state, action, episode)
                path(episode, result.state, after, probability * transition_probability * action_probability,
                     reward_so_far + result.reward - charge, decisions + 1, events_so_far + event)

    with torch.no_grad():
        for truth, ordinary, delayed, corrupt in itertools.product((-1, 1), (-1, 1), (-1, 1), (False, True)):
            mass = parameters.prior_probability if truth == 1 else 1.0 - parameters.prior_probability
            mass *= parameters.ordinary_reliability if ordinary == truth else 1.0 - parameters.ordinary_reliability
            mass *= parameters.delayed_reliability if delayed == truth else 1.0 - parameters.delayed_reliability
            mass *= parameters.corruption_probability if corrupt else 1.0 - parameters.corruption_probability
            episode = Episode(0, parameters, truth, (ordinary,), delayed, corrupt)
            path(episode, initial_state(episode), model.n_grid // 2, mass, 0.0, 0, 0)
    return {"probability_mass": float(totals[0]), "expected_return": float(totals[1]),
            "expected_decisions": float(totals[2]), "expected_events": float(totals[3]),
            "explicit_leaf_paths": leaves, "external_worlds": 16}


class JointControlTests(unittest.TestCase):
    def test_myopic_targets_include_the_next_stop_compute_and_event_fees(self):
        parameters = TaskParameters(horizon=2, budget=2, ordinary_count=1,
                                    ordinary_reliability=0.72, delayed_reliability=0.86,
                                    arrival_tick=1, corruption_probability=0.3,
                                    prior_probability=0.58)
        graph = build_graph([parameters])
        compute_price, event_price = 0.017, 0.031
        for mode in ("clocked", "first_passage"):
            model = sensitive_model(mode)
            _, details = evaluate_graph(model, graph, compute_price=compute_price, event_price=event_price)
            initial_index = graph.initial_indices[0]
            expected = np.zeros((model.core.n_states, len(ACTIONS)), dtype=np.float64)
            with torch.no_grad():
                for truth, ordinary, delayed, corrupt in itertools.product((-1, 1), (-1, 1), (-1, 1), (False, True)):
                    probability = parameters.prior_probability if truth == 1 else 1.0 - parameters.prior_probability
                    probability *= parameters.ordinary_reliability if ordinary == truth else 1.0 - parameters.ordinary_reliability
                    probability *= parameters.delayed_reliability if delayed == truth else 1.0 - parameters.delayed_reliability
                    probability *= parameters.corruption_probability if corrupt else 1.0 - parameters.corruption_probability
                    episode = Episode(0, parameters, truth, (ordinary,), delayed, corrupt)
                    state = initial_state(episode)
                    for a, action in enumerate(ACTIONS):
                        if action not in legal_actions(state):
                            continue
                        first = step(state, action, episode)
                        for latent_after_current in range(model.core.n_states):
                            total = first.reward - compute_price
                            if not first.state.terminated:
                                inputs = torch.from_numpy(features(first.state)[None, :])
                                _, drive = model.encode(inputs)
                                transition, _ = model.core.transition_matrix(drive)
                                final = step(first.state, "STOP", episode)
                                continuation = 0.0
                                for latent_after_next in range(model.core.n_states):
                                    new_event = int(latent_after_current < model.n_grid and latent_after_next >= model.n_grid)
                                    continuation += float(transition[0, latent_after_current, latent_after_next]) * (
                                        final.reward - compute_price - event_price * new_event)
                                total += continuation
                            expected[latent_after_current, a] += probability * total
            legal = graph.legal[initial_index].numpy()
            actual = details["myopic_targets"][initial_index].detach().numpy()
            np.testing.assert_allclose(actual[:, legal], expected[:, legal], rtol=2e-12, atol=2e-13)
            stop = ACTIONS.index("STOP")
            target = details["myopic_targets"][initial_index, :, stop].sum()
            derivatives = torch.autograd.grad(target, (model.core.raw_reset_plus, model.core.raw_reset_minus,
                                                       model.core.raw_recovery), allow_unused=True)
            future_derivatives = [0.0 if value is None else float(value) for value in derivatives]
            self.assertTrue(all(abs(value) < 1e-13 for value in future_derivatives))
            AUDIT_RECORDS.append({"test": "full_cost_myopic_targets", "mode": mode,
                                  "external_worlds": 16, "latent_states": model.core.n_states,
                                  "maximum_absolute_error": float(np.max(np.abs(actual[:, legal] - expected[:, legal]))),
                                  "stop_future_reset_recovery_gradients": future_derivatives,
                                  "meaning": "current compute plus next forced-STOP compute and incoming event fee; current event is already sunk"})

    def test_explicit_external_world_and_internal_path_sum(self):
        parameters = TaskParameters(horizon=2, budget=2, ordinary_count=1,
                                    ordinary_reliability=0.72, delayed_reliability=0.86,
                                    arrival_tick=1, corruption_probability=0.3,
                                    prior_probability=0.58)
        graph = build_graph([parameters])
        self.assertEqual(graph.inputs.dtype, torch.float64)
        temperature, compute_price, event_price = 0.4, 0.017, 0.031
        for mode in ("clocked", "first_passage"):
            with self.subTest(mode=mode):
                model = sensitive_model(mode)
                explicit = explicit_world_path_sum(model, parameters, temperature, compute_price, event_price)
                actual, _ = evaluate_graph(model, graph, temperature=temperature,
                                           compute_price=compute_price, event_price=event_price)
                self.assertAlmostEqual(explicit["probability_mass"], 1.0, delta=2e-12)
                self.assertAlmostEqual(float(actual.detach()), explicit["expected_return"], delta=3e-12)
                self.assertGreater(explicit["explicit_leaf_paths"], 100)
                AUDIT_RECORDS.append({"test": "explicit_path_sum", "mode": mode,
                                      "graph_return": float(actual.detach()), **explicit,
                                      "absolute_difference": abs(float(actual.detach()) - explicit["expected_return"])})

                epsilon = 1e-5
                for name, price, count in (("compute_price", compute_price, explicit["expected_decisions"]),
                                           ("event_price", event_price, explicit["expected_events"])):
                    fees = {"compute_price": compute_price, "event_price": event_price}
                    with torch.no_grad():
                        fees[name] = price + epsilon
                        high = float(evaluate_graph(model, graph, temperature=temperature, **fees)[0])
                        fees[name] = price - epsilon
                        low = float(evaluate_graph(model, graph, temperature=temperature, **fees)[0])
                    derivative = (high - low) / (2.0 * epsilon)
                    self.assertAlmostEqual(derivative, -count, delta=2e-9)
                    AUDIT_RECORDS.append({"test": "complete_fee_derivative", "mode": mode,
                                          "price": name, "finite_difference": derivative,
                                          "negative_explicit_count": -count})

    def test_full_task_return_all_group_gradients(self):
        parameters = TaskParameters(horizon=4, budget=3, ordinary_count=1,
                                    ordinary_reliability=0.65, delayed_reliability=0.85,
                                    arrival_tick=1, corruption_probability=0.5,
                                    read_cost=0.08, wait_cost=0.03, repair_cost=0.05,
                                    stop_cost=0.01, latency_cost=0.01, prior_probability=0.58)
        graph = build_graph([parameters])
        for mode in ("clocked", "first_passage"):
            model = sensitive_model(mode)
            probes = [("core." + name, parameter, ()) for name, parameter in model.core.named_parameters()]
            probes += [("content.encoder_weight", model.content[0].weight, (0, 0)),
                       ("content.drive_bias", model.drive.bias, (0,)),
                       ("readout.voltage_weight", model.readout[0].weight, (0, model.readout[0].weight.shape[1] - 4))]

            def objective():
                return evaluate_graph(model, graph, temperature=0.4)[0]

            value = objective()
            derivatives = torch.autograd.grad(value, [parameter for _, parameter, _ in probes])
            for (name, parameter, coordinate), derivative in zip(probes, derivatives):
                with self.subTest(mode=mode, parameter=name):
                    analytic = float(derivative[coordinate])
                    self.assertTrue(math.isfinite(analytic))
                    self.assertGreater(abs(analytic), 1e-10)
                    original = float(parameter[coordinate].detach())
                    epsilon = 1e-5
                    with torch.no_grad():
                        parameter[coordinate] = original + epsilon
                        high = float(objective())
                        parameter[coordinate] = original - epsilon
                        low = float(objective())
                        parameter[coordinate] = original
                    numerical = (high - low) / (2.0 * epsilon)
                    self.assertAlmostEqual(analytic, numerical, delta=2e-8 + 2e-4 * abs(numerical))
                    AUDIT_RECORDS.append({"test": "full_return_gradient", "mode": mode,
                                          "parameter": name, "autodiff": analytic,
                                          "central_difference": numerical,
                                          "absolute_difference": abs(analytic - numerical),
                                          "public_states": len(graph.states)})

    def test_forced_terminal_charges_once_and_has_no_future_reset_gradient(self):
        parameters = TaskParameters(horizon=1, budget=0, ordinary_count=0,
                                    prior_probability=0.7, stop_cost=0.012, latency_cost=0.003)
        graph = build_graph([parameters])
        compute_price, event_price = 0.017, 0.031
        for mode in ("clocked", "first_passage"):
            model = sensitive_model(mode)
            _, drive = model.encode(graph.inputs)
            _, events = model.core.transition_matrix(drive)
            incoming_events = float(events[0, model.n_grid // 2].sum().detach())
            value, _ = evaluate_graph(model, graph, compute_price=compute_price, event_price=event_price)
            expected = abs(2.0 * parameters.prior_probability - 1.0) - parameters.stop_cost - parameters.latency_cost - compute_price - event_price * incoming_events
            self.assertAlmostEqual(float(value.detach()), expected, delta=2e-13)
            self.assertEqual(len(graph.states), 1)
            gradients = torch.autograd.grad(value, (model.core.raw_reset_plus, model.core.raw_reset_minus,
                                                    model.core.raw_recovery), allow_unused=True)
            values = [0.0 if g is None else float(g) for g in gradients]
            self.assertTrue(all(abs(g) < 1e-13 for g in values))
            AUDIT_RECORDS.append({"test": "forced_stop_cost_and_causality", "mode": mode,
                                  "graph_return": float(value.detach()), "independent_return": expected,
                                  "incoming_event_count": incoming_events,
                                  "reset_plus_reset_minus_recovery_gradients": values})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path)
    arguments = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(JointControlTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if arguments.evidence is not None:
        arguments.evidence.parent.mkdir(parents=True, exist_ok=True)
        arguments.evidence.write_text(json.dumps({"created_utc": datetime.now(timezone.utc).isoformat(),
                                                 "status": "PASS" if result.wasSuccessful() else "FAIL",
                                                 "tests_run": result.testsRun, "failures": len(result.failures),
                                                 "errors": len(result.errors), "records": AUDIT_RECORDS},
                                                indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    raise SystemExit(0 if result.wasSuccessful() else 1)

