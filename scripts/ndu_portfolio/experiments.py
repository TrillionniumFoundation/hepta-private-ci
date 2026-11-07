"""Predeclared toy comparisons with a shared router and exact outcome scoring.

Model-derived toy quality is not evidence about generated text, images or media.
Controller timings below are diagnostics; no equal physical-compute claim follows.
"""

from dataclasses import replace
from functools import lru_cache
import math
import time

import numpy as np

from .core import Config, Environment, certainty_equivalent, evaluate_policy, optimal
from .gradients import SoftmaxPolicy, policy_value_gradient

ACTION_ORDER = ("generate_0", "generate_1", "generate_2", "verify", "stop")
SEEDS = (11, 29, 47)


def task_configs():
    """Task families fixed before inspecting results; holdouts are never fitted."""
    return {
        "train_text_image": Config(),
        "train_three_branch": Config(branches=3, budget=6, horizon=7),
        "heldout_tight_budget": Config(budget=4, horizon=5),
        "heldout_cost_shift": Config(
            budget=7, horizon=8, costs=(2, 1), success_probabilities=(0.42, 0.83)
        ),
        "heldout_three_branch": Config(
            branches=3, budget=5, horizon=6, success_probabilities=(0.8, 0.4, 0.7)
        ),
    }


def features(env, state, freeze_preference=False, no_interaction_features=False):
    """Public current-state features; no future outcome or optimal value input."""
    n = env.config.branches
    q = list(state.quality) + [0] * (3 - n)
    probabilities = list(env.config.success_probabilities) + [0] * (3 - n)
    costs = list(env.config.costs) + [0] * (3 - n)
    durations = list(env.config.durations) + [0] * (3 - n)
    preference = 0 if freeze_preference else state.preference
    result = np.asarray(
        [
            1.0,
            *[v / 2 for v in q],
            *[float(i < n) for i in range(3)],
            *probabilities,
            *[v / 4 for v in costs],
            *[v / 4 for v in durations],
            float(preference == 0),
            float(preference == 1),
            state.budget / 10,
            state.elapsed / 10,
            (env.config.horizon - state.elapsed) / 10,
            float(state.verified),
            min(state.quality) / 2,
            q[0] * q[1] / 4,
            q[0] * q[2] / 4,
            q[1] * q[2] / 4,
        ],
        dtype=np.float64,
    )
    if no_interaction_features:
        result[-4:] = 0.0
    return result


class SharedRouter:
    """Fixed-capacity linear masked router; transferable across 2/3 branches."""

    def __init__(self, weights, freeze_preference=False, no_interaction_features=False):
        self.weights = np.asarray(weights, dtype=np.float64).copy()
        self.freeze_preference = freeze_preference
        self.no_interaction_features = no_interaction_features

    def policy(self, env):
        def choose(state):
            actions = env.actions(state)
            columns = [ACTION_ORDER.index(a) for a in actions]
            logits = (
                features(
                    env, state, self.freeze_preference, self.no_interaction_features
                )
                @ self.weights[:, columns]
            )
            probabilities = np.exp(logits - logits.max())
            probabilities /= probabilities.sum()
            return dict(zip(actions, probabilities.tolist()))

        return choose


def train_router(configs, seed, variant="ndu", steps=80):
    "Same feature space, explicit ablation masks, initialization and update budget.\n\nEach update uses exact model-based gradients, not an actor-critic estimator.\nOnly the two train tasks enter optimization; exact DP is used only for evaluation.\n"
    if variant not in ("ndu", "ordinary_router", "no_interaction", "static_preference"):
        raise ValueError("unknown router variant")
    if type(steps) is not int or steps <= 0:
        raise ValueError("positive training steps required")
    freeze = variant == "static_preference"
    no_interaction_features = variant == "no_interaction"
    environments, policies, matrices = [], [], []
    for config in configs:
        if variant == "ordinary_router":
            config = replace(config, risk=0.0)
        elif freeze:
            config = replace(config, dynamic_preferences=False)
        env = Environment(config)
        policy = SoftmaxPolicy(env, seed)
        matrices.append(
            np.stack(
                [
                    features(env, s, freeze, no_interaction_features)
                    for s in policy.states
                ]
            )
        )
        environments.append(env)
        policies.append(policy)
    weights = np.random.default_rng(seed).normal(0, 0.03, (matrices[0].shape[1], 5))
    first, second = np.zeros_like(weights), np.zeros_like(weights)
    started = time.perf_counter()
    initial = None
    for step in range(1, steps + 1):
        gradient, values = np.zeros_like(weights), []
        for policy, matrix in zip(policies, matrices):
            columns = [ACTION_ORDER.index(a) for a in policy.actions]
            policy.theta = matrix @ weights[:, columns]
            value, logits_gradient = policy_value_gradient(policy)
            values.append(value)
            gradient[:, columns] += matrix.T @ logits_gradient / len(policies)
        if initial is None:
            initial = float(np.mean(values))
        norm = np.linalg.norm(gradient)
        gradient /= max(1.0, norm)
        first = 0.9 * first + 0.1 * gradient
        second = 0.999 * second + 0.001 * gradient**2
        weights += (
            0.08
            * (first / (1 - 0.9**step))
            / (np.sqrt(second / (1 - 0.999**step)) + 1e-8)
        )
    router = SharedRouter(weights, freeze, no_interaction_features)
    final = [evaluate_policy(env, router.policy(env)) for env in environments]
    return router, {
        "variant": variant,
        "seed": seed,
        "steps": steps,
        "trainable_parameters": int(weights.size),
        "initial_training_value": initial,
        "final_training_value": float(np.mean(final)),
        "training_wall_seconds": time.perf_counter() - started,
        "model_gradient_evaluations": steps * len(policies),
        "train_reachable_states": [len(p.states) for p in policies],
        "joint_reward_preserved": True,
        "explicit_cross_modal_features": not no_interaction_features,
        "estimator": "exact model-based reverse-mode gradient; no DP labels",
    }


def fixed_policy(env, state):
    """Predeclared branch order, then verify, then stop; no outcome optimization."""
    legal = env.actions(state)
    for i in range(env.config.branches):
        action = f"generate_{i}"
        if state.quality[i] == 0 and action in legal:
            return action
    return "verify" if "verify" in legal else "stop"


def fixed_cyclic_policy(env, state):
    "Fixed cyclic branch priority, spending spare quota before final verification.\n\nOnly hard feasibility and already-saturated branches can skip a scheduled action.\nUnlike the single-pass comparator, this schedule uses spare generation capacity.\n"
    legal = env.actions(state)
    if not all(state.quality):
        return fixed_policy(env, state)
    if state.verified:
        return "stop"
    offset = (env.config.budget - state.budget) % env.config.branches
    for j in range(env.config.branches):
        action = f"generate_{(offset + j) % env.config.branches}"
        if action not in legal:
            continue
        cost, duration = env.cost_duration(action)
        if (
            state.budget >= cost + 1
            and state.elapsed + duration + 1 <= env.config.horizon
        ):
            return action
    return "verify" if "verify" in legal else "stop"


def greedy_policy(env, state):
    """Immediate terminal-score improvement; mandatory completion is reserved."""
    legal = env.actions(state)
    if not all(state.quality):
        return fixed_policy(env, state)
    scores = {}
    for action in legal:
        if action == "stop":
            scores[action] = env.terminal_value(state)
        else:
            cost, duration = env.cost_duration(action)
            outcomes = env.transitions(state, action)
            scores[action] = certainty_equivalent(
                [
                    -env.config.cost_weight * cost
                    + env.config.discount**duration * env.terminal_value(s)
                    for _, s in outcomes
                ],
                [p for p, _ in outcomes],
                env.config.risk,
            )
    return max(scores, key=scores.get)


def limited_planner(env, continuation, depth=2):
    "Receding finite-step lookahead with the learned policy as leaf rollout.\n\nThe leaf value is exact evaluation of a fixed learned policy in the toy model.\nIt is deliberately labelled an oracle continuation, not an available real critic.\n"
    if type(depth) is not int or depth < 1:
        raise ValueError("positive planning depth required")
    counts = {"expanded_states": 0, "leaf_policy_evaluations": 0}

    def choose(start):
        @lru_cache(maxsize=None)
        def visit(state, remaining):
            counts["expanded_states"] += 1
            if remaining == 0:
                counts["leaf_policy_evaluations"] += 1
                return evaluate_policy(env, continuation, start=state), None
            scores = {}
            for action in env.actions(state):
                if action == "stop":
                    scores[action] = env.terminal_value(state)
                else:
                    cost, duration = env.cost_duration(action)
                    outcomes = env.transitions(state, action)
                    scores[action] = certainty_equivalent(
                        [
                            -env.config.cost_weight * cost
                            + env.config.discount**duration * visit(s, remaining - 1)[0]
                            for _, s in outcomes
                        ],
                        [p for p, _ in outcomes],
                        env.config.risk,
                    )
            action = max(scores, key=scores.get)
            return scores[action], action

        return visit(start, depth)[1]

    return choose, counts


def score_policy(env, choose):
    """Exact outcome distribution, tail and feasibility with independent toy labels."""
    decisions, timings, occupancies = {}, {}, {env.initial: 1.0}

    @lru_cache(maxsize=None)
    def visit(state):
        start = time.perf_counter()
        choice = choose(state)
        timings[state] = time.perf_counter() - start
        weights = {choice: 1.0} if isinstance(choice, str) else choice
        if not weights or set(weights) - set(env.actions(state)):
            raise ValueError("illegal evaluation action")
        if any(not math.isfinite(p) or p < 0 for p in weights.values()):
            raise ValueError("invalid evaluation action mass")
        if not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-12):
            raise ValueError("evaluation action probabilities do not sum to one")
        decisions[state] = weights
        terminal = {}
        for action, weight in weights.items():
            if weight == 0:
                continue
            if action == "stop":
                terminal[state] = terminal.get(state, 0.0) + weight
            else:
                for probability, successor in env.transitions(state, action):
                    for final, p in visit(successor).items():
                        terminal[final] = (
                            terminal.get(final, 0.0) + weight * probability * p
                        )
        return terminal

    terminal = visit(env.initial)
    if not math.isclose(sum(terminal.values()), 1.0, abs_tol=1e-10):
        raise ValueError("terminal probability is not conserved")
    for state in sorted(decisions, key=lambda s: s.elapsed):
        for action, weight in decisions[state].items():
            if action != "stop" and weight > 0:
                for probability, successor in env.transitions(state, action):
                    occupancies[successor] = occupancies.get(successor, 0) + (
                        occupancies.get(state, 0) * weight * probability
                    )
    observed = [
        (env.external_metrics(state), p, state) for state, p in terminal.items()
    ]
    quality_tail = sorted((m["weakest_quality"], p) for m, p, _ in observed)
    remaining, bottom = 0.1, 0.0
    for quality, p in quality_tail:
        take = min(remaining, p)
        bottom += take * quality
        remaining -= take
        if remaining <= 1e-12:
            break
    return {
        "recursive_value": evaluate_policy(env, decisions),
        "joint_success_rate": sum(p * m["joint_success"] for m, p, _ in observed),
        "weakest_modality_quality": sum(
            p * m["weakest_quality"] for m, p, _ in observed
        ),
        "weakest_quality_lower_tail_mean_10pct": bottom / 0.1,
        "missing_delivery_rate": sum(
            p * (m["missing_deliveries"] > 0) for m, p, _ in observed
        ),
        "unchecked_cross_modal_rate": sum(
            p * m["unchecked_cross_modal"] for m, p, _ in observed
        ),
        "per_modality_quality": [
            sum(p * m["per_modality_quality"][i] for m, p, _ in observed)
            for i in range(env.config.branches)
        ],
        "expected_generation_compute_units": sum(
            p * (env.config.budget - s.budget) for _, p, s in observed
        ),
        "expected_generation_duration_ticks": sum(
            p * s.elapsed for _, p, s in observed
        ),
        "expected_decision_count": sum(occupancies.values()),
        "controller_wall_seconds_per_episode_diagnostic": sum(
            occupancies[s] * timings[s] for s in timings
        ),
        "budget_violations": sum(
            p for _, p, s in observed if s.budget < 0 or s.elapsed > env.config.horizon
        ),
        "terminal_states": len(terminal),
        "evaluated_decision_states": len(decisions),
        "measurement_scope": "exact toy outcome distribution, not real model quality",
        "physical_compute_matched": False,
    }


def compare_routers(seeds=SEEDS, steps=80, include_planner=True):
    configs = task_configs()
    training = [config for name, config in configs.items() if name.startswith("train_")]
    rows, training_receipts = [], []
    for seed in seeds:
        routers = {}
        for variant in (
            "ndu",
            "ordinary_router",
            "no_interaction",
            "static_preference",
        ):
            routers[variant], receipt = train_router(training, seed, variant, steps)
            training_receipts.append(receipt)
        for task, config in configs.items():
            env = Environment(config)
            optimum, optimal_actions, _ = optimal(env)
            controllers = {
                "fixed_single_pass": lambda s, e=env: fixed_policy(e, s),
                "fixed_cyclic_allocation": lambda s, e=env: fixed_cyclic_policy(e, s),
                "one_step_greedy": lambda s, e=env: greedy_policy(e, s),
                "ordinary_learned_router": routers["ordinary_router"].policy(env),
                "ndu_learned_router": routers["ndu"].policy(env),
                "ndu_no_explicit_cross_modal_features": routers[
                    "no_interaction"
                ].policy(env),
                "ndu_no_dynamic_preference": routers["static_preference"].policy(env),
                "ndu_no_risk": routers["ordinary_router"].policy(env),
                "exact_dp_oracle": lambda s, p=optimal_actions: p[s],
            }
            planner_counts = None
            if include_planner:
                planner, planner_counts = limited_planner(
                    env, routers["ndu"].policy(env)
                )
                controllers["ndu_two_step_oracle_continuation"] = planner
            for label, controller in controllers.items():
                metrics = score_policy(env, controller)
                rows.append(
                    {
                        "seed": seed,
                        "task": task,
                        "split": "heldout" if task.startswith("heldout_") else "train",
                        "controller": label,
                        "optimal_value": optimum,
                        "optimality_gap": optimum - metrics["recursive_value"],
                        **metrics,
                    }
                )
                if label == "ndu_two_step_oracle_continuation":
                    rows[-1]["planning_work"] = dict(planner_counts)
                    rows[-1]["planning_work_scope"] = (
                        "totals over exhaustive evaluation states; leaf rollout recursion "
                        "excluded from expanded_states; not per-episode physical work"
                    )
    return {
        "seeds": list(seeds),
        "training_steps": steps,
        "tasks": {name: vars(c) for name, c in configs.items()},
        "training": training_receipts,
        "comparisons": rows,
        "notes": [
            "No-risk and ordinary learned router are identical in this registered profile.",
            "Heldout configurations never enter gradient fitting or hyperparameter selection.",
            "Planning uses exact model continuation; real learned critic calibration is unmeasured.",
            "Generation units are matched caps; controller wall time is a separate diagnostic.",
            "Cross-modal feature ablation preserves joint reward and verification incentive; it removes only explicit minimum/product features, not every possible cross-modal dependence.",
            "Fixed cyclic allocation spends spare quota; fixed single pass is retained only as a cheaper reference.",
            "This suite does not establish a quality or efficiency advantage on real generation.",
        ],
    }
