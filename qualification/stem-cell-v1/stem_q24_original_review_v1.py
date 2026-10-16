#!/usr/bin/env python3
"""Independent NumPy-only original Q24 artifact and prediction review.

No import of the producer, Torch, model-loader or training implementation.
The observer opens historical public heldout labels only after producer sealing.
This is descriptive evidence, not a model issuer or production qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import stat

import numpy as np
from safetensors.numpy import load_file

D, Q = 32, 1 << 24
H = 8 * Q
ARMS = ("initial", "learned", "cyclic_wrong_labels")
FILES = ("private-raw.safetensors", "private-pca.safetensors", "private-q24.json",
         "private-predictions.json", *(arm + ".safetensors" for arm in ARMS))


def check(flag, message):
    if not flag:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def path_bytes(p):
    p = Path(p)
    info = p.lstat()
    check(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
          and 0 < info.st_size <= 8_000_000, "unsafe or unbounded original artifact")
    data = p.read_bytes()
    post = p.stat()
    check((info.st_ino, info.st_size, info.st_mtime_ns) ==
          (post.st_ino, post.st_size, post.st_mtime_ns), "mutable reviewer input")
    return data


def document(p):
    def unique(pairs):
        value = {}
        for k, v in pairs:
            check(k not in value, "duplicate JSON keys")
            value[k] = v
        return value
    def finite(v):
        n = float(v)
        check(math.isfinite(n), "nonfinite numeric source")
        return n
    return json.loads(path_bytes(p), object_pairs_hook=unique, parse_float=finite,
                      parse_constant=lambda s: (_ for _ in ()).throw(ValueError("nonfinite constant")))


def canonical(value):
    return digest(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode("utf8"))


def independent_projection(fit):
    x = fit.astype(np.float64)
    avg = x.mean(axis=0)
    _, singular, vt = np.linalg.svd(x - avg, full_matrices=False)
    check(singular[31] > 1e-9, "original 32D PCA cannot be fitted")
    axes = vt[:D].T.copy()
    for col in range(D):
        arg = np.argmax(np.abs(axes[:, col]))
        if axes[arg, col] < 0:
            axes[:, col] *= -1
    scale = max(1.0, float(np.max(np.abs((x-avg) @ axes))) / 4.0)
    return avg, axes, scale


def independent_q24(raw, avg, axes, scale):
    encoded = np.rint(((raw.astype(np.float64)-avg) @ axes) / scale * Q)
    check(np.isfinite(encoded).all(), "bad encoded original source")
    return np.clip(encoded, -H, H).astype(np.int64)


def logits(q24_features, params):
    shapes = {"linear_weight": (4,D), "linear_bias": (4,),
              "gate_weight": (4,D), "gate_bias": (4,)}
    check(set(params) == set(shapes)
          and all(params[k].dtype == np.float32 and params[k].shape == shp
                  and np.isfinite(params[k]).all() for k,shp in shapes.items()),
          "invalid physical Cell tensors")
    x = q24_features.astype(np.float32) / Q
    linear = x @ params["linear_weight"].T + params["linear_bias"]
    gate = x @ params["gate_weight"].T + params["gate_bias"]
    return linear / (1. + np.exp(-gate))


def metrics(actual, targets):
    check(actual.shape == (32,4) and np.isfinite(actual).all(), "bad logits")
    y = np.array(targets, dtype=np.int64)
    probs = np.exp(actual - actual.max(axis=1, keepdims=True))
    probs /= probs.sum(axis=1, keepdims=True)
    return {"count":32,
            "correct":int((actual.argmax(1) == y).sum()),
            "accuracy":float((actual.argmax(1) == y).mean()),
            "brier":float(np.square(probs - np.eye(4)[y]).sum(axis=1).mean())}


def review(root, inputs, labels):
    root = Path(root)
    report = document(root / "PRODUCER.json")
    check(report.get("schema") == "hepta.stem-original-q24-bridge.v1"
          and report.get("authority") == "DENY_ALL"
          and report.get("production_authorized") is False
          and report.get("native_q24_cell_executed") is False
          and report.get("heldout_targets_used_in_training") is False
          and report.get("pretrained_issuer_independently_verified") is False
          and report.get("future_utility_verified") is False
          and report.get("encoder_forward_count") == 96
          and report.get("train_only_pca") is True
          and report.get("Q24") == Q
          and report.get("feature_dimension") == 32
          and report.get("cell_params_each_arm") == 264,
          "false original-forward or promotion claim")
    check(report.get("source_class") in ("FIXTURE", "ORIGINAL_PUBLIC_MODERNBERT"),
          "unregistered feature origin")
    if report["source_class"] == "ORIGINAL_PUBLIC_MODERNBERT":
        check(report.get("model_revision") == "8949b909ec900327062f0ebf497f51aef5e6f0c8"
              and isinstance(report.get("model_snapshot_sha256"), str)
              and len(report["model_snapshot_sha256"]) == 64,
              "unbound original pretrained material")
    else:
        check(report.get("model_revision") is None, "synthetic presented as original")
    check(set(report.get("private_files", {})) == set(FILES),
          "missing original experiment files")
    for name in FILES:
        check(digest(path_bytes(root / name)) == report["private_files"][name],
              "original source/Head/prediction SHA mismatch")

    check(isinstance(inputs, dict)
          and set(inputs) == {"schema","intents","fit","heldout","input_id"}
          and inputs["schema"] == "hepta.banking77-four-intent-inputs.v1"
          and inputs["input_id"] ==
              canonical({k:v for k,v in inputs.items() if k != "input_id"}) ==
              report["input_id"], "wrong source/corpus digest")
    fit_rows, held_rows = inputs["fit"], inputs["heldout"]
    check(len(fit_rows) == 64 and len(held_rows) == 32
          and len({r["id"] for r in fit_rows+held_rows}) == 96
          and all(set(r) == {"id","text","label"} for r in fit_rows)
          and all(set(r) == {"id","text"} for r in held_rows)
          and all(type(r["label"]) is int and 0 <= r["label"] < 4 for r in fit_rows),
          "incomplete rows, duplicate IDs or HELD label leakage")

    raw = load_file(str(root / "private-raw.safetensors"))
    pca = load_file(str(root / "private-pca.safetensors"))
    check(set(raw) == {"fit","heldout"} and set(pca) == {"mean","axes","scale"},
          "wrong pretrained source and PCA inventories")
    width = report["hidden_dimension"]
    check(type(width) is int and 32 <= width <= 8192
          and raw["fit"].shape == (64,width) and raw["heldout"].shape == (32,width)
          and raw["fit"].dtype == np.float32 and raw["heldout"].dtype == np.float32
          and np.isfinite(raw["fit"]).all() and np.isfinite(raw["heldout"]).all(),
          "invalid physical original feature material")
    mean, axes, scale = independent_projection(raw["fit"])
    check(pca["mean"].shape == (width,) and pca["axes"].shape == (width,D)
          and pca["scale"].shape == (1,)
          and np.allclose(pca["mean"], mean, rtol=1e-9, atol=1e-9)
          and np.allclose(pca["axes"], axes, rtol=1e-8, atol=1e-8)
          and np.allclose(pca["scale"], [scale], rtol=1e-9, atol=1e-9),
          "PCA not derived from TRAIN-only original features")
    q = document(root / "private-q24.json")
    check(set(q) == {"input_id","fit","heldout"} and q["input_id"] == report["input_id"]
          and [r["id"] for r in q["fit"]] == [r["id"] for r in fit_rows]
          and [r["id"] for r in q["heldout"]] == [r["id"] for r in held_rows]
          and all(set(r) == {"id","label","feature_q24"} for r in q["fit"])
          and all(set(r) == {"id","feature_q24"} for r in q["heldout"])
          and [r["label"] for r in q["fit"]] == [r["label"] for r in fit_rows],
          "input/cell identity mismatch or heldout-label injection")
    def matrix(rows):
        check(all(type(r["feature_q24"]) is list and len(r["feature_q24"]) == D
                  and all(type(v) is int and -H <= v <= H for v in r["feature_q24"])
                  for r in rows), "malformed fixed-point Cell inputs")
        return np.asarray([r["feature_q24"] for r in rows], dtype=np.int64)
    held = matrix(q["heldout"])
    check(np.array_equal(matrix(q["fit"]), independent_q24(raw["fit"],mean,axes,scale))
          and np.array_equal(held, independent_q24(raw["heldout"],mean,axes,scale)),
          "Q24 outputs differ from original projected tensor values")

    predictions = document(root / "private-predictions.json")
    check(set(predictions) == {"input_id","heldout_ids","arms"}
          and predictions["input_id"] == report["input_id"]
          and predictions["heldout_ids"] == [r["id"] for r in held_rows]
          and set(predictions["arms"]) == set(ARMS),
          "predictions were not sealed before target join")
    previous = load_file(str(root / "initial.safetensors"))
    outputs = {}
    for arm in ARMS:
        current = load_file(str(root / (arm+".safetensors")))
        calculated = logits(held, current)
        stored = np.asarray(predictions["arms"][arm], dtype=np.float64)
        check(stored.shape == (32,4) and np.isfinite(stored).all()
              and np.max(np.abs(stored-calculated)) <= 2e-5,
              "independent NumPy calculation disagrees with Torch prediction")
        if arm != "initial":
            check(any(not np.array_equal(current[k], previous[k]) for k in previous),
                  "untrained frozen control mislabelled learned")
        outputs[arm] = calculated

    check(set(labels) == {"schema","input_id","rows"}
          and labels["schema"] == "hepta.banking77-four-intent-labels.v1"
          and labels["input_id"] == report["input_id"]
          and len(labels["rows"]) == 32, "external heldout labels missing/incorrect")
    targets = []
    for gold, row in zip(labels["rows"], held_rows, strict=True):
        check(set(gold) == {"id","label"} and gold["id"] == row["id"]
              and type(gold["label"]) is int and 0 <= gold["label"] <= 3,
              "mismatched publisher observer label")
        targets.append(gold["label"])
    check([targets.count(i) for i in range(4)] == [8,8,8,8],
          "hidden/modified heldout evaluation opportunity")
    return {"schema":"hepta.stem-q24-independent-review.v1",
            "source_class":report["source_class"],"input_id":report["input_id"],
            "original_feature_bytes_reopened":True,"q24_all_96_numerically_recomputed":True,
            "independent_numpy_96_arm_predictions":True,"score":{arm:metrics(out, targets)
            for arm,out in outputs.items()},"weak_four_intent_historical_evaluation":True,
            "native_rust_q24_executed":False,"future_task_gain_verified":False,
            "independent_issuer_verified":False,"stem_winner_verified":False,
            "production_authorized":False,"authority":"DENY_ALL","decision":"HOLD_NO_GO"}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--run", required=True)
    p.add_argument("--inputs", required=True)
    p.add_argument("--observer-labels", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    verdict = review(args.run, document(args.inputs), document(args.observer_labels))
    with Path(args.output).open("x", encoding="utf8") as f:
        json.dump(verdict, f, sort_keys=True, allow_nan=False)
        f.write("\n")


if __name__ == "__main__":
    main()
