"""Actual CPU head learning from *externally supplied frozen feature vectors*.

Research-only. The training path never accepts held-out targets. The supplied
encoder/source hashes are caller assertions, NOT independent provenance proof.
No pretrained encoder is executed by this module and no production use is allowed.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import struct
import time
from typing import Any

SCHEMA = "hepta.hdcf.frozen-feature-bank.v1"
MAX_INPUT_BYTES = 4_000_000
MAX_TRAIN = 2048
MAX_HELD = 1024
MAX_DIM = 256
MAX_STEPS = 8192


class Denied(ValueError):
    pass


def _dump(obj: Any) -> bytes:
    try:
        data = json.dumps(obj, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as error:
        raise Denied("noncanonical data") from error
    if len(data) > MAX_INPUT_BYTES:
        raise Denied("oversize evidence")
    return data


def digest(obj: Any) -> str:
    return hashlib.sha256(b"hepta.hdcf.frozen-feature.v1\0" + _dump(obj)).hexdigest()


def _object_keys(obj: Any, names: set[str]) -> None:
    if type(obj) is not dict or set(obj) != names:
        raise Denied("missing or unknown field")


def _sha(s: Any) -> None:
    if type(s) is not str or len(s) != 64 or any(c not in "0123456789abcdef" for c in s):
        raise Denied("invalid digest")


def _name(s: Any) -> None:
    if type(s) is not str or not 1 <= len(s) <= 128 or not s.isascii() or any(c.isspace() for c in s):
        raise Denied("invalid identifier")


def _integer(n: Any, low: int, high: int) -> None:
    if type(n) is not int or not low <= n <= high:
        raise Denied("invalid integer")


def _vector(v: Any, d: int) -> tuple[float, ...]:
    if type(v) is not list or len(v) != d:
        raise Denied("invalid feature dimension")
    out = []
    for x in v:
        if type(x) not in (float, int) or not math.isfinite(x) or abs(x) > 8:
            raise Denied("invalid feature scalar")
        out.append(float(x))
    return tuple(out)


def validate_bundle(bundle: Any) -> tuple[list, list, int]:
    """Full preflight before a single parameter or prediction changes."""
    _object_keys(bundle, {"schema", "producer", "dimension", "types", "fit", "held"})
    if bundle["schema"] != SCHEMA:
        raise Denied("unsupported schema")
    producer = bundle["producer"]
    _object_keys(producer, {"encoder_sha256", "preprocess_sha256", "source_sha256", "generation", "principal"})
    for f in ("encoder_sha256", "preprocess_sha256", "source_sha256"):
        _sha(producer[f])
    _integer(producer["generation"], 1, 2**63 - 1)
    _name(producer["principal"])
    d = bundle["dimension"]
    _integer(d, 1, MAX_DIM)
    typ = bundle["types"]
    if type(typ) is not list or len(typ) != 2 or typ[0] == typ[1]:
        raise Denied("exactly two distinct types required")
    for t in typ:
        _name(t)
    fit, held = [], []
    ids = set()
    vectors = set()
    train_families = set()
    held_families = set()
    class_counts = {(i, j): 0 for i in range(2) for j in range(2)}
    for split, min_size, limit, out in (("fit", 8, MAX_TRAIN, fit), ("held", 4, MAX_HELD, held)):
        rows = bundle[split]
        if type(rows) is not list or not min_size <= len(rows) <= limit:
            raise Denied("invalid split size")
        counts = {t: 0 for t in typ}
        for r in rows:
            expected = {"id", "family", "type", "vector", "target"} if split == "fit" else {"id", "family", "type", "vector"}
            _object_keys(r, expected)
            _name(r["id"])
            _name(r["family"])
            if r["id"] in ids or r["type"] not in counts:
                raise Denied("duplicate id or invalid type")
            ids.add(r["id"])
            v = _vector(r["vector"], d)
            key = struct.pack("<" + "d" * d, *v)
            if key in vectors:
                raise Denied("duplicate exact feature across split")
            vectors.add(key)
            counts[r["type"]] += 1
            if split == "fit":
                _integer(r["target"], 0, 1)
                class_counts[(typ.index(r["type"]), r["target"])] += 1
                train_families.add(r["family"])
                out.append((r["id"], r["family"], typ.index(r["type"]), v, r["target"]))
            else:
                held_families.add(r["family"])
                out.append((r["id"], r["family"], typ.index(r["type"]), v))
        if not all(counts.values()):
            raise Denied("missing one Cell type in a split")
    if any(count == 0 for count in class_counts.values()):
        raise Denied("each training type must contain both target classes")
    if train_families & held_families:
        raise Denied("source-family overlap; held does not mean future")
    return fit, held, d


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def _weights_digest(weights: list[list[float]]) -> str:
    b = b"".join(struct.pack("<d", x) for w in weights for x in w)
    return hashlib.sha256(b"hepta.hdcf.actual-head-weights.v1\0" + b).hexdigest()


def _pred(weights: list[list[float]], x: tuple[float, ...], cell: int, mode: str) -> float:
    if mode in ("shared_dense", "shared_one_touch"):
        w = [(a + b) * 0.5 for a, b in zip(*weights)]
    else:
        w = weights[cell if mode != "swapped" else 1 - cell]
    return _sigmoid(sum(a * b for a, b in zip(w[:-1], x)) + w[-1])


def _fit_arm(fit: list, d: int, steps: int, seed: int, lr: float, mode: str, initial: list[list[float]]) -> tuple[list, dict]:
    w = [row.copy() for row in initial]
    rng = random.Random(seed + 1)  # Exact common example order across arms.
    order = list(range(len(fit)))
    positions = []
    while len(positions) < steps:
        rng.shuffle(order)
        positions.extend(order)
    touched = 0
    start_cpu = time.process_time_ns()
    start = time.perf_counter_ns()
    for step, j in enumerate(positions[:steps]):
        _, _, cell, x, target = fit[j]
        p = _pred(w, x, cell, mode)
        gradient = (p - target)
        indices = [0, 1] if mode == "shared_dense" else [step % 2] if mode == "shared_one_touch" else [cell]
        coefficient = 0.5 if mode in ("shared_dense", "shared_one_touch") else 1.0
        # Note: single-head shared update uses *full* active gradient on only one
        # sampled member, unbiased against the two-head shared ensemble gradient.
        if mode == "shared_one_touch":
            coefficient = 1.0
        for k in indices:
            for c, value in enumerate((*x, 1.0)):
                w[k][c] -= lr * gradient * coefficient * value
            touched += d + 1
    cpu = time.process_time_ns() - start_cpu
    wall = time.perf_counter_ns() - start
    return w, {"actual_sgd_steps": steps, "estimated_parameter_touches": touched,
               "observed_train_cpu_ns": cpu, "observed_train_wall_ns": wall,
               "weights_digest": _weights_digest(w)}


def train(bundle: Any, *, steps: int = 256, seed: int = 7347, lr: float = 0.05) -> dict:
    """Physically updates float64 Cell heads; NEVER receives held labels."""
    fit, held, d = validate_bundle(bundle)
    _integer(steps, 1, MAX_STEPS)
    _integer(seed, 1, 2**31 - 1)
    if type(lr) not in (float, int) or not math.isfinite(lr) or not 0 < lr <= 0.2:
        raise Denied("invalid learning rate")
    rng = random.Random(seed)
    initial = [[(rng.random() - 0.5) * 0.02 for _ in range(d + 1)] for _ in range(2)]
    arms = {}
    predictions = {}
    for mode in ("frozen", "shared_dense", "shared_one_touch", "split", "swapped"):
        if mode == "frozen":
            w, work = initial, {"actual_sgd_steps": 0, "estimated_parameter_touches": 0,
                                "observed_train_cpu_ns": 0, "observed_train_wall_ns": 0,
                                "weights_digest": _weights_digest(initial)}
        elif mode == "swapped":
            w, work = split_weights, dict(split_work)
            work["actual_sgd_steps"] = 0
            work["estimated_parameter_touches"] = 0
            work["observed_train_cpu_ns"] = 0
            work["observed_train_wall_ns"] = 0
            work["reuses_split_weights"] = True
        else:
            w, work = _fit_arm(fit, d, steps, seed, float(lr), mode, initial)
            if mode == "split":
                split_weights, split_work = w, work
        pred_mode = "swapped" if mode == "swapped" else mode
        rows = []
        for id_, family, cell, x in held:
            rows.append({"id": id_, "family": family, "type": bundle["types"][cell],
                         "p1": _pred(w, x, cell, pred_mode)})
        if not all(math.isfinite(r["p1"]) for r in rows):
            raise Denied("nonfinite prediction")
        arms[mode] = work
        predictions[mode] = rows
    return {"schema": "hepta.hdcf.actual-head-trial.v1", "claim": "CPU_HEAD_SGD_ONLY_NO_PRETRAINED_ENCODER_FORWARD",
            "bundle_digest": digest(bundle), "producer_claim_digest": digest(bundle["producer"]),
            "trial_identity": digest({"bundle": digest(bundle), "steps": steps, "seed": seed, "lr": float(lr)}),
            "head_params_per_arm": 2 * (d + 1), "head_weight_payload_bytes_per_arm": 2 * (d + 1) * 8,
            "heads_actually_trained": True, "encoder_forward_count": 0,
            "pretrained_model_provenance_verified": False,
            "source_family_independence_verified": False,
            "held_labels_present_in_training": False,
            "external_effect_authorized": False, "production_authorized": False,
            "arms": arms, "predictions": predictions}


def score(trial: Any, labels: Any) -> dict:
    """Independent scorer sees *only* predictions and held labels, never fit data."""
    _object_keys(trial, {"schema", "claim", "bundle_digest", "producer_claim_digest", "trial_identity",
                         "head_params_per_arm", "head_weight_payload_bytes_per_arm", "heads_actually_trained",
                         "encoder_forward_count", "pretrained_model_provenance_verified",
                         "source_family_independence_verified", "held_labels_present_in_training",
                         "external_effect_authorized", "production_authorized", "arms", "predictions"})
    if (trial["schema"] != "hepta.hdcf.actual-head-trial.v1"
            or trial["claim"] != "CPU_HEAD_SGD_ONLY_NO_PRETRAINED_ENCODER_FORWARD"
            or trial["production_authorized"] is not False
            or trial["external_effect_authorized"] is not False
            or trial["pretrained_model_provenance_verified"] is not False
            or trial["encoder_forward_count"] != 0
            or trial["held_labels_present_in_training"] is not False):
        raise Denied("untrusted training artifact")
    for key in ("bundle_digest", "producer_claim_digest", "trial_identity"):
        _sha(trial[key])
    _object_keys(labels, {"schema", "bundle_digest", "targets"})
    if labels["schema"] != "hepta.hdcf.blind-targets.v1" or labels["bundle_digest"] != trial["bundle_digest"]:
        raise Denied("target set identity mismatch")
    targets = {}
    if type(labels["targets"]) is not list or not 4 <= len(labels["targets"]) <= MAX_HELD:
        raise Denied("invalid target census")
    for row in labels["targets"]:
        _object_keys(row, {"id", "family", "type", "target"})
        _name(row["id"]); _name(row["family"]); _name(row["type"])
        _integer(row["target"], 0, 1)
        if row["id"] in targets:
            raise Denied("duplicate target")
        targets[row["id"]] = row
    names = {"frozen", "shared_dense", "shared_one_touch", "split", "swapped"}
    if type(trial["predictions"]) is not dict or set(trial["predictions"]) != names or set(trial["arms"]) != names:
        raise Denied("incomplete comparison")
    results = {}
    for mode, preds in trial["predictions"].items():
        if type(preds) is not list or len(preds) != len(targets):
            raise Denied("incomplete prediction set")
        used = set()
        brier, correct = 0.0, 0
        per_type = {}
        for r in preds:
            _object_keys(r, {"id", "family", "type", "p1"})
            id_ = r["id"]
            if type(id_) is not str or id_ not in targets or id_ in used:
                raise Denied("missing or duplicated predicted id")
            used.add(id_)
            t = targets[id_]
            if t["family"] != r["family"] or t["type"] != r["type"]:
                raise Denied("source/type identity mismatch")
            p = r["p1"]
            if type(p) not in (float, int) or not math.isfinite(p) or not 0 <= p <= 1:
                raise Denied("invalid probability")
            y = t["target"]
            brier += (p-y)**2
            hit = int((p >= 0.5) == bool(y))
            correct += hit
            slot = per_type.setdefault(t["type"], [0, 0]); slot[0] += hit; slot[1] += 1
        results[mode] = {"n": len(targets), "correct": correct,
                         "accuracy": correct / len(targets), "brier": brier / len(targets),
                         "type_accuracy": {k: v[0]/v[1] for k,v in sorted(per_type.items())}}
    return {"schema": "hepta.hdcf.independent-head-review.v1",
            "trial_identity": trial["trial_identity"], "target_digest": digest(labels),
            "results": results, "independent_source_authenticated": False,
            "future_window_claim": False, "production_authorized": False}
