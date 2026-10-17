"""Independent NumPy-only complete 40-step SGD audit for private research Head bytes.

The replay cannot authenticate the original pretrained Encoder or human labels.
It never scores heldout truth, promotes a model or supplies a production grant.
The independent reviewer reconstructs feature hashing as well as all SGD steps.
"""
from __future__ import annotations

import hashlib
import math
import numpy as np

import gate
import matched_head as mh


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x, dtype=np.float32))


def _independent_project(bank):
    """Recompute the full label-free projection without the producer helper."""
    dimension = bank["encoder_output_dimension"]
    samples = np.asarray([r["values"] for r in bank["rows"]], dtype=np.float32)
    out = np.zeros((len(samples), mh.WIDTH), dtype=np.float32)
    fixed = ("hepta.stem.matched-projection.v1|" + bank["model"] + "|" +
             bank["revision"] + "|" + bank["source_weights_sha256"] + "|")
    buckets = []
    signs = []
    factor = np.float32(1.0 / math.sqrt(max(1.0, dimension / mh.WIDTH)))
    for index in range(dimension):
        word = hashlib.sha256((fixed + str(index)).encode("ascii")).digest()
        col = int.from_bytes(word[:4], "big") % mh.WIDTH
        direction = 1 if word[4] & 1 else -1
        buckets.append(col)
        signs.append(direction)
        out[:, col] += np.float32(direction) * samples[:, index] * factor
    digest = mh._hash({"buckets": buckets, "signs": signs,
                       "model": bank["model"], "input_width": dimension})
    return out, digest


def independent_replay(panel, bank, fit_labels, product, *, atol=3e-5):
    """Reconstruct every SGD parameter update with no torch/trainer imports."""
    mh.validate_bank(panel, bank)
    labels = mh.validate_fit(panel, fit_labels)
    receipt = product["receipt"]
    gate.require(receipt["authority"] == "DENY_ALL" and receipt["disposition"] == "HOLD_NO_GO" and
                 receipt["production_promotion_permitted"] is False and
                 receipt["trainable_params"] == mh.PARAMS and receipt["steps"] == mh.STEPS and
                 receipt["panel_sha256"] == gate.digest(panel) and
                 receipt["feature_bank_sha256"] == mh._hash(bank) and
                 receipt["fit_labels_sha256"] == mh._hash(fit_labels),
                 "untrusted matched-head training receipt")
    initial = product["initial_head_tensors"]
    final = product["trained_head_tensors"]
    keys = {"0.weight", "0.bias", "2.weight", "2.bias"}
    gate.require(type(initial) is dict and type(final) is dict and
                 set(initial) == set(final) == keys, "missing trained or initial Head parameter")
    specs = {"0.weight": (32, 128), "0.bias": (32,),
             "2.weight": (1, 32), "2.bias": (1,)}
    for k, shape in specs.items():
        for bundle in (initial, final):
            item=bundle[k]
            gate.require(type(item) is np.ndarray and item.dtype == np.dtype("float32") and
                         item.shape == shape and np.isfinite(item).all(), "wrong tensor inventory")
    X, projection_digest = _independent_project(bank)
    gate.require(receipt["projection"]["projection_digest"] == projection_digest and
                 receipt["projection"]["projection_trainable_params"] == 0 and
                 receipt["projection"]["projection_adds"] == len(X) * bank["encoder_output_dimension"] and
                 receipt["projection"]["projection_multiplies"] == len(X) * bank["encoder_output_dimension"] and
                 receipt["projection"]["projection_scratch_bytes"] == len(X) * mh.WIDTH * 4 and
                 receipt["projection"]["projection_index_bytes"] == bank["encoder_output_dimension"] * 8,
                 "independent feature projection accounting mismatch")
    fit_ix = [i for i, row in enumerate(panel["cases"]) if row["split"] == "fit"]
    a = initial["0.weight"].copy(); b=initial["0.bias"].copy()
    c = initial["2.weight"].copy(); d=initial["2.bias"].copy()
    Y = np.asarray(labels, dtype=np.float32).reshape(-1, 1)
    T = X[fit_ix]
    for _ in range(mh.STEPS):
        h = _sigmoid(T @ a.T + b)
        z = h @ c.T + d
        dz = (_sigmoid(z) - Y) / np.float32(len(Y))
        dc = dz.T @ h
        dd = dz.sum(axis=0)
        dh = (dz @ c) * h * (1.0 - h)
        da = dh.T @ T
        db = dh.sum(axis=0)
        a -= np.float32(mh.LR) * da
        b -= np.float32(mh.LR) * db
        c -= np.float32(mh.LR) * dc
        d -= np.float32(mh.LR) * dd
    recomputed = {"0.weight": a, "0.bias": b, "2.weight": c, "2.bias": d}
    errors = {k:float(np.max(np.abs(recomputed[k]-final[k]))) for k in specs}
    gate.require(max(errors.values()) <= atol, "independent physical SGD tensor replay failed")
    dhash=hashlib.sha256()
    for k, tensor in sorted(final.items()):
        dhash.update(k.encode("ascii") + b"\0" + tensor.tobytes(order="C"))
    gate.require(dhash.hexdigest() == receipt["head_weight_sha256"],
                 "saved complete Head tensor hash differs")
    hidden = _sigmoid(X @ a.T + b)
    logits = (hidden @ c.T + d).ravel()
    gate.require(np.isfinite(logits).all(), "nonfinite recomputed predictions")
    for split, key in (("cal", "raw_calibration_logits"), ("test", "raw_test_logits")):
        orig = receipt[key]
        subset = [(i, case["case_id"]) for i, case in enumerate(panel["cases"]) if case["split"] == split]
        gate.require(type(orig) is list and len(orig) == len(subset), "missing blind prediction rows")
        for (i, identity), row in zip(subset, orig, strict=True):
            gate.require(type(row) is dict and set(row) == {"case_id", "logit"} and
                         row["case_id"] == identity and type(row["logit"]) is float and
                         abs(row["logit"] - float(logits[i])) <= atol,
                         "independently recomputed raw score mismatch")
    return {"schema": "hepta.stem.equal-size.matched-head-review.v1",
            "head_sha256": receipt["head_weight_sha256"],
            "parameter_max_abs_error": max(errors.values()),
            "replayed_steps": mh.STEPS, "source_quality_verified": False,
            "human_heldout_accuracy_scored": False, "no_change_production_verified": False,
            "promotion_permitted": False, "authority": "DENY_ALL",
            "disposition": "HOLD_NO_GO"}
