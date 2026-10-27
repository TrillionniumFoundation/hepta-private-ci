"""Independent development-trajectory gate. This module never fits a predictor.

The supplied records enumerate all four permitted branches of each development
optimizer snapshot. The original complete state and future minibatch schedule
must be identical within a record. Predictions use only frozen fitting data.
Audit outcomes and prediction arrays are inspected here after collection.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

SCHEMA = "hepta.field-bridge.v2.trajectory-gate.v1"
SEEDS = (17, 29, 43)
MODES = ("field", "generic", "richer")
ACTION_COUNT = 4
TRAJECTORY_COUNTS = {"fit": 8, "audit": 8}
BOOTSTRAPS = 4000
BOOTSTRAP_SEED = 271028


def canonical_digest(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def fitting_rows_digest(records):
    ignored = {"predictions", "prediction_controller_sha256"}
    fit = [{k: v for k, v in row.items() if k not in ignored}
           for row in records if row["partition"] == "fit"]
    fit.sort(key=lambda row: (row["seed"], row["trajectory"], row["step"]))
    return canonical_digest(fit)


def _hash(value, name):
    if (not isinstance(value, str) or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)):
        raise ValueError(f"Invalid SHA-256 for {name}")
    return value


def _vector(value, name):
    a = np.asarray(value, dtype=float)
    if a.shape != (ACTION_COUNT,) or not np.isfinite(a).all():
        raise ValueError(f"{name} must contain four finite numbers")
    return a


def validate(records, freeze):
    if not isinstance(records, list) or not records:
        raise ValueError("Complete fitting and audit records are required")
    expected_steps = freeze.get("decision_steps")
    if (not isinstance(expected_steps, list) or not expected_steps
            or any(type(step) is not int or step < 0 for step in expected_steps)
            or expected_steps != sorted(set(expected_steps))):
        raise ValueError("Freeze must list the complete sorted decision_steps grid")
    seen, by_seed, trajectory_parts = set(), {}, {}
    for row in records:
        seed, trajectory, step = (row[k] for k in ("seed", "trajectory", "step"))
        partition = row["partition"]
        if (type(seed) is not int or seed not in SEEDS or type(trajectory) is not int
                or trajectory < 0 or type(step) is not int or step < 0
                or partition not in TRAJECTORY_COUNTS):
            raise ValueError("Invalid seed, trajectory, step or partition")
        identity = (seed, trajectory, step)
        if identity in seen:
            raise ValueError("Repeated optimizer snapshot")
        seen.add(identity)
        key = (seed, trajectory)
        if key in trajectory_parts and trajectory_parts[key] != partition:
            raise ValueError("One trajectory appears in both fit and audit")
        trajectory_parts[key] = partition
        for name in ("state_sha256", "optimizer_sha256", "schedule_sha256"):
            _hash(row[name], name)
        if not np.isfinite(float(row["current_value"])):
            raise ValueError("Current hard value is nonfinite")
        values = _vector(row["action_values"], "action values")
        if abs(float(values[0]) - float(row["current_value"])) > 1e-12:
            raise ValueError("No-update branch changed the fixed-panel hard value")
        if partition == "audit":
            for mode in MODES:
                _vector(row["predictions"][mode], f"{mode} predictions")
                expected = freeze["controller_sha256"][str(seed)][mode]
                _hash(expected, "frozen controller")
                if row["prediction_controller_sha256"][mode] != expected:
                    raise ValueError("Audit predictions name a different controller")
        by_seed.setdefault(seed, {"fit": [], "audit": []})[partition].append(row)
    if set(by_seed) != set(SEEDS):
        raise ValueError("All three original model seeds must be present")
    for seed, partitions in by_seed.items():
        for partition, rows in partitions.items():
            trajectories = sorted({row["trajectory"] for row in rows})
            if len(trajectories) != TRAJECTORY_COUNTS[partition]:
                raise ValueError(f"Seed {seed} needs eight {partition} trajectories")
            steps = [{row["step"] for row in rows if row["trajectory"] == trajectory}
                     for trajectory in trajectories]
            if any(part != set(expected_steps) for part in steps):
                raise ValueError("Trajectories have incomplete or unequal decision grids")
    actual = fitting_rows_digest(records)
    if freeze.get("fit_rows_sha256") != actual:
        raise ValueError("Fitting records differ from the pre-audit freeze")
    return by_seed


def _cluster_interval(values, rng):
    """Equal fixed-seed weight; resample complete trajectories within each seed."""
    estimates = np.zeros(BOOTSTRAPS)
    for seed in SEEDS:
        cluster = np.asarray(values[seed], dtype=float)
        if cluster.shape != (TRAJECTORY_COUNTS["audit"],):
            raise ValueError("Bootstrap unit must be each of eight complete trajectories")
        indices = rng.integers(len(cluster), size=(BOOTSTRAPS, len(cluster)))
        estimates += cluster[indices].mean(axis=1) / len(SEEDS)
    return [float(x) for x in np.quantile(estimates, [.025, .975])]


def audit(records, freeze):
    grouped = validate(records, freeze)
    by_seed, cluster_improvements, cluster_skill = {}, {}, {}
    sums = {mode: {"mse": [], "regret": [], "value": []} for mode in MODES}
    baseline_mses = {name: [] for name in ("no_change", "global_mean_delta", "action_mean_delta")}
    fixed_regrets, improvements = [], []
    for seed, partitions in sorted(grouped.items()):
        fit = sorted(partitions["fit"], key=lambda row: (row["trajectory"], row["step"]))
        held = sorted(partitions["audit"], key=lambda row: (row["trajectory"], row["step"]))
        fit_delta = np.asarray([row["action_values"] for row in fit]) - np.asarray(
            [row["current_value"] for row in fit])[:, None]
        fixed_action = int(np.argmax(fit_delta.mean(axis=0)))
        values = np.asarray([row["action_values"] for row in held])
        current = np.asarray([row["current_value"] for row in held])
        delta = values - current[:, None]
        spread, oracle = np.ptp(values, axis=1), values.max(axis=1)
        fixed_value = values[:, fixed_action]
        baseline_errors = {
            "no_change": delta ** 2,
            "global_mean_delta": (delta - fit_delta.mean()) ** 2,
            "action_mean_delta": (delta - fit_delta.mean(axis=0)) ** 2,
        }
        base = {name: float(err.mean()) for name, err in baseline_errors.items()}
        for name, mse in base.items():
            baseline_mses[name].append(mse)
        candidate = {}
        field_value, field_error = None, None
        for mode in MODES:
            pred = np.asarray([row["predictions"][mode] for row in held])
            error = (pred - values) ** 2
            actions = np.argmax(pred, axis=1)
            value = values[np.arange(len(values)), actions]
            regret = oracle - value
            metrics = {"mse": float(error.mean()), "rmse": float(np.sqrt(error.mean())),
                       "mean_value": float(value.mean()), "mean_regret": float(regret.mean()),
                       "action_counts": np.bincount(actions, minlength=ACTION_COUNT).tolist(),
                       "improvement_over_fit_selected_fixed": float((value - fixed_value).mean())}
            candidate[mode] = metrics
            sums[mode]["mse"].append(metrics["mse"])
            sums[mode]["regret"].append(metrics["mean_regret"])
            sums[mode]["value"].append(metrics["mean_value"])
            if mode == "field":
                field_value, field_error = value, error
        fixed_regret = float((oracle - fixed_value).mean())
        fixed_regrets.append(fixed_regret)
        improvement = field_value - fixed_value
        improvements.append(float(improvement.mean()))
        trajectories = np.asarray([row["trajectory"] for row in held])
        ids = sorted(set(trajectories.tolist()))
        cluster_improvements[seed] = [float(improvement[trajectories == t].mean()) for t in ids]
        cluster_skill[seed] = {
            name: [float((err - field_error)[trajectories == t].mean()) for t in ids]
            for name, err in baseline_errors.items()
        }
        by_seed[str(seed)] = {
            "fit_rows": len(fit), "audit_rows": len(held), "audit_trajectory_ids": ids,
            "fit_selected_fixed_action": fixed_action,
            "mean_action_spread": float(spread.mean()),
            "fraction_action_spread_at_least_0_001": float((spread >= .001).mean()),
            "max_action_spread": float(spread.max()),
            "oracle_mean_value": float(oracle.mean()), "fixed_mean_value": float(fixed_value.mean()),
            "fixed_mean_regret": fixed_regret, "baselines_mse": base, "candidates": candidate,
            "field_no_worse_than_best_baseline": candidate["field"]["mse"] <= min(base.values()),
        }
    pooled = {mode: {key: float(np.mean(value)) for key, value in result.items()}
              for mode, result in sums.items()}
    baselines = {key: float(np.mean(value)) for key, value in baseline_mses.items()}
    interval = _cluster_interval(cluster_improvements, np.random.default_rng(BOOTSTRAP_SEED))
    skill_intervals = {name: _cluster_interval(
        {seed: cluster_skill[seed][name] for seed in SEEDS},
        np.random.default_rng(BOOTSTRAP_SEED + index + 1))
        for index, name in enumerate(baselines)}
    fixed_regret = float(np.mean(fixed_regrets))
    improvement = float(np.mean(improvements))
    gates = {
        "audit_response": all(r["mean_action_spread"] >= .001 and
                              r["fraction_action_spread_at_least_0_001"] >= .25
                              for r in by_seed.values()),
        "field_prediction_skill": (pooled["field"]["mse"] <= .9 * min(baselines.values())
                                   and all(r["field_no_worse_than_best_baseline"] for r in by_seed.values())),
        "field_decision_skill": (pooled["field"]["regret"] <= .8 * fixed_regret
                                 and improvement >= .001 and interval[0] > 0),
    }
    return {"schema": SCHEMA, "fit_rows_sha256": fitting_rows_digest(records),
            "freeze_sha256": canonical_digest(freeze), "record_count": len(records),
            "by_seed": by_seed, "pooled_equal_seed": pooled,
            "baseline_mses_equal_seed": baselines, "fixed_mean_regret": fixed_regret,
            "field_mean_improvement": improvement, "improvement_ci95": interval,
            "baseline_minus_field_mse_ci95": skill_intervals,
            "gates": gates, "all_development_audit_gates_pass": all(gates.values()),
            "uncertainty": {"unit": "complete optimizer trajectory within fixed model seed",
                "bootstraps": BOOTSTRAPS, "seed": BOOTSTRAP_SEED,
                "interval": "paired stratified trajectory bootstrap; descriptive 95%; no model-population inference"},
            "scope": "Development audit only. Hashes verify consistency with supplied freeze; execution chronology requires separately committed receipts. No test/retention or theorem acceptance is inferred."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bank", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    bank = json.loads(args.bank.read_text())
    records = bank["records"] if isinstance(bank, dict) else bank
    result = audit(records, json.loads(args.freeze.read_text()))
    result["input_files"] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in (args.bank, args.freeze)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x") as file:
        json.dump(result, file, indent=2, sort_keys=True, allow_nan=False)
        file.write("\n")
    print(json.dumps({"gates": result["gates"], "out": str(args.out)}, sort_keys=True))


if __name__ == "__main__":
    main()
