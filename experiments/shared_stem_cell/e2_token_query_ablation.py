"""Offline E2 shared-Token-Matrix vs pooled Head learning, research-only.

All features must originate from the SAME frozen Encoder physical forward.
This scorer alone does not verify model weights, labels, origin or future NDU.
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
import time

import torch
from torch import nn
from torch.nn import functional as F

SCHEMA = "hepta.stem.e2-token-query-physical-shadow.v1"
CAP = 2048
Q24 = 1 << 24
DIMENSIONS = (384, 768)
SPLITS = {"train": 128, "calibration": 32, "test": 64}
TEMPERATURES = (0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0)


class Invalid(ValueError):
    pass


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest_module(module: nn.Module) -> str:
    digest = hashlib.sha256(b"hepta.stem.e2-head-bytes.v1\0")
    for name, t in sorted(module.state_dict().items()):
        digest.update(name.encode() + b"\0")
        digest.update(t.detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def _q24_tensor(t: torch.Tensor, *, width: int, matrix: bool):
    if (not isinstance(t, torch.Tensor) or t.dtype != torch.float32 or t.device.type != "cpu"
            or t.ndim != (2 if matrix else 1) or t.shape[-1] != width
            or (matrix and (not 1 <= t.shape[0] <= 512))
            or not bool(torch.isfinite(t).all()) or not bool((t.abs() <= 8).all())
            or not bool(torch.equal(t * Q24, torch.round(t * Q24)))):
        raise Invalid("incomplete, noncanonical or unbounded frozen Q24 tensor")
    return t


def frozen_bank(cases: list[dict], snapshots: dict, *, width: int):
    """Strict source-identified immutability digest, not a model attestation."""
    if width not in DIMENSIONS or len(cases) != 224 or type(snapshots) is not dict:
        raise Invalid("unexpected task inventory or Stem width")
    identifiers = [r.get("case_id") for r in cases]
    if (len(identifiers) != len(set(identifiers)) or set(identifiers) != set(snapshots)
            or any(type(i) is not str or not i or len(i) > 128 for i in identifiers)):
        raise Invalid("missing/duplicate frozen case identity")
    split_counts = {split: sum(r.get("split") == split for r in cases) for split in SPLITS}
    if split_counts != SPLITS or any(type(r.get("label")) is not int or r["label"] not in (0, 1)
                                      or type(r.get("joint_input_digest")) is not str
                                      or len(r["joint_input_digest"]) != 64 for r in cases):
        raise Invalid("wrong source groups, labels or exact split")
    bank = hashlib.sha256(b"hepta.stem.e2-token-matrix-bank.v1\0")
    for ident in sorted(identifiers):
        snapshot = snapshots[ident]
        if type(snapshot) is not dict or set(snapshot) != {"tokens", "native_pooled"}:
            raise Invalid("missing actual unpadded matrix or native pooled vector")
        tokens = _q24_tensor(snapshot["tokens"], width=width, matrix=True)
        pooled = _q24_tensor(snapshot["native_pooled"], width=width, matrix=False)
        bank.update(ident.encode() + b"\0" + struct.pack("<II", tokens.shape[0], width))
        bank.update(tokens.contiguous().numpy().tobytes())
        bank.update(pooled.contiguous().numpy().tobytes())
    return {"case_count": len(identifiers), "dimension": width,
            "frozen_token_and_native_pooled_sha256": bank.hexdigest(),
            "authenticated_model_forward": False, "authority": "DENY_ALL"}


class Head(nn.Module):
    """Single-task binary learning; all trainable parameters explicitly counted."""
    def __init__(self, width: int, kind: str, initial_readout: torch.Tensor):
        super().__init__()
        if width not in DIMENSIONS or kind not in ("pooled_linear", "pooled_gated", "token_query"):
            raise Invalid("unregistered E2 ablation head")
        self.width, self.kind = width, kind
        self.readout = nn.Parameter(initial_readout.clone())
        self.bias = nn.Parameter(torch.zeros(()))
        if kind == "token_query":
            self.query = nn.Parameter(torch.zeros(width))
        elif kind == "pooled_gated":
            self.gate = nn.Parameter(torch.zeros(width))

    def forward(self, tokens: torch.Tensor, mask: torch.Tensor, pooled: torch.Tensor):
        if self.kind == "token_query":
            logits = torch.einsum("bld,d->bl", tokens, self.query) * math.sqrt(self.width)
            logits = logits.masked_fill(~mask, torch.finfo(logits.dtype).min)
            attention = F.softmax(logits, dim=1)
            value = F.normalize(torch.einsum("bl,bld->bd", attention, tokens), dim=-1)
            logodds = value @ self.readout + self.bias
        else:
            logodds = pooled @ self.readout + self.bias
            if self.kind == "pooled_gated":
                logodds = (pooled @ self.readout) * torch.sigmoid(
                    (pooled @ self.gate) * math.sqrt(self.width)) + self.bias
        return torch.stack((torch.zeros_like(logodds), logodds), dim=1)


def _materialize(cases: list[dict], snapshots: dict, width: int):
    max_tokens = max(snapshots[r["case_id"]]["tokens"].shape[0] for r in cases)
    batch = torch.zeros((len(cases), max_tokens, width), dtype=torch.float32)
    mask = torch.zeros((len(cases), max_tokens), dtype=torch.bool)
    pooled = torch.empty((len(cases), width), dtype=torch.float32)
    for i, row in enumerate(cases):
        tokens = snapshots[row["case_id"]]["tokens"]
        n = tokens.shape[0]
        batch[i, :n] = tokens
        mask[i, :n] = True
        pooled[i] = snapshots[row["case_id"]]["native_pooled"]
    return batch, mask, pooled


def _train(module, tokens, mask, pooled, y, *, steps: int, lr: float):
    before = _digest_module(module)
    initial_query = module.query.detach().clone() if module.kind == 'token_query' else None
    optimizer = torch.optim.SGD(module.parameters(), lr=lr)
    started = time.perf_counter_ns()
    for _ in range(steps):
        optimizer.zero_grad(set_to_none=True)
        loss = F.cross_entropy(module(tokens, mask, pooled), y)
        if not bool(torch.isfinite(loss)):
            raise Invalid("nonfinite supervised SGD loss")
        loss.backward()
        optimizer.step()
    end = _digest_module(module)
    if end == before:
        raise Invalid("no actual Head update")
    query_changed = None if initial_query is None else not bool(torch.equal(initial_query, module.query.detach()))
    if query_changed is False:
        raise Invalid("token attention query was never updated")
    return {"initial_head_sha256": before, "final_head_sha256": end,
            "learnable_query_actually_changed": query_changed,
            "train_steps": steps, "train_ms": (time.perf_counter_ns() - started) / 1e6,
            "trainable_parameters": sum(p.numel() for p in module.parameters())}


def study(cases: list[dict], snapshots: dict, *, width: int,
          seed: int = 20261015, steps: int = 40, lr: float = 0.15):
    if (type(seed) is not int or type(steps) is not int or not 1 <= steps <= 128
            or type(lr) not in (int, float) or not math.isfinite(lr) or not 0 < lr <= 1):
        raise Invalid("unregistered E2 Head optimizer schedule")
    original = frozen_bank(cases, snapshots, width=width)
    per_split = {split: [r for r in cases if r["split"] == split] for split in SPLITS}
    train, calibration, test = [per_split[k] for k in SPLITS]
    # Source labels are TRAIN-only for updates; CAL-only for temperatures;
    # TEST labels are not used at any point in producing predictions.
    train_tokens, train_mask, train_pooled = _materialize(train, snapshots, width)
    y = torch.tensor([r["label"] for r in train], dtype=torch.long)
    cal_tokens, cal_mask, cal_pooled = _materialize(calibration, snapshots, width)
    cy = torch.tensor([r["label"] for r in calibration], dtype=torch.long)
    scored = calibration + test
    scored_tokens, scored_mask, scored_pooled = _materialize(scored, snapshots, width)
    rng = torch.Generator(device="cpu").manual_seed(seed)
    common_readout = torch.randn(width, generator=rng) * (0.05 / math.sqrt(width))
    results = {}
    for kind in ("pooled_linear", "pooled_gated", "token_query"):
        head = Head(width, kind, common_readout)
        expected = width + 1 if kind == "pooled_linear" else 2 * width + 1
        if sum(p.numel() for p in head.parameters()) != expected or expected > CAP:
            raise Invalid("incorrect exact private Head parameter accounting")
        frozen_digest = _digest_module(head)
        with torch.no_grad():
            frozen_scores = head(scored_tokens, scored_mask, scored_pooled)
        receipt = _train(head, train_tokens, train_mask, train_pooled, y,
                         steps=steps, lr=lr)
        if _digest_module(head) != receipt["final_head_sha256"]:
            raise Invalid("saved Head changed after training")
        with torch.no_grad():
            cal_logits = head(cal_tokens, cal_mask, cal_pooled)
            temperature = min(TEMPERATURES, key=lambda t: float(F.cross_entropy(cal_logits / t, cy)))
            scores = F.softmax(head(scored_tokens, scored_mask, scored_pooled) / temperature,
                               dim=-1)[:, 1].tolist()
        results[kind] = {
            "frozen_initial_head_sha256": frozen_digest,
            "frozen_initial_predictions_sha256": _sha(
                frozen_scores.detach().cpu().numpy().tobytes()),
            "train_receipt": receipt,
            "calibration_temperature": temperature,
            "predictions": [{"case_id": row["case_id"], "split": row["split"],
                             "joint_input_digest": row["joint_input_digest"],
                             "positive_probability": float(p)} for row, p in zip(scored, scores)],
        }
    if frozen_bank(cases, snapshots, width=width) != original:
        raise Invalid("frozen token matrix or native pool mutated during Head learning")
    return {"schema": SCHEMA, "width": width, "feature_bank": original,
            "head_parameter_ceiling": CAP, "seed": seed, "steps": steps,
            "learning_rate": lr, "optimizer": "full_batch_sgd",
            "arms": results, "same_original_physical_token_matrix_claimed": True,
            "one_encoder_forward_per_input_required": True,
            "pretrained_model_origin_independently_authenticated": False,
            "authentic_future_ndu_available": False,
            "production_no_change_authenticated": False,
            "stem_winner_selected": False, "production_promotion_permitted": False,
            "authority": "DENY_ALL"}
