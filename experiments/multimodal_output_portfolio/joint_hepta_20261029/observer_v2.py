"""Registered natural observer development; this entry point cannot read holdout.

The v1 failure stays immutable. Only original observer_train sources enter this
revision; even a passing development result does not open the fresh 64 sources.
"""

import argparse
import gzip
import json
from pathlib import Path
import platform
import re
import subprocess
import time

from .natural_data import (HERE, OLD, budget_check, cpu_seconds, digest, prepare_role,
                           read_inputs, restore_portable_seed, select_training, write_new)
from .natural_eval import majority_label, normalize_fit, report_accuracy, source_weights
from .observer_v2_audit import audit_predictions, support_diagnostics, training_rows


def registered_sources(commit):
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("A full immutable registration commit is required")
    root = HERE.parents[2]
    paths = [HERE / name for name in ("observer_v2.py", "observer_v2_features.py", "observer_v2_audit.py",
             "observer_v2_protocol.json", "natural_data.py", "natural_eval.py", "evidence/observer/ALLOCATION.json.gz")]
    paths += [OLD / name for name in ("semantic_tsm.py", "semantic_backbones.py", "data_prepare.py",
                                     "data_prepare_v2.py", "data_sources.py", "semantic_top1_v4/ci/PILOT.json")]
    paths.append(HERE.parent / "unified_20261028/natural_data.py")
    result = {}
    for path in paths:
        relative = str(path.relative_to(root))
        frozen = subprocess.check_output(["git", "show", commit + ":" + relative], cwd=root)
        if frozen != path.read_bytes():
            raise ValueError("Observer code differs from its public registration: " + relative)
        result[relative] = digest(frozen)
    return result


def freeze_training_allocation(seed_assets, output, protocol):
    _, source, registry = read_inputs(seed_assets)
    prior = json.loads(gzip.decompress((HERE / "evidence/observer/ALLOCATION.json.gz").read_bytes()))
    body = dict(prior)
    if body.pop("allocation_sha256") != digest(body):
        raise ValueError("Archived v1 source allocation changed")
    selected = [row for row in select_training(source, protocol) if row["study_role"] == "observer_train"]
    original = [row for row in prior["selected"] if row["study_role"] == "observer_train"]
    if ([row["source_id"] for row in selected[:64]] != [row["source_id"] for row in original]
            or len(selected) != protocol["observer_training_sources"]):
        raise ValueError("V2 source order no longer extends the fixed v1 prefix")
    forbidden = {row["source_id"] for row in source["selected"] if row["role"] != "observer_train"}
    fresh = {row["source_id"] for row in prior["selected"] if row["study_role"] == "fresh_observer_calibration"}
    if len(fresh) != 64 or {row["source_id"] for row in selected} & (forbidden | fresh):
        raise ValueError("Non-training source admitted to observer development")
    allocation = {"schema": "hepta.joint-observer-training-allocation.v2", "protocol": protocol,
                  "protocol_sha256": digest(protocol), "parent_source_protocol_sha256": source["protocol_sha256"],
                  "prior_allocation_sha256": prior["allocation_sha256"], "ontology": source["ontology"],
                  "archive": source["archive"], "selected": selected,
                  "known_hashes": {r["source_id"]: r["original_video_sha256"] for r in registry["source_rows"]
                                   if "original_video_sha256" in r},
                  "fresh_calibration_source_count_preserved": len(fresh), "fresh_media_access": False,
                  "excluded_source_ids": sorted(forbidden | fresh),
                  "source_unit": "original_video_id; participant independence unknown"}
    allocation["allocation_sha256"] = digest(allocation)
    write_new(output / "ALLOCATION.json", allocation)
    return allocation


def load_development_features(allocation, assets):
    import numpy as np
    rows, video, audio, hashes = [], [], [], set()
    for source in allocation["selected"]:
        if source["role"] != "observer_train" or source["study_role"] != "observer_train":
            raise ValueError("V2 reader accepts original observer_train sources only")
        root = Path(assets) / "prepared/observer_train" / source["source_id"]
        record = json.loads((root / "RECEIPT.json").read_text())
        if (record["allocation_sha256"] != allocation["allocation_sha256"]
                or record["role"] != "observer_train" or record["source_id"] != source["source_id"]
                or record["original_sha256"] in hashes
                or digest((root / "FEATURES.npz").read_bytes()) != record["feature_sha256"]):
            raise ValueError("V2 feature receipt differs from registered source")
        hashes.add(record["original_sha256"])
        events = source["events"][:source["retained_event_count"]]
        if len(record["events"]) != len(events):
            raise ValueError("V2 retained events incomplete")
        for actual, frozen in zip(record["events"], events, strict=True):
            if (actual["role"] != "observer_train" or actual["source_id"] != source["source_id"]
                    or actual["fold"] != source["fold"] or any(actual[k] != v for k, v in frozen.items())):
                raise ValueError("V2 labels, windows or source folds changed")
        with np.load(root / "FEATURES.npz", allow_pickle=False) as data:
            for key, width, destination in (("video", 3646, video), ("audio", 6204, audio)):
                value = data[key]
                if value.shape != (len(events), width) or not np.isfinite(value).all():
                    raise ValueError("Invalid V2 delivered-media features")
                destination.append(value.astype(np.float64))
        rows.extend(record["events"])
    video, audio = np.concatenate(video), np.concatenate(audio)
    return rows, {"action_s3d": video[:, :1424], "action_tsm": video[:, 1424:],
                  "sound_pann": audio[:, :1551], "sound_temporal": audio}


def fit_ridge(features, rows, kind, classes, ridge):
    import numpy as np
    if len(features) != len(rows) or not len(rows) or ridge <= 0 or not np.isfinite(features).all():
        raise ValueError("Invalid observer regression inputs")
    weights = source_weights(rows)
    mean, scale, x = normalize_fit(features, weights)
    labels = np.asarray([classes.index(row[kind + "_id"]) for row in rows])
    target = np.eye(len(classes))[labels]
    xmean, ymean = weights @ x, weights @ target
    rootw = np.sqrt(weights * len(rows))[:, None]
    xx, yy = (x - xmean) * rootw, (target - ymean) * rootw
    beta = xx.T @ np.linalg.solve(xx @ xx.T + ridge * np.eye(len(rows)), yy)
    return {"mean": mean, "scale": scale, "weights": beta, "intercept": ymean - xmean @ beta,
            "classes": np.asarray(classes), "majority_label": majority_label(rows, kind, classes)}


def predict_ridge(state, features):
    import numpy as np
    x = np.clip((features - state["mean"]) / state["scale"], -8, 8)
    return state["classes"][(x @ state["weights"] + state["intercept"]).argmax(1)]


def fit_development(allocation, rows, features, output, started_cpu, started_wall):
    import numpy as np
    protocol = allocation["protocol"]
    expected_rows = training_rows(allocation)
    if [(r["source_id"], r["fold"], r["action_id"], r["sound_id"]) for r in rows] != [
            (r["source_id"], r["fold"], r["action_id"], r["sound_id"]) for r in expected_rows]:
        raise ValueError("Prepared feature rows differ from registered training allocation")
    folds = np.asarray([row["fold"] for row in rows])
    results, selected, support = {}, {}, {}
    for kind in ("action", "sound"):
        classes = sorted(map(int, allocation["ontology"][kind]))
        support[kind] = support_diagnostics(rows, allocation["ontology"], kind)
        results[kind] = []
        for candidate in protocol["candidates"][kind]:
            x = features[candidate["feature"]]
            predictions, majority = np.empty(len(rows), int), np.empty(len(rows), int)
            fits, visits = [], np.zeros(len(rows), int)
            for fold in range(5):
                budget_check(started_cpu, started_wall, protocol)
                train, valid = np.where(folds != fold)[0], np.where(folds == fold)[0]
                training = [rows[i] for i in train]
                train_ids, valid_ids = {r["source_id"] for r in training}, {rows[i]["source_id"] for i in valid}
                if not len(train) or not len(valid) or train_ids & valid_ids:
                    raise ValueError("Incomplete or overlapping observer source fold")
                state = fit_ridge(x[train], training, kind, classes, candidate["ridge"])
                predictions[valid] = predict_ridge(state, x[valid])
                majority[valid] = state["majority_label"]
                visits[valid] += 1
                fits.append({"fold": fold, "training_sources": sorted(train_ids), "validation_sources": sorted(valid_ids),
                             "training_feature_sha256": digest(x[train].tobytes()),
                             "training_labels_sha256": digest([r[kind + "_id"] for r in training])})
            if not np.all(visits == 1):
                raise ValueError("Every development event needs exactly one OOF prediction")
            report = {"candidate": candidate, "out_of_fold": report_accuracy(predictions, rows, kind),
                      "majority_control": report_accuracy(majority, rows, kind), "folds": fits}
            report["audit"] = audit_predictions(report["out_of_fold"], report["majority_control"], rows, kind, allocation["ontology"])
            results[kind].append(report)
            print(json.dumps({"observer_v2": kind, "candidate": candidate["name"],
                              "source_oof_accuracy": report["out_of_fold"]["source_uniform_accuracy"]}), flush=True)
        chosen = max(results[kind], key=lambda result: result["out_of_fold"]["source_uniform_accuracy"])
        candidate = chosen["candidate"]
        budget_check(started_cpu, started_wall, protocol)
        state = fit_ridge(features[candidate["feature"]], rows, kind, classes, candidate["ridge"])
        checkpoint = output / (kind + "_observer.npz")
        np.savez_compressed(checkpoint, **state)
        selected[kind] = {**chosen, "checkpoint_file": checkpoint.name, "checkpoint_sha256": digest(checkpoint.read_bytes())}
    passed = all(value["out_of_fold"]["source_uniform_accuracy"] >= protocol["adequacy"][kind + "_accuracy"]
                 and value["out_of_fold"]["source_uniform_accuracy"] > value["majority_control"]["source_uniform_accuracy"]
                 for kind, value in selected.items())
    freeze = {"schema": "hepta.joint-observer-development-freeze.v2", "allocation_sha256": allocation["allocation_sha256"],
              "protocol_sha256": digest(protocol), "candidates": results, "selected": selected, "support": support,
              "development_passed": passed, "fresh_calibration_media_accessed": False,
              "generated_output_reliability_established": False, "semantic_qualification": False,
              "independent_confirmation": False, "original_sources": len({r["source_id"] for r in rows}),
              "events": len(rows), "ridge_fits": sum(5 * len(v) + 1 for v in protocol["candidates"].values()),
              "neural_optimizer_updates": 0,
              "training_source_hashes": sorted({r["source_sha256"] for r in rows}),
              "selection_bias": "The same source OOF estimates select and report candidates. This is development, not confirmation."}
    write_new(output / "OBSERVER_V2_FREEZE.json", freeze)
    return freeze


def run(output, registration_sha):
    import torch
    from .observer_v2_features import ObserverBackbones, download_pretrained
    started_cpu, started_wall = cpu_seconds(), time.monotonic()
    binding = registered_sources(registration_sha)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    result = {"schema": "hepta.joint-observer-development-run.v2", "registration_sha": registration_sha,
              "source_code_sha256": binding, "status": "started", "fresh_calibration_media_accessed": False,
              "fresh_calibration_predictions": 0, "old_development_or_calibration_accessed": False,
              "generated_output_reliability_established": False, "semantic_qualification": False}
    try:
        protocol = json.loads((HERE / "observer_v2_protocol.json").read_text())
        write_new(output / "PROTOCOL.json", protocol)
        torch.set_num_threads(protocol["budget"]["torch_threads"])
        seed = restore_portable_seed(output / "seed")
        allocation = freeze_training_allocation(seed, output, protocol)
        result["runtime"] = {"python": platform.python_version(), "torch": torch.__version__}
        result["weights"] = download_pretrained(output / "pretrained")
        model = ObserverBackbones(output / "pretrained")
        assets = output / "actual"
        assets.mkdir()
        prepare_role(allocation, assets, "observer_train", models=model, start_cpu=started_cpu, start_wall=started_wall)
        del model
        rows, features = load_development_features(allocation, assets)
        freeze = fit_development(allocation, rows, features, output, started_cpu, started_wall)
        result.update(status="development_gate_passed_confirmation_unopened" if freeze["development_passed"] else "development_gate_failed",
                      development_passed=freeze["development_passed"], original_sources=freeze["original_sources"],
                      events=freeze["events"], freeze_sha256=digest(freeze))
    except Exception as exc:
        result.update(status="incomplete_or_failed", error=type(exc).__name__ + ": " + str(exc))
        raise
    finally:
        result.update(cpu_seconds_self_plus_completed_children=cpu_seconds() - started_cpu,
                      wall_seconds=time.monotonic() - started_wall, physical_cpu_tail_bound_proved=False,
                      cost_scope="Python run entry including registration checks, downloads, codec children, feature extraction and regression; process startup/import excluded")
        write_new(output / "RESULT.json", result)
        print(json.dumps(result), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--registration-sha", required=True)
    args = parser.parse_args()
    run(args.output, args.registration_sha)
