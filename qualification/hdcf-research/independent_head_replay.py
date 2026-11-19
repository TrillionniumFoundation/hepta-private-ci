"""Independent scalar oracle for HDCF's frozen-feature five-arm research trial.

Numerically replays training from source-bound feature bytes and an externally
selected plan. This DOES NOT authenticate the pretrained model, a publisher,
training hardware, CPU duration, a future task distribution or production use.
It deliberately does NOT call the producer's train/_fit_arm/_pred implementations.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import struct

from physical_bank import Denied, digest, validate_bundle

MODES = ("frozen", "shared_dense", "shared_one_touch", "split", "swapped")
DOMAIN = b"hepta.hdcf.actual-head-weights.v1\0"


def _require(ok, error):
    if not ok:
        raise Denied(error)


def _score(w, features, subtype, mode):
    # Independent linear logistic calculation with the original declared float64
    # operation order. No fitted Encoder or readout object is accessed here.
    if mode in ("shared_dense", "shared_one_touch"):
        coefficients = [(left + right) * 0.5 for left, right in zip(w[0], w[1], strict=True)]
    else:
        coefficients = w[subtype ^ int(mode == "swapped")]
    z = sum(coefficients[i] * feature for i, feature in enumerate(features)) + coefficients[-1]
    if z >= 0:
        return 1 / (1 + math.exp(-z))
    exp = math.exp(z)
    return exp / (1 + exp)


def _hash_weights(weights):
    sha = hashlib.sha256(DOMAIN)
    for row in weights:
        for value in row:
            sha.update(struct.pack("<d", value))
    return sha.hexdigest()


def _replay_fit(fit, d, plan, weights, treatment):
    copied = [row.copy() for row in weights]
    rng = random.Random(plan["seed"] + 1)
    indices = list(range(len(fit)))
    selections = []
    while len(selections) < plan["steps"]:
        rng.shuffle(indices)
        selections.extend(indices)
    touched = 0
    for ix, selected in enumerate(selections[:plan["steps"]]):
        _, _, subtype, features, label = fit[selected]
        pred = _score(copied, features, subtype, treatment)
        residual = pred - label
        if treatment == "shared_dense":
            routed = ((0, 0.5), (1, 0.5))
        elif treatment == "shared_one_touch":
            routed = ((ix % 2, 1.0),)
        else:
            routed = ((subtype, 1.0),)
        for slot, factor in routed:
            for j, scalar in enumerate((*features, 1.0)):
                copied[slot][j] -= plan["lr"] * residual * factor * scalar
            touched += d + 1
    return copied, touched


def audit_head_replay(bundle, trial, *, steps=256, seed=7347, lr=0.05):
    """Recompute actual float64 update mathematics and every sealed prediction.

    Timing fields remain independently *unverified*, although obvious false
    counts and negative/zero alleged resource measurements fail closed.
    """
    fit, held, dimension = validate_bundle(bundle)
    _require(type(steps) is int and 1 <= steps <= 8192, "unregistered training steps")
    _require(type(seed) is int and 1 <= seed < 2**31, "unregistered training seed")
    _require(type(lr) in (int, float) and math.isfinite(lr) and 0 < lr <= 0.2,
             "unregistered optimizer rate")
    plan = {"steps": steps, "seed": seed, "lr": float(lr)}
    identity = digest({"bundle": digest(bundle), **plan})
    _require(type(trial) is dict and trial.get("schema") == "hepta.hdcf.actual-head-trial.v1" and
             trial.get("claim") == "CPU_HEAD_SGD_ONLY_NO_PRETRAINED_ENCODER_FORWARD" and
             trial.get("bundle_digest") == digest(bundle) and trial.get("trial_identity") == identity and
             trial.get("producer_claim_digest") == digest(bundle["producer"]) and
             trial.get("head_params_per_arm") == 2 * (dimension + 1) and
             trial.get("head_weight_payload_bytes_per_arm") == 16 * (dimension + 1) and
             trial.get("heads_actually_trained") is True and
             type(trial.get("encoder_forward_count")) is int and trial["encoder_forward_count"] == 0 and
             trial.get("pretrained_model_provenance_verified") is False and
             trial.get("source_family_independence_verified") is False and
             trial.get("held_labels_present_in_training") is False and
             trial.get("external_effect_authorized") is False and
             trial.get("production_authorized") is False and
             type(trial.get("arms")) is dict and set(trial["arms"]) == set(MODES) and
             type(trial.get("predictions")) is dict and set(trial["predictions"]) == set(MODES),
             "trial provenance, tensor inventory or authority changed")
    rng = random.Random(seed)
    init = [[(rng.random() - 0.5) * 0.02 for _ in range(dimension + 1)] for _ in range(2)]
    split_weights = None
    digests = {}
    total_checks = 0
    for mode in MODES:
        if mode == "frozen":
            weights, touched, updates = init, 0, 0
        elif mode == "swapped":
            _require(split_weights is not None, "split predecessor not replayed")
            weights, touched, updates = split_weights, 0, 0
        else:
            weights, touched = _replay_fit(fit, dimension, plan, init, mode)
            updates = steps
            if mode == "split":
                split_weights = weights
        report = trial["arms"][mode]
        mandatory = {"actual_sgd_steps", "estimated_parameter_touches", "observed_train_cpu_ns",
                     "observed_train_wall_ns", "weights_digest"}
        if mode == "swapped":
            mandatory.add("reuses_split_weights")
        _require(type(report) is dict and set(report) == mandatory and
                 type(report["actual_sgd_steps"]) is int and report["actual_sgd_steps"] == updates and
                 type(report["estimated_parameter_touches"]) is int and
                 report["estimated_parameter_touches"] == touched and
                 report["weights_digest"] == _hash_weights(weights) and
                 (mode != "swapped" or report["reuses_split_weights"] is True),
                 "training work, digest or parameters disagree with independent replay")
        for clock in ("observed_train_cpu_ns", "observed_train_wall_ns"):
            t = report[clock]
            _require(type(t) is int and (t > 0 if updates else t == 0),
                     "invalid declared CPU or wall timing")
        rows = trial["predictions"][mode]
        _require(type(rows) is list and len(rows) == len(held), "missing predictions")
        for original, found in zip(held, rows, strict=True):
            case_id, family, subtype, features = original
            _require(type(found) is dict and set(found) == {"id", "family", "type", "p1"} and
                     found["id"] == case_id and found["family"] == family and
                     found["type"] == bundle["types"][subtype] and
                     type(found["p1"]) in (float, int) and math.isfinite(found["p1"]) and
                     0 <= found["p1"] <= 1, "replayed population mismatch")
            recomputed = _score(weights, features, subtype, mode)
            _require(abs(float(found["p1"]) - recomputed) <= 1e-13,
                     "predictor logits disagree with independently replayed SGD")
            total_checks += 1
        digests[mode] = _hash_weights(weights)
    return {"schema": "hepta.hdcf.independent-head-scalar-replay.v1",
            "trial_identity": identity, "training_plan": plan, "arms_replayed": list(MODES),
            "original_prediction_rows_replayed": total_checks,
            "original_trained_weights_recomputed": digests,
            "independent_model_source_authenticated": False,
            "actual_cpu_time_independently_verified": False,
            "future_source_independence_verified": False,
            "model_selection_authorized": False,
            "native_execution_authorized": False,
            "production_authorized": False}
