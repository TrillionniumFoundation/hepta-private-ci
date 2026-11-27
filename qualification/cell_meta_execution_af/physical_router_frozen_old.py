#!/usr/bin/env python3
"""Additive, shadow-only *actual frozen* old-task parent for Cell/Meta comparisons.

Unlike trial v1's 'no_change' (no structural split but continued joint SGD),
this reference trains only on old_train and freezes before seeing new_train.
No original owner, NDU selector, Codex, or production authority is affected.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any

from qualification.cell_meta_execution_af import physical_router_trial as trial

SCHEMA = "hepta.cell-meta-frozen-old-parent.v1"


def run(panel: dict[str, Any], *, steps: int = 24) -> dict[str, Any]:
    """Freeze exact FP32 parent after old_train; never train on new_train labels."""
    trial.validate(panel)
    trial.require(type(steps) is int and 2 <= steps <= 100, "bounded old-only SGD steps")
    import torch

    torch.set_num_threads(1)
    old_x, old_y = trial.vectors(panel, "old_train")
    source = panel["source"]
    bank = trial.TwoHeadBank(source["dim"], source["router_feature_index"], seed=source["seed"])
    optimizer = torch.optim.SGD((bank.weights, bank.gate), lr=0.6)
    before = time.process_time()
    for _ in range(steps):
        optimizer.zero_grad(set_to_none=True)
        probs = bank.forward(old_x)
        loss = torch.nn.functional.binary_cross_entropy(probs, old_y)
        trial.require(bool(torch.isfinite(loss)), "non-finite old-only SGD")
        loss.backward()
        optimizer.step()
        bank.counter.optimizer_updates += 1
        bank.counter.input_rows_trained += len(old_x)
    old_cpu_seconds = time.process_time() - before

    # The only mutable parameters are now finished. Scoring follows this seal.
    frozen_sha = bank.weight_sha()
    frozen_weights = bank.weight_blobs()
    predictions: dict[str, list[dict[str, Any]]] = {}
    with torch.no_grad():
        for part in trial.EVAL_PARTITIONS:
            x, _ = trial.vectors(panel, part, include_labels=False)
            probabilities = bank.forward(x).detach().tolist()
            trial.require(all(math.isfinite(p) for p in probabilities), "non-finite frozen prediction")
            predictions[part] = [
                {"id": row["id"], "probability": round(float(p), 9)}
                for row, p in zip(panel["partitions"][part], probabilities, strict=True)
            ]
    sealed_predictions = trial.digest(predictions)
    summary = trial.score_sealed(panel, {"predictions": predictions,
                                         "prediction_sha256": sealed_predictions})
    return {
        "schema": SCHEMA,
        "source_panel_sha256": trial.digest(panel),
        "source_kind": source["kind"],
        "source_scope": source["scope"],
        "seed": source["seed"],
        "freeze_point": "after_old_train_before_new_train",
        "trained_new_rows": 0,
        "split_proposed": False,
        "optimizer_steps_old_only": steps,
        "weights_sha256": frozen_sha,
        "weights_fp32": frozen_weights,
        "prediction_sha256": sealed_predictions,
        "predictions": predictions,
        "evaluation": summary,
        "meters": {
            "optimizer_steps": bank.counter.optimizer_updates,
            "sample_exposures": bank.counter.input_rows_trained,
            "head_forward_rows": bank.counter.head_rows,
            "router_forward_rows": bank.counter.router_rows,
            "train_cpu_seconds": round(old_cpu_seconds, 6),
        },
        "physically_executed_torch_fp32": True,
        "real_pretrained_encoder_executed": False,
        "original_source_authenticated": False,
        "independent_outcome_verified": False,
        "future_window_prospective": False,
        "total_compute_matched": False,
        "ndu_selection_authorized": False,
        "production_admission": "BLOCKED",
        "authority_posture": "DENY_ALL",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--panel", type=Path)
    source.add_argument("--synthetic-rule", choices=("stable", "conditional"))
    parser.add_argument("--seed", type=int, default=41)
    parser.add_argument("--steps", type=int, default=24)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        panel = trial.read_panel(args.panel) if args.panel else trial.synthetic_panel(
            seed=args.seed, rule=args.synthetic_rule)
        report = run(panel, steps=args.steps)
        payload = trial.canonical(report) + b"\n"
        trial.require(len(payload) <= trial.MAX_BYTES, "frozen baseline report too large")
        fd = os.open(args.report, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        print(json.dumps({"report_sha256": hashlib.sha256(payload).hexdigest(),
                          "production_admission": "BLOCKED", "freeze_point": report["freeze_point"]}))
        return 0
    except (trial.InvalidPanel, OSError, ValueError, RuntimeError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
