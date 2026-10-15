#!/usr/bin/env python3
"""Actually train a sparse Top-1 Hepta Head bank, not soft-trained weights.

This is a research-only controlled CPU study. A chosen Head is the ONLY Head
forwarded for a given row during training AND inference. Policy-gradient router
updates use only old/new fitting labels. No runtime/selection/split authority.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Any

from qualification.cell_meta_execution_af import physical_router_audit as soft_audit
from qualification.cell_meta_execution_af import physical_router_top1_review as posthoc_audit
from qualification.cell_meta_execution_af import physical_router_trial as base

SCHEMA = "hepta.cell-meta-hard-trained-top1.v1"
LR = 0.35
REINFORCE_SCALE = 0.4
ENTROPY_SCALE = 0.002
REGISTERED_SEEDS = (41, 47, 53)


class HardTrainDenied(ValueError):
    """Fail closed on an unpaired input or unsupported experiment claim."""


def check(ok: bool, message: str) -> None:
    if not ok:
        raise HardTrainDenied(message)


def float_blob(tensor: Any) -> dict[str, Any]:
    data = tensor.detach().cpu().contiguous().numpy().astype("<f4", copy=False)
    return {"shape": list(data.shape), "data_le_hex": data.tobytes().hex()}


def _route_trace(indices: list[int]) -> str:
    """Row-ordered little-bit-order packed selected expert IDs."""
    raw = bytearray((len(indices) + 7) // 8)
    for index, value in enumerate(indices):
        check(type(value) is int and value in (0, 1), "invalid hard-route ID")
        raw[index // 8] |= value << (index % 8)
    return raw.hex()


@dataclass
class Work:
    train_head_0_rows: int = 0
    train_head_1_rows: int = 0
    eval_head_0_rows: int = 0
    eval_head_1_rows: int = 0
    train_router_rows: int = 0
    eval_router_rows: int = 0
    sampled_routes: int = 0
    train_head_batches: int = 0
    eval_head_batches: int = 0
    optimizer_steps: int = 0
    learned_gate_optimizer_steps: int = 0
    sample_exposures: int = 0
    diagnostic_head_rows: int = 0
    diagnostic_router_rows: int = 0


class SparseTop1Bank:
    """Trainable two-Head bank with score-function routing and bounded counters."""

    def __init__(self, width: int, feature_index: int, *, seed: int):
        import torch

        self.torch = torch
        self.width = width
        self.feature_index = feature_index
        self.weights = torch.nn.Parameter(torch.zeros((2, width + 1), dtype=torch.float32))
        self.gate = torch.nn.Parameter(torch.zeros(width + 1, dtype=torch.float32))
        self.rng = torch.Generator(device="cpu").manual_seed(seed ^ 0x45CC)
        self.work = Work()
        self.split = False
        self.mode = "no_change"

    def extended(self, x: Any) -> Any:
        return self.torch.cat((x, self.torch.ones((len(x), 1))), dim=1)

    def forward(self, x: Any, *, train: bool, count: bool = True) -> tuple[Any, Any, Any]:
        torch = self.torch
        b = self.extended(x)
        log_probs = None
        entropy = None
        if not self.split:
            selected = torch.zeros((len(x),), dtype=torch.long)
        else:
            logits = b @ self.gate
            if count:
                if train:
                    self.work.train_router_rows += len(x)
                else:
                    self.work.eval_router_rows += len(x)
            if train and self.mode in ("learned_router", "adaptive_split"):
                alpha = torch.sigmoid(logits).clamp(base.EPS, 1.0 - base.EPS)
                selected = (torch.rand((len(x),), generator=self.rng) < alpha.detach()).long()
                log_probs = torch.where(selected.bool(), torch.log(alpha), torch.log1p(-alpha))
                entropy = -(alpha * torch.log(alpha) + (1 - alpha) * torch.log1p(-alpha))
                if count:
                    self.work.sampled_routes += len(x)
            else:
                # Both fixed and learned inference execute one router dot-product.
                # No soft mixture of Head predictions is computed here.
                selected = (logits >= 0).long()
        output = torch.zeros((len(x),), dtype=torch.float32)
        for expert_id in (0, 1):
            indices = torch.nonzero(selected == expert_id, as_tuple=True)[0]
            if indices.numel() == 0:
                continue
            logits = self.extended(x.index_select(0, indices)) @ self.weights[expert_id]
            values = torch.sigmoid(logits).clamp(base.EPS, 1.0 - base.EPS)
            output = output.index_copy(0, indices, values)
            if count:
                count_key = ("train" if train else "eval") + f"_head_{expert_id}_rows"
                setattr(self.work, count_key, getattr(self.work, count_key) + len(indices))
                batch_key = "train_head_batches" if train else "eval_head_batches"
                setattr(self.work, batch_key, getattr(self.work, batch_key) + 1)
        return output, selected, (log_probs, entropy)

    def clone_parent(self, sample: Any, arm: str) -> None:
        check(arm in ("fixed_router", "learned_router", "adaptive_split"), "invalid growth arm")
        with self.torch.no_grad():
            before = self.forward(sample, train=False, count=False)[0].clone()
            self.weights[1].copy_(self.weights[0])
            self.gate.zero_()
            self.gate[self.feature_index] = 1.0
            self.split, self.mode = True, arm
            after = self.forward(sample, train=False, count=False)[0]
            check(bool(self.torch.allclose(before, after, atol=1e-7, rtol=0)),
                  "split violates exact parent-output parity")
            check(bool(self.torch.equal(self.weights[0], self.weights[1])),
                  "child did not inherit exact parent")
            # These are real Tensor forwards: explicitly meter them even though
            # they do not enter a training gradient or final scored prediction.
            self.work.diagnostic_head_rows += 2 * len(sample)
            self.work.diagnostic_router_rows += len(sample)

    def weight_inventory(self) -> tuple[dict[str, dict[str, Any]], str]:
        tensors = {"heads": float_blob(self.weights), "gate": float_blob(self.gate)}
        h = hashlib.sha256()
        for name in ("heads", "gate"):
            item = tensors[name]
            h.update(name.encode() + b"\0")
            h.update(base.canonical(item["shape"]) + b"\0")
            h.update(bytes.fromhex(item["data_le_hex"]))
        return tensors, h.hexdigest()


def train_one(panel: dict[str, Any], arm: str, *, steps: int) -> dict[str, Any]:
    import torch
    import torch.nn.functional as F

    check(arm in base.ARMS and type(steps) is int and 2 <= steps <= 100,
          "unregistered arm or update budget")
    meta = panel["source"]
    x0, y0 = base.vectors(panel, "old_train")
    x1, y1 = base.vectors(panel, "new_train")
    xall, yall = torch.cat((x0, x1)), torch.cat((y0, y1))
    bank = SparseTop1Bank(meta["dim"], meta["router_feature_index"], seed=meta["seed"])
    optimizer = torch.optim.SGD((bank.weights, bank.gate), lr=LR)
    start = time.process_time()

    for _ in range(steps):
        optimizer.zero_grad(set_to_none=True)
        p, _, _ = bank.forward(x0, train=True)
        loss = F.binary_cross_entropy(p, y0)
        check(bool(torch.isfinite(loss)), "nonfinite initial training loss")
        loss.backward()
        optimizer.step()
        bank.work.optimizer_steps += 1
        bank.work.sample_exposures += len(x0)
    stage1 = float_blob(bank.weights[0])
    with torch.no_grad():
        old_brier = float(((bank.forward(x0, train=False, count=False)[0] - y0) ** 2).mean())
        new_brier = float(((bank.forward(x1, train=False, count=False)[0] - y1) ** 2).mean())
        # Frozen training-only baseline, independent of subsequent stochastic route samples.
        parent_old_loss = float(F.binary_cross_entropy(
            bank.forward(xall, train=False, count=False)[0], yall))
    # Frozen Brier/parent baseline also execute actual extra Head forwards.
    bank.work.diagnostic_head_rows += len(x0) + len(x1) + len(xall)
    excess = new_brier - old_brier
    trigger = arm != "no_change" and (arm != "adaptive_split" or excess > 0.08)
    if trigger:
        bank.clone_parent(x0, arm)
    stage1_child = float_blob(bank.weights[1])
    stage1_gate = float_blob(bank.gate)

    trace: list[str] = []
    for _ in range(steps):
        optimizer.zero_grad(set_to_none=True)
        p, selected, policy = bank.forward(xall, train=True)
        losses = F.binary_cross_entropy(p, yall, reduction="none")
        loss = losses.mean()
        if trigger and arm in ("learned_router", "adaptive_split"):
            log_probs, entropy = policy
            check(log_probs is not None and entropy is not None, "missing stochastic route")
            # REINFORCE; frozen pre-stage2 constant avoids action-dependent baseline bias.
            loss = loss + REINFORCE_SCALE * ((losses.detach() - parent_old_loss) * log_probs).mean()
            loss = loss - ENTROPY_SCALE * entropy.mean()
            bank.work.learned_gate_optimizer_steps += 1
        check(bool(torch.isfinite(loss)), "nonfinite specialized training loss")
        loss.backward()
        optimizer.step()
        bank.work.optimizer_steps += 1
        bank.work.sample_exposures += len(xall)
        trace.append(_route_trace(selected.detach().cpu().tolist()))

    cpu_seconds = time.process_time() - start
    blobs, weight_sha = bank.weight_inventory()
    with torch.no_grad():
        prelabel_predictions: dict[str, list[dict[str, Any]]] = {}
        for part in base.EVAL_PARTITIONS:
            x, _ = base.vectors(panel, part, include_labels=False)
            probabilities, route, _ = bank.forward(x, train=False)
            check(bool(torch.isfinite(probabilities).all()), "nonfinite Top-1 final probability")
            prelabel_predictions[part] = [
                {"id": row["id"], "selected_head": selected, "probability": round(float(p), 9)}
                for row, selected, p in zip(panel["partitions"][part], route.tolist(),
                                             probabilities.tolist(), strict=True)
            ]
    w = bank.work
    head_rows = w.train_head_0_rows + w.train_head_1_rows
    eval_rows = w.eval_head_0_rows + w.eval_head_1_rows
    n0, n1 = len(x0), len(x1)
    ne = sum(len(panel["partitions"][part]) for part in base.EVAL_PARTITIONS)
    check(head_rows == steps * (2*n0 + n1) and eval_rows == ne,
          "actual Top-1 Head dispatch failed row conservation")
    parameter_slots = bank.weights.numel() + bank.gate.numel()
    return {
        "arm": arm, "split_proposed": trigger, "split_threshold": 0.08,
        "train_only_old_brier": round(old_brier, 9),
        "train_only_new_brier": round(new_brier, 9),
        "train_only_excess_brier": round(excess, 9),
        "stage1_parent_fp32": stage1, "stage1_child_fp32": stage1_child,
        "stage1_gate_fp32": stage1_gate,
        "weights_sha256": weight_sha, "weights_fp32": blobs,
        "prediction_sha256": base.digest(prelabel_predictions),
        "predictions": prelabel_predictions,
        "stage2_selected_head_bitsets_le": trace,
        "parameter_slots": parameter_slots,
        "resident_weight_bytes_fp32": parameter_slots * 4,
        "meters": {
            "train_head_0_rows": w.train_head_0_rows,
            "train_head_1_rows": w.train_head_1_rows,
            "eval_head_0_rows": w.eval_head_0_rows,
            "eval_head_1_rows": w.eval_head_1_rows,
            "train_router_rows": w.train_router_rows,
            "eval_router_rows": w.eval_router_rows,
            "sampled_routes": w.sampled_routes,
            "train_head_batches": w.train_head_batches,
            "eval_head_batches": w.eval_head_batches,
            "optimizer_steps": w.optimizer_steps,
            "learned_gate_optimizer_steps": w.learned_gate_optimizer_steps,
            "sample_exposures": w.sample_exposures,
            "diagnostic_head_rows": w.diagnostic_head_rows,
            "diagnostic_router_rows": w.diagnostic_router_rows,
            "train_cpu_seconds": round(cpu_seconds, 6),
        },
    }


def score_after_seal(panel: dict[str, Any], fitted: dict[str, Any]) -> dict[str, Any]:
    check(base.digest(fitted["predictions"]) == fitted["prediction_sha256"],
          "trained-hard prelabel prediction seal broken")
    answer = {}
    for part in base.EVAL_PARTITIONS:
        records = panel["partitions"][part]
        predictions = fitted["predictions"][part]
        check(len(records) == len(predictions) and
              all(x["id"] == y["id"] for x, y in zip(records, predictions, strict=True)),
              "source row swapped before retrospective scoring")
        n = len(records)
        ps = [x["probability"] for x in predictions]
        ys = [x["label"] for x in records]
        answer[part] = {
            "count": n,
            "accuracy": round(sum(int((p >= .5) == bool(y)) for p, y in zip(ps, ys, strict=True))/n, 7),
            "brier": round(sum((p - y)**2 for p, y in zip(ps, ys, strict=True))/n, 7),
            "nll": round(-sum(y * math.log(p) + (1-y) * math.log1p(-p)
                              for p, y in zip(ps, ys, strict=True))/n, 7),
        }
    return answer


def produce(panel: dict[str, Any], soft: dict[str, Any], posthoc: dict[str, Any]) -> dict[str, Any]:
    base.validate(panel)
    soft_audit.validate(panel, soft)
    posthoc_audit.replay(panel, soft, posthoc)
    steps = soft["training_steps_each_stage"]
    check(panel["source"]["seed"] in REGISTERED_SEEDS and 2 <= steps <= 100,
          "only original paired training seeds and steps admitted")
    import torch
    torch.set_num_threads(1)
    results = []
    for arm in base.ARMS:
        candidate = train_one(panel, arm, steps=steps)
        results.append(candidate | {"retrospective_evaluation": score_after_seal(panel, candidate)})
    return {
        "schema": SCHEMA,
        "source_panel_sha256": base.digest(panel),
        "soft_predecessor_sha256": base.digest(soft),
        "posthoc_predecessor_sha256": base.digest(posthoc),
        "method": "genuinely-sparse-training-reinforce-top1-v1",
        "steps_each_stage": steps,
        "learning_rate": LR,
        "reinforce_scale": REINFORCE_SCALE,
        "entropy_scale": ENTROPY_SCALE,
        "router_sampling_seed_xor": 0x45CC,
        "shared_precomputed_features": True,
        "torch_cpu_fp32_training_self_reported": True,
        "matched_primary_train_eval_head_rows": True,
        "matched_all_head_forward_rows": False,
        "total_compute_matched": False,
        "prospective_future_windows_verified": False,
        "true_ood_verified": False,
        "independent_model_origin_verified": False,
        "external_training_execution_attested": False,
        "ndu_selection_authorized": False,
        "physical_cell_split_permitted": False,
        "model_promotion_permitted": False,
        "production_admission": "BLOCKED", "authority_posture": "DENY_ALL",
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", required=True, type=Path)
    parser.add_argument("--soft-report", required=True, type=Path)
    parser.add_argument("--posthoc-report", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        panel = base.read_panel(args.panel)
        soft = soft_audit.load(args.soft_report)
        posthoc = soft_audit.load(args.posthoc_report)
        report = produce(panel, soft, posthoc)
        payload = base.canonical(report) + b"\n"
        check(0 < len(payload) <= base.MAX_BYTES, "bounded report required")
        fd = os.open(args.out, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        print(json.dumps({"output": str(args.out), "sha256": hashlib.sha256(payload).hexdigest(),
                          "authority_posture": "DENY_ALL"}))
        return 0
    except (HardTrainDenied, base.InvalidPanel, soft_audit.AuditError,
            posthoc_audit.Top1AuditError, ValueError, TypeError, OSError,
            RuntimeError, IndexError, KeyError, RecursionError) as exc:
        print(f"HARD-TRAIN DENIED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
