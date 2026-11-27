"""Frozen small encoder curves; all choices are sealed before any final labels open."""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
import torch

from qualification.hcsn_adaptive.budget import Budget, summarize_journal
from qualification.hcsn_adaptive.campaign import digest, runtime_identity, source_identity, write_json
from qualification.hcsn_adaptive.checkpoint import claim_final_holdout
from qualification.hcsn_adaptive.datasets import file_digest, inspect_splits, load_split
from .model import ModelConfig, SequenceModel, validate_split
from .train import failure_receipt, prepare_track, probe_prediction, raw_features, train_one


def executable_identity():
    sources = source_identity()
    root = Path(__file__).resolve().parents[2]
    sources.update({str(path.relative_to(root)): file_digest(path)
                    for path in sorted(Path(__file__).parent.glob("*.py"))
                    if not path.name.endswith("_tests.py")})
    return sources


def numeric_policy(config):
    torch.set_num_threads(config["threads"])
    if torch.get_num_interop_threads() != config["interop_threads"]:
        torch.set_num_interop_threads(config["interop_threads"])
    torch.use_deterministic_algorithms(True)


def freeze(config_path, manifest_path):
    supplied = json.loads(Path(config_path).read_text())
    cfg = {"models": ["hcsn", "gru"], "widths": [4, 8, 16], "seeds": [20261121, 20261122, 20261123],
           "steps": 24, "checkpoints": [0, 8, 24], "batch_size": 2,
           "bins": 4, "stages": 2, "dtype": "float64", "device": "cpu", "threads": 1, "interop_threads": 1,
           "learning_rate": .003, "gradient_clip": 1.0, "ridge": .001, **supplied}
    if (not cfg.get("experiment_id") or not cfg.get("data_dir")
            or not cfg["models"] or not set(cfg["models"]).issubset({"hcsn", "gru"})
            or len(set(cfg["models"])) != len(cfg["models"])
            or not cfg["widths"] or len(set(cfg["widths"])) != len(cfg["widths"])
            or any(type(w) is not int or not 1 <= w <= 64 for w in cfg["widths"])
            or not cfg["seeds"] or len(set(cfg["seeds"])) != len(cfg["seeds"])
            or any(type(s) is not int or not 0 <= s < 2**63 for s in cfg["seeds"])
            or type(cfg["steps"]) is not int or not 1 <= cfg["steps"] <= 128
            or not cfg["checkpoints"] or cfg["checkpoints"] != sorted(set(cfg["checkpoints"]))
            or any(type(step) is not int or not 0 <= step <= cfg["steps"] for step in cfg["checkpoints"])
            or cfg["checkpoints"][0] != 0 or cfg["checkpoints"][-1] != cfg["steps"]
            or type(cfg["batch_size"]) is not int or not 1 <= cfg["batch_size"] <= 16
            or cfg["dtype"] not in ("float32", "float64")
            or any(type(cfg[key]) is not int or not 1 <= cfg[key] <= 64 for key in ("threads", "interop_threads"))
            or any(not math.isfinite(cfg[key]) or cfg[key] <= 0 for key in ("learning_rate", "gradient_clip", "ridge"))):
        raise ValueError("invalid frozen encoder experiment matrix or budget policy")
    cfg["budget"] = asdict(Budget(**{**asdict(Budget(wall_seconds=180.0,
        proposals=cfg["steps"], development_queries=len(cfg["checkpoints"]))), **cfg.get("budget", {})}))
    numeric_policy(cfg)
    data = inspect_splits(cfg["data_dir"])
    train = load_split(cfg["data_dir"], "train", data)
    input_size = train["x"].shape[-1]
    validate_split(train, input_size)
    scale = 10.0 * float(np.median(train["dt"]))
    for kind in cfg["models"]:
        for width in cfg["widths"]:
            ModelConfig(kind, input_size, width, scale, cfg["bins"], cfg["stages"], dtype=cfg["dtype"])
    tracks = [{"kind": kind, "width": width, "seed": seed}
              for kind in cfg["models"] for width in cfg["widths"] for seed in cfg["seeds"]]
    tracks.insert(0, {"kind": "raw", "width": 0, "seed": None})
    for track in tracks:
        track["id"] = digest(track)[:20]
    manifest = {"schema": "hepta.hcsn.encoder-scale.v1", "config": cfg, "data": data,
                "input_size": input_size, "clock_scale_seconds": scale,
                "clock_scale_rule": "10 * median(train dt); rates converted, actual seconds unchanged",
                "train_target_mean": train["y"].mean(0).tolist(), "source": executable_identity(),
                "runtime": runtime_identity(cfg["device"]), "tracks": tracks,
                "frozen_utc": datetime.now(timezone.utc).isoformat(),
                "claims": {"scope": "small self-supervised sensor encoder capacity/update curves",
                    "pretraining": "train x[t], known dt[t] -> x[t+1]; full encoder/controller/decoder BP",
                    "probe": "train-only affine ridge: mean MSE + lambda * non-bias squared weights; dev selects checkpoint",
                    "capacity": "HCSN content width and GRU hidden width; actual parameter counts differ; fixed bins/stages",
                    "checkpoint": "between independent windows; no in-flight state or past AD graph",
                    "query": "next arrival timestamp visible, next sensor values/label hidden",
                    "test": "all checkpoint/capacity/seed choices sealed before final test",
                    "no_claims": ["foundation-model pretraining", "matched parameter counts", "Transformer or SNN superiority"]}}
    manifest["sha256"] = digest(manifest)
    write_json(manifest_path, manifest, exclusive=True)
    return manifest


def read_manifest(path):
    manifest = json.loads(Path(path).read_text())
    cfg = manifest["config"]
    numeric_policy(cfg)
    if (manifest["sha256"] != digest({k: v for k, v in manifest.items() if k != "sha256"})
            or manifest["source"] != executable_identity()
            or manifest["runtime"] != runtime_identity(cfg["device"])
            or manifest["data"] != inspect_splits(cfg["data_dir"])):
        raise ValueError("frozen source, runtime, data, or manifest changed")
    return manifest


def seal_selection_set(manifest, output):
    output = Path(output)
    records, selections, best = [], [], {}
    for track in manifest["tracks"]:
        identity, directory, _ = prepare_track(manifest, track, output)
        record = json.loads((directory / "training.json").read_text())
        if record["identity"] != identity or record["manifest"] != manifest["sha256"] or record["track"] != track:
            raise ValueError("track selection belongs to another experiment")
        if record["status"] in ("running", "paused", "interrupted"):
            raise ValueError("every predeclared trajectory must terminate before final labels open")
        selected = record.get("selected_sha256")
        if selected and file_digest(directory / "selected.pt") != selected:
            raise ValueError("selected model changed before sealing")
        selections.append({"id": track["id"], "training_sha256": file_digest(directory / "training.json"),
                           "selected_sha256": selected})
        records.append(record)
        if selected:
            score = (record["best_dev"], track["id"])
            if track["kind"] not in best or score < best[track["kind"]][0]:
                best[track["kind"]] = (score, track["id"])
    seal = {"manifest": manifest["sha256"], "selections": selections,
            "capacity_seed_choices_by_dev": {kind: value[1] for kind, value in best.items()}}
    path = output / "finalization-seal.json"
    if path.exists():
        if json.loads(path.read_text()) != seal:
            raise ValueError("sealed checkpoint/capacity/seed selection changed")
    else:
        write_json(path, seal, exclusive=True)
    return records, seal


def finalize_one(manifest, track, output, training):
    _, directory, config = prepare_track(manifest, track, output)
    seal_path = Path(output) / "finalization-seal.json"
    if not seal_path.exists():
        raise ValueError("all capacity/seed/checkpoint selections must be sealed before test")
    seal = json.loads(seal_path.read_text())
    sealed = next((item for item in seal["selections"] if item["id"] == track["id"]), None)
    if (seal["manifest"] != manifest["sha256"] or sealed is None
            or [item["id"] for item in seal["selections"]] != [item["id"] for item in manifest["tracks"]]
            or any(item["training_sha256"] != file_digest(Path(output) / "tracks" / item["id"] / "training.json")
                   for item in seal["selections"])
            or sealed["selected_sha256"] != training.get("selected_sha256")):
        raise ValueError("final evaluation does not match the sealed selection set")
    if "selected_sha256" not in training:
        return {"status": "unavailable", "track": track, "reason": "no dev-selected checkpoint"}
    identity = digest({"manifest": manifest["sha256"], "track": track, "selected": training["selected_sha256"]})
    path = directory / "final.json"
    if file_digest(directory / "selected.pt") != training["selected_sha256"]:
        raise ValueError("sealed selected model changed")
    if path.exists():
        prior = json.loads(path.read_text())
        if prior["identity"] != identity or prior["track"] != track:
            raise ValueError("final receipt belongs to another selection")
        return prior
    started = time.perf_counter()
    cfg = manifest["config"]
    selected = torch.load(directory / "selected.pt", map_location=cfg["device"], weights_only=True)
    if selected["identity"] != training["identity"] or selected["step"] != training["best_step"]:
        raise ValueError("selected payload binding mismatch")
    probe = selected["probe"]
    if any(not torch.isfinite(value).all() for value in probe.values()) or not (probe["scale"] > 0).all():
        raise ValueError("invalid probe normalization or weights")
    model = None
    if config is not None:
        if selected["config"] != asdict(config):
            raise ValueError("encoder configuration changed")
        model = SequenceModel(config).to(device=cfg["device"])
        model.load_state_dict(selected["model"])
    claim_final_holdout(directory / "final.started", identity)
    test = load_split(cfg["data_dir"], "test", manifest["data"])
    validate_split(test, manifest["input_size"])
    dtype = getattr(torch, cfg["dtype"])
    with torch.no_grad():
        if model is None:
            features = raw_features(test, manifest["clock_scale_seconds"], dtype=dtype, device=cfg["device"])
            ssl_loss = None
        else:
            x = torch.as_tensor(test["x"], dtype=dtype, device=cfg["device"])
            features, ssl_loss = model.representations(x, test["dt"])
        prediction = probe_prediction(probe, features)
        target = torch.as_tensor(test["y"], dtype=dtype, device=cfg["device"])
        mse = float((prediction - target).square().mean())
    if not np.isfinite(mse):
        raise FloatingPointError("nonfinite final result; this holdout claim cannot retry")
    result = {"identity": identity, "manifest": manifest["sha256"], "track": track,
              "status": "completed", "selected_step": training["best_step"], "test_probe_mse": mse,
              "test_ssl_mse": ssl_loss, "test_examples": len(test["x"]),
              "wall_seconds": time.perf_counter() - started, "final_evaluation_count": 1,
              "test_selection_count": 0}
    if np.isin(test["y"], [0, 1]).all() and np.all(test["y"].sum(1) == 1):
        truth, predicted = target.argmax(1), prediction.argmax(1)
        classes = target.shape[1]
        confusion = torch.bincount(truth * classes + predicted, minlength=classes**2).reshape(classes, classes)
        denom = confusion.sum(0) + confusion.sum(1)
        f1 = torch.where(denom > 0, 2 * confusion.diag() / denom.clamp_min(1), torch.zeros_like(denom))
        result.update(accuracy=float((truth == predicted).double().mean()), macro_f1=float(f1.double().mean()),
                      confusion=confusion.cpu().tolist(), macro_f1_zero_division=0)
    write_json(path, result, exclusive=True)
    return result


def summary(manifest, output):
    output = Path(output)
    rows, costs = [], {}
    for track in manifest["tracks"]:
        _, directory, _ = prepare_track(manifest, track, output)
        training = json.loads((directory / "training.json").read_text()) if (directory / "training.json").exists() else {}
        final = json.loads((directory / "final.json").read_text()) if (directory / "final.json").exists() else {}
        costs[track["id"]] = summarize_journal(directory / "cost.jsonl")
        rows.append({"track": track, "status": training.get("status", "unavailable"),
                     "model": training.get("model"), "curve": training.get("curve", []),
                     "selected_step": training.get("best_step"), "outcome": training.get("outcome"),
                     "peak_rss_bytes": training.get("peak_rss_bytes"), "final": final})
    return {"manifest": manifest["sha256"], "tracks": rows, "cost_journals": costs,
            "total_reserved_counts": {key: sum(value.get("reserved_cost", value.get("known_reserved_cost", {})).get(key, 0) for value in costs.values())
                for key in ("training_examples", "encoder_events", "forward_examples", "backward_examples", "development_queries", "proposals", "failures")},
            "cost_uncertain_tracks": [key for key, value in costs.items() if value["status"] != "settled"],
            "scope": "small finite sensor encoder curves; actual parameters differ; no foundation or Transformer/SNN comparison"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    freeze_parser = sub.add_parser("freeze")
    freeze_parser.add_argument("--config", required=True)
    freeze_parser.add_argument("--manifest", required=True)
    for name in ("run", "track", "finalize"):
        command = sub.add_parser(name)
        command.add_argument("--manifest", required=True)
        command.add_argument("--output", required=True)
        if name in ("run", "track"):
            command.add_argument("--resume", action="store_true")
        if name == "track":
            command.add_argument("--track-id", required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        result = freeze(args.config, args.manifest)
    else:
        manifest = read_manifest(args.manifest)
        out = Path(args.output)
        if args.command in ("run", "track") and (out / "finalization-seal.json").exists():
            raise ValueError("final phase is sealed; training/reselection is closed")
        if args.command == "track":
            track = next(t for t in manifest["tracks"] if t["id"] == args.track_id)
            try:
                result = train_one(manifest, track, out, resume=args.resume)
            except Exception as error:
                result = failure_receipt(manifest, track, out, error)
        elif args.command == "run":
            for track in manifest["tracks"]:
                started = time.perf_counter()
                command = [sys.executable, "-m", "qualification.hcsn_scale.campaign", "track",
                           "--manifest", args.manifest, "--output", str(out), "--track-id", track["id"]]
                if args.resume:
                    command.append("--resume")
                process = subprocess.run(command, text=True, capture_output=True, check=False)
                directory = out / "tracks" / track["id"]
                write_json(directory / f"process-{time.time_ns()}.json", {"returncode": process.returncode,
                    "wall_seconds": time.perf_counter() - started, "stdout": process.stdout, "stderr": process.stderr}, exclusive=True)
                if process.returncode != 0 and not (directory / "training.json").exists():
                    failure_receipt(manifest, track, out, RuntimeError("worker exit " + str(process.returncode)))
            result = summary(manifest, out)
            write_json(out / "training-summary.json", result)
        else:
            records, seal = seal_selection_set(manifest, out)
            finals = []
            for track, record in zip(manifest["tracks"], records):
                try:
                    finals.append(finalize_one(manifest, track, out, record))
                except Exception as error:
                    finals.append({"status": "unavailable", "track": track,
                                   "reason": type(error).__name__ + ": " + str(error)})
            result = {"seal": seal, "finals": finals, "summary": summary(manifest, out)}
            write_json(out / "final-summary.json", result)
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
