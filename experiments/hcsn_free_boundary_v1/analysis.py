"""Read-only analysis of the frozen study, with explicit failure and cost gates.

No primary result is read without COMPLETE.json unless --partial is supplied.
Learning-rate/checkpoint choices are audited, never changed by this module.
"""

import argparse
from collections import defaultdict
import csv
import hashlib
import itertools
import json
import math
from pathlib import Path
import time

import numpy as np
from scipy.special import logsumexp
from scipy.stats import t as student_t


PACKAGE = Path(__file__).resolve().parent
REPOSITORY = PACKAGE.parents[1]
BASELINES = ("legacy_hcsn", "two_gates", "continuous_rnn", "cfc", "mamba1", "transformer", "lif_snn")
HCSN_MODELS = {"free_dual", "fixed_dual", "direct_dual", "free_margin", "free_continuation", "free_ordinary"}
GROUPS = ("content", "dynamics", "boundary", "reset", "refractory")


class IncompleteStudyError(RuntimeError):
    pass


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            result.update(block)
    return result.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def expected_jobs(protocol):
    return sorted({(task, model, seed) for section in ("core", "mechanism")
                   for task in protocol[section]["tasks"] for model in protocol[section]["models"]
                   for seed in protocol[section]["seeds"]})


def require_complete(study, partial=False):
    marker = Path(study) / "COMPLETE.json"
    if not marker.is_file() and not partial:
        raise IncompleteStudyError("COMPLETE.json is absent; primary analysis is blocked. Use --partial only for explicitly incomplete reporting.")
    return read_json(marker) if marker.is_file() else None


def sign_flip_test(differences):
    values = np.asarray(differences, dtype=float)
    if values.ndim != 1 or not 1 <= len(values) <= 20 or not np.isfinite(values).all():
        raise ValueError("Require 1..20 finite paired differences.")
    signs = np.asarray(list(itertools.product((-1.0, 1.0), repeat=len(values))))
    null_statistics = np.abs(signs @ values / len(values))
    observed = abs(float(values.mean()))
    tolerance = 32 * np.finfo(float).eps * max(1.0, float(np.max(null_statistics)))
    extreme = int(np.count_nonzero(null_statistics >= observed - tolerance))
    return dict(p_value=extreme / len(null_statistics), permutations=len(null_statistics),
                extreme_permutations=extreme, observed_absolute_mean=observed,
                assumption="paired differences have sign exchangeability/symmetry under the null")


def holm_adjust(p_values):
    values = np.asarray(p_values, dtype=float)
    if values.ndim != 1 or not np.isfinite(values).all() or np.any((values < 0) | (values > 1)):
        raise ValueError("Holm requires finite probabilities.")
    order = np.argsort(values, kind="stable")
    adjusted, running = np.empty_like(values), 0.0
    for rank, index in enumerate(order):
        running = max(running, (len(values) - rank) * float(values[index]))
        adjusted[index] = min(1.0, running)
    return adjusted.tolist()


def descriptive(values):
    values = np.asarray(values, dtype=float)
    if not len(values):
        return dict(n=0, mean=None, sample_sd=None)
    if not np.isfinite(values).all():
        raise ValueError("Nonfinite descriptive observations.")
    return dict(n=len(values), mean=float(values.mean()),
                sample_sd=float(values.std(ddof=1)) if len(values) > 1 else None)


def paired_interval(values, alpha=0.05):
    result = descriptive(values)
    n = result["n"]
    if n < 2:
        return dict(result, lower=None, upper=None, degrees_of_freedom=None)
    radius = float(student_t.ppf(1 - alpha / 2, n - 1)) * result["sample_sd"] / math.sqrt(n)
    return dict(result, lower=result["mean"] - radius, upper=result["mean"] + radius,
                degrees_of_freedom=n - 1, interpretation="nominal paired-t interval, not simultaneous")


def validate_prediction_archive(path, expected_labels, classes):
    """Use explicit row coordinates; never flatten/reorder predictions by guess."""
    with np.load(path, allow_pickle=False) as archive:
        arrays = {name: np.array(archive[name], copy=True) for name in
                  ("logits", "predictions", "labels", "supervised", "sample_indices", "step_indices")}
    logits, predictions, labels = (arrays[name] for name in ("logits", "predictions", "labels"))
    mask, samples, steps = (arrays[name] for name in ("supervised", "sample_indices", "step_indices"))
    n = len(labels)
    if (expected_labels.ndim != 2 or mask.dtype != np.bool_ or mask.shape != expected_labels.shape
            or not np.array_equal(mask, expected_labels != -100) or logits.shape != (n, classes)
            or any(v.ndim != 1 or len(v) != n for v in (predictions, labels, samples, steps))
            or any(not np.issubdtype(v.dtype, np.integer) for v in (predictions, labels, samples, steps))
            or not np.isfinite(logits).all() or n == 0):
        raise ValueError("Prediction archive shape, finite-value, integer, or supervision-mask mismatch.")
    if np.any(samples < 0) or np.any(samples >= mask.shape[0]) or np.any(steps < 0) or np.any(steps >= mask.shape[1]):
        raise ValueError("Prediction row coordinate is out of bounds.")
    flattened = samples * mask.shape[1] + steps
    if not np.array_equal(np.sort(flattened), np.flatnonzero(mask)):
        raise ValueError("Prediction row coordinates must cover each supervised position exactly once.")
    if (not np.array_equal(labels, expected_labels[samples, steps])
            or not np.array_equal(predictions, logits.argmax(-1))
            or np.any(labels < 0) or np.any(labels >= classes)):
        raise ValueError("Prediction/argmax or mapped label disagreement.")
    correct = predictions == labels
    metrics = dict(accuracy=float(correct.mean()), correct=int(correct.sum()),
                   supervised_positions=n, samples=int(mask.shape[0]),
                   cross_entropy=float((logsumexp(logits.astype(float), axis=1) - logits[np.arange(n), labels]).mean()))
    return metrics, dict(samples=samples, steps=steps, correct=correct, labels=labels)


def _source_digest(archive, prefixes):
    result = hashlib.sha256()
    for name in sorted(k for k in archive.files if k.startswith(prefixes)):
        array = archive[name]
        result.update(name.encode())
        result.update(str((array.shape, array.dtype.str)).encode())
        result.update(array.tobytes())
    return result.hexdigest()


def _group(name):
    if "raw_K" in name or "raw_boundary_gap" in name:
        return "boundary"
    if "raw_reset_gap" in name:
        return "reset"
    if "raw_refractory" in name:
        return "refractory"
    if any(part in name for part in ("drift_input", "mu_bias", "raw_sigma", "raw_rho")):
        return "dynamics"
    return "content"


def selected_parameter_audit(initial_path, selected_path, counts):
    changes = {g: dict(l2=0.0, max_abs=0.0, elements=0) for g in GROUPS}
    named = {}
    with np.load(initial_path, allow_pickle=False) as initial, np.load(selected_path, allow_pickle=False) as selected:
        if set(initial.files) != set(selected.files):
            raise ValueError("Selected and initial state_dict keys differ.")
        for name in initial.files:
            if name.endswith(".fixed_boundary"):
                if not np.array_equal(initial[name], selected[name]):
                    raise ValueError("Fixed-boundary buffer changed.")
                continue
            if initial[name].shape != selected[name].shape or not np.isfinite(selected[name]).all():
                raise ValueError("Selected parameter shape/nonfinite mismatch.")
            difference = selected[name].astype(float) - initial[name].astype(float)
            group = _group(name)
            squared = float(np.sum(difference**2))
            maximum = float(np.max(np.abs(difference))) if difference.size else 0.0
            changes[group]["l2"] += squared
            changes[group]["max_abs"] = max(changes[group]["max_abs"], maximum)
            changes[group]["elements"] += difference.size
            if any(part in name for part in ("mu_bias", "raw_sigma", "raw_rho", "raw_K", "raw_reset_gap", "raw_refractory")):
                named[name] = dict(l2=math.sqrt(squared), max_abs=maximum, changed=maximum > 0)
        for group, record in changes.items():
            record["l2"] = math.sqrt(record["l2"])
            if record["elements"] != counts["groups"][group]:
                raise ValueError(f"Independent trainable parameter count mismatch for {group}.")
    return changes, named


def _read_updates(path, selected_step=None):
    prefixes, gradients = [], {}
    previous_cpu = -1.0
    with Path(path).open() as stream:
        for line in stream:
            row = json.loads(line)
            if row["step"] != len(prefixes) + 1 or row["training_cpu_seconds"] < previous_cpu:
                raise ValueError("Update steps/CPU clock are not monotone.")
            previous_cpu = row["training_cpu_seconds"]
            prefixes.append((row["step"], row["batch_sha256"], row["prefix_sha256"]))
            if selected_step is None or row["step"] <= selected_step:
                for name, g in row["gradients"].items():
                    record = gradients.setdefault(name, dict(all_finite=True, ever_nonzero=False, max_abs=0.0,
                                                             maximum_missing_elements=0, observations=0))
                    finite = bool(g["finite"]) and math.isfinite(g["l2"]) and math.isfinite(g["max_abs"])
                    record["all_finite"] &= finite
                    record["ever_nonzero"] |= g["max_abs"] > 0
                    record["max_abs"] = max(record["max_abs"], g["max_abs"])
                    record["maximum_missing_elements"] = max(record["maximum_missing_elements"], g["missing_elements"])
                    record["observations"] += 1
    return prefixes, gradients


def _metrics_match(actual, recorded):
    for name in ("accuracy", "correct", "supervised_positions", "samples"):
        if not math.isclose(actual[name], recorded[name], abs_tol=1e-12, rel_tol=1e-12):
            raise ValueError(f"Recomputed {name} disagrees with summary.")
    if not math.isclose(actual["cross_entropy"], recorded["cross_entropy"], abs_tol=1e-5, rel_tol=1e-6):
        raise ValueError("Recomputed cross entropy disagrees with summary.")


def inspect_run(directory, task, model, seed, protocol, dataset):
    """Audit a finished run and retain failures instead of silently dropping it."""
    directory = Path(directory)
    entry = dict(task=task, model=model, seed=seed, directory=str(directory), status="invalid", errors=[])
    prefixes, predictions, trainability = [], {}, None
    if (directory / "EXECUTION.json").is_file():
        try:
            entry["execution_receipt"] = read_json(directory / "EXECUTION.json")
        except Exception as error:
            entry["errors"].append(dict(type=type(error).__name__, message=str(error)))
    if not (directory / "summary.json").is_file():
        entry["status"] = "failed" if (directory / "failure.json").is_file() else "missing"
        if (directory / "failure.json").is_file():
            entry["failure"] = read_json(directory / "failure.json")
        return entry, prefixes, predictions, trainability
    try:
        summary = read_json(directory / "summary.json")
        execution = entry["execution_receipt"]
        if summary["status"] != "completed" or execution["status"] != "completed" or execution["returncode"] != 0:
            raise ValueError("Summary or process execution did not complete successfully.")
        request, selection = summary["request"], summary["selection"]
        if request["model"] != model or request["seed"] != seed or selection["dataset_sha256"] != dataset["sha256"]:
            raise ValueError("Run identity/dataset hash mismatch.")
        optimization = protocol["optimization"]
        for key in ("width", "depth", "batch_size", "max_updates"):
            if request[key] != optimization[key]:
                raise ValueError(f"Run request differs from frozen {key}.")
        if request["cpu_seconds"] != optimization["training_cpu_seconds_per_lr"] or request["learning_rates"] != optimization["learning_rates"]:
            raise ValueError("Run search budget/learning rates differ from protocol.")
        if read_json(directory / "selection.json") != selection:
            raise ValueError("Durable selection differs from summary.")
        selected_digest = digest(directory / "selected.npz")
        if selected_digest != selection["selected_checkpoint_sha256"]:
            raise ValueError("Selected checkpoint hash mismatch.")
        candidates = summary["candidates"]
        if sorted(c["learning_rate"] for c in candidates) != sorted(optimization["learning_rates"]):
            raise ValueError("Missing/duplicated learning-rate candidate.")
        winning = min(candidates, key=lambda c: (c["best"]["validation"]["cross_entropy"], c["learning_rate"]))
        if (winning["learning_rate"] != selection["selected_learning_rate"]
                or winning["best"]["step"] != selection["selected_step"]
                or winning["best"]["sha256"] != selected_digest
                or winning["best"]["validation"] != selection["selected_validation"]
                or selection["completed_lr_candidates"] != len(candidates)):
            raise ValueError("Primary selection was not the predeclared validation-only winner.")
        locked = [i for i, row in enumerate(summary["access_log"]) if row["event"] == "selection_locked"]
        heldout_access = [i for i, row in enumerate(summary["access_log"]) if row.get("split") in ("test", "ood")]
        if len(locked) != 1 or any(i <= locked[0] for i in heldout_access):
            raise ValueError("Access log fails the selection-before-holdout contract.")
        for candidate in candidates:
            candidate_dir = directory / candidate["directory"]
            disk = read_json(candidate_dir / "candidate.json")
            if disk != {k: v for k, v in candidate.items() if k != "directory"}:
                raise ValueError("Candidate JSON differs from summary copy.")
            if candidate["requested_training_cpu_seconds"] != optimization["training_cpu_seconds_per_lr"]:
                raise ValueError("Candidate requested CPU budget differs from frozen budget.")
            if candidate["training_cpu_seconds"] < candidate["requested_training_cpu_seconds"] and candidate["updates"] < optimization["max_updates"]:
                raise ValueError("Candidate stopped before both allowed stopping conditions.")
            if digest(candidate_dir / "initial.npz") != candidate["initial_sha256"]:
                raise ValueError("Initial checkpoint hash mismatch.")
            best = min((c for c in candidate["checkpoints"] if c["primary_eligible"]),
                       key=lambda c: (c["validation"]["cross_entropy"], c["training_cpu_seconds"], c["step"]))
            if best != candidate["best"]:
                raise ValueError("Within-LR checkpoint selection differs from validation/CPU/step rule.")
            for checkpoint in candidate["checkpoints"]:
                if digest(candidate_dir / checkpoint["weights"]) != checkpoint["sha256"]:
                    raise ValueError("Candidate checkpoint hash mismatch.")
            updates, gradients = _read_updates(candidate_dir / "updates.jsonl", winning["best"]["step"] if candidate is winning else None)
            if not all(g["all_finite"] for g in gradients.values()):
                raise ValueError("Recorded candidate gradients include a nonfinite value.")
            if len(updates) != candidate["updates"] or not updates or updates[-1][2] != candidate["batch_prefix_sha256"]:
                raise ValueError("Update log length/final prefix differs from candidate.")
            if candidate["updates"] >= 128 and updates[127][2] != candidate["first128_prefix_sha256"]:
                raise ValueError("128-update prefix mismatch.")
            with np.load(candidate_dir / "initial.npz", allow_pickle=False) as archive:
                shared_digest = _source_digest(archive, ("frontend.", "readout."))
            prefixes.append(dict(task=task, model=model, seed=seed, lr=candidate["learning_rate"],
                                 updates=updates, shared_initial_sha256=shared_digest,
                                 log_sha256=digest(candidate_dir / "updates.jsonl")))
            if candidate is winning and model in HCSN_MODELS:
                changes, named = selected_parameter_audit(candidate_dir / "initial.npz", directory / "selected.npz", summary["counts"])
                groups = {}
                for name in GROUPS:
                    recorded = candidate["selected_parameter_changes"][name]
                    if not math.isclose(changes[name]["l2"], recorded["l2"], abs_tol=1e-7, rel_tol=2e-5):
                        raise ValueError("Independent selected parameter change differs from recorded change.")
                    g = gradients.get(name, dict(all_finite=False, ever_nonzero=False, observations=0))
                    groups[name] = dict(gradient=g, selected_change=changes[name],
                                        passed=g["all_finite"] and g["ever_nonzero"] and changes[name]["max_abs"] > 0)
                trainability = dict(task=task, model=model, seed=seed, selected_step=winning["best"]["step"],
                                    selected_lr=winning["learning_rate"], groups=groups,
                                    named_dynamics_and_reset=named, all_groups_passed=all(g["passed"] for g in groups.values()))
        metrics = {}
        for split in ("test", "ood"):
            if split not in dataset["labels"]:
                if summary["holdout"].get(split) is not None:
                    raise ValueError("Holdout metrics exist for an absent data split.")
                metrics[split] = None
                continue
            path = directory / f"{split}_predictions.npz"
            actual, rows = validate_prediction_archive(path, dataset["labels"][split], dataset["manifest"]["output_dim"])
            _metrics_match(actual, summary["holdout"][split])
            metrics[split] = dict(actual, predictions_sha256=digest(path))
            predictions[split] = rows
        child_cpu = execution.get("child_cpu_seconds")
        costs = dict(training_cpu_seconds=sum(c["training_cpu_seconds"] for c in candidates),
                     candidate_setup_cpu_seconds=sum(c["setup_cpu_seconds"] for c in candidates),
                     candidate_validation_cpu_seconds=sum(c["validation_cpu_seconds"] for c in candidates),
                     candidate_total_cpu_seconds=sum(c["total_cpu_seconds"] for c in candidates),
                     holdout_cpu_seconds=summary["holdout_cpu_seconds"], search_function_cpu_seconds=summary["total_cpu_seconds"],
                     complete_child_cpu_seconds=child_cpu,
                     outside_search_function_cpu_seconds=None if child_cpu is None else child_cpu - summary["total_cpu_seconds"],
                     complete_child_wall_seconds=execution["wall_seconds"],
                     whole_process_peak_rss_bytes=execution.get("whole_child_peak_rss_bytes"),
                     updates_per_lr={str(c["learning_rate"]): c["updates"] for c in candidates})
        entry.update(status="valid", metrics=metrics, selection=selection, counts=summary["counts"], costs=costs,
                     selected_model_config=summary["selected_model_config"],
                     cross_lr_exact_validation_tie=len({c["best"]["validation"]["cross_entropy"] for c in candidates}) < len(candidates),
                     summary_sha256=digest(directory / "summary.json"), execution_sha256=digest(directory / "EXECUTION.json"))
    except Exception as error:
        entry["errors"].append(dict(type=type(error).__name__, message=str(error)))
    return entry, prefixes, predictions, trainability


def verify_pairing(prefixes):
    groups = defaultdict(list)
    for record in prefixes:
        groups[(record["task"], record["seed"])].append(record)
    result = []
    for (task, seed), records in sorted(groups.items()):
        minimum = min(len(r["updates"]) for r in records)
        reference = records[0]
        mismatches = []
        for row in records[1:]:
            first = next((i + 1 for i in range(minimum) if row["updates"][i] != reference["updates"][i]), None)
            if first is not None:
                mismatches.append(dict(model=row["model"], lr=row["lr"], first_mismatched_update=first))
        shared = {r["shared_initial_sha256"] for r in records}
        result.append(dict(task=task, seed=seed, candidates=len(records), common_updates=minimum,
                           common_prefix_sha256=reference["updates"][minimum - 1][2] if minimum else None,
                           paired_minibatches_verified=not mismatches and minimum > 0,
                           shared_frontend_readout_initialization_verified=len(shared) == 1,
                           mismatches=mismatches,
                           candidate_logs=[dict(model=r["model"], lr=r["lr"], updates=len(r["updates"]),
                                                updates_sha256=r["log_sha256"]) for r in records]))
    return result


def mechanism_comparisons(protocol, runs, global_gate=True):
    section, statistics = protocol["mechanism"], protocol["statistics"]
    rows, raw_p = [], []
    for comparator in statistics["mechanism_contrasts"]:
        pairs, missing = [], []
        for seed in section["seeds"]:
            task_differences = {}
            for task in section["tasks"]:
                left, right = runs.get((task, "free_dual", seed)), runs.get((task, comparator, seed))
                if not left or not right or left["status"] != "valid" or right["status"] != "valid":
                    missing.append(dict(task=task, seed=seed, free_status=None if not left else left["status"],
                                        comparison_status=None if not right else right["status"]))
                else:
                    task_differences[task] = left["metrics"]["test"]["accuracy"] - right["metrics"]["test"]["accuracy"]
            if len(task_differences) == len(section["tasks"]):
                pairs.append(dict(seed=seed, task_differences=task_differences,
                                  mean_difference=float(np.mean(list(task_differences.values())))))
        complete = not missing and len(pairs) == len(section["seeds"])
        differences = [p["mean_difference"] for p in pairs]
        test = sign_flip_test(differences) if complete else None
        interval = paired_interval(differences, statistics["alpha"]) if complete else None
        rows.append(dict(comparison=comparator, direction="free_dual_minus_comparison",
                         status="complete" if complete else "incomplete", seed_pairs=pairs, missing_or_invalid=missing,
                         test=test, paired_interval=interval, family_size=len(statistics["mechanism_contrasts"])))
        # Missing comparisons retain their place in the prespecified family.
        raw_p.append(test["p_value"] if test else 1.0)
    adjusted = holm_adjust(raw_p)
    for row, p in zip(rows, adjusted):
        interval = row["paired_interval"]
        row["holm_adjusted_p"] = p if row["test"] else None
        row["acceptance_components"] = dict(
            complete=row["status"] == "complete", global_integrity_gate=bool(global_gate),
            minimum_effect=interval is not None and interval["mean"] >= statistics["minimum_mean_advantage"],
            holm_significant=row["test"] is not None and p <= statistics["alpha"],
            nominal_interval_lower_positive=interval is not None and interval["lower"] > 0)
        row["accepted"] = all(row["acceptance_components"].values())
    return rows


def core_table(protocol, runs, global_gate=True):
    rows = []
    for task in protocol["core"]["tasks"]:
        for model in protocol["core"]["models"]:
            expected = protocol["core"]["seeds"]
            records = [runs[(task, model, seed)] for seed in expected]
            good = [r for r in records if r["status"] == "valid"]
            row = dict(task=task, model=model, status="complete" if len(good) == len(expected) else "incomplete",
                       expected_seeds=len(expected), valid_seeds=len(good),
                       missing_or_invalid_seeds=[r["seed"] for r in records if r["status"] != "valid"],
                       interpretation="three-seed descriptive mean/sample SD; no significance claim")
            for split in ("test", "ood"):
                metrics = [r["metrics"][split] for r in good if r["metrics"][split] is not None]
                for metric in ("accuracy", "cross_entropy"):
                    stats = descriptive([m[metric] for m in metrics])
                    row.update({f"{split}_{metric}_mean": stats["mean"], f"{split}_{metric}_sample_sd": stats["sample_sd"]})
                row[f"{split}_evaluated_seeds"] = len(metrics)
            for name in ("total", "frontend", "backbone", "readout"):
                counts = sorted({r["counts"][name] for r in good})
                row[f"parameters_{name}"] = counts[0] if len(counts) == 1 else counts
            for name in ("training_cpu_seconds", "complete_child_cpu_seconds", "search_function_cpu_seconds",
                         "outside_search_function_cpu_seconds", "complete_child_wall_seconds", "whole_process_peak_rss_bytes"):
                values = [r["costs"][name] for r in good if r["costs"][name] is not None]
                row[f"{name}_mean"] = descriptive(values)["mean"]
            rows.append(row)
    screens = []
    lookup = {(r["task"], r["model"]): r for r in rows}
    for task in protocol["core"]["tasks"]:
        free = lookup[(task, "free_dual")]
        alternatives = [lookup[(task, m)] for m in BASELINES]
        complete = free["status"] == "complete" and all(r["status"] == "complete" for r in alternatives)
        eligible = [r for r in alternatives if r["test_accuracy_mean"] is not None]
        best = max(eligible, key=lambda r: r["test_accuracy_mean"]) if eligible else None
        difference = None if not best or free["test_accuracy_mean"] is None else free["test_accuracy_mean"] - best["test_accuracy_mean"]
        matching = []
        for candidate in alternatives:
            target, actual = free["parameters_backbone"], candidate["parameters_backbone"]
            gap = abs(actual - target) / target if isinstance(target, int) and target > 0 and isinstance(actual, int) else None
            matching.append(dict(model=candidate["model"], backbone_relative_gap=gap,
                                  within_five_percent=gap is not None and gap <= 0.05,
                                  shared_frontend_count=candidate["parameters_frontend"] == free["parameters_frontend"],
                                  shared_readout_count=candidate["parameters_readout"] == free["parameters_readout"]))
        matched = all(r["within_five_percent"] and r["shared_frontend_count"] and r["shared_readout_count"] for r in matching)
        screens.append(dict(task=task, status="complete" if complete else "incomplete", best_baseline=None if not best else best["model"],
                            free_minus_best_baseline=difference, maximum_tolerated_accuracy_loss=0.02,
                            parameter_matching=matching, includes_legacy_hcsn=True,
                            passed=bool(global_gate and complete and matched and difference >= -0.02),
                            interpretation="descriptive 2pp screen, not an equivalence/noninferiority test"))
    return rows, screens


def data_strata(task, model, seed, split, rows, metadata):
    samples, correct = rows["samples"], rows["correct"]
    categories = {}
    for field, name in (("speakers", "speaker"), ("query_modalities", "query_modality")):
        if field in metadata:
            categories[name] = np.asarray(metadata[field], dtype=str)[samples]
    if "image_labels" in metadata and "audio_labels" in metadata:
        image, audio = np.asarray(metadata["image_labels"])[samples], np.asarray(metadata["audio_labels"])[samples]
        both = (image >= 0) & (audio >= 0)
        agreement = np.where(both, np.where(image == audio, "agree", "disagree"), "not_applicable")
        categories["distractor_digit_agreement"] = agreement
        if "query_modality" in categories:
            categories["query_by_agreement"] = np.char.add(np.char.add(categories["query_modality"], "|"), agreement)
    result = []
    for field, category in categories.items():
        for value in sorted(set(category.tolist()) - {""}):
            mask = category == value
            selected_samples = np.unique(samples[mask])
            record = dict(task=task, model=model, seed=seed, split=split, stratum=field, value=value,
                          supervised_positions=int(mask.sum()), correct=int(correct[mask].sum()),
                          accuracy=float(correct[mask].mean()), unique_episodes=len(selected_samples))
            for source, label in (("audio_source_ids", "unique_recordings"), ("image_source_ids", "unique_images")):
                record[label] = len({metadata[source][i] for i in selected_samples} - {""}) if source in metadata else 0
            result.append(record)
    return result


def aggregate_strata(protocol, rows):
    result = {}
    for cohort in ("core", "mechanism"):
        section = protocol[cohort]
        groups = defaultdict(list)
        for row in rows:
            if row["task"] in section["tasks"] and row["model"] in section["models"] and row["seed"] in section["seeds"]:
                key = tuple(row[k] for k in ("task", "model", "split", "stratum", "value"))
                groups[key].append(row)
        result[cohort] = [dict(zip(("task", "model", "split", "stratum", "value"), key),
                               accuracy=descriptive([r["accuracy"] for r in values]),
                               observed_seeds=[r["seed"] for r in values], expected_seeds=section["seeds"],
                               complete=len(values) == len(section["seeds"]),
                               supervised_positions_per_seed=[r["supervised_positions"] for r in values],
                               unique_recordings_per_seed=[r["unique_recordings"] for r in values])
                          for key, values in sorted(groups.items())]
    return result


def inspect_dataset(data_directory, task):
    path = Path(data_directory) / f"{task}.npz"
    manifest = read_json(path.with_suffix(".json"))
    actual_hash = digest(path)
    if actual_hash != manifest["sha256"]:
        raise ValueError(f"Frozen dataset hash mismatch: {task}")
    with np.load(path, allow_pickle=False) as archive:
        labels = {split: np.array(archive[f"{split}_y"], copy=True) for split in manifest["splits"]}
    audit = dict(task=task, sha256=actual_hash, manifest_sha256=digest(path.with_suffix(".json")),
                 splits={}, limitations=manifest["limitations"])
    for split, meta in manifest["splits"].items():
        if any(isinstance(value, list) and len(value) != len(labels[split]) for value in meta.values()):
            raise ValueError(f"Episode metadata length mismatch: {task}/{split}")
        ids = meta["episode_ids"]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate episode identity.")
        audit["splits"][split] = dict(episodes=len(ids), supervised_positions=int((labels[split] != -100).sum()),
                                      speakers=sorted(set(meta.get("speakers", [])) - {""}),
                                      unique_images=len(set(meta.get("image_source_ids", [])) - {""}),
                                      unique_recordings=len(set(meta.get("audio_source_ids", [])) - {""}))
    overlaps = []
    for field in ("image_source_ids", "audio_source_ids", "speakers"):
        for left, right in itertools.combinations(("train", "val", "test"), 2):
            a = set(manifest["splits"][left].get(field, [])) - {""}
            b = set(manifest["splits"][right].get(field, [])) - {""}
            overlap = sorted(a & b)
            if overlap:
                overlaps.append(dict(field=field, left=left, right=right, values=overlap))
    audit["source_or_speaker_overlaps"] = overlaps
    if overlaps:
        raise ValueError(f"Source/speaker split overlap: {task}")
    return dict(manifest=manifest, sha256=actual_hash, labels=labels, audit=audit)


def _write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def _write_csv(path, rows):
    if not rows:
        path.write_text("")
        return
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v for k, v in row.items()})


def analyze(study, data_directory, protocol_path, output=None, partial=False):
    started, started_cpu = time.perf_counter(), time.process_time()
    study, data_directory, protocol_path = map(Path, (study, data_directory, protocol_path))
    completion = require_complete(study, partial)
    protocol = read_json(protocol_path)
    output = Path(output) if output is not None else study / ("analysis_partial" if partial else "analysis001")
    filenames = ("ANALYSIS.json", "CORE_TABLE.csv", "MECHANISM_TABLE.csv", "TRAINABILITY.json", "DATA_STRATA.json")
    if any((output / name).exists() for name in filenames):
        raise FileExistsError("Analysis evidence already exists; select a fresh output directory.")
    identity = read_json(study / "IDENTITY.json") if (study / "IDENTITY.json").exists() else None
    integrity_errors = []
    if identity is None:
        integrity_errors.append("missing study IDENTITY.json")
    else:
        for path, expected in identity["files"].items():
            if not (REPOSITORY / path).is_file() or digest(REPOSITORY / path) != expected:
                integrity_errors.append(f"frozen file mismatch: {path}")
        unsigned = {k: v for k, v in identity.items() if k != "identity_sha256"}
        canonical = hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if canonical != identity["identity_sha256"]:
            integrity_errors.append("study identity self-hash mismatch")
        if completion and completion.get("identity_sha256") != identity["identity_sha256"]:
            integrity_errors.append("completion marker belongs to another identity")
        protocol_binding = identity.get("files", {}).get(identity.get("protocol_path"))
        if protocol_binding is None or protocol_binding != digest(protocol_path):
            integrity_errors.append("analysis protocol is not bound to the frozen protocol bytes")
        declared = {(r["task"], r["model"], r["seed"]) for r in identity.get("jobs", [])}
        if declared != set(expected_jobs(protocol)):
            integrity_errors.append("analysis job matrix differs from the frozen job matrix")
    if completion and (completion.get("finished_searches") != len(expected_jobs(protocol))
                       or completion.get("scheduled_searches") != len(expected_jobs(protocol))):
        integrity_errors.append("completion marker does not cover the full declared job matrix")
    datasets, dataset_errors = {}, []
    for task in protocol["core"]["tasks"]:
        try:
            datasets[task] = inspect_dataset(data_directory, task)
            if identity is not None:
                prefix = identity.get("data_directory", "") + "/" + task
                if (identity["files"].get(prefix + ".npz") != datasets[task]["sha256"]
                        or identity["files"].get(prefix + ".json") != datasets[task]["audit"]["manifest_sha256"]):
                    integrity_errors.append(f"analysis data/metadata is not bound to frozen files: {task}")
        except Exception as error:
            dataset_errors.append(dict(task=task, type=type(error).__name__, message=str(error)))
    runs, prefixes, strata, training_records = {}, [], [], []
    for task, model, seed in expected_jobs(protocol):
        if task not in datasets:
            entry = dict(task=task, model=model, seed=seed, status="invalid_dataset", errors=dataset_errors)
            runs[(task, model, seed)] = entry
            continue
        entry, run_prefixes, predictions, trainability = inspect_run(study / "runs" / task / model / str(seed),
                                                                    task, model, seed, protocol, datasets[task])
        runs[(task, model, seed)] = entry
        prefixes.extend(run_prefixes)
        if trainability is not None:
            trainability["run_integrity_status"] = entry["status"]
            training_records.append(trainability)
        if entry["status"] == "valid":
            for split, rows in predictions.items():
                strata.extend(data_strata(task, model, seed, split, rows, datasets[task]["manifest"]["splits"][split]))
    pairing = verify_pairing(prefixes)
    bad_pairing = any(not r["paired_minibatches_verified"] or not r["shared_frontend_readout_initialization_verified"] for r in pairing)
    global_gate = completion is not None and not partial and not integrity_errors and not dataset_errors and not bad_pairing
    core, screens = core_table(protocol, runs, global_gate)
    mechanism = mechanism_comparisons(protocol, runs, global_gate)
    valid = [r for r in runs.values() if r["status"] == "valid"]
    expected_hcsn = [key for key in runs if key[1] in HCSN_MODELS]
    trainability_map = {(r["task"], r["model"], r["seed"]): r for r in training_records}
    missing_training = [dict(task=t, model=m, seed=s, run_status=runs[(t, m, s)]["status"])
                        for t, m, s in expected_hcsn if (t, m, s) not in trainability_map]
    trainability_report = dict(schema="hcsn.trainability-analysis.v1", records=training_records,
                               missing_or_invalid=missing_training,
                               all_required_groups_passed=global_gate and not missing_training and all(
                                   r["all_groups_passed"] and r["run_integrity_status"] == "valid" for r in training_records),
                               evidence_scope="recorded gradients through selected step and independently recomputed numeric checkpoint changes")
    receipts = [r["execution_receipt"] for r in runs.values() if "execution_receipt" in r]
    costs = dict(known_training_cpu_seconds_from_valid_summaries=sum(r["costs"]["training_cpu_seconds"] for r in valid),
                 complete_child_cpu_seconds=sum(r.get("child_cpu_seconds") or 0 for r in receipts),
                 complete_child_cost_available_runs=sum(r.get("child_cpu_seconds") is not None for r in receipts),
                 failed_or_invalid_complete_child_cpu_seconds=sum(r["execution_receipt"].get("child_cpu_seconds") or 0
                                                                  for r in runs.values() if r["status"] != "valid" and "execution_receipt" in r),
                 scheduler_cpu_seconds=None if completion is None else completion.get("scheduler_cpu_seconds"),
                 latest_execution_all_child_cpu_seconds=None if completion is None else completion.get("all_child_process_cpu_seconds"),
                 scope="all observed unique search processes, including failed/invalid; full process cost charged regardless of selected checkpoint; no cost invented for a missing receipt",
                 outside_search_scope="child wait4 minus measured search function: interpreter/import/startup/shutdown combined, not a pure import benchmark",
                 additional_shared_data_audits_native_scaling_analysis_costs="reported separately; not silently included in these training-search totals",
                 energy_measured=False)
    report = dict(schema="hcsn.frozen-study-analysis.v1", study_id=protocol["study_id"], partial=bool(partial),
                  completion_marker_present=completion is not None, expected_searches=len(runs), valid_searches=len(valid),
                  freeze_identity_sha256=None if identity is None else identity.get("identity_sha256"),
                  statuses={status: sum(r["status"] == status for r in runs.values()) for status in sorted({r["status"] for r in runs.values()})},
                  global_integrity_gate=global_gate, integrity_errors=integrity_errors, dataset_errors=dataset_errors,
                  runs=list(runs.values()), pairing=pairing, core_content_screens=screens, mechanism=mechanism, costs=costs,
                  primary_acceptance_count=sum(row["accepted"] for row in mechanism),
                  all_content_screens_passed=all(row["passed"] for row in screens),
                  all_training_groups_passed=trainability_report["all_required_groups_passed"],
                  tie_operational_reading="within LR: validation CE, earlier CPU, step; across LR: validation CE then smaller LR; clarified before main outcomes",
                  exact_cross_lr_validation_tie_runs=[dict(task=r["task"], model=r["model"], seed=r["seed"]) for r in valid if r["cross_lr_exact_validation_tie"]],
                  statistical_scope=protocol["statistics"], source_sha256={"analysis.py": digest(__file__),
                      "analysis_tests.py": digest(PACKAGE / "analysis_tests.py"), "protocol": digest(protocol_path)},
                  analysis_cpu_seconds=time.process_time() - started_cpu, analysis_wall_seconds=time.perf_counter() - started,
                  analysis_cost_scope="analysis function, including verification/parsing/statistics; excludes interpreter/module import and final report writes")
    strata_report = dict(schema="hcsn.data-strata-analysis.v1", datasets=[v["audit"] for v in datasets.values()],
                         per_run=strata, aggregates=aggregate_strata(protocol, strata),
                         uncertainty_scope="seed means/sample SD only; no episode-level binomial CI or independent-recording inflation")
    mechanism_csv = [dict(comparison=r["comparison"], status=r["status"], n_seed_pairs=len(r["seed_pairs"]),
                          mean_advantage=None if r["paired_interval"] is None else r["paired_interval"]["mean"],
                          sample_sd=None if r["paired_interval"] is None else r["paired_interval"]["sample_sd"],
                          paired_t95_lower=None if r["paired_interval"] is None else r["paired_interval"]["lower"],
                          paired_t95_upper=None if r["paired_interval"] is None else r["paired_interval"]["upper"],
                          sign_flip_p=None if r["test"] is None else r["test"]["p_value"],
                          holm_adjusted_p=r["holm_adjusted_p"], accepted=r["accepted"], missing_or_invalid=r["missing_or_invalid"])
                     for r in mechanism]
    output.mkdir(parents=True, exist_ok=True)
    for name, value in (("ANALYSIS.json", report), ("TRAINABILITY.json", trainability_report), ("DATA_STRATA.json", strata_report)):
        _write_json(output / name, value)
    _write_csv(output / "CORE_TABLE.csv", core)
    _write_csv(output / "MECHANISM_TABLE.csv", mechanism_csv)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", choices=("analyze", "secondary128"), default="analyze")
    parser.add_argument("--study", type=Path, default=PACKAGE / "results/study001")
    parser.add_argument("--data", type=Path, default=PACKAGE / "data/study001")
    parser.add_argument("--protocol", type=Path, default=PACKAGE / "PROTOCOL.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--partial", action="store_true")
    args = parser.parse_args()
    if args.command == "secondary128":
        from .analysis_secondary import evaluate_secondary128
        result = evaluate_secondary128(args.study, args.data, args.protocol, args.output, args.partial)
        print(json.dumps(dict(status=result["status"], available_runs=result["available_runs"], expected_runs=result["expected_runs"])))
    else:
        result = analyze(args.study, args.data, args.protocol, args.output, args.partial)
        print(json.dumps(dict(valid_searches=result["valid_searches"], expected_searches=result["expected_searches"],
                              global_integrity_gate=result["global_integrity_gate"], accepted_mechanism_contrasts=result["primary_acceptance_count"])))


if __name__ == "__main__":
    main()
