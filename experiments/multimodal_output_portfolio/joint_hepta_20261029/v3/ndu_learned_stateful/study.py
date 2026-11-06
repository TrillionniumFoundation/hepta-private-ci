"""Registered simulator study. Truth lives here; model.Policy receives purchased estimates."""
import argparse
import hashlib
import json
from pathlib import Path
from time import perf_counter
from datetime import datetime, timezone
import numpy as np
from .model import ACTIONS, OUTCOMES, METRICS, Kernel, Task, Policy, estimate, evaluate, rollouts, tv_error, tv_radius, value_radius

ROOT = Path(__file__).parent
SOURCES = ("model.py", "study.py", "test_model.py", "protocol.json")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def world_kernel(effect, signal):
    """Evaluator/generator capability only; unrestricted estimator does not know this factorization."""
    p = np.zeros((2, 2, 2, 12))
    for h, z, a in np.ndindex(2, 2, 2):
        theta = .5 + (signal - .5) * (.7 + .3 * z)
        base_z = (.15, .85)[z] if a == 0 else ((.78, .9) if effect == "restoring" else (.12, .45))[z]
        for i, (y, d, nz) in enumerate(OUTCOMES):
            duration_p = .5 if a == 0 else ((.65 if h else .35) if d == 1 else (.35 if h else .65))
            if y == -1:
                yd = .1 * duration_p
            elif a == 0:
                yd = .45 * (theta if ((y == h) == (d == 1)) else 1 - theta)
            else:
                yd = .9 * duration_p * (.55 if y == h else .45)
            pz = base_z + (.04 if h else -.04) + ((.05 if a else -.05) if d == 3 else 0)
            p[h, z, a, i] = yd * (pz if nz else 1 - pz)
    return Kernel(p)


def calibration_bank(kernel, n, seed):
    rng = np.random.default_rng(seed)
    return np.stack([rng.choice(12, n, p=row) for row in kernel.p.reshape(8, 12)]).reshape(2, 2, 2, n).astype(np.uint8)


def acquisition(draws, prices):
    durations = np.array([o[1] for o in OUTCOMES])[draws]
    calls, clock = int(draws.size), int(durations.sum())
    return {"draws": calls, "simulated_clock": clock, "launch_cost": calls * prices["launch"],
            "label_cost": calls * prices["label"], "reset_cost": calls * prices["state_reset"],
            "time_cost": clock * prices["per_simulated_time"],
            "total": calls * (prices["launch"] + prices["label"] + prices["state_reset"]) + clock * prices["per_simulated_time"]}


def freeze():
    lock = ROOT / "freeze.json"
    if lock.exists():
        raise FileExistsError("freeze already exists; do not overwrite a preregistration")
    write_json(lock, {"protocol_id": json.loads((ROOT / "protocol.json").read_text())["id"],
                     "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
                     "source_sha256": {name: digest(ROOT / name) for name in SOURCES}})
    return lock


def run(destination):
    started = perf_counter()
    lock = json.loads((ROOT / "freeze.json").read_text())
    if lock["source_sha256"] != {name: digest(ROOT / name) for name in SOURCES}:
        raise ValueError("frozen source mismatch; preserve pilot and register a new experiment")
    destination.mkdir(parents=True, exist_ok=False)
    protocol = json.loads((ROOT / "protocol.json").read_text())
    (destination / "protocol.json").write_bytes((ROOT / "protocol.json").read_bytes())
    (destination / "freeze.json").write_bytes((ROOT / "freeze.json").read_bytes())
    write_json(destination / "source_snapshot.json", {name: (ROOT / name).read_text() for name in SOURCES})
    prices, config = protocol["calibration_cost"], protocol["deployment"]
    modes, sizes = protocol["policies"], protocol["row_sample_counts"]
    data, banks, laws = {}, {}, []
    full_expense = 0.
    for wi, world in enumerate(protocol["worlds"]):
        truth = world_kernel(world["effect"], world["signal"])
        laws.append(truth)
        for seed in protocol["calibration_seeds"]:
            key = f"w{wi}_s{seed}"
            data[key] = calibration_bank(truth, max(sizes), 100000 * wi + seed)
            full_expense += acquisition(data[key], prices)["total"]
        rng = np.random.default_rng(protocol["confirmation"]["seeds"][wi])
        n = protocol["confirmation"]["episodes_per_world"]
        banks[f"w{wi}_h"] = rng.integers(0, 2, n, dtype=np.int8)
        banks[f"w{wi}_u"] = rng.random((n, config["max_steps"], 2, 2))
    np.savez_compressed(destination / "calibration_raw.npz", **data)
    np.savez_compressed(destination / "confirmation_raw.npz", **banks)
    learning, cases, utilities = [], [], []
    total_confirmation_cost = 0.
    for wi, world in enumerate(protocol["worlds"]):
        truth, hidden, uniforms = laws[wi], banks[f"w{wi}_h"], banks[f"w{wi}_u"]
        for seed in protocol["calibration_seeds"]:
            all_draws = data[f"w{wi}_s{seed}"]
            full_cost = acquisition(all_draws, prices)
            for n in sizes:
                fitted = estimate(all_draws[..., :n], protocol["estimator"]["pseudocount"])
                epsilon = tv_radius(n, protocol["statistics"]["kernel_alpha"], protocol["statistics"]["kernel_family_size"])
                error = tv_error(fitted, truth)
                learning.append({"world": world["name"], "seed": seed, "n_per_row": n,
                                 "max_row_tv": error, "uniform_tv_radius": epsilon,
                                 "bound_event_holds": error <= epsilon, "full_bank_acquisition": full_cost,
                                 "prefix_acquisition_counterfactual": acquisition(all_draws[..., :n], prices),
                                 "estimated_kernel": fitted.p.tolist()})
                for deadline in config["deadlines"]:
                    for fee in config["launch_fees"]:
                        task = Task(deadline, fee, config["time_price"], config["max_steps"])
                        case = {"world": world["name"], "seed": seed, "n_per_row": n, "deadline": deadline, "fee": fee}
                        policy_rows, sample_rows = [], []
                        for mode in modes:
                            policy = Policy(truth if mode == "known_oracle" else fitted, task, mode)
                            exact_true, exact_fit = evaluate(truth, task, policy), evaluate(fitted, task, policy)
                            samples = rollouts(truth, task, policy, hidden, uniforms)
                            sample_rows.append(samples[:, 0])
                            paid = float(np.sum(samples[:, 2] + task.time_price * samples[:, 3])) + len(hidden) * (prices["label"] + prices["state_reset"])
                            total_confirmation_cost += paid
                            policy_rows.append({"policy": mode, "initial_action": list(policy(.5, 0, deadline, task.max_steps)),
                                                "exact_true": dict(zip(METRICS, exact_true.tolist())),
                                                "exact_fitted": dict(zip(METRICS, exact_fit.tolist())),
                                                "confirmation_mean": dict(zip(METRICS, samples.mean(axis=0).tolist())),
                                                "confirmation_acquisition_cost": paid,
                                                "planner_cache_states": policy.solve.cache_info().currsize})
                        matrix = np.stack(sample_rows)
                        utilities.append(matrix)
                        candidate = modes.index("plugin_dp")
                        rows = {row["policy"]: row for row in policy_rows}
                        radius = value_radius(task, epsilon)
                        family = protocol["statistics"]["confirmation_family_size"]
                        alpha = protocol["statistics"]["confirmation_alpha"]
                        paired_radius = task.span * np.sqrt(2 * np.log(family / alpha) / len(hidden))
                        absolute_radius = paired_radius / 2
                        N = protocol["amortization"]["primary_N_deploy"]
                        candidate_K = full_cost["total"] + rows["plugin_dp"]["confirmation_acquisition_cost"]
                        contrasts = []
                        for baseline in ("prior_stop", "myopic", "no_duration", "no_state"):
                            delta = matrix[candidate] - matrix[modes.index(baseline)]
                            baseline_K = 0 if baseline == "prior_stop" else full_cost["total"] + rows[baseline]["confirmation_acquisition_cost"]
                            extra = candidate_K - baseline_K
                            exact_gap = rows["plugin_dp"]["exact_true"]["utility"] - rows[baseline]["exact_true"]["utility"]
                            fitted_gap = rows["plugin_dp"]["exact_fitted"]["utility"] - rows[baseline]["exact_fitted"]["utility"]
                            lower = fitted_gap - 2 * radius
                            contrasts.append({"baseline": baseline, "exact_gap": exact_gap, "fitted_gap": fitted_gap,
                                              "model_certificate_lower": lower, "model_certificate_valid": exact_gap + 1e-10 >= lower,
                                              "paired_mean": float(delta.mean()), "paired_lower": float(delta.mean() - paired_radius),
                                              "incremental_acquisition_cost": extra, "lifecycle_lower_primary": float(delta.mean() - paired_radius - extra / N),
                                              "exact_break_even_deployments": max(0., extra) / exact_gap if exact_gap > 1e-12 else None})
                        exact_regret = rows["known_oracle"]["exact_true"]["utility"] - rows["plugin_dp"]["exact_true"]["utility"]
                        lifecycle = float(matrix[candidate].mean() - absolute_radius - candidate_K / N)
                        case.update({"policies": policy_rows, "contrasts": contrasts,
                                     "value_radius": radius, "oracle_regret": exact_regret, "regret_upper": 2 * radius,
                                     "regret_certificate_valid": exact_regret <= 2 * radius + 1e-10,
                                     "candidate_acquisition_cost": candidate_K, "candidate_absolute_lower_primary": lifecycle,
                                     "candidate_absolute_lower_secondary": float(matrix[candidate].mean() - absolute_radius - candidate_K / protocol["amortization"]["secondary_N_deploy"]),
                                     "positive_net_cell_gate": lifecycle > 0 and all(c["lifecycle_lower_primary"] > 0 for c in contrasts)})
                        cases.append(case)
        print(f"completed world {wi + 1}/{len(laws)}; {len(cases)} registered cells", flush=True)
    np.savez_compressed(destination / "paired_utilities.npz", utilities=np.stack(utilities))
    result = {"protocol_id": protocol["id"], "source_sha256": lock["source_sha256"],
              "truth_access": "generation and evaluation only; known_oracle separately labeled diagnostic",
              "world_kernels_diagnostic": [law.p.tolist() for law in laws], "learning": learning, "cases": cases,
              "cost_audit": {"all_unique_calibration_banks": full_expense, "all_confirmation_policy_executions": total_confirmation_cost,
                             "money_paid_to_real_providers": 0, "currency": "synthetic score units; simulated acquisition ledger, not real paid model data"},
              "hardware_elapsed_seconds": perf_counter() - started,
              "hardware_timing_scope": "entire Python study, data generation, planning, evaluation and serialization; separate from simulated_clock and objective",
              "raw_sha256": {name: digest(destination / name) for name in ("calibration_raw.npz", "confirmation_raw.npz", "paired_utilities.npz")}}
    write_json(destination / "results.json", result)
    write_json(destination / "manifest.json", {"sha256": {p.name: digest(p) for p in destination.iterdir() if p.is_file()},
                                               "cases": len(cases), "learning_banks": len(learning), "all_negative_results_retained": True})
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--output", default="evidence/registered_v1")
    args = parser.parse_args()
    print(freeze() if args.freeze else run(ROOT / args.output)["hardware_elapsed_seconds"])
