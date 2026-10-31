"""Read-only independent review of completed Round 3 calibration confirmation.

This script never generates datasets, fits models, invokes native, or calls the
scientific prediction or summary functions. Dense Gaussian covariance solves,
mixture moments, losses, calibration bins and resampling are reimplemented here.
"""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from scipy.special import erfc, expit, log_ndtr

from experiments.analytic_event_neuron.round3 import freeze

Q24 = 1 << 24
HORIZONS = np.array([.5, 1., 2.])


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_npz(path):
    with np.load(path, allow_pickle=False) as source:
        return {name: source[name].item() if source[name].ndim == 0 else source[name].copy()
                for name in source.files}


def data_digest(data):
    value = hashlib.sha256()
    for key in sorted(data):
        value.update(key.encode())
        item = data[key]
        value.update(item.tobytes() if isinstance(item, np.ndarray) else str(item).encode())
    return value.hexdigest()


def dense_filter(parameters, data):
    """Condition the joint Brownian Gaussian using no sequential filter code."""
    drift, diffusion, noise = parameters
    means, variances, likelihoods = [], [], []
    for obs, times, seen, sensor in zip(data["obs"], data["times"], data["mask"], data["obs_var"]):
        t, y, r = times[seen], obs[seen], sensor[seen]
        covariance = 1 + diffusion * np.minimum.outer(t, t) + np.diag(noise * r)
        centered, cross = y - drift * t, 1 + diffusion * t
        inverse_products = np.linalg.solve(covariance, np.column_stack([centered, cross]))
        future_time = np.max(times) + HORIZONS
        means.append(drift * future_time + cross @ inverse_products[:, 0])
        variances.append(1 + diffusion * future_time - cross @ inverse_products[:, 1])
        sign, logdet = np.linalg.slogdet(covariance)
        if sign != 1:
            raise AssertionError("Independent covariance reference is not positive definite")
        likelihoods.append(-.5 * (len(t) * np.log(2 * np.pi) + logdet + centered @ inverse_products[:, 0]))
    return np.asarray(means), np.asarray(variances), np.asarray(likelihoods)


def independent_prediction(model, data, cache):
    def filtered(filter_model):
        key = tuple(filter_model["parameters"])
        if key not in cache:
            cache[key] = dense_filter(key, data)
        return cache[key]

    if model["kind"] == "filter":
        return filtered(model)[:2], {}
    m0, v0, ll0 = filtered(model["anchor"])
    m1, v1, ll1 = filtered(model["adaptive"])
    details = {}
    if model["kind"] == "protected_filter":
        prior = model["prior"]
        weight = expit(np.log(prior / (1 - prior)) + ll1 - ll0)[:, None]
        proposal = m0 + weight * (m1 - m0)
        details["adaptive_weight"] = weight[:, 0]
        if model.get("output_quantization") is None:
            delta = np.clip((proposal - m0) / np.sqrt(v0), -model["epsilon"], model["epsilon"])
            return (m0 + np.sqrt(v0) * delta, v0 * (1 + abs(delta))), details
        if model["output_quantization"] != "guarded_q24_v1":
            raise AssertionError("Unknown protected quantization")
        change = np.clip(proposal - m0, -.5 * model["epsilon"] * np.sqrt(v0),
                         .5 * model["epsilon"] * np.sqrt(v0))
        mean = np.rint((m0 + change) * Q24) / Q24
        delta = (mean - m0) / np.sqrt(v0)
        variance = np.maximum(np.ceil(v0 * (1 + abs(delta)) * Q24), np.ceil(v0 * Q24)) / Q24
        return (mean, variance), details
    if model["kind"] != "empirical_calibration":
        raise AssertionError("Unregistered calibration model kind")
    raw = np.asarray(model["parameters"])
    feature = np.clip((ll1 - ll0) / 4, -2, 2)
    weight = expit(raw[0] + raw[1] * feature)[:, None]
    # Independent raw second-moment expression for the candidate Gaussian.
    candidate_mean = (1 - weight) * m0 + weight * m1
    candidate_variance = ((1 - weight) * (v0 + m0 ** 2) + weight * (v1 + m1 ** 2)
                          - candidate_mean ** 2) * np.exp(raw[3:])
    strength, inflation = model["strength"], model["variance_inflation"]
    mean = m0 + strength * (candidate_mean - m0)
    variance = inflation * ((1 - strength) * v0 + strength * candidate_variance
                            + strength * (1 - strength) * (candidate_mean - m0) ** 2)
    if model["output_quantization"] == "q24_parameters_nearest":
        mean = np.rint(mean * Q24) / Q24
        variance = np.maximum(1, np.rint(variance * Q24)) / Q24
    elif model["output_quantization"] is not None:
        raise AssertionError("Unknown empirical quantization")
    return (mean, variance), {"adaptive_weight": weight[:, 0]}


def event_reference(mean, variance):
    """Complementary erfc probabilities and independent stable log differences."""
    lower, upper = (-.6 - mean) / np.sqrt(variance), (.6 - mean) / np.sqrt(variance)
    put, call = .5 * erfc(-lower / np.sqrt(2)), .5 * erfc(upper / np.sqrt(2))
    middle = np.where(lower >= 0, .5 * (erfc(lower / np.sqrt(2)) - erfc(upper / np.sqrt(2))),
                      .5 * (erfc(-upper / np.sqrt(2)) - erfc(-lower / np.sqrt(2))))
    loga = np.where(lower >= 0, log_ndtr(-lower), log_ndtr(upper))
    logb = np.where(lower >= 0, log_ndtr(-upper), log_ndtr(lower))
    logmiddle = loga + np.log(-np.expm1(logb - loga))
    return np.stack([put, middle, call], -1), np.stack([log_ndtr(lower), logmiddle, log_ndtr(-upper)], -1)


def calibration_bins(probability, labels):
    p, y = probability.reshape(-1, 3), labels.reshape(-1)
    bins, errors = [], []
    for event in range(3):
        error = 0.
        for index in range(10):
            selected = (np.minimum(np.floor(p[:, event] * 10).astype(int), 9) == index)
            count = int(selected.sum())
            prediction = float(p[selected, event].mean()) if count else None
            observed = float((y[selected] == event).mean()) if count else None
            if count:
                error += abs(float(np.sum(p[selected, event] - (y[selected] == event)))) / len(p)
            bins.append({"event": event, "bin": index, "count": count,
                         "mean_probability": prediction, "frequency": observed})
        errors.append(error)
    return {"classwise_ece": float(np.mean(errors)), "event_ece": errors, "bins": bins,
            "independent_sample_count": len(labels), "horizon_measurements_per_trajectory": labels.shape[1]}


def bootstrap_reference(differences, replicates, seed):
    """Resample seed clusters, then paired full trajectories inside each window."""
    differences = np.asarray(differences)
    seed_count, windows, trajectories = differences.shape
    rng, values = np.random.default_rng(seed), []
    for first in range(0, replicates, 100):
        count = min(100, replicates - first)
        selected_seeds = rng.integers(seed_count, size=(count, seed_count, 1, 1))
        selected_rows = rng.integers(trajectories, size=(count, seed_count, windows, trajectories))
        seed_samples = differences[selected_seeds.reshape(count, seed_count)]
        paired_samples = np.take_along_axis(seed_samples, selected_rows, axis=3)
        values.extend(paired_samples.mean((1, 2, 3)).tolist())
    return {"mean_difference": float(differences.mean()),
            "interval95": np.quantile(values, [.025, .975]).tolist(),
            "per_seed_mean": differences.mean((1, 2)).tolist(), "replicates": replicates,
            "method": "seed bootstrap then trajectory bootstrap inside each fixed window",
            "windows_not_independent_training_replicates": True}


def gaussian_worst_case(mean0, variance0, mean1, variance1):
    """Complete quadratic supremum, including unbounded narrower distributions."""
    delta = (mean1 - mean0) / np.sqrt(variance0)
    relative = (variance1 - variance0) / variance0
    answer = np.full(delta.shape, np.inf)
    equal = (relative == 0) & (delta == 0)
    answer[equal] = 0
    broad = relative > 0
    answer[broad] = .5 * np.log1p(relative[broad]) + delta[broad] ** 2 / (2 * relative[broad])
    return answer


def review(run_dir, output):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    run_dir, output = Path(run_dir).resolve(), Path(output)
    frozen = freeze.verify(run_dir)
    source_before = dict(frozen["sources_sha256"])
    prepared = run_dir / "calibration_prepared"
    confirmed = run_dir / "calibration_confirmation"
    protocol = json.loads((freeze.PROJECT / "PROTOCOL.json").read_text())
    reg = protocol["calibration"]
    preparation = json.loads((prepared / "PREPARED.json").read_text())
    result = json.loads((confirmed / "RESULTS.json").read_text())
    index = json.loads((confirmed / "INDEX.json").read_text())
    failures, counts, maxima = [], defaultdict(int), defaultdict(float)

    def require(condition, group, message):
        counts[group] += 1
        if not condition:
            failures.append(group + ": " + message)

    def close(actual, expected, group, message, tolerance=3e-10):
        a, b = np.asarray(actual), np.asarray(expected)
        valid = a.shape == b.shape and np.isfinite(a).all() and np.isfinite(b).all()
        error = float(np.max(abs(a - b), initial=0)) if valid else float("inf")
        if np.isfinite(error):
            maxima[group] = max(maxima[group], error)
        require(valid and error <= tolerance, group, message)

    def documents(actual, expected, group, prefix=""):
        if isinstance(expected, dict):
            require(isinstance(actual, dict) and set(actual) == set(expected), group, prefix + " keys")
            if isinstance(actual, dict):
                for key in expected:
                    if key in actual:
                        documents(actual[key], expected[key], group, prefix + "/" + key)
        elif isinstance(expected, (list, tuple)):
            require(isinstance(actual, (list, tuple)) and len(actual) == len(expected), group, prefix + " length")
            if isinstance(actual, (list, tuple)):
                for i, (a, b) in enumerate(zip(actual, expected)):
                    documents(a, b, group, prefix + "/" + str(i))
        elif isinstance(expected, float):
            close(actual, expected, group, prefix)
        else:
            require(actual == expected, group, prefix)

    require(preparation["registration"] == reg == result["registration"], "registration", "Prepared/global/completed registrations")
    require(result["prepared_sha256"] == sha(prepared / "PREPARED.json"), "binding", "Prepared study digest")
    require(result["global_freeze_sha256"] == sha(run_dir / "FREEZE.json"), "binding", "Global freeze digest")
    coordinates = {(seed, window) for seed in reg["seeds"] for window in range(len(reg["windows"]))}
    require(len(index["records"]) == len(index["arrays"]) == len(coordinates), "coverage", "All window records")
    require({(r["seed"], r["window"]) for r in index["records"]} == coordinates, "coverage", "Unique records")
    require({(r["seed"], r["window"]) for r in index["arrays"]} == coordinates, "coverage", "Unique raw arrays")
    records = {(r["seed"], r["window"]): r for r in index["records"]}
    arrays_index = {(r["seed"], r["window"]): r for r in index["arrays"]}
    loaded, metrics = {}, {}
    ids_seen, old_ids_seen = set(), set()
    dense_forecast_rows = 0
    equivalence = {"fp64_max_abs": 0., "q24_max_abs": 0.}
    protected = {name: {"max_observed_excess": -1e99, "max_certified_bound": 0.}
                 for name in ("protected", "protected_q24")}
    empirical_bounds = {name: {"forecast_count": 0, "unbounded_count": 0,
                              "finite_bound_above_002_count": 0, "maximum_finite_bound": 0.}
                        for name in ("calibrated", "calibrated_q24")}
    for seed in reg["seeds"]:
        old = read_npz(confirmed / f"seed_{seed}_OLD.npz")
        old_seed = reg["seed_offset"] + 10000 * seed + 1200 + 5
        require(old["seed"] == old_seed and old["split"] == "calibration_old_confirmation" and old["law"] == "gaussian",
                "data_identity", f"Old {seed}")
        expected_ids = np.array([f"calibration_old_confirmation:gaussian:{old_seed}:{i}" for i in range(reg["old_holdout_rows"])])
        require(np.array_equal(old["ids"], expected_ids), "data_identity", f"Old IDs {seed}")
        require(not old_ids_seen.intersection(old["ids"]), "data_identity", f"Distinct old holdout {seed}")
        old_ids_seen.update(old["ids"])
        for window, law in enumerate(reg["windows"]):
            coordinate = seed, window
            prefix = f"seed_{seed}_window_{window:02d}"
            checkpoint_path = prepared / f"seed_{seed}/window_{window:02d}_CHECKPOINT.json"
            checkpoint = json.loads(checkpoint_path.read_text())
            require(records[coordinate]["checkpoint_sha256"] == sha(checkpoint_path), "binding", prefix + " checkpoint")
            require(json.loads((confirmed / (prefix + ".json")).read_text()) == records[coordinate], "binding", prefix + " row record")
            score_path = (confirmed / arrays_index[coordinate]["path"]).resolve()
            require(score_path.is_relative_to(confirmed), "binding", prefix + " safe score path")
            require(records[coordinate]["scores_sha256"] == sha(score_path), "binding", prefix + " score digest")
            raw = read_npz(score_path)
            loaded[coordinate] = raw
            new = read_npz(confirmed / (prefix + "_NEW.npz"))
            expected_seed = reg["seed_offset"] + 10000 * seed + 100 * window + 4
            require(new["seed"] == expected_seed and new["split"] == "calibration_new_confirmation" and new["law"] == law,
                    "data_identity", prefix + " new")
            require(records[coordinate]["holdout_dataset_digest"] == data_digest(new), "data_identity", prefix + " logical bytes")
            expected_ids = np.array([f"calibration_new_confirmation:{law}:{expected_seed}:{i}" for i in range(reg["new_holdout_rows"])])
            require(np.array_equal(new["ids"], expected_ids), "data_identity", prefix + " new IDs")
            require(not ids_seen.intersection(new["ids"]), "data_identity", prefix + " unique trajectories")
            ids_seen.update(new["ids"])
            metrics[coordinate] = {}
            for domain, data in (("old", old), ("new", new)):
                cache = {}
                target = data["future"][:, [1, 2, 4]]
                labels = np.where(target <= -.6, 0, np.where(target > .6, 2, 1))
                frozen_mean = raw["frozen__" + domain + "__mean"]
                frozen_variance = raw["frozen__" + domain + "__variance"]
                for arm in reg["arms"]:
                    model = checkpoint["models"][arm]
                    (mean, variance), detail = independent_prediction(model, data, cache)
                    key = arm + "__" + domain + "__"
                    actual_mean, actual_variance = raw[key + "mean"], raw[key + "variance"]
                    close(actual_mean, mean, "independent_dense_mean", prefix + "/" + arm + "/" + domain)
                    close(actual_variance, variance, "independent_dense_variance", prefix + "/" + arm + "/" + domain)
                    dense_forecast_rows += len(mean)
                    require(np.array_equal(raw[key + "ids"], data["ids"]), "data_identity", key + " IDs")
                    close(raw[key + "targets"], target, "target", key)
                    require(np.array_equal(raw[key + "labels"], labels), "target", key + " labels")
                    # Recompute losses from the exact delivered/stored Gaussian, after dense reference comparison.
                    gaussian = .5 * (np.log(2 * np.pi * actual_variance) + (target - actual_mean) ** 2 / actual_variance)
                    probability, logp = event_reference(actual_mean, actual_variance)
                    event = -np.take_along_axis(logp, labels[..., None], -1)[..., 0]
                    mse = ((target - actual_mean) ** 2).mean(1)
                    covered = (abs(target - actual_mean) <= 1.959963984540054 * np.sqrt(actual_variance)).mean(1)
                    for name, value in (("gaussian_nll_by_horizon", gaussian), ("gaussian_nll", gaussian.mean(1)),
                                        ("event_nll", event.mean(1)), ("probabilities", probability), ("mse", mse),
                                        ("coverage95", covered)):
                        close(raw[key + name], value, "independent_metric", key + name)
                    if "adaptive_weight" in detail:
                        close(raw[key + "adaptive_weight"], detail["adaptive_weight"], "dense_public_gate", key)
                    summary = {"gaussian_nll": float(gaussian.mean()), "event_nll": float(event.mean()),
                        "mse": float(mse.mean()), "coverage95": float(covered.mean()),
                        "classwise_ece": calibration_bins(probability, labels)["classwise_ece"]}
                    documents(records[coordinate]["scores"][arm][domain], summary, "window_summary", key)
                    metrics[coordinate].setdefault(arm, {})[domain] = summary
                    if key + "mean_q24" in raw:
                        require(np.array_equal(actual_mean * Q24, raw[key + "mean_q24"])
                            and np.array_equal(actual_variance * Q24, raw[key + "variance_q24"]), "q24_grid", key)
                        native_domain = (abs(actual_mean) <= 8) & (actual_variance <= 8) & (actual_variance >= 1 / Q24)
                        require(np.array_equal(raw[key + "native_typed_domain_mask"], native_domain), "q24_grid", key + " native domain")
                    if arm in protected:
                        bound = gaussian_worst_case(frozen_mean, frozen_variance, actual_mean, actual_variance)
                        close(raw[key + "pointwise_nll_bound"], bound, "independent_gaussian_supremum", key)
                        observed = gaussian - raw["frozen__" + domain + "__gaussian_nll_by_horizon"]
                        require(np.all(bound <= .02 + 2e-12) and np.all(observed <= bound + 2e-10), "pointwise_guard", key)
                        protected[arm]["max_observed_excess"] = max(protected[arm]["max_observed_excess"], float(observed.max()))
                        protected[arm]["max_certified_bound"] = max(protected[arm]["max_certified_bound"], float(bound.max()))
                    if arm in empirical_bounds:
                        bound = gaussian_worst_case(frozen_mean, frozen_variance, actual_mean, actual_variance)
                        profile = empirical_bounds[arm]
                        profile["forecast_count"] += bound.size
                        profile["unbounded_count"] += int(np.isinf(bound).sum())
                        profile["finite_bound_above_002_count"] += int(((bound > .02) & np.isfinite(bound)).sum())
                        profile["maximum_finite_bound"] = max(profile["maximum_finite_bound"], float(bound[np.isfinite(bound)].max(initial=0)))
                for suffix, metric in (("", "fp64_max_abs"), ("_q24", "q24_max_abs")):
                    for moment in ("mean", "variance"):
                        a = raw["calibrated" + suffix + "__" + domain + "__" + moment]
                        b = raw["calibrated" + suffix + "_classical__" + domain + "__" + moment]
                        equivalence[metric] = max(equivalence[metric], float(abs(a - b).max()))
            for arm in reg["arms"]:
                old_change = float(np.mean(raw[arm + "__old__gaussian_nll"] - raw["frozen__old__gaussian_nll"]))
                close(records[coordinate]["scores"][arm]["old_nll_degradation_from_initial"], old_change,
                      "old_retention_difference", prefix + "/" + arm)
            print(json.dumps({"review": "calibration_confirmation", "seed": seed, "window": window,
                              "failures": len(failures)}), flush=True)
    shifted = [i for i, law in enumerate(reg["windows"]) if law == "drift_shift"]
    final = len(reg["windows"]) - 1
    for arm in reg["arms"]:
        changes = [float(np.mean([np.mean(loaded[(seed, window)][arm + "__old__gaussian_nll"]
                                                 - loaded[(seed, window)]["frozen__old__gaussian_nll"])
                                      for seed in reg["seeds"]])) for window in range(len(reg["windows"]))]
        differences = np.array([[loaded[(seed, window)][arm + "__new__gaussian_nll"]
                                - loaded[(seed, window)]["frozen__new__gaussian_nll"]
                                for window in shifted] for seed in reg["seeds"]])
        final_difference = np.array([[loaded[(seed, final)][arm + "__new__gaussian_nll"]
                                     - loaded[(seed, final)]["frozen__new__gaussian_nll"]] for seed in reg["seeds"]])
        interval = bootstrap_reference(differences, reg["bootstrap_replicates"], reg["bootstrap_seed"])
        final_interval = bootstrap_reference(final_difference, reg["bootstrap_replicates"], reg["bootstrap_seed"] + 1)
        probabilities = np.concatenate([loaded[(seed, window)][arm + "__new__probabilities"]
                                        for seed in reg["seeds"] for window in shifted])
        labels = np.concatenate([loaded[(seed, window)][arm + "__new__labels"]
                                 for seed in reg["seeds"] for window in shifted])
        calibration = calibration_bins(probabilities, labels)
        coverage = float(np.mean([metrics[(seed, window)][arm]["new"]["coverage95"]
                                  for seed in reg["seeds"] for window in shifted]))
        original = max(changes) <= .02 and final_interval["mean_difference"] <= 0
        efficacy = (original and final_interval["mean_difference"] <= -.005
                    and final_interval["interval95"][1] < 0 and max(final_interval["per_seed_mean"]) < 0)
        calibrated = calibration["classwise_ece"] <= .04 and .92 <= coverage <= .98
        expected = {"old_nll_changes_by_window": changes, "worst_window_old_nll_increase": max(changes),
            "worst_single_seed_window_old_nll_increase": max(float(np.mean(loaded[(seed, window)][arm + "__old__gaussian_nll"]
                - loaded[(seed, window)]["frozen__old__gaussian_nll"])) for seed, window in coordinates),
            "shifted_nll_difference": interval, "final_nll_difference": final_interval,
            "shifted_calibration": calibration, "shifted_coverage95": coverage,
            "passes_original_bounded_retention_gate": bool(original), "passes_new_nll_efficacy_gate": bool(efficacy),
            "passes_descriptive_calibration_gate": bool(calibrated), "passes_joint_empirical_gate": bool(efficacy and calibrated),
            "universal_pointwise_retention_guarantee": arm in ("frozen", "protected", "protected_q24")}
        documents(result["arms"][arm], expected, "all_gates_and_statistics", arm)
    documents(result["equivalence"], equivalence, "equivalence")
    documents(result["protected_profiles"], protected, "pointwise_summary")
    require(result["unique_old_holdout_trajectories"] == len(old_ids_seen) == 1280,
            "sampling_units", "Old trajectories reused, not counted per window")
    require(result["unique_new_holdout_trajectories"] == len(ids_seen) == 15360,
            "sampling_units", "New trajectories distinct across windows")
    require(not ids_seen.intersection(old_ids_seen), "sampling_units", "Old and new holdouts disjoint")
    require(result["native_execution_in_this_study"] is False and result["production_promotion"] is False,
            "scope", "Predictive retention study has no native/production promotion")
    verified = freeze.verify(run_dir)
    require(verified["sources_sha256"] == source_before, "binding", "All global source/prepared bytes reverified after review")
    report = {"schema": "hepta.round3.calibration-independent-confirmation-review.v1", "passed": not failures,
        "checks": dict(counts), "failures": failures, "maximum_absolute_errors": dict(maxima),
        "source_commit": frozen["source_commit"], "global_freeze_sha256": sha(run_dir / "FREEZE.json"),
        "results_sha256": sha(confirmed / "RESULTS.json"), "index_sha256": sha(confirmed / "INDEX.json"),
        "review_script_sha256": sha(__file__), "global_frozen_sources_verified": len(frozen["sources_sha256"]),
        "global_prepared_artifacts_verified": len(frozen["artifacts_sha256"]),
        "full_model_domain_trajectory_predictions_independently_recomputed": dense_forecast_rows,
        "dependent_horizon_measurements_independently_recomputed": dense_forecast_rows * 3,
        "unique_old_trajectories": len(old_ids_seen), "unique_new_trajectories": len(ids_seen),
        "independent_dense_gaussian_gate_and_moments": True, "all_losses_calibration_coverage_and_gates_recomputed": True,
        "twenty_paired_seed_trajectory_bootstraps_recomputed": True, "actual_model_refit_or_dataset_generation": False,
        "native_executed": False, "empirical_profiles_gaussian_worst_cases": empirical_bounds,
        "empirical_worst_case_results_are_secondary_math_diagnostics_not_redefined_gates": True,
        "label_budget_scope": "512 fitting labels matched for replay/calibration; calibration additionally selects on256dev labels, replaydoesnot; classical calibration shares identical selection",
        "wall_ns": time.perf_counter_ns() - started, "parent_cpu_ns": time.process_time_ns() - cpu}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"passed": report["passed"], "checks": sum(counts.values()), "failures": failures[:10],
                      "maximum_absolute_errors": dict(maxima), "report_sha256": sha(output)}))
    if failures:
        raise SystemExit(1)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    review(arguments.run_dir, arguments.output)
