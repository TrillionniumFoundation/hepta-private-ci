"""Read-only independent audit of the registered Round5 preparation.

Run with the same Python executable as preparation, for example:
  python -B experiments/analytic_event_neuron/round5/evidence/reviews/review_prepared.py

The only output is PREPARED_REVIEW.json, created exclusively after every check.
No generator, optimizer, freeze, confirmation or native evaluator is called.
"""

import time

AUDIT_WALL_STARTED = time.perf_counter_ns()
AUDIT_CPU_STARTED = time.process_time_ns()

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO))

import numpy as np
from scipy.special import expit, logsumexp

from experiments.analytic_event_neuron import learners, retention, task
from experiments.analytic_event_neuron.round4 import calibration as cal
from experiments.analytic_event_neuron.round4 import calibration_study as prior_study
from experiments.analytic_event_neuron.round5 import selection_study as study

PREFIX = "experiments/analytic_event_neuron/round5/"
EXPECTED_NEW_SOURCES = {
    PREFIX + "selection_study.py": "32d5033041ed69c4f6b880f165d98705d1aa1a2ea91136714d7b4229f9a73e83",
    PREFIX + "selection_math.py": "ea1344a6c4c5a81d9fa932f4f70e938e9d37cb9a695301c5bcabe87055d9f72b",
    PREFIX + "SELECTION_CONTRACT.md": "cb00c253a1564ceb3533d78831964e5bb17a36d022ef920bf5c0b1d2fdaffa4a",
    PREFIX + "test_selection.py": "f86a63f1e9fb91706efe4865e55e507d7b91da91c40282cf59a6dcfb279908ec",
    PREFIX + "__init__.py": "b02ccc3b03e70e66e4338ce36e0a12cc76e38a8ec50845e315a4695e39dee4b5",
}
EXPECTED_REGISTRATION = "ec3c907a0d016ba7bad960d69e76a0571af1eec14bb9e24a8ded202179a0defc"
EXPECTED_PREPARED = "077a8fc372ba603da451ed6118fd99343d924524c5fd7cd2e0b6ef10b6432bf6"
EXPECTED_SOURCE_REVIEW = "ad7a2be7e2a8720a9982f01cf2db806a165e0f2fca165372761b30773ec7e473"
CHECKS = 0
FORBIDDEN_CALLS = {"generation": 0, "optimization": 0, "study_mutation": 0}


def require(value, label):
    global CHECKS
    CHECKS += 1
    if not value:
        raise AssertionError(label)


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def object_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def load_data(path):
    with np.load(path, allow_pickle=False) as archive:
        return {key: archive[key].item() if archive[key].ndim == 0 else archive[key] for key in archive.files}


def dataset_digest(data):
    digest = hashlib.sha256()
    for key, value in sorted(data.items()):
        digest.update(key.encode())
        digest.update(value.tobytes() if isinstance(value, np.ndarray) else str(value).encode())
    return digest.hexdigest()


def forbid(kind):
    def rejected(*args, **kwargs):
        FORBIDDEN_CALLS[kind] += 1
        raise RuntimeError("Independent preparation audit prohibits " + kind)
    return rejected


def disable_mutating_science():
    task.build_dataset = forbid("generation")
    retention._adapt = forbid("optimization")
    retention.minimize = forbid("optimization")
    cal.fit_prior = forbid("optimization")
    cal.minimize = forbid("optimization")
    for name in ("adapt", "prepare", "freeze_prepared", "confirm", "summarize", "write"):
        setattr(study, name, forbid("study_mutation"))


def max_error(left, right):
    left, right = np.asarray(left), np.asarray(right)
    require(left.shape == right.shape, "forecast shape")
    finite = np.isfinite(left)
    require(np.array_equal(finite, np.isfinite(right)), "forecast finite mask")
    require(np.array_equal(left[~finite], right[~finite]), "forecast structural infinities")
    return float(np.max(np.abs(left[finite] - right[finite]), initial=0.0))


def independent_mixture_nll(cache, prior, projection, target):
    """Direct posterior-weight and density formula, separate from selectors."""
    likelihood = cache["query_log_likelihoods"] + cache["context_log_likelihoods"]
    if prior in (0.0, 1.0):
        log_weights = np.tile([0.0, -np.inf] if prior == 0.0 else [-np.inf, 0.0], (len(target), 1))
    else:
        unnormalized = likelihood + np.log([1.0 - prior, prior])
        log_weights = unnormalized - logsumexp(unnormalized, axis=1, keepdims=True)
    means, variances = cache["means"], cache["variances"]
    if projection:
        weights = np.exp(log_weights)[:, None, :]
        mean = np.sum(weights * means, axis=-1)
        variance = np.sum(weights * (variances + (means - mean[..., None]) ** 2), axis=-1)
        return 0.5 * (np.log(2.0 * np.pi * variance) + (target - mean) ** 2 / variance)
    component_density = -0.5 * (np.log(2.0 * np.pi * variances) + (target[..., None] - means) ** 2 / variances)
    return -logsumexp(log_weights[:, None, :] + component_density, axis=-1)


def component_objective(parameters, pieces):
    pairs = [task.combine_training(data) for data in pieces]
    history = {key: np.concatenate([pair[0][key] for pair in pairs]) for key in pairs[0][0]}
    target = np.concatenate([pair[1] for pair in pairs])
    mean, variance = learners.predict({"kind": "filter", "parameters": parameters}, history)
    return float(0.5 * np.mean(np.log(2.0 * np.pi * variance) + (target - mean) ** 2 / variance)), len(target)


def component_fit(label, fit, pieces, initial, model):
    require(fit["optimizer_success"] is True, label + " optimizer status")
    require(fit["initial_parameters"] == initial["parameters"] and fit["final_parameters"] == model["parameters"], label + " parameter identity")
    require(model["planning_q"] == model["parameters"][1] and model["planning_noise_scale"] == model["parameters"][2], label + " planning state")
    digests = [dataset_digest(data) for data in pieces]
    require(fit["dataset_digests"] == digests and fit["training_trajectories"] == sum(len(data["ids"]) for data in pieces), label + " fit data")
    require(all(data["split"] in ("train", "retention_train") for data in pieces), label + " training-only split")
    before, rows = component_objective(fit["initial_parameters"], pieces)
    after, final_rows = component_objective(fit["final_parameters"], pieces)
    trace = np.asarray(fit["objective_trace"])
    require(len(trace) > 1 and np.isfinite(trace).all() and rows == final_rows, label + " objective trace")
    initial_error, final_error = abs(before - trace[0]), float(np.min(np.abs(after - trace)))
    require(initial_error < 2e-12 and final_error < 2e-12, label + " objective endpoint replay")
    delta = float(np.linalg.norm(np.asarray(fit["final_parameters"]) - fit["initial_parameters"]))
    require(delta > 0.0 and after <= before + 2e-12, label + " actual parameter update")
    require(fit["complete_fit_wall_ns"] >= fit["training_wall_ns"] > 0 and fit["complete_fit_parent_cpu_ns"] > 0, label + " complete-fit timing")
    return {"fit": label, "training_trajectories": fit["training_trajectories"], "correlated_stage_rows": rows,
            "dataset_digests": digests, "initial_parameters": fit["initial_parameters"], "final_parameters": fit["final_parameters"],
            "parameter_delta_l2": delta, "initial_objective": before, "final_objective": after,
            "initial_objective_error": initial_error, "final_objective_nearest_trace_error": final_error,
            "final_objective_last_quartet_error": float(np.min(np.abs(after - trace[-4:]))),
            "objective_evaluations": len(trace), "optimizer_success": True,
            "complete_fit_wall_ns": fit["complete_fit_wall_ns"], "complete_fit_parent_cpu_ns": fit["complete_fit_parent_cpu_ns"]}


def prior_fit(label, fit, anchor, online, old_train, train, projection):
    pieces = [old_train, train]
    digests = [dataset_digest(data) for data in pieces]
    require(fit["optimizer_success"] is True and fit["initial_prior"] == 0.5, label + " prior status")
    require(fit["dataset_digests"] == digests and fit["training_trajectories"] == 512 and fit["context_public_histories"] == 0, label + " prior data")
    model = cal.make_model(anchor, online, context_count=0, projection=projection)
    model["prior"] = fit["fitted_prior"]
    caches = [cal.component_cache(model, task.history(data)) for data in pieces]
    cache = {key: np.concatenate([item[key] for item in caches]) for key in caches[0]}
    target = np.concatenate([task.targets(data) for data in pieces])
    errors = []
    for row in fit["objective_trace"]:
        value, gradient = cal.prior_objective([row["prior_logit"]], cache, target, projection)
        direct = float(independent_mixture_nll(cache, float(expit(row["prior_logit"])), projection, target).mean())
        errors.append(max(abs(value - row["nll"]), abs(float(gradient[0]) - row["gradient"]), abs(direct - row["nll"])))
    trace = fit["objective_trace"]
    require(len(trace) > 1 and max(errors) < 2e-12, label + " prior objective/gradient trace")
    require(abs(float(expit(trace[-1]["prior_logit"])) - fit["fitted_prior"]) < 1e-15, label + " final prior")
    require(abs(trace[-1]["prior_logit"]) == fit["prior_logit_change"] and fit["prior_logit_change"] > 0.0, label + " logit update")
    require(trace[-1]["nll"] <= trace[0]["nll"] + 2e-12, label + " objective improvement")
    require(fit["training_wall_ns"] > 0 and fit["training_parent_cpu_ns"] > 0, label + " prior timing")
    return model, {"fit": label, "training_trajectories": 512, "dataset_digests": digests,
                   "fitted_prior": fit["fitted_prior"], "prior_logit_change": fit["prior_logit_change"],
                   "final_logit": trace[-1]["prior_logit"], "at_inherited_logit_bound": abs(trace[-1]["prior_logit"]) == 6.0,
                   "initial_objective": trace[0]["nll"], "final_objective": trace[-1]["nll"],
                   "objective_evaluations": len(trace), "max_objective_or_gradient_replay_error": max(errors), "optimizer_success": True,
                   "training_wall_ns": fit["training_wall_ns"], "training_parent_cpu_ns": fit["training_parent_cpu_ns"]}


def selector_check(seed, window, arm, record, anchor, endpoint, model, old_dev, new_dev):
    histories = [task.history(data) for data in (old_dev, new_dev)]
    targets = [task.targets(data) for data in (old_dev, new_dev)]
    gaussian = arm in ("replay_legacy", "gaussian_full_range")
    require(record["candidate_count"] == len(record["candidates"]) == 21 and record["public_context_histories"] == 0, arm + " candidate/context count")
    require(record["development_dataset_digests"] == [dataset_digest(old_dev), dataset_digest(new_dev)] and record["development_labelled_queries"] == 512, arm + " development identity")
    require(record["old_guard_is_selection_heuristic_not_guarantee"] is True, arm + " guard scope")
    require(record["selection_wall_ns"] > 0 and record["selection_parent_cpu_ns"] > 0, arm + " timing")
    if gaussian:
        mean, var = learners.predict(anchor, histories[0])
        anchor_loss = 0.5 * (np.log(2 * np.pi * var[:, 1:]) + (targets[0][:, 1:] - mean[:, 1:]) ** 2 / var[:, 1:])
        require(record["endpoint"] == ("balanced_replay" if arm == "replay_legacy" else "current_only_online"), arm + " endpoint")
    else:
        caches = [cal.component_cache(model, history) for history in histories]
        anchor_loss = independent_mixture_nll(caches[0], 0.0, False, targets[0])[:, 1:]
        require(record["fitted_prior"] == model["prior"] and record["grid"] == ("legacy" if arm.endswith("legacy") else "full_range"), arm + " fitted prior/grid")
        require(record["grids_not_assumed_nested"] is True, arm + " grid declaration")
    errors, eligible, independent_new, candidates = [], [], [], []
    for index, (strength, row) in enumerate(zip(np.linspace(0, 1, 21), record["candidates"])):
        strength = float(strength)
        require(row["strength"] == strength, arm + " candidate strength")
        if gaussian:
            params = ((1.0 - strength) * np.asarray(anchor["parameters"]) + strength * np.asarray(endpoint["parameters"]))
            require(row["parameters"] == params.tolist(), arm + " interpolation geometry")
            candidate = {**deepcopy(endpoint), "parameters": params.tolist(), "planning_q": float(params[1]), "planning_noise_scale": float(params[2])}
            losses = []
            for history, target in zip(histories, targets):
                mean, var = learners.predict(candidate, history)
                losses.append(0.5 * (np.log(2 * np.pi * var[:, 1:]) + (target[:, 1:] - mean[:, 1:]) ** 2 / var[:, 1:]))
            selected = cal.make_model(candidate, candidate, context_count=0)
            selected["prior"] = 0.0
        else:
            prior = strength * model["prior"] if record["grid"] == "legacy" else strength
            require(row["prior"] == prior, arm + " prior grid geometry")
            losses = [independent_mixture_nll(cache, prior, model["projection"], target)[:, 1:] for cache, target in zip(caches, targets)]
            selected = {**deepcopy(model), "prior": prior}
        difference = (losses[0] - anchor_loss).mean(axis=1)
        old_mean = float(difference.mean())
        paired_se = float(difference.std(ddof=1) / np.sqrt(len(difference)))
        upper, new_mean = old_mean + 1.645 * paired_se, float(losses[1].mean())
        expect = {"old_nll_change": old_mean, "old_paired_se": paired_se, "old_upper_heuristic": upper, "new_nll": new_mean}
        errors.append(max(abs(row[key] - value) for key, value in expect.items()))
        require(row["eligible"] == (upper <= 0.02), arm + " eligibility")
        if upper <= 0.02:
            eligible.append(index)
        independent_new.append(new_mean)
        candidates.append(selected)
    require(max(errors) < 2e-12 and 0 in eligible, arm + " independent candidate scores")
    chosen = min(eligible, key=lambda index: (independent_new[index], index))
    require(chosen == record["selected_index"], arm + " independently selected index")
    stored_choice = min([i for i, row in enumerate(record["candidates"]) if row["eligible"]], key=lambda i: (record["candidates"][i]["new_nll"], i))
    require(chosen == stored_choice, arm + " stored-score tie break")
    picked = record["candidates"][chosen]
    return candidates[chosen], {"seed": seed, "window": window, "arm": arm, "candidates_checked": 21,
                               "max_independent_score_error": max(errors), "selected_index": chosen,
                               "eligible_candidates": len(eligible), "selected_strength": picked["strength"],
                               "selected_prior": picked.get("prior"), "selected_new_nll": picked["new_nll"],
                               "selected_old_upper_heuristic": picked["old_upper_heuristic"],
                               "selection_wall_ns": record["selection_wall_ns"], "selection_parent_cpu_ns": record["selection_parent_cpu_ns"]}


def audit(run_dir):
    disable_mutating_science()
    prepared_root = run_dir / "prepared"
    prepared_path = prepared_root / "PREPARED.json"
    prepared, started = read(prepared_path), read(run_dir / "PREPARATION_STARTED.json")
    require(file_sha(prepared_path) == EXPECTED_PREPARED, "pinned preparation identity")
    require(file_sha(study.OLD_FREEZE) == study.OLD_FREEZE_SHA, "inherited Round4 freeze")
    old = read(study.OLD_FREEZE)["sources_sha256"]
    sources = {**old, **EXPECTED_NEW_SOURCES}
    require(len(old) == 102 and len(sources) == 107, "source cardinality")
    require(prepared["sources_sha256"] == started["sources_sha256"] == sources, "source maps")
    for path, digest in sources.items():
        require(file_sha(REPO / path) == digest, "source hash: " + path)
    source_review_path = Path(__file__).with_name("SELECTION_SOURCE_REVIEW.json")
    source_review = read(source_review_path)
    require(file_sha(source_review_path) == EXPECTED_SOURCE_REVIEW and source_review["source_hashes_sha256"] == EXPECTED_NEW_SOURCES, "independent source review binding")
    require(source_review["verdict"]["blocking_findings_remaining"] == 0, "source-review blockers")
    reg = prepared["registration"]
    require(reg == started["registration"] == study.registration(), "registered protocol")
    require(object_sha(reg) == prepared["registration_sha256"] == started["registration_sha256"] == EXPECTED_REGISTRATION, "registered protocol digest")
    require(prepared["environment"] == started["environment"] == study.environment_snapshot(), "recorded/current numerical environment")
    schedule = prepared["planned_seed_schedule"]
    require(schedule == started["planned_seed_schedule"] == study.seed_schedule(reg), "full planned identity roster")
    require(len(schedule) == len({row["generator_seed"] for row in schedule}) == 250, "planned identities unique")
    smoke_seeds = {row["generator_seed"] for row in study.seed_schedule(study.registration("development_smoke"))}
    require(not smoke_seeds.intersection(row["generator_seed"] for row in schedule), "formal/smoke identity separation")
    for name in ("confirmation", "CONFIRMATION_STARTED.json", "CONFIRMATION_FAILED.json", "FREEZE.json", "PREPARATION_FAILED.json"):
        require(not (run_dir / name).exists(), "unexpected pre-freeze artifact: " + name)
    expected = set()
    for seed in reg["seeds"]:
        expected.update(f"seed_{seed}/{name}" for name in ("ORIGINAL_TRAIN.npz", "ANCHOR.json"))
        expected.update(f"seed_{seed}/window_{window:02d}_{name}" for window in range(12) for name in ("TRAIN.npz", "OLD_DEV.npz", "NEW_DEV.npz", "CHECKPOINT.json"))
    actual = {path.relative_to(prepared_root).as_posix(): file_sha(path) for path in prepared_root.rglob("*") if path.is_file() and path != prepared_path}
    require(set(actual) == expected and actual == prepared["artifacts_sha256"] and len(actual) == 250, "exact prepared artifact roster")
    data_rows, datasets, identifiers = [], {}, set()
    for row in schedule:
        if row["phase"] != "prepare":
            continue
        seed, window, role = row["seed"], row["window"], row["role"]
        name = "ORIGINAL_TRAIN.npz" if role == "anchor" else f"window_{window:02d}_{role.upper()}.npz"
        path = prepared_root / f"seed_{seed}" / name
        data, count = load_data(path), 512 if role == "anchor" else 256
        datasets[seed, window, role] = data
        identity = "|".join(map(str, (reg["namespace"], "prepare", seed, window, role)))
        derived = int.from_bytes(hashlib.sha256(identity.encode()).digest()[:8], "big") & ((1 << 53) - 1)
        split = "train" if role == "anchor" else "retention_train" if role == "train" else "calibration_development"
        law = "gaussian" if role in ("anchor", "old_dev") else reg["windows"][window]
        ids = [f"{split}:{law}:{derived}:{i}" for i in range(count)]
        require(data["seed"] == row["generator_seed"] == derived and data["split"] == split and data["law"] == law, "raw seed/split/domain identity")
        require(data["drift"] == (0.32 if law == "drift_shift" else 0.12), "raw drift metadata")
        require(data["ids"].tolist() == ids and not identifiers.intersection(ids), "raw row identities/disjointness")
        identifiers.update(ids)
        matrix_keys = ("obs", "times", "mask", "obs_var", "future")
        vector_keys = ("repair_observation", "wait_observation", "wait_repair_observation", "cost_multiplier")
        require(set(data) == set(matrix_keys + vector_keys + ("ids", "seed", "split", "law", "drift")), "raw exact field roster")
        require(all(data[key].shape == (count, 6) and np.isfinite(data[key]).all() for key in matrix_keys), "raw matrix shape/finiteness")
        require(all(data[key].shape == (count,) and np.isfinite(data[key]).all() for key in vector_keys), "raw vector shape/finiteness")
        require(data["mask"].dtype == bool and np.all(data["mask"][:, -1]) and np.all(data["obs"][~data["mask"]] == 0), "mask semantics")
        require(np.all(data["times"][:, 0] > 0) and np.all(np.diff(data["times"], axis=1) > 0), "physical time order")
        require(np.all(data["obs_var"] == 0.64) and set(data["cost_multiplier"]) <= {0.5, 1.0, 2.0, 4.0}, "sensor variance/cost metadata")
        digest = dataset_digest(data)
        require(digest == task.dataset_digest(data), "independent digest agreement")
        data_rows.append({"path": path.relative_to(run_dir).as_posix(), "generator_seed": derived, "rows": count,
                          "split": split, "law": law, "sha256": file_sha(path), "dataset_digest": digest})
    require(len(data_rows) == 185 and len(identifiers) == 48640, "raw collection count")
    require(len(prepared["checkpoint_receipts"]) == 60, "checkpoint receipt count")
    receipts = {(row["seed"], row["window"]): row for row in prepared["checkpoint_receipts"]}
    require(set(receipts) == {(seed, window) for seed in reg["seeds"] for window in range(12)}, "checkpoint receipt scopes")
    component_rows, prior_rows, selection_rows, reload_rows = [], [], [], []
    for seed in reg["seeds"]:
        original = datasets[seed, -1, "anchor"]
        old_train = prior_study.subset(original, 256)
        anchor_record = read(prepared_root / f"seed_{seed}/ANCHOR.json")
        anchor = anchor_record["model"]
        component_rows.append(component_fit(f"{seed}/anchor", anchor_record["fit"], [original], {"parameters": [0.0, 0.4, 1.4]}, anchor))
        previous, online, replay = None, anchor, anchor
        for window, law in enumerate(reg["windows"]):
            cp_path = prepared_root / f"seed_{seed}/window_{window:02d}_CHECKPOINT.json"
            checkpoint, receipt = read(cp_path), receipts[seed, window]
            train, old_dev, new_dev = [datasets[seed, window, role] for role in ("train", "old_dev", "new_dev")]
            require(checkpoint["seed"] == seed and checkpoint["window"] == window and checkpoint["training_environment"] == law, "checkpoint scope")
            require(checkpoint["previous_checkpoint_sha256"] == previous and receipt["checkpoint_sha256"] == file_sha(cp_path), "checkpoint hash chain")
            require(checkpoint["holdout_used"] is False and checkpoint["public_context_histories"] == 0 and checkpoint["extra_model_features"] == [], "checkpoint information boundary")
            require(checkpoint["training_dataset_digests"] == {"old": dataset_digest(old_train), "new": dataset_digest(train)}, "checkpoint training datasets")
            require(set(checkpoint["component_training"]) == {"online", "replay"} and set(checkpoint["prior_training"]) == {"mixture", "moment"}, "fit roster")
            for name, pieces, initial in (("online", [train], online), ("replay", [old_train, train], replay)):
                result = component_fit(f"{seed}/{window}/{name}", checkpoint["component_training"][name], pieces, initial, checkpoint[name + "_state"])
                require(receipt["component_parameter_changes"][name] == result["parameter_delta_l2"], "component-change receipt")
                component_rows.append(result)
            online, replay = checkpoint["online_state"], checkpoint["replay_state"]
            fitted = {}
            for family, projection in (("mixture", False), ("moment", True)):
                fitted[family], result = prior_fit(f"{seed}/{window}/{family}", checkpoint["prior_training"][family], anchor, online, old_train, train, projection)
                require(receipt["prior_logit_changes"][family] == result["prior_logit_change"], "prior-change receipt")
                prior_rows.append(result)
            models = {"frozen": cal.make_model(anchor, anchor, context_count=0)}
            models["frozen"]["prior"] = 0.0
            selector_arms = [name for name in reg["arms"] if name not in ("frozen", "same_weight_moment_full")]
            require(set(checkpoint["selection"]) == set(selector_arms), "selector roster")
            for arm in selector_arms:
                family = "mixture" if arm.startswith("mixture") else "moment"
                model = fitted[family] if arm.startswith(("mixture", "moment")) else None
                models[arm], result = selector_check(seed, window, arm, checkpoint["selection"][arm], anchor,
                                                     replay if arm == "replay_legacy" else online, model, old_dev, new_dev)
                selection_rows.append(result)
            models["same_weight_moment_full"] = {**deepcopy(models["mixture_full_range"]), "projection": True}
            require(models == checkpoint["models"], "all selected model dictionaries independently reconstruct")
            require(set(receipt["reload_errors"]) == set(reg["arms"]) and all(value == 0 for value in receipt["reload_errors"].values()), "original reload receipt")
            errors = {}
            for arm in reg["arms"]:
                maximum = 0.0
                for data in (train, old_dev, new_dev):
                    history = task.history(data)
                    left = cal.predict_distribution(models[arm], history)
                    right = cal.predict_distribution(checkpoint["models"][arm], history)
                    maximum = max(maximum, *(max_error(left[key], right[key]) for key in left))
                errors[arm] = maximum
            require(max(errors.values()) == 0.0, "actual reconstructed/saved forecasts")
            altered = deepcopy(new_dev)
            altered["future"][:] = -999.0
            altered["ids"][:] = "irrelevant"
            altered["law"], altered["drift"] = "unused_metadata", -100.0
            for key in ("repair_observation", "wait_observation", "wait_repair_observation"):
                altered[key][:] = -1000.0
            hidden_errors = {}
            for arm in reg["arms"]:
                left = cal.predict_distribution(checkpoint["models"][arm], task.history(new_dev))
                right = cal.predict_distribution(checkpoint["models"][arm], task.history(altered))
                hidden_errors[arm] = max(max_error(left[key], right[key]) for key in left)
            require(max(hidden_errors.values()) == 0.0, "prediction excludes hidden labels and unselected actions")
            reload_rows.append({"seed": seed, "window": window, "checkpoint_sha256": file_sha(cp_path),
                                "raw_rows_checked_per_arm": 768, "forecast_errors": errors,
                                "hidden_metadata_target_unselected_action_errors": hidden_errors,
                                "original_reload_probe_rows_per_arm": 2})
            previous = file_sha(cp_path)
        print(json.dumps({"audit_progress": "completed_seed", "seed": seed}), flush=True)
    require(len(component_rows) == 125 and len(prior_rows) == 120 and prepared["optimizer_fit_count"] == 245, "total optimizer fits")
    require(len(selection_rows) == prepared["selector_count"] == 360 and sum(row["candidates_checked"] for row in selection_rows) == prepared["candidate_evaluations"] == 7560, "total selections/candidates")
    require(prepared["optimizer_failures"] == [] and prepared["confirmation_arrays_constructed"] is False and started["confirmation_arrays_constructed"] is False, "preparation status")
    require(prepared["unique_labelled_preparation_queries"] == 48640 and prepared["public_context_histories"] == 0, "preparation information counts")
    execution_path = run_dir / "execution/selection_registered_prepare_001_COMPLETED.json"
    execution = read(execution_path)
    execution_start = read(run_dir / "execution/selection_registered_prepare_001_STARTED.json")
    expected_command = ["python", "-m", "experiments.analytic_event_neuron.round5.selection_study", "prepare", "--run-dir", run_dir.relative_to(REPO).as_posix()]
    require(execution["returncode"] == 0 and execution["command"] == execution_start["command"] == expected_command, "actual preparation invocation")
    require(execution["full_invocation_scope"] and execution["nested_component_times_must_not_be_added"] and execution["wall_ns"] >= prepared["wall_ns"] > 0, "full invocation costs")
    log_rows = [json.loads(line) for line in (run_dir / execution["log"]).read_text().splitlines()]
    require(len(log_rows) == 61 and {(row["seed"], row["window"]) for row in log_rows[:-1]} == set(receipts), "actual completed scope log")
    require(all(row["phase"] == "prepare" and row["profile"] == "registered" for row in log_rows[:-1]), "logged phase/profile")
    for key, value in log_rows[-1].items():
        require(prepared[key] == value, "logged summary: " + key)
    require(study.verify_prepared(run_dir) == prepared, "actual reviewed verification API")
    require(file_sha(prepared_path) == EXPECTED_PREPARED and {path: file_sha(prepared_root / path) for path in actual} == actual, "audit preserved raw/model bytes")
    require(all(value == 0 for value in FORBIDDEN_CALLS.values()), "no forbidden execution")
    run_files = {path.relative_to(run_dir).as_posix(): {"sha256": file_sha(path), "bytes": path.stat().st_size} for path in run_dir.rglob("*") if path.is_file()}
    return {"schema": "hepta.analytic-event.round5.independent-prepared-review.v1",
            "reviewed_utc": datetime.now(timezone.utc).isoformat(), "reviewer": "r4_remote_recovery",
            "verdict": "PASS_COMPLETE_REGISTERED_PREPARATION_READY_FOR_ROOT_FREEZE",
            "blocking_findings": [], "review_does_not_authorize_or_execute_confirmation": True,
            "run_dir": run_dir.relative_to(REPO).as_posix(), "prepared_sha256": EXPECTED_PREPARED,
            "registration_sha256": EXPECTED_REGISTRATION, "source_review_sha256": EXPECTED_SOURCE_REVIEW,
            "audit_code_sha256": file_sha(__file__), "sources": {"inherited_count": 102, "new_count": 5, "all_sources_digest": object_sha(sources), "new_source_hashes": EXPECTED_NEW_SOURCES},
            "environment": {"start_prepared_current_equal": True, "snapshot_sha256": object_sha(prepared["environment"]),
                            **{key: prepared["environment"][key] for key in ("python", "implementation", "executable", "numpy", "scipy", "platform", "machine", "thread_environment")}},
            "counts": {"raw_datasets": 185, "raw_unique_trajectories": 48640, "unique_training_trajectories": 17920,
                       "unique_development_trajectories": 30720, "model_json_artifacts": 65, "prepared_artifacts": 250,
                       "component_fits": 125, "prior_fits": 120, "optimizer_fits": 245, "selectors": 360,
                       "candidate_evaluations": 7560, "checkpoints": 60, "arm_window_reload_checks": 480,
                       "saved_query_rows_checked_per_arm_window": 768, "planned_confirmation_identities_only": 65},
            "all_raw_data": data_rows, "component_fit_checks": component_rows, "prior_fit_checks": prior_rows,
            "selector_checks": selection_rows, "checkpoint_checks": reload_rows,
            "largest_candidate_score_replay_error": max(row["max_independent_score_error"] for row in selection_rows),
            "largest_prior_objective_gradient_replay_error": max(row["max_objective_or_gradient_replay_error"] for row in prior_rows),
            "inherited_prior_bound_solutions": sum(row["at_inherited_logit_bound"] for row in prior_rows),
            "run_inventory": {"files": len(run_files), "bytes": sum(row["bytes"] for row in run_files.values()), "manifest_sha256": object_sha(run_files)},
            "execution": {"receipt_sha256": file_sha(execution_path), "full_invocation": execution,
                          "preparation_wall_ns": prepared["wall_ns"], "preparation_parent_cpu_ns": prepared["parent_cpu_ns"],
                          "shared_fits_counted_once": True, "nested_timings_not_added": True},
            "audit_operations": {"generation_or_optimization": FORBIDDEN_CALLS, "confirmation_arrays_constructed": False,
                                 "raw_arrays_regenerated": False, "native_execution": False, "reviewed_artifact_mutations": False},
            "limitations": [
                "Preparation/development losses are not confirmation results. No range benefit, retention/calibration gate, downstream action value or production promotion is inferred.",
                "The raw saved arrays are audited by exact file hashes, metadata, shapes, namespace-derived seed identifiers and disjoint row IDs; the stochastic data generator is deliberately not rerun.",
                "Component fit receipts preserve initial/final parameters and scalar objective evaluation traces, not every intermediate optimizer parameter vector. Initial/final objectives are recomputed; the complete component search trajectory is not refitted. Evaluation counts are not iteration counts.",
                "Prior logits may reach the inherited optimization bounds [-6,6]. These remain legitimate bounded optimizer solutions and are explicitly counted; no unbounded-optimum claim is made.",
                "The prior-density reference and selector-score formulas are separately implemented here, while inherited filtering/public-likelihood functions remain shared, source-pinned dependencies. This audit is distinct from an entirely independent implementation of the diffusion solver.",
                "Original checkpoint reload probes used two training rows per arm. This audit checks 768 saved query rows per arm/window and hidden-input perturbations, adding no new independent trajectories or out-of-sample evidence.",
                "Numerical library build/version and declared thread environment match exactly. Unset thread variables do not establish an effective thread-count limit or hardware benchmark reproducibility.",
                "Complete component-fit timers include inherited training-history assembly; inherited prior-fit timers begin after component-cache construction. Full preparation and command timers include their nested operations and must not be added to component timers. Financial cost and native energy remain unmeasured.",
                "This is a local pre-freeze artifact review. Root must create and verify its own freeze and durable-publication receipts before any authorized confirmation; this review does neither."
            ]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=REPO / PREFIX / "evidence/selection_registered_001")
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("PREPARED_REVIEW.json"))
    args = parser.parse_args()
    require(not args.output.exists(), "do not overwrite an existing independent audit")
    result = audit(args.run_dir.resolve())
    result["audit_measurement"] = {"wall_ns": time.perf_counter_ns() - AUDIT_WALL_STARTED,
                                   "parent_cpu_ns": time.process_time_ns() - AUDIT_CPU_STARTED,
                                   "checks_completed": CHECKS,
                                   "scope": "This audit process after its initial time import, including scientific imports, all source/data/fit/selector/checkpoint checks and final identity recheck; excludes interpreter startup and final review JSON write."}
    with args.output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"verdict": result["verdict"], "review_sha256": file_sha(args.output), "audit_measurement": result["audit_measurement"]}), flush=True)


if __name__ == "__main__":
    main()
