"""Frozen training and separate post-publication historical evaluation."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time
import numpy as np
import torch
from torch import nn
from .data import Normalization, dataset
from .model import Model


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def configure():
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)


def state_sha(state):
    result = hashlib.sha256()
    for name, tensor in sorted(state.items()):
        result.update(name.encode()+tensor.detach().numpy().tobytes())
    return result.hexdigest()


def read_plan(run):
    plan = json.loads((run/"PLAN.json").read_text())
    for path, expected in plan["source_sha256"].items():
        if sha(ROOT/path) != expected:
            raise RuntimeError("Frozen source changed: "+path)
    for path, expected in plan["input_sha256"].items():
        if sha(run/path) != expected:
            raise RuntimeError("Frozen training input changed: "+path)
    return plan


def prepare(run):
    run.mkdir(parents=True, exist_ok=False)
    protocol = json.loads((HERE/"PROTOCOL.json").read_text())
    inputs, identities = {}, {}
    for task in protocol["tasks"]:
        x, y, groups, _, identity = dataset(task, "train")
        norm = Normalization.fit(x.numpy())
        path = run/(task+"-TRAIN.npz")
        np.savez_compressed(path, x=x.numpy(), y=y.numpy(), groups=groups,
                            center=norm.center, scale=norm.scale)
        inputs[path.name] = sha(path); identities[task] = identity
    modules = [m for name, m in sys.modules.items() if name.startswith("experiments.")]
    paths = {Path(m.__file__).resolve() for m in modules if getattr(m, "__file__", None)}
    paths.update(HERE.glob("*.py")); paths.add(HERE/"PROTOCOL.json")
    sources = {str(path.relative_to(ROOT)): sha(path) for path in sorted(paths) if path.suffix in (".py", ".json")}
    write(run/"PLAN.json", {"schema": "hcsn-v13-joint-training-freeze.v1", "created_unix": time.time(),
          "protocol": protocol, "source_sha256": sources, "input_sha256": inputs, "training_identities": identities,
          "runtime": {"torch": torch.__version__, "numpy": np.__version__, "python": sys.version},
          "evaluation_opened": False, "classes_are_actual_task_targets": True})


def fit(run, task, family, seed):
    plan = read_plan(run); protocol = plan["protocol"]
    if task not in protocol["tasks"] or family not in protocol["families"] or seed not in protocol["seeds"]:
        raise ValueError("Fit outside predeclared roster")
    out = run/f"fit-{task}-{family}-{seed}"
    out.mkdir()
    with np.load(run/(task+"-TRAIN.npz"), allow_pickle=False) as arrays:
        norm = Normalization(arrays["center"], arrays["scale"])
        x = norm.apply(torch.from_numpy(arrays["x"]))
        y = torch.from_numpy(arrays["y"])
    torch.manual_seed(seed)
    model = Model(family, protocol["tasks"][task])
    initial_sha = state_sha(model.state_dict())
    initial_asset = model.asset_drive.weight.detach().clone() if hasattr(model, "asset_drive") else None
    optimizer = torch.optim.AdamW(model.parameters(), lr=protocol["learning_rate"], weight_decay=protocol["weight_decay"])
    generator = torch.Generator().manual_seed(seed+100000)
    stream = hashlib.sha256(); training = []
    for update in range(protocol["updates_per_fit"]):
        indices = torch.randint(len(x), (protocol["batch_size"],), generator=generator)
        stream.update(indices.numpy().tobytes())
        optimizer.zero_grad()
        logits, events = model(x[indices], return_events=True)
        loss = nn.functional.cross_entropy(logits.flatten(0, 1), y[indices].flatten())
        if not torch.isfinite(loss):
            raise ArithmeticError("Nonfinite training objective")
        loss.backward()
        if any(p.grad is not None and not torch.isfinite(p.grad).all() for p in model.parameters()):
            raise ArithmeticError("Nonfinite joint gradient")
        asset_norm = float(model.asset_drive.weight.grad.norm()) if hasattr(model, "asset_drive") else None
        optimizer.step()
        training.append({"update": update+1, "loss": float(loss.detach()), "asset_encoder_gradient_norm": asset_norm,
                         "reset_cell_events": sum(int(e["reset"].sum()) for e in events),
                         "restoration_cell_events": sum(int(e["restored"].sum()) for e in events)})
        with (out/"UPDATES.jsonl").open("a") as stream_out:
            stream_out.write(json.dumps(training[-1], allow_nan=False)+"\n")
    torch.save(model.state_dict(), out/"weights.pt")
    norm.save(out/"NORMALIZATION.npz")
    write(out/"TRAIN.json", {"task": task, "family": family, "seed": seed, "classes": model.classes,
          "parameter_count": sum(p.numel() for p in model.parameters()), "initial_state_sha256": initial_sha,
          "batch_stream_sha256": stream.hexdigest(), "optimizer_updates": len(training), "training": training,
          "weights_sha256": sha(out/"weights.pt"), "normalization_sha256": sha(out/"NORMALIZATION.npz"),
          "plan_sha256": sha(run/"PLAN.json"), "source_sha256": plan["source_sha256"],
          "asset_encoder_weight_change_norm": float((model.asset_drive.weight-initial_asset).norm().detach()) if initial_asset is not None else None,
          "margin_zero_feature_columns": [5*i+j for i in range(8) for j in (1, 2, 3, 4)] if family == "hx_margin" else [],
          "allocated_parameter_count_is_not_effective_capacity_matching": True, "evaluation_opened": False})


def load_candidate(directory):
    metadata = json.loads((directory/"TRAIN.json").read_text())
    for path, expected in metadata["source_sha256"].items():
        if sha(ROOT/path) != expected:
            raise RuntimeError("Frozen candidate source changed: "+path)
    if sha(directory/"weights.pt") != metadata["weights_sha256"] or sha(directory/"NORMALIZATION.npz") != metadata["normalization_sha256"]:
        raise RuntimeError("Frozen candidate identity differs")
    model = Model(metadata["family"], metadata["classes"])
    model.load_state_dict(torch.load(directory/"weights.pt", map_location="cpu", weights_only=True))
    return model.eval(), Normalization.load(directory/"NORMALIZATION.npz")


def freeze(run):
    plan = read_plan(run); protocol = plan["protocol"]
    records = []
    for task in protocol["tasks"]:
        for seed in protocol["seeds"]:
            paired = []
            streams = set()
            for family in protocol["families"]:
                directory = run/f"fit-{task}-{family}-{seed}"
                meta = json.loads((directory/"TRAIN.json").read_text())
                assert meta["optimizer_updates"] == protocol["updates_per_fit"]
                assert meta["weights_sha256"] == sha(directory/"weights.pt")
                assert meta["normalization_sha256"] == sha(directory/"NORMALIZATION.npz")
                streams.add(meta["batch_stream_sha256"])
                if family in ("hx_full", "hx_margin", "ordinary_gate"):
                    paired.append(meta["initial_state_sha256"])
                records.append({"directory": directory.name, "weights_sha256": sha(directory/"weights.pt"),
                                "train_metadata_sha256": sha(directory/"TRAIN.json"), "task": task, "family": family, "seed": seed})
            assert len(streams) == 1 and len(set(paired)) == 1
    write(run/"CANDIDATES.json", {"models": records, "plan_sha256": sha(run/"PLAN.json"),
                                 "evaluation_opened": False, "classes": protocol["tasks"]})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "fit", "freeze"))
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--task"); parser.add_argument("--family"); parser.add_argument("--seed", type=int)
    args = parser.parse_args(); configure()
    if args.command == "prepare": prepare(args.run)
    elif args.command == "fit": fit(args.run, args.task, args.family, args.seed)
    else: freeze(args.run)
