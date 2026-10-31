"""Registered train/freeze/confirmation study of exact conditional mixtures."""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from .. import learners, retention, statistics, task
from . import calibration as cal

ARMS = ("frozen", "replay", "mixture_zero", "moment_zero", "mixture_context", "moment_context",
        "same_weight_moment", "mixture_classical", "mixture_q24", "mixture_q24_classical")
SOURCE_PATHS = tuple("experiments/analytic_event_neuron/" + name for name in (
    "round4/calibration.py", "round4/calibration_study.py", "round3/calibration.py",
    "round2/adaptation.py", "analytic.py", "learners.py", "task.py", "retention.py", "statistics.py"))


def registration():
    return {"schema": "hepta.analytic-event.calibration-registration.v4", "phase": "confirmation",
            "seeds": [1213, 1427, 1619, 1823, 2017], "windows": ["gaussian", "drift_shift"] * 6,
            "anchor_rows": 512, "training_rows": 256, "replay_rows": 256,
            "development_rows_per_domain": 256, "confirmation_rows_per_domain": 256,
            "public_context_histories_per_block": 8, "train_seed_offset": 400000000,
            "confirmation_seed_offset": 500000000,
            "seed_rule": "offset+10000*seed+100*window+code; newtrain1,olddev2,newdev3,newconfirm4; window99 anchor1/oldconfirm5; context=correspondingqueryseed+50",
            "arms": list(ARMS), "selection_candidates_per_trained_head": 21,
            "selector": "old-dev exact density NLL difference mean+1.645 pairedSE<=.02; minimize new-dev densityNLL; anchor feasible",
            "old_nll_margin": .02, "new_nll_improvement_min": .005,
            "calibration_ece_max": .04, "calibration_coverage_min": .92, "calibration_coverage_max": .98,
            "primary_profiles": ["mixture_zero", "mixture_context"], "primary_family_size": 2,
            "bootstrap_replicates": 4000, "bootstrap_seed": 28102844,
            "primary_interval_alpha": .025, "diagnostic_interval_alpha": .05,
            "same_query_and_context_information_except_declared_zero_context_ablation": True,
            "matched_train_and_development_labels": True, "query_regime_window_or_targets_are_not_features": True,
            "context_block_unit": "8 distinct prior public-only trajectories and one query; shared regime, independent conditional paths",
            "old_confirm_blocks_reused_across_windows": True,
            "pointwise_retention_guarantee": False, "confirmation_generated_after_freeze_only": True}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, document):
    Path(path).write_text(json.dumps(document, sort_keys=True, indent=2, allow_nan=False) + "\n")


def load(path):
    with np.load(path, allow_pickle=False) as archive:
        return {key: archive[key].item() if archive[key].ndim == 0 else archive[key] for key in archive.files}


def array_error(left, right):
    left, right = np.asarray(left), np.asarray(right)
    finite = np.isfinite(left)
    if (left.shape != right.shape or not np.array_equal(finite, np.isfinite(right))
            or not np.array_equal(left[~finite], right[~finite])):
        raise ValueError("Forecast arrays disagree on nonfinite structural entries")
    return float(np.max(np.abs(left[finite] - right[finite]), initial=0.))


def data_seed(reg, seed, window, code, confirmation=False):
    return reg["confirmation_seed_offset" if confirmation else "train_seed_offset"] + 10000 * seed + 100 * window + code


def public_context(seed, rows, law, count=8):
    """Prior paths expose only public sensor histories; latent targets discarded."""
    generated = task.build_dataset(seed, rows * count, "prior_public_context", law)
    history = task.history(generated)
    return {key: history[key] for key in ("obs", "times", "mask", "occupied", "obs_var")}


def subset(data, count):
    n = len(data["ids"])
    return {key: value[:count] if isinstance(value, np.ndarray) and value.ndim and len(value) == n else value
            for key, value in data.items()}


def single_model(filter_model, context_count=8):
    model = cal.make_model(filter_model, filter_model, context_count)
    model["prior"] = 0.
    return model


def select_replay(anchor, replay, old, new):
    targets = [task.targets(data)[:, 1:] for data in (old, new)]
    histories = [task.history(data) for data in (old, new)]
    m0, v0 = learners.predict(anchor, histories[0])
    base = .5 * (np.log(2 * np.pi * v0[:, 1:]) + (targets[0] - m0[:, 1:]) ** 2 / v0[:, 1:])
    rows, models = [], []
    for strength in cal.STRENGTHS:
        model = deepcopy(replay)
        model["parameters"] = ((1 - strength) * np.asarray(anchor["parameters"])
                               + strength * np.asarray(replay["parameters"])).tolist()
        losses = []
        for history, target in zip(histories, targets):
            mean, variance = learners.predict(model, history)
            losses.append(.5 * (np.log(2 * np.pi * variance[:, 1:]) + (target - mean[:, 1:]) ** 2 / variance[:, 1:]))
        delta = (losses[0] - base).mean(1)
        upper = float(delta.mean() + 1.645 * delta.std(ddof=1) / np.sqrt(len(delta)))
        rows.append({"strength": strength, "old_nll_change": float(delta.mean()),
                     "old_upper_heuristic": upper, "new_nll": float(losses[1].mean()), "eligible": upper <= .02})
        models.append(single_model(model))
    chosen = min((i for i, row in enumerate(rows) if row["eligible"]), key=lambda i: (rows[i]["new_nll"], i))
    return models[chosen], {"candidates": rows, "selected_index": chosen, "development_labelled_queries": len(old["ids"]) + len(new["ids"])}


def prepare(run_dir):
    run_dir, reg = Path(run_dir), registration()
    destination = run_dir / "calibration_prepared"
    destination.mkdir(parents=True, exist_ok=False)
    repo = Path(__file__).resolve().parents[3]
    source_hashes = {path: sha(repo / path) for path in SOURCE_PATHS}
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    receipts = []
    for seed in reg["seeds"]:
        root = destination / f"seed_{seed}"
        root.mkdir()
        original_seed = data_seed(reg, seed, 99, 1)
        original = task.build_dataset(original_seed, reg["anchor_rows"], "train")
        old_train = subset(original, reg["replay_rows"])
        old_context = public_context(original_seed + 50, reg["replay_rows"], "gaussian")
        np.savez_compressed(root / "ORIGINAL_TRAIN.npz", **original)
        np.savez_compressed(root / "OLD_TRAIN_CONTEXT.npz", **old_context)
        initial = {"kind": "filter", "parameters": [0., .4, 1.4], "planning_q": .4, "planning_noise_scale": 1.4}
        anchor, anchor_fit = retention._adapt(initial, [original])
        write(root / "ANCHOR.json", {"model": anchor, "fit": anchor_fit})
        online, replay, previous = deepcopy(anchor), deepcopy(anchor), None
        for window, law in enumerate(reg["windows"]):
            prefix = f"window_{window:02d}"
            datasets, contexts = {}, {}
            for name, code, rows, split, environment in (
                ("TRAIN", 1, reg["training_rows"], "retention_train", law),
                ("OLD_DEV", 2, reg["development_rows_per_domain"], "calibration_development", "gaussian"),
                ("NEW_DEV", 3, reg["development_rows_per_domain"], "calibration_development", law)):
                seed_value = data_seed(reg, seed, window, code)
                datasets[name] = task.build_dataset(seed_value, rows, split, environment)
                contexts[name] = public_context(seed_value + 50, rows, environment)
                np.savez_compressed(root / (prefix + "_" + name + ".npz"), **datasets[name])
                np.savez_compressed(root / (prefix + "_" + name + "_CONTEXT.npz"), **contexts[name])
            online, online_fit = retention._adapt(online, [datasets["TRAIN"]])
            replay, replay_fit = retention._adapt(replay, [old_train, datasets["TRAIN"]])
            models = {"frozen": single_model(anchor, 0)}
            models["replay"], replay_selection = select_replay(anchor, replay, datasets["OLD_DEV"], datasets["NEW_DEV"])
            fit_receipts, selections = {}, {"replay": replay_selection}
            for name, count, projection in (("mixture_zero", 0, False), ("moment_zero", 0, True),
                                             ("mixture_context", 8, False), ("moment_context", 8, True)):
                candidate = cal.make_model(anchor, online, count, projection)
                candidate, fit_receipts[name] = cal.fit_prior(candidate, [(old_train, old_context), (datasets["TRAIN"], contexts["TRAIN"])])
                models[name], selections[name] = cal.select_model(candidate, datasets["OLD_DEV"], datasets["NEW_DEV"],
                                                                  contexts["OLD_DEV"], contexts["NEW_DEV"])
            models["same_weight_moment"] = {**deepcopy(models["mixture_context"]), "projection": True}
            models["mixture_classical"] = deepcopy(models["mixture_context"])
            models["mixture_q24"] = {**deepcopy(models["mixture_context"]), "parameter_q24": True}
            models["mixture_q24_classical"] = deepcopy(models["mixture_q24"])
            checkpoint = {"seed": seed, "window": window, "training_environment": law, "models": models,
                          "previous_checkpoint_sha256": previous, "holdout_used": False,
                          "component_training": {"online": online_fit, "replay": replay_fit},
                          "prior_training": fit_receipts, "selection": selections,
                          "query_time_hidden_regime_input": False,
                          "matched_label_budget": {"shared_initial_anchor": reg["anchor_rows"], "old_training": reg["replay_rows"],
                                                   "new_training": reg["training_rows"], "old_development": reg["development_rows_per_domain"],
                                                   "new_development": reg["development_rows_per_domain"]},
                          "online_state": online, "replay_state": replay}
            path = root / (prefix + "_CHECKPOINT.json")
            write(path, checkpoint)
            restored = json.loads(path.read_text())
            probe = task.history(subset(datasets["TRAIN"], 2))
            context_probe = {key: value[:16] for key, value in contexts["TRAIN"].items()}
            reload_errors = {}
            for name in ARMS:
                before = cal.predict_distribution(models[name], probe, context_probe)
                after = cal.predict_distribution(restored["models"][name], probe, context_probe)
                reload_errors[name] = max(array_error(before[key], after[key]) for key in before)
                if reload_errors[name] != 0:
                    raise AssertionError("Checkpoint reload altered a forecast")
            online, replay, previous = restored["online_state"], restored["replay_state"], sha(path)
            receipts.append({"seed": seed, "window": window, "checkpoint_sha256": previous, "reload_errors": reload_errors,
                             "component_parameter_changes": {"online": float(np.linalg.norm(np.asarray(online_fit["final_parameters"]) - online_fit["initial_parameters"])),
                                                             "replay": float(np.linalg.norm(np.asarray(replay_fit["final_parameters"]) - replay_fit["initial_parameters"]))},
                             "prior_logit_changes": {name: fit_receipts[name]["prior_logit_change"] for name in fit_receipts}})
            print(json.dumps({"phase": "calibration_prepare", "seed": seed, "window": window}), flush=True)
    if source_hashes != {path: sha(repo / path) for path in SOURCE_PATHS}:
        raise RuntimeError("Scientific source changed during preparation; retain this attempt and prepare a new registered artifact")
    prepared = {"schema": "hepta.analytic-event.calibration-prepared.v4", "registration": reg,
                "source_sha256": source_hashes,
                "artifacts_sha256": {path.relative_to(destination).as_posix(): sha(path) for path in sorted(destination.rglob("*")) if path.is_file()},
                "checkpoint_receipts": receipts, "holdouts_constructed": False,
                "preparation_wall_ns": time.perf_counter_ns() - started, "preparation_parent_cpu_ns": time.process_time_ns() - cpu}
    write(destination / "PREPARED.json", prepared)
    return prepared


def verify_prepared(run_dir, freeze_path):
    run_dir = Path(run_dir).resolve()
    destination = run_dir / "calibration_prepared"
    prepared = json.loads((destination / "PREPARED.json").read_text())
    freeze = json.loads(Path(freeze_path).read_text())
    repo = Path(__file__).resolve().parents[3]
    if prepared["registration"] != registration():
        raise ValueError("Prepared registration changed")
    for path, digest in prepared["source_sha256"].items():
        if sha(repo / path) != digest or freeze["sources_sha256"].get(path) != digest:
            raise ValueError("Source lacks exact freeze binding: " + path)
    for name in ["PREPARED.json", *prepared["artifacts_sha256"]]:
        path = destination / name
        digest = sha(path)
        if (name != "PREPARED.json" and digest != prepared["artifacts_sha256"][name]) or freeze["artifacts_sha256"].get(path.relative_to(run_dir).as_posix()) != digest:
            raise ValueError("Prepared artifact lacks exact freeze binding: " + name)
    return prepared


def confirm(run_dir, freeze_path):
    run_dir = Path(run_dir)
    prepared = verify_prepared(run_dir, freeze_path)
    reg, destination = prepared["registration"], run_dir / "calibration_confirmation"
    destination.mkdir(exist_ok=False)
    records, started, cpu = [], time.perf_counter_ns(), time.process_time_ns()
    equivalence = {"fp64": 0., "q24": 0.}
    for seed in reg["seeds"]:
        old_seed = data_seed(reg, seed, 99, 5, True)
        old = task.build_dataset(old_seed, reg["confirmation_rows_per_domain"], "calibration_old_confirmation")
        old_context = public_context(old_seed + 50, reg["confirmation_rows_per_domain"], "gaussian")
        np.savez_compressed(destination / f"seed_{seed}_OLD.npz", **old)
        np.savez_compressed(destination / f"seed_{seed}_OLD_CONTEXT.npz", **old_context)
        for window, law in enumerate(reg["windows"]):
            prefix = f"seed_{seed}_window_{window:02d}"
            checkpoint = json.loads((run_dir / "calibration_prepared" / f"seed_{seed}" / f"window_{window:02d}_CHECKPOINT.json").read_text())
            new_seed = data_seed(reg, seed, window, 4, True)
            new = task.build_dataset(new_seed, reg["confirmation_rows_per_domain"], "calibration_new_confirmation", law)
            new_context = public_context(new_seed + 50, reg["confirmation_rows_per_domain"], law)
            np.savez_compressed(destination / (prefix + "_NEW.npz"), **new)
            np.savez_compressed(destination / (prefix + "_NEW_CONTEXT.npz"), **new_context)
            archive, summaries, distributions = {}, {}, {}
            arm_costs = {}
            for name in ARMS:
                summaries[name], distributions[name] = {}, {}
                started_arm, cpu_arm = time.perf_counter_ns(), time.process_time_ns()
                for domain, data, context in (("old", old, old_context), ("new", new, new_context)):
                    dist = cal.predict_distribution(checkpoint["models"][name], task.history(data), context,
                                                    classical=name in ("mixture_classical", "mixture_q24_classical"))
                    arrays, summaries[name][domain] = cal.scores(dist, data)
                    distributions[name][domain] = dist
                    archive.update({name + "__" + domain + "__" + key: value for key, value in arrays.items()})
                arm_costs[name] = {"wall_ns": time.perf_counter_ns() - started_arm, "parent_cpu_ns": time.process_time_ns() - cpu_arm}
            for domain in ("old", "new"):
                for standard, classical, label in (("mixture_context", "mixture_classical", "fp64"), ("mixture_q24", "mixture_q24_classical", "q24")):
                    for key in distributions[standard][domain]:
                        equivalence[label] = max(equivalence[label], array_error(distributions[standard][domain][key], distributions[classical][domain][key]))
            archive_path = destination / (prefix + "_SCORES.npz")
            np.savez_compressed(archive_path, **archive)
            record = {"seed": seed, "window": window, "environment": law, "summary": summaries, "costs": arm_costs,
                      "score_path": archive_path.name, "score_sha256": sha(archive_path),
                      "query_dataset_digests": {"old": task.dataset_digest(old), "new": task.dataset_digest(new)}}
            write(destination / (prefix + ".json"), record)
            records.append(record)
            print(json.dumps({"phase": "calibration_confirm", "seed": seed, "window": window}), flush=True)
    index = {"schema": "hepta.analytic-event.calibration-confirmation.v4", "registration": reg, "records": records,
             "prepared_sha256": sha(run_dir / "calibration_prepared" / "PREPARED.json"), "dense_equivalence_max_abs": equivalence,
             "confirmation_wall_ns": time.perf_counter_ns() - started, "confirmation_parent_cpu_ns": time.process_time_ns() - cpu,
             "unique_query_blocks": len(reg["seeds"]) * (len(reg["windows"]) + 1) * reg["confirmation_rows_per_domain"],
             "prior_public_histories_per_block": 8, "horizons_per_query": 3, "old_blocks_reused_across_windows": True}
    write(destination / "INDEX.json", index)
    return summarize(run_dir)


def interval(values, replicates, seed, alpha):
    values = np.asarray(values)
    nseeds, nwindows, nrows = values.shape
    rng, boots = np.random.default_rng(seed), []
    for start in range(0, replicates, 100):
        count = min(100, replicates - start)
        seeds = rng.integers(nseeds, size=(count, nseeds, 1, 1))
        rows = rng.integers(nrows, size=(count, nseeds, nwindows, nrows))
        windows = np.arange(nwindows)[None, None, :, None]
        boots.extend(values[seeds, windows, rows].mean((1, 2, 3)).tolist())
    return {"mean_difference": float(values.mean()), "interval": np.quantile(boots, [alpha / 2, 1 - alpha / 2]).tolist(),
            "per_seed_mean": values.mean((1, 2)).tolist(), "alpha": alpha, "replicates": replicates,
            "method": "resample training seeds then independent whole context/query blocks within each fixed window"}


def summarize(run_dir):
    destination = Path(run_dir) / "calibration_confirmation"
    index = json.loads((destination / "INDEX.json").read_text())
    reg = index["registration"]
    scopes = {(record["seed"], record["window"]): load(destination / record["score_path"]) for record in index["records"]}
    result = {"schema": "hepta.analytic-event.calibration-results.v4", "registration": reg, "arms": {},
              "equivalence": index["dense_equivalence_max_abs"], "unique_query_blocks": index["unique_query_blocks"],
              "unique_public_context_histories": index["unique_query_blocks"] * 8,
              "independent_sampling_unit": "a full public-context/query block; old blocks reused over windows",
              "context_task_is_a_distinct_information_experiment": True, "mechanism_comparisons": {}}
    for arm_index, arm in enumerate(ARMS):
        old, new, final, shifted_p, shifted_y, shifted_cov = [], [], [], [], [], []
        for seed in reg["seeds"]:
            old_seed, new_seed = [], []
            for window, law in enumerate(reg["windows"]):
                values = scopes[seed, window]
                old_seed.append(values[arm + "__old__density_nll"] - values["frozen__old__density_nll"])
                new_seed.append(values[arm + "__new__density_nll"] - values["frozen__new__density_nll"])
                if law == "drift_shift":
                    shifted_p.append(values[arm + "__new__probabilities"])
                    shifted_y.append(values[arm + "__new__labels"])
                    shifted_cov.append(values[arm + "__new__coverage95"])
            old.append(old_seed)
            new.append(new_seed)
            final.append(new_seed[-1:])
        old, new = np.asarray(old), np.asarray(new)
        alpha = reg["primary_interval_alpha"] if arm in reg["primary_profiles"] else reg["diagnostic_interval_alpha"]
        final_interval = interval(final, reg["bootstrap_replicates"], reg["bootstrap_seed"] + arm_index, alpha)
        ece = statistics.calibration(np.concatenate(shifted_p), np.concatenate(shifted_y))["classwise_ece"]
        coverage = float(np.concatenate(shifted_cov).mean())
        retention_ok = bool(old.mean((0, 2)).max() <= .02 and np.mean(final) <= 0)
        efficacy = bool(retention_ok and np.mean(final) <= -.005 and final_interval["interval"][1] < 0
                        and max(final_interval["per_seed_mean"]) < 0)
        calibration_ok = bool(ece <= .04 and .92 <= coverage <= .98)
        result["arms"][arm] = {"worst_cross_seed_mean_old_nll_increase": float(old.mean((0, 2)).max()),
            "worst_single_seed_window_old_nll_increase": float(old.mean(2).max()),
            "old_nll_increase_by_window": old.mean((0, 2)).tolist(), "final_new_nll_difference": final_interval,
            "pooled_shifted_classwise_ece": ece, "pooled_shifted_coverage95": coverage,
            "passes_retention_gate": retention_ok, "passes_nll_efficacy_gate": efficacy,
            "passes_calibration_gate": calibration_ok, "passes_joint_empirical_gate": bool(efficacy and calibration_ok),
            "pointwise_retention_certificate": False}
    for left, right in (("mixture_context", "mixture_zero"), ("mixture_context", "moment_context"),
                        ("mixture_context", "same_weight_moment"), ("mixture_zero", "moment_zero"),
                        ("mixture_context", "replay"), ("mixture_q24", "mixture_context")):
        delta = [[scopes[seed, window][left + "__new__density_nll"] - scopes[seed, window][right + "__new__density_nll"]
                  for window, law in enumerate(reg["windows"]) if law == "drift_shift"] for seed in reg["seeds"]]
        result["mechanism_comparisons"][left + "_minus_" + right] = interval(delta, reg["bootstrap_replicates"], reg["bootstrap_seed"] + 100, .05)
    write(destination / "RESULTS.json", result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("prepare", "confirm", "summary"))
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--freeze")
    args = parser.parse_args()
    if args.phase == "prepare":
        prepare(args.run_dir)
    elif args.phase == "confirm":
        if not args.freeze:
            parser.error("Confirmation requires --freeze")
        confirm(args.run_dir, args.freeze)
    else:
        summarize(args.run_dir)


if __name__ == "__main__":
    main()
