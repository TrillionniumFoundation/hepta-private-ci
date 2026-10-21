"""Candidate-only policy distillation into an existing tiny local-state gated Head.

Fit sees TRAIN labels ONLY. Prediction sees feature/state records but no labels.
A separate scorer opens future targets AFTER the prediction seal exists.
No approval, signers, actual external model evidence, or selection is created.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import time

import torch
from torch.nn import functional as F
from multimodal_head import StateGatedCellHead


class DistillError(ValueError):
    pass


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False) + "\n").encode()


def _digest_model(model):
    raw = bytearray(b"hepta.shadow-state-gated-distillation.v1\0")
    for name, value in sorted(model.state_dict().items()):
        tensor = value.detach().cpu().contiguous()
        raw.extend(_canonical([name, list(tensor.shape), str(tensor.dtype)]))
        raw.extend(tensor.numpy().tobytes())
    return _sha(raw)


@dataclass(frozen=True)
class Row:
    case_id: str
    group_id: str
    observed_at: int
    feature: tuple[float, ...]
    state: tuple[float, ...]


@dataclass(frozen=True)
class TrainedHead:
    model: StateGatedCellHead
    model_sha256: str
    initial_sha256: str
    train_groups: frozenset[str]
    train_case_ids: frozenset[str]
    train_max_time: int
    optimizer_steps: int
    train_wall_ns: int
    parameter_count: int
    declared_teacher: str
    production_accepted: bool = False


def _inputs(rows, feature_dim, state_dim, *, allow_empty=False):
    if ((not rows and not allow_empty) or len(rows) > 16384
            or any(type(r) is not Row for r in rows)):
        raise DistillError("bounded typed observation records required")
    keys, groups = set(), set()
    for r in rows:
        if (not r.case_id or not r.group_id or len(r.case_id) > 128 or len(r.group_id) > 128
                or r.case_id in keys or type(r.observed_at) is not int or r.observed_at < 1
                or len(r.feature) != feature_dim or len(r.state) != state_dim):
            raise DistillError("input identity, time or width drift")
        if any(type(x) not in (float, int) or not math.isfinite(x) or abs(x) > 8
               for x in (*r.feature, *r.state)):
            raise DistillError("nonfinite or unbounded Q24-ready features")
        keys.add(r.case_id)
        groups.add(r.group_id)
    features = torch.tensor([r.feature for r in rows], dtype=torch.float32)
    states = torch.tensor([r.state for r in rows], dtype=torch.float32)
    return features, states, keys, groups


def fit(train_rows: tuple[Row, ...], train_targets: dict[str, int], *,
        teacher_sha256: str, feature_dim: int, state_dim: int,
        rank: int, classes: int = 2, steps: int = 128,
        seed: int = 17) -> TrainedHead:
    if (type(teacher_sha256) is not str or len(teacher_sha256) != 64 or
            any(c not in "0123456789abcdef" for c in teacher_sha256)
            or type(steps) is not int or not 1 <= steps <= 512
            or type(seed) is not int or not 0 <= seed < 2**32):
        raise DistillError("pinned teacher identity and fixed fit budget required")
    x, s, keys, groups = _inputs(train_rows, feature_dim, state_dim)
    if len(train_rows) < 8 or len(groups) < 2 or set(train_targets) != keys:
        raise DistillError("train-only complete labels and independent groups required")
    if any(type(v) is not int or not 0 <= v < classes for v in train_targets.values()):
        raise DistillError("bounded teacher action labels required")
    y = torch.tensor([train_targets[r.case_id] for r in train_rows], dtype=torch.long)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        model = StateGatedCellHead(feature_dim, state_dim, rank, classes)
    if model.parameter_count() > 16384:
        raise DistillError("head exceeds registered local parameter ceiling")
    init_digest = _digest_model(model)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.03, weight_decay=0.0)
    model.train()
    start = time.perf_counter_ns()
    for _ in range(steps):
        optimizer.zero_grad(set_to_none=True)
        loss = F.cross_entropy(model(x, s), y)
        if not bool(torch.isfinite(loss).item()):
            raise DistillError("nonfinite loss")
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
    elapsed = time.perf_counter_ns() - start
    model.eval().requires_grad_(False)
    # These are separate candidate bytes. The shared Stem was never updated.
    return TrainedHead(model, _digest_model(model), init_digest, frozenset(groups),
                       frozenset(keys), max(r.observed_at for r in train_rows),
                       steps, elapsed, model.parameter_count(), teacher_sha256)


def predict(candidate: TrainedHead, future_rows: tuple[Row, ...]) -> dict:
    if not isinstance(candidate, TrainedHead) or candidate.production_accepted:
        raise DistillError("only unselected shadow candidates")
    model = candidate.model
    if (model.training or any(p.requires_grad for p in model.parameters())
            or _digest_model(model) != candidate.model_sha256):
        raise DistillError("candidate mutated since fit")
    x, s, keys, groups = _inputs(future_rows, model.feature_dim, model.state_dim)
    if (candidate.train_case_ids & keys or candidate.train_groups & groups
            or min(row.observed_at for row in future_rows) <= candidate.train_max_time):
        raise DistillError("future source leakage or noncausal timestamp")
    with torch.inference_mode():
        probs = F.softmax(model(x, s), dim=-1).tolist()
    records = [{"case_id": row.case_id, "group_id": row.group_id,
                "observed_at": row.observed_at, "probabilities": [float(p) for p in prob]}
               for row, prob in zip(future_rows, probs)]
    body = {"schema": "hepta.ndu.cell-distill.sealed-predictions.v1",
            "candidate_sha256": candidate.model_sha256,
            "teacher_sha256": candidate.declared_teacher,
            "train_groups_sha256": _sha(_canonical(sorted(candidate.train_groups))),
            "predictions": records, "production_accepted": False}
    body["seal_sha256"] = _sha(_canonical(body))
    return body


def evaluate_sealed(seal: dict, future_targets: dict[str, tuple[str, int]]) -> dict:
    """Separate no-model evaluator: exact future rows, group and seal identity."""
    if type(seal) is not dict or seal.get("production_accepted") is not False:
        raise DistillError("unknown or authorized prediction record")
    body = {k: v for k, v in seal.items() if k != "seal_sha256"}
    if (body.get("schema") != "hepta.ndu.cell-distill.sealed-predictions.v1"
            or _sha(_canonical(body)) != seal.get("seal_sha256")):
        raise DistillError("prediction bytes altered after seal")
    rows = body["predictions"]
    if (not rows or type(future_targets) is not dict or
            set(future_targets) != {r["case_id"] for r in rows} or
            len(future_targets) != len(rows)):
        raise DistillError("future target alignment or coverage failure")
    correct, brier = 0, 0.0
    for row in rows:
        group, truth = future_targets[row["case_id"]]
        probs = row["probabilities"]
        if (type(group) is not str or row["group_id"] != group
                or type(truth) is not int or not 0 <= truth < len(probs)
                or len(probs) < 2 or any(type(p) is not float or not math.isfinite(p)
                                        or p < 0 or p > 1 for p in probs)
                or not abs(sum(probs) - 1) < 1e-5):
            raise DistillError("score tamper or label mismatch")
        correct += int(max(range(len(probs)), key=probs.__getitem__) == truth)
        brier += sum((p - int(i == truth))**2 for i, p in enumerate(probs))
    return {"cases": len(rows), "accuracy": correct / len(rows),
            "multiclass_brier": brier / len(rows),
            "model_sha256": body["candidate_sha256"],
            "predictions_sha256": seal["seal_sha256"],
            "independent_outcome_authenticated": False,
            "production_accepted": False}
