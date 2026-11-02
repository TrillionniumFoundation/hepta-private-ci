"""Fit future correctness from actual new-head forwards on TRAIN, calibrate VAL.

All future arrays and labels are confined to this offline builder. Legal prefix
tree nodes are computed once per object/model, then reused as explicit targets;
target count is not an independent-object or model-forward count.
"""

import argparse
import gzip
import json
from pathlib import Path
import sys
import time
import subprocess
import hashlib

import numpy as np
import torch
from torch import nn

from experiments.hcsn_v7_support_20261101.content_interface.content_interface import CacheBudget, Modality, VisibleContent
from experiments.hcsn_v8_execution_20261101.frontend.legacy_v3 import prepared_observation
from experiments.hcsn_v8_execution_20261101.scheduler.planning import Plan, Read
from ..joint_core.campaign import configure, load_candidate
from ..joint_core.data import legacy_data, labels_of, row_from_cache
from .runtime import VALUE_WIDTH, ValueNet, feature, sha


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def load_packet(path):
    with np.load(path, allow_pickle=False) as z:
        return {name: z[name].copy() for name in z.files}


def content_publication_gate(models, publication, protocol):
    if publication is None:
        raise RuntimeError("Verified content-candidate/source publication required before any VAL load")
    receipt = json.loads(publication.read_text())
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if receipt.get("local_head") != head or receipt.get("all_stage_root_trees_exact") is not True or len(receipt.get("remote_head", "")) != 40:
        raise RuntimeError("Content-candidate publication does not bind this complete tree")
    candidates = json.loads((models / "CANDIDATES.json").read_text())
    expected = {(t, f, s) for t in protocol["tasks"] for f in protocol["families"] for s in protocol["seeds"]}
    actual = {(m["task"], m["family"], m["seed"]) for m in candidates["models"]}
    if len(candidates["models"]) != len(expected) or actual != expected or candidates["evaluation_opened"]:
        raise RuntimeError("Complete untouched-TEST content roster required before VAL")
    if candidates["plan_sha256"] != sha(models / "PLAN.json"):
        raise RuntimeError("Content training plan changed")
    required = [models / "PLAN.json", models / "CANDIDATES.json", HERE / "PROTOCOL.json", *HERE.glob("*.py")]
    for item in candidates["models"]:
        directory = models / item["directory"]
        metadata = json.loads((directory / "TRAIN.json").read_text())
        if sha(directory / "TRAIN.json") != item["train_metadata_sha256"] or sha(directory / "weights.pt") != item["weights_sha256"]:
            raise RuntimeError("Content candidate differs from its frozen roster")
        if sha(directory / "NORMALIZATION.npz") != metadata["normalization_sha256"]:
            raise RuntimeError("Content normalization changed")
        required += [directory / name for name in ("weights.pt", "NORMALIZATION.npz", "TRAIN.json")]
    entries = subprocess.check_output(["git", "ls-tree", "-rz", head]).split(b"\0")
    committed = {row.split(b"\t", 1)[1].decode(): row.split(b"\t", 1)[0].split()[2].decode() for row in entries if row}
    for path in required:
        content = path.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
        if committed.get(str(path.resolve().relative_to(ROOT))) != blob:
            raise RuntimeError("Required content/source bytes are absent from verified published tree")
    return receipt


def prepare(run, models, publication):
    protocol = json.loads((HERE / "PROTOCOL.json").read_text())
    receipt = content_publication_gate(models, publication, protocol)
    run.mkdir(parents=True, exist_ok=False)
    identities = {}
    for task in protocol["tasks"]:
        for split in ("train", "val"):
            data = legacy_data(task, split)
            path = run / f"{task}-{split}.npz"
            np.savez_compressed(path, **{k: data[k] for k in ("x", "valid", "observed", "relative_times", "ids")},
                                labels=np.asarray(labels_of(data), dtype=np.int64))
            identities[path.name] = {"sha256": sha(path), "source_array_sha256": data["metadata"]["array_sha256"],
                                     "objects": len(data["ids"]), "role": split}
    modules = [m for name, m in sys.modules.items() if name.startswith("experiments.")]
    paths = {Path(m.__file__).resolve() for m in modules if getattr(m, "__file__", None)}
    paths.update(HERE.glob("*.py")); paths.add(HERE / "PROTOCOL.json")
    write(run / "PLAN.json", {"schema": "hcsn-v13-new-head-value-fit-plan.v1", "created_unix": time.time(),
        "models_directory": str(models.resolve().relative_to(ROOT)), "candidates_sha256": sha(models / "CANDIDATES.json"),
        "content_publication_remote_head": receipt["remote_head"], "content_publication_receipt_sha256": sha(publication),
        "protocol": protocol, "packets": identities,
        "source_sha256": {str(p.relative_to(ROOT)): sha(p) for p in sorted(paths) if p.suffix in (".py", ".json")},
        "test_opened": False, "calibration_role": "historical VAL; correlated prefixes, no independent qualification"})


def read_plan(run):
    plan = json.loads((run / "PLAN.json").read_text())
    for path, digest in plan["source_sha256"].items():
        if sha(ROOT / path) != digest:
            raise RuntimeError("Frozen control source changed: " + path)
    for path, item in plan["packets"].items():
        if sha(run / path) != item["sha256"]:
            raise RuntimeError("Frozen training/calibration packet changed")
    if sha(ROOT / plan["models_directory"] / "CANDIDATES.json") != plan["candidates_sha256"]:
        raise RuntimeError("Content candidates changed")
    return plan


def tree(model, norm, data, index, prior):
    object_id = "offline-" + str(index)
    valid = data["valid"][index]
    arrays = data["x"][index, valid], data["observed"][index, valid], data["relative_times"][index, valid]
    empty = VisibleContent(object_id, CacheBudget(65536))
    initial = model.initial(torch.zeros((1, 55), dtype=torch.float64))
    nodes = {}

    def visit(path, content, state, history, p, elapsed):
        nodes[path] = {"content": content, "state": state, "history": history, "p": p}
        for modality in Modality:
            if not path and modality != Modality.AUDIO:
                continue
            level = int(content.level(modality)) + 1
            if level > 3:
                continue
            step = (modality.value, level)
            at = max(elapsed, level) + .001
            obs = prepared_observation(*arrays, object_id=object_id, modality=modality, prefix_end=level,
                                       completed_at=at, event_id="offline-" + repr(path + (step,)))
            updated = content.accept(obs, at)
            raw = row_from_cache(updated, modality, max(content.level(m) for m in Modality))
            row = torch.as_tensor(norm.apply(raw)[None], dtype=torch.float64)
            with torch.no_grad():
                child, _ = model.step(row, state)
                next_history = history + [row]
                probabilities = torch.softmax(model.classify(next_history, child), -1)[0].tolist()
            visit(path + (step,), updated, child, next_history, probabilities, at)

    visit((), empty, initial, [], prior, 0.)
    return nodes


def targets(model, norm, data, prior, stream, split):
    x, y, current_p, current_labels, forwards = [], [], [], [], 0
    for index, label in enumerate(data["labels"]):
        nodes = tree(model, norm, data, index, prior)
        forwards += len(nodes) - 1
        for path, node in nodes.items():
            current_p.append(node["p"]); current_labels.append(int(label))
            if not path:
                continue  # mandatory A1 precedes every actual controller decision
            history = [row[0].tolist() for row in node["history"]]
            for future, child in nodes.items():
                if not len(path) < len(future) <= len(path) + 2 or future[:len(path)] != path:
                    continue
                steps = future[len(path):]
                plan = Plan(tuple(Read(Modality(m), level) for m, level in steps))
                values = feature(history, node["p"], plan)
                correct = int(np.argmax(child["p"]) == int(label))
                x.append(values); y.append(correct)
                stream.write(json.dumps({"split": split, "object": index, "current": path, "future": future,
                    "label_for_training_only": int(label), "future_probabilities": child["p"], "correct": correct,
                    "feature_sha256": hashlib.sha256(values.tobytes()).hexdigest()}) + "\n")
    return np.asarray(x), np.asarray(y), np.asarray(current_p), np.asarray(current_labels), forwards


def calibrate(predicted, correct):
    bins = np.minimum((np.asarray(predicted) * 5).astype(int), 4)
    correct = np.asarray(correct)
    global_rate = float((correct.sum() + 1) / (len(correct) + 2))
    counts = [int((bins == i).sum()) for i in range(5)]
    rates = [float((correct[bins == i].sum() + 1) / (counts[i] + 2)) if counts[i] else global_rate for i in range(5)]
    return {"counts": counts, "rates": rates, "rule": "five fixed p bins; Laplace(1,1); empty bin uses global rate"}


def fit(run, task, family, seed):
    plan = read_plan(run); protocol = plan["protocol"]
    if task not in protocol["tasks"] or family not in protocol["families"] or seed not in protocol["seeds"]:
        raise ValueError("Reader fit outside frozen roster")
    directory = ROOT / plan["models_directory"] / f"fit-{task}-{family}-{seed}"
    model, norm = load_candidate(directory)
    out = run / f"fit-{task}-{family}-{seed}"
    out.mkdir()
    train, val = (load_packet(run / f"{task}-{split}.npz") for split in ("train", "val"))
    prior = (np.bincount(train["labels"], minlength=model.classes) + 1).astype(float)
    prior /= prior.sum()
    with gzip.open(out / "FUTURE_TARGETS.jsonl.gz", "xt") as stream:
        tx, ty, _, _, train_forwards = targets(model, norm, train, prior.tolist(), stream, "train")
        vx, vy, vp, vl, val_forwards = targets(model, norm, val, prior.tolist(), stream, "val")
    mean, scale = tx.mean(0), np.maximum(tx.std(0), 1e-5)
    x, y = torch.from_numpy((tx - mean) / scale), torch.from_numpy(ty.astype(float))
    torch.manual_seed(seed + 500000)
    reader = ValueNet()
    optimizer = torch.optim.AdamW(reader.parameters(), lr=protocol["learning_rate"], weight_decay=protocol["weight_decay"])
    generator = torch.Generator().manual_seed(seed + 600000)
    losses = []
    for _ in range(protocol["updates_per_reader"]):
        indices = torch.randint(len(x), (protocol["batch_size"],), generator=generator)
        optimizer.zero_grad()
        loss = nn.functional.binary_cross_entropy_with_logits(reader(x[indices]), y[indices])
        if not torch.isfinite(loss):
            raise ArithmeticError("Nonfinite new-head future-correctness objective")
        loss.backward(); optimizer.step(); losses.append(float(loss.detach()))
    with torch.no_grad():
        values = torch.sigmoid(reader(torch.from_numpy((vx - mean) / scale))).numpy()
    head_id = f"joint-v13-{task}-{family}-{sha(directory / 'weights.pt')[:20]}"
    metadata = {"schema": "hcsn-v13-new-head-value-candidate.v1", "task": task, "family": family, "seed": seed,
        "head_id": head_id, "train_prior": prior.tolist(), "value_mean": mean.tolist(), "value_scale": scale.tolist(),
        "stop_calibration": calibrate(vp.max(1), vp.argmax(1) == vl), "future_calibration": calibrate(values, vy),
        "model_directory": str(directory.relative_to(ROOT)), "model_weights_sha256": sha(directory / "weights.pt"),
        "model_normalization_sha256": sha(directory / "NORMALIZATION.npz"), "plan_sha256": sha(run / "PLAN.json"),
        "training_rows": len(tx), "calibration_rows": len(vx), "training_actual_model_updates": train_forwards,
        "calibration_actual_model_updates": val_forwards, "losses": losses, "test_opened": False,
        "calibration_scope": "Historical VAL objects/prefixes; correlated rows, no independent calibration guarantee"}
    torch.save(reader.state_dict(), out / "VALUE.pt")
    metadata["value_weights_sha256"] = sha(out / "VALUE.pt")
    metadata["future_targets_sha256"] = sha(out / "FUTURE_TARGETS.jsonl.gz")
    write(out / "CANDIDATE.json", metadata)


def load(directory):
    metadata = json.loads((directory / "CANDIDATE.json").read_text())
    if sha(directory / "VALUE.pt") != metadata["value_weights_sha256"]:
        raise RuntimeError("Value checkpoint changed")
    core = ROOT / metadata["model_directory"]
    if sha(core / "weights.pt") != metadata["model_weights_sha256"] or sha(core / "NORMALIZATION.npz") != metadata["model_normalization_sha256"]:
        raise RuntimeError("New content target changed")
    model, norm = load_candidate(core)
    reader = ValueNet(); reader.load_state_dict(torch.load(directory / "VALUE.pt", map_location="cpu", weights_only=True))
    return model, norm, reader.eval(), metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "fit"))
    parser.add_argument("--run", type=Path, required=True); parser.add_argument("--models", type=Path)
    parser.add_argument("--publication", type=Path)
    parser.add_argument("--task"); parser.add_argument("--family"); parser.add_argument("--seed", type=int)
    args = parser.parse_args(); configure()
    if args.command == "prepare": prepare(args.run, args.models, args.publication)
    else: fit(args.run, args.task, args.family, args.seed)
