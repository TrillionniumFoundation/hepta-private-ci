"""Fit two small heads on fixed semantic features; score in a separate command.

Only the original frozen train/development files are accepted by fit.  Existing
held sets and the new-task set cannot enter fitting, early stopping or threshold
selection.  This candidate is opt-in and retains failed gates as evidence.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time
import warnings

import numpy as np

from semantic_encoder_worker import load_encoder
from semantic_protocol import ENCODER_DIGEST, FEATURE_PROFILE, INTENTS, SHAPES, SCHEMA
from semantic_protocol import address, canonical, digest, gold, hypothesis, intent_label, route

TRAIN_SHA = "cea20fe493db180e9acc4a122a49b56238124edf2a9c421407fec04dc387830e"
DEV_SHA = "8b512b856425533b569fbd6c8524636b5afcdce4203f7b0c1a9ae3555e1026f6"
ALIASES_SHA = "1bfff5dda30e3d43e98400b57536bb7725498135f2d9f98bc307f7ac9662aa97"


def pinned_json(path, expected):
    raw = path.read_bytes()
    if digest(raw) != expected:
        raise ValueError(f"frozen fitting input differs: {path.name}")
    return json.loads(raw)


def encoder_from(args):
    return load_encoder(args.encoder_source, args.encoder_source_sha256, args.encoder, ENCODER_DIGEST)


def encode_rows(encoder, rows):
    vectors, truncated = [], []
    for row in rows:
        text = row["text"]
        if not isinstance(text, str) or not text.strip() or len(text.encode()) > 8192:
            raise ValueError("unbounded text")
        overflow = bool(encoder.tokenizer.encode(text).overflowing)
        truncated.append(overflow)
        vectors.append(np.zeros(384, dtype=np.float32) if overflow else encoder.encode([text])[0])
    return np.stack(vectors), truncated


def fit(args):
    from sklearn.exceptions import ConvergenceWarning
    from sklearn.linear_model import LogisticRegression
    from threadpoolctl import threadpool_limits

    if args.output.exists():
        raise FileExistsError(args.output)
    train = pinned_json(args.training, TRAIN_SHA)
    dev = pinned_json(args.calibration, DEV_SHA)
    aliases = pinned_json(args.aliases, ALIASES_SHA)
    protocol = json.loads(args.protocol.read_bytes())
    if protocol["training_sha256"] != TRAIN_SHA or protocol["calibration_sha256"] != DEV_SHA \
            or protocol["aliases_sha256"] != ALIASES_SHA:
        raise ValueError("predeclared protocol differs")
    started, cpu = time.perf_counter(), time.process_time()
    encoder = encoder_from(args)
    x, truncated = encode_rows(encoder, train)
    development_x, development_truncated = encode_rows(encoder, dev)
    if any(truncated) or any(development_truncated):
        raise ValueError("fitting text exceeds the frozen tokenizer profile")
    labels = [intent_label(row) for row in train]
    shapes = [SHAPES[INTENTS.index(row["role"])] if row["role"] != "unknown" else "unsupported" for row in train]
    model = {"schema": SCHEMA, "feature_profile": FEATURE_PROFILE, "encoder_digest": ENCODER_DIGEST,
             "dimension": 384, "training_digest": TRAIN_SHA, "calibration_digest": DEV_SHA,
             "intent_labels": list(INTENTS), "shape_labels": list(SHAPES),
             "threshold": 1.01, "minimum_margin": 0.0, "aliases": aliases}
    receipts = []
    for name, targets, order in (("intent", labels, INTENTS), ("shape", shapes, SHAPES)):
        if set(targets) != set(order):
            raise ValueError("each fitted class requires declared training evidence")
        learner = LogisticRegression(C=8.0, class_weight="balanced", max_iter=2000,
                                     solver="lbfgs", random_state=731, tol=1e-7)
        began, began_cpu = time.perf_counter(), time.process_time()
        with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=1):
            warnings.simplefilter("always")
            learner.fit(x.astype(np.float64), targets)
        if any(issubclass(item.category, ConvergenceWarning) for item in caught):
            raise ValueError("fixed-budget head fit failed to converge")
        positions = [list(learner.classes_).index(label) for label in order]
        model[name + "_weights"] = learner.coef_[positions].astype(np.float32).tolist()
        model[name + "_bias"] = learner.intercept_[positions].astype(np.float32).tolist()
        receipts.append({"head": name, "actual_fit": True, "rows": len(train),
                         "iterations": learner.n_iter_.tolist(), "cpu_seconds": time.process_time() - began_cpu,
                         "wall_seconds": time.perf_counter() - began,
                         "warnings": [str(item.message) for item in caught]})
    # Evaluate the fixed Rust-order arithmetic before calibration.  Computing
    # these scores once avoids hiding repeated encoder work inside the grid.
    scores = [hypothesis(model, feature) for feature in development_x]
    keys = [address(row["text"], aliases) for row in dev]
    trials = []
    for threshold in (*[i / 20 for i in range(20)], .99, 1.01):
        for margin in (0., .05, .1, .15, .2, .25, .3, .4, .5):
            predicted = []
            for key, (winner, score, gap) in zip(keys, scores, strict=True):
                present = None if key is None else (key["entity"] is not None, key["workflow"] is not None)
                if key is None or winner == 3 or score < float(np.float32(threshold)) or gap < float(np.float32(margin)) \
                        or present != ((True, False), (False, True), (True, True))[winner]:
                    predicted.append(None)
                else:
                    predicted.append({"operation": ("semantic", "procedure", "apply")[winner], **key})
            unknown_accepted = sum(row["role"] == "unknown" and value is not None for row, value in zip(dev, predicted, strict=True))
            known_wrong = sum(row["role"] != "unknown" and value is not None and value != gold(row) for row, value in zip(dev, predicted, strict=True))
            correct = sum(row["role"] != "unknown" and value == gold(row) for row, value in zip(dev, predicted, strict=True))
            trials.append({"threshold": threshold, "minimum_margin": margin, "unknown_accepted": unknown_accepted,
                           "known_wrong": known_wrong, "known_correct": correct})
    eligible = [trial for trial in trials if trial["unknown_accepted"] == 0 and trial["known_wrong"] == 0]
    selected = max(eligible, key=lambda trial: (trial["known_correct"], trial["threshold"], trial["minimum_margin"]))
    model.update({name: selected[name] for name in ("threshold", "minimum_margin")})
    args.output.mkdir(parents=True)
    raw = canonical(model)
    (args.output / "semantic-router.json").write_bytes(raw)
    np.savez_compressed(args.output / "fitting-features.npz", training=x, calibration=development_x)
    receipt = {"schema": "hepta.memory.inventory-semantic-fit.v1", "model_sha256": digest(raw),
               "training_sha256": TRAIN_SHA, "calibration_sha256": DEV_SHA, "aliases_sha256": ALIASES_SHA,
               "protocol_sha256": digest(args.protocol.read_bytes()), "selection_used_held": False,
               "selection_used_new_tasks": False, "training_rows": len(train), "calibration_rows": len(dev),
               "selected": selected, "trials": trials, "heads": receipts, "encoder": encoder.receipt(),
               "learned_f32_parameters": sum(len(row) for name in ("intent", "shape") for row in model[name + "_weights"])
                                         + sum(len(model[name + "_bias"]) for name in ("intent", "shape")),
               "serialized_bytes": len(raw), "cpu_seconds": time.process_time() - cpu,
               "wall_seconds": time.perf_counter() - started,
               "source_sha256": {name: digest(Path(__file__).with_name(name).read_bytes())
                                 for name in ("train_semantic_router.py", "semantic_protocol.py", "semantic_encoder_worker.py")},
               "status": "experimental opt-in; no held/new-task qualification inferred from development"}
    (args.output / "FIT.json").write_bytes(canonical(receipt))
    print(json.dumps({name: receipt[name] for name in ("model_sha256", "selected", "serialized_bytes", "learned_f32_parameters", "wall_seconds")}))


def evaluation_rows(raw):
    value = json.loads(raw)
    if isinstance(value, list):
        return value
    result = []
    for i, case in enumerate(value["cases"]):
        gold_route = case["gold_route"]
        result.append({"id": f"regression:{i}", "text": case["text"],
                       "role": "unknown" if gold_route is None else {"semantic": "semantic", "procedure": "skill", "apply": "compose"}[gold_route["operation"]],
                       "entity": None if gold_route is None or gold_route["entity"] is None else int(gold_route["entity"].split(":")[-1]),
                       "workflow": None if gold_route is None or gold_route["workflow"] is None else int(gold_route["workflow"].split(":")[-1])})
    return result


def score(args):
    if args.output.exists():
        raise FileExistsError(args.output)
    raw_model, raw_queries = args.model.read_bytes(), args.queries.read_bytes()
    model = json.loads(raw_model)
    if digest(raw_model) != args.model_sha256 or model["encoder_digest"] != ENCODER_DIGEST:
        raise ValueError("evaluation model pin differs")
    rows = evaluation_rows(raw_queries)
    encoder = encoder_from(args)
    features, truncated = encode_rows(encoder, rows)
    groups, cases = {}, []
    for row, feature, overflow in zip(rows, features, truncated, strict=True):
        prediction = route(model, row["text"], None if overflow else feature)
        case = {"id": row["id"], "text": row["text"], "gold_route": gold(row),
                "reference_route": prediction, "features": [] if overflow else feature.tolist(), "truncated": overflow}
        cases.append(case)
        for group in ("role:" + row["role"], "language:" + row.get("language", "en"), "family:" + row.get("family", row["role"])):
            counts = groups.setdefault(group, {"total": 0, "correct": 0, "abstained": 0, "unknown_false_accept": 0})
            counts["total"] += 1; counts["correct"] += prediction == gold(row)
            counts["abstained"] += prediction is None
            counts["unknown_false_accept"] += row["role"] == "unknown" and prediction is not None
    report = {"schema": "hepta.memory.inventory-semantic-python-reference.v1", "model_sha256": digest(raw_model),
              "queries_sha256": digest(raw_queries), "encoder_digest": ENCODER_DIGEST,
              "rows": len(rows), "groups": groups, "cases": cases, "encoder": encoder.receipt(),
              "fit_or_calibration_updated": False}
    args.output.write_bytes(canonical(report))
    print(json.dumps({"rows": len(rows), "groups": groups, "model_sha256": digest(raw_model)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    fitting = sub.add_parser("fit")
    fitting.add_argument("--training", type=Path, required=True)
    fitting.add_argument("--calibration", type=Path, required=True)
    fitting.add_argument("--aliases", type=Path, required=True)
    fitting.add_argument("--protocol", type=Path, required=True)
    scoring = sub.add_parser("score")
    scoring.add_argument("--model", type=Path, required=True)
    scoring.add_argument("--model-sha256", required=True)
    scoring.add_argument("--queries", type=Path, required=True)
    for command in (fitting, scoring):
        command.add_argument("--encoder-source", type=Path, required=True)
        command.add_argument("--encoder-source-sha256", required=True)
        command.add_argument("--encoder", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    fit(args) if args.mode == "fit" else score(args)
