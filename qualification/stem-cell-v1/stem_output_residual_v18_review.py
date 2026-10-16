"""Independent NumPy reviewer of V18 original-feature physical Cell fits.

Imports no Torch or experiment producer. Archived publisher CAL labels are
reopened by this reviewer only; blind labels are never scored or exported.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import numpy as np
from safetensors.numpy import load as load_numpy

ARCHIVE_SHA = "0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7"
DATA_SHA = "50335a2214756c7a9e09fee9ac9ed27ab855ea98635bb0fab0998144165ffb2c"
FEATURE_SHA = "e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490"
SCHEMA = "hepta.stem.output-residual.v18.research"
ARMS = ("frozen", "continued8", "continued80", "continued160", "linear_residual80", "gated_rank4_80")
SEEDS = ("41", "47", "53")
EXPECTED = {
    "frozen": {"weight": (4, 384), "bias": (4,)},
    "linear_residual80": {"base_w": (4, 384), "base_b": (4,), "delta.weight": (4, 384), "delta.bias": (4,)},
    "gated_rank4_80": {"base_w": (4, 384), "base_b": (4,), "down.weight": (4, 384), "down.bias": (4,),
                       "up.weight": (4, 4), "up.bias": (4,), "gate.weight": (1, 384), "gate.bias": (1,)}
}
for name in ("continued8", "continued80", "continued160"):
    EXPECTED[name] = EXPECTED["frozen"]


def check(ok, why):
    if not ok:
        raise ValueError(why)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def pairs_unique(pairs):
    ret = {}
    for key, val in pairs:
        check(key not in ret, "duplicate JSON key")
        ret[key] = val
    return ret


def safe_json(p, max_bytes):
    p = Path(p)
    check(p.is_file() and not p.is_symlink() and p.stat().st_size <= max_bytes, "bounded regular JSON")
    obj = json.loads(p.read_bytes(), object_pairs_hook=pairs_unique)
    json.dumps(obj, allow_nan=False)
    return obj


def forward(weights, arm, z):
    if arm in ("frozen", "continued8", "continued80", "continued160"):
        return z @ weights["weight"].T + weights["bias"]
    fixed = z @ weights["base_w"].T + weights["base_b"]
    if arm == "linear_residual80":
        return fixed + (z @ weights["delta.weight"].T + weights["delta.bias"])
    raw = z @ weights["down.weight"].T + weights["down.bias"]
    down = np.tanh(raw)
    up = down @ weights["up.weight"].T + weights["up.bias"]
    gate = z @ weights["gate.weight"].T + weights["gate.bias"]
    return fixed + (1 / (1 + np.exp(-gate))) * up


def softmax(logits):
    v = logits.astype(np.float64)
    exp = np.exp(v - v.max(axis=1, keepdims=True))
    return exp / exp.sum(axis=1, keepdims=True)


def brier(p, labels):
    ideal = np.eye(4)[labels]
    return float(np.mean(np.sum((p - ideal) ** 2, axis=1)))


def verify(archive, inputs, candidates):
    archive, inputs, candidates = map(Path, (archive, inputs, candidates))
    check(archive.is_file() and not archive.is_symlink() and archive.stat().st_size < 2_000_000
          and digest(archive.read_bytes()) == ARCHIVE_SHA, "original archived source mismatch")
    with ZipFile(archive) as z:
        data = z.read("hepta-public-study/dataset.jsonl")
    check(digest(data) == DATA_SHA, "publisher data mismatch")
    original = [json.loads(line, object_pairs_hook=pairs_unique) for line in data.splitlines()]
    meta = safe_json(inputs / "meta.json", 300_000)
    check(meta["schema"] == SCHEMA and meta["original_archive_sha256"] == ARCHIVE_SHA
          and meta["original_dataset_sha256"] == DATA_SHA and meta["feature_sha256"] == FEATURE_SHA
          and meta["held_labels_absent"] is True and meta["production_authorized"] is False,
          "bad input lineage")
    check({p.name for p in inputs.iterdir()} == {"features.safetensors", "meta.json"},
          "unexpected input files")
    partitions = meta["partitions"]
    check(set(partitions) == {"train", "calibration", "holdout"} and
          [len(partitions[k]) for k in ("train", "calibration", "holdout")] == [64, 32, 32] and
          sorted(sum(partitions.values(), [])) == list(range(128)), "wrong source partitions")
    labeled = {str(i) for k in ("train", "calibration") for i in partitions[k]}
    check(set(meta["labels"]) == labeled and len(meta["case_ids"]) == len(original) == 128,
          "labels leakage or incomplete original cohort")
    for i, row in enumerate(original):
        check(meta["case_ids"][i]["case_id"] == row["case_id"]
              and meta["case_ids"][i]["group"] == row["group"]
              and meta["case_ids"][i]["split"] == row["split"], "source join mismatch")
        if str(i) in labeled:
            check(meta["labels"][str(i)] == row["label"], "changed TRAIN/CAL original label")
    path = inputs / "features.safetensors"
    check(path.is_file() and not path.is_symlink() and digest(path.read_bytes()) == FEATURE_SHA,
          "original mmBERT features changed")
    x = load_numpy(path.read_bytes())["features"]
    check(x.shape == (128, 384) and x.dtype == np.float32 and np.isfinite(x).all(), "feature shape")
    mean = x[partitions["train"][:32]].mean(axis=0).astype(np.float32)
    zz = x - mean
    zz = (zz / np.maximum(np.linalg.norm(zz, axis=1, keepdims=True), 1e-12)).astype(np.float32)
    record = safe_json(candidates / "predictions.json", 2_000_000)
    check(record["schema"] == SCHEMA and record["meta_sha256"] == digest((inputs / "meta.json").read_bytes())
          and record["feature_sha256"] == FEATURE_SHA and record["blind_labels_read"] is False
          and record["blind_scores"] is None and record["future_task_gain"] is None
          and record["independent_retention"] is None and record["production_authorized"] is False
          and record["total_updates"] == 1464 and set(record["seeds"]) == set(SEEDS),
          "overstated study or work ledger")
    inv = record["model_files"]
    check(set(candidates.iterdir()) == {candidates / "predictions.json"} | {candidates / k for k in inv},
          "unexpected candidate artifact")
    check(set(inv) == {f"{seed}-{arm}.safetensors" for seed in SEEDS for arm in ARMS},
          "missing/extra physical tensor checkpoint")
    max_delta = 0.0
    score_summary = {}
    for seed in SEEDS:
        row = record["seeds"][seed]
        check(set(row["calibration"]) == set(row["old_train"]) ==
              set(row["blind_probabilities"]) == set(ARMS), "missing arm outcomes")
        work = row["work"]
        check(set(work) == {"parent"} | (set(ARMS) - {"frozen"})
              and work["parent"]["updates"] == 80
              and {arm: work[arm]["updates"] for arm in ARMS if arm != "frozen"} ==
              {"continued8": 8, "continued80": 80, "continued160": 160,
               "linear_residual80": 80, "gated_rank4_80": 80}, "unpaid SGD updates")
        weights_by_arm = {}
        for arm in ARMS:
            name = f"{seed}-{arm}.safetensors"
            p = candidates / name
            check(p.is_file() and not p.is_symlink() and p.stat().st_size < 400_000
                  and digest(p.read_bytes()) == inv[name]["sha256"], "changed physical tensor")
            weights = load_numpy(p.read_bytes())
            check(set(weights) == set(EXPECTED[arm]) and all(v.shape == EXPECTED[arm][k]
                  and v.dtype == np.float32 and np.isfinite(v).all() for k, v in weights.items()),
                  "wrong physical parameter set")
            expected_scalars = sum(int(v.size) for v in weights.values())
            check(inv[name]["resident_scalars"] == expected_scalars and
                  inv[name]["trainable_scalars_pre_freeze"] ==
                  (0 if arm == "frozen" else expected_scalars - (1540 if "residual" in arm or "gated" in arm else 0)),
                  "incorrect charged parameter inventory")
            weights_by_arm[arm] = weights
        base = weights_by_arm["frozen"]
        for arm in ("linear_residual80", "gated_rank4_80"):
            check(np.array_equal(base["weight"], weights_by_arm[arm]["base_w"]) and
                  np.array_equal(base["bias"], weights_by_arm[arm]["base_b"]),
                  "no-change logits were modified")
        summary = {}
        for arm in ARMS:
            w = weights_by_arm[arm]
            for split, indices, labels in (("calibration", partitions["calibration"],
                                             np.array([meta["labels"][str(i)] for i in partitions["calibration"]])),
                                            ("old_train", partitions["train"][:32],
                                             np.array([meta["labels"][str(i)] for i in partitions["train"][:32]]))):
                p = softmax(forward(w, arm, zz[indices]))
                actual = brier(p, labels)
                reported = row[split][arm]
                check(reported["count"] == len(labels) and
                      abs(actual - reported["brier"]) < 1e-5 and
                      int(np.sum(np.argmax(p, axis=1) == labels)) == reported["correct"],
                      "original label-independent reviewer disagrees with reported score")
                max_delta = max(max_delta, abs(actual - reported["brier"]))
                if split == "calibration":
                    summary[arm] = {"brier": round(actual, 6), "correct": reported["correct"]}
            blind = softmax(forward(w, arm, zz[partitions["holdout"]]))
            recorded = np.array(row["blind_probabilities"][arm], dtype=np.float64)
            check(recorded.shape == (32, 4) and np.isfinite(recorded).all()
                  and np.max(np.abs(blind - recorded)) < 3e-6,
                  "unscored blind model output mismatch")
            max_delta = max(max_delta, float(np.max(np.abs(blind - recorded))))
        # Not a selection reconstruction; this reviewer certifies the descriptive scores only.
        check(row["selected_calibration_only"] in ARMS, "foreign candidate selector")
        score_summary[seed] = summary
    return {"schema": SCHEMA, "verified_original_model_bundles": 18,
            "verified_calibration_rows_per_seed": 32, "verified_blind_rows_per_seed": 32,
            "original_archive_sha256": ARCHIVE_SHA, "maximum_numerical_deviation": max_delta,
            "blind_labels_scored": False, "future_gain": None,
            "production_authorized": False, "summary": score_summary}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--archive", required=True)
    ap.add_argument("--inputs", required=True)
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    receipt = verify(args.archive, args.inputs, args.candidates)
    p = Path(args.out)
    check(p.parent.is_dir() and not p.parent.is_symlink() and not p.exists(), "create-only output")
    with p.open("xb") as f:
        f.write(json.dumps(receipt, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
        f.flush()
        import os
        os.fsync(f.fileno())
    print(json.dumps(receipt, sort_keys=True))
