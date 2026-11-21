"""Freeze -> train/dev selection -> seal all selections -> one final evaluation.

This is a new experiment identity. It does not import prior benchmark results,
relabel financial values as task optima, or reproduce an LLM editing agent.
"""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import tempfile
import time

import numpy as np
import torch

from .budget import Budget, BudgetExhausted, CostLedger, summarize_journal
from .batched_flow import FlowConfig
from .checkpoint import claim_final_holdout, load_checkpoint, save_checkpoint
from .continuation import ContinuationBoundary
from .datasets import file_digest, inspect_splits, load_split, make_synthetic
from .features import (CHANNEL_ABLATIONS, boundary_candidates, build_encoder, extract_features,
                       fit_task_boundary, flow_for, standardize, training_ridge_score)
from .learner import METHODS, LearnerConfig, fit_readout


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def write_json(path, value, *, exclusive=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if exclusive:
        with path.open("x") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        return
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def save_tensor_file(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        torch.save(payload, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def source_identity():
    root = Path(__file__).resolve().parents[2]
    paths = sorted(Path(__file__).parent.glob("*.py"))
    paths += sorted((root / "qualification/hcsn_training").glob("*.py"))
    return {str(path.relative_to(root)): file_digest(path)
            for path in paths if not path.name.endswith("_tests.py")}


def runtime_identity(device):
    return {"python": platform.python_version(), "torch": str(torch.__version__),
            "numpy": np.__version__, "device": device, "cuda": torch.version.cuda,
            "device_name": torch.cuda.get_device_name(torch.device(device))
            if device.startswith("cuda") else platform.processor() or "cpu",
            "machine": platform.machine(), "platform": platform.platform(),
            "torch_threads": torch.get_num_threads(), "torch_interop_threads": torch.get_num_interop_threads(),
            "torch_config_sha256": hashlib.sha256(torch.__config__.show().encode()).hexdigest(),
            "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
            "cudnn_deterministic": torch.backends.cudnn.deterministic,
            "cudnn_benchmark": torch.backends.cudnn.benchmark,
            "matmul_allow_tf32": torch.backends.cuda.matmul.allow_tf32,
            "cudnn_allow_tf32": torch.backends.cudnn.allow_tf32,
            "cublas_workspace_config": os.environ.get("CUBLAS_WORKSPACE_CONFIG")}


def freeze(config_path, manifest_path):
    config = json.loads(Path(config_path).read_text())
    required = {"experiment_id", "data_dir", "stage", "seeds", "variants", "methods"}
    if not required.issubset(config) or config["stage"] not in ("P1", "P2", "smoke"):
        raise ValueError("config must declare identity, immutable data, stage and full matrix")
    if not config["seeds"] or len(set(config["seeds"])) != len(config["seeds"]):
        raise ValueError("nonempty unique model seeds required")
    if (not config["variants"] or not config["methods"] or len(config["methods"]) != len(set(config["methods"]))
            or not set(config["methods"]).issubset(METHODS)):
        raise ValueError("invalid or duplicate learner matrix")
    if config["stage"] == "P1" and len(config["methods"]) != 1:
        raise ValueError("P1 fixes one learner to isolate mechanism substitutions")
    if config["stage"] == "P2" and len(config["variants"]) != 1:
        raise ValueError("P2 fixes one encoder/boundary/channel variant")
    config.setdefault("device", "cpu")
    config.setdefault("dtype", "float64")
    config.setdefault("target_type", "regression")
    if config["target_type"] not in ("regression", "one_hot_classification"):
        raise ValueError("unknown target type")
    if config["dtype"] not in ("float32", "float64"):
        raise ValueError("only declared FP32 or FP64 runs are supported")
    config["budget"] = asdict(Budget(**config.get("budget", {})))
    config["feature_budget"] = asdict(Budget(**config.get("feature_budget", {"wall_seconds": 120.0})))
    config["learner"] = asdict(LearnerConfig(**config.get("learner", {})))
    ids = [variant["id"] for variant in config["variants"]]
    if len(set(ids)) != len(ids):
        raise ValueError("variant identifiers must be unique")
    with np.load(Path(config["data_dir"]) / "train.npz", allow_pickle=False) as training:
        input_size = training["x"].shape[2]
    for variant in config["variants"]:
        boundary_candidates(variant["boundary"])
        if variant.get("drift", "input") not in ("fixed", "input"):
            raise ValueError("unknown drift ablation")
        if variant.get("channels", "dual") not in CHANNEL_ABLATIONS:
            raise ValueError("unknown channel ablation")
        FlowConfig(input_size=input_size, **flow_for(config, variant))
    trials = [{"seed": seed, "variant": variant, "method": method}
              for seed in config["seeds"] for variant in config["variants"] for method in config["methods"]]
    for trial in trials:
        trial["id"] = digest(trial)[:20]
    manifest = {"schema": "hepta.adaptive.campaign.v1", "config": config,
                "data": inspect_splits(config["data_dir"]), "source": source_identity(),
                "runtime": runtime_identity(config["device"]), "trials": trials,
                "frozen_utc": datetime.now(timezone.utc).isoformat(),
                "claims": {"parameter_mask": "frozen features; common affine readout",
                           "task_boundary": "finite observed MDP surrogate and explicit threshold projection",
                           "editing": "ProgrammaticEdit, not MIT agent reproduction",
                           "budget": "common ceilings; actual work and all failed attempts reported"}}
    manifest["sha256"] = digest(manifest)
    write_json(manifest_path, manifest, exclusive=True)
    return manifest


def read_manifest(path):
    manifest = json.loads(Path(path).read_text())
    payload = {key: value for key, value in manifest.items() if key != "sha256"}
    if manifest["sha256"] != digest(payload) or manifest["source"] != source_identity():
        raise ValueError("frozen manifest or executable source changed")
    if manifest["runtime"] != runtime_identity(manifest["config"]["device"]):
        raise ValueError("runtime/hardware differs from the frozen identity")
    if manifest["data"] != inspect_splits(manifest["config"]["data_dir"]):
        raise ValueError("frozen data bytes or split identities changed")
    return manifest


def prepare_features(manifest, trial, output, *, resume=False):
    started = time.perf_counter()
    config, variant = manifest["config"], trial["variant"]
    identity = digest({"manifest": manifest["sha256"], "seed": trial["seed"], "variant": variant})
    directory = Path(output) / "features" / identity[:20]
    cache_path, checkpoint = directory / "features.pt", directory / "checkpoint.pt"
    existed = (directory / "cost.jsonl").exists()
    ledger = CostLedger(directory / "cost.jsonl", Budget(**config["feature_budget"]), identity,
                        started_at=started)
    if cache_path.exists():
        receipt = json.loads((directory / "features.json").read_text())
        if receipt["identity"] != identity or receipt["sha256"] != file_digest(cache_path):
            raise ValueError("immutable feature-cache bytes changed")
        cache = torch.load(cache_path, map_location=config["device"], weights_only=True)
        if cache["identity"] != identity:
            raise ValueError("feature-cache identity mismatch")
        cost = ledger.snapshot()
        cost["wall_seconds"] = ledger.prior_wall
        return cache, {"key": identity, "shared_cost": cost, "reused": True,
                       "reuse_load_seconds": time.perf_counter() - started}
    if existed and not resume:
        raise FileExistsError("incomplete feature attempt requires explicit resume")
    train = load_split(config["data_dir"], "train", manifest["data"])
    dev = load_split(config["data_dir"], "dev", manifest["data"])
    if config["target_type"] == "one_hot_classification":
        for split in (train, dev):
            if not np.isin(split["y"], [0, 1]).all() or not np.all(split["y"].sum(1) == 1):
                raise ValueError("classification targets must be one-hot rows")
    model = build_encoder(train["x"].shape[2], seed=trial["seed"], flow=flow_for(config, variant),
                          device=config["device"], dtype=config["dtype"])
    optimizer = torch.optim.Adam(model.parameters(), lr=config["learner"]["learning_rate"])
    generator = torch.Generator().manual_seed(trial["seed"])
    targets = torch.as_tensor(train["y"], dtype=model.drive.weight.dtype, device=config["device"])
    controller = {"next_candidate": 0, "best_score": None, "best_features": None,
                  "policy": None, "attempts": [], "critic": None, "train_report": None}
    if resume and checkpoint.exists():
        controller = load_checkpoint(checkpoint, identity=identity, model=model, optimizer=optimizer,
                                     generator=generator, ledger=ledger)
    def save():
        save_checkpoint(checkpoint, identity=identity, model=model, optimizer=optimizer,
                        controller=controller, generator=generator, ledger=ledger)
    critic = ContinuationBoundary.from_record(controller["critic"]) if controller["critic"] else None
    if variant["boundary"] == "task_continuation" and critic is None:
        metadata_path = Path(config["data_dir"]) / "dataset.json"
        metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
        with ledger.operation("fit_train_only_continuation", training_examples=int(np.prod(train["x"].shape[:2])),
                              proposals=1):
            critic = fit_task_boundary(train, reward_definition=config.get("reward_definition")
                                       or metadata.get("reward_definition"))
            controller["critic"] = critic.to_record()
        save()
    candidates = boundary_candidates(variant["boundary"], config.get("boundary_offsets", [-0.25, 0.0, 0.25]),
                                     config.get("boundary_gains", [-0.25, 0.0, 0.25]))
    for index in range(controller["next_candidate"], len(candidates)):
        policy = candidates[index]
        try:
            with ledger.operation("boundary_candidate", encoder_events=int(np.prod(train["x"].shape[:2])),
                                  training_examples=len(train["x"]) if len(candidates) > 1 else 0,
                                  forward_examples=len(train["x"]) if len(candidates) > 1 else 0, proposals=1):
                features, report = extract_features(model, train["x"], intervals=train.get("dt"),
                    policy=policy, critic=critic, drift=variant.get("drift", "input"),
                    channels=variant.get("channels", "dual"))
                score = training_ridge_score(features, targets, config["learner"]["ridge"]) if len(candidates) > 1 else 0.0
                if not np.isfinite(score):
                    raise FloatingPointError("nonfinite boundary search score")
                if controller["best_score"] is None or score < controller["best_score"]:
                    controller.update(best_score=score, best_features=features, policy=policy, train_report=report)
            controller["attempts"].append({"index": index, "policy": policy, "training_mse": score,
                                            "status": "completed"})
        except (FloatingPointError, RuntimeError) as exc:
            if isinstance(exc, BudgetExhausted):
                raise
            controller["attempts"].append({"index": index, "policy": policy, "status": "failed",
                                            "error": type(exc).__name__ + ": " + str(exc)})
        controller["next_candidate"] = index + 1
        save()
    if controller["best_features"] is None:
        raise RuntimeError("all boundary candidates failed; costs retained")
    with ledger.operation("development_features", encoder_events=int(np.prod(dev["x"].shape[:2]))):
        dev_features, dev_report = extract_features(model, dev["x"], intervals=dev.get("dt"),
            policy=controller["policy"], critic=critic, drift=variant.get("drift", "input"),
            channels=variant.get("channels", "dual"))
        train_features, dev_features, mean, scale = standardize(controller["best_features"], dev_features)
    cache = {"identity": identity, "train_x": train_features, "dev_x": dev_features, "train_y": targets,
             "dev_y": torch.as_tensor(dev["y"], dtype=targets.dtype, device=targets.device),
             "mean": mean, "scale": scale, "encoder_state": model.state_dict(),
             "input_size": train["x"].shape[2], "policy": controller["policy"], "critic": controller["critic"],
             "critic_report": critic.report() if critic else None, "boundary_search": controller["attempts"],
             "train_report": controller["train_report"], "dev_report": dev_report}
    with ledger.operation("checkpoint", mandatory=True):
        save_tensor_file(cache_path, cache)
        write_json(directory / "features.json", {"identity": identity, "sha256": file_digest(cache_path)},
                   exclusive=True)
    return cache, {"key": identity, "shared_cost": ledger.snapshot(), "reused": False,
                   "reuse_load_seconds": 0.0}


def train_trial(manifest, trial, output, *, resume=False, stop_after=None):
    directory = Path(output) / "trials" / trial["id"]
    result = directory / "training.json"
    if result.exists():
        old = json.loads(result.read_text())
        if old["manifest"] != manifest["sha256"] or old["trial"] != trial:
            raise ValueError("output directory contains another frozen experiment")
        if old["status"] not in ("paused", "interrupted"):
            return old
        if not resume:
            raise FileExistsError("paused attempt requires --resume; its prior record is preserved")
    started = time.perf_counter()
    try:
        cache, feature_cost = prepare_features(manifest, trial, output, resume=resume)
        identity = digest({"manifest": manifest["sha256"], "trial": trial})
        config = manifest["config"]
        model, report = fit_readout(cache["train_x"], cache["train_y"], cache["dev_x"], cache["dev_y"],
            method=trial["method"], seed=trial["seed"], budget=Budget(**config["budget"]),
            directory=directory / "learner", identity=identity, config=LearnerConfig(**config["learner"]),
            resume=resume and (directory / "learner/checkpoint.pt").exists(), stop_after=stop_after)
        report.update(trial=trial, manifest=manifest["sha256"], feature_cost=feature_cost,
                      boundary_search=cache["boundary_search"], critic_report=cache["critic_report"])
        if report["status"] in ("completed", "budget_exhausted") and report["outcome"] != "Unavailable":
            payload = {"state": model.state_dict(), "feature_identity": cache["identity"],
                       "feature_sha256": file_digest(Path(output) / "features" / cache["identity"][:20] / "features.pt"),
                       "learner_identity": report["identity"], "input_features": cache["train_x"].shape[1],
                       "outputs": cache["train_y"].shape[1]}
            save_tensor_file(directory / "selected.pt", payload)
            report["selected_sha256"] = file_digest(directory / "selected.pt")
    except Exception as exc:
        report = {"status": "failed", "trial": trial, "manifest": manifest["sha256"],
                  "error": type(exc).__name__ + ": " + str(exc),
                  "feature_cost_key": digest({"manifest": manifest["sha256"], "seed": trial["seed"],
                                              "variant": trial["variant"]}),
                  "cost_evidence": {
                      "feature": summarize_journal(Path(output) / "features" / digest({
                          "manifest": manifest["sha256"], "seed": trial["seed"], "variant": trial["variant"]})[:20] / "cost.jsonl"),
                      "learner": summarize_journal(directory / "learner/cost.jsonl")}}
    report["trial_wall_seconds"] = time.perf_counter() - started
    write_json(result, report)
    return report


def seal_selection_set(manifest, output):
    """Freeze the whole preregistered matrix before any final labels are loaded."""
    output = Path(output)
    records, selections = [], []
    for trial in manifest["trials"]:
        directory = output / "trials" / trial["id"]
        record = json.loads((directory / "training.json").read_text())
        if record["manifest"] != manifest["sha256"] or record["trial"] != trial:
            raise ValueError("training result is not part of the frozen matrix")
        if record["status"] not in ("completed", "budget_exhausted", "failed"):
            raise ValueError("every planned training attempt must terminate before final holdout")
        selected_hash = record.get("selected_sha256")
        if selected_hash and file_digest(directory / "selected.pt") != selected_hash:
            raise ValueError("development selection payload changed before sealing")
        selections.append({"id": trial["id"], "training_sha256": file_digest(directory / "training.json"),
                           "selected_sha256": selected_hash})
        records.append(record)
    seal = {"manifest": manifest["sha256"], "selections": selections}
    path = output / "finalization-seal.json"
    if path.exists():
        if json.loads(path.read_text()) != seal:
            raise ValueError("the sealed selection set changed")
    else:
        write_json(path, seal, exclusive=True)
    return records


def finalize_trial(manifest, trial, output, training):
    seal = json.loads((Path(output) / "finalization-seal.json").read_text())
    if (seal["manifest"] != manifest["sha256"]
            or [entry["id"] for entry in seal["selections"]] != [row["id"] for row in manifest["trials"]]):
        raise ValueError("finalization requires the exact complete selection seal")
    for entry in seal["selections"]:
        path = Path(output) / "trials" / entry["id"] / "training.json"
        if file_digest(path) != entry["training_sha256"]:
            raise ValueError("training records changed after the selection set was sealed")
    directory = Path(output) / "trials" / trial["id"]
    result_path = directory / "final.json"
    if "selected_sha256" not in training:
        return {"status": "unavailable", "trial": trial, "reason": "no qualified dev-selected checkpoint"}
    if file_digest(directory / "selected.pt") != training["selected_sha256"]:
        raise ValueError("selected checkpoint changed after development selection")
    identity = digest({"manifest": manifest["sha256"], "trial": trial,
                       "selected_sha256": training["selected_sha256"]})
    if result_path.exists():
        previous = json.loads(result_path.read_text())
        if previous["identity"] != identity or previous["trial"] != trial:
            raise ValueError("final receipt belongs to another selected experiment")
        return previous
    started = time.perf_counter()
    config = manifest["config"]
    selected = torch.load(directory / "selected.pt", map_location=config["device"], weights_only=True)
    cache_path = Path(output) / "features" / selected["feature_identity"][:20] / "features.pt"
    if file_digest(cache_path) != selected["feature_sha256"]:
        raise ValueError("selected feature payload bytes changed")
    cache = torch.load(cache_path, map_location=config["device"], weights_only=True)
    if cache["identity"] != selected["feature_identity"]:
        raise ValueError("selected feature contract changed")
    encoder = build_encoder(cache["input_size"], seed=trial["seed"], flow=flow_for(config, trial["variant"]),
                            device=config["device"], dtype=config["dtype"])
    encoder.load_state_dict(cache["encoder_state"])
    critic = ContinuationBoundary.from_record(cache["critic"]) if cache["critic"] else None
    model = torch.nn.Linear(selected["input_features"], selected["outputs"]).to(encoder.drive.weight)
    model.load_state_dict(selected["state"])
    if (cache["mean"].shape != (selected["input_features"],)
            or cache["scale"].shape != cache["mean"].shape
            or not torch.isfinite(cache["mean"]).all() or not torch.isfinite(cache["scale"]).all()
            or not (cache["scale"] > 0).all()):
        raise ValueError("invalid frozen feature normalization")
    claim_final_holdout(directory / "final.started", identity)
    test = load_split(config["data_dir"], "test", manifest["data"])
    features, feature_report = extract_features(encoder, test["x"], intervals=test.get("dt"),
        policy=cache["policy"], critic=critic, drift=trial["variant"].get("drift", "input"),
        channels=trial["variant"].get("channels", "dual"))
    with torch.no_grad():
        targets = torch.as_tensor(test["y"], dtype=features.dtype, device=features.device)
        prediction = model((features - cache["mean"]) / cache["scale"])
        mse = float((prediction - targets).square().mean())
        constant_mse = float((cache["train_y"].mean(0) - targets).square().mean())
    if not np.isfinite(mse):
        raise FloatingPointError("nonfinite final prediction; final holdout is not retried")
    result = {"status": "completed", "identity": identity, "trial": trial, "test_mse": mse,
              "training_mean_constant_mse": constant_mse, "test_examples": len(test["x"]),
              "feature_report": feature_report, "wall_seconds": time.perf_counter() - started,
              "test_selection_count": 0, "final_evaluation_count": 1}
    if config["target_type"] == "one_hot_classification":
        if not np.isin(test["y"], [0, 1]).all() or not np.all(test["y"].sum(1) == 1):
            raise ValueError("final classification labels are not one-hot")
        truth, predicted = targets.argmax(1), prediction.argmax(1)
        classes = targets.shape[1]
        confusion = torch.bincount(truth * classes + predicted, minlength=classes * classes).reshape(classes, classes)
        tp = confusion.diag().to(torch.float64)
        denominators = confusion.sum(0) + confusion.sum(1)
        f1 = torch.where(denominators > 0, 2 * tp / denominators.clamp_min(1), torch.zeros_like(tp))
        result.update(accuracy=float((predicted == truth).double().mean()),
                      macro_f1=float(f1.mean()), confusion=confusion.cpu().tolist(),
                      classification_fit_objective="MSE on one-hot targets; fixed common readout",
                      macro_f1_zero_division=0)
    write_json(result_path, result, exclusive=True)
    return result


def summarize_campaign(manifest, output):
    """Deduplicate shared encoders while retaining every failed/resumed work log."""
    output = Path(output)
    feature_keys = {digest({"manifest": manifest["sha256"], "seed": trial["seed"],
                           "variant": trial["variant"]}) for trial in manifest["trials"]}
    paths = {"feature:" + key: output / "features" / key[:20] / "cost.jsonl" for key in feature_keys}
    paths.update({"learner:" + trial["id"]: output / "trials" / trial["id"] / "learner/cost.jsonl"
                  for trial in manifest["trials"]})
    journals = {key: summarize_journal(path) for key, path in paths.items()}
    totals, wall_lower_bound = {}, 0.0
    for evidence in journals.values():
        for key, value in evidence.get("reserved_cost", evidence.get("known_reserved_cost", {})).items():
            totals[key] = totals.get(key, 0) + value
        wall_lower_bound += evidence.get("accounted_wall_lower_bound_seconds", 0.0)
    groups, status_counts = {}, {}
    for trial in manifest["trials"]:
        path = output / "trials" / trial["id"]
        training = json.loads((path / "training.json").read_text()) if (path / "training.json").exists() else {}
        status = training.get("status", "unavailable")
        status_counts[status] = status_counts.get(status, 0) + 1
        key = trial["variant"]["id"] + ":" + trial["method"]
        group = groups.setdefault(key, {"planned": 0, "completed_test": 0, "test_mse": [],
                                       "training_failed": 0, "no_update": 0})
        group["planned"] += 1
        group["training_failed"] += int(status == "failed")
        group["no_update"] += int(training.get("outcome") == "NoUpdate")
        if (path / "final.json").exists():
            final = json.loads((path / "final.json").read_text())
            if final["status"] == "completed":
                group["completed_test"] += 1
                group["test_mse"].append(final["test_mse"])
    for group in groups.values():
        values = group.pop("test_mse")
        group.update(test_mse_mean=float(np.mean(values)) if values else None,
                     test_mse_sample_sd=float(np.std(values, ddof=1)) if len(values) > 1 else None,
                     final_unavailable=group["planned"] - group["completed_test"])
    return {"manifest": manifest["sha256"], "planned_trials": len(manifest["trials"]),
            "training_status_counts": status_counts, "groups": groups,
            "total_reserved_work_deduplicated": totals, "journal_wall_lower_bound_seconds": wall_lower_bound,
            "uncertain_or_unavailable_cost_records": [key for key, value in journals.items() if value["status"] != "settled"],
            "cost_journals": journals,
            "cost_scope": "shared preprocessing counted once; all attempt reservations retained; final evaluation and outer process overhead reported separately"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    data = commands.add_parser("make-data")
    data.add_argument("--directory", required=True)
    data.add_argument("--task", choices=("future_return", "delayed_recall"), default="future_return")
    for name, default in (("seed", 20261121), ("train", 64), ("dev", 32), ("test", 32), ("length", 12)):
        data.add_argument("--" + name, type=int, default=default)
    freeze_parser = commands.add_parser("freeze")
    freeze_parser.add_argument("--config", required=True)
    freeze_parser.add_argument("--manifest", required=True)
    for name in ("run", "finalize"):
        command = commands.add_parser(name)
        command.add_argument("--manifest", required=True)
        command.add_argument("--output", required=True)
        if name == "run":
            command.add_argument("--resume", action="store_true")
            command.add_argument("--stop-after", type=int)
    arguments = parser.parse_args()
    if arguments.command == "make-data":
        result = make_synthetic(**{key: value for key, value in vars(arguments).items() if key != "command"})
    elif arguments.command == "freeze":
        result = freeze(arguments.config, arguments.manifest)
    else:
        manifest = read_manifest(arguments.manifest)
        output = Path(arguments.output)
        seal_path = output / "finalization-seal.json"
        if arguments.command == "run":
            if seal_path.exists():
                raise ValueError("final holdout phase has begun; this campaign cannot train or reselect")
            result = [train_trial(manifest, trial, output, resume=arguments.resume,
                                  stop_after=arguments.stop_after) for trial in manifest["trials"]]
            write_json(output / "training-summary.json", result)
        else:
            records = seal_selection_set(manifest, output)
            result = []
            for trial, record in zip(manifest["trials"], records):
                attempted_at = time.perf_counter()
                try:
                    result.append(finalize_trial(manifest, trial, output, record))
                except Exception as exc:
                    result.append({"status": "unavailable", "trial": trial,
                                   "reason": type(exc).__name__ + ": " + str(exc),
                                   "final_attempt_wall_seconds": time.perf_counter() - attempted_at})
            write_json(output / "final-summary.json", result)
        write_json(output / "campaign-summary.json", summarize_campaign(manifest, output))
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
