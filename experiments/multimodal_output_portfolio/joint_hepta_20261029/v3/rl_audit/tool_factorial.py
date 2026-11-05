"""Finite real-tool 2x2 equivalence control, not a novel-algorithm efficacy test."""

from collections import Counter
import hashlib
import itertools
import math
import time

import numpy as np

from .tool_runtime import ACTIONS, HORIZON, TARIFF, child_usage, failure_controls, run_episode

ETA = 2.0


def protocol():
    return {
        "schema": "hepta.ndu-tool-equivalence.v1",
        "seeds": [51001, 51031, 51061],
        "updates": 500,
        "learning_rate": 3.0,
        "initial_logit_sd": 0.03,
        "eta": ETA,
        "horizon": HORIZON,
        "tariff": dict(TARIFF),
        "cost_unit": "declared_research_credits",
        "initial_counts": [0, 1, 2],
        "prior": [1 / 3] * 3,
        "parameter_pairs": [[2, 3], [-3, 5], [7, -11]],
        "training": ["inherited_flat_ce", "recursive_ce"],
        "inference": ["fixed", "dynamic"],
        "budget": "same initialization and exact full-law updates; CPU separately measured",
        "service_order": "seeded permutation of four cells; same task roster in every cell",
        "qualification_faults": ["syntax_failure", "malformed_success", "deadline_0.25s", "cancel_after_one_action"],
        "fixed_consumes_trained_parameters": False,
        "real_frozen_llm": False,
        "known_model": True,
        "future_window": False,
        "independent_administrator": False,
        "prediction": "The two CE gradients and trained policies agree; no novel-method claim.",
        "confirmation": False,
    }


def build_model():
    """Full public histories; hidden counts are available only to the environment."""
    histories, branches, index = [], [], {}

    def add(history, support):
        state = len(histories)
        index[history] = state
        histories.append(history)
        branches.append([])
        repairs = sum(action == "REPAIR" for action, _ in history)
        for ai, action in enumerate(ACTIONS):
            if action == "STOP":
                for count in support:
                    branches[state].append(
                        (ai, 1 / len(support), -1, float(count <= repairs), TARIFF[action] + TARIFF["ORACLE"])
                    )
                continue
            groups = {}
            for count in support:
                outcome = str(max(0, count - repairs)) if action == "CHECK" else "attempted"
                groups.setdefault(outcome, []).append(count)
            for outcome, counts in groups.items():
                tail = history + ((action, outcome),)
                child = add(tail, counts) if len(tail) < HORIZON else -1
                cost = TARIFF[action] + (TARIFF["ORACLE"] if child < 0 else 0)
                branches[state].append((ai, len(counts) / len(support), child, 0.0, cost))
        return state

    add((), [0, 1, 2])
    masses, returns, rows, states, actions = [], [], [], [], []

    def expand(count, history, path, cost):
        state = index[history]
        repairs = sum(action == "REPAIR" for action, _ in history)
        for ai, action in enumerate(ACTIONS):
            next_path = path + ((state, ai),)
            total = cost + TARIFF[action]
            if action == "STOP" or len(history) + 1 == HORIZON:
                row = len(returns)
                returns.append(float(action == "STOP" and count <= repairs) - total - TARIFF["ORACLE"])
                masses.append(1 / 3)
                for si, aj in next_path:
                    rows.append(row)
                    states.append(si)
                    actions.append(aj)
            else:
                outcome = str(max(0, count - repairs)) if action == "CHECK" else "attempted"
                expand(count, history + ((action, outcome),), next_path, total)

    for count in (0, 1, 2):
        expand(count, (), (), 0.0)
    return {
        "histories": histories,
        "index": index,
        "branches": branches,
        "returns": np.array(returns),
        "log_mass": np.log(masses),
        "path_rows": np.array(rows),
        "states": np.array(states),
        "actions": np.array(actions),
    }


def probabilities(logits):
    shifted = logits - logits.max(axis=1, keepdims=True)
    values = np.exp(shifted)
    return values / values.sum(axis=1, keepdims=True)


def flat_gradient(model, logits):
    """Complete-law tilted trajectory score, the inherited CE-oracle formula."""
    policy = probabilities(logits)
    rows, states, actions = (model[k] for k in ("path_rows", "states", "actions"))
    logs = model["log_mass"] + np.bincount(rows, weights=np.log(policy[states, actions]))
    tilted_logs = logs - ETA * model["returns"]
    peak = tilted_logs.max()
    tilt = np.exp(tilted_logs - peak)
    total = tilt.sum()
    tilt /= total
    counts = np.bincount(states * 3 + actions, weights=tilt[rows], minlength=logits.size).reshape(logits.shape)
    gradient = (counts.sum(axis=1, keepdims=True) * policy - counts) / ETA
    return float(-(peak + np.log(total)) / ETA), gradient


def recursive_gradient(model, logits):
    """Conditional CE reverse derivative with tilted branch occupancies."""
    policy, values, tilted = probabilities(logits), np.zeros(len(logits)), {}
    for state in reversed(range(len(logits))):
        edges = model["branches"][state]
        logs = np.array(
            [
                math.log(policy[state, ai] * mass) - ETA * ((values[child] if child >= 0 else terminal) - cost)
                for ai, mass, child, terminal, cost in edges
            ]
        )
        peak = logs.max()
        weights = np.exp(logs - peak)
        values[state] = -(peak + np.log(weights.sum())) / ETA
        tilted[state] = weights / weights.sum()
    occupancy, gradient = np.zeros(len(logits)), np.zeros_like(logits)
    occupancy[0] = 1.0
    for state, edges in enumerate(model["branches"]):
        action_mass = np.zeros(3)
        for weight, (ai, _, child, _, _) in zip(tilted[state], edges):
            action_mass[ai] += weight
            if child >= 0:
                occupancy[child] += occupancy[state] * weight
        gradient[state] = occupancy[state] * (policy[state] - action_mass) / ETA
    return float(values[0]), gradient


def fit(model, seed, method, updates=None):
    settings = protocol()
    count = settings["updates"] if updates is None else updates
    start, cpu = time.perf_counter(), time.process_time()
    logits = np.random.default_rng(seed).normal(0, settings["initial_logit_sd"], (len(model["histories"]), 3))
    initial_digest = hashlib.sha256(logits.astype("<f8").tobytes()).hexdigest()
    evaluate = {"inherited_flat_ce": flat_gradient, "recursive_ce": recursive_gradient}[method]
    trace, no_update = [], 0
    for _ in range(count):
        value, gradient = evaluate(model, logits)
        if not np.isfinite(gradient).all() or not math.isfinite(value):
            no_update += 1
            break
        trace.append(value)
        logits += settings["learning_rate"] * gradient
    final, _ = evaluate(model, logits)
    return logits, {
        "seed": seed,
        "method": method,
        "requested_updates": count,
        "actual_updates": len(trace),
        "no_update": no_update,
        "ce_trace": trace,
        "initial_parameter_sha256": initial_digest,
        "final_parameter_sha256": hashlib.sha256(logits.astype("<f8").tobytes()).hexdigest(),
        "final_stochastic_ce": final,
        "wall_s": time.perf_counter() - start,
        "cpu_s": time.process_time() - cpu,
        "monetary_cost": None,
    }


def references(model):
    """Exhaustive fixed schedules and exact adaptive known-model Bellman policy."""
    best, schedules = None, 0
    for length in range(HORIZON):
        for prefix in itertools.product(("CHECK", "REPAIR"), repeat=length):
            schedule = prefix + ("STOP",)
            repairs = prefix.count("REPAIR")
            cost = sum(TARIFF[a] for a in schedule) + TARIFF["ORACLE"]
            returns = np.array([float(count <= repairs) - cost for count in (0, 1, 2)])
            ce = -np.log(np.exp(-ETA * returns).mean()) / ETA
            schedules += 1
            if best is None or ce > best["ce"]:
                best = {"schedule": schedule, "ce": float(ce)}
    values, policy = np.zeros(len(model["histories"])), {}
    for state in reversed(range(len(values))):
        q = []
        for ai in range(3):
            moment = sum(
                mass * math.exp(-ETA * ((values[child] if child >= 0 else terminal) - cost))
                for aj, mass, child, terminal, cost in model["branches"][state]
                if aj == ai
            )
            q.append(-math.log(moment) / ETA)
        chosen = int(np.argmax(q))
        values[state], policy[model["histories"][state]] = q[chosen], ACTIONS[chosen]
    return {
        "fixed": best,
        "schedules_enumerated": schedules,
        "adaptive_ce": float(values[0]),
        "adaptive_policy": policy,
    }


def summarize(records):
    returns = [r["return"] for r in records]
    statuses = Counter(r["status"] for r in records)
    terminations = Counter(r["termination_reason"] for r in records)
    verification = Counter(r["verification_status"] for r in records)
    children = [r["child_cpu_s"] for r in records]
    return {
        "n": len(records),
        "quality": float(np.mean([r["quality"] for r in records])),
        "ce": float(-np.log(np.exp(-ETA * np.array(returns)).mean()) / ETA),
        "tariff": float(np.mean([r["tariff"] for r in records])),
        "wall_s": float(np.mean([r["wall_s"] for r in records])),
        "cpu_s": None
        if any(c is None for c in children)
        else float(np.mean([r["parent_cpu_s"] + r["child_cpu_s"] for r in records])),
        "p95_wall_s": float(np.quantile([r["wall_s"] for r in records], 0.95)),
        "p99_wall_s": float(np.quantile([r["wall_s"] for r in records], 0.99)),
        "stop_rate": float(np.mean([r["delivered"] for r in records])),
        "semantic_failure_rate": float(np.mean([r["quality"] == 0 for r in records])),
        "status_counts": {k: statuses[k] for k in ("completed", "failed", "timeout", "cancelled", "expired")},
        "termination_counts": dict(terminations),
        "verification_status_counts": dict(verification),
        "peak_rss_bytes": None,
        "monetary_cost": None,
    }


def break_even(one_time, fixed, dynamic):
    """CPU seconds only; no conversion from tool credits or elapsed wall time."""
    if fixed["quality"] != dynamic["quality"]:
        return {"services": None, "reason": "observed quality differs"}
    if fixed["cpu_s"] is None or dynamic["cpu_s"] is None or one_time is None:
        return {"services": None, "reason": "CPU cost unavailable"}
    delta = fixed["cpu_s"] - dynamic["cpu_s"]
    return {
        "unit": "CPU_seconds",
        "observed_delta_per_service": delta,
        "one_time_cpu_s": one_time,
        "services": None,
        "services_measured_scope_only": math.floor(one_time / delta) + 1 if delta > 0 else None,
        "complete_one_time_cost_known": False,
        "reason": "descriptive repeated-template observation; no stable deployment estimate"
        if delta > 0
        else "no positive measured saving",
    }


def qualification_conforms(records):
    """A failed or malformed verifier is an unmet gate, not a lost experiment."""
    if not records:
        return False
    for record in records:
        oracle = record["events"][-1]
        if not (
            record["status"] == "expired"
            and record["verification_status"] == "completed"
            and oracle["output_schema_valid"] is True
            and isinstance(oracle["result"], dict)
            and oracle["result"].get("quality") == 1
        ):
            return False
        repaired = 0
        for action, outcome in record["history"]:
            if action == "CHECK" and outcome != str(max(0, len(record["task"]["bugs"]) - repaired)):
                return False
            repaired += action == "REPAIR"
    return True


def run_study(seeds=None):
    """Formal invocation is allowed only after the caller freezes source/protocol."""
    settings = protocol()
    selected = settings["seeds"] if seeds is None else list(seeds)
    if not selected or len(set(selected)) != len(selected) or any(type(x) is not int for x in selected):
        raise ValueError("Unique integer seeds required")
    start, cpu, child = time.perf_counter(), time.process_time(), child_usage()
    model = build_model()
    refs = references(model)
    setup_cpu = time.process_time() - cpu
    tasks = [
        {
            "id": f"p{i}-b{n}",
            "scale": a,
            "offset": b,
            "bugs": [] if n == 0 else (["scale"] if i % 2 == 0 else ["offset"]) if n == 1 else ["scale", "offset"],
        }
        for i, (a, b) in enumerate(settings["parameter_pairs"])
        for n in (0, 1, 2)
    ]
    # Qualification is real subprocess execution; model fitting uses the full known law.
    validation = [run_episode(lambda h: "CHECK" if len(h) % 2 == 0 else "REPAIR", task) for task in tasks]
    qualification_ok = qualification_conforms(validation)
    faults = failure_controls()
    fault_controls_ok = (
        [r["status"] for r in faults] == ["failed", "failed", "timeout", "cancelled"]
        and "entered" in faults[2]["stdout"]
        and faults[1]["returncode"] == 0
    )
    qualification = validation + faults
    validation_cpu = (
        None
        if any(r["child_cpu_s"] is None for r in qualification)
        else sum(r["parent_cpu_s"] + r["child_cpu_s"] for r in qualification)
    )
    records, training, pairs, matrices, models = [], [], [], [], []
    for seed in selected:
        fitted = {}
        for method in settings["training"]:
            fitted[method], receipt = fit(model, seed, method)
            training.append(receipt)
            models.append(
                {
                    "seed": seed,
                    "method": method,
                    "logits": fitted[method].tolist(),
                    "dtype": "float64",
                    "sha256_little_endian": receipt["final_parameter_sha256"],
                }
            )
        gap = float(np.max(np.abs(fitted[settings["training"][0]] - fitted[settings["training"][1]])))
        pairs.append(
            {
                "seed": seed,
                "max_parameter_difference": gap,
                "action_disagreements": int(
                    np.count_nonzero(
                        fitted[settings["training"][0]].argmax(1) != fitted[settings["training"][1]].argmax(1)
                    )
                ),
            }
        )
        matrix = {"seed": seed, "cells": {}}
        cells = list(itertools.product(settings["training"], settings["inference"]))
        np.random.default_rng(seed + 90000).shuffle(cells)
        matrix["execution_order"] = cells
        for method, inference in cells:
            policy = {h: ACTIONS[int(np.argmax(fitted[method][i]))] for i, h in enumerate(model["histories"])}
            select = (lambda h: refs["fixed"]["schedule"][len(h)]) if inference == "fixed" else policy.__getitem__
            group = []
            for task in tasks:
                row = run_episode(select, task)
                row.update({"seed": seed, "training": method, "inference": inference})
                records.append(row)
                group.append(row)
            matrix["cells"][method + "/" + inference] = summarize(group)
        a, b, c, d = (
            matrix["cells"][key]["ce"]
            for key in (
                "inherited_flat_ce/fixed",
                "recursive_ce/fixed",
                "inherited_flat_ce/dynamic",
                "recursive_ce/dynamic",
            )
        )
        matrix["effects"] = {
            "training_on_fixed": b - a,
            "training_on_dynamic": d - c,
            "inference_on_flat": c - a,
            "inference_on_recursive": d - b,
            "interaction": d - c - b + a,
            "fixed_training_path_absent": True,
        }
        one_time = (
            None
            if validation_cpu is None
            else setup_cpu
            + validation_cpu
            + next(r["cpu_s"] for r in training if r["seed"] == seed and r["method"] == "recursive_ce")
        )
        matrix["break_even"] = break_even(
            one_time, matrix["cells"]["recursive_ce/fixed"], matrix["cells"]["recursive_ce/dynamic"]
        )
        matrices.append(matrix)
    reference_runs = [run_episode(refs["adaptive_policy"].__getitem__, task) for task in tasks]
    after = child_usage()
    return {
        "protocol": settings,
        "executed_seeds": selected,
        "state_count": len(model["histories"]),
        "training": training,
        "equivalence": pairs,
        "matrices": matrices,
        "records": records,
        "validation": validation,
        "model_conformance": qualification_ok,
        "qualification_faults": faults,
        "fault_controls_passed": fault_controls_ok,
        "fixed_reference": refs["fixed"],
        "fixed_schedules_enumerated": refs["schedules_enumerated"],
        "adaptive_reference_ce": refs["adaptive_ce"],
        "adaptive_reference": reference_runs,
        "adaptive_reference_summary": summarize(reference_runs),
        "wall_s": time.perf_counter() - start,
        "parent_cpu_s": time.process_time() - cpu,
        "child_cpu_s": None if after is None else after - child,
        "once_only_setup_cpu_s": setup_cpu,
        "qualification_cpu_s": validation_cpu,
        "trained_models": models,
        "parameter_history_order": model["histories"],
        "confirmation": False,
        "novel_algorithm_established": False,
        "physical_costs_monetized": False,
        "fixed_consumes_trained_parameters": False,
        "limitations": [
            "Known finite model and frozen string-repair rules; no LLM or multimodal generator.",
            "Both training rows optimize the same inherited entropic objective.",
            "Fixed inference ignores trained parameters; its training contrast is structurally zero.",
            "Training uses stochastic policies; service uses deterministic argmax.",
            "Exact planner has the same full known model and public histories.",
            "Small repeated templates and local timings are not future-window or independent deployment evidence.",
        ],
    }
