"""Research-only equal-parameter decision Head for independently produced frozen Features.

No pretrained download, feature fabrication, model selection, publisher signing,
production owner or access to calibration/heldout truth occurs here. A caller MUST
provide physical pretrained Encoder feature banks for each complete original panel.
Identity flags in an input bank are claims, not independently attested evidence.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from typing import Any

import gate

SCHEMA = "hepta.stem.equal-size.matched-head.v1"
FEATURE_SCHEMA = "hepta.stem.equal-size.original-frozen-feature-bank.v1"
FIT_SCHEMA = "hepta.stem.equal-size.fit-labels.v1"
WIDTH = 128
HIDDEN = 32
PARAMS = WIDTH * HIDDEN + HIDDEN + HIDDEN + 1  # 4,161
STEPS = 40
LR = 0.1
MAX_VECTOR_DIM = 4096
MAX_TOTAL_VALUES = 2_000_000
MAX_ABS_FEATURE = 8.0


def require(ok: Any, msg: str) -> None:
    gate.require(ok, msg)


def _float(x: Any) -> float:
    require(type(x) in (float, int) and math.isfinite(x) and abs(x) <= MAX_ABS_FEATURE,
            "unbounded/nonfinite frozen feature")
    return float(x)


def _canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _hash(obj):
    return hashlib.sha256(_canonical(obj)).hexdigest()


def validate_bank(panel, bank):
    plan = gate.validate_panel(panel)
    require(type(bank) is dict and set(bank) == {
        "schema", "panel_sha256", "model", "repo", "revision", "source_weights_sha256",
        "source_tokenizer_sha256", "encoder_output_dimension", "precision", "rows",
        "actual_pretrained_forward_reported", "physical_source_sha256_checked_reported",
        "signed_publisher_identity_verified", "production_authorized", "future_window_verified",
        "authority"}, "unknown/unsafe feature-bank fields")
    model = bank["model"]
    require(type(model) is str and model in gate.MODELS, "unregistered feature bank model")
    repo, revision, _, _ = gate.MODELS[model]
    require(bank["schema"] == FEATURE_SCHEMA and bank["panel_sha256"] == plan["panel_sha256"] and
            bank["repo"] == repo and bank["revision"] == revision and
            gate.sha(bank["source_weights_sha256"]) and gate.sha(bank["source_tokenizer_sha256"]) and
            bank["precision"] == "float32" and bank["authority"] == "DENY_ALL" and
            bank["actual_pretrained_forward_reported"] is True and
            bank["physical_source_sha256_checked_reported"] is True and
            bank["signed_publisher_identity_verified"] is False and
            bank["production_authorized"] is False and
            bank["future_window_verified"] is False,
            "frozen pretrained bank identity or permission mismatch")
    d = bank["encoder_output_dimension"]
    require(type(d) is int and 1 <= d <= MAX_VECTOR_DIM, "invalid real feature dimension")
    rows = bank["rows"]
    expected = panel["cases"]
    require(type(rows) is list and len(rows) == len(expected) and len(rows) * d <= MAX_TOTAL_VALUES,
            "incomplete or oversized frozen features")
    for source, row in zip(expected, rows, strict=True):
        require(type(row) is dict and set(row) == {"case_id", "input_sha256", "source_sha256", "values"},
                "model bank includes forbidden label/text/unknown feature")
        require(row["case_id"] == source["case_id"] and
                row["input_sha256"] == source["input_sha256"] and
                row["source_sha256"] == source["source_sha256"],
                "frozen feature reordered or bound to a different source")
        require(type(row["values"]) is list and len(row["values"]) == d,
                "incomplete variable-width frozen feature")
        for value in row["values"]:
            _float(value)
    return d


def validate_fit(panel, labels):
    gate.validate_panel(panel)
    require(type(labels) is dict and set(labels) == {
        "schema", "panel_sha256", "source_label_owner_sha256", "targets", "authority",
        "production_authorized"}, "unexpected fit-label fields or held-label leak")
    require(labels["schema"] == FIT_SCHEMA and labels["panel_sha256"] == gate.digest(panel) and
            gate.sha(labels["source_label_owner_sha256"]) and labels["authority"] == "DENY_ALL" and
            labels["production_authorized"] is False, "fit source custody invalid")
    expected = [x["case_id"] for x in panel["cases"] if x["split"] == "fit"]
    targets = labels["targets"]
    require(type(targets) is list and len(targets) == len(expected),
            "fit targets incomplete or test/calibration data mixed")
    values = []
    for case_id, row in zip(expected, targets, strict=True):
        require(type(row) is dict and set(row) == {"case_id", "target"} and
                row["case_id"] == case_id and type(row["target"]) is int and row["target"] in (0, 1),
                "fit labels reordered, non-binary, or from a heldout source")
        values.append(row["target"])
    require(0 in values and 1 in values, "fitting data has no binary class support")
    return values


def projection_plan(bank):
    """Unsigned label-independent feature hashing: no fitted projection parameters."""
    d = bank["encoder_output_dimension"]
    # A source identity makes the hash basis model-specific, but never label-driven.
    fixed = f"hepta.stem.matched-projection.v1|{bank['model']}|{bank['revision']}|{bank['source_weights_sha256']}|"
    buckets, signs = [], []
    for i in range(d):
        h = hashlib.sha256((fixed + str(i)).encode("ascii")).digest()
        buckets.append(int.from_bytes(h[:4], "big") % WIDTH)
        signs.append(1 if h[4] & 1 else -1)
    return buckets, signs, _hash({"buckets": buckets, "signs": signs,
                                  "model": bank["model"], "input_width": d})


def project_bank(bank):
    """Produce a fixed 128D float32 view. Count transform work, do not call it free."""
    import numpy as np
    d = bank["encoder_output_dimension"]
    buckets, signs, token = projection_plan(bank)
    rows = bank["rows"]
    x = np.array([r["values"] for r in rows], dtype=np.float32)
    require(x.shape == (len(rows), d) and np.isfinite(x).all(), "non-finite physical features")
    y = np.zeros((len(rows), WIDTH), dtype=np.float32)
    scale = np.float32(1.0 / math.sqrt(max(1.0, d / WIDTH)))
    for j in range(d):
        y[:, buckets[j]] += (np.float32(signs[j]) * x[:, j]) * scale
    require(np.isfinite(y).all(), "projection instability")
    cost = {"projection_adds": len(rows) * d,
            "projection_multiplies": len(rows) * d,
            "projection_scratch_bytes": len(rows) * WIDTH * 4,
            "projection_index_bytes": d * 8,
            "projection_trainable_params": 0,
            "projection_digest": token,
            "lossy_projected_dimension": WIDTH}
    return y, cost


def new_head(torch, seed):
    require(type(seed) is int and 0 <= seed <= 2**31-1, "invalid deterministic seed")
    torch.manual_seed(seed)
    head = torch.nn.Sequential(torch.nn.Linear(WIDTH, HIDDEN),
                               torch.nn.Sigmoid(), torch.nn.Linear(HIDDEN, 1))
    require(sum(p.numel() for p in head.parameters()) == PARAMS, "head budget drift")
    return head


def train_one(panel, bank, labels, *, seed=None):
    """40 true FP32 full-batch SGD steps on FIT only; CAL/TEST predictions not scored."""
    import numpy as np
    import torch
    dim = validate_bank(panel, bank)
    truth = validate_fit(panel, labels)
    budget = panel["budget"]
    require(budget["head_trainable_params"] == PARAMS and budget["head_steps"] == STEPS and
            budget["head_optimizer"] == "sgd-lr-0.1" and budget["precision"] == "float32",
            "not a matched 4,161-parameter / 40-step trial")
    seed = budget["head_seed"] if seed is None else seed
    x, projection_cost = project_bank(bank)
    xs = torch.from_numpy(x.copy())
    fit_ids = [i for i, c in enumerate(panel["cases"]) if c["split"] == "fit"]
    fit_x = xs[fit_ids]
    fit_y = torch.tensor(truth, dtype=torch.float32).reshape(-1, 1)
    head = new_head(torch, seed)
    orig = {k: v.detach().cpu().numpy().copy() for k, v in head.state_dict().items()}
    optimizer = torch.optim.SGD(head.parameters(), lr=LR)
    begin_cpu, begin_wall = time.process_time_ns(), time.monotonic_ns()
    for _ in range(STEPS):
        optimizer.zero_grad(set_to_none=True)
        logits = head(fit_x)
        loss = torch.nn.functional.binary_cross_entropy_with_logits(logits, fit_y)
        require(bool(torch.isfinite(loss)), "unstable optimizer")
        loss.backward()
        optimizer.step()
    train_cpu, train_wall = time.process_time_ns() - begin_cpu, time.monotonic_ns() - begin_wall
    head.eval()
    with torch.inference_mode():
        all_logits = head(xs).reshape(-1).cpu().numpy()
    current = {k: v.detach().cpu().numpy().copy() for k, v in head.state_dict().items()}
    require(all(np.isfinite(v).all() for v in current.values()) and np.isfinite(all_logits).all(),
            "nonfinite parameters or predictions")
    weight_digest = hashlib.sha256()
    for name, tensor in sorted(current.items()):
        weight_digest.update(name.encode("ascii") + b"\0" + tensor.tobytes(order="C"))
    # This content is an in-memory PRIVATE verifier handoff, not a signed artifact.
    split = {s: [{"case_id": c["case_id"], "logit": float(all_logits[i])}
                 for i, c in enumerate(panel["cases"]) if c["split"] == s]
             for s in ("cal", "test")}
    public = {"schema": SCHEMA, "model": bank["model"], "repo": bank["repo"],
              "revision": bank["revision"], "panel_sha256": gate.digest(panel),
              "feature_bank_sha256": _hash(bank), "fit_labels_sha256": _hash(labels),
              "actual_original_encoder_source_sha256": bank["source_weights_sha256"],
              "trainable_params": PARAMS, "steps": STEPS, "learning_rate": LR,
              "projection": projection_cost, "feature_dim": dim,
              "head_weight_sha256": weight_digest.hexdigest(), "seed": seed,
              "fit_train_cpu_ns_self_reported": train_cpu,
              "fit_train_wall_ns_self_reported": train_wall,
              "projected_inputs_reused_for_head": True,
              "has_calibration_labels": False, "has_test_labels": False,
              "producer_model_origin_authenticated": False,
              "equal_pretrained_lifecycle_cost_verified": False,
              "future_window_uplift_verified": False,
              "production_promotion_permitted": False,
              "authority": "DENY_ALL", "disposition": "HOLD_NO_GO",
              "raw_calibration_logits": split["cal"], "raw_test_logits": split["test"]}
    return {"receipt": public, "initial_head_tensors": orig,
            "trained_head_tensors": current}
