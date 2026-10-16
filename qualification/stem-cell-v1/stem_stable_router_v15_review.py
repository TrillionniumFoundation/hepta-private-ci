"""Independent NumPy replay of V15 models, cross-fit targets and calibration.

No Torch/producer import and no archive or held-label reader. A successful result
proves numerical consistency, not gradient re-execution, label custody or efficacy.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from safetensors.numpy import load

SCHEMA = "hepta.stem.stable-router.v15.research"
INPUT = "d029f906565946216126db39e4ca3f4f14d7ab5a3c297ec2a62639ccdfbf604a"
FEATURE = "e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490"
ARCHIVE = "0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7"
V14 = "7e325bf6a08216b1bb497ee3910682b4155705b56fd77534251a42f590112e86"
ARMS = ("frozen", "continued", "wide", "centroid", "task")
PROFILES = ARMS + ("centroid_swapped", "centroid_shuffled", "task_swapped")
CAPACITY = {"frozen": 1540, "continued": 1540, "wide": 4267, "centroid": 3848, "task": 4233}
PROTOCOL = {"schema": SCHEMA, "steps": 80, "batch": 16, "learning_rate": .1,
            "seeds": [41, 47, 53], "folds": 4, "normalizer": "old-TRAIN-mean then row L2",
            "gate_target": "smaller out-of-fold expert label NLL; ties choose zero",
            "gate_loss": "binary cross entropy", "wide_rank": 7, "resident_cap": 4352,
            "held_labels_permitted": False, "prospective_efficacy_verified": False}


def need(condition, reason):
    if not condition:
        raise ValueError(reason)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def pairs(items):
    result = {}
    for k, v in items:
        need(k not in result, "duplicate field")
        result[k] = v
    return result


def raw(path):
    path = Path(path)
    need(not path.is_symlink() and path.is_file() and path.stat().st_size <= 4_000_000,
         "bounded regular evidence required")
    return path.read_bytes()


def read(path):
    value = json.loads(raw(path), object_pairs_hook=pairs)
    encode(value)
    return value


def norm(x, mean):
    z = x - mean
    return z / np.maximum(np.linalg.norm(z, axis=1, keepdims=True), 1e-12)


def assign(x, centers):
    distance = (x * x).sum(1, keepdims=True) - 2 * x @ centers.T + (centers * centers).sum(1)
    return distance.argmin(1)


def centers(x):
    current = np.stack([x[0], x[((x - x[0]) ** 2).sum(1).argmax()]])
    for _ in range(16):
        groups = assign(x, current)
        updated = current.copy()
        for k in (0, 1):
            if np.any(groups == k):
                updated[k] = x[groups == k].mean(0)
        if np.array_equal(updated, current):
            break
        current = updated
    return current[np.argsort(current @ np.linspace(-1, 1, 384, dtype=np.float32), kind="stable")]


def softmax(x):
    x = x.astype(np.float64)
    e = np.exp(x - x.max(-1, keepdims=True))
    return e / e.sum(-1, keepdims=True)


def linear(s, x, prefix=""):
    return x @ s[prefix + "weight"].T + s[prefix + "bias"]


def forward(states, x, seed):
    split = states["centroid"]
    r = assign(x, split["centers"])
    t = (linear(states["gate"], x)[:, 0] > 0).astype(int)
    shuffled = r[np.random.default_rng(seed ^ 0x1515).permutation(len(x))]
    routes = {"centroid": r, "task": t, "centroid_swapped": 1 - r,
              "centroid_shuffled": shuffled, "task_swapped": 1 - t}
    out = {a: linear(states[a], x) for a in ("frozen", "continued")}
    s = states["wide"]
    hidden = np.tanh(linear(s, x, "residual.0."))
    out["wide"] = linear(s, x, "parent.") + linear(s, hidden, "residual.2.")
    for name, route in routes.items():
        v = np.empty((len(x), 4), dtype=np.float32)
        for k in (0, 1):
            ix = np.flatnonzero(route == k)
            v[ix] = linear(split, x[ix], f"heads.{k}.")
        out[name] = v
    return {a: softmax(v) for a, v in out.items()}, {a: v.tolist() for a, v in routes.items()}


def brier(p, y):
    return float(((p - np.eye(4)[y]) ** 2).sum(1).mean())


def choose(cal, old):
    eligible = ["frozen"] + [a for a in ARMS[1:] if cal["frozen"] - cal[a] > .01
                             and old[a] - old["frozen"] <= .01]
    rank = lambda a: (cal[a] + .01 * CAPACITY[a] / 4352, ARMS.index(a))
    win = min(eligible, key=rank)
    if win not in ("frozen", "continued") and cal["continued"] - cal[win] <= .01:
        win = min([a for a in eligible if a in ("frozen", "continued")], key=rank)
    return win


def review(inputs, candidates):
    inputs, candidates = Path(inputs), Path(candidates)
    meta = read(inputs / "input.json")
    need(digest(raw(inputs / "input.json")) == INPUT, "original input/labels changed")
    feature_bytes = raw(inputs / "features.safetensors")
    need(digest(feature_bytes) == FEATURE, "original feature file changed")
    original = load(feature_bytes)["features"]
    parts = meta["partitions"]
    tx, cx, bx = (original[parts[a]] for a in ("train", "calibration", "holdout"))
    y = np.asarray([meta["labels"][str(i)] for i in parts["train"]])
    cy = np.asarray([meta["labels"][str(i)] for i in parts["calibration"]])
    need(set(meta["labels"]) == {str(i) for i in parts["train"] + parts["calibration"]}, "held labels present")
    report = read(candidates / "sealed.json")
    need(report["schema"] == SCHEMA and report["protocol"] == PROTOCOL
         and report["protocol_sha256"] == digest(encode(PROTOCOL))
         and report["input_sha256"] == INPUT and report["archive_sha256"] == ARCHIVE
         and report["feature_sha256"] == FEATURE and report["v14_source_sha256"] == V14,
         "protocol or source mismatch")
    need(report["producer_sha256"] == digest(raw(Path(__file__).with_name("stem_stable_router_v15.py")))
         and digest(raw(Path(__file__).with_name("stem_counterfactual_split_v14.py"))) == V14,
         "producer source changed")
    need(report["held_labels_read"] is False and report["held_scores"] is None
         and report["production_authorized"] is False and report["new_encoder_forwards"] == 0
         and report["prospective_efficacy_verified"] is False
         and report["source_families_independently_verified"] is False, "false capability claim")
    need(set(report["seeds"]) == {"41", "47", "53"}, "wrong seeds")
    ordered = sorted(range(64), key=lambda i: digest(meta["roster"][parts["train"][i]]["group"].encode()))
    folds = [sorted(ordered[k::4]) for k in range(4)]
    need(folds == report["folds"], "fold source changed")
    expected_names = {"normalizer"}
    for seed in (41, 47, 53):
        expected_names.update(f"{seed}-{a}" for a in ("frozen", "continued", "wide", "centroid", "gate", "raw_parent", "raw_continue"))
        expected_names.update(f"{seed}-fold{k}-{a}" for k in range(4) for a in ("parent", "split", "normalizer"))
    need(set(report["models"]) == expected_names, "wrong model inventory")
    need({p.name for p in candidates.iterdir()} == {f"{a}.safetensors" for a in expected_names} | {"sealed.json"},
         "unexpected or missing candidate file")
    states = {}
    base = {"weight": (4, 384), "bias": (4,)}
    split_shape = {"centers": (2, 384), **{f"heads.{k}.{n}": s for k in (0, 1) for n, s in base.items()}}
    for name in sorted(expected_names):
        data = raw(candidates / f"{name}.safetensors")
        slot = report["models"][name]
        need(digest(data) == slot["sha256"], "model bytes changed")
        s = load(data)
        if name.endswith("normalizer"):
            shapes = {"mean": (384,)}
        elif name.endswith("gate"):
            shapes = {"weight": (1, 384), "bias": (1,)}
        elif name.endswith("wide"):
            shapes = {"parent.weight": (4, 384), "parent.bias": (4,), "residual.0.weight": (7, 384),
                      "residual.0.bias": (7,), "residual.2.weight": (4, 7), "residual.2.bias": (4,)}
        elif name.endswith(("centroid", "split")):
            shapes = split_shape
        else:
            shapes = base
        need(set(s) == set(shapes) and all(v.dtype == np.float32 and v.shape == shapes[k]
             and np.isfinite(v).all() for k, v in s.items()), "invalid tensor shape/dtype/value")
        need(sum(v.size for v in s.values()) == slot["scalars"], "false parameter count")
        states[name] = s
    mean = tx[:32].mean(0)
    need(np.allclose(states["normalizer"]["mean"], mean, atol=2e-5, rtol=0), "normalizer used wrong rows")
    z, cz, bz = (norm(a, mean) for a in (tx, cx, bx))
    deviations, results = [], {}
    for seed in (41, 47, 53):
        row = report["seeds"][str(seed)]
        model = {a: states[f"{seed}-{a}"] for a in ("frozen", "continued", "wide", "centroid", "gate")}
        need(np.allclose(model["centroid"]["centers"], centers(z), atol=2e-5, rtol=0), "outer TRAIN router drift")
        oof = np.empty((64, 2, 4), dtype=np.float32)
        for k, excluded in enumerate(folds):
            train = [i for i in range(64) if i not in excluded]
            old_train = [i for i in range(32) if i not in excluded]
            im = tx[old_train].mean(0)
            need(np.allclose(states[f"{seed}-fold{k}-normalizer"]["mean"], im, atol=2e-5, rtol=0), "fold normalizer leakage")
            iz = norm(tx, im)
            s = states[f"{seed}-fold{k}-split"]
            need(np.allclose(s["centers"], centers(iz[train]), atol=2e-5, rtol=0), "fold router leakage")
            for head in (0, 1):
                oof[excluded, head] = linear(s, iz[excluded], f"heads.{head}.")
        observed = np.asarray(row["oof_logits"])
        need(observed.shape == (64, 2, 4), "wrong out-of-fold logits")
        error = float(np.max(np.abs(oof - observed)))
        need(error < 5e-5, "out-of-fold logits drift")
        deviations.append(error)
        probs = softmax(oof)
        nll = -np.log(np.take_along_axis(probs, np.broadcast_to(y[:, None, None], (64, 2, 1)), 2).squeeze(2))
        target = (nll[:, 1] < nll[:, 0]).astype(int)
        need(target.tolist() == row["oof_targets"] and np.bincount(target, minlength=2).tolist() == row["oof_target_counts"],
             "false task-gate targets")
        old_prob, _ = forward(model, z[:32], seed)
        cal, cr = forward(model, cz, seed)
        blind, br = forward(model, bz, seed)
        need(cr == row["calibration_routes"] and br == row["blind_routes"], "route mismatch")
        for name, values in (("calibration_probabilities", cal), ("blind_probabilities", blind)):
            need(set(row[name]) == set(PROFILES), "incomplete probability profiles")
            for a, value in values.items():
                saved = np.asarray(row[name][a])
                need(saved.shape == (32, 4) and np.isfinite(saved).all(), "bad probability shape")
                delta = float(np.max(np.abs(value - saved)))
                need(delta < 5e-5 and np.array_equal(value.argmax(1), saved.argmax(1)), "prediction replay failed")
                deviations.append(delta)
        cal_brier = {a: brier(v, cy) for a, v in cal.items()}
        old_brier = {a: brier(old_prob[a], y[:32]) for a in ARMS}
        need(set(row["calibration"]) == set(PROFILES) and set(row["old_train_brier"]) == set(ARMS), "metric inventory")
        for a in PROFILES:
            need(row["calibration"][a]["correct"] == int((cal[a].argmax(1) == cy).sum())
                 and abs(row["calibration"][a]["brier"] - cal_brier[a]) < 5e-5, "calibration metric mismatch")
        need(all(abs(old_brier[a] - row["old_train_brier"][a]) < 5e-5 for a in ARMS), "old TRAIN metric mismatch")
        selection = choose({a: cal_brier[a] for a in ARMS}, old_brier)
        need(selection == row["selected_research_candidate"], "selector drift")
        for a in ("raw_parent", "raw_continue"):
            p = softmax(linear(states[f"{seed}-{a}"], cx))
            need(int((p.argmax(1) == cy).sum()) == row["raw_calibration"][a]["correct"]
                 and abs(brier(p, cy) - row["raw_calibration"][a]["brier"]) < 5e-5, "raw diagnostic mismatch")
        work = row["work"]
        need(set(work) == {"raw_parent", "raw_continue", "parent", "continued", "wide", "centroid", "task_gate"}
             | {f"fold{k}_{a}" for k in range(4) for a in ("parent", "split")}, "work inventory")
        for a, v in work.items():
            need(v["steps"] == 80 and v["examples"] == 1280 and type(v["cpu_ns"]) is int and v["cpu_ns"] >= 0
                 and type(v["wall_ns"]) is int and v["wall_ns"] >= 0
                 and all(np.isfinite(v[k]) and v[k] >= 0 for k in ("loss_before", "loss_after", "max_gradient_norm")), "invalid work")
            if a == "centroid" or a.endswith("_split"):
                need(v["selected_head_rows"] == 1280, "false sparse work")
        need(len({work[a]["schedule_sha256"] for a in ("raw_continue", "continued", "wide", "centroid", "task_gate")}) == 1,
             "unequal outer training schedule")
        results[str(seed)] = {"calibration_correct": {a: int((v.argmax(1) == cy).sum()) for a, v in cal.items()},
            "calibration_brier": cal_brier, "old_train_brier": old_brier, "selected_research_candidate": selection,
            "raw_calibration": row["raw_calibration"], "oof_target_counts": row["oof_target_counts"],
            "raw_parent_loss_after": work["raw_parent"]["loss_after"], "stable_parent_loss_after": work["parent"]["loss_after"],
            "optimizer_steps_reported": sum(v["steps"] for v in work.values()),
            "fit_loop_cpu_ns_reported": sum(v["cpu_ns"] for v in work.values())}
    return {"schema": SCHEMA + ".numpy-review", "status": "CALIBRATION_ONLY_NO_EFFICACY_CLAIM",
        "archive_sha256": ARCHIVE, "feature_sha256": FEATURE, "input_sha256": INPUT,
        "producer_sha256": report["producer_sha256"], "sealed_sha256": digest(raw(candidates / "sealed.json")),
        "model_files_replayed": 58, "learned_parameter_bundles": 45, "oof_teacher_logits_replayed": 1536,
        "blind_probability_rows_replayed": 768, "calibration_probability_rows_replayed": 768,
        "max_numeric_error": max(deviations), "seeds": results,
        "independent_gradient_reexecution": False, "held_scores": None, "held_labels_read": False,
        "new_encoder_forwards": 0, "future_utility_gain": None, "independent_retention": None,
        "production_authorized": False, "prospective_efficacy_verified": False,
        "normalizer_shared_scalars": 384, "candidate_resident_scalars": CAPACITY,
        "p99": None, "throughput_4096_cells": None, "target_host_qualified": False}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inputs", required=True)
    p.add_argument("--candidates", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    result = review(args.inputs, args.candidates)
    with Path(args.output).open("xb") as f:
        f.write(encode(result) + b"\n")
