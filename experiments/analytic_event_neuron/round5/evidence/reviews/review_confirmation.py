"""Independent read-only numerical review of an already completed selection run.

Run as a module from the repository root, only after root authorizes confirmation
review. Supply trusted freeze, INDEX and RESULTS SHA256s and a new output outside
the run directory. No training, data generation or source/result modification.
"""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from scipy.special import erf, log_ndtr, logsumexp, ndtr, ndtri

from experiments.analytic_event_neuron import task
from experiments.analytic_event_neuron.round4 import calibration as published
from experiments.analytic_event_neuron.round5 import selection_study as study


SOURCE_REVIEW_SHA256 = "ad7a2be7e2a8720a9982f01cf2db806a165e0f2fca165372761b30773ec7e473"
ATOL, RTOL = 2e-10, 2e-10
HORIZONS = np.array([0., .5, 1., 2.])
TARGET_COLUMNS = [1, 2, 4]
LOWER, UPPER = -.6, .6
SECONDARY = (("mixture_full_range", "moment_full_range"),
             ("mixture_full_range", "same_weight_moment_full"),
             ("mixture_full_range", "gaussian_full_range"),
             ("gaussian_full_range", "replay_legacy"))


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def load_arrays(path):
    with np.load(path, allow_pickle=False) as archive:
        return {key: value.item() if value.ndim == 0 else value
                for key in archive.files for value in [archive[key]]}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def compare(actual, expected, name, errors, exact=False):
    a, b = np.asarray(actual), np.asarray(expected)
    require(a.shape == b.shape, name + ": shape differs")
    if exact:
        require(np.array_equal(a, b), name + ": exact values differ")
        return
    finite = np.isfinite(a) & np.isfinite(b)
    require(np.array_equal(a[~finite], b[~finite]), name + ": nonfinite values differ")
    difference = np.abs(a[finite] - b[finite])
    maximum = float(difference.max(initial=0.))
    errors[name] = max(errors.get(name, 0.), maximum)
    require(np.all(difference <= ATOL + RTOL * np.abs(b[finite])),
            name + ": numerical mismatch, maximum absolute error=" + str(maximum))


def compare_tree(actual, expected, name, errors):
    if isinstance(expected, dict):
        require(set(actual) == set(expected), name + ": field roster differs")
        for key in expected:
            compare_tree(actual[key], expected[key], name + "/" + key, errors)
    elif isinstance(expected, (str, bool)) or expected is None:
        require(type(actual) is type(expected) and actual == expected, name + ": value differs")
    else:
        compare(actual, expected, name, errors)


def dense_component(parameters, data):
    """Independent Cholesky conditioning on six public scheduled sensor slots."""
    drift, process_variance, noise_scale = map(float, parameters)
    require(process_variance > 0 and noise_scale > 0, "Positive component noise required")
    means, variances, likelihoods = [], [], []
    for observations, times, mask, noise in zip(data["obs"], data["times"], data["mask"], data["obs_var"]):
        observed_times = times[mask]
        require(len(observed_times) > 0, "Registered queries must have an observed final sensor")
        covariance = 1. + process_variance * np.minimum.outer(observed_times, observed_times)
        covariance += np.diag(noise_scale * noise[mask])
        chol = np.linalg.cholesky(covariance)
        whitened = np.linalg.solve(chol, observations[mask] - drift * observed_times)
        cross = np.linalg.solve(chol, 1. + process_variance * observed_times)
        end_times = times.max() + HORIZONS
        means.append(drift * end_times + cross @ whitened)
        variances.append(1. + process_variance * end_times - cross @ cross)
        likelihoods.append(-.5 * (len(observed_times) * np.log(2 * np.pi)
                                  + 2 * np.log(np.diag(chol)).sum() + whitened @ whitened))
    require(np.all(np.asarray(variances) > 0), "Nonpositive conditional variance")
    return np.asarray(means), np.asarray(variances), np.asarray(likelihoods)


def independent_distribution(model, data, cache):
    require(model["schema"] == published.SCHEMA and model["kind"] == "context_mixture"
            and model["context_count"] == 0 and model["parameter_q24"] is False,
            "Only the registered unquantized zero-context models are supported")
    components = []
    for name in ("anchor", "adaptive"):
        require(model[name]["kind"] == "filter", "Unregistered component family")
        key = tuple(model[name]["parameters"])
        if key not in cache:
            cache[key] = dense_component(key, data)
        components.append(cache[key])
    means = np.stack([part[0] for part in components], axis=-1)
    variances = np.stack([part[1] for part in components], axis=-1)
    prior = float(model["prior"])
    require(0 <= prior <= 1, "Prior outside unit interval")
    with np.errstate(divide="ignore"):
        log_prior = np.log([1. - prior, prior])
    joint = np.stack([part[2] for part in components], axis=-1) + log_prior
    log_weights = joint - logsumexp(joint, axis=-1, keepdims=True)
    weights = np.exp(log_weights)
    if model["projection"]:
        mean = np.sum(weights[:, None, :] * means, axis=-1)
        variance = np.sum(weights[:, None, :] * (variances + (means - mean[..., None]) ** 2), axis=-1)
        means, variances = mean[..., None], variance[..., None]
        weights, log_weights = np.ones((len(mean), 1)), np.zeros((len(mean), 1))
    return {"weights": weights, "log_weights": log_weights, "means": means, "variances": variances}


def event_logs(means, variances):
    """Stable normal event integrals, independent of the published event helper."""
    low, high = (LOWER - means) / np.sqrt(variances), (UPPER - means) / np.sqrt(variances)
    middle = np.empty_like(low)
    for mask, big, small in ((high <= 0, log_ndtr(high), log_ndtr(low)),
                             (low >= 0, log_ndtr(-low), log_ndtr(-high))):
        middle[mask] = big[mask] + np.log(-np.expm1(small[mask] - big[mask]))
    crossing = (low < 0) & (high > 0)
    middle[crossing] = np.log(.5 * (erf(high[crossing] / np.sqrt(2)) - erf(low[crossing] / np.sqrt(2))))
    return np.stack((log_ndtr(low), middle, log_ndtr(-high)), axis=-1)


def quantiles(weights, means, variances):
    values, scales = [], np.sqrt(variances)
    for level in (.025, .975):
        component = means + scales * ndtri(level)
        left, right = component.min(-1), component.max(-1)
        for _ in range(64):
            center = left + (right - left) / 2
            cdf = (weights[:, None, :] * ndtr((center[..., None] - means) / scales)).sum(-1)
            below = cdf < level
            left, right = np.where(below, center, left), np.where(below, right, center)
        values.append(left + (right - left) / 2)
    return np.stack(values, axis=-1)


def ece(probabilities, labels):
    probabilities, labels = probabilities.reshape(-1, 3), labels.reshape(-1)
    total = 0.
    for category in range(3):
        assignments = np.minimum(np.floor(10 * probabilities[:, category]).astype(int), 9)
        for bin_index in range(10):
            selected = assignments == bin_index
            if selected.any():
                total += abs(float((probabilities[selected, category] - (labels[selected] == category)).sum())) / len(labels)
    return total / 3


def independent_scores(distribution, data):
    target = data["future"][:, TARGET_COLUMNS]
    means, variance = distribution["means"][:, 1:], distribution["variances"][:, 1:]
    weights, log_weights = distribution["weights"], distribution["log_weights"][:, None, :]
    logpdf = -.5 * (np.log(2 * np.pi * variance) + (target[..., None] - means) ** 2 / variance)
    density = -logsumexp(log_weights + logpdf, axis=-1)
    logp = logsumexp(log_weights[..., None] + event_logs(means, variance), axis=-2)
    probabilities = np.exp(logp)
    labels = np.where(target <= LOWER, 0, np.where(target > UPPER, 2, 1))
    intervals = quantiles(weights, means, variance)
    mean = (weights[:, None, :] * means).sum(-1)
    scores = {"density_nll_by_horizon": density, "density_nll": density.mean(1),
              "event_nll": -np.take_along_axis(logp, labels[..., None], axis=-1)[..., 0].mean(1),
              "probabilities": probabilities, "labels": labels,
              "coverage95": ((target >= intervals[..., 0]) & (target <= intervals[..., 1])).mean(1),
              "mean": mean, "quantiles95": intervals, "targets": target,
              "mse": ((mean - target) ** 2).mean(1)}
    summary = {key: float(scores[key].mean()) for key in ("density_nll", "event_nll", "coverage95", "mse")}
    summary["classwise_ece"] = ece(probabilities, labels)
    return scores, summary


def private_field_challenge(model, data, original):
    """Every query/model sees changed private values; public histories stay fixed."""
    altered = deepcopy(data)
    for key in ("future", "repair_observation", "wait_observation", "wait_repair_observation", "cost_multiplier"):
        altered[key] = np.full_like(altered[key], -12345.)
    altered.update(ids=np.full(len(data["ids"]), "irrelevant-private-id"), law="unused-private-law",
                   drift=-987., seed=-123, split="private-metadata-challenge", window_index=-999)
    altered["obs"] = np.where(altered["mask"], altered["obs"], 12345.)
    altered["obs_var"] = np.where(altered["mask"], altered["obs_var"], 9876.)
    changed = published.predict_distribution(model, task.history(altered))
    require(set(original) == set(changed), "Prediction field roster changed under private data challenge")
    for key in original:
        require(np.array_equal(original[key], changed[key]), "Private/masked information changed prediction: " + key)


def interval(values, replicates, seed, alpha):
    """Independent paired resampling implementation with the registered RNG order."""
    values = np.asarray(values)
    clusters, windows, queries = values.shape
    rng, bootstrap = np.random.default_rng(seed), []
    for start in range(0, replicates, 100):
        count = min(100, replicates - start)
        chosen_clusters = rng.integers(clusters, size=(count, clusters))
        chosen_queries = rng.integers(queries, size=(count, clusters, windows, queries))
        sampled = np.take_along_axis(values[chosen_clusters], chosen_queries, axis=3)
        bootstrap.extend(sampled.mean(axis=(1, 2, 3)).tolist())
    ordered = np.sort(bootstrap)
    endpoints = []
    for probability in (alpha / 2, 1 - alpha / 2):
        rank = probability * (replicates - 1)
        lower = int(np.floor(rank))
        upper = min(lower + 1, replicates - 1)
        endpoints.append(float(ordered[lower] + (rank - lower) * (ordered[upper] - ordered[lower])))
    return {"mean_difference": float(values.mean()), "interval": endpoints,
            "per_seed_mean": values.mean(axis=(1, 2)).tolist(), "alpha": alpha, "replicates": replicates,
            "method": "resample training seeds then independent whole context/query blocks within each fixed window"}


def independent_summary(scopes, reg):
    arms, comparisons = {}, {}
    seeds, windows = reg["seeds"], reg["windows"]
    for number, arm in enumerate(reg["arms"]):
        old = np.array([[scopes[s, w][arm + "__old__density_nll"] - scopes[s, w]["frozen__old__density_nll"]
                         for w in range(len(windows))] for s in seeds])
        final = np.array([[scopes[s, len(windows) - 1][arm + "__new__density_nll"]
                           - scopes[s, len(windows) - 1]["frozen__new__density_nll"]] for s in seeds])
        shifted = [scopes[s, w] for s in seeds for w, law in enumerate(windows) if law == "drift_shift"]
        calibration = ece(np.concatenate([v[arm + "__new__probabilities"] for v in shifted]),
                          np.concatenate([v[arm + "__new__labels"] for v in shifted]))
        coverage = float(np.concatenate([v[arm + "__new__coverage95"] for v in shifted]).mean())
        ci = interval(final, reg["bootstrap_replicates"], reg["bootstrap_seed"] + number, reg["diagnostic_interval_alpha"])
        retained = bool(old.mean(axis=(0, 2)).max() <= reg["old_nll_margin"] and final.mean() <= 0)
        efficacy = bool(retained and final.mean() <= -reg["final_new_nll_improvement_min"]
                        and all(v < 0 for v in ci["per_seed_mean"]) and ci["interval"][1] < 0)
        calibrated = bool(calibration <= reg["calibration_ece_max"]
                          and reg["coverage95_range"][0] <= coverage <= reg["coverage95_range"][1])
        arms[arm] = {"worst_cross_seed_mean_old_nll_increase": float(old.mean(axis=(0, 2)).max()),
                     "worst_single_seed_window_old_nll_increase": float(old.mean(axis=2).max()),
                     "old_nll_increase_by_window": old.mean(axis=(0, 2)).tolist(),
                     "final_new_nll_difference_descriptive95": ci, "pooled_shifted_classwise_ece": calibration,
                     "pooled_shifted_coverage95": coverage, "passes_retention_gate": retained,
                     "passes_nll_efficacy_gate": efficacy, "passes_calibration_gate": calibrated,
                     "passes_joint_empirical_gate": efficacy and calibrated}
    primary = tuple(map(tuple, reg["primary_comparisons"]))
    for number, (left, right) in enumerate(primary + SECONDARY):
        values = [[scopes[s, w][left + "__new__density_nll"] - scopes[s, w][right + "__new__density_nll"]
                   for w, law in enumerate(windows) if law == "drift_shift"] for s in seeds]
        is_primary = (left, right) in primary
        ci = interval(values, reg["bootstrap_replicates"], reg["bootstrap_seed"] + 100 + number,
                      reg["primary_interval_alpha"] if is_primary else reg["diagnostic_interval_alpha"])
        comparisons[left + "_minus_" + right] = {**ci, "scope": "primary" if is_primary else "descriptive",
            "range_benefit_detected": bool(ci["interval"][1] < 0) if is_primary else None,
            "expanded_joint_gate_passed": arms[left]["passes_joint_empirical_gate"] if is_primary else None}
    return arms, comparisons


def review(args, report):
    run, freeze = args.run_dir.resolve(), args.freeze.resolve()
    index_path, results_path = run / "confirmation/INDEX.json", run / "confirmation/RESULTS.json"
    trusted = {freeze: args.expected_freeze_sha256, index_path: args.expected_index_sha256,
               results_path: args.expected_results_sha256, Path(__file__).with_name("SELECTION_SOURCE_REVIEW.json"): SOURCE_REVIEW_SHA256}
    for path, expected in trusted.items():
        require(sha(path) == expected, "Trusted input hash differs: " + str(path))
    source_review = read(Path(__file__).with_name("SELECTION_SOURCE_REVIEW.json"))
    for path, expected in source_review["source_hashes_sha256"].items():
        require(sha(study.REPO / path) == expected, "Reviewed selection source changed: " + path)
    index, stored = study.verify_confirmation(run, freeze)
    result, reg = read(results_path), index["registration"]
    require(result["registration"] == reg and result["index_sha256"] == sha(index_path)
            and result["freeze_sha256"] == sha(freeze) and result["environment"] == index["environment"],
            "Published results are not bound to the verified confirmation")
    compare(task.HORIZONS, HORIZONS, "registered_horizons", report["maximum_errors"], exact=True)
    require((task.LOWER, task.UPPER) == (LOWER, UPPER), "Registered event thresholds changed")
    regenerated = {}
    for row in index["records"]:
        seed, window = row["seed"], row["window"]
        checkpoint = run / "prepared" / f"seed_{seed}/window_{window:02d}_CHECKPOINT.json"
        models = read(checkpoint)["models"]
        require(set(models) == set(reg["arms"]), "Frozen model arm roster differs")
        recalculated = {}
        for domain, filename in (("old", f"seed_{seed}_OLD.npz"),
                                  ("new", f"seed_{seed}_window_{window:02d}_NEW.npz")):
            data, cache = load_arrays(run / "confirmation" / filename), {}
            for arm in reg["arms"]:
                dist = independent_distribution(models[arm], data, cache)
                ordinary = published.predict_distribution(models[arm], task.history(data))
                for key in dist:
                    compare(ordinary[key], dist[key], "distribution/" + key, report["maximum_errors"])
                private_field_challenge(models[arm], data, ordinary)
                scores, summary = independent_scores(dist, data)
                prefix = arm + "__" + domain + "__"
                for key, expected in scores.items():
                    compare(stored[seed, window][prefix + key], expected, "score/" + key,
                            report["maximum_errors"], exact=key in ("targets", "labels", "coverage95"))
                    recalculated[prefix + key] = expected
                compare_tree(row["summary"][arm][domain], summary, "scope_summary", report["maximum_errors"])
                report["recomputed_model_domain_scopes"] += 1
                report["private_information_challenges"] += 1
                report["recomputed_query_forecasts_including_reused_old_rows"] += len(data["ids"])
        regenerated[seed, window] = recalculated
    arms, comparisons = independent_summary(regenerated, reg)
    compare_tree(result["arms"], arms, "arm_profiles", report["maximum_errors"])
    compare_tree(result["comparisons"], comparisons, "comparisons", report["maximum_errors"])
    for key in ("unique_query_trajectories", "public_context_histories"):
        require(result[key] == index[key], "Result count differs: " + key)
    require(result["production_promotion"] is False and result["original_round4_evidence_reconstructed"] is False,
            "Result exceeded its scientific scope")
    for path, expected in trusted.items():
        require(sha(path) == expected, "Trusted input changed during review: " + str(path))
    study.verify_prepared(run, freeze)
    report.update(unique_query_trajectories=index["unique_query_trajectories"], reviewed_seed_windows=len(regenerated),
                  recomputed_intervals=len(arms) + len(comparisons), primary_family_size=reg["primary_family_size"],
                  environment=index["environment"], reference_comparisons=comparisons,
                  source_review_sha256=SOURCE_REVIEW_SHA256, review_pass=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("run-dir", "freeze", "output"):
        parser.add_argument("--" + option, type=Path, required=True)
    for option in ("expected-freeze-sha256", "expected-index-sha256", "expected-results-sha256"):
        parser.add_argument("--" + option, required=True)
    args = parser.parse_args()
    require(not args.output.resolve().is_relative_to(args.run_dir.resolve()), "Review output must be outside the scientific run")
    require(not args.output.exists(), "A review receipt must not replace an existing file")
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    source_hash = sha(__file__)
    report = {"schema": "hepta.analytic-event.independent-confirmation-review.v5", "review_pass": False,
              "reviewer": "/root/neuron_bridge_scope", "role_attestation_not_cryptographic_signature": True,
              "started_utc": datetime.now(timezone.utc).isoformat(), "reviewer_source_sha256": source_hash,
              "expected_freeze_sha256": args.expected_freeze_sha256, "expected_index_sha256": args.expected_index_sha256,
              "expected_results_sha256": args.expected_results_sha256, "absolute_tolerance": ATOL, "relative_tolerance": RTOL,
              "training_executed": False, "data_generators_called": False, "scientific_artifacts_modified": False,
              "reference_methods": ["dense Cholesky conditioning and public-history likelihood", "independent mixture scoring and quantile inversion",
                                    "whole-query private-field challenges", "independent ECE and hierarchical resampling aggregation"],
              "recomputed_model_domain_scopes": 0, "private_information_challenges": 0,
              "recomputed_query_forecasts_including_reused_old_rows": 0, "maximum_errors": {}}
    try:
        review(args, report)
        require(sha(__file__) == source_hash, "Reviewer source changed during execution")
    except Exception as error:
        report.update(review_pass=False, error_type=type(error).__name__, error=str(error))
    report.update(wall_ns=time.perf_counter_ns() - started, parent_cpu_ns=time.process_time_ns() - cpu,
                  timing_scope="review including verification, dense replay, information challenges and bootstrap; excludes final receipt write")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"review_pass": report["review_pass"], "receipt": str(args.output), "sha256": sha(args.output)}))
    return 0 if report["review_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
