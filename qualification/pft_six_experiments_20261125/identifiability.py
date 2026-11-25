#!/usr/bin/env python3
"""PFT1: controlled-system identifiability; this is not an LLM experiment."""
import argparse
import hashlib
import json
import os
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
import numpy as np

RHO = 0.70


def digest(array):
    value = np.ascontiguousarray(array, dtype="<f8")
    return hashlib.sha256(str(value.shape).encode() + value.tobytes()).hexdigest()


def ground_truth(size, seed):
    rng = np.random.default_rng(np.random.SeedSequence([seed, size, 910]))
    left = np.linalg.qr(rng.normal(size=(size, size)))[0]
    right = np.linalg.qr(rng.normal(size=(size, size)))[0]
    return (left * np.linspace(0.6, 1.4, size)) @ right.T


def episode(weight, rng, horizon, noise, mismatch=False, ood=False, drives=None):
    size = len(weight)
    if drives is None:
        q = rng.normal(size=size)
        inputs = []
        for _ in range(horizon):
            innovation = rng.standard_t(4, size=size) / np.sqrt(2) if ood else rng.normal(size=size)
            q = (0.8 if ood else 0.6) * q + (1.2 if ood else 0.8) * innovation
            inputs.append(q.copy())
        drives = np.asarray(inputs)
    states = [rng.normal(scale=2.0 if ood else 1.0, size=size)]
    for q in drives:
        feature = np.tanh(q) if mismatch else q
        states.append(RHO * states[-1] + weight @ feature)
    states = np.asarray(states)
    observed = states + rng.normal(scale=noise, size=states.shape)
    return {"q": np.asarray(drives), "true": states, "observed": observed}


def design(episodes, full_trajectory):
    xs, ys = [], []
    for item in episodes:
        q, s = item["q"], item["observed"]
        if full_trajectory:
            xs.extend(q)
            ys.extend(s[1:] - RHO * s[:-1])
        else:
            powers = RHO ** np.arange(len(q) - 1, -1, -1)
            xs.append(powers @ q)
            ys.append(s[-1] - RHO ** len(q) * s[0])
    return np.asarray(xs), np.asarray(ys)


def relative_error(estimated, expected):
    return float(np.linalg.norm(estimated - expected) / max(np.linalg.norm(expected), 1e-15))


def fit_and_measure(x, y, weight, tests, ridge_relative):
    size = len(weight)
    singular = np.linalg.svd(x, compute_uv=False)
    tolerance = np.finfo(float).eps * max(x.shape) * singular[0]
    rank = int(np.sum(singular > tolerance))
    regularizer = ridge_relative * float(np.trace(x.T @ x)) / size
    if regularizer == 0:
        fitted = np.linalg.lstsq(x, y, rcond=None)[0].T
    else:
        fitted = np.linalg.solve(x.T @ x + regularizer * np.eye(size), x.T @ y).T
    truth_paths, fitted_paths = [], []
    for item in tests:
        path = [item["true"][0]]
        for q in item["q"]:
            path.append(RHO * path[-1] + fitted @ q)
        truth_paths.append(item["true"][1:])
        fitted_paths.append(path[1:])
    truth_paths, fitted_paths = np.asarray(truth_paths), np.asarray(fitted_paths)
    values = {
        "parameter_relative_error": relative_error(fitted, weight),
        "training_observation_relative_error": relative_error(x @ fitted.T, y),
        "heldout_path_relative_error": relative_error(fitted_paths, truth_paths),
        "heldout_terminal_relative_error": relative_error(fitted_paths[:, -1], truth_paths[:, -1]),
        "design_rank": rank,
        "full_parameter_operator_rank": rank * size,
        "parameter_count": size * size,
        "rank_fraction": rank / size,
        "per_output_singular_values": np.pad(singular, (0, size - len(singular))).tolist(),
        "nonzero_condition_number": float(singular[0] / singular[rank - 1]),
        "effective_ridge": regularizer,
        "design_sha256": digest(x),
        "target_sha256": digest(y),
        "fitted_weight_sha256": digest(fitted),
    }
    return values


def nonunique_example(weight, x, tests, rng):
    _, singular, vt = np.linalg.svd(x, full_matrices=True)
    rank = int(np.linalg.matrix_rank(x))
    if rank >= x.shape[1]:
        return {"available": False, "reason": "No design nullspace."}
    direction = vt[rank]
    output_direction = rng.normal(size=len(weight))
    output_direction /= np.linalg.norm(output_direction)
    perturbation = 0.75 * np.linalg.norm(weight) * np.outer(output_direction, direction)
    hold_x, _ = design(tests, False)
    return {
        "available": True,
        "construction": "W_alternative = W + 0.75*||W||_F*a*v^T; Xv=0, ||a||=||v||=1",
        "training_terminal_change_relative": float(np.linalg.norm(x @ perturbation.T) / max(np.linalg.norm(x @ weight.T), 1e-15)),
        "parameter_change_relative": float(np.linalg.norm(perturbation) / np.linalg.norm(weight)),
        "heldout_terminal_change_relative": float(np.linalg.norm(hold_x @ perturbation.T) / max(np.linalg.norm(hold_x @ weight.T), 1e-15)),
        "alternative_weight_sha256": digest(weight + perturbation),
        "null_vector_sha256": digest(direction),
        "design_rank": rank,
    }


def run_case(size, seed, case_index, horizon, ridge_relative):
    names = ["exact_linear", "measurement_noise", "nonlinear_model_mismatch"]
    case = names[case_index]
    noise = 0.0 if case_index == 0 else 0.02
    mismatch = case_index == 2
    weight = ground_truth(size, seed)
    rng = np.random.default_rng(np.random.SeedSequence([seed, size, case_index, 1]))
    test_rng = np.random.default_rng(np.random.SeedSequence([seed, size, case_index, 999]))
    trajectories = max(2, int(np.ceil(size / horizon)))
    train = [episode(weight, rng, horizon, noise, mismatch) for _ in range(trajectories)]
    matched = [episode(weight, rng, horizon, noise, mismatch) for _ in range(trajectories * horizon)]
    state_only = [episode(weight, rng, horizon, noise, mismatch, drives=train[0]["q"]) for _ in range(trajectories * horizon)]
    tests = [episode(weight, test_rng, horizon, 0.0, mismatch, ood=True) for _ in range(48)]
    arms = [
        ("one_initial_endpoint", train[:1], False),
        ("multiple_initial_endpoints", train, False),
        ("full_intermediate_trajectories", train, True),
        ("matched_observation_budget_endpoints", matched, False),
        ("initial_state_only_no_new_excitation", state_only, False),
    ]
    records = []
    for arm, episodes, trajectory in arms:
        x, y = design(episodes, trajectory)
        record = {"size": size, "seed": seed, "case": case, "arm": arm,
                  "episodes": len(episodes), "state_transitions_collected": len(episodes) * horizon,
                  "vector_observations": len(x), "scalar_observations": len(x) * size,
                  "ground_truth_sha256": digest(weight)}
        record.update(fit_and_measure(x, y, weight, tests, 0.0 if case_index == 0 else ridge_relative))
        records.append(record)
    example = None
    if case_index == 0:
        x, _ = design(train[:1], False)
        example = {"size": size, "seed": seed, **nonunique_example(weight, x, tests, rng)}
    return records, example


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "results/pft1.json")
    parser.add_argument("--seed", type=int, default=731)
    parser.add_argument("--num-seeds", type=int, default=3)
    parser.add_argument("--sizes", default="8,16,32,64")
    parser.add_argument("--horizon", type=int, default=8)
    parser.add_argument("--ridge", type=float, default=0.001)
    args = parser.parse_args()
    sizes = [int(value) for value in args.sizes.split(",")]
    if min(sizes) < 2 or args.num_seeds < 1 or args.horizon < 1 or args.ridge < 0:
        parser.error("Positive sizes/seeds/horizon and nonnegative ridge are required.")
    start = time.perf_counter()
    records, examples = [], []
    for size in sizes:
        for seed in range(args.seed, args.seed + args.num_seeds):
            for case_index in range(3):
                case_records, example = run_case(size, seed, case_index, args.horizon, args.ridge)
                records.extend(case_records)
                if example:
                    examples.append(example)
    summary = []
    for case in sorted({record["case"] for record in records}):
        for arm in sorted({record["arm"] for record in records}):
            group = [record for record in records if record["case"] == case and record["arm"] == arm]
            summary.append({"case": case, "arm": arm, "runs": len(group),
                            **{key + "_mean": float(np.mean([r[key] for r in group])) for key in
                               ["parameter_relative_error", "heldout_terminal_relative_error", "rank_fraction"]}})
    payload = {
        "experiment": "PFT1", "protocol_version": "controlled-linear-identifiability-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(), "numpy": np.__version__,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "configuration": {"sizes": sizes, "seed": args.seed, "num_seeds": args.num_seeds,
                          "horizon": args.horizon, "rho": RHO, "ridge_relative": args.ridge},
        "model": "n response cells: s[t+1]=rho*s[t]+W*q[t]; known external drive q, unknown n*n W. W is nonsingular, so the system is input-controllable; rho<1 makes unforced state stable.",
        "evidence_semantics": "Multiple initial episodes vary both initial response state and the initial/exogenous drive. A separate negative arm varies response state only. Full trajectories contain more observations than the same-episode endpoint arm; matched-observation endpoints disclose that budget explicitly.",
        "heldout_protocol": "48 independent episodes per size/seed/case; larger initial-state variance, Student-t(4) innovations, changed amplitude and temporal correlation. No heldout targets used to fit or tune ridge.",
        "limitations": ["Controlled simulation, not transformer or Hepta runtime integration.",
                        "Known scalar state law; no identification of unknown recurrent dynamics, diffusion or reset.",
                        "Nonlinear mismatch truth uses W*tanh(q), while every estimator assumes W*q.",
                        "Noiseless least-squares equality demonstrates structural identifiability, not general intelligence or training speed.",
                        "Noisy and misspecified negative results are retained in full."],
        "numerical_checks": {"all_nonunique_constructions_match_endpoint": all(e["training_terminal_change_relative"] < 1e-10 for e in examples),
                             "all_nonunique_constructions_change_holdout": all(e["heldout_terminal_change_relative"] > 0.05 for e in examples)},
        "records": records, "nonunique_examples": examples, "summary": summary,
        "elapsed_seconds": time.perf_counter() - start,
    }
    encoded = json.dumps(payload, allow_nan=False, sort_keys=True, separators=(",", ":"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded + "\n")
    print(json.dumps({"output": str(args.output), "records": len(records), "elapsed_seconds": payload["elapsed_seconds"],
                      "checks": payload["numerical_checks"], "summary": summary}, allow_nan=False))


if __name__ == "__main__":
    main()
