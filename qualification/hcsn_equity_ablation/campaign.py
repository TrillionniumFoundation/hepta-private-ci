"""A fixed 18-trial comparison; explicit global seal precedes one test claim."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import statistics
import time

import numpy as np
import torch

from qualification.hcsn.tensor import HXParams
from qualification.hcsn_adaptive.budget import Budget, CostLedger, summarize_journal
from qualification.hcsn_adaptive.campaign import digest, runtime_identity, save_tensor_file, source_identity, write_json
from qualification.hcsn_adaptive.checkpoint import claim_final_holdout
from qualification.hcsn_adaptive.datasets import file_digest, inspect_splits, load_split
from qualification.hcsn_adaptive.features import build_encoder, standardize, tensor_digest
from qualification.hcsn_history.call_adapters import FrozenHXCurve
from .features import ARMS, extract_arms


SEEDS = (11, 29, 47)
TASK_LENGTHS = {"future_return": 16, "delayed_recall": 32}
FLOW = {"content_size": 4, "bins": 6, "stages": 3, "upper_mode": "reflecting", "transport_precision": "float64"}


def sources():
    root = Path(__file__).resolve().parents[2]
    result = source_identity()
    paths = [root/"qualification/hcsn/tensor.py", root/"qualification/hcsn_history/call_adapters.py",
             root/"qualification/hcsn_history/__init__.py"]
    paths += [p for p in Path(__file__).parent.glob("*.py") if not p.name.endswith("_tests.py")]
    result.update({str(p.relative_to(root)): file_digest(p) for p in paths})
    return result


def numeric_policy():
    torch.set_num_threads(1)
    if torch.get_num_interop_threads() != 1:
        torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)


def validate_data(data, task, count):
    if (data["x"].shape != (count, TASK_LENGTHS[task], 2) or data["y"].shape != (count, 1)
            or data["dt"].shape != data["x"].shape[:2] or not np.all(data["dt"] == .1)):
        raise ValueError("formal synthetic shape or physical-time contract changed")


def freeze(output, experiment_id, future_data, recall_data):
    numeric_policy()
    tasks = {}
    for task, directory in zip(TASK_LENGTHS, (future_data, recall_data)):
        directory = str(Path(directory).resolve())
        data = inspect_splits(directory)
        metadata = json.loads((Path(directory)/"dataset.json").read_text())
        if metadata["task"] != task or metadata["length"] != TASK_LENGTHS[task] or data["test"]["samples"] != 48:
            raise ValueError("formal task definition or test count changed")
        for split, count in (("train", 96), ("dev", 48)):
            validate_data(load_split(directory, split, data), task, count)
        tasks[task] = {"directory": directory, "data": data}
    manifest = {"schema": "hcsn.equity-ablation.v1", "experiment_id": experiment_id, "tasks": tasks,
                "seeds": SEEDS, "arms": ARMS, "trials": 18, "flow": FLOW, "ridge": .001,
                "budget_seconds_per_task_seed": 120.0, "dtype": "float64", "device": "cpu",
                "source": sources(), "runtime": runtime_identity("cpu"), "financial_parameters": asdict(HXParams()),
                "selection": "mean dev MSE across all three seeds; ties follow declared arm order",
                "readout_objective": "mean MSE + ridge * sum(non-bias weights squared)",
                "normalization": "same train-only rule per arm; non-Call columns have identical statistics",
                "cost_scope": "one shared frozen trajectory per split; original Call solve retained; HX setup/apply extra",
                "hx_semantics": "active sum p*E_HX(x)/b_HX; financial parameters fixed; phase/escape contribute zero"}
    manifest["sha256"] = digest(manifest)
    Path(output).mkdir(parents=True, exist_ok=False)
    write_json(Path(output)/"manifest.json", manifest, exclusive=True)
    return manifest


def read_manifest(output):
    numeric_policy()
    manifest = json.loads((Path(output)/"manifest.json").read_text())
    if (manifest["sha256"] != digest({k: v for k, v in manifest.items() if k != "sha256"})
            or manifest["source"] != sources() or manifest["runtime"] != runtime_identity("cpu")
            or any(spec["data"] != inspect_splits(spec["directory"]) for spec in manifest["tasks"].values())):
        raise ValueError("frozen source/runtime/data/manifest identity changed")
    return manifest


def groups(manifest):
    return [(task, seed, f"{task}-{seed}") for task in manifest["tasks"] for seed in manifest["seeds"]]


def ridge(train, target, dev, dev_target, penalty):
    a, b, mean, scale = standardize(train, dev)
    design = torch.cat((a, torch.ones_like(a[:, :1])), 1)
    regularizer = torch.eye(design.shape[1], dtype=a.dtype)*(len(a)*target.shape[1]*penalty)
    regularizer[-1, -1] = 0
    weight = torch.linalg.solve(design.T@design+regularizer, design.T@target)
    probe = {"weight": weight, "mean": mean, "scale": scale}
    return probe, float((predict(probe, train)-target).square().mean()), float((predict(probe, dev)-dev_target).square().mean())


def predict(probe, features):
    x = (features-probe["mean"])/probe["scale"]
    value = torch.cat((x, torch.ones_like(x[:, :1])), 1)@probe["weight"]
    if not bool(torch.isfinite(value).all()):
        raise FloatingPointError("nonfinite shared-objective ridge prediction")
    return value


def train_group(manifest, output, task, seed, name):
    root = Path(output)
    if (root/"selection-seal.json").exists() or (root/"final.started").exists():
        raise ValueError("selection sealed; training is closed")
    directory = root/name
    identity = digest({"manifest": manifest["sha256"], "group": name})
    if (directory/"training.json").exists():
        record = json.loads((directory/"training.json").read_text())
        if record["identity"] != identity:
            raise ValueError("existing group has a different experiment identity")
        return record
    directory.mkdir(exist_ok=False)
    started = time.perf_counter()
    ledger = CostLedger(directory/"cost.jsonl", Budget(wall_seconds=120.0, proposals=3, development_queries=3), identity, started_at=started)
    record = {"identity": identity, "manifest": manifest["sha256"], "task": task, "seed": seed, "status": "failed", "arms": {}}
    try:
        spec = manifest["tasks"][task]
        model = build_encoder(2, seed=seed, flow=manifest["flow"]).requires_grad_(False)
        encoder_sha = digest({k: tensor_digest(v) for k, v in model.state_dict().items()})
        with ledger.operation("fixed_financial_curve_setup"):
            begin = time.perf_counter()
            curve = FrozenHXCurve.build(model.centers)
            record["cache_setup_seconds"] = time.perf_counter()-begin
        record.update(encoder_sha256=encoder_sha, curve_sha256=tensor_digest(curve.values),
                      curve_parameters=dict(curve.parameters), curve_payload_bytes=sum(t.numel()*t.element_size() for t in (curve.nodes, curve.values)))
        features, targets, extraction = {}, {}, {}
        for split, count in (("train", 96), ("dev", 48)):
            data = load_split(spec["directory"], split, spec["data"])
            validate_data(data, task, count)
            with ledger.operation(split+"_shared_encoder_and_hx", encoder_events=count*TASK_LENGTHS[task], forward_examples=count*TASK_LENGTHS[task]):
                features[split], extraction[split], _ = extract_arms(model, data["x"], data["dt"], curve)
            targets[split] = torch.as_tensor(data["y"], dtype=torch.float64)
        probes = {}
        for arm in ARMS:
            with ledger.operation("ridge_"+arm, training_examples=96, forward_examples=144, development_queries=1, proposals=1):
                probe, train_mse, dev_mse = ridge(features["train"][arm], targets["train"], features["dev"][arm], targets["dev"], manifest["ridge"])
                probes[arm] = probe
                record["arms"][arm] = {"train_mse": train_mse, "dev_mse": dev_mse,
                                       "readout_parameters": probe["weight"].numel(), "readout_mask": "all affine coefficients; bias unpenalized"}
        record["extraction"] = extraction
        with ledger.operation("checkpoint", mandatory=True):
            save_tensor_file(directory/"selected.pt", {"identity": identity, "encoder": model.state_dict(), "probes": probes})
        record.update(status="completed", selected_sha256=file_digest(directory/"selected.pt"))
    except Exception as exc:
        record["error"] = type(exc).__name__+": "+str(exc)
    record["cost"] = ledger.snapshot()
    record["cost_journal"] = summarize_journal(directory/"cost.jsonl")
    write_json(directory/"training.json", record, exclusive=True)
    return record


def selection(manifest, output):
    rows, scores = [], {task: {arm: [] for arm in ARMS} for task in manifest["tasks"]}
    for task, seed, name in groups(manifest):
        directory = Path(output)/name
        row = json.loads((directory/"training.json").read_text())
        if (row["identity"] != digest({"manifest": manifest["sha256"], "group": name})
                or row["status"] != "completed" or set(row["arms"]) != set(ARMS)
                or any(not np.isfinite(value["dev_mse"]) for value in row["arms"].values())
                or file_digest(directory/"selected.pt") != row["selected_sha256"]):
            raise ValueError("all predeclared trials must complete and bind before sealing")
        rows.append({"group": name, "training_sha256": file_digest(directory/"training.json"), "selected_sha256": row["selected_sha256"]})
        for arm in ARMS:
            scores[task][arm].append(row["arms"][arm]["dev_mse"])
    means = {task: {arm: statistics.mean(values) for arm, values in data.items()} for task, data in scores.items()}
    return {"manifest": manifest["sha256"], "groups": rows, "dev_mean_mse": means,
            "selected_arm_by_task": {task: min(ARMS, key=lambda a: data[a]) for task, data in means.items()}}


def seal(manifest, output):
    value, path = selection(manifest, output), Path(output)/"selection-seal.json"
    if path.exists():
        if json.loads(path.read_text()) != value:
            raise ValueError("sealed global choices changed")
    else:
        write_json(path, value, exclusive=True)
    return value


def finalize(manifest, output):
    root = Path(output)
    started = time.perf_counter()
    path = root/"selection-seal.json"
    if not path.exists() or json.loads(path.read_text()) != selection(manifest, output):
        raise ValueError("all trials must be globally sealed and unchanged before test")
    identity = digest(json.loads(path.read_text()))
    if (root/"final.json").exists():
        result = json.loads((root/"final.json").read_text())
        if result["identity"] != identity:
            raise ValueError("final receipt has a different sealed identity")
        return result
    claim_final_holdout(root/"final.started", identity)
    tests = {task: load_split(spec["directory"], "test", spec["data"]) for task, spec in manifest["tasks"].items()}
    results = []
    for task, seed, name in groups(manifest):
        group_started = time.perf_counter()
        ledger = CostLedger(root/name/"final-cost.jsonl", Budget(wall_seconds=120.0), identity, started_at=group_started)
        data = tests[task]
        validate_data(data, task, 48)
        model = build_encoder(2, seed=seed, flow=manifest["flow"]).requires_grad_(False)
        saved = torch.load(root/name/"selected.pt", weights_only=True)
        if saved["identity"] != digest({"manifest": manifest["sha256"], "group": name}):
            raise ValueError("selected encoder/readouts identity mismatch")
        model.load_state_dict(saved["encoder"])
        with ledger.operation("fixed_financial_curve_setup"):
            setup_started = time.perf_counter()
            curve = FrozenHXCurve.build(model.centers)
            setup_seconds = time.perf_counter()-setup_started
        with ledger.operation("test_shared_encoder_and_hx", encoder_events=48*TASK_LENGTHS[task], forward_examples=48*TASK_LENGTHS[task]):
            features, diagnostic, _ = extract_arms(model, data["x"], data["dt"], curve)
        target = torch.as_tensor(data["y"], dtype=torch.float64)
        with ledger.operation("test_all_presealed_readouts", forward_examples=48*len(ARMS)):
            rows = [{"task": task, "seed": seed, "arm": arm,
                     "test_mse": float((predict(saved["probes"][arm], features[arm])-target).square().mean())} for arm in ARMS]
        write_json(root/name/"final.json", {"identity": identity, "results": rows, "extraction": diagnostic,
                                           "cache_setup_seconds": setup_seconds, "cost": ledger.snapshot()}, exclusive=True)
        results.extend(rows)
    result = {"identity": identity, "manifest": manifest["sha256"], "results": results,
              "selected_arm_by_dev": json.loads(path.read_text())["selected_arm_by_task"],
              "test_selection_count": 0, "global_test_claims": 1, "shared_encoder_extraction_per_task_seed_split": 1,
              "final_wall_seconds_including_data_and_models": time.perf_counter()-started}
    write_json(root/"final.json", result, exclusive=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "train", "seal", "finalize"))
    parser.add_argument("--output", required=True)
    parser.add_argument("--experiment-id")
    parser.add_argument("--future-data")
    parser.add_argument("--recall-data")
    args = parser.parse_args()
    if args.command == "freeze":
        if not all((args.experiment_id, args.future_data, args.recall_data)):
            parser.error("freeze requires experiment ID and both formal dataset directories")
        result = freeze(args.output, args.experiment_id, args.future_data, args.recall_data)
    else:
        manifest = read_manifest(args.output)
        if args.command == "train":
            result = [train_group(manifest, args.output, *group) for group in groups(manifest)]
        else:
            try:
                result = {"seal": seal, "finalize": finalize}[args.command](manifest, args.output)
            except Exception as exc:
                if args.command == "finalize" and (Path(args.output)/"final.started").exists():
                    write_json(Path(args.output)/f"final-failure-{time.time_ns()}.json",
                               {"error": type(exc).__name__+": "+str(exc), "holdout_claim_consumed": True,
                                "costs": {name: summarize_journal(Path(args.output)/name/"final-cost.jsonl")
                                          for _, _, name in groups(manifest)}}, exclusive=True)
                raise
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
