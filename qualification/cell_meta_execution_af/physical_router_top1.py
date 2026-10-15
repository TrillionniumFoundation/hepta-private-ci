#!/usr/bin/env python3
"""Real CPU Top-1 Head dispatch over existing, frozen Soft-MoE Head weights.

Research-only: no retraining, artifact selection, independent model attestation,
NDU, FinalUse, CellSplit or production authority. This is a *post-training*
soft-vs-hard-routing ablation, NOT a matched-budget training study.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Any

from qualification.cell_meta_execution_af import physical_router_audit as original_audit
from qualification.cell_meta_execution_af import physical_router_trial as original_trial

SCHEMA = "hepta.cell-meta-top1-physical-research.v1"
EVAL_PARTS = original_trial.EVAL_PARTITIONS
ARMS = original_trial.ARMS


class Top1Denied(ValueError):
    """A research artifact violates the frozen original trial/Top-1 contract."""


def check(condition: bool, message: str) -> None:
    if not condition:
        raise Top1Denied(message)


def _decode_tensor(obj: dict[str, Any], shape: tuple[int, ...]):
    import torch

    check(type(obj) is dict and set(obj) == {"shape", "data_le_hex"} and
          obj["shape"] == list(shape), "wrong frozen tensor schema")
    data = obj["data_le_hex"]
    check(type(data) is str and len(data) == 8 * math.prod(shape) and
          all(c in "0123456789abcdef" for c in data), "wrong FP32 bytes")
    # Fresh mutable byte copy: never alias/mutate the original read-only evidence.
    return torch.frombuffer(bytearray.fromhex(data), dtype=torch.float32).clone().reshape(shape)


def infer_top1(panel: dict[str, Any], soft_report: dict[str, Any]) -> dict[str, Any]:
    """Physical grouped Top-1 matmul: each input row reaches exactly ONE Head."""
    import torch

    original_trial.validate(panel)
    # The original independent stdlib replay must accept the complete 4-arm fit
    # before this layer may claim to reuse those FP32 weights.
    original_audit.validate(panel, soft_report)
    torch.set_num_threads(1)
    width = panel["source"]["dim"]
    route_index = panel["source"]["router_feature_index"]
    output: list[dict[str, Any]] = []
    for predecessor in soft_report["results"]:
        arm = predecessor["arm"]
        active = predecessor["split_proposed"]
        objects = predecessor["weights_fp32"]
        heads = _decode_tensor(objects["heads"], (2, width + 1))
        gate = _decode_tensor(objects["gate"], (width + 1,))
        grouped_rows = [0, 0]
        head_batches = 0
        router_rows = 0
        prediction: dict[str, list[dict[str, Any]]] = {}
        started = time.process_time()
        with torch.inference_mode():
            for part in EVAL_PARTS:
                records = panel["partitions"][part]
                x = torch.tensor([row["features"] for row in records], dtype=torch.float32)
                x_bias = torch.cat((x, torch.ones((len(records), 1), dtype=torch.float32)), dim=1)
                if not active:
                    route = torch.zeros((len(records),), dtype=torch.long)
                elif arm == "fixed_router":
                    route = (x[:, route_index] >= 0.0).long()
                else:
                    # One real batched router dot-product; sigmoid(alpha)>=0.5
                    # is equivalent to a nonnegative FP32 gate logit.
                    route = (x_bias @ gate >= 0.0).long()
                    router_rows += len(records)
                probabilities = torch.empty((len(records),), dtype=torch.float32)
                # Index-partition first; no computation of the unselected Head.
                for head_id in (0, 1):
                    indices = (route == head_id).nonzero(as_tuple=True)[0]
                    if indices.numel() == 0:
                        continue
                    logits = torch.mv(x_bias.index_select(0, indices), heads[head_id])
                    values = torch.sigmoid(logits).clamp(original_trial.EPS, 1 - original_trial.EPS)
                    probabilities.index_copy_(0, indices, values)
                    grouped_rows[head_id] += indices.numel()
                    head_batches += 1
                check(bool(torch.isfinite(probabilities).all()), "nonfinite physical Head output")
                prediction[part] = [
                    {"id": row["id"], "selected_head": int(selected),
                     "probability": round(float(prob), 9)}
                    for row, selected, prob in zip(records, route.tolist(),
                                                  probabilities.tolist(), strict=True)
                ]
        cpu_seconds = time.process_time() - started
        expected_rows = sum(len(panel["partitions"][part]) for part in EVAL_PARTS)
        check(sum(grouped_rows) == expected_rows, "Top-1 dispatch must execute one Head per row")
        # This seal is created before any evaluation label is accessed by score().
        prediction_sha = original_trial.digest(prediction)
        output.append({
            "arm": arm, "weights_sha256": predecessor["weights_sha256"],
            "predecessor_prediction_sha256": predecessor["prediction_sha256"],
            "split_proposed": active, "top1_prediction_sha256": prediction_sha,
            "top1_predictions": prediction,
            "metrics": {"executed_head_rows": sum(grouped_rows),
                        "head_0_rows": grouped_rows[0], "head_1_rows": grouped_rows[1],
                        "head_batch_matmuls": head_batches, "router_rows": router_rows,
                        "cpu_seconds": round(cpu_seconds, 6)},
        })
    return {
        "schema": SCHEMA, "source_panel_sha256": original_trial.digest(panel),
        "predecessor_report_sha256": original_trial.digest(soft_report),
        "method": "post-training-frozen-head-soft-versus-hard-top1",
        "training_weights_updated": False, "reported_real_cpu_tensor_dispatch": True,
        "compute_matched_training": False,
        "independent_pretrained_encoder_attested": False,
        "real_ood_verified": False, "future_window_prospective": False,
        "independent_outcome_verified": False, "production_admission": "BLOCKED",
        "model_selection_permitted": False, "physical_cell_split_permitted": False,
        "authority_posture": "DENY_ALL", "results": output,
    }


def score(panel: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Second pass reads labels only after the Top-1 prediction seal is frozen."""
    scores = {}
    for fitted in result["results"]:
        check(original_trial.digest(fitted["top1_predictions"]) == fitted["top1_prediction_sha256"],
              "unsealed Top-1 predictions")
        parts = {}
        for part in EVAL_PARTS:
            rows = panel["partitions"][part]
            values = fitted["top1_predictions"][part]
            check(len(rows) == len(values) and all(a["id"] == b["id"]
                  for a, b in zip(rows, values, strict=True)), "postseal source mismatch")
            n = len(rows)
            correct = 0
            brier = 0.0
            nll = 0.0
            for row, item in zip(rows, values, strict=True):
                p, y = item["probability"], row["label"]
                check(type(p) is float and original_trial.EPS <= p <= 1-original_trial.EPS,
                      "unbounded final probability")
                correct += int((p >= 0.5) == bool(y))
                brier += (p-y)**2
                nll -= y*math.log(p) + (1-y)*math.log1p(-p)
            parts[part] = {"count": n, "accuracy": round(correct/n, 7),
                           "brier": round(brier/n, 7), "nll": round(nll/n, 7)}
        scores[fitted["arm"]] = parts
    return scores


def create_report(panel: dict[str, Any], soft_report: dict[str, Any]) -> dict[str, Any]:
    result = infer_top1(panel, soft_report)
    scores = score(panel, result)
    for row in result["results"]:
        row["retrospective_evaluation"] = scores[row["arm"]]
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", required=True, type=Path)
    parser.add_argument("--soft-report", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        panel = original_trial.read_panel(args.panel)
        soft = original_audit.load(args.soft_report)
        report = create_report(panel, soft)
        payload = original_trial.canonical(report) + b"\n"
        check(0 < len(payload) <= original_trial.MAX_BYTES, "report size exceeded")
        fd = os.open(args.out, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        print(json.dumps({"top1_research_report": str(args.out),
                          "production_admission": "BLOCKED"}))
        return 0
    except (Top1Denied, original_audit.AuditError, original_trial.InvalidPanel,
            OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        print(f"TOP1 BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
