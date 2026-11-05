"""Frozen-bank JAC optimization diagnosis; model-based methods, not new RL."""

import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import time

from .core import evaluate, optimal_policy, policy_gradient, softmax_policy
from .finite_study import build_problem, fit_actor, sample_model


def greedy_policy(rows):
    """Stable row maximization; rows can be probabilities or action values."""
    result = {}
    for state, row in rows.items():
        chosen = max(sorted(row), key=row.get)
        result[state] = {action: float(action == chosen) for action in row}
    return result


def residual_bound(model, result, rho):
    """Finite-DAG upper bound on empirical V* - Vpi, without solving for V*."""
    residuals, bounds = {}, {}
    for state in result["order"]:
        residuals[state] = max(0.0, max(result["action_values"][state].values())
                               - result["values"][state])
        continuation = max((math.exp(-rho * o.duration) * bounds[o.next_state]
                            for law in model[state].values() for o in law
                            if o.next_state is not None), default=0.0)
        bounds[state] = residuals[state] + continuation
    return residuals, bounds


def initialize(model, seed):
    rng = random.Random(seed)
    return {s: {a: rng.uniform(-0.1, 0.1) for a in row} for s, row in model.items()}


def mirror_actor(model, root, seed, eta, rho, steps=120, step_size=2.0):
    """Exact empirical all-row mirror improvement; every row has model access.

    Updating log pi by alpha*Q removes occupancy/Fisher attenuation, including
    at rows unreachable from the current root policy. Hence this is explicitly
    model-based all-state policy improvement, not a sampled on-policy estimator.
    """
    started = time.perf_counter(), time.process_time()
    logits = initialize(model, seed)
    trace = []
    for _ in range(steps):
        result = evaluate(model, root, softmax_policy(model, logits), eta, rho)
        trace.append(result["value"])
        for state, row in logits.items():
            for action in row:
                row[action] += step_size * result["advantages"][state][action]
    policy = softmax_policy(model, logits)
    return policy, {"updates": steps, "policy_evaluations": steps,
        "conditional_action_backups": steps * sum(map(len, model.values())),
        "wall_seconds": time.perf_counter()-started[0],
        "cpu_seconds": time.process_time()-started[1],
        "empirical_trace": trace}


def empirical_policy_iteration(model, root, initial, eta, rho, max_updates=16,
                               tolerance=1e-10):
    """Greedy improvement until a finite-DAG Bellman residual certifies the gap."""
    started = time.perf_counter(), time.process_time()
    policy, trace, updates = initial, [], 0
    for iteration in range(max_updates + 1):
        result = evaluate(model, root, policy, eta, rho)
        residuals, bounds = residual_bound(model, result, rho)
        trace.append({"value": result["value"], "root_gap_bound": bounds[root],
                      "max_local_residual": max(residuals.values())})
        if bounds[root] <= tolerance or iteration == max_updates:
            break
        policy = greedy_policy(result["action_values"])
        updates += 1
    return policy, {"updates": updates, "policy_evaluations": len(trace),
        "conditional_action_backups": len(trace) * sum(map(len, model.values())),
        "empirical_gap_upper_bound": bounds[root],
        "converged": bounds[root] <= tolerance, "empirical_trace": trace,
        "wall_seconds": time.perf_counter()-started[0],
        "cpu_seconds": time.process_time()-started[1]}


def evaluate_method(truth, model, root, policy, eta, rho, planner, true_optimum):
    fitted = evaluate(model, root, policy, eta, rho)
    actual = evaluate(truth, root, policy, eta, rho)
    residuals, bounds = residual_bound(model, fitted, rho)
    return {"empirical_value": fitted["value"], "true_value": actual["value"],
        "empirical_optimization_gap": planner["value"] - fitted["value"],
        "model_optimism": fitted["value"] - actual["value"],
        "true_regret": true_optimum - actual["value"],
        "empirical_gap_upper_bound": bounds[root],
        "max_local_residual": max(residuals.values()), "root_policy": policy[root]}


def run(protocol):
    start = time.perf_counter(), time.process_time()
    truth, root, _ = build_problem()
    eta, rho = protocol["eta"], protocol["rho"]
    # Truth is read only for validation. It is never passed into any learner.
    true_optimum = optimal_policy(truth, root, eta, rho)["value"]
    historical = json.loads((Path(__file__).parent / "evidence/finite.json").read_text())
    old = {row["seed"]: row for row in historical["rows"]}
    rows, instrument_wall, instrument_cpu = [], 0.0, 0.0
    seeds = protocol["reproduction_seeds"] + protocol["heldout_bank_seeds"]
    for seed in seeds:
        begin = time.perf_counter(), time.process_time()
        model, sampling = sample_model(truth, protocol["draws_per_state_action"], random.Random(seed))
        sampling.update(wall_seconds=time.perf_counter()-begin[0],
                        cpu_seconds=time.process_time()-begin[1])
        bank = {s: {a: [asdict(o) for o in law] for a, law in row.items()}
                for s, row in model.items()}
        bank_hash = hashlib.sha256(json.dumps(bank, sort_keys=True,
                                  separators=(",", ":")).encode()).hexdigest()
        actor_seed = seed + protocol["actor_seed_offset"]
        vanilla, vanilla_cost = fit_actor(model, root, actor_seed, eta, rho,
                                          protocol["vanilla_steps"])
        vanilla_cost.update(policy_evaluations=protocol["vanilla_steps"],
            conditional_action_backups=protocol["vanilla_steps"] * sum(map(len, model.values())))
        mirror, mirror_cost = mirror_actor(model, root, actor_seed, eta, rho,
                             protocol["mirror_steps"], protocol["mirror_step_size"])
        initial = softmax_policy(model, initialize(model, actor_seed))
        pi, pi_cost = empirical_policy_iteration(model, root, initial, eta, rho,
            protocol["policy_iteration_max_updates"], protocol["empirical_residual_tolerance"])
        begin = time.perf_counter(), time.process_time()
        planner = optimal_policy(model, root, eta, rho)
        dp_cost = {"policy_evaluations": 0, "optimality_sweeps": 1,
            "conditional_action_backups": sum(map(len, model.values())),
            "wall_seconds": time.perf_counter()-begin[0],
            "cpu_seconds": time.process_time()-begin[1]}
        policies = {"original_vanilla": vanilla, "vanilla_argmax": greedy_policy(vanilla),
                    "all_state_mirror": mirror, "all_state_mirror_argmax": greedy_policy(mirror),
                    "empirical_policy_iteration": pi, "same_bank_dp": planner["policy"]}
        begin = time.perf_counter(), time.process_time()
        metrics = {name: evaluate_method(truth, model, root, policy, eta, rho,
                                        planner, true_optimum) for name, policy in policies.items()}
        raw, dp = metrics["original_vanilla"], metrics["same_bank_dp"]
        decomposition = {"true_dp_minus_actor": dp["true_value"]-raw["true_value"],
            "empirical_optimization_gap": raw["empirical_optimization_gap"],
            "dp_model_optimism": dp["model_optimism"],
            "actor_model_optimism": raw["model_optimism"]}
        decomposition["identity_error"] = (decomposition["true_dp_minus_actor"]
            - raw["empirical_optimization_gap"] + dp["model_optimism"] - raw["model_optimism"])
        # Exact tilted visitation diagnostics of the final vanilla actor.
        log_pi = {s: {a: math.log(max(p, 1e-300)) for a, p in row.items()}
                  for s, row in vanilla.items()}
        final = policy_gradient(model, root, log_pi, eta, rho)
        occupancy = [v for s, v in final["occupancy"].items() if s != root]
        diagnostics = {"nonroot_min_tilted_occupancy": min(occupancy),
            "nonroot_median_tilted_occupancy": statistics.median(occupancy),
            "zero_occupancy_states": sum(v == 0 for v in occupancy),
            "root_local_residual": max(final["action_values"][root].values())-final["value"]}
        reproduction_error = None if seed not in old else max(
            abs(raw["true_value"] - old[seed]["actor_true_value"]),
            abs(dp["true_value"] - old[seed]["same_bank_dp_true_value"]))
        instrument_wall += time.perf_counter()-begin[0]
        instrument_cpu += time.process_time()-begin[1]
        rows.append({"seed": seed, "split": "reproduction" if seed in old else "heldout_bank",
            "bank_sha256": bank_hash, "sampling": sampling, "metrics": metrics,
            "policies": policies, "decomposition": decomposition, "diagnostics": diagnostics,
            "reproduction_max_abs_error": reproduction_error,
            "costs": {"original_vanilla": vanilla_cost, "all_state_mirror": mirror_cost,
                      "empirical_policy_iteration": pi_cost, "same_bank_dp": dp_cost},
            "argmax_cost": "deterministic row extraction; parent training required; not timed separately"})
    summaries = {}
    for split in ("reproduction", "heldout_bank"):
        part = [r for r in rows if r["split"] == split]
        summaries[split] = {name: {
            "mean_true_value": statistics.mean(r["metrics"][name]["true_value"] for r in part),
            "mean_empirical_gap": statistics.mean(r["metrics"][name]["empirical_optimization_gap"] for r in part),
            "max_empirical_gap": max(r["metrics"][name]["empirical_optimization_gap"] for r in part),
            "mean_true_regret": statistics.mean(r["metrics"][name]["true_regret"] for r in part),
            "true_wins_vs_vanilla": sum(r["metrics"][name]["true_value"] >
                                    r["metrics"]["original_vanilla"]["true_value"]+1e-12 for r in part),
            "true_losses_vs_same_bank_dp": sum(r["metrics"][name]["true_value"] <
                                    r["metrics"]["same_bank_dp"]["true_value"]-1e-12 for r in part)}
            for name in protocol["methods"]}
    return {"schema": "ndu-jac.optimization-gap-study.v1", "protocol": protocol,
        "state_count": len(truth), "state_action_count": sum(map(len, truth.values())),
        "true_optimum": true_optimum, "rows": rows, "summary": summaries,
        "validation_instrumentation": {"wall_seconds": instrument_wall, "cpu_seconds": instrument_cpu},
        "total_wall_seconds": time.perf_counter()-start[0],
        "total_cpu_seconds": time.process_time()-start[1],
        "scope": "same synthetic task, independent banks; planning parity is not algorithmic originality or net-economic benefit"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Refuse to overwrite evidence; select a new output path")
    protocol_bytes = args.protocol.read_bytes()
    result = run(json.loads(protocol_bytes))
    result["protocol_sha256"] = hashlib.sha256(protocol_bytes).hexdigest()
    result["source_sha256"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (Path(__file__), Path(__file__).with_name("core.py"),
                  Path(__file__).with_name("finite_study.py"))}
    args.output.write_text(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)+"\n")
