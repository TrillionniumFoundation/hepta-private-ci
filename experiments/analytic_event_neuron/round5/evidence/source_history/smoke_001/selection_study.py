"""Fresh zero-context study of development candidate range, with a freeze gate."""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from .. import retention, statistics, task
from ..round4 import calibration as cal, calibration_study as prior_study
from .selection_math import select_gaussian, select_prior, single_model, zero_context


REPO = Path(__file__).resolve().parents[3]
PREFIX = "experiments/analytic_event_neuron/round5/"
OLD_FREEZE = REPO / "experiments/analytic_event_neuron/round4/evidence/FREEZE.json"
OLD_FREEZE_SHA = "e7fd9c474e0c4a0ad56ad910a643ab84970da430600e6f8caccae2849c824c2d"
ARMS = ("frozen", "replay_legacy", "gaussian_full_range", "mixture_legacy", "mixture_full_range",
        "moment_legacy", "moment_full_range", "same_weight_moment_full")
PRIMARY = (("mixture_full_range", "mixture_legacy"), ("moment_full_range", "moment_legacy"))


def registration(profile="registered"):
    if profile not in ("registered", "development_smoke"):
        raise ValueError("Unknown study profile")
    smoke = profile == "development_smoke"
    return {"schema": "hepta.analytic-event.selection-registration.v5", "profile": profile,
            "namespace": "hepta.aen.r5.selection." + ("development-smoke.v1" if smoke else "confirmation-study.v1"),
            "seeds": [99001] if smoke else [2131, 2377, 2539, 2791, 3011],
            "windows": ["gaussian", "drift_shift"] * (1 if smoke else 6),
            "anchor_rows": 64 if smoke else 512, "replay_rows": 32 if smoke else 256,
            "training_rows": 32 if smoke else 256, "development_rows_per_domain": 32 if smoke else 256,
            "confirmation_rows_per_domain": 0 if smoke else 256, "public_context_histories_per_query": 0,
            "seed_rule": "first8 SHA256 bytes of namespace|phase|seed|window|role, masked to53bits; explicit schedule collision checked",
            "arms": list(ARMS), "candidates_per_selector": 21, "selectors_per_window": 6,
            "primary_comparisons": [list(pair) for pair in PRIMARY], "primary_family_size": 2,
            "primary_interval_alpha": .025, "diagnostic_interval_alpha": .05,
            "primary_endpoint": "mean new-domain density NLL difference over the six fixed drift windows",
            "bootstrap_replicates": 4000, "bootstrap_seed": 28102855,
            "selector": "old-dev mean NLL increase +1.645 pairedSE<=.02; minimize new-dev NLL; index tie break",
            "old_nll_margin": .02, "final_new_nll_improvement_min": .005,
            "calibration_ece_max": .04, "coverage95_range": [.92, .98],
            "profile_gates_use_descriptive_anchor_intervals": True,
            "profile_gates_are_not_familywise_or_pointwise_certificates": True,
            "full_range_prior_grid": "linspace(0,1,21)", "legacy_prior_grid": "linspace(0,fit_prior,21)",
            "candidate_sets_not_assumed_nested": True, "architectures_and_arithmetic_costs_not_identical": True,
            "confirmation_constructed_after_source_and_prepared_freeze_only": True,
            "old_confirmation_rows_reused_across_windows": True,
            "independent_unit": "one query trajectory; three correlated future horizons stay together",
            "original_round4_evidence_reconstructed": False, "native_runtime_or_utility_claim": False}


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def object_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def write(path, document):
    with Path(path).open("x") as stream:
        json.dump(document, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def seed_value(reg, phase, seed, window, role):
    if phase not in ("prepare", "confirmation") or (phase == "confirmation" and reg["profile"] != "registered"):
        raise ValueError("Development-only profiles cannot address confirmation identities")
    key = "|".join(map(str, (reg["namespace"], phase, seed, window, role)))
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big") & ((1 << 53) - 1)


def seed_schedule(reg):
    rows = []
    for seed in reg["seeds"]:
        scopes = [("prepare", -1, "anchor")]
        scopes += [("prepare", window, role) for window in range(len(reg["windows"])) for role in ("train", "old_dev", "new_dev")]
        if reg["profile"] == "registered":
            scopes += [("confirmation", -1, "old")]
            scopes += [("confirmation", window, "new") for window in range(len(reg["windows"]))]
        rows += [{"phase": phase, "seed": seed, "window": window, "role": role,
                  "generator_seed": seed_value(reg, phase, seed, window, role)} for phase, window, role in scopes]
    if len({row["generator_seed"] for row in rows}) != len(rows):
        raise ValueError("The planned generator identities collide")
    return rows


def source_snapshot():
    if sha(OLD_FREEZE) != OLD_FREEZE_SHA:
        raise ValueError("The inherited Round4 source identity is not the pinned freeze")
    old = json.loads(OLD_FREEZE.read_text())["sources_sha256"]
    if any(sha(REPO / path) != digest for path, digest in old.items()):
        raise ValueError("An inherited frozen scientific source changed")
    extra = [PREFIX + name for name in ("selection_study.py", "selection_math.py", "test_selection.py", "SELECTION_CONTRACT.md", "__init__.py")]
    return {**old, **{path: sha(REPO / path) for path in extra}}


def prepare(run_dir, profile="registered"):
    run_dir, reg = Path(run_dir), registration(profile)
    run_dir.mkdir(parents=True, exist_ok=True)
    destination = run_dir / "prepared"
    destination.mkdir(exist_ok=False)
    sources, schedule = source_snapshot(), seed_schedule(reg)
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    write(run_dir / "PREPARATION_STARTED.json", {"created_utc": datetime.now(timezone.utc).isoformat(),
          "registration": reg, "registration_sha256": object_sha(reg), "sources_sha256": sources,
          "planned_seed_schedule": schedule, "confirmation_arrays_constructed": False})
    receipts, failures = [], []
    try:
        for seed in reg["seeds"]:
            root = destination / f"seed_{seed}"
            root.mkdir()
            original = task.build_dataset(seed_value(reg, "prepare", seed, -1, "anchor"), reg["anchor_rows"], "train")
            np.savez_compressed(root / "ORIGINAL_TRAIN.npz", **original)
            old_train = prior_study.subset(original, reg["replay_rows"])
            initial = {"kind": "filter", "parameters": [0., .4, 1.4], "planning_q": .4, "planning_noise_scale": 1.4}
            anchor, anchor_fit = retention._adapt(initial, [original])
            write(root / "ANCHOR.json", {"model": anchor, "fit": anchor_fit})
            if not anchor_fit["optimizer_success"]:
                failures.append({"seed": seed, "window": -1, "fit": "anchor"})
            online, replay, previous = deepcopy(anchor), deepcopy(anchor), None
            for window, law in enumerate(reg["windows"]):
                prefix, data = f"window_{window:02d}", {}
                for role, rows, split, domain in (("train", reg["training_rows"], "retention_train", law),
                         ("old_dev", reg["development_rows_per_domain"], "calibration_development", "gaussian"),
                         ("new_dev", reg["development_rows_per_domain"], "calibration_development", law)):
                    data[role] = task.build_dataset(seed_value(reg, "prepare", seed, window, role), rows, split, domain)
                    np.savez_compressed(root / (prefix + "_" + role.upper() + ".npz"), **data[role])
                online, online_fit = retention._adapt(online, [data["train"]])
                replay, replay_fit = retention._adapt(replay, [old_train, data["train"]])
                models, selections, fits = {"frozen": single_model(anchor)}, {}, {"online": online_fit, "replay": replay_fit}
                for arm, endpoint, name in (("replay_legacy", replay, "balanced_replay"),
                                             ("gaussian_full_range", online, "current_only_online")):
                    models[arm], selections[arm] = select_gaussian(anchor, endpoint, data["old_dev"], data["new_dev"], name)
                for family, projection in (("mixture", False), ("moment", True)):
                    candidate = cal.make_model(anchor, online, context_count=0, projection=projection)
                    candidate, fits[family + "_prior"] = cal.fit_prior(candidate, [(old_train, zero_context()), (data["train"], zero_context())])
                    for grid in ("legacy", "full_range"):
                        arm = family + "_" + grid
                        models[arm], selections[arm] = select_prior(candidate, data["old_dev"], data["new_dev"], grid)
                models["same_weight_moment_full"] = {**deepcopy(models["mixture_full_range"]), "projection": True}
                failures += [{"seed": seed, "window": window, "fit": name} for name, fit in fits.items() if not fit["optimizer_success"]]
                checkpoint = {"seed": seed, "window": window, "training_environment": law, "models": models,
                              "component_training": {name: fits[name] for name in ("online", "replay")},
                              "prior_training": {name: fits[name + "_prior"] for name in ("mixture", "moment")},
                              "selection": selections, "online_state": online, "replay_state": replay,
                              "previous_checkpoint_sha256": previous, "holdout_used": False,
                              "public_context_histories": 0, "extra_model_features": [],
                              "training_dataset_digests": {"old": task.dataset_digest(old_train), "new": task.dataset_digest(data["train"])}}
                path = root / (prefix + "_CHECKPOINT.json")
                write(path, checkpoint)
                restored = json.loads(path.read_text())
                probe = task.history(prior_study.subset(data["train"], 2))
                errors = {name: max(prior_study.array_error(a[key], b[key]) for key in a)
                          for name in ARMS for a, b in [(cal.predict_distribution(models[name], probe), cal.predict_distribution(restored["models"][name], probe))]}
                if max(errors.values()) != 0:
                    raise AssertionError("Checkpoint reload changed a distribution")
                previous = sha(path)
                online, replay = restored["online_state"], restored["replay_state"]
                receipts.append({"seed": seed, "window": window, "checkpoint_sha256": previous, "reload_errors": errors,
                                 "component_parameter_changes": {name: float(np.linalg.norm(np.asarray(fits[name]["final_parameters"]) - fits[name]["initial_parameters"])) for name in ("online", "replay")},
                                 "prior_logit_changes": {name: fits[name + "_prior"]["prior_logit_change"] for name in ("mixture", "moment")}})
                print(json.dumps({"phase": "prepare", "profile": profile, "seed": seed, "window": window}), flush=True)
        if sources != source_snapshot():
            raise ValueError("Source changed during preparation; retain this attempt")
        prepared = {"schema": "hepta.analytic-event.selection-prepared.v5", "registration": reg,
                    "registration_sha256": object_sha(reg), "sources_sha256": sources, "planned_seed_schedule": schedule,
                    "artifacts_sha256": {p.relative_to(destination).as_posix(): sha(p) for p in sorted(destination.rglob("*")) if p.is_file()},
                    "checkpoint_receipts": receipts, "optimizer_failures": failures, "confirmation_arrays_constructed": False,
                    "optimizer_fit_count": len(reg["seeds"]) + 4 * len(receipts),
                    "selector_count": 6 * len(receipts), "candidate_evaluations": 126 * len(receipts),
                    "unique_labelled_preparation_queries": len(reg["seeds"]) * (reg["anchor_rows"] + len(reg["windows"]) * (reg["training_rows"] + 2 * reg["development_rows_per_domain"])),
                    "public_context_histories": 0, "wall_ns": time.perf_counter_ns() - started,
                    "parent_cpu_ns": time.process_time_ns() - cpu}
        write(destination / "PREPARED.json", prepared)
        return prepared
    except BaseException as error:
        write(run_dir / "PREPARATION_FAILED.json", {"error_type": type(error).__name__, "error": str(error),
              "wall_ns": time.perf_counter_ns() - started, "parent_cpu_ns": time.process_time_ns() - cpu,
              "partial_files_retained": True, "confirmation_arrays_constructed": False})
        raise


def verify_prepared(run_dir, freeze_path=None, profile="registered"):
    root = Path(run_dir) / "prepared"
    prepared = json.loads((root / "PREPARED.json").read_text())
    reg = registration(profile)
    if (prepared["registration"] != reg or prepared["registration_sha256"] != object_sha(reg)
            or prepared["optimizer_failures"] or prepared["confirmation_arrays_constructed"]):
        raise ValueError("Only the complete successful declared preparation can be verified")
    if prepared["sources_sha256"] != source_snapshot() or prepared["planned_seed_schedule"] != seed_schedule(reg):
        raise ValueError("Prepared source or planned identities changed")
    actual = {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.rglob("*")) if p.is_file() and p.name != "PREPARED.json"}
    if actual != prepared["artifacts_sha256"]:
        raise ValueError("Prepared artifact bytes or file inventory changed")
    expected = set()
    for seed in reg["seeds"]:
        expected.update(f"seed_{seed}/{name}" for name in ("ORIGINAL_TRAIN.npz", "ANCHOR.json"))
        expected.update(f"seed_{seed}/window_{window:02d}_{name}" for window in range(len(reg["windows"]))
                        for name in ("TRAIN.npz", "OLD_DEV.npz", "NEW_DEV.npz", "CHECKPOINT.json"))
    receipts = prepared["checkpoint_receipts"]
    expected_scopes = {(seed, window) for seed in reg["seeds"] for window in range(len(reg["windows"]))}
    if (set(actual) != expected or len(receipts) != len(expected_scopes)
            or {(row["seed"], row["window"]) for row in receipts} != expected_scopes
            or any(row["checkpoint_sha256"] != actual[f"seed_{row['seed']}/window_{row['window']:02d}_CHECKPOINT.json"] for row in receipts)):
        raise ValueError("The complete declared preparation roster is required")
    if freeze_path is not None:
        frozen = json.loads(Path(freeze_path).read_text())
        if (profile != "registered" or frozen.get("schema") != "hepta.analytic-event.selection-freeze.v5"
                or frozen.get("prepared_sha256") != sha(root / "PREPARED.json")
                or frozen.get("reviewed_registration_sha256") != object_sha(registration())
                or frozen.get("sources_sha256") != prepared["sources_sha256"]
                or frozen.get("artifacts_sha256") != actual
                or frozen.get("confirmation_arrays_constructed") is not False):
            raise ValueError("The exact source/prepared/registration freeze is required")
    return prepared


def freeze_prepared(run_dir, reviewed_registration_sha256):
    if reviewed_registration_sha256 != object_sha(registration()):
        raise ValueError("Explicit acknowledgement of the reviewed registration hash is required")
    if (Path(run_dir) / "confirmation").exists() or (Path(run_dir) / "CONFIRMATION_STARTED.json").exists():
        raise ValueError("A new freeze cannot be created after confirmation starts")
    prepared = verify_prepared(run_dir)
    frozen = {"schema": "hepta.analytic-event.selection-freeze.v5", "created_utc": datetime.now(timezone.utc).isoformat(),
              "reviewed_registration_sha256": reviewed_registration_sha256,
              "prepared_sha256": sha(Path(run_dir) / "prepared/PREPARED.json"),
              "sources_sha256": prepared["sources_sha256"], "artifacts_sha256": prepared["artifacts_sha256"],
              "confirmation_arrays_constructed": False, "scope": "Local source/model identity binding; remote publication or durable storage requires its own receipt."}
    write(Path(run_dir) / "FREEZE.json", frozen)
    return frozen


def confirm(run_dir, freeze_path):
    if freeze_path is None or not Path(freeze_path).is_file():
        raise ValueError("A verified source/prepared freeze is required before confirmation generation")
    prepared = verify_prepared(run_dir, freeze_path)
    reg, destination = prepared["registration"], Path(run_dir) / "confirmation"
    destination.mkdir(exist_ok=False)
    started, cpu, records = time.perf_counter_ns(), time.process_time_ns(), []
    write(Path(run_dir) / "CONFIRMATION_STARTED.json", {"created_utc": datetime.now(timezone.utc).isoformat(), "freeze_sha256": sha(freeze_path)})
    try:
        for seed in reg["seeds"]:
            old = task.build_dataset(seed_value(reg, "confirmation", seed, -1, "old"), reg["confirmation_rows_per_domain"], "selection_old_confirmation")
            np.savez_compressed(destination / f"seed_{seed}_OLD.npz", **old)
            for window, law in enumerate(reg["windows"]):
                prefix = f"seed_{seed}_window_{window:02d}"
                checkpoint = json.loads((Path(run_dir) / "prepared" / f"seed_{seed}" / f"window_{window:02d}_CHECKPOINT.json").read_text())
                new = task.build_dataset(seed_value(reg, "confirmation", seed, window, "new"), reg["confirmation_rows_per_domain"], "selection_new_confirmation", law)
                np.savez_compressed(destination / (prefix + "_NEW.npz"), **new)
                arrays, summaries, costs = {}, {}, {}
                for name in ARMS:
                    wall_arm, cpu_arm = time.perf_counter_ns(), time.process_time_ns()
                    summaries[name] = {}
                    for domain, data in (("old", old), ("new", new)):
                        distribution = cal.predict_distribution(checkpoint["models"][name], task.history(data))
                        scores, summaries[name][domain] = cal.scores(distribution, data)
                        arrays.update({name + "__" + domain + "__" + key: value for key, value in scores.items()})
                    costs[name] = {"wall_ns": time.perf_counter_ns() - wall_arm, "parent_cpu_ns": time.process_time_ns() - cpu_arm}
                score_path = destination / (prefix + "_SCORES.npz")
                np.savez_compressed(score_path, **arrays)
                record = {"seed": seed, "window": window, "environment": law, "summary": summaries, "costs": costs,
                          "score_path": score_path.name, "score_sha256": sha(score_path),
                          "checkpoint_sha256": sha(Path(run_dir) / "prepared" / f"seed_{seed}" / f"window_{window:02d}_CHECKPOINT.json"),
                          "query_dataset_digests": {"old": task.dataset_digest(old), "new": task.dataset_digest(new)}}
                write(destination / (prefix + ".json"), record)
                records.append(record)
                print(json.dumps({"phase": "confirmation", "seed": seed, "window": window}), flush=True)
        verify_prepared(run_dir, freeze_path)
        index = {"schema": "hepta.analytic-event.selection-confirmation.v5", "registration": reg, "records": records,
                 "freeze_sha256": sha(freeze_path), "unique_query_trajectories": len(reg["seeds"]) * (len(reg["windows"]) + 1) * reg["confirmation_rows_per_domain"],
                 "public_context_histories": 0, "old_rows_reused_across_windows": True,
                 "wall_ns": time.perf_counter_ns() - started, "parent_cpu_ns": time.process_time_ns() - cpu}
        write(destination / "INDEX.json", index)
        return summarize(run_dir)
    except BaseException as error:
        write(Path(run_dir) / "CONFIRMATION_FAILED.json", {"error_type": type(error).__name__, "error": str(error),
              "wall_ns": time.perf_counter_ns() - started, "parent_cpu_ns": time.process_time_ns() - cpu,
              "partial_files_retained": True, "completed_scopes": len(records)})
        raise


def summarize(run_dir):
    root = Path(run_dir) / "confirmation"
    index = json.loads((root / "INDEX.json").read_text())
    reg = index["registration"]
    expected = {(seed, window) for seed in reg["seeds"] for window in range(len(reg["windows"]))}
    if (reg != registration() or len(index["records"]) != len(expected)
            or {(row["seed"], row["window"]) for row in index["records"]} != expected
            or any(sha(root / row["score_path"]) != row["score_sha256"] for row in index["records"])):
        raise ValueError("The full registered confirmation roster is required")
    scopes = {(row["seed"], row["window"]): prior_study.load(root / row["score_path"]) for row in index["records"]}
    result = {"schema": "hepta.analytic-event.selection-results.v5", "registration": reg, "arms": {}, "comparisons": {},
              "unique_query_trajectories": index["unique_query_trajectories"], "public_context_histories": 0,
              "original_round4_evidence_reconstructed": False, "production_promotion": False,
              "candidate_sets_need_not_be_nested": True, "profile_gates_are_empirical_not_simultaneous_certificates": True}
    for ai, arm in enumerate(ARMS):
        old = np.array([[scopes[seed, window][arm + "__old__density_nll"] - scopes[seed, window]["frozen__old__density_nll"]
                         for window in range(len(reg["windows"]))] for seed in reg["seeds"]])
        final = np.array([[scopes[seed, len(reg["windows"]) - 1][arm + "__new__density_nll"]
                           - scopes[seed, len(reg["windows"]) - 1]["frozen__new__density_nll"]] for seed in reg["seeds"]])
        selected = [scopes[seed, window] for seed in reg["seeds"] for window, law in enumerate(reg["windows"]) if law == "drift_shift"]
        probabilities = np.concatenate([value[arm + "__new__probabilities"] for value in selected])
        labels = np.concatenate([value[arm + "__new__labels"] for value in selected])
        ece = statistics.calibration(probabilities, labels)["classwise_ece"]
        coverage = float(np.concatenate([value[arm + "__new__coverage95"] for value in selected]).mean())
        ci = prior_study.interval(final, reg["bootstrap_replicates"], reg["bootstrap_seed"] + ai, .05)
        retained = bool(old.mean((0, 2)).max() <= .02 and final.mean() <= 0)
        efficacy = bool(retained and final.mean() <= -.005 and max(ci["per_seed_mean"]) < 0 and ci["interval"][1] < 0)
        calibrated = bool(ece <= .04 and .92 <= coverage <= .98)
        result["arms"][arm] = {"worst_cross_seed_mean_old_nll_increase": float(old.mean((0, 2)).max()),
            "worst_single_seed_window_old_nll_increase": float(old.mean(2).max()),
            "old_nll_increase_by_window": old.mean((0, 2)).tolist(), "final_new_nll_difference_descriptive95": ci,
            "pooled_shifted_classwise_ece": ece, "pooled_shifted_coverage95": coverage,
            "passes_retention_gate": retained, "passes_nll_efficacy_gate": efficacy,
            "passes_calibration_gate": calibrated, "passes_joint_empirical_gate": efficacy and calibrated}
    secondary = (("mixture_full_range", "moment_full_range"), ("mixture_full_range", "same_weight_moment_full"),
                 ("mixture_full_range", "gaussian_full_range"), ("gaussian_full_range", "replay_legacy"))
    for pi, (left, right) in enumerate(PRIMARY + secondary):
        delta = [[scopes[seed, window][left + "__new__density_nll"] - scopes[seed, window][right + "__new__density_nll"]
                  for window, law in enumerate(reg["windows"]) if law == "drift_shift"] for seed in reg["seeds"]]
        primary = (left, right) in PRIMARY
        ci = prior_study.interval(delta, reg["bootstrap_replicates"], reg["bootstrap_seed"] + 100 + pi, .025 if primary else .05)
        result["comparisons"][left + "_minus_" + right] = {**ci, "scope": "primary" if primary else "descriptive",
            "range_benefit_detected": bool(ci["interval"][1] < 0) if primary else None,
            "expanded_joint_gate_passed": result["arms"][left]["passes_joint_empirical_gate"] if primary else None}
    write(root / "RESULTS.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("smoke", "prepare", "freeze", "confirm", "summary"))
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--freeze", type=Path)
    parser.add_argument("--reviewed-registration-sha256")
    args = parser.parse_args()
    if args.phase in ("smoke", "prepare"):
        result = prepare(args.run_dir, "development_smoke" if args.phase == "smoke" else "registered")
        print(json.dumps({key: result[key] for key in ("registration_sha256", "optimizer_fit_count", "selector_count", "candidate_evaluations", "optimizer_failures", "confirmation_arrays_constructed")}))
    elif args.phase == "freeze":
        result = freeze_prepared(args.run_dir, args.reviewed_registration_sha256)
        print(json.dumps({"freeze_sha256": sha(args.run_dir / "FREEZE.json"), "reviewed_registration_sha256": result["reviewed_registration_sha256"]}))
    elif args.phase == "confirm":
        result = confirm(args.run_dir, args.freeze)
        print(json.dumps({"comparisons": result["comparisons"]}))
    else:
        print(json.dumps(summarize(args.run_dir)["comparisons"]))


if __name__ == "__main__":
    main()
