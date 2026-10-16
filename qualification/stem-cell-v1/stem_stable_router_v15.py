"""V15 TRAIN-only stabilization and cross-fitted task routing; no held-label access.

Uses the exact V14 input contract. Calibration is diagnostic/selection data, NOT
independent efficacy. Blind predictions are sealed but never scored here. Original
owners and V14 stay unchanged. Cross-fitting costs are explicitly charged.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
import time

import numpy as np
from safetensors.numpy import load
from safetensors.torch import save
import torch
from torch import nn
from torch.nn import functional as F

import stem_counterfactual_split_v14 as old

SCHEMA = "hepta.stem.stable-router.v15.research"
ARMS = ("frozen", "continued", "wide", "centroid", "task")
PROFILES = ARMS + ("centroid_swapped", "centroid_shuffled", "task_swapped")
BUDGET = {"frozen": 1540, "continued": 1540, "wide": 4267,
          "centroid": 3848, "task": 4233}
V14_SOURCE = "7e325bf6a08216b1bb497ee3910682b4155705b56fd77534251a42f590112e86"
PROTOCOL = {"schema": SCHEMA, "steps": 80, "batch": 16, "learning_rate": .1,
            "seeds": [41, 47, 53], "folds": 4, "normalizer": "old-TRAIN-mean then row L2",
            "gate_target": "smaller out-of-fold expert label NLL; ties choose zero",
            "gate_loss": "binary cross entropy", "wide_rank": 7, "resident_cap": 4352,
            "held_labels_permitted": False, "prospective_efficacy_verified": False}
require = old.require


def normalized(x, mean):
    old.checked_features(x)
    require(mean.shape == (384,) and mean.dtype == torch.float32
            and mean.device.type == "cpu" and bool(torch.isfinite(mean).all()), "invalid normalizer")
    z = x - mean
    return z / z.norm(dim=1, keepdim=True).clamp_min(1e-12)


def partition(groups):
    require(len(groups) == 64 and len(set(groups)) == 64, "64 unique original TRAIN IDs required")
    ordered = sorted(range(64), key=lambda i: old.sha(groups[i].encode()))
    return [sorted(ordered[k::4]) for k in range(4)]


def centers_for(x):
    centers = old.fit_centers(x)
    # Deterministic slot convention across folds, not guaranteed semantic alignment.
    direction = torch.linspace(-1., 1., 384)
    return centers[torch.argsort(centers @ direction, stable=True)]


class Wide(nn.Module):
    def __init__(self, parent, seed):
        super().__init__()
        self.parent = deepcopy(parent)
        with torch.random.fork_rng():
            torch.manual_seed(seed ^ 0x1515)
            self.residual = nn.Sequential(nn.Linear(384, 7), nn.Tanh(), nn.Linear(7, 4))
        nn.init.zeros_(self.residual[-1].weight)
        nn.init.zeros_(self.residual[-1].bias)

    def forward(self, x):
        return self.parent(x) + self.residual(x)


def linear(seed, classes=4):
    with torch.random.fork_rng():
        torch.manual_seed(seed)
        return nn.Linear(384, classes)


def measured_fit(model, x, y, batches, *, binary=False):
    old.checked_features(x)
    require(y.dtype == torch.long and y.shape == (len(x),)
            and bool(((y >= 0) & (y < (2 if binary else 4))).all()), "invalid TRAIN targets")
    optimizer = torch.optim.SGD(model.parameters(), lr=.1)
    def loss_at(features, targets):
        scores = model(features)
        if binary:
            return F.binary_cross_entropy_with_logits(scores.squeeze(1), targets.float())
        return F.cross_entropy(scores, targets)
    with torch.no_grad():
        start_loss = float(loss_at(x, y))
    start_rows = model.head_rows if isinstance(model, old.Split) else None
    start_cpu, start_wall = time.process_time_ns(), time.perf_counter_ns()
    max_gradient = 0.
    for ix in batches:
        optimizer.zero_grad(set_to_none=True)
        loss = loss_at(x[ix], y[ix])
        require(bool(torch.isfinite(loss)), "nonfinite training loss")
        loss.backward()
        grad = float(torch.sqrt(sum(p.grad.square().sum() for p in model.parameters() if p.grad is not None)))
        require(np.isfinite(grad), "nonfinite training gradient")
        max_gradient = max(max_gradient, grad)
        optimizer.step()
    cpu, wall = time.process_time_ns() - start_cpu, time.perf_counter_ns() - start_wall
    actual_rows = model.head_rows - start_rows if start_rows is not None else None
    with torch.no_grad():
        end_loss = float(loss_at(x, y))
    require(np.isfinite(end_loss), "nonfinite trained model")
    return {"steps": len(batches), "examples": sum(map(len, batches)),
            "schedule_sha256": old.sha(np.asarray(batches, dtype="<i8").tobytes()),
            "cpu_ns": cpu, "wall_ns": wall, "loss_before": start_loss, "loss_after": end_loss,
            "max_gradient_norm": max_gradient, "selected_head_rows": actual_rows}


def choose(cal, retention):
    require(set(cal) == set(retention) == set(ARMS), "incomplete selector input")
    require(all(type(v) in (int, float) and np.isfinite(v) and 0 <= v <= 2
                for v in (*cal.values(), *retention.values())), "invalid selector metric")
    eligible = ["frozen"] + [a for a in ARMS[1:] if cal["frozen"] - cal[a] > .01
                             and retention[a] - retention["frozen"] <= .01]
    rank = lambda a: (cal[a] + .01 * BUDGET[a] / 4352, ARMS.index(a))
    selected = min(eligible, key=rank)
    if selected not in ("frozen", "continued") and cal["continued"] - cal[selected] <= .01:
        selected = min([a for a in eligible if a in ("frozen", "continued")], key=rank)
    return selected


def profile_logits(models, gate, x, seed):
    split = models["centroid"]
    route = old.assign(x, split.centers)
    task = (gate(x).squeeze(1) > 0).long()
    perm = torch.from_numpy(np.random.default_rng(seed ^ 0x1515).permutation(len(x)))
    routes = {"centroid": route, "task": task, "centroid_swapped": 1 - route,
              "centroid_shuffled": route[perm], "task_swapped": 1 - task}
    values = {a: models[a](x) for a in ("frozen", "continued", "wide")}
    for a, r in routes.items():
        values[a] = split(x, r)
    return values, {a: r.tolist() for a, r in routes.items()}


def read_inputs(root):
    root = Path(root)
    require(not root.is_symlink() and root.is_dir(), "real input directory required")
    require(old.sha(Path(old.__file__).read_bytes()) == V14_SOURCE, "V14 source changed")
    require(old.sha((root / "input.json").read_bytes()) == old.INPUT_SHA, "original input changed")
    meta = old.read_json(root / "input.json")
    raw = (root / "features.safetensors").read_bytes()
    require(old.sha(raw) == old.FEATURE_SHA, "original feature bytes changed")
    x = torch.from_numpy(load(raw)["features"].copy())
    old.checked_features(x)
    parts = meta["partitions"]
    require(set(meta["labels"]) == {str(i) for i in parts["train"] + parts["calibration"]},
            "trainer must not receive held labels")
    return x, meta


def run(inputs, output):
    x, meta = read_inputs(inputs)
    output = Path(output)
    require(not output.exists(), "new output required")
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    parts = meta["partitions"]
    tx, cx, bx = (x[parts[k]] for k in ("train", "calibration", "holdout"))
    y = torch.tensor([meta["labels"][str(i)] for i in parts["train"]])
    cy = torch.tensor([meta["labels"][str(i)] for i in parts["calibration"]])
    groups = [meta["roster"][i]["group"] for i in parts["train"]]
    folds = partition(groups)
    mean = tx[:32].mean(0)
    z, cz, bz = (normalized(a, mean) for a in (tx, cx, bx))
    output.mkdir(mode=0o700)
    result = {"schema": SCHEMA, "protocol": PROTOCOL, "protocol_sha256": old.sha(old.canonical(PROTOCOL)),
              "producer_sha256": old.sha(Path(__file__).read_bytes()), "v14_source_sha256": V14_SOURCE,
              "archive_sha256": old.ARCHIVE_SHA, "input_sha256": old.INPUT_SHA,
              "feature_sha256": old.FEATURE_SHA, "folds": folds, "models": {}, "seeds": {},
              "new_encoder_forwards": 0, "held_labels_read": False, "held_scores": None,
              "production_authorized": False, "prospective_efficacy_verified": False,
              "source_families_independently_verified": False,
              "raw_train_norm_range": [float(tx.norm(dim=1).min()), float(tx.norm(dim=1).max())],
              "normalized_train_max_norm": float(z.norm(dim=1).max()),
              "runtime": {"torch": torch.__version__, "numpy": np.__version__}}
    def store(name, state):
        state = {k: v.detach().contiguous() for k, v in state.items()}
        data = save(state)
        old.write_new(output / f"{name}.safetensors", data)
        result["models"][name] = {"sha256": old.sha(data), "scalars": sum(t.numel() for t in state.values())}
    store("normalizer", {"mean": mean})
    for seed in (41, 47, 53):
        rng = np.random.default_rng(seed)
        first = rng.integers(0, 32, (80, 16)).tolist()
        second = rng.integers(0, 64, (80, 16)).tolist()
        work = {}
        raw_parent = linear(seed)
        work["raw_parent"] = measured_fit(raw_parent, tx[:32], y[:32], first)
        raw_continue = deepcopy(raw_parent)
        work["raw_continue"] = measured_fit(raw_continue, tx, y, second)
        parent = linear(seed)
        work["parent"] = measured_fit(parent, z[:32], y[:32], first)
        parent_hash = old.parameter_sha(parent)
        models = {"frozen": parent, "continued": deepcopy(parent), "wide": Wide(parent, seed),
                  "centroid": old.Split(parent, centers_for(z))}
        with torch.no_grad():
            for a in ("continued", "wide", "centroid"):
                require(torch.allclose(models[a](z), parent(z), atol=2e-6, rtol=0), "inheritance mismatch")
        for a in ("continued", "wide", "centroid"):
            work[a] = measured_fit(models[a], z, y, second)
        oof_logits = torch.empty((64, 2, 4))
        for fold_id, excluded in enumerate(folds):
            train = [i for i in range(64) if i not in excluded]
            old_train = [i for i in range(32) if i not in excluded]
            inner_mean = tx[old_train].mean(0)
            inner_z = normalized(tx, inner_mean)
            irng = np.random.default_rng(seed + fold_id * 1009)
            inner = linear(seed)
            k = f"fold{fold_id}"
            work[k + "_parent"] = measured_fit(inner, inner_z[old_train], y[old_train],
                irng.integers(0, len(old_train), (80, 16)).tolist())
            split = old.Split(inner, centers_for(inner_z[train]))
            work[k + "_split"] = measured_fit(split, inner_z[train], y[train],
                irng.integers(0, len(train), (80, 16)).tolist())
            with torch.no_grad():
                oof_logits[excluded] = torch.stack([h(inner_z[excluded]) for h in split.heads], 1)
            store(f"{seed}-{k}-parent", inner.state_dict())
            store(f"{seed}-{k}-split", split.state_dict())
            store(f"{seed}-{k}-normalizer", {"mean": inner_mean})
        # Every teacher prediction comes from experts with this row excluded.
        nll = -oof_logits.log_softmax(2).gather(2, y[:, None, None].expand(-1, 2, 1)).squeeze(2)
        targets = (nll[:, 1] < nll[:, 0]).long()
        gate = linear(seed, 1)
        nn.init.zeros_(gate.weight)
        nn.init.zeros_(gate.bias)
        work["task_gate"] = measured_fit(gate, z, targets, second, binary=True)
        require(old.parameter_sha(parent) == parent_hash, "frozen parent was mutated")
        for a, model in {**models, "raw_parent": raw_parent, "raw_continue": raw_continue, "gate": gate}.items():
            store(f"{seed}-{a}", model.state_dict())
        with torch.no_grad():
            cal_logits, cal_routes = profile_logits(models, gate, cz, seed)
            old_logits, _ = profile_logits(models, gate, z[:32], seed)
            blind_logits, blind_routes = profile_logits(models, gate, bz, seed)
            cal_prob = {a: v.softmax(1) for a, v in cal_logits.items()}
            cal_brier = {a: old.brier(cal_prob[a], cy) for a in ARMS}
            old_brier = {a: old.brier(old_logits[a].softmax(1), y[:32]) for a in ARMS}
            scores = {a: {"correct": int((v.argmax(1) == cy).sum()), "brier": old.brier(v, cy)}
                      for a, v in cal_prob.items()}
            raw_cal = {a: {"correct": int((m(cx).argmax(1) == cy).sum()),
                          "brier": old.brier(m(cx).softmax(1), cy)}
                       for a, m in (("raw_parent", raw_parent), ("raw_continue", raw_continue))}
        result["seeds"][str(seed)] = {"work": work, "oof_logits": oof_logits.tolist(),
            "oof_targets": targets.tolist(), "oof_target_counts": torch.bincount(targets, minlength=2).tolist(),
            "calibration": scores, "raw_calibration": raw_cal, "old_train_brier": old_brier,
            "selected_research_candidate": choose(cal_brier, old_brier), "calibration_routes": cal_routes,
            "calibration_probabilities": {a: v.tolist() for a, v in cal_prob.items()},
            "blind_probabilities": {a: v.softmax(1).tolist() for a, v in blind_logits.items()},
            "blind_routes": blind_routes, "frozen_parent_unchanged": True}
    require(read_inputs(inputs)[1] == meta, "input changed during study")
    old.write_new(output / "sealed.json", old.canonical(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    run(args.inputs, args.output)
