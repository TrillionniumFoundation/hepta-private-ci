#!/usr/bin/env python3
"""Offline Laya inference observation producer, NOT a qualification authority.

Requires installed laya, torch and psutil, and pre-staged exact local weights.
Never downloads checkpoints or changes the selected checkpoint during a run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time

import bakeoff
from laya_isolation import load_laya_isolated


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def choice_question(row: dict) -> dict:
    criteria = row.get("criteria")
    if criteria is None:
        criteria = {label: label for label in row["labels"]}
    if set(criteria) != set(row["labels"]):
        raise ValueError("choice labels/criteria mismatch")
    if not isinstance(row.get("question"), str) or not row["question"]:
        raise ValueError("question required")
    return {"decision": {"type": "choice", "instructions": row["question"], "criteria": criteria}}


def load_calibration(path: Path, rows: list[dict], weights_sha256: str, expected_threshold: float) -> float:
    """Require independent, precommitted calibration over ONLY the calibration split.

    The Laya SDK already applies its checkpoint's own temperatures. This profile
    applies an additional frozen temperature to the returned choice distribution.
    """
    value = json.loads(path.read_text(encoding="utf-8"))
    if type(value) is not dict or value.get("schema") != "hepta.neuron-bakeoff.laya-calibration.v1":
        raise ValueError("unregistered Laya calibration schema")
    if value.get("weights_sha256") != weights_sha256:
        raise ValueError("calibration model weights identity drift")
    calibration_rows = sorted((r for r in rows if r["split"] == "calibration"),
                              key=lambda r: r["case_id"])
    if not calibration_rows:
        raise ValueError("approved calibration rows required")
    calibration_digest = hashlib.sha256(bakeoff.canonical(calibration_rows)).hexdigest()
    if value.get("calibration_split_sha256") != calibration_digest:
        raise ValueError("independent calibration split digest drift")
    temp, threshold = value.get("temperature"), value.get("threshold")
    if (type(temp) not in (int, float) or not math.isfinite(temp) or
            not 0.1 <= temp <= 10 or type(threshold) not in (int, float) or
            not math.isfinite(threshold) or not 0 <= threshold <= 1 or
            threshold != expected_threshold):
        raise ValueError("temperature / frozen threshold not registered")
    return float(temp)


def apply_extra_temperature(probs: dict, temperature: float) -> dict:
    if (type(probs) is not dict or not probs or
            any(type(p) not in (int, float) or not math.isfinite(p) or
                p < 0 or p > 1 for p in probs.values()) or
            abs(sum(probs.values()) - 1.0) > 0.001):
        raise ValueError("invalid original Laya probability vector")
    weights = {key: max(float(prob), 1e-12) ** (1.0 / temperature)
               for key, prob in probs.items()}
    total = sum(weights.values())
    return {key: value / total for key, value in weights.items()}


def result_row(row: dict, answer: dict, *, elapsed_ms: float, rss: int, host_id: str,
               device: str, weights_sha256: str, calibration_sha256: str,
               threshold: float, gpu_allocator_peak: int | None) -> dict:
    probs = answer["probabilities"]
    if set(probs) != set(row["labels"]):
        raise ValueError("Laya returned wrong choice schema")
    confidence = max(float(probs[c]) for c in row["labels"])
    return {"case_id": row["case_id"], "probabilities": {c: float(probs[c]) for c in row["labels"]},
            "abstained": bool(confidence < threshold), "latency_ms": elapsed_ms,
            "rss_bytes": rss, "gpu_peak_bytes": None,
            "gpu_allocator_peak_bytes": gpu_allocator_peak, "host_id": host_id,
            "device": device, "model_weights_sha256": weights_sha256,
            "calibration_sha256": calibration_sha256}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--checkpoint-dir", type=Path, required=True)
    parser.add_argument("--weights-file", type=Path, required=True)
    parser.add_argument("--weights-sha256", required=True)
    parser.add_argument("--calibration-file", type=Path, required=True,
                        help="pinned, separately fitted Laya SDK temperature-calibration JSON")
    parser.add_argument("--host-id", required=True)
    parser.add_argument("--device", choices=["cpu", "cuda", "mps", "xpu"], required=True)
    parser.add_argument("--confidence-min", type=float, required=True,
                        help="Precommitted threshold selected on calibration split ONLY")
    parser.add_argument("--max-len", type=int, required=True)
    parser.add_argument("--head-max-len", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if not (0 <= args.confidence_min <= 1) or not (1 <= args.head_max_len <= args.max_len):
            raise ValueError("invalid precommitted confidence or context budgets")
        root = args.checkpoint_dir.resolve(strict=True)
        weight_path = args.weights_file.resolve(strict=True)
        if not weight_path.is_relative_to(root):
            raise ValueError("weights must be within checkpoint directory")
        if file_sha(weight_path) != args.weights_sha256:
            raise ValueError("selected weights SHA256 mismatch")
        calibration = args.calibration_file.resolve(strict=True)
        calibration_sha256 = file_sha(calibration)
        if not args.host_id or args.output.exists():
            raise ValueError("explicit host and new output path are required; refuse overwrite")
        # Freeze case-group separation and calibration before importing heavy SDKs.
        dataset_rows = bakeoff.records(args.dataset)
        bakeoff.validate_dataset(dataset_rows)
        temperature = load_calibration(calibration, dataset_rows,
                                       args.weights_sha256, args.confidence_min)
        # The pinned upstream Agent only accepts (model_id_or_path, device,
        # token, subfolder); there is NO backend= or calibration= argument.
        # It may rewrite tokenizer_config.json, hence the private bounded copy.
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["USE_TF"] = "0"
        import laya
        import psutil
        import torch
        agent, isolation = load_laya_isolated(root, laya.load, device=args.device)
        if agent.device.type != args.device:
            raise ValueError("Laya fallback to a different device during load")
        # Frozen experiment sequence budgets are applied to in-memory policy
        # configuration, not to the immutable publisher checkpoint artifacts.
        agent.cfg["max_len"] = args.max_len
        agent.cfg["head_max_len"] = args.head_max_len
        process = psutil.Process(os.getpid())
        if args.device == "cuda":
            torch.cuda.synchronize()
        with args.output.open("x", encoding="utf-8") as output:
            for row in dataset_rows:
                if row["split"] not in ("test", "future"):
                    continue
                question = choice_question(row)
                # DO NOT pass label, group, OOD, split or any ground truth to the model.
                state = row["state"]
                if args.device == "cuda":
                    torch.cuda.reset_peak_memory_stats()
                    torch.cuda.synchronize()
                start = time.perf_counter()
                prediction = agent.predict(state, question)
                if agent.device.type != args.device:
                    raise ValueError("Laya silently changed device during original policy forward")
                if args.device == "cuda":
                    torch.cuda.synchronize()
                elapsed = (time.perf_counter() - start) * 1_000
                allocated = int(torch.cuda.max_memory_allocated()) if args.device == "cuda" else None
                answer = dict(prediction["answers"]["decision"])
                answer["probabilities"] = apply_extra_temperature(
                    answer["probabilities"], temperature)
                observation = result_row(
                    row, answer, elapsed_ms=elapsed, rss=process.memory_info().rss,
                    host_id=args.host_id, device=args.device,
                    weights_sha256=args.weights_sha256, calibration_sha256=calibration_sha256,
                    threshold=args.confidence_min, gpu_allocator_peak=allocated)
                observation["sdk_probability_postcalibration_temperature"] = temperature
                observation["original_tokenizer_inventory_sha256"] = isolation[
                    "original_tokenizer_inventory_sha256"]
                observation["effective_tokenizer_inventory_sha256"] = isolation[
                    "effective_tokenizer_inventory_sha256"]
                output.write(json.dumps(observation, ensure_ascii=False, allow_nan=False) + "\n")
                output.flush()
                os.fsync(output.fileno())
        if file_sha(weight_path) != args.weights_sha256:
            raise ValueError("publisher model weights changed during load/forward")
    except (OSError, ValueError, KeyError, ImportError, RuntimeError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
