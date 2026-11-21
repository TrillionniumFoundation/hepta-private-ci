"""Freeze -> train paired task teachers/policy search -> seal -> final test once."""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time

import numpy as np
import torch

from qualification.hcsn_adaptive.batched_flow import FlowConfig
from qualification.hcsn_adaptive.budget import Budget, summarize_journal
from qualification.hcsn_adaptive.campaign import digest, runtime_identity, source_identity, write_json
from qualification.hcsn_adaptive.checkpoint import claim_final_holdout
from qualification.hcsn_adaptive.datasets import file_digest, inspect_splits, load_split
from .model import evaluate_policy, policy_grid
from .train import failure_receipt, paths_for, prepare_shared, tensors, train_trial


def executable_identity():
    result = source_identity()
    root = Path(__file__).resolve().parents[2]
    result.update({str(path.relative_to(root)): file_digest(path)
                   for path in sorted(Path(__file__).parent.glob("*.py"))
                   if not path.name.endswith("_tests.py")})
    return result


def numeric_policy(config):
    torch.set_num_threads(config["threads"])
    if torch.get_num_interop_threads() != config["interop_threads"]:
        torch.set_num_interop_threads(config["interop_threads"])
    torch.use_deterministic_algorithms(True)


def freeze(config_path, manifest_path):
    cfg = {"seeds": [11, 29, 47], "horizon": 4, "train_limit": 64,
           "partition_seed": 20261121, "readout_ridge": .001, "critic_ridge": .01,
           "event_cost": .01, "device": "cpu", "dtype": "float64", "threads": 1,
           "interop_threads": 1, **json.loads(Path(config_path).read_text())}
    if (not cfg.get("experiment_id") or not cfg.get("data_dir") or cfg["device"] != "cpu"
            or cfg["dtype"] != "float64" or not cfg["seeds"] or len(set(cfg["seeds"])) != len(cfg["seeds"])
            or any(type(s) is not int or not 0 <= s < 2**63 for s in cfg["seeds"])
            or type(cfg["partition_seed"]) is not int or not 0 <= cfg["partition_seed"] < 2**63
            or type(cfg["horizon"]) is not int or cfg["horizon"] < 2
            or type(cfg["train_limit"]) is not int or not 4 <= cfg["train_limit"] <= 256
            or any(type(cfg[k]) is not int or not 1 <= cfg[k] <= 64 for k in ("threads", "interop_threads"))
            or any(not math.isfinite(cfg[k]) or cfg[k] <= 0 for k in ("readout_ridge", "critic_ridge"))
            or not math.isfinite(cfg["event_cost"]) or cfg["event_cost"] < 0):
        raise ValueError("invalid immutable task-advantage protocol")
    cfg["shared_budget"] = asdict(Budget(**{"wall_seconds": 120.0, "development_queries": 1,
                                          **cfg.get("shared_budget", {})}))
    cfg["budget"] = asdict(Budget(**{"wall_seconds": 120.0, "development_queries": 9,
                                   "proposals": 9, **cfg.get("budget", {})}))
    numeric_policy(cfg)
    data = inspect_splits(cfg["data_dir"])
    metadata = json.loads((Path(cfg["data_dir"]) / "dataset.json").read_text())
    if metadata.get("task") != "future_return":
        raise ValueError("this pilot is restricted to the declared regular-clock future_return task")
    train = load_split(cfg["data_dir"], "train", data)
    length, input_size = train["x"].shape[1:]
    if (train["y"].shape[1] != 1 or cfg["horizon"] >= length
            or len(train["x"]) < cfg["train_limit"]):
        raise ValueError("scalar task, 2<=H<T and the full declared training subset required")
    flow = FlowConfig(**{"input_size": input_size, "bins": 4, "stages": 2, "content_size": 2,
                         "upper_mode": "reflecting", "transport_precision": "float64", **cfg.get("flow", {})})
    if (flow.upper_mode != "reflecting" or flow.input_size != input_size
            or train.get("dt") is None or train["dt"].shape != train["x"].shape[:2]
            or not np.isfinite(train["dt"]).all()
            or not np.allclose(train["dt"]*1_000_000, round(flow.dt*1_000_000), rtol=0, atol=1e-6)):
        raise ValueError("finite reflecting flow and declared known regular physical clock required")
    indices = np.random.default_rng(cfg["partition_seed"]).permutation(len(train["x"]))[:cfg["train_limit"]]
    half = len(indices)//2
    policies = policy_grid()
    trials = [{"seed": seed, "arm": arm} for seed in cfg["seeds"] for arm in policies]
    for trial in trials:
        trial["id"] = digest(trial)[:20]
    manifest = {"schema": "hepta.hcsn.task-advantage.v1", "config": cfg, "flow": asdict(flow),
                "length": length, "data": data, "readout_indices": indices[:half].tolist(),
                "teacher_indices": indices[half:].tolist(), "policies": policies, "trials": trials,
                "source": executable_identity(), "runtime": runtime_identity(cfg["device"]),
                "frozen_utc": datetime.now(timezone.utc).isoformat(),
                "claims": {"teacher": "train-only realized task-MSE contrast between low/high single boundary pulses",
                    "advantage": "loss_low-loss_high-event_cost*(events_high-events_low)",
                    "deployment": "b=-0.25+0.5*sigmoid((predicted_A/train_A_std-offset)/temperature)",
                    "decision": "single t=T-H; restore b=0 after one interval; H counts visible suffix intervals",
                    "target": "same forecast label: mean utility of six hidden steps after the visible T-step window",
                    "fit": "disjoint fixed training folds for common readout and counterfactual critic",
                    "ridge_objective": "mean squared loss + lambda/N * non-bias squared weights; scalar outputs",
                    "selection": "common task MSE + event_cost*expected_events on dev; baseline NoUpdate included",
                    "mask": "identical frozen encoder/readout for all policies of a seed; controller capacity differs",
                    "budget": "common operation-admission ceilings; actual work/overruns/failed attempts retained",
                    "scope": "finite one-decision policy improvement surrogate, not Bellman/global/financial optimality",
                    "test": "all trials sealed before any final labels; no test-based selection"}}
    manifest["sha256"] = digest(manifest)
    write_json(manifest_path, manifest, exclusive=True)
    return manifest


def read_manifest(path):
    manifest = json.loads(Path(path).read_text())
    numeric_policy(manifest["config"])
    if (manifest["sha256"] != digest({k: v for k, v in manifest.items() if k != "sha256"})
            or manifest["source"] != executable_identity()
            or manifest["runtime"] != runtime_identity(manifest["config"]["device"])
            or manifest["data"] != inspect_splits(manifest["config"]["data_dir"])):
        raise ValueError("frozen source, runtime, data or manifest identity changed")
    return manifest


def seal_selection_set(manifest, output):
    entries, records = [], []
    for trial in manifest["trials"]:
        identity, directory = paths_for(manifest, trial, output)
        training = json.loads((directory / "training.json").read_text())
        if (training["identity"] != identity or training["trial"] != trial
                or training["manifest"] != manifest["sha256"] or training["status"] == "paused"):
            raise ValueError("all predeclared trials must terminate with matching immutable identities")
        selected = training.get("selected_sha256")
        if selected and file_digest(directory / "selected.pt") != selected:
            raise ValueError("selected policy changed before sealing")
        entries.append({"id": trial["id"], "training_sha256": file_digest(directory / "training.json"),
                        "selected_sha256": selected})
        records.append(training)
    seal = {"manifest": manifest["sha256"], "selections": entries}
    path = Path(output) / "finalization-seal.json"
    if path.exists():
        if json.loads(path.read_text()) != seal:
            raise ValueError("sealed selections changed")
    else:
        write_json(path, seal, exclusive=True)
    return records, seal


def finalize_trial(manifest, trial, output, training):
    identity, directory = paths_for(manifest, trial, output)
    seal = json.loads((Path(output) / "finalization-seal.json").read_text())
    if (seal["manifest"] != manifest["sha256"]
            or [row["id"] for row in seal["selections"]] != [row["id"] for row in manifest["trials"]]
            or any(file_digest(Path(output) / "trials" / row["id"] / "training.json") != row["training_sha256"]
                   for row in seal["selections"])
            or training["identity"] != identity or training["trial"] != trial):
        raise ValueError("complete selection seal must match before any final labels open")
    if "selected_sha256" not in training:
        return {"status": "unavailable", "trial": trial, "reason": "no qualified selected policy"}
    if file_digest(directory / "selected.pt") != training["selected_sha256"]:
        raise ValueError("selected policy bytes changed after sealing")
    final_identity = digest({"manifest": manifest["sha256"], "trial": trial,
                             "selected": training["selected_sha256"], "shared": training["shared_sha256"]})
    final_path = directory / "final.json"
    if final_path.exists():
        prior = json.loads(final_path.read_text())
        if prior["identity"] != final_identity or prior["trial"] != trial:
            raise ValueError("final receipt belongs to another policy selection")
        return prior
    started = time.perf_counter()
    cfg = manifest["config"]
    selected = torch.load(directory / "selected.pt", map_location=cfg["device"], weights_only=True)
    if not (Path(output) / "shared" / str(trial["seed"]) / "shared.json").exists():
        raise ValueError("shared training artifact must preexist final evaluation")
    model, shared, _ = prepare_shared(manifest, trial["seed"], output)
    if (selected["identity"] != identity or selected["trial"] != trial
            or selected["shared_sha256"] != shared["sha256"] or shared["sha256"] != training["shared_sha256"]
            or selected["readout_sha256"] != shared["readout_sha256"]
            or selected["policy"] != training["policy"]
            or selected["policy"] not in [{"kind": "zero"}, *manifest["policies"][trial["arm"]]]
            or any(not torch.isfinite(value).all() for value in model.state_dict().values())
            or not (model.readout_scale > 0).all() or not (model.critic_scale > 0).all()
            or not model.advantage_scale > 0 or not model.input_scale > 0):
        raise ValueError("invalid shared model, normalization, or selected policy binding")
    claim_final_holdout(directory / "final.started", final_identity)
    test = load_split(cfg["data_dir"], "test", manifest["data"])
    x, y = tensors(test, cfg["device"])
    metrics = evaluate_policy(model, x, test["dt"], y, selected["policy"], cfg["event_cost"])
    result = {"identity": final_identity, "manifest": manifest["sha256"], "trial": trial,
              "status": "completed", "policy": selected["policy"], "readout_sha256": shared["readout_sha256"],
              "test": metrics, "test_examples": len(x), "wall_seconds": time.perf_counter()-started,
              "test_selection_count": 0, "final_evaluation_count": 1}
    write_json(final_path, result, exclusive=True)
    return result


def summary(manifest, output):
    output = Path(output)
    costs = {"shared:"+str(seed): summarize_journal(output / "shared" / str(seed) / "cost.jsonl")
             for seed in manifest["config"]["seeds"]}
    rows = []
    for trial in manifest["trials"]:
        _, directory = paths_for(manifest, trial, output)
        record = json.loads((directory / "training.json").read_text()) if (directory / "training.json").exists() else {}
        final = json.loads((directory / "final.json").read_text()) if (directory / "final.json").exists() else None
        costs[trial["id"]] = summarize_journal(directory / "cost.jsonl")
        rows.append({"trial": trial, "status": record.get("status", "unavailable"),
                     "outcome": record.get("outcome"), "policy": record.get("policy"),
                     "dev": record.get("dev"), "final": final})
    total, wall = {}, 0.0
    for journal in costs.values():
        for key, count in journal.get("reserved_cost", journal.get("known_reserved_cost", {})).items():
            total[key] = total.get(key, 0) + count
        wall += journal.get("accounted_wall_lower_bound_seconds", 0.0)
    return {"manifest": manifest["sha256"], "rows": rows, "cost_journals": costs,
            "total_reserved_work_deduplicated": total, "accounted_wall_lower_bound_seconds": wall,
            "unavailable_or_uncertain_costs": [key for key, value in costs.items() if value["status"] != "settled"],
            "cost_scope": "shared readout, paired teachers, diagnostics and zero reference counted once per seed; all failed candidate reservations retained; final inference/outer process overhead separate"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("freeze")
    command.add_argument("--config", required=True)
    command.add_argument("--manifest", required=True)
    for name in ("run", "seal", "finalize", "summary"):
        command = commands.add_parser(name)
        command.add_argument("--manifest", required=True)
        command.add_argument("--output", required=True)
        if name == "run":
            command.add_argument("--resume", action="store_true")
            command.add_argument("--stop-after", type=int)
    args = parser.parse_args()
    if args.command == "freeze":
        result = freeze(args.config, args.manifest)
    else:
        manifest = read_manifest(args.manifest)
        if args.command == "run":
            if (Path(args.output) / "finalization-seal.json").exists():
                raise ValueError("policy search is sealed")
            result = []
            for trial in manifest["trials"]:
                attempted_at = time.perf_counter()
                try:
                    result.append(train_trial(manifest, trial, args.output, resume=args.resume, stop_after=args.stop_after))
                except Exception as exc:
                    result.append(failure_receipt(manifest, trial, args.output, exc, time.perf_counter()-attempted_at))
            write_json(Path(args.output) / "training-summary.json", result)
        elif args.command == "seal":
            _, result = seal_selection_set(manifest, args.output)
        elif args.command == "finalize":
            records, _ = seal_selection_set(manifest, args.output)
            result = []
            for trial, training in zip(manifest["trials"], records):
                started = time.perf_counter()
                try:
                    result.append(finalize_trial(manifest, trial, args.output, training))
                except Exception as exc:
                    result.append({"trial": trial, "status": "unavailable", "reason": type(exc).__name__+": "+str(exc),
                                   "final_attempt_wall_seconds": time.perf_counter()-started})
            write_json(Path(args.output) / "final-summary.json", result)
        else:
            result = summary(manifest, args.output)
        write_json(Path(args.output) / "campaign-summary.json", summary(manifest, args.output))
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
