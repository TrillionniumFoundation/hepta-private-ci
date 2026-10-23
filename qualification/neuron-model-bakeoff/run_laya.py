#!/usr/bin/env python3
"""Offline Laya inference observation producer, NOT a qualification authority.

Requires installed laya, torch and psutil, and pre-staged exact local weights.
Never downloads checkpoints or changes the selected checkpoint during a run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time


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


def result_row(row: dict, answer: dict, *, elapsed_ms: float, rss: int, host_id: str,
               device: str, weights_sha256: str, threshold: float, gpu_allocator_peak: int | None) -> dict:
    probs = answer["probabilities"]
    if set(probs) != set(row["labels"]):
        raise ValueError("Laya returned wrong choice schema")
    confidence = max(float(probs[c]) for c in row["labels"])
    return {"case_id": row["case_id"], "probabilities": {c: float(probs[c]) for c in row["labels"]},
            "abstained": bool(confidence < threshold), "latency_ms": elapsed_ms,
            "rss_bytes": rss, "gpu_peak_bytes": None,
            "gpu_allocator_peak_bytes": gpu_allocator_peak, "host_id": host_id,
            "device": device, "model_weights_sha256": weights_sha256}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--checkpoint-dir", type=Path, required=True)
    parser.add_argument("--weights-file", type=Path, required=True)
    parser.add_argument("--weights-sha256", required=True)
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
        if not args.host_id or args.output.exists():
            raise ValueError("explicit host and new output path are required; refuse overwrite")
        # Heavy optional dependencies are deliberately imported after exact-file checks.
        import laya
        import psutil
        import torch
        agent = laya.load(str(root), device=args.device, backend="eager")
        process = psutil.Process(os.getpid())
        if args.device == "cuda":
            torch.cuda.synchronize()
        with args.dataset.open(encoding="utf-8") as source, args.output.open("x", encoding="utf-8") as output:
            for text in source:
                if not text.strip():
                    continue
                row = json.loads(text)
                if row.get("split") not in ("test", "future"):
                    continue
                question = choice_question(row)
                # DO NOT pass label, group, OOD, split, or any ground truth to model.
                state = row["state"]
                if args.device == "cuda":
                    torch.cuda.reset_peak_memory_stats()
                    torch.cuda.synchronize()
                start = time.perf_counter()
                prediction = agent.predict(state, question,
                                           max_len=args.max_len, head_max_len=args.head_max_len)
                if args.device == "cuda":
                    torch.cuda.synchronize()
                elapsed = (time.perf_counter() - start) * 1_000
                allocated = int(torch.cuda.max_memory_allocated()) if args.device == "cuda" else None
                observation = result_row(
                    row, prediction["answers"]["decision"], elapsed_ms=elapsed,
                    rss=process.memory_info().rss, host_id=args.host_id, device=args.device,
                    weights_sha256=args.weights_sha256, threshold=args.confidence_min,
                    gpu_allocator_peak=allocated)
                output.write(json.dumps(observation, ensure_ascii=False, allow_nan=False) + "\n")
                output.flush()
                os.fsync(output.fileno())
    except (OSError, ValueError, KeyError, ImportError, RuntimeError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
