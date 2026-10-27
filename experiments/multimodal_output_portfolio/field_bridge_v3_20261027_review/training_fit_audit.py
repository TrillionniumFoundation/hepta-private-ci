"""Independent reconstruction of every V3 trajectory-CV and full-fit terminal head."""

import argparse
import json
from pathlib import Path
import time

import numpy as np

from .training_audit_common import SCIENCE, bound, check_close, digest, inventory, read, require


MODES = ("field", "generic", "richer", "h7")


def independent_head(raw, targets, mode, alpha, projection_seed):
    """Use augmented least squares, independent of the fitted normal-equation solve."""
    raw_center = np.mean(raw, axis=0)
    raw_scale = np.maximum(np.std(raw, axis=0, ddof=0), 1e-6)
    if mode == "generic":
        matrix = np.random.default_rng(projection_seed).normal(size=(30, 12))
        projection = np.linalg.qr(matrix)[0]
    else:
        dimension = {"field": 12, "richer": 30, "h7": 7}[mode]
        projection = np.eye(30)[:, :dimension]
    projected = ((raw - raw_center) / raw_scale) @ projection
    projected_center = projected.mean(axis=0)
    projected_scale = np.maximum(projected.std(axis=0, ddof=0), 1e-6)
    z = (projected - projected_center) / projected_scale
    design = np.c_[np.ones(len(raw)), z]
    penalty = np.sqrt(alpha) * np.eye(design.shape[1])
    penalty[0, 0] = 0.
    coefficients = np.linalg.lstsq(np.vstack((design, penalty)),
                                  np.vstack((targets, np.zeros((design.shape[1], 4)))), rcond=None)[0]
    return {"raw_mean": raw_center, "raw_scale": raw_scale, "projection": projection,
            "projected_mean": projected_center, "projected_scale": projected_scale, "coefficients": coefficients}


def independently_predict(head, raw):
    z = ((raw - head["raw_mean"]) / head["raw_scale"]) @ np.asarray(head["projection"])
    z = (z - head["projected_mean"]) / head["projected_scale"]
    return np.c_[np.ones(len(raw)), z] @ np.asarray(head["coefficients"])


def check_head(head, raw, targets, mode, alpha, p, names):
    dimension = {"field": 12, "generic": 12, "richer": 30, "h7": 7}[mode]
    require(head["schema"] == "hepta.field-bridge.v3.terminal-head.1" and head["mode"] == mode
            and head["ridge"] == alpha and head["dimension"] == dimension and head["fit_rows"] == len(raw)
            and head["coefficient_count"] == (dimension + 1) * 4 and head["feature_names"] == names
            and head["prediction_clipping"] is False, "Head identity, dimension, capacity, or clipping changed")
    expected = independent_head(raw, targets, mode, alpha, p["generic_projection_seed"])
    maximum = 0.
    for key, value in expected.items():
        actual = np.asarray(head[key])
        require(actual.shape == value.shape and np.isfinite(actual).all(), f"Head tensor shape/value differs: {key}")
        check_close(actual, value, f"Independent head reconstruction differs: {key}", atol=1e-8, rtol=1e-8)
        maximum = max(maximum, float(np.max(np.abs(actual - value))))
    return maximum


def audit_fit(run, seed, freeze_path, source=SCIENCE):
    root, directory = Path(run), Path(run) / "fit" / str(seed)
    protocol = read(Path(source) / "PROTOCOL.json")
    p = protocol["training"]
    complete, start, freeze = inventory(directory, freeze_path, "fit", seed, source)
    require(start["requested_roles"] == [], "Head fitting loaded new source roles")
    bank_path, controller_path = root / "bank" / str(seed) / "BANK.json", directory / "CONTROLLERS.json"
    bank, fitted = read(bank_path), read(controller_path)
    require(fitted["seed"] == seed and fitted["bank_sha256"] == digest(bank_path)
            and fitted["reference_sha256"] == bank["reference_sha256"]
            and fitted["training_configuration_sha256"] == bank["training_configuration_sha256"] == bound(p),
            "Controller fitting inputs/configuration changed")
    require(fitted["development_or_audit_rows_used"] == 0, "Head selection used held-out rows")
    rows = bank["records"]
    raw = np.asarray([row["state"] for row in rows], dtype=float)
    targets = np.asarray([row["action_values"] for row in rows], dtype=float)
    groups = np.asarray([row["trajectory"] for row in rows])
    require(raw.shape == (24, 30) and targets.shape == (24, 4)
            and [(row["trajectory"], row["step"]) for row in rows] == [(i, t) for i in range(4) for t in range(0, 288, 48)],
            "Terminal fitting bank grid differs")
    names, maximum, checked, results = bank["feature_names"], 0., 0, {}
    require(set(fitted["controllers"]) == set(fitted["all_candidates"]) == set(MODES), "Controller family omitted or expanded")
    for mode in MODES:
        choices = fitted["all_candidates"][mode]["candidates"]
        require([choice["ridge"] for choice in choices] == p["ridges"], "Ridge family expanded or reordered")
        losses = []
        for alpha, choice in zip(p["ridges"], choices, strict=True):
            residuals = []
            require([fold["held_out_trajectory"] for fold in choice["folds"]] == [0, 1, 2, 3], "Trajectory-CV folds changed")
            for fold in choice["folds"]:
                held_out = fold["held_out_trajectory"]
                train, validation = groups != held_out, groups == held_out
                require(fold["training_trajectories"] == [index for index in range(4) if index != held_out],
                        "A whole held-out trajectory entered fitting")
                maximum = max(maximum, check_head(fold["head"], raw[train], targets[train], mode, alpha, p, names))
                checked += 1
                predictions = independently_predict(fold["head"], raw[validation])
                check_close(predictions, fold["predictions"], "Fold held-out predictions differ")
                error = predictions - targets[validation]
                check_close(float(np.square(error).mean()), fold["mse"], "Fold error arithmetic differs")
                residuals.extend(error.ravel().tolist())
            loss = float(np.mean(np.square(residuals)))
            check_close(loss, choice["cv_mse"], "Pooled trajectory-CV error differs")
            losses.append(loss)
            maximum = max(maximum, check_head(choice["full_fit_head"], raw, targets, mode, alpha, p, names))
            checked += 1
        winner = min(range(3), key=lambda index: (losses[index], index))
        require(fitted["all_candidates"][mode]["selected_index"] == winner
                and fitted["controllers"][mode] == choices[winner]["full_fit_head"], "Selected full-fit head differs from the grouped-CV winner")
        results[mode] = {"selected_index": winner, "ridge": p["ridges"][winner], "cv_mse": losses}
    expected_cost = {"fold_head_fits": 48, "full_fit_candidate_heads": 12, "linear_system_solves": 60,
                     "terminal_target_values_available": 96, "shared_branch_bank_counted_here": 0}
    require(fitted["resources"] == complete["resources"] == expected_cost, "Fitting/search cost accounting differs")
    return {"schema": "hepta.field-bridge.v3.independent-training-fit-audit.1", "passed": True, "seed": seed,
            "complete_sha256": digest(directory / "COMPLETE.json"), "bank_sha256": digest(bank_path),
            "controller_file_sha256": digest(controller_path), "all_heads_checked": checked,
            "maximum_head_tensor_error": maximum, "selections": results, "verification_least_squares_solves": checked,
            "verification_gradient_microsteps": 0, "actual_source_roles_loaded": [],
            "fit_only_whole_trajectory_normalization_verified": True, "verification_used_to_refit_controllers": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--seed", type=int, choices=(17, 29, 43), required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=SCIENCE)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    require(not args.out.exists() and not args.out.resolve().is_relative_to((args.run / "fit" / str(args.seed)).resolve()),
            "Audit report must be new and outside the fit stage")
    started = time.perf_counter_ns()
    result = audit_fit(args.run, args.seed, args.freeze, args.source)
    result.update(script_sha256=digest(__file__), helpers_sha256=digest(Path(__file__).with_name("training_audit_common.py")),
                  verification_wall_ns=time.perf_counter_ns() - started)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
