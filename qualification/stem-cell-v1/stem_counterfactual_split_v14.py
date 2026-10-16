"""Retrospective Cell-split experiment on the original archived mmBERT features.

Research only: no runtime owner, model promotion, network download or synthetic
fallback. Prepare / train / score are deliberately different process entrypoints.
The source preparer sees labels; training receives no held labels. This is process
separation, not an independent label custodian or OS access-control attestation.
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
INPUT_SHA = "d029f906565946216126db39e4ca3f4f14d7ab5a3c297ec2a62639ccdfbf604a"
SOURCE_COMMIT = "4133d6ac5bd3f8d4200c56fffb09e6aba004a084"
SCHEMA = "hepta.stem.counterfactual-split.v14.research"
SEEDS = (41, 47, 53)
ARMS = ("frozen", "continued", "wide", "split")
PROFILES = ARMS + ("shuffled_route", "swapped_route")
STEPS = 80
LR = 0.1
BATCH = 16
WIDTH = 384
CLASSES = 4
PARAMETER_CAP = 4096
MIN_GAIN = 0.01
MAX_OLD_TRAIN_REGRESSION = 0.01


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON field")
        result[key] = value
    return result


def read_json(path):
    path = Path(path)
    require(not path.is_symlink() and path.is_file() and path.stat().st_size <= 8_000_000,
            "bounded regular JSON file required")
    value = json.loads(path.read_bytes(), object_pairs_hook=unique_object)
    canonical(value)  # reject NaN/Infinity even under python -O
    return value


def write_new(path, raw):
    path = Path(path)
    require(path.parent.is_dir() and not path.parent.is_symlink(), "existing real parent required")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def parameter_sha(model):
    digest = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):
        value = tensor.detach().cpu().contiguous().numpy().astype("<f4", copy=False)
        digest.update(name.encode() + b"\0" + canonical(list(value.shape)) + b"\0" + value.tobytes())
    return digest.hexdigest()


def checked_features(x):
    require(isinstance(x, torch.Tensor) and x.device.type == "cpu" and x.dtype == torch.float32
            and x.ndim == 2 and 0 < len(x) <= 128 and x.shape[1] == WIDTH
            and bool(torch.isfinite(x).all()) and bool((x.abs() <= 1e6).all()),
            "finite bounded original-width CPU features required")


@torch.no_grad()
def fit_centers(train):
    """Label-free two-means on TRAIN ONLY, identical first/farthest convention."""
    checked_features(train)
    farthest = (train - train[0]).square().sum(1).argmax()
    centers = torch.stack((train[0], train[farthest])).clone()
    for _ in range(16):
        selected = assign(train, centers)
        updated = centers.clone()
        for cell in (0, 1):
            subset = train[selected == cell]
            if len(subset):
                updated[cell] = subset.mean(0)
        if torch.equal(centers, updated):
            break
        centers = updated
    require(bool(torch.bincount(assign(train, centers), minlength=2).min() > 0),
            "empty routing child; do not invent a split")
    return centers


def assign(x, centers):
    checked_features(x)
    require(tuple(centers.shape) == (2, WIDTH) and centers.dtype == torch.float32
            and centers.device.type == "cpu" and bool(torch.isfinite(centers).all()),
            "two finite frozen centers required")
    distance = x.square().sum(1, keepdim=True) - 2 * x @ centers.T + centers.square().sum(1)
    require(bool(torch.isfinite(distance).all()), "nonfinite routing")
    return distance.argmin(1)


class Split(nn.Module):
    """Two distinct inherited linear Heads, physically selected-row execution."""
    def __init__(self, parent, centers):
        super().__init__()
        self.heads = nn.ModuleList([deepcopy(parent), deepcopy(parent)])
        self.register_buffer("centers", centers.detach().clone())
        self.head_rows = 0
        self.router_rows = 0

    def forward(self, x, routes=None):
        checked_features(x)
        if routes is None:
            routes = assign(x, self.centers)
            self.router_rows += len(x)
        require(routes.device.type == "cpu" and routes.dtype == torch.long and tuple(routes.shape) == (len(x),)
                and bool(((routes == 0) | (routes == 1)).all()), "invalid selected routes")
        out = x.new_zeros((len(x), CLASSES))
        for cell in (0, 1):
            indexes = torch.nonzero(routes == cell, as_tuple=True)[0]
            if len(indexes):
                out = out.index_copy(0, indexes, self.heads[cell](x.index_select(0, indexes)))
                self.head_rows += len(indexes)
        return out


class Wide(nn.Module):
    """Knowledge-preserving unsplit capacity control, no fake padded parameters.

    1540 parent + 2338 rank-6 residual = 3878 trainable scalars.
    Split has 3080 trainable + 768 centroid scalars = 3848 resident scalars.
    Resident gap is 30/3848; optimizer bytes and active FLOPs are NOT matched.
    """
    def __init__(self, parent, seed):
        super().__init__()
        self.parent = deepcopy(parent)
        with torch.random.fork_rng():
            torch.manual_seed(seed ^ 0x1414)
            self.residual = nn.Sequential(nn.Linear(WIDTH, 6), nn.Tanh(), nn.Linear(6, CLASSES))
        nn.init.zeros_(self.residual[-1].weight)
        nn.init.zeros_(self.residual[-1].bias)

    def forward(self, x):
        return self.parent(x) + self.residual(x)


def brier(probability, labels):
    require(probability.ndim == 2 and probability.shape[1] == CLASSES
            and tuple(labels.shape) == (len(probability),), "unaligned score")
    return float(((probability - F.one_hot(labels, CLASSES)) ** 2).sum(1).mean())


def choose_candidate(calibration, old_fit):
    """Prespecified descriptive research selector; no held scores accepted."""
    require(set(calibration) == set(ARMS) and set(old_fit) == set(ARMS), "complete candidate census")
    require(all(type(x) in (int, float) and np.isfinite(x) and 0 <= x <= 2
                for x in (*calibration.values(), *old_fit.values())), "invalid Brier")
    eligible = ["frozen"]
    for arm in ARMS[1:]:
        if (calibration["frozen"] - calibration[arm] > MIN_GAIN
                and old_fit[arm] - old_fit["frozen"] <= MAX_OLD_TRAIN_REGRESSION):
            eligible.append(arm)
    # Minimal memory charge fixed before fitting; not a measured lifecycle cost.
    resident = {"frozen": 1540, "continued": 1540, "wide": 3878, "split": 3848}
    value = {arm: calibration[arm] + 0.01 * resident[arm] / PARAMETER_CAP for arm in eligible}
    selected = min(eligible, key=lambda arm: (value[arm], ARMS.index(arm)))
    # A growing candidate must ALSO exceed the non-growing continuation by margin.
    if selected in ("wide", "split") and calibration["continued"] - calibration[selected] <= MIN_GAIN:
        selected = min((x for x in eligible if x in ("frozen", "continued")),
                       key=lambda arm: (value[arm], ARMS.index(arm)))
    return selected


def fit(model, x, y, schedule):
    checked_features(x)
    require(tuple(y.shape) == (len(x),) and y.dtype == torch.long
            and bool(((y >= 0) & (y < CLASSES)).all()), "original aligned training labels required")
    optimizer = torch.optim.SGD(model.parameters(), lr=LR)
    start_cpu, start_wall = time.process_time_ns(), time.perf_counter_ns()
    start_rows = model.head_rows if isinstance(model, Split) else 0
    for indexes in schedule:
        optimizer.zero_grad(set_to_none=True)
        loss = F.cross_entropy(model(x[indexes]), y[indexes])
        require(bool(torch.isfinite(loss)), "nonfinite learning loss")
        loss.backward()
        optimizer.step()
    return {"steps": len(schedule), "examples": sum(len(i) for i in schedule),
            "process_cpu_ns": time.process_time_ns() - start_cpu,
            "wall_ns": time.perf_counter_ns() - start_wall,
            "selected_head_rows": model.head_rows - start_rows if isinstance(model, Split) else None,
            "schedule_sha256": sha(np.array(schedule, dtype="<i8").tobytes())}


def prepare(archive, out, labels_out):
    archive, out, labels_out = Path(archive), Path(out), Path(labels_out)
    require(not archive.is_symlink() and archive.stat().st_size < 2_000_000, "original small ZIP required")
    raw = archive.read_bytes()
    require(sha(raw) == ARCHIVE_SHA, "wrong original archive; no replacement/synthetic fallback")
    with ZipFile(archive) as z:
        names = z.namelist()
        require(len(names) == len(set(names)), "duplicate archive member")
        data = z.read("hepta-public-study/dataset.jsonl")
        features = z.read("hepta-public-study/execution/frozen-features/features.safetensors")
        manifest = json.loads(z.read("hepta-public-study/execution/frozen-features/manifest.json"))
        require(z.read("hepta-pretrained-source.txt").decode().splitlines()[0] == SOURCE_COMMIT,
                "wrong generating source")
    require(sha(data) == DATA_SHA and sha(features) == FEATURE_SHA
            and manifest["file_sha256"] == FEATURE_SHA and manifest["contains_labels"] is False,
            "original data/feature bytes differ")
    rows = [json.loads(line) for line in data.splitlines()]
    tensors = load_numpy(features)
    require(set(tensors) == {"features"} and tensors["features"].shape == (128, WIDTH)
            and tensors["features"].dtype == np.float32 and np.isfinite(tensors["features"]).all(),
            "wrong original feature tensor")
    require(len(rows) == len(manifest["rows"]) == 128
            and len({r["case_id"] for r in rows}) == 128
            and len({r["group"] for r in rows}) == 128, "incomplete original source roster")
    for row, binding in zip(rows, manifest["rows"]):
        require(all(row[k] == binding[k] for k in ("case_id", "group", "scope", "split", "cell"))
                and sha((json.dumps([row["scope"], row["text"]], ensure_ascii=False, separators=(",", ":")) + "\n").encode()) == binding["input_sha256"]
                and type(row["label"]) is int and 0 <= row["label"] < CLASSES,
                "source identity/input/label mismatch")
    roster = [{"case_id": r["case_id"], "group": r["group"], "split": r["split"]} for r in rows]
    partitions = {s: [i for i, r in enumerate(rows) if r["split"] == s]
                  for s in ("train", "calibration", "holdout")}
    require([len(partitions[s]) for s in partitions] == [64, 32, 32], "original partitions changed")
    require(not out.exists() and not labels_out.exists(), "outputs must be new")
    out.mkdir(mode=0o700)
    # No text or holdout labels in the training directory.
    inputs = {"schema": SCHEMA, "archive_sha256": ARCHIVE_SHA, "feature_sha256": FEATURE_SHA,
              "dataset_sha256": DATA_SHA, "roster": roster, "partitions": partitions,
              "labels": {str(i): r["label"] for i, r in enumerate(rows) if r["split"] != "holdout"},
              "production_authorized": False}
    write_new(out / "features.safetensors", features)
    write_new(out / "input.json", canonical(inputs))
    write_new(labels_out, canonical({"schema": SCHEMA, "archive_sha256": ARCHIVE_SHA,
        "case_ids": [rows[i]["case_id"] for i in partitions["holdout"]],
        "labels": [rows[i]["label"] for i in partitions["holdout"]]}))


def run(inputs, output):
    inputs, output = Path(inputs), Path(output)
    require(sha((inputs / "input.json").read_bytes()) == INPUT_SHA, "original train/label roster changed")
    meta = read_json(inputs / "input.json")
    require(meta["schema"] == SCHEMA and meta["archive_sha256"] == ARCHIVE_SHA
            and meta["production_authorized"] is False, "wrong input binding")
    raw = (inputs / "features.safetensors").read_bytes()
    require(sha(raw) == FEATURE_SHA, "original feature tensor modified")
    p = meta["partitions"]
    require(set(p) == {"train", "calibration", "holdout"}
            and [len(p[s]) for s in ("train", "calibration", "holdout")] == [64, 32, 32]
            and sorted(p["train"] + p["calibration"] + p["holdout"]) == list(range(128))
            and set(meta["labels"]) == {str(i) for i in p["train"] + p["calibration"]},
            "partition overlap or held labels supplied to trainer")
    x = torch.from_numpy(load_numpy(raw)["features"].copy())
    checked_features(x)
    # One physical immutable source tensor; all arms share these encoded inputs.
    y_train = torch.tensor([meta["labels"][str(i)] for i in p["train"]], dtype=torch.long)
    y_cal = torch.tensor([meta["labels"][str(i)] for i in p["calibration"]], dtype=torch.long)
    tx, cx, hx = x[p["train"]], x[p["calibration"]], x[p["holdout"]]
    require(not output.exists(), "candidate output already exists")
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    router_start = time.process_time_ns()
    centers = fit_centers(tx)
    router_cpu = time.process_time_ns() - router_start
    result = {"schema": SCHEMA, "archive_sha256": ARCHIVE_SHA, "feature_sha256": FEATURE_SHA,
              "input_sha256": sha((inputs / "input.json").read_bytes()),
              "source_sha256": sha(Path(__file__).read_bytes()),
              "case_ids": [meta["roster"][i]["case_id"] for i in p["holdout"]],
              "new_encoder_forwards": 0, "production_authorized": False,
              "prospective_efficacy_verified": False, "seeds": {},
              "router_train_counts": torch.bincount(assign(tx, centers), minlength=2).tolist(),
              "router_fit_cpu_ns": router_cpu, "router_state_scalars": centers.numel(),
              "runtime": {"torch": torch.__version__, "numpy": np.__version__}}
    output.mkdir(mode=0o700)
    for seed in SEEDS:
        with torch.random.fork_rng():
            torch.manual_seed(seed)
            parent = nn.Linear(WIDTH, CLASSES)
        rng = np.random.default_rng(seed)
        first = rng.integers(0, 32, size=(STEPS, BATCH)).tolist()
        second = rng.integers(0, 64, size=(STEPS, BATCH)).tolist()
        work = {"parent": fit(parent, tx[:32], y_train[:32], first)}
        parent_hash = parameter_sha(parent)
        models = {"frozen": parent, "continued": deepcopy(parent),
                  "wide": Wide(parent, seed), "split": Split(parent, centers)}
        parent.eval().requires_grad_(False)
        parent.zero_grad(set_to_none=True)
        with torch.no_grad():
            baseline = parent(tx)
            require(torch.equal(models["wide"](tx), baseline), "wide inheritance changed output")
            require(torch.allclose(models["split"](tx), baseline, atol=2e-6, rtol=0),
                    "split inheritance changed output")
        for arm in ARMS[1:]:
            work[arm] = fit(models[arm], tx, y_train, second)
        with torch.no_grad():
            cal = {arm: brier(F.softmax(model(cx), 1), y_cal) for arm, model in models.items()}
            old = {arm: brier(F.softmax(model(tx[:32]), 1), y_train[:32]) for arm, model in models.items()}
            selected = choose_candidate(cal, old)
            probs = {arm: F.softmax(model(hx), 1).tolist() for arm, model in models.items()}
            routes = assign(hx, centers)
            perm = torch.from_numpy(np.random.default_rng(seed ^ 0x1414).permutation(len(hx)))
            probs["shuffled_route"] = F.softmax(models["split"](hx, routes[perm]), 1).tolist()
            probs["swapped_route"] = F.softmax(models["split"](hx, 1 - routes), 1).tolist()
        require(parameter_sha(parent) == parent_hash, "other candidate mutated frozen parent")
        slots = {}
        for arm, model in models.items():
            n = sum(v.numel() for v in model.parameters())
            state = sum(v.numel() for v in model.buffers())
            require(n + state <= PARAMETER_CAP, "physical scalar budget exceeded")
            data = save_torch({k: v.detach().contiguous() for k, v in model.state_dict().items()})
            name = f"{seed}-{arm}.safetensors"
            write_new(output / name, data)
            slots[arm] = {"file": name, "file_sha256": sha(data), "parameter_sha256": parameter_sha(model),
                          "parameter_scalars": n, "gradient_scalars": 0 if arm == "frozen" else n, "optimizer_state_scalars": 0,
                          "buffer_scalars": state, "resident_bytes": 4 * (n + state)}
        result["seeds"][str(seed)] = {"models": slots, "work": work, "calibration_brier": cal,
            "old_train_brier": old, "selected_research_candidate": selected,
            "held_predictions": probs, "held_routes": routes.tolist(),
            "shuffled_routes": routes[perm].tolist(), "frozen_parent_unchanged": True,
            "inheritance_checked": True}
    require(sha((inputs / "features.safetensors").read_bytes()) == FEATURE_SHA, "input mutated")
    # Complete all seeds, frozen candidates and label-free predictions BEFORE scoring.
    write_new(output / "predictions.json", canonical(result))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--archive", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--labels-out", required=True)
    p = sub.add_parser("train")
    p.add_argument("--inputs", required=True)
    p.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.archive, args.out, args.labels_out)
    else:
        run(args.inputs, args.out)


if __name__ == "__main__":
    main()
