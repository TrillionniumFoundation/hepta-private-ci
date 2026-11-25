"""Post-run analytic validation of frozen policies; zero new sampled trajectories.

Expected costs integrate the registered innovation covariance conditional on
the 27 previously observed initial states. They are not a new learning study.
The original protocol, algorithm and result remain byte-preserved.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from . import pft_horizon as experiment


def affine_policy(method, prepared, iterations):
    policies = []
    for k, mapping in enumerate(prepared["maps"]):
        if method in ("full_riccati", "blind_belief_ablation"):
            F = -prepared["full"]["gains"][k].copy()
            if method == "blind_belief_ablation":
                F[:, F.shape[1] // 2 :] = 0.0
            f = prepared["full"]["offsets"][k]
        elif method == "pft_compressed":
            F = -prepared["bases"][k] @ prepared["small"]["gains"][k]
            f = prepared["bases"][k] @ prepared["small"]["offsets"][k]
        else:
            if method == "single_action_ridge":
                M = mapping["single"]
                inverse_response = mapping["whiten"] @ np.linalg.solve(
                    M.T @ M + np.eye(M.shape[1]), M.T
                )
            elif method == "full_horizon_gd":
                values, vectors = np.linalg.eigh(mapping["H"])
                response = (
                    1.0 - np.power(1.0 - mapping["step"] * values, iterations)
                ) / values
                inverse_response = (
                    (vectors * response) @ (vectors.T @ mapping["G"].T)
                )[: mapping["width"]]
            else:
                raise ValueError("unknown frozen policy")
            F, f = (
                -inverse_response @ mapping["O"],
                inverse_response @ mapping["target"],
            )
        policies.append((F, f))
    return policies


def innovation_covariance(width, k, spec):
    Q = np.zeros((2 * width, 2 * width))
    if k + 1 == spec["reveal_transition"]:
        Q[width:, width:] = spec["innovation_sigma"] ** 2 * np.eye(width)
    return Q


def expected_cost(system, policy, initial, C, R, spec):
    width, h = len(initial) // 2, spec["horizon"]
    mean, covariance = initial.copy(), np.zeros((len(initial), len(initial)))
    task_map, keep_map = np.c_[C, -C], np.c_[R, np.zeros_like(R)]
    keep_target = R @ initial[:width]
    totals = dict(task=0.0, retention=0.0, effort=0.0)
    for k in range(h + 1):
        task_weight = spec["terminal_task"] if k == h else spec["stage_task"]
        keep_weight = spec["terminal_retention"] if k == h else spec["stage_retention"]
        task_error, keep_error = task_map @ mean, keep_map @ mean - keep_target
        totals["task"] += (
            0.5
            * task_weight
            * (task_error @ task_error + np.trace(task_map @ covariance @ task_map.T))
        )
        totals["retention"] += (
            0.5
            * keep_weight
            * (keep_error @ keep_error + np.trace(keep_map @ covariance @ keep_map.T))
        )
        if k == h:
            break
        F, f = policy[k]
        action_mean, action_covariance = F @ mean + f, F @ covariance @ F.T
        cost = system[-1][k]
        totals["effort"] += 0.5 * (
            action_mean @ cost @ action_mean + np.trace(cost @ action_covariance)
        )
        transition = system[0][k] + system[1][k] @ F
        mean = transition @ mean + system[1][k] @ f
        covariance = transition @ covariance @ transition.T + innovation_covariance(
            width, k, spec
        )
        covariance = (covariance + covariance.T) / 2
    totals = {key: float(value) for key, value in totals.items()}
    totals["total"] = sum(totals.values())
    return totals


def backward_expected_cost(system, policy, initial, spec):
    """Separate backward quadratic value evaluation including noise constants."""
    A, E, L, targets, costs = system
    S, t, c = L[-1].T @ L[-1], -L[-1].T @ targets[-1], 0.5 * targets[-1] @ targets[-1]
    width = len(initial) // 2
    for k in range(len(A) - 1, -1, -1):
        F, f = policy[k]
        transition, shift = A[k] + E[k] @ F, E[k] @ f
        next_S = L[k].T @ L[k] + F.T @ costs[k] @ F + transition.T @ S @ transition
        next_t = (
            -L[k].T @ targets[k] + F.T @ costs[k] @ f + transition.T @ (S @ shift + t)
        )
        c += (
            0.5 * targets[k] @ targets[k]
            + 0.5 * f @ costs[k] @ f
            + 0.5 * shift @ S @ shift
            + t @ shift
            + 0.5 * np.trace(S @ innovation_covariance(width, k, spec))
        )
        S, t = next_S, next_t
    return float(0.5 * initial @ S @ initial + t @ initial + c)


def audit(protocol, result):
    spec = protocol["specification"]
    expected_groups = {(w, s) for w in spec["widths"] for s in spec["seeds"]}
    if (
        len(result["groups"]) != len(expected_groups)
        or {(g["width"], g["seed"]) for g in result["groups"]} != expected_groups
    ):
        raise ValueError("frozen group census differs")
    rows, pairs, action_error, arithmetic_error = [], [], 0.0, 0.0
    for group in result["groups"]:
        width, seed = group["width"], group["seed"]
        expected_slots = {
            (i, p)
            for i in range(spec["initial_states"])
            for p in range(spec["innovation_paths"])
        }
        if (
            len(group["episodes"]) != len(expected_slots)
            or {(e["origin"], e["path"]) for e in group["episodes"]} != expected_slots
        ):
            raise ValueError("frozen episode census differs")
        conditional = []
        for setup in group["shared_setups"]:
            origin, initial = setup["origin"], np.asarray(setup["initial"])
            system, C, R = experiment.make_system(width, seed, initial[:width], spec)
            prepared = experiment.prepare(
                system, dict(feature_response=0, solve=0, validation=0, communication=0)
            )
            expected, feedback = {}, {}
            for method in experiment.METHODS:
                with np.errstate(divide="ignore", invalid="raise"):
                    feedback[method] = affine_policy(
                        method, prepared, spec["gd_iterations"]
                    )
                expected[method] = expected_cost(
                    system, feedback[method], initial, C, R, spec
                )
                backward = backward_expected_cost(
                    system, feedback[method], initial, spec
                )
                arithmetic_error = max(
                    arithmetic_error, abs(backward - expected[method]["total"])
                )
            conditional.append(expected)
            rows.append(dict(width=width, seed=seed, origin=origin, expected=expected))
            for episode in (e for e in group["episodes"] if e["origin"] == origin):
                for method in experiment.METHODS:
                    state = initial.copy()
                    for k, saved in enumerate(episode["methods"][method]["actions"]):
                        F, f = feedback[method][k]
                        action = np.asarray(saved)
                        action_error = max(
                            action_error, float(np.max(np.abs(F @ state + f - action)))
                        )
                        state = system[0][k] @ state + system[1][k] @ action
                        if k + 1 == spec["reveal_transition"]:
                            state[width:] += episode["innovation"]
                    if not np.allclose(
                        state,
                        episode["methods"][method]["endpoint"],
                        atol=1e-12,
                        rtol=1e-12,
                    ):
                        raise ValueError("recorded endpoint cannot be reconstructed")
        actual = {
            m: float(
                np.mean(
                    [e["methods"][m]["objective"]["total"] for e in group["episodes"]]
                )
            )
            for m in experiment.METHODS
        }
        means = {
            m: float(np.mean([e[m]["total"] for e in conditional]))
            for m in experiment.METHODS
        }
        pairs.append(
            dict(
                width=width,
                seed=seed,
                episode_count=len(group["episodes"]),
                sample_mean=actual,
                exact_conditional_mean=means,
                sample_paired_delta={
                    m: actual[m] - actual["full_riccati"] for m in experiment.METHODS
                },
                expected_paired_delta={
                    m: means[m] - means["full_riccati"] for m in experiment.METHODS
                },
            )
        )
    margins = [
        r["expected"][m]["total"] - r["expected"]["full_riccati"]["total"]
        for r in rows
        for m in ("single_action_ridge", "full_horizon_gd", "blind_belief_ablation")
    ]
    parity = max(
        abs(
            r["expected"]["pft_compressed"]["total"]
            - r["expected"]["full_riccati"]["total"]
        )
        for r in rows
    )
    return dict(
        passed=action_error < 1e-10
        and arithmetic_error < 1e-10
        and min(margins) >= -1e-10
        and parity < 1e-10,
        exact_conditional_results=rows,
        group_descriptive_pairs=pairs,
        minimum_competitor_expected_gap=min(margins),
        maximum_expected_pft_parity_error=parity,
        maximum_saved_action_reconstruction_error=action_error,
        maximum_forward_backward_expectation_error=arithmetic_error,
        rls_interpretation="RLS can solve the complete condensed horizon too; the single-action restriction is a planner choice, not an RLS limitation",
        inference_scope="nine width/seed groups described; no confidence interval treating 108 episodes as independent sources",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    protocol, protocol_sha = experiment.load_protocol(args.protocol)
    raw = args.result.read_bytes()
    result = json.loads(raw)
    if (
        result["protocol_sha256"] != protocol_sha
        or result["source_sha256"] != protocol["source_sha256"]
    ):
        raise ValueError("original result/source binding differs")
    began = time.perf_counter_ns()
    report = audit(protocol, result)
    report.update(
        schema="hepta.e1e6.pft-horizon-postrun-analytic-audit.v1",
        scope=__doc__,
        new_samples=0,
        new_training_runs=0,
        original_result_sha256=hashlib.sha256(raw).hexdigest(),
        protocol_sha256=protocol_sha,
        auditor_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        wall_ns=time.perf_counter_ns() - began,
    )
    with args.output.open("x", encoding="utf-8") as out:
        json.dump(report, out, ensure_ascii=False, allow_nan=False, indent=2)
        out.write("\n")
    print(
        json.dumps(
            {
                k: v
                for k, v in report.items()
                if k
                not in ("exact_conditional_results", "group_descriptive_pairs", "scope")
            }
        )
    )
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
