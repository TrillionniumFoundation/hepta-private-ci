"""Twelve-window retention study with training/checkpoint freeze before scoring."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from .. import learners, retention, statistics, task
from ..analytic import event_log_probs
from . import adaptation


ARMS = ("frozen", "online", "replay", "fixed_mixture", "likelihood_mixture",
        "protected", "protected_classical", "protected_quantized", "protected_quantized_classical")
SOURCE_PATHS = ("round2/adaptation.py", "round2/retention_study.py", "round2/quantized_guard.py", "analytic.py",
                "learners.py", "task.py", "retention.py", "statistics.py")


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def _load(path):
    with np.load(path, allow_pickle=False) as archive:
        return {key: archive[key].item() if archive[key].ndim == 0 else archive[key]
                for key in archive.files}


def _prefix(data, count):
    n = len(data["ids"])
    return {key: value[:count] if isinstance(value, np.ndarray) and value.ndim and len(value) == n else value
            for key, value in data.items()}


def _registration(registration):
    required = ("phase", "seeds", "windows", "training_rows", "new_replay_rows",
                "original_replay_rows", "old_holdout_rows", "new_holdout_rows", "epsilon",
                "old_nll_margin", "new_nll_improvement_min", "seed_offset")
    if any(key not in registration for key in required):
        raise ValueError("Retention registration is incomplete")
    if (registration["phase"] not in ("development", "confirmation")
            or registration["training_rows"] != registration["new_replay_rows"] + registration["original_replay_rows"]
            or registration["epsilon"] != 0.02 or registration["old_nll_margin"] != 0.02
            or not registration["windows"] or len(set(registration["seeds"])) != len(registration["seeds"])):
        raise ValueError("Invalid phase, matched budget, seed identity or original retention margin")
    return deepcopy(registration)


def prepare_study(destination, registration, anchors_by_seed, original_training_by_seed):
    """Sequentially train checkpoints without constructing or reading any holdout.

    Every arm has access to the same original frozen anchor. Online and routing
    arms use 256 new trajectories; replay uses 128 new plus 128 original rows.
    Routing/guarding reuse the online fit, with their extra prediction costs
    measured later. No model is selected using old/new evaluation outcomes.
    """
    registration = _registration(registration)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    receipts, artifacts = [], {}
    root = Path(__file__).resolve().parent.parent
    source_hashes = {name: _sha(root / name) for name in SOURCE_PATHS}
    started, cpu_started = time.perf_counter_ns(), time.process_time_ns()
    for seed in registration["seeds"]:
        original = original_training_by_seed[seed]
        if original["split"] != "train" or len(original["ids"]) < registration["original_replay_rows"]:
            raise ValueError("Only sufficient original training data may be replayed")
        anchor = deepcopy(anchors_by_seed[seed])
        adaptation._validate_filter(anchor)
        seed_dir = destination / f"seed_{seed}"
        seed_dir.mkdir()
        np.savez_compressed(seed_dir / "ORIGINAL_TRAIN.npz", **original)
        _write(seed_dir / "ANCHOR.json", anchor)
        online, replay = deepcopy(anchor), deepcopy(anchor)
        prior_checkpoint = None
        for window, law in enumerate(registration["windows"]):
            prefix = f"window_{window:02d}"
            train_seed = registration["seed_offset"] + 1000 * seed + window
            training = task.build_dataset(train_seed, registration["training_rows"], "retention_train", law)
            np.savez_compressed(seed_dir / (prefix + "_TRAIN.npz"), **training)
            online, online_receipt = retention._adapt(online, [training])
            replay, replay_receipt = retention._adapt(replay, [
                _prefix(training, registration["new_replay_rows"]),
                _prefix(original, registration["original_replay_rows"])])
            models = {"frozen": deepcopy(anchor), "online": deepcopy(online), "replay": deepcopy(replay),
                      "fixed_mixture": adaptation.make_model(anchor, online, "fixed_mixture", routing="fixed"),
                      "likelihood_mixture": adaptation.make_model(anchor, online, "likelihood_mixture"),
                      "protected": adaptation.make_model(anchor, online, epsilon=registration["epsilon"]),
                      "protected_classical": adaptation.make_model(
                          anchor, online, epsilon=registration["epsilon"], classical=True),
                      "protected_quantized": adaptation.make_model(
                          anchor, online, epsilon=registration["epsilon"], output_quantization="guarded_q24_v1"),
                      "protected_quantized_classical": adaptation.make_model(
                          anchor, online, epsilon=registration["epsilon"], classical=True,
                          output_quantization="guarded_q24_v1")}
            checkpoint = {"seed": seed, "window": window, "training_environment": law,
                          "routing_reads_environment_label": False, "models": models,
                          "previous_checkpoint_sha256": prior_checkpoint,
                          "training_dataset_sha256": task.dataset_digest(training),
                          "training": {"online": online_receipt, "replay": replay_receipt},
                          "holdout_used": False}
            checkpoint_path = seed_dir / (prefix + "_CHECKPOINT.json")
            _write(checkpoint_path, checkpoint)
            # Real filesystem close/read reconstruction, using training histories only.
            loaded = json.loads(checkpoint_path.read_text())
            probe = task.history(_prefix(training, 3))
            reload_errors = {}
            for arm in ARMS:
                before = adaptation.predict(models[arm], probe)
                after = adaptation.predict(loaded["models"][arm], probe)
                error = max(float(np.max(np.abs(a - b))) for a, b in zip(before, after))
                if error != 0:
                    raise AssertionError("Checkpoint reconstruction changed predictions")
                reload_errors[arm] = error
            # The next training window resumes the reconstructed document.
            online, replay = loaded["models"]["online"], loaded["models"]["replay"]
            prior_checkpoint = _sha(checkpoint_path)
            receipts.append({"seed": seed, "window": window, "checkpoint_sha256": prior_checkpoint,
                             "reload_max_absolute_errors": reload_errors,
                             "optimizer_success": {"online": online_receipt["optimizer_success"],
                                                   "replay": replay_receipt["optimizer_success"]}})
    for path in sorted(destination.rglob("*")):
        if path.is_file():
            artifacts[path.relative_to(destination).as_posix()] = _sha(path)
    prepared = {"schema": "hepta.analytic-event.retention-prepared.v2", "registration": registration,
                "source_sha256": source_hashes, "artifacts_sha256": artifacts,
                "checkpoint_receipts": receipts, "holdouts_constructed": False,
                "matched_trajectory_budget": True, "routing_has_hidden_regime": False,
                "preparation_wall_ns": time.perf_counter_ns() - started,
                "preparation_parent_cpu_ns": time.process_time_ns() - cpu_started}
    _write(destination / "PREPARED.json", prepared)
    return {"prepared_sha256": _sha(destination / "PREPARED.json"), **prepared}


def _verify_prepared(destination, registration, freeze_path):
    prepared_path = destination / "PREPARED.json"
    prepared = json.loads(prepared_path.read_text())
    if prepared["registration"] != registration:
        raise ValueError("Registration differs from the prepared study")
    root = Path(__file__).resolve().parent.parent
    for name, digest in prepared["source_sha256"].items():
        if _sha(root / name) != digest:
            raise ValueError("Retention source changed after preparation: " + name)
    for name, digest in prepared["artifacts_sha256"].items():
        if _sha(destination / name) != digest:
            raise ValueError("Retention prepared artifact changed: " + name)
    if registration["phase"] == "confirmation":
        if freeze_path is None:
            raise ValueError("Confirmation requires the parent source/artifact freeze receipt")
        freeze_path = Path(freeze_path)
        freeze = json.loads(freeze_path.read_text())
        run_root = freeze_path.parent.resolve()
        for name in ["PREPARED.json", *prepared["artifacts_sha256"]]:
            path = (destination / name).resolve()
            key = path.relative_to(run_root).as_posix()
            if freeze["artifacts_sha256"].get(key) != _sha(path):
                raise ValueError("Prepared artifact is not bound by the parent freeze: " + key)
        project = root.parent.parent
        for name in prepared["source_sha256"]:
            path = root / name
            key = path.relative_to(project).as_posix()
            if freeze["sources_sha256"].get(key) != _sha(path):
                raise ValueError("Retention source is not bound by the parent freeze: " + key)
    return prepared


def _scores(model, data):
    public = task.history(data)
    mean, variance, diagnostics = adaptation.predict_details(model, public)
    mean, variance, target = mean[:, 1:], variance[:, 1:], task.targets(data)[:, 1:]
    labels = task.event_labels(target)
    logp = event_log_probs(mean, variance, task.LOWER, task.UPPER)
    event = -np.take_along_axis(logp, labels[..., None], -1)[..., 0]
    gaussian = .5 * (np.log(2 * np.pi * variance) + (target - mean) ** 2 / variance)
    probability = np.exp(logp)
    result = {"gaussian_nll": gaussian.mean(1), "event_nll": event.mean(1),
              "mse": ((target - mean) ** 2).mean(1), "mean": mean, "variance": variance,
              "targets": target, "ids": data["ids"], "labels": labels, "probabilities": probability,
              "coverage95": (np.abs(target - mean) <= 1.959963984540054 * np.sqrt(variance)).mean(1),
              "gaussian_nll_by_horizon": gaussian, "event_nll_by_horizon": event}
    if "pointwise_nll_bound" in diagnostics:
        result["bound_by_horizon"] = diagnostics["pointwise_nll_bound"][:, 1:]
        result["correction_by_horizon"] = diagnostics["normalized_correction"][:, 1:]
    if "adaptive_weight" in diagnostics:
        result["adaptive_weight"] = diagnostics["adaptive_weight"]
    for name in ("mean_q24", "variance_q24", "native_typed_domain_mask"):
        if name in diagnostics:
            result[name] = np.asarray(diagnostics[name])[:, 1:]
    if model["kind"] in ("fixed_mixture", "likelihood_mixture"):
        exact, exact_event = adaptation.exact_mixture_log_scores(model, public, task.targets(data))
        result["exact_mixture_nll"] = exact[:, 1:].mean(1)
        result["exact_mixture_event_nll"] = exact_event[:, 1:].mean(1)
    scalars = {name: float(result[name].mean())
               for name in ("gaussian_nll", "event_nll", "mse", "coverage95")}
    scalars["classwise_ece"] = statistics.calibration(probability, labels)["classwise_ece"]
    if model.get("event_probability_quantization") == "anchor_constrained_q24_v1":
        from .quantized_guard import protected_event_quantize
        anchor_mean, anchor_variance = learners.predict(model["anchor"], public)
        anchor_logp = event_log_probs(anchor_mean[:, 1:], anchor_variance[:, 1:], task.LOWER, task.UPPER)
        counts, certificate = protected_event_quantize(anchor_logp, probability, model["epsilon"])
        delivered = counts / (1 << 24)
        delivered_nll = -np.take_along_axis(np.log(delivered), labels[..., None], -1)[..., 0]
        result.update({"q24_event_probability_counts": counts,
                       "q24_minimum_counts": certificate["minimum_counts"],
                       "q24_event_nll_by_horizon": delivered_nll,
                       "q24_event_nll": delivered_nll.mean(1),
                       "q24_event_certificate_max_excess": certificate["maximum_event_nll_excess"],
                       "q24_projection_squared_error": certificate["projection_squared_error"]})
        scalars["q24_event_nll"] = float(delivered_nll.mean())
        scalars["q24_classwise_ece"] = statistics.calibration(delivered, labels)["classwise_ece"]
    return result, scalars


def _interval(differences, replicates=4000, seed=193017):
    """Seeds resampled first; rows separately within each fixed recurring window."""
    differences = np.asarray(differences)
    seeds, windows, trajectories = differences.shape
    rng, values = np.random.default_rng(seed), []
    for start in range(0, replicates, 100):
        count = min(100, replicates - start)
        chosen = rng.integers(seeds, size=(count, seeds, 1, 1))
        rows = rng.integers(trajectories, size=(count, seeds, windows, trajectories))
        win = np.arange(windows)[None, None, :, None]
        values.extend(differences[chosen, win, rows].mean((1, 2, 3)).tolist())
    return {"mean_difference": float(differences.mean()),
            "interval95": np.quantile(values, [.025, .975]).tolist(),
            "per_seed_mean": differences.mean((1, 2)).tolist(), "replicates": replicates,
            "method": "seed bootstrap then trajectory bootstrap inside each fixed window",
            "windows_not_independent_training_replicates": True}


def evaluate_study(destination, registration, freeze_path=None, output=None):
    """Read frozen checkpoints, then generate and score untouched confirmation data."""
    destination = Path(destination)
    registration = _registration(registration)
    prepared = _verify_prepared(destination, registration, freeze_path)
    evaluation = Path(output) if output is not None else destination.parent / (
        "retention_confirmation" if registration["phase"] == "confirmation" else destination.name + "_evaluation")
    if evaluation.resolve() == destination.resolve() or destination.resolve() in evaluation.resolve().parents:
        raise ValueError("Scoring output must be outside the frozen prepared directory")
    evaluation.mkdir(parents=True, exist_ok=False)
    records, shift_differences, final_differences = [], [], []
    quantized_shift_differences, quantized_final_differences = [], []
    max_pointwise, max_event, max_equivalence = -np.inf, -np.inf, 0.0
    quantized_max_pointwise, quantized_max_event, quantized_max_equivalence = -np.inf, -np.inf, 0.0
    quantized_certified_max, quantized_native_valid, quantized_native_total = 0.0, 0, 0
    q24_event_observed_max, q24_event_certified_max = -np.inf, -np.inf
    started, cpu_started = time.perf_counter_ns(), time.process_time_ns()
    for seed in registration["seeds"]:
        seed_dir = destination / f"seed_{seed}"
        anchor = json.loads((seed_dir / "ANCHOR.json").read_text())
        old = task.build_dataset(registration["seed_offset"] + 2000000 + seed,
                                 registration["old_holdout_rows"], "retention_old_" + registration["phase"])
        np.savez_compressed(evaluation / f"seed_{seed}_OLD.npz", **old)
        old_anchor, _ = _scores(anchor, old)
        seed_shift, seed_quantized_shift = [], []
        for window, law in enumerate(registration["windows"]):
            checkpoint_path = seed_dir / f"window_{window:02d}_CHECKPOINT.json"
            checkpoint = json.loads(checkpoint_path.read_text())
            models = checkpoint["models"]
            new = task.build_dataset(registration["seed_offset"] + 3000000 + 1000 * seed + window,
                                     registration["new_holdout_rows"], "retention_new_" + registration["phase"], law)
            prefix = f"seed_{seed}_window_{window:02d}"
            np.savez_compressed(evaluation / (prefix + "_NEW.npz"), **new)
            archive, scores, measured_cost = {}, {}, {}
            pair_results = {}
            for arm in ARMS:
                began, cpu = time.perf_counter_ns(), time.process_time_ns()
                results = {"old": _scores(models[arm], old), "new": _scores(models[arm], new)}
                measured_cost[arm] = {"wall_ns": time.perf_counter_ns() - began,
                                      "parent_cpu_ns": time.process_time_ns() - cpu}
                scores[arm] = {domain: summary for domain, (_, summary) in results.items()}
                scores[arm]["old_nll_degradation_from_initial"] = float(
                    (results["old"][0]["gaussian_nll"] - old_anchor["gaussian_nll"]).mean())
                pair_results[arm] = {domain: arrays for domain, (arrays, _) in results.items()}
                for domain, (arrays, _) in results.items():
                    archive.update({f"{arm}__{domain}__{key}": value for key, value in arrays.items()})
            for domain in ("old", "new"):
                guarded, frozen = pair_results["protected"][domain], pair_results["frozen"][domain]
                max_pointwise = max(max_pointwise, float(np.max(
                    guarded["gaussian_nll_by_horizon"] - frozen["gaussian_nll_by_horizon"])))
                max_event = max(max_event, float(np.max(
                    guarded["event_nll_by_horizon"] - frozen["event_nll_by_horizon"])))
                classical = pair_results["protected_classical"][domain]
                max_equivalence = max(max_equivalence, *(float(np.max(np.abs(guarded[k] - classical[k])))
                                                         for k in ("mean", "variance")))
                quantized = pair_results["protected_quantized"][domain]
                quantized_max_pointwise = max(quantized_max_pointwise, float(np.max(
                    quantized["gaussian_nll_by_horizon"] - frozen["gaussian_nll_by_horizon"])))
                quantized_max_event = max(quantized_max_event, float(np.max(
                    quantized["event_nll_by_horizon"] - frozen["event_nll_by_horizon"])))
                quantized_certified_max = max(quantized_certified_max, float(np.max(quantized["bound_by_horizon"])))
                q24_event_observed_max = max(q24_event_observed_max, float(np.max(
                    quantized["q24_event_nll_by_horizon"] - frozen["event_nll_by_horizon"])))
                q24_event_certified_max = max(q24_event_certified_max, float(np.max(
                    quantized["q24_event_certificate_max_excess"])))
                quantized_classical = pair_results["protected_quantized_classical"][domain]
                quantized_max_equivalence = max(quantized_max_equivalence, *(float(np.max(np.abs(
                    quantized[k] - quantized_classical[k]))) for k in ("mean", "variance")))
                if "native_typed_domain_mask" in quantized:
                    quantized_native_valid += int(quantized["native_typed_domain_mask"].sum())
                    quantized_native_total += int(quantized["native_typed_domain_mask"].size)
            difference = pair_results["protected"]["new"]["gaussian_nll"] - pair_results["frozen"]["new"]["gaussian_nll"]
            quantized_difference = pair_results["protected_quantized"]["new"]["gaussian_nll"] - pair_results["frozen"]["new"]["gaussian_nll"]
            if law == "drift_shift":
                seed_shift.append(difference)
                seed_quantized_shift.append(quantized_difference)
            if window == len(registration["windows"]) - 1:
                final_differences.append(difference)
                quantized_final_differences.append(quantized_difference)
            np.savez_compressed(evaluation / (prefix + "_SCORES.npz"), **archive)
            record = {"seed": seed, "window": window, "law_for_scoring_only": law,
                      "checkpoint_sha256": _sha(checkpoint_path), "scores": scores,
                      "evaluation_cost": measured_cost, "holdouts_fit_or_select_model": False}
            _write(evaluation / (prefix + ".json"), record)
            records.append(record)
        shift_differences.append(seed_shift)
        quantized_shift_differences.append(seed_quantized_shift)
    windows = []
    for window, law in enumerate(registration["windows"]):
        selected = [row for row in records if row["window"] == window]
        arms = {}
        for arm in ARMS:
            arms[arm] = {"old_nll_degradation": float(np.mean([
                row["scores"][arm]["old_nll_degradation_from_initial"] for row in selected]))}
            for domain in ("old", "new"):
                arms[arm][domain] = {key: float(np.mean([row["scores"][arm][domain][key] for row in selected]))
                                     for key in ("gaussian_nll", "event_nll", "mse", "coverage95", "classwise_ece")}
                if arm in ("protected_quantized", "protected_quantized_classical"):
                    arms[arm][domain].update({key: float(np.mean([
                        row["scores"][arm][domain][key] for row in selected]))
                                             for key in ("q24_event_nll", "q24_classwise_ece")})
        windows.append({"window": window, "law": law, "arms": arms})
    worst = max(row["arms"]["protected"]["old_nll_degradation"] for row in windows)
    shift_interval = _interval(shift_differences)
    final_difference = float(np.mean(final_differences))
    original_gate = bool(worst <= registration["old_nll_margin"] and final_difference <= 0)
    efficacy_gate = bool(shift_interval["mean_difference"] <= -registration["new_nll_improvement_min"]
                         and shift_interval["interval95"][1] < 0
                         and all(value < 0 for value in shift_interval["per_seed_mean"]))
    quantized_worst = max(row["arms"]["protected_quantized"]["old_nll_degradation"] for row in windows)
    quantized_interval = _interval(quantized_shift_differences)
    quantized_final = float(np.mean(quantized_final_differences))
    quantized_original_gate = bool(quantized_worst <= registration["old_nll_margin"] and quantized_final <= 0)
    quantized_efficacy_gate = bool(quantized_interval["mean_difference"] <= -registration["new_nll_improvement_min"]
                                   and quantized_interval["interval95"][1] < 0
                                   and all(value < 0 for value in quantized_interval["per_seed_mean"]))
    summary = {"schema": "hepta.analytic-event.retention-results.v2", "registration": registration,
               "prepared_sha256": _sha(destination / "PREPARED.json"), "windows": windows,
               "protected_worst_window_old_nll_degradation": worst,
               "protected_final_new_nll_difference_from_frozen": final_difference,
               "protected_shift_window_nll_contrast": shift_interval,
               "max_observed_pointwise_gaussian_nll_increase": max_pointwise,
               "max_observed_pointwise_event_nll_increase": max_event,
               "pointwise_nll_bound_at_epsilon": .5 * (np.log1p(registration["epsilon"]) + registration["epsilon"]),
               "protected_classical_max_moment_difference": max_equivalence,
               "passes_original_bounded_retention_gate": original_gate,
               "passes_additional_shift_efficacy_gate": efficacy_gate,
               "quantized_protection": {
                   "arm": "protected_quantized", "worst_window_old_nll_degradation": quantized_worst,
                   "final_new_nll_difference_from_frozen": quantized_final,
                   "shift_window_nll_contrast": quantized_interval,
                   "passes_original_bounded_retention_gate": quantized_original_gate,
                   "passes_additional_shift_efficacy_gate": quantized_efficacy_gate,
                   "max_observed_pointwise_gaussian_nll_increase": quantized_max_pointwise,
                   "max_observed_pointwise_event_nll_increase": quantized_max_event,
                   "max_certified_pointwise_nll_bound": quantized_certified_max,
                   "classical_max_moment_difference": quantized_max_equivalence,
                   "native_typed_domain_valid_forecasts": quantized_native_valid,
                   "native_typed_domain_checked_forecasts": quantized_native_total,
                   "pointwise_empirical_envelope_check": bool(
                       quantized_max_pointwise <= registration["epsilon"] + 1e-10
                       and quantized_max_event <= registration["epsilon"] + 1e-10
                       and quantized_certified_max <= registration["epsilon"] + 1e-10),
                   "scope": "Gaussian parameter Q24 lattice; continuous and anchor-corrected integer event logscores are separate",
                   "native_unconstrained_probability_q24_inherits_event_nll_bound": False,
                   "anchor_constrained_event_q24": {
                       "max_observed_event_nll_increase": q24_event_observed_max,
                       "max_certified_event_nll_increase": q24_event_certified_max,
                       "passes_same_event_nll_margin": bool(
                           q24_event_observed_max <= registration["epsilon"] + 1e-10
                           and q24_event_certified_max <= registration["epsilon"] + 1e-10),
                       "gaussian_nll_gate_replaced": False,
                       "raw_counts_saved": True},
                   "native_execution_performed_in_this_study": False},
               "pointwise_empirical_envelope_check": bool(max_pointwise <= registration["epsilon"] + 1e-10
                                                          and max_event <= registration["epsilon"] + 1e-10),
               "trained_optimizations": 2 * len(prepared["checkpoint_receipts"]),
               "real_checkpoint_reload_count": len(prepared["checkpoint_receipts"]),
               "all_optimizers_success": all(all(row["optimizer_success"].values())
                                             for row in prepared["checkpoint_receipts"]),
               "holdout_tuning": False, "hidden_regime_routing": False,
               "population_long_term_guarantee": False,
               "scope": "Twelve sequential parameter updates; bounded state retention, not multiyear semantic memory",
               "gaussian_moment_projection_and_exact_mixture_scores_separate": True,
               "evaluation_wall_ns": time.perf_counter_ns() - started,
               "evaluation_parent_cpu_ns": time.process_time_ns() - cpu_started,
               "cost_scope": "Full scoring, checkpoint readback, raw array persistence; no GPU/energy estimate"}
    _write(evaluation / "RESULTS.json", summary)
    return summary
