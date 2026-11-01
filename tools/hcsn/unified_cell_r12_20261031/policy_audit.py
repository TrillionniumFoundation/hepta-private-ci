"""Exact small-tree Q^pi audit retaining the deployed estimator's hidden state.

The world distribution and the actor's estimate are DIFFERENT objects. Future
state/observation probabilities come from the fitted world, never from a GRU's
current output. Every observed branch clones hidden/current, calls the actual
estimator.step, and selects the next action with the common deployed planner.
This diagnostic does not change the four primary arms or their common planner.
"""
import copy
import hashlib
import json
import time

import numpy as np

from .data import encode_observation
from .task_value import ExactBeliefDP, choose_values


def _state_identity(model):
    digest = hashlib.sha256(json.dumps(model.export(), sort_keys=True, allow_nan=False).encode())
    for name in ("hidden", "current"):
        value = getattr(model, name, None)
        digest.update(name.encode())
        if value is not None:
            array = np.asarray(value)
            digest.update(str((array.shape, array.dtype)).encode())
            digest.update(array.tobytes())
    return digest.hexdigest()


def audit_deployed_policy(cell, model, world_belief, schedule=(.15, .45), budget=1,
                          planner=None):
    """Enumerate each first action, then the actual recurrent deployed policy.

    ``model`` must already be at the specified causal prefix. Its current output
    can be wrong; ``world_belief`` is the separate fitted-model posterior at the
    SAME prefix. All supplied model/hidden state remains unchanged. Horizons are
    deliberately bounded to three for this audit, rather than a new controller.
    """
    started = time.process_time()
    planner = ExactBeliefDP(cell) if planner is None else planner
    world = ExactBeliefDP(cell, planner.reset_cost, planner.latency_price, planner.read_multiplier)
    if planner.model_identity != world.model_identity:
        raise ValueError("This audit requires the identical fitted planning/world model")
    p, times, budget = world._inputs(world_belief, schedule, budget)
    if len(times) > 3:
        raise ValueError("Hidden-state policy audit is restricted to at most three intervals")
    if getattr(model, "current", None) is None:
        raise ValueError("Start the estimator and supply the matching causal-prefix belief")
    estimated, _, _ = planner._inputs(model.current, times, budget)
    before_identity = _state_identity(model)
    root_model = copy.deepcopy(model)
    leaves, transitions, read_branches = 0, 0, 0
    path_masses = []

    def follow(mass, estimator, remaining, reads):
        # Hidden/current is the actor state. The mass vector is evaluator-only.
        action = planner.choose(estimator.current, remaining, reads)
        return force(action, mass, estimator, remaining, reads)

    def force(action, mass, estimator, remaining, reads):
        nonlocal leaves, transitions, read_branches
        if action not in planner.legal_actions(remaining, reads):
            raise ValueError("Deployed planner chose an illegal audit action")
        total_mass = float(mass.sum())
        if action.startswith("STOP"):
            leaves += 1
            path_masses.append(total_mass)
            return float(mass @ world.reward[:, int(action[-1])])
        dt, rest = remaining[0], remaining[1:]
        matrix = world._transition(dt)
        successor = mass @ world.R @ matrix if action == "RESET" else mass @ matrix
        transitions += 1
        value = -total_mass*(planner.latency_price*dt
                            + (planner.reset_cost if action == "RESET" else 0.))
        if action == "READ":
            value -= planner.read_multiplier*float(successor @ world.read_cost)
            for token in range(world.E.shape[1]):
                joint_mass = successor*world.E[:, token]
                if joint_mass.sum() > 0:
                    branch = copy.deepcopy(estimator)
                    branch.step(encode_observation(token, dt))
                    read_branches += 1
                    value += follow(joint_mass, branch, rest, reads-1)
        else:
            branch = copy.deepcopy(estimator)
            branch.step(encode_observation(-1, dt, action == "RESET"))
            value += follow(successor, branch, rest, reads)
        return float(value)

    actual_q, leaf_mass = {}, {}
    for action in planner.legal_actions(times, budget):
        offset = len(path_masses)
        actual_q[action] = force(action, p, root_model, times, budget)
        leaf_mass[action] = float(sum(path_masses[offset:]))
    planned_q = planner.action_values(estimated, times, budget)
    world_optimal_q = planner.action_values(p, times, budget)
    selected = planner.choose(estimated, times, budget)
    actual_a = max(actual_q[a] for a in ("WAIT", "READ") if a in actual_q) if times else None
    actual_b = actual_q.get("RESET")
    after_identity = _state_identity(model)
    if before_identity != after_identity:
        raise AssertionError("Policy audit mutated the original deployed estimator")
    return dict(
        schema="hcsn.r12.actual-hidden-policy-audit.v1", kind=model.kind,
        model_identity=planner.model_identity, estimator_state_identity=before_identity,
        original_state_unchanged=True, world_belief=p.tolist(), estimated_belief=estimated.tolist(),
        schedule=list(times), read_budget=budget, selected_action=selected,
        planned_q_star_at_estimate=planned_q, fitted_world_q_star=world_optimal_q,
        actual_recurrent_q_pi=actual_q,
        actual_channels=dict(A=actual_a, B=actual_b,
                             advantage=None if not times else actual_a-actual_b,
                             stop=max(actual_q["STOP0"], actual_q["STOP1"])),
        best_one_step_deviation=choose_values(actual_q),
        one_step_policy_improvement=max(actual_q.values())-actual_q[selected],
        planned_minus_actual={a: planned_q[a]-actual_q[a] for a in actual_q},
        state_estimation_component={a: planned_q[a]-world_optimal_q[a] for a in actual_q},
        continuation_policy_component={a: world_optimal_q[a]-actual_q[a] for a in actual_q},
        deployed_value=actual_q[selected], leaf_mass_per_first_action=leaf_mass,
        max_leaf_mass_error=max(abs(mass-1) for mass in leaf_mass.values()),
        terminal_branches=leaves, state_transitions=transitions, read_branches=read_branches,
        cpu_seconds=time.process_time()-started,
        scope="Exact finite fitted-world expectation at one prefix; not true-world calibration or task superiority.")


def run_policy_fixture(cell, model):
    """A fixed causal prefix, chosen without inspecting any audit outcome.

    Prefix: WAIT .15, then READ symbol 0 at the end of .45. Condition on that
    possible symbol using the fitted-world likelihood. Only the ten actor input
    features are sent to the estimator. This is a diagnostic, not a sampled test
    cohort or a statement about the frequency of this conditioning event.
    """
    estimator = copy.deepcopy(model)
    estimator.start(cell.prior)
    posterior = np.array(cell.prior, copy=True)
    prefix = []
    for token, dt in ((-1, .15), (0, .45)):
        posterior = posterior @ cell.transition(dt)
        evidence = 1.
        if token >= 0:
            posterior *= cell.E[:, token]
            evidence = float(posterior.sum())
            if evidence <= 0:
                raise ValueError("Fixed audit prefix has zero fitted-world probability")
            posterior /= evidence
        estimator.step(encode_observation(token, dt))
        prefix.append(dict(token=token, dt=dt, observation_probability=evidence))
    result = audit_deployed_policy(cell, estimator, posterior, (.15, .45), 1)
    result["fixed_prefix"] = prefix
    return result
