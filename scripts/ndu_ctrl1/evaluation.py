"""Exact policy evaluation and separately metered sampled executions."""

import math
import random
import time
from functools import lru_cache

from ndu_real_runtime.objective import edge_value

from .model import ACTIONS, backup, initial_state, legal_actions, transitions
from .oracle import Oracle
from .policies import after_compute

METRICS = (
    "terminal_payoff",
    "environment_cost",
    "controller_cost",
    "environment_seconds",
    "controller_seconds",
    "expanded_nodes",
    "stop_regret",
    "compute_and_stop_regret",
    "continuation_regret",
    "budget_violations",
    "fallback_count",
    "slow_calls",
    "decision_calls",
)


def evaluate(scenario, profile, controller, start_state=None):
    """Exact reachable-policy graph; oracle work is strictly offline reference.

    The NDU value is nested CE, while all other fields are expectations under the
    actual joint kernel. The ideal oracle excludes online computation overhead.
    """
    oracle = Oracle(scenario, profile)
    start = initial_state(scenario) if start_state is None else start_state
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    optimum = oracle.value(start)
    oracle_measurement = {
        "wall_ns": time.perf_counter_ns() - wall,
        "cpu_ns": time.process_time_ns() - cpu,
        "reachable_states": len(oracle.states),
        "timing_scope": "initial_oracle_solve_only",
    }
    seen = set()
    evaluation_wall, evaluation_cpu = time.perf_counter_ns(), time.process_time_ns()

    @lru_cache(maxsize=None)
    def visit(state):
        if state not in seen:
            if len(seen) >= 20_000:
                raise ValueError("Policy evaluation state cap exceeded")
            seen.add(state)
        decision = controller.choose(scenario, state)
        admitted = after_compute(state, decision)
        if decision.action not in legal_actions(scenario, admitted):
            raise ValueError("Controller returned an inadmissible environment action")
        outcomes = transitions(scenario, admitted, decision.action)
        children = [
            None if o.next_state is None else visit(o.next_state) for o in outcomes
        ]
        continuations = [
            o.reward if child is None else child["value"]
            for o, child in zip(outcomes, children)
        ]
        value = -profile.resource_weight * decision.cost + edge_value(
            decision.duration, backup(outcomes, continuations, profile), profile
        )
        row = dict.fromkeys(METRICS, 0.0)
        row.update({"value": value, "actions": dict.fromkeys(ACTIONS, 0.0)})
        for outcome, child in zip(outcomes, children):
            mass = float(outcome.probability)
            row["environment_cost"] += mass * outcome.cost
            row["environment_seconds"] += mass * outcome.duration
            if child is None:
                row["terminal_payoff"] += mass * outcome.reward
            else:
                for key in METRICS:
                    row[key] += mass * child[key]
                for action in ACTIONS:
                    row["actions"][action] += mass * child["actions"][action]
        row["controller_cost"] += decision.cost
        row["controller_seconds"] += decision.duration
        row["expanded_nodes"] += decision.expanded_nodes
        row["fallback_count"] += int(decision.fallback)
        row["slow_calls"] += int(decision.route == "slow")
        row["decision_calls"] += 1
        row["actions"][decision.action] += 1
        if decision.action == "stop":
            row["stop_regret"] += max(
                0.0, oracle.value(admitted) - oracle.q(admitted, "stop")
            )
            row["compute_and_stop_regret"] += max(0.0, oracle.value(state) - value)
        elif oracle.action(admitted) == "stop":
            row["continuation_regret"] += max(
                0.0,
                oracle.q(admitted, "stop") - oracle.q(admitted, decision.action),
            )
        return row

    result = dict(visit(start))
    result["policy_gap"] = optimum - result["value"]
    result["oracle_value"] = optimum
    result["net_terminal_utility"] = (
        result["terminal_payoff"]
        - profile.resource_weight
        * (result["environment_cost"] + result["controller_cost"])
        - profile.latency_weight
        * (result["environment_seconds"] + result["controller_seconds"])
    )
    if result["policy_gap"] < -1e-10:
        raise AssertionError("Controller exceeds the same-objective ideal oracle")
    result["policy_states"] = visit.cache_info().currsize
    oracle_measurement["total_stats_including_regret_queries"] = oracle.stats
    result["offline_oracle"] = oracle_measurement
    result["offline_policy_evaluation"] = {
        "wall_ns": time.perf_counter_ns() - evaluation_wall,
        "cpu_ns": time.process_time_ns() - evaluation_cpu,
        "scope": "inclusive; contains controller and regret-oracle work; do not add nested timers",
    }
    result["evaluation"] = "exact_environment"
    return result


def sample_episode(scenario, profile, controller, seed):
    """Execute one public-belief trajectory and retain every realized charge.

    Its discounted path return is NOT an estimator of a nested risk-sensitive CE.
    Expectations of payoff, resource cost and time remain ordinary sample means.
    """
    rng, state = random.Random(seed), initial_state(scenario)
    path = []
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    for step in range(scenario.horizon + 1):
        decision = controller.choose(scenario, state)
        admitted = after_compute(state, decision)
        outcomes = transitions(scenario, admitted, decision.action)
        draw, cumulative = rng.random(), 0.0
        chosen = outcomes[-1]
        for outcome in outcomes:
            cumulative += float(outcome.probability)
            if draw < cumulative:
                chosen = outcome
                break
        path.append(
            {
                "step": step,
                "belief": str(state.belief),
                "action": decision.action,
                "route": decision.route,
                "fallback": decision.fallback,
                "controller_cost": decision.cost,
                "controller_seconds": decision.duration,
                "expanded_nodes": decision.expanded_nodes,
                "observation": chosen.observation,
                "environment_cost": chosen.cost,
                "environment_seconds": chosen.duration,
                "reward": chosen.reward,
                "probability": str(chosen.probability),
            }
        )
        if chosen.next_state is None:
            break
        state = chosen.next_state
    else:
        raise AssertionError("Finite-horizon controller did not terminate")
    environment_cost = sum(item["environment_cost"] for item in path)
    controller_cost = sum(item["controller_cost"] for item in path)
    duration = sum(
        item["environment_seconds"] + item["controller_seconds"] for item in path
    )
    if (
        environment_cost + controller_cost > scenario.budget
        or duration > scenario.deadline
    ):
        raise AssertionError("An actually executed trajectory exceeded a hard budget")
    return {
        "seed": seed,
        "status": "Completed",
        "terminal_payoff": path[-1]["reward"],
        "environment_cost": environment_cost,
        "controller_cost": controller_cost,
        "duration_seconds": duration,
        "budget_violations": 0,
        "wall_ns": time.perf_counter_ns() - wall,
        "cpu_ns": time.process_time_ns() - cpu,
        "path": path,
    }


def paired_summary(rows):
    """Descriptive paired contrasts; repeated episodes are not training seeds."""
    grouped = {}
    for row in rows:
        key = (row["profile_id"], row["scenario_id"], row["training_seed"])
        grouped.setdefault(key, {})[row["controller"]] = row
    comparisons = {}
    for pair in grouped.values():
        baseline = pair.get("fast_actor_critic")
        if baseline is None:
            continue
        for name, row in pair.items():
            if name == "fast_actor_critic":
                continue
            comparisons.setdefault(name, []).append(row["value"] - baseline["value"])
    return {
        name: {
            "paired_cases": len(values),
            "mean_value_delta": math.fsum(values) / len(values),
            "minimum_value_delta": min(values),
            "maximum_value_delta": max(values),
        }
        for name, values in comparisons.items()
    }
