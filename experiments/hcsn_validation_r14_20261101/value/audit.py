"""Evaluate the deployed recurrent policy in a separate finite true world.

World mass is evaluator-only.  Actor calls receive only their own causal state,
the public clock and READ budget.  Every hypothetical READ calls the actual
checkpoint's step method, retaining hidden memory.  No Bayes-oracle tail replaces
the actor.  This is a finite CTMC audit, not a continuum approximation claim.
"""

import copy
import hashlib
import json

import numpy as np

from .upstream.data import encode_observation
from .upstream.task_value import choose_values


FIELDS = ("utility", "reward", "read_fee", "time_fee", "reset_fee", "reads",
          "waits", "resets", "correctness", "elapsed")


def state_identity(model):
    digest = hashlib.sha256(json.dumps(model.export(), sort_keys=True,
                                       allow_nan=False).encode())
    for name in ("hidden", "current"):
        value = getattr(model, name, None)
        digest.update(name.encode())
        if value is not None:
            array = np.asarray(value)
            digest.update(str((array.shape, array.dtype)).encode())
            digest.update(array.tobytes())
    return digest.hexdigest()


def clone_actor(model):
    """Copy all mutable decision state of the two pinned estimator classes.

    Parameters and Cell transition caches are inference-immutable mathematical
    inputs.  Cache population cannot affect policy values.  Hidden/current are
    copied; no recurrent state is shared between alternative action branches.
    """
    if model.kind not in ("hx_distribution", "gru", "continuous_diagonal_ssm"):
        raise TypeError("Unregistered actor needs an explicit state clone")
    result = copy.copy(model)
    for name in ("hidden", "current"):
        if getattr(model, name, None) is not None:
            setattr(result, name, np.array(getattr(model, name), copy=True))
    return result


def choose_actor(model, planner, schedule, budget, control):
    if control == "value":
        return planner.choose(model.current, schedule, budget)
    if control != "fixed_read":
        raise ValueError("Unknown frozen controller")
    if schedule and budget:
        return "READ"
    answer = int(model.current @ planner.reward[:, 1] > model.current @ planner.reward[:, 0])
    return "STOP" + str(answer)


def conditional_posterior(world, belief, observation):
    p = np.array(belief, copy=True)
    if observation["reset"]:
        p = p @ world.R
    p = p @ world._transition(observation["dt"])
    if observation["observed"]:
        p *= world.E[:, observation["token"]]
    probability = float(p.sum())
    if probability <= 0:
        raise ArithmeticError("Impossible causal observation")
    return p / probability


def q_pi(world, model, belief, schedule, budget, planner, control, keep_tree=False):
    """Force every legal first action, then execute the same frozen actor.

    Each trace node records its unconditional mass and actual immediate expected
    costs or terminal reward.  Summing a first action's nodes reconstructs Qpi.
    Hidden endpoint fees affect the evaluator only, never the actor update.
    """
    p, times, budget = world._inputs(belief, schedule, budget)
    before = state_identity(model)
    leaf_mass, trees, statistics = {}, {}, {}

    def force(action, mass, actor, clock, reads, path, nodes):
        weight = float(mass.sum())
        out = np.zeros(len(FIELDS))
        if action.startswith("STOP"):
            answer = int(action[-1])
            reward = float(mass @ world.reward[:, answer])
            out[0] = out[1] = reward
            out[8] = float(mass[(np.arange(world.states) % 2) == answer].sum())
            if keep_tree:
                nodes.append(dict(path=path, action=action, mass=weight, reward=reward,
                                  correctness=out[8]))
            return out, weight
        dt, rest = clock[0], clock[1:]
        if action not in planner.legal_actions(clock, reads):
            raise ValueError("Illegal forced action")
        successor = mass @ world.R if action == "RESET" else mass
        successor = successor @ world._transition(dt)
        out[3] = weight * world.latency_price * dt
        out[4] = weight * world.reset_cost if action == "RESET" else 0.
        out[2] = world.read_multiplier * float(successor @ world.read_cost) if action == "READ" else 0.
        out[5:8] = [weight * (action == candidate) for candidate in ("READ", "WAIT", "RESET")]
        out[9] = weight * dt
        out[0] = -sum(out[2:5])
        if keep_tree:
            nodes.append(dict(path=path, action=action, mass=weight, dt=dt,
                              read_fee=out[2], time_fee=out[3], reset_fee=out[4]))
        leaves = 0.
        tokens = range(world.E.shape[1]) if action == "READ" else (-1,)
        for token in tokens:
            branch_mass = successor * world.E[:, token] if token >= 0 else successor
            if branch_mass.sum() <= 0:
                continue
            branch = clone_actor(actor)
            branch.step(encode_observation(token, dt, action == "RESET"))
            next_reads = reads - (action == "READ")
            selected = choose_actor(branch, planner, rest, next_reads, control)
            tail, tail_mass = force(selected, branch_mass, branch, rest, next_reads,
                                    path + [[action, int(token)]], nodes)
            out += tail
            leaves += tail_mass
        return out, leaves

    for action in planner.legal_actions(times, budget):
        nodes = []
        values, leaves = force(action, p, model, times, budget, [], nodes)
        statistics[action] = dict(zip(FIELDS, map(float, values)))
        leaf_mass[action] = leaves
        if keep_tree:
            trees[action] = nodes
    if before != state_identity(model):
        raise AssertionError("Counterfactual execution mutated its source actor")
    if max(abs(x - 1.) for x in leaf_mass.values()) > 2e-10:
        raise AssertionError("Conditional branch probability mass lost")
    for values in statistics.values():
        if abs(values["utility"] - values["reward"] + values["read_fee"]
               + values["time_fee"] + values["reset_fee"]) > 2e-10:
            raise AssertionError("Incomplete action fee accounting")
    return dict(q={a: v["utility"] for a, v in statistics.items()},
                statistics=statistics, leaf_mass=leaf_mass, trees=trees,
                actor_state_sha256=before, source_state_unchanged=True)


def audit_prefix(true_world, fitted_world, model, true_belief, fitted_belief,
                 schedule, budget, planner, control):
    actual = q_pi(true_world, model, true_belief, schedule, budget, planner, control, True)
    fitted = q_pi(fitted_world, model, fitted_belief, schedule, budget, planner, control)
    planned = planner.action_values(model.current, schedule, budget)
    fitted_star = planner.action_values(fitted_belief, schedule, budget)
    selected = choose_actor(model, planner, schedule, budget, control)
    aq, fq = actual["q"], fitted["q"]
    components = {
        "state_estimation": {a: planned[a] - fitted_star[a] for a in aq},
        "continuation_policy": {a: fitted_star[a] - fq[a] for a in aq},
        "world_model": {a: fq[a] - aq[a] for a in aq},
    }
    error = max(abs(planned[a] - aq[a] - sum(row[a] for row in components.values())) for a in aq)
    if error > 2e-12:
        raise AssertionError("Qstar-Qpi decomposition does not close")
    true_stop, planned_stop = max(aq[a] for a in ("STOP0", "STOP1")), max(planned[a] for a in ("STOP0", "STOP1"))
    advantages = {a: dict(predicted=planned[a]-planned_stop, actual=aq[a]-true_stop)
                  for a in aq if not a.startswith("STOP")}
    pairs = [(a, b) for i, a in enumerate(aq) for b in list(aq)[i+1:]
             if abs(aq[a] - aq[b]) > 1e-10]
    rank = [int(np.sign(planned[a]-planned[b]) == np.sign(aq[a]-aq[b])) for a, b in pairs]
    return dict(selected=selected, best_one_step=choose_values(aq),
                true_qpi=actual, fitted_qpi=fitted["q"], planned_qstar=planned,
                fitted_world_qstar=fitted_star, decomposition=components,
                decomposition_max_error=error, advantages=advantages,
                advantage_absolute_error_mean=float(np.mean([abs(v["predicted"]-v["actual"]) for v in advantages.values()])) if advantages else None,
                rank_correct=sum(rank), rank_pairs=len(rank),
                one_step_regret=max(aq.values())-aq[selected],
                stop_deficit=max(0., true_stop-aq[selected]),
                reset_strictly_best=("RESET" in aq and aq["RESET"] > max(v for a, v in aq.items() if a != "RESET")+1e-12),
                true_belief=np.asarray(true_belief).tolist(), fitted_belief=np.asarray(fitted_belief).tolist(),
                actor_belief=model.current.tolist(),
                actor_hidden=None if getattr(model,"hidden",None) is None else model.hidden.tolist(),
                remaining_schedule=list(schedule), read_budget=budget,
                true_world_identity=true_world.model_identity,
                fitted_world_identity=fitted_world.model_identity,
                scope="Exact finite-world expected execution of the frozen recurrent actor; planned Qstar is diagnostic for fixed-read arms.")
