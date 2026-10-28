"""Frozen multiwindow calibration and empirical retention confirmation study."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from .. import learners, retention, statistics, task
from ..analytic import event_log_probs
from ..round2 import adaptation
from ..round2.retention_study import _interval
from . import calibration


ARMS = ("frozen", "online", "replay", "protected", "protected_q24", "calibrated",
        "calibrated_classical", "calibrated_q24", "calibrated_q24_classical",
        "calibrated_unconstrained")
SOURCE_PATHS = ("round3/calibration.py", "round3/calibration_study.py", "round2/adaptation.py",
                "round2/quantized_guard.py", "round2/retention_study.py", "analytic.py",
                "learners.py", "task.py", "retention.py", "statistics.py")


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def _prefix(data, count):
    n = len(data["ids"])
    return {key: value[:count] if isinstance(value, np.ndarray) and value.ndim and len(value) == n else value
            for key, value in data.items()}


def registration():
    return {"phase": "confirmation", "seeds": [607, 701, 809, 907, 1009],
            "windows": ["gaussian", "drift_shift"] * 6, "training_rows": 256,
            "development_rows": 128, "old_holdout_rows": 256, "new_holdout_rows": 256,
            "seed_offset": 50000000, "epsilon": .02, "old_nll_margin": .02,
            "new_nll_improvement_min": .005, "calibration_ece_max": .04,
            "calibration_coverage_min": .92, "calibration_coverage_max": .98,
            "bootstrap_replicates": 4000, "bootstrap_seed": 20261028,
            "seed_rule": "offset+10000*seed+100*window+code; train1,olddev2,newdev3,newholdout4; oldholdout window12/code5",
            "selector": "55 candidates; old-dev mean NLL change+1.645 paired SE<=.02; min new-dev Gaussian NLL",
            "arms": list(ARMS), "empirical_profile_pointwise_guarantee": False,
            "same_available_information": True,
            "replay_and_calibration_labelled_rows_equal": True,
            "online_labelled_rows_per_window": 256,
            "replay_and_calibration_labelled_rows_per_window": 512,
            "prediction_receives_hidden_regime_or_window": False}


def _registered(value):
    value = deepcopy(value)
    required = set(registration())
    if not required.issubset(value):
        raise ValueError("Incomplete calibration registration")
    if (value["epsilon"] != .02 or value["old_nll_margin"] != .02
            or value["arms"] != list(ARMS) or not 0 < len(value["windows"]) <= 12
            or value["phase"] not in ("development", "confirmation")
            or not value["seeds"] or len(value["seeds"]) != len(set(value["seeds"]))
            or any(value[name] < 2 for name in ("training_rows", "development_rows", "old_holdout_rows", "new_holdout_rows"))
            or value["prediction_receives_hidden_regime_or_window"]
            or value["empirical_profile_pointwise_guarantee"]):
        raise ValueError("Invalid margin, partition, arm or guarantee contract")
    return value


def data_seed(reg, seed, window, code):
    if not 0 <= window <= 12 or code not in (1, 2, 3, 4, 5):
        raise ValueError("Unknown calibration dataset coordinate")
    return reg["seed_offset"] + 10000 * seed + 100 * window + code


def prepare_study(destination, registration, anchors_by_seed, original_training_by_seed):
    """Fit all checkpoints using train/dev only, before any holdout is generated."""
    reg = _registered(registration)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    source_root = Path(__file__).resolve().parent.parent
    source_hashes = {name: _sha(source_root / name) for name in SOURCE_PATHS}
    receipts = []
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    for seed in reg["seeds"]:
        original = original_training_by_seed[seed]
        if original["split"] != "train" or len(original["ids"]) < reg["training_rows"]:
            raise ValueError("Sufficient original training trajectories are required")
        old_training = _prefix(original, reg["training_rows"])
        anchor = deepcopy(anchors_by_seed[seed])
        adaptation._validate_filter(anchor)
        seed_dir = destination / f"seed_{seed}"
        seed_dir.mkdir()
        np.savez_compressed(seed_dir / "ORIGINAL_TRAIN.npz", **old_training)
        _write(seed_dir / "ANCHOR.json", anchor)
        online, replay, previous = deepcopy(anchor), deepcopy(anchor), None
        for window, law in enumerate(reg["windows"]):
            prefix = f"window_{window:02d}"
            training = task.build_dataset(data_seed(reg, seed, window, 1), reg["training_rows"], "retention_train", law)
            old_dev = task.build_dataset(data_seed(reg, seed, window, 2), reg["development_rows"],
                                         "calibration_development", "gaussian")
            new_dev = task.build_dataset(data_seed(reg, seed, window, 3), reg["development_rows"],
                                         "calibration_development", law)
            for name, data in (("TRAIN", training), ("OLD_DEV", old_dev), ("NEW_DEV", new_dev)):
                np.savez_compressed(seed_dir / (prefix + "_" + name + ".npz"), **data)
            online, online_fit = retention._adapt(online, [training])
            replay, replay_fit = retention._adapt(replay, [old_training, training])
            candidate, calibration_fit = calibration.fit_model(anchor, online, [old_training, training])
            selected, selection = calibration.select_model(candidate, old_dev, new_dev, reg["old_nll_margin"])
            models = {"frozen": deepcopy(anchor), "online": deepcopy(online), "replay": deepcopy(replay),
                "protected": adaptation.make_model(anchor, online, epsilon=reg["epsilon"]),
                "protected_q24": adaptation.make_model(anchor, online, epsilon=reg["epsilon"],
                                                         output_quantization="guarded_q24_v1"),
                "calibrated": selected,
                "calibrated_classical": {**deepcopy(selected), "classical": True},
                "calibrated_q24": {**deepcopy(selected), "output_quantization": "q24_parameters_nearest"},
                "calibrated_q24_classical": {**deepcopy(selected), "classical": True,
                                             "output_quantization": "q24_parameters_nearest"},
                "calibrated_unconstrained": candidate}
            checkpoint = {"seed": seed, "window": window, "training_environment": law,
                "prediction_reads_environment_or_window": False, "models": models,
                "previous_checkpoint_sha256": previous,
                "training": {"online": online_fit, "replay": replay_fit, "calibration": calibration_fit},
                "selection": selection, "holdout_used": False}
            path = seed_dir / (prefix + "_CHECKPOINT.json")
            _write(path, checkpoint)
            loaded = json.loads(path.read_text())
            probe = task.history(_prefix(training, 3))
            errors = {}
            for arm in ARMS:
                before = calibration.predict(models[arm], probe)
                after = calibration.predict(loaded["models"][arm], probe)
                errors[arm] = max(float(np.max(np.abs(a - b))) for a, b in zip(before, after))
                if errors[arm] != 0:
                    raise AssertionError("Actual checkpoint reload changed prediction")
            online, replay = loaded["models"]["online"], loaded["models"]["replay"]
            previous = _sha(path)
            receipts.append({"seed": seed, "window": window, "checkpoint_sha256": previous,
                "reload_max_absolute_errors": errors,
                "optimizer_success": {"online": online_fit["optimizer_success"],
                    "replay": replay_fit["optimizer_success"], "calibration": calibration_fit["optimizer_success"]},
                "calibration_parameter_l2_change": calibration_fit["parameter_l2_change"],
                "selected_index": selection["selected_index"], "candidate_count": selection["grid_size"]})
            print(json.dumps({"phase": "calibration_prepare", "seed": seed, "window": window}), flush=True)
    artifacts = {path.relative_to(destination).as_posix(): _sha(path)
                 for path in sorted(destination.rglob("*")) if path.is_file()}
    prepared = {"schema": "hepta.analytic-event.calibration-prepared.v1", "registration": reg,
        "source_sha256": source_hashes, "artifacts_sha256": artifacts, "checkpoint_receipts": receipts,
        "holdouts_constructed": False, "preparation_wall_ns": time.perf_counter_ns() - started,
        "preparation_parent_cpu_ns": time.process_time_ns() - cpu,
        "empirical_selection_is_not_a_pointwise_bound": True}
    _write(destination / "PREPARED.json", prepared)
    return {"prepared_sha256": _sha(destination / "PREPARED.json"), **prepared}


def verify_prepared(destination, reg, freeze_path=None):
    destination = Path(destination)
    prepared = json.loads((destination / "PREPARED.json").read_text())
    if prepared["registration"] != reg:
        raise ValueError("Calibration registration differs from preparation")
    source_root = Path(__file__).resolve().parent.parent
    for name, digest in prepared["source_sha256"].items():
        if _sha(source_root / name) != digest:
            raise ValueError("Prepared calibration source changed: " + name)
    for name, digest in prepared["artifacts_sha256"].items():
        if _sha(destination / name) != digest:
            raise ValueError("Prepared calibration artifact changed: " + name)
    if reg["phase"] == "confirmation":
        if freeze_path is None:
            raise ValueError("A parent source/model freeze is required before confirmation")
        freeze_path = Path(freeze_path)
        frozen = json.loads(freeze_path.read_text())
        for name in ["PREPARED.json", *prepared["artifacts_sha256"]]:
            path = (destination / name).resolve()
            key = path.relative_to(freeze_path.parent.resolve()).as_posix()
            if frozen["artifacts_sha256"].get(key) != _sha(path):
                raise ValueError("Prepared artifact is not bound by global freeze: " + key)
        repo = source_root.parent.parent
        for name in prepared["source_sha256"]:
            path = source_root / name
            key = path.relative_to(repo).as_posix()
            if frozen["sources_sha256"].get(key) != _sha(path):
                raise ValueError("Scientific source is not bound by global freeze: " + key)
    return prepared


def scores(model, data):
    mean, variance, details = calibration.predict_details(model, task.history(data))
    mean, variance, target = mean[:, 1:], variance[:, 1:], task.targets(data)[:, 1:]
    labels = task.event_labels(target)
    logp = event_log_probs(mean, variance, task.LOWER, task.UPPER)
    gaussian = .5 * (np.log(2 * np.pi * variance) + (target - mean) ** 2 / variance)
    event = -np.take_along_axis(logp, labels[..., None], -1)[..., 0]
    probability = np.exp(logp)
    output = {"ids": data["ids"], "targets": target, "mean": mean, "variance": variance,
        "probabilities": probability, "labels": labels, "gaussian_nll_by_horizon": gaussian,
        "gaussian_nll": gaussian.mean(1), "event_nll": event.mean(1),
        "coverage95": (abs(target - mean) <= 1.959963984540054 * np.sqrt(variance)).mean(1),
        "mse": ((target - mean) ** 2).mean(1)}
    for name in ("pointwise_nll_bound", "normalized_correction", "mean_q24", "variance_q24", "native_typed_domain_mask"):
        if name in details:
            output[name] = np.asarray(details[name])[:, 1:]
    if "adaptive_weight" in details:
        output["adaptive_weight"] = details["adaptive_weight"]
    scalar = {name: float(output[name].mean()) for name in ("gaussian_nll", "event_nll", "mse", "coverage95")}
    scalar["classwise_ece"] = statistics.calibration(probability, labels)["classwise_ece"]
    return output, scalar


def evaluate_study(destination, registration, freeze_path=None, output=None):
    """Generate fresh holdouts only after source and all prepared checkpoints bind."""
    destination, reg = Path(destination), _registered(registration)
    prepared = verify_prepared(destination, reg, freeze_path)
    output = Path(output) if output else destination.parent / "calibration_confirmation"
    if output.resolve() == destination.resolve() or destination.resolve() in output.resolve().parents:
        raise ValueError("Confirmation must not modify prepared model artifacts")
    output.mkdir(parents=True, exist_ok=False)
    records, array_index = [], []
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    equivalence = {"fp64_max_abs": 0.0, "q24_max_abs": 0.0}
    protection = {"protected": {"max_observed_excess": -1e99, "max_certified_bound": 0.0},
                  "protected_q24": {"max_observed_excess": -1e99, "max_certified_bound": 0.0}}
    for seed in reg["seeds"]:
        source = destination / f"seed_{seed}"
        old = task.build_dataset(data_seed(reg, seed, 12, 5), reg["old_holdout_rows"], "calibration_old_" + reg["phase"])
        np.savez_compressed(output / f"seed_{seed}_OLD.npz", **old)
        anchor = json.loads((source / "ANCHOR.json").read_text())
        old_anchor, _ = scores(anchor, old)
        for window, law in enumerate(reg["windows"]):
            prefix = f"seed_{seed}_window_{window:02d}"
            checkpoint = json.loads((source / f"window_{window:02d}_CHECKPOINT.json").read_text())
            new = task.build_dataset(data_seed(reg, seed, window, 4), reg["new_holdout_rows"],
                                     "calibration_new_" + reg["phase"], law)
            np.savez_compressed(output / (prefix + "_NEW.npz"), **new)
            archive, summaries, collected = {}, {}, {}
            for arm in ARMS:
                summaries[arm], collected[arm] = {}, {}
                for domain, data in (("old", old), ("new", new)):
                    arrays, summary = scores(checkpoint["models"][arm], data)
                    collected[arm][domain] = arrays
                    summaries[arm][domain] = summary
                    archive.update({arm + "__" + domain + "__" + key: value for key, value in arrays.items()})
                summaries[arm]["old_nll_degradation_from_initial"] = float(
                    (collected[arm]["old"]["gaussian_nll"] - old_anchor["gaussian_nll"]).mean())
            for domain in ("old", "new"):
                for suffix, key in (("", "fp64_max_abs"), ("_q24", "q24_max_abs")):
                    for moment in ("mean", "variance"):
                        error = float(np.max(abs(collected["calibrated" + suffix][domain][moment]
                                                  - collected["calibrated" + suffix + "_classical"][domain][moment])))
                        equivalence[key] = max(equivalence[key], error)
                for arm in protection:
                    values = collected[arm][domain]
                    observed = values["gaussian_nll_by_horizon"] - collected["frozen"][domain]["gaussian_nll_by_horizon"]
                    protection[arm]["max_observed_excess"] = max(protection[arm]["max_observed_excess"], float(observed.max()))
                    protection[arm]["max_certified_bound"] = max(protection[arm]["max_certified_bound"],
                                                                 float(values["pointwise_nll_bound"].max()))
                    if np.any(observed > values["pointwise_nll_bound"] + 2e-10):
                        raise AssertionError("Protected Gaussian bound failed on actual targets")
            path = output / (prefix + "_SCORES.npz")
            np.savez_compressed(path, **archive)
            record = {"seed": seed, "window": window, "law": law, "scores": summaries,
                "checkpoint_sha256": _sha(source / f"window_{window:02d}_CHECKPOINT.json"),
                "scores_sha256": _sha(path), "holdout_dataset_digest": task.dataset_digest(new)}
            records.append(record)
            array_index.append({"seed": seed, "window": window, "law": law, "path": path.name})
            _write(output / (prefix + ".json"), record)
            print(json.dumps({"phase": "calibration_confirmation", "seed": seed, "window": window}), flush=True)
    result = summarize(output, reg, records, array_index)
    result.update({"equivalence": equivalence, "protected_profiles": protection,
        "prepared_sha256": _sha(destination / "PREPARED.json"),
        "global_freeze_sha256": _sha(freeze_path) if freeze_path else None,
        "wall_ns": time.perf_counter_ns() - started, "parent_cpu_ns": time.process_time_ns() - cpu,
        "checkpoint_count": len(prepared["checkpoint_receipts"]),
        "unique_old_holdout_trajectories": len(reg["seeds"]) * reg["old_holdout_rows"],
        "unique_new_holdout_trajectories": len(reg["seeds"]) * len(reg["windows"]) * reg["new_holdout_rows"],
        "native_execution_in_this_study": False})
    verify_prepared(destination, reg, freeze_path)
    _write(output / "INDEX.json", {"records": records, "arrays": array_index})
    _write(output / "RESULTS.json", result)
    return result


def summarize(directory, reg, records, array_index):
    directory = Path(directory)
    loaded = {}
    for item in array_index:
        with np.load(directory / item["path"], allow_pickle=False) as data:
            loaded[(item["seed"], item["window"])] = {name: data[name] for name in data.files}
    result = {"schema": "hepta.analytic-event.calibration-results.v1", "registration": reg,
              "arms": {}, "unbounded_retention_claim": False, "production_promotion": False,
              "empirical_bootstrap_not_population_certificate": True,
              "windows_are_not_independent_training_replicates": True}
    shifted = [i for i, law in enumerate(reg["windows"]) if law == "drift_shift"]
    final_window = len(reg["windows"]) - 1
    for arm in ARMS:
        old_changes = [float(np.mean([r["scores"][arm]["old_nll_degradation_from_initial"]
                                     for r in records if r["window"] == window])) for window in range(len(reg["windows"]))]
        delta = np.asarray([[loaded[(seed, window)][arm + "__new__gaussian_nll"]
                             - loaded[(seed, window)]["frozen__new__gaussian_nll"]
                             for window in shifted] for seed in reg["seeds"]])
        final = np.asarray([[loaded[(seed, final_window)][arm + "__new__gaussian_nll"]
                             - loaded[(seed, final_window)]["frozen__new__gaussian_nll"]]
                             for seed in reg["seeds"]])
        interval = _interval(delta, reg["bootstrap_replicates"], reg["bootstrap_seed"])
        final_interval = _interval(final, reg["bootstrap_replicates"], reg["bootstrap_seed"] + 1)
        probability = np.concatenate([loaded[(seed, window)][arm + "__new__probabilities"]
                                      for seed in reg["seeds"] for window in shifted])
        labels = np.concatenate([loaded[(seed, window)][arm + "__new__labels"]
                                 for seed in reg["seeds"] for window in shifted])
        ece = statistics.calibration(probability, labels)
        coverage = float(np.mean([r["scores"][arm]["new"]["coverage95"] for r in records if r["window"] in shifted]))
        retention_pass = max(old_changes) <= reg["old_nll_margin"] and final_interval["mean_difference"] <= 0
        efficacy_pass = (retention_pass and final_interval["mean_difference"] <= -reg["new_nll_improvement_min"]
            and final_interval["interval95"][1] < 0 and max(final_interval["per_seed_mean"]) < 0)
        calibration_pass = (ece["classwise_ece"] <= reg["calibration_ece_max"]
            and reg["calibration_coverage_min"] <= coverage <= reg["calibration_coverage_max"])
        result["arms"][arm] = {"old_nll_changes_by_window": old_changes,
            "worst_window_old_nll_increase": max(old_changes),
            "worst_single_seed_window_old_nll_increase": max(r["scores"][arm]["old_nll_degradation_from_initial"] for r in records),
            "shifted_nll_difference": interval, "final_nll_difference": final_interval,
            "shifted_calibration": ece, "shifted_coverage95": coverage,
            "passes_original_bounded_retention_gate": bool(retention_pass),
            "passes_new_nll_efficacy_gate": bool(efficacy_pass),
            "passes_descriptive_calibration_gate": bool(calibration_pass),
            "passes_joint_empirical_gate": bool(efficacy_pass and calibration_pass),
            "universal_pointwise_retention_guarantee": arm in ("frozen", "protected", "protected_q24")}
    return result
