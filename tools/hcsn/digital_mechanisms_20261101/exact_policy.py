"""Exact autonomous-policy expectation on a declared bounded task restriction.

The source task is the six-slot task in digital_read_before_20261031. This
module forces terminal actions at a shorter, explicitly supplied horizon. It
integrates fitted READ outcomes and every reachable finite-cell state; there
are no packet reads or claims about an unknown true content law.
"""
import json
import math

import numpy as np
import torch

from ..digital_read_before_20261031 import task


def _key(state):
    return json.dumps(state, sort_keys=True, separators=(",", ":"), allow_nan=False)


def transition_context(public, before, after):
    """Pre-action driver, followed by a single successful completion impulse."""
    context = dict(dt=float(public["duration"][before["tick"]]),
                   symbol=float(before["last_symbol"]),
                   reliability=float(before["last_reliability"]),
                   injection_symbol=0., injection_reliability=.5)
    if len(after["history"]) == len(before["history"]) + 1:
        latest = after["history"][-1]
        context.update(injection_symbol=float(2 * latest["observation"] - 1),
                       injection_reliability=float(latest["reliability"]))
    return context


def _branches(public, state, action, confusion):
    """Probabilities are conditional on the complete *observed* history."""
    source = task.due_request(public, state, action)
    if source is None:
        return ((1., None),)
    belief = task.posterior(public, state, confusion)
    reliability = public["reliability"][source]
    law = reliability * confusion + (1 - reliability) * confusion[::-1]
    predictive = (1 - belief) * law[0] + belief * law[1]
    failure = public["failure_probability"]
    return ((failure, dict(failure=True)),
            ((1 - failure) * float(predictive[0]), dict(observation=0)),
            ((1 - failure) * float(predictive[1]), dict(observation=1)))


def _initial_mass(policy):
    if hasattr(policy, "initial_mass"):
        return policy.initial_mass()
    parameter = next(policy.parameters())
    return parameter.new_ones(1) if policy.cell is None else policy.cell.initial()


def _transition(policy, context, reference, cache):
    if policy.cell is None:
        return reference.new_ones((1, 1))
    key = tuple(context.items())
    if key not in cache:
        if hasattr(policy, "transition_for_context"):
            cache[key] = policy.transition_for_context(context)[0]
        else:
            cache[key] = policy.cell.transition(
                context["dt"], context["symbol"], context["reliability"])[0]
    return cache[key]


def evaluate_exact(policy, public, confusion, horizon=2, temperature=.7,
                   detach_action_probabilities=False, max_nodes=30000):
    """Return differentiable expected utility with full task x cell path mass.

    Actions are legal softmax(Q/temperature), including terminal actions.
    At ``horizon`` only STOP/SUBMIT_0/SUBMIT_1 remain legal. The cap is a
    deliberate computational contract: only horizons 1, 2 and 3 are admitted.
    ``detach_action_probabilities`` is an explicit incorrect-gradient negative
    control; its forward value is unchanged. It must not be used for training.
    """
    public = task.validate_public(public)
    confusion = np.asarray(confusion, dtype=np.float64)
    if (confusion.shape != (2, 2) or not np.all(np.isfinite(confusion))
            or np.any(confusion <= 0) or not np.allclose(confusion.sum(1), 1)):
        raise ValueError("positive finite row-stochastic fitted confusion required")
    if (not isinstance(horizon, int) or isinstance(horizon, bool)
            or not 1 <= horizon <= 3 or not math.isfinite(temperature)
            or temperature <= 0 or not isinstance(max_nodes, int) or max_nodes < 1):
        raise ValueError("bounded horizon, positive temperature and node cap required")
    parameter = next(policy.parameters())
    if parameter.dtype != torch.float64:
        raise ValueError("exact witness requires float64 policy")
    zero = parameter.sum() * 0
    value, terminal_mass = zero, zero
    counts = zero.expand(6).clone()
    terminal_actions = zero.expand(6).clone()
    initial = task.initial(public)
    layer = {_key(initial): (initial, _initial_mass(policy))}
    feature_cache, transition_cache = {}, {}
    visited, widest_layer, terminal_branches = 0, 1, 0
    for tick in range(horizon + 1):
        next_layer = {}
        for state, mass in layer.values():
            visited += 1
            if visited > max_nodes:
                raise ValueError("exact policy task-state cap exceeded")
            if state["tick"] != tick or state["terminal"]:
                raise AssertionError("invalid exact policy frontier")
            output = policy.latent_outputs(public, state, feature_cache)
            if output.shape != (mass.numel(), 7) or not bool(torch.isfinite(output).all()):
                raise ValueError("finite [latent,7] policy outputs required")
            allowed = task.legal(public, state)
            if tick == horizon:
                allowed = [allowed[a] and a in (0, 4, 5) for a in range(6)]
            mask = torch.tensor(allowed, device=parameter.device)
            probabilities = torch.softmax(output[:, :6].masked_fill(~mask, -torch.inf) / temperature, -1)
            if detach_action_probabilities:
                probabilities = probabilities.detach()
            belief = task.posterior(public, state, confusion)
            for action in range(6):
                if not allowed[action]:
                    continue
                # Selection reweights latent states *before* the cell propagates.
                action_mass = mass * probabilities[:, action]
                counts = counts + torch.nn.functional.one_hot(
                    torch.tensor(action, device=parameter.device), 6) * action_mass.sum()
                if action in (0, 4, 5):
                    reward = 0. if action == 0 else (1 - 2 * belief if action == 4 else 2 * belief - 1)
                    value = value + reward * action_mass.sum()
                    terminal_mass = terminal_mass + action_mass.sum()
                    terminal_actions = terminal_actions + torch.nn.functional.one_hot(
                        torch.tensor(action, device=parameter.device), 6) * action_mass.sum()
                    terminal_branches += 1
                    continue
                for outcome_probability, completion in _branches(public, state, action, confusion):
                    if outcome_probability == 0:
                        continue
                    successor = task.successor(public, state, action, completion)
                    fee = successor["charges"] - state["charges"]
                    value = value - outcome_probability * fee * action_mass.sum()
                    transition = _transition(policy, transition_context(public, state, successor), parameter, transition_cache)
                    if (transition.shape != (mass.numel(), mass.numel())
                            or not bool(torch.isfinite(transition).all())
                            or float(transition.detach().min()) < -2e-10
                            or float((transition.detach().sum(-1) - 1).abs().max()) > 2e-9):
                        raise ValueError("cell transition violates finite probability contract")
                    new_mass = outcome_probability * (action_mass @ transition)
                    key = _key(successor)
                    if key in next_layer:
                        new_mass = new_mass + next_layer[key][1]
                    next_layer[key] = (successor, new_mass)
        layer = next_layer
        widest_layer = max(widest_layer, len(layer))
    if layer or abs(float(terminal_mass.detach()) - 1) > 2e-8:
        raise ArithmeticError("autonomous task x cell path probability did not terminate with mass one")
    return dict(value=value, terminal_mass=terminal_mass, action_counts=counts,
                terminal_action_mass=terminal_actions, task_state_nodes=visited,
                maximum_layer_nodes=widest_layer, terminal_branches=terminal_branches,
                cached_transitions=len(transition_cache), horizon=horizon,
                temperature=temperature, fitted_law_only=True,
                forced_terminal_at_horizon=True,
                detached_action_negative_control=bool(detach_action_probabilities))


def monte_carlo_reference(policy, public, confusion, horizon=2, temperature=.7,
                          episodes=20000, seed=8800001):
    """Independent scalar trajectories: sample hidden class, observations and cell.

    Unlike evaluate_exact, the observation generator uses the sampled hidden
    class, and the terminal score uses that class instead of a posterior.
    Lookup caching changes host work, not the sampled policy or path law.
    """
    if not isinstance(episodes, int) or episodes < 2 or not 1 <= horizon <= 3:
        raise ValueError("at least two episodes and admitted horizon required")
    confusion = np.asarray(confusion, dtype=np.float64)
    rng = np.random.default_rng(seed)
    probability_cache, transition_cache = {}, {}
    reference = next(policy.parameters())
    values, action_counts = [], np.zeros(6, dtype=np.int64)
    with torch.no_grad():
        initial_mass = _initial_mass(policy).detach().cpu().numpy()
        for _ in range(episodes):
            label = int(rng.integers(2))
            state, cell = task.initial(public), int(rng.choice(len(initial_mass), p=initial_mass))
            utility = 0.
            while True:
                key = _key(state)
                if key not in probability_cache:
                    output = policy.latent_outputs(public, state)[:, :6].detach().cpu().numpy()
                    allowed = np.asarray(task.legal(public, state), dtype=bool)
                    if state["tick"] == horizon:
                        allowed[1:4] = False
                    logits = np.where(allowed, output / temperature, -np.inf)
                    probabilities = np.exp(logits - np.max(logits, axis=-1, keepdims=True))
                    probability_cache[key] = probabilities / probabilities.sum(-1, keepdims=True)
                action = int(rng.choice(6, p=probability_cache[key][cell]))
                action_counts[action] += 1
                if action in (0, 4, 5):
                    utility += 0. if action == 0 else (1. if action - 4 == label else -1.)
                    break
                source = task.due_request(public, state, action)
                completion = None
                if source is not None:
                    if rng.random() < public["failure_probability"]:
                        completion = dict(failure=True)
                    else:
                        reliability = public["reliability"][source]
                        law = reliability * confusion + (1 - reliability) * confusion[::-1]
                        completion = dict(observation=int(rng.choice(2, p=law[label])))
                after = task.successor(public, state, action, completion)
                utility -= after["charges"] - state["charges"]
                transition = _transition(policy, transition_context(public, state, after), reference, transition_cache)
                row = transition[cell].detach().cpu().numpy()
                cell = int(rng.choice(len(row), p=row / row.sum()))
                state = after
            values.append(utility)
    values = np.asarray(values)
    return dict(mean=float(values.mean()), standard_error=float(values.std(ddof=1) / math.sqrt(episodes)),
                episodes=episodes, seed=seed, action_counts=(action_counts / episodes).tolist(),
                independent_hidden_class_sampling=True)
