"""V18: physical, original-mmBERT-feature frozen-logit residual experiment.

Research only; does not load a model, issue effects, or select a production Cell.
Use prepare in a separate process: the learner never receives the blind labels.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import time
from zipfile import ZipFile

import numpy as np
from safetensors.numpy import load as load_numpy
from safetensors.torch import save as save_torch
import torch
from torch import nn
from torch.nn import functional as F

ARCHIVE_SHA = "0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7"
DATA_SHA = "50335a2214756c7a9e09fee9ac9ed27ab855ea98635bb0fab0998144165ffb2c"
FEATURE_SHA = "e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490"
SOURCE_COMMIT = "4133d6ac5bd3f8d4200c56fffb09e6aba004a084"
SCHEMA = "hepta.stem.output-residual.v18.research"
SEEDS = (41, 47, 53)
ARMS = ("frozen", "continued8", "continued80", "continued160", "linear_residual80", "gated_rank4_80")
STEPS_PARENT, STEPS_MAX, BATCH, LR = 80, 160, 16, 0.1
WIDTH, CLASSES, RANK = 384, 4, 4


def check(ok, reason):
    if not ok:
        raise ValueError(reason)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def nodup(pairs):
    result = {}
    for k, v in pairs:
        check(k not in result, "duplicate JSON key")
        result[k] = v
    return result


def read_json(path):
    p = Path(path)
    check(not p.is_symlink() and p.is_file() and p.stat().st_size <= 1_500_000, "bounded regular JSON required")
    obj = json.loads(p.read_bytes(), object_pairs_hook=nodup)
    canonical(obj)
    return obj


def write_new(path, data):
    p = Path(path)
    check(p.parent.is_dir() and not p.parent.is_symlink() and not p.exists(), "create-only real destination")
    with p.open("xb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def prepare(archive, target):
    archive, target = Path(archive), Path(target)
    check(not archive.is_symlink() and archive.is_file() and archive.stat().st_size < 2_000_000, "bounded archive")
    check(sha(archive.read_bytes()) == ARCHIVE_SHA, "original source ZIP mismatch")
    with ZipFile(archive) as z:
        names = z.namelist()
        check(len(names) == len(set(names)) and len(names) <= 150, "duplicate/oversized ZIP listing")
        data = z.read("hepta-public-study/dataset.jsonl")
        raw_feature = z.read("hepta-public-study/execution/frozen-features/features.safetensors")
        manifest = json.loads(z.read("hepta-public-study/execution/frozen-features/manifest.json"), object_pairs_hook=nodup)
        check(z.read("hepta-pretrained-source.txt").decode().splitlines()[0] == SOURCE_COMMIT,
              "different producer")
    check(sha(data) == DATA_SHA and sha(raw_feature) == FEATURE_SHA and
          manifest["file_sha256"] == FEATURE_SHA and manifest["contains_labels"] is False,
          "wrong immutable data/features")
    rows = [json.loads(line, object_pairs_hook=nodup) for line in data.splitlines()]
    x = load_numpy(raw_feature)["features"]
    check(len(rows) == len(manifest["rows"]) == 128 and
          x.shape == (128, WIDTH) and x.dtype == np.float32 and np.isfinite(x).all(),
          "wrong original feature inventory")
    check(len({r["case_id"] for r in rows}) == len({r["group"] for r in rows}) == 128,
          "duplicated publisher source ID")
    divisions = {s: [] for s in ("train", "calibration", "holdout")}
    public_ids = []
    labels = {}
    for i, (row, binding) in enumerate(zip(rows, manifest["rows"])):
        check(row["split"] in divisions and row["scope"] == "public-ag-news-research" and
              all(row[k] == binding[k] for k in ("case_id", "group", "scope", "split", "cell")) and
              row["observed_at"] is None and row["cell"] in (0, 1), "source identity changed")
        raw = (json.dumps([row["scope"], row["text"]], ensure_ascii=False,
                          separators=(",", ":")) + "\n").encode()
        check(sha(raw) == binding["input_sha256"], "source text/feature join changed")
        check(type(row["label"]) is int and 0 <= row["label"] < CLASSES, "invalid publisher label")
        divisions[row["split"]].append(i)
        public_ids.append({"case_id": row["case_id"], "group": row["group"], "split": row["split"],
                           "input_sha256": binding["input_sha256"]})
        if row["split"] != "holdout":
            labels[str(i)] = row["label"]
    check([len(divisions[k]) for k in divisions] == [64, 32, 32] and
          len(labels) == 96, "noncanonical original split")
    check(not target.exists(), "prepare requires fresh directory")
    target.mkdir(mode=0o700)
    meta = {"schema": SCHEMA, "original_archive_sha256": ARCHIVE_SHA, "source_commit": SOURCE_COMMIT,
            "original_dataset_sha256": DATA_SHA, "feature_sha256": FEATURE_SHA,
            "partitions": divisions, "case_ids": public_ids, "labels": labels,
            "held_labels_absent": True, "future_windows": 0, "independent_source_families": None,
            "production_authorized": False}
    write_new(target / "features.safetensors", raw_feature)
    write_new(target / "meta.json", canonical(meta))
    return meta


def load_inputs(target):
    target = Path(target)
    check(target.is_dir() and not target.is_symlink() and
          {x.name for x in target.iterdir()} == {"features.safetensors", "meta.json"},
          "original inputs contain unexpected/missing files")
    meta = read_json(target / "meta.json")
    check(meta["schema"] == SCHEMA and meta["original_archive_sha256"] == ARCHIVE_SHA
          and meta["feature_sha256"] == FEATURE_SHA and meta["original_dataset_sha256"] == DATA_SHA
          and meta["source_commit"] == SOURCE_COMMIT and meta["held_labels_absent"] is True
          and meta["production_authorized"] is False and meta["future_windows"] == 0,
          "source/effect claim mismatch")
    parts = meta["partitions"]
    check(set(parts) == {"train", "calibration", "holdout"} and
          [len(parts[s]) for s in ("train", "calibration", "holdout")] == [64, 32, 32] and
          sorted(sum(parts.values(), [])) == list(range(128)), "source partitions not exact")
    label_ids = {str(i) for s in ("train", "calibration") for i in parts[s]}
    check(set(meta["labels"]) == label_ids and all(type(n) is int and 0 <= n < CLASSES for n in meta["labels"].values()),
          "blind label leakage or bad training labels")
    case_ids = meta["case_ids"]
    check(len(case_ids) == 128 and len({v["case_id"] for v in case_ids}) == 128 and
          len({v["group"] for v in case_ids}) == 128 and
          all(case_ids[i]["split"] == s for s in parts for i in parts[s]), "source groups changed")
    path = target / "features.safetensors"
    check(not path.is_symlink() and path.is_file() and path.stat().st_size == 196688 and
          sha(path.read_bytes()) == FEATURE_SHA, "original feature tensor mutated")
    features = load_numpy(path.read_bytes())
    check(set(features) == {"features"}, "unexpected original feature tensors")
    x = features["features"]
    check(x.dtype == np.float32 and x.shape == (128, WIDTH) and np.isfinite(x).all(),
          "feature tensor invalid")
    return torch.from_numpy(x.copy()), meta


def norm(x, mean):
    return F.normalize(x - mean, p=2, dim=1, eps=1e-12)


def new_linear():
    return nn.Linear(WIDTH, CLASSES)


class LinearResidual(nn.Module):
    """Frozen no-change logits + trainable zero-initialized additive linear delta."""
    def __init__(self, parent):
        super().__init__()
        self.register_buffer("base_w", parent.weight.detach().clone())
        self.register_buffer("base_b", parent.bias.detach().clone())
        self.delta = new_linear()
        nn.init.zeros_(self.delta.weight)
        nn.init.zeros_(self.delta.bias)

    def forward(self, x):
        return F.linear(x, self.base_w, self.base_b) + self.delta(x)


class GatedRank4(nn.Module):
    """Frozen logits + gated rank-4 residual, exact zero initial function change."""
    def __init__(self, parent):
        super().__init__()
        self.register_buffer("base_w", parent.weight.detach().clone())
        self.register_buffer("base_b", parent.bias.detach().clone())
        self.down = nn.Linear(WIDTH, RANK)
        self.up = nn.Linear(RANK, CLASSES)
        self.gate = nn.Linear(WIDTH, 1)
        nn.init.zeros_(self.up.weight)
        nn.init.zeros_(self.up.bias)
        nn.init.zeros_(self.gate.weight)
        nn.init.zeros_(self.gate.bias)

    def forward(self, x):
        return (F.linear(x, self.base_w, self.base_b)
                + torch.sigmoid(self.gate(x)) * self.up(torch.tanh(self.down(x))))


def brier(prob, y):
    return float(((prob - F.one_hot(y, CLASSES)) ** 2).sum(1).mean())


def fit(model, x, y, schedule):
    cpu, wall = time.process_time_ns(), time.perf_counter_ns()
    opt = torch.optim.SGD(model.parameters(), lr=LR)
    for indexes in schedule:
        opt.zero_grad(set_to_none=True)
        loss = F.cross_entropy(model(x[indexes]), y[indexes])
        check(bool(torch.isfinite(loss)), "nonfinite SGD")
        loss.backward()
        opt.step()
    return {"updates": len(schedule), "examples": sum(len(i) for i in schedule),
            "cpu_ns": time.process_time_ns() - cpu, "wall_ns": time.perf_counter_ns() - wall}


def tensors(model):
    return {k: v.detach().cpu().contiguous().to(torch.float32) for k, v in model.state_dict().items()}


def score_model(model, x, y):
    with torch.no_grad():
        prob = torch.softmax(model(x), dim=-1)
    return {"brier": brier(prob, y), "correct": int((prob.argmax(1) == y).sum()), "count": len(y)}


def research_selector(stats, old):
    """Descriptive calibration-only: extra frozen-residual capability must beat strong continuation."""
    check(set(stats) == set(old) == set(ARMS), "incomplete candidate scoring")
    for key in ARMS:
        check(np.isfinite(stats[key]["brier"]) and np.isfinite(old[key]["brier"]), "nonfinite score")
    strong = "continued160"
    winner = min(ARMS, key=lambda key: (stats[key]["brier"], ARMS.index(key)))
    if winner in ("linear_residual80", "gated_rank4_80"):
        if (stats[strong]["brier"] - stats[winner]["brier"] <= 0.01 or
            old[winner]["brier"] - old[strong]["brier"] > 0.01):
            return strong
    return winner


def run(inputs, target):
    inputs, target = Path(inputs), Path(target)
    x, meta = load_inputs(inputs)
    check(not target.exists(), "candidate folder must be new")
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    parts = meta["partitions"]
    train, cal, blind = (x[parts[k]] for k in ("train", "calibration", "holdout"))
    y = torch.tensor([meta["labels"][str(i)] for i in parts["train"]], dtype=torch.long)
    cy = torch.tensor([meta["labels"][str(i)] for i in parts["calibration"]], dtype=torch.long)
    check(len(y) == 64 and len(cy) == 32, "expected only training/calibration labels")
    mean = train[:32].mean(0)
    z, cz, hz = (norm(a, mean) for a in (train, cal, blind))
    target.mkdir(mode=0o700)
    result = {"schema": SCHEMA, "source_sha256": sha(Path(__file__).read_bytes()),
              "meta_sha256": sha((inputs / "meta.json").read_bytes()), "feature_sha256": FEATURE_SHA,
              "protocol": {"seeds": SEEDS, "arms": ARMS, "parent_steps": STEPS_PARENT,
                           "max_steps": STEPS_MAX, "batch": BATCH, "lr": LR,
                           "rank": RANK, "train_rows": 64, "calibration_rows": 32,
                           "unscored_blind_rows": 32},
              "blind_labels_read": False, "blind_scores": None, "future_task_gain": None,
              "independent_retention": None, "production_authorized": False,
              "total_updates": 0, "model_files": {}, "seeds": {}}
    for seed in SEEDS:
        with torch.random.fork_rng():
            torch.manual_seed(seed)
            parent = new_linear()
        g0 = torch.Generator().manual_seed(seed ^ 0x1800)
        sched0 = [torch.randperm(32, generator=g0)[:BATCH] for _ in range(STEPS_PARENT)]
        work = {"parent": fit(parent, z[:32], y[:32], sched0)}
        parent.requires_grad_(False)
        before = tensors(parent)
        with torch.no_grad():
            base_logits = parent(cz).clone()
        g1 = torch.Generator().manual_seed(seed ^ 0x4800)
        sched = [torch.randperm(64, generator=g1)[:BATCH] for _ in range(STEPS_MAX)]
        with torch.random.fork_rng():
            torch.manual_seed(seed ^ 0xF00D)
            models = {"frozen": deepcopy(parent), "continued8": deepcopy(parent),
                      "continued80": deepcopy(parent), "continued160": deepcopy(parent),
                      "linear_residual80": LinearResidual(parent),
                      "gated_rank4_80": GatedRank4(parent)}
        for name in ("linear_residual80", "gated_rank4_80"):
            with torch.no_grad():
                check(torch.equal(models[name](cz), base_logits), "initially nonzero output residual")
        for arm, updates in (("continued8", 8), ("continued80", 80), ("continued160", 160),
                             ("linear_residual80", 80), ("gated_rank4_80", 80)):
            models[arm].requires_grad_(True)
            if arm.endswith("residual80") or arm == "gated_rank4_80":
                # Keep the original logits frozen, train only independent residual parameters.
                check(not models[arm].base_w.requires_grad and not models[arm].base_b.requires_grad,
                      "baseline buffer became trainable")
            work[arm] = fit(models[arm], z, y, sched[:updates])
        for model in models.values():
            model.eval().requires_grad_(False)
        check(all(torch.equal(tensors(parent)[key], before[key]) for key in before),
              "frozen parent mutated")
        stats, old, blind_probs, inventory = {}, {}, {}, {}
        for arm, model in models.items():
            stats[arm] = score_model(model, cz, cy)
            old[arm] = score_model(model, z[:32], y[:32])
            with torch.no_grad():
                blind_probs[arm] = torch.softmax(model(hz), dim=1).tolist()
            raw = save_torch(tensors(model))
            name = f"{seed}-{arm}.safetensors"
            write_new(target / name, raw)
            par = sum(p.numel() for p in model.parameters())
            buf = sum(b.numel() for b in model.buffers())
            check(par + buf <= 5200, "unexpected resident scalar budget")
            inventory[name] = {"sha256": sha(raw), "trainable_scalars_pre_freeze": 0 if arm == "frozen" else par,
                               "resident_scalars": par + buf, "state_bytes": len(raw)}
        result["total_updates"] += sum(w["updates"] for w in work.values())
        result["model_files"].update(inventory)
        result["seeds"][str(seed)] = {"work": work, "calibration": stats, "old_train": old,
                                    "blind_probabilities": blind_probs,
                                    "selected_calibration_only": research_selector(stats, old),
                                    "parent_state_preserved": True}
    check(sha((inputs / "features.safetensors").read_bytes()) == FEATURE_SHA,
          "original feature changed during training")
    write_new(target / "predictions.json", canonical(result))
    return result


def sanitized(result):
    return {"schema": result["schema"], "source_sha256": result["source_sha256"],
            "feature_sha256": result["feature_sha256"], "total_updates": result["total_updates"],
            "blind_labels_read": False, "blind_scores": None, "production_authorized": False,
            "seeds": {s: {"calibration": v["calibration"], "old_train": v["old_train"],
                           "selected_calibration_only": v["selected_calibration_only"],
                           "work": v["work"]} for s, v in result["seeds"].items()}}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("prepare")
    a.add_argument("--archive", required=True)
    a.add_argument("--out", required=True)
    b = sub.add_parser("run")
    b.add_argument("--inputs", required=True)
    b.add_argument("--out", required=True)
    args = p.parse_args()
    if args.cmd == "prepare":
        prepare(args.archive, args.out)
    else:
        val = run(args.inputs, args.out)
        print(json.dumps(sanitized(val), sort_keys=True))
