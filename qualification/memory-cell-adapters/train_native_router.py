"""Fit a native role router; training/calibration files are separate from scoring.

No stored inventory values, held questions or held answers enter fit().
This does not claim open-world natural language understanding.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import time

import numpy as np

DIMENSION = 2048
PROFILE = "hepta.memory.ascii-words-ngrams-sha256-l2.v1"
ROLES = ("semantic", "skill", "compose", "unknown")

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()

def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()

def words(text):
    return re.findall(r"[a-z0-9_]+", text.lower())

def features(masked):
    tokens = words(masked)
    vector = np.zeros(DIMENSION, dtype=np.float32)
    entries = ["u:" + word for word in tokens]
    entries += ["c:" + padded[i:i+3] for word in tokens for padded in ["^"+word+"$"] for i in range(len(padded)-2)]
    entries += ["b:" + a + " " + b for a, b in zip(tokens, tokens[1:])]
    for entry in entries:
        digest = hashlib.sha256(entry.encode("ascii")).digest()
        vector[int.from_bytes(digest[:8], "little") % DIMENSION] += 1 if digest[8] & 1 == 0 else -1
    squared = np.float32(0)
    for value in vector:
        squared = np.float32(squared + value * value)
    norm = np.float32(np.sqrt(squared))
    if norm > 0:
        vector /= norm
    return vector

def address(text, aliases):
    if not text or len(text) > 8192 or not text.isascii() or len(words(text)) > 256:
        return None
    normalized = " " + " ".join(words(text)) + " "
    masked = normalized
    keys = {"entity": set(), "workflow": set()}
    for alias in aliases:
        for phrase in alias["phrases"]:
            needle = " " + " ".join(words(phrase)) + " "
            if needle in normalized:
                keys[alias["kind"]].add(alias["key"])
                masked = masked.replace(needle, " " + alias["kind"] + "_port ")
    if any(len(value) > 1 for value in keys.values()) or not any(keys.values()):
        return None
    return masked, {kind: next(iter(value), None) for kind, value in keys.items()}

def probabilities(model, rows):
    weights = np.asarray(model["weights"], dtype=np.float32)
    bias = np.asarray(model["bias"], dtype=np.float32)
    result = []
    for row in rows:
        parsed = address(row["text"], model["aliases"])
        if parsed is None:
            result.append((None, None))
            continue
        masked, keys = parsed
        vector = features(masked)
        # Scalar f32 order mirrors Rust. Quality is evaluated separately from
        # this numerical reference, including negative and abstained cases.
        logits = np.zeros(4, dtype=np.float32)
        for i in range(4):
            total = np.float32(0)
            for weight, value in zip(weights[i], vector):
                total = np.float32(total + weight * value)
            logits[i] = total + bias[i]
        scores = np.exp(logits - logits.max()).astype(np.float32)
        scores /= scores.sum(dtype=np.float32)
        result.append((scores, keys))
    return result

def route(scores, keys, threshold, margin):
    if scores is None:
        return None
    order = sorted(range(4), key=lambda i: (-float(scores[i]), i))
    winner = order[0]
    if winner == 3 or scores[winner] < threshold or scores[winner] - scores[order[1]] < margin:
        return None
    present = (keys["entity"] is not None, keys["workflow"] is not None)
    if present != ((True, False), (False, True), (True, True))[winner]:
        return None
    return {"operation": ("semantic", "procedure", "apply")[winner], **keys}

def gold(row):
    if row["role"] == "unknown":
        return None
    return {"operation": {"semantic": "semantic", "skill": "procedure", "compose": "apply"}[row["role"]],
            "entity": None if row["entity"] is None else f"inventory:entity:{row['entity']}",
            "workflow": None if row["workflow"] is None else f"inventory:workflow:{row['workflow']}"}

def fit(training_file, calibration_file, aliases_file, output):
    if output.exists():
        raise FileExistsError(output)
    started = time.perf_counter()
    train = json.loads(training_file.read_bytes())
    calibration = json.loads(calibration_file.read_bytes())
    aliases = json.loads(aliases_file.read_bytes())
    parsed = [address(row["text"], aliases) for row in train]
    x = np.stack([features(item[0]) for item in parsed]).astype(np.float64)
    y = np.asarray([ROLES.index(row["role"]) for row in train])
    sample_weights = len(y) / (4 * np.bincount(y, minlength=4)[y])
    rng = np.random.default_rng(731)
    weights = rng.normal(0, .001, (4, DIMENSION))
    bias = np.zeros(4)
    parameters = [weights, bias]
    first = [np.zeros_like(p) for p in parameters]
    second = [np.zeros_like(p) for p in parameters]
    # Protocol constants are frozen before evaluation: no checkpoint sweep or
    # model selection on held data. Only declared development thresholds vary.
    for step in range(1, 801):
        logits = x @ weights.T + bias
        scores = np.exp(logits - logits.max(axis=1, keepdims=True))
        scores /= scores.sum(axis=1, keepdims=True)
        scores[np.arange(len(y)), y] -= 1
        scores *= sample_weights[:, None] / sample_weights.sum()
        gradients = [scores.T @ x + .001 * weights, scores.sum(axis=0)]
        for parameter, gradient, m, v in zip(parameters, gradients, first, second):
            m *= .9; m += .1 * gradient
            v *= .999; v += .001 * gradient * gradient
            parameter -= .025 * (m / (1 - .9 ** step)) / (np.sqrt(v / (1 - .999 ** step)) + 1e-8)
    model = {"schema": "hepta.memory.inventory-text-router.v1", "feature_profile": PROFILE,
             "dimension": DIMENSION, "training_digest": sha(training_file.read_bytes()),
             "calibration_digest": sha(calibration_file.read_bytes()), "weights": weights.astype(np.float32).tolist(),
             "bias": bias.astype(np.float32).tolist(), "threshold": 1.1, "minimum_margin": 0.0, "aliases": aliases}
    decoded = probabilities(model, calibration)
    trials = []
    for threshold in (.25, .4, .5, .6, .7, .8, .9, .95, .99, 1.1):
        for margin in (0., .1, .2, .3, .4):
            predicted = [route(p, keys, threshold, margin) for p, keys in decoded]
            false_accept = sum(row["role"] == "unknown" and prediction is not None for row, prediction in zip(calibration, predicted))
            known_correct = sum(row["role"] != "unknown" and prediction == gold(row) for row, prediction in zip(calibration, predicted))
            trials.append({"threshold": threshold, "minimum_margin": margin, "unknown_false_accept": false_accept, "known_correct": known_correct})
    eligible = [row for row in trials if row["unknown_false_accept"] == 0]
    chosen = max(eligible, key=lambda row: (row["known_correct"], row["threshold"], row["minimum_margin"]))
    model.update({key: chosen[key] for key in ("threshold", "minimum_margin")})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical(model))
    report = {"schema": "hepta.memory.native-router-fit.v1", "seed": 731, "steps": 800,
              "train_rows": len(train), "calibration_rows": len(calibration), "model_sha256": sha(output.read_bytes()),
              "train_sha256": model["training_digest"], "calibration_sha256": model["calibration_digest"],
              "aliases_sha256": sha(aliases_file.read_bytes()), "selection_used_held": False,
              "chosen": chosen, "trials": trials, "seconds": time.perf_counter() - started,
              "serialized_bytes": output.stat().st_size, "learned_f32_parameters": weights.size + bias.size}
    output.with_suffix(".fit.json").write_bytes(canonical(report))
    print(json.dumps({key: report[key] for key in ("model_sha256", "chosen", "seconds", "serialized_bytes")}))

def score(model_file, query_file, output):
    model = json.loads(model_file.read_bytes())
    rows = json.loads(query_file.read_bytes())
    decoded = probabilities(model, rows)
    predicted = [route(p, keys, model["threshold"], model["minimum_margin"]) for p, keys in decoded]
    report = {"schema": "hepta.memory.native-router-python-reference.v1", "model_sha256": sha(model_file.read_bytes()),
              "queries_sha256": sha(query_file.read_bytes()), "rows": len(rows), "groups": {},
              "cases": [{"text": row["text"], "reference_route": prediction, "gold_route": gold(row)} for row, prediction in zip(rows, predicted)]}
    for role in ROLES:
        selected = [(row, prediction) for row, prediction in zip(rows, predicted) if row["role"] == role]
        report["groups"][role] = {"total": len(selected), "correct": sum(prediction == gold(row) for row, prediction in selected), "abstained": sum(prediction is None for _, prediction in selected)}
    output.write_bytes(canonical(report))
    print(json.dumps({key: report[key] for key in ("model_sha256", "queries_sha256", "groups")}))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    train = sub.add_parser("fit")
    train.add_argument("--training", type=Path, required=True)
    train.add_argument("--calibration", type=Path, required=True)
    train.add_argument("--aliases", type=Path, required=True)
    train.add_argument("--output", type=Path, required=True)
    evaluate = sub.add_parser("score")
    evaluate.add_argument("--model", type=Path, required=True)
    evaluate.add_argument("--queries", type=Path, required=True)
    evaluate.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "fit": fit(args.training, args.calibration, args.aliases, args.output)
    else: score(args.model, args.queries, args.output)
