#!/usr/bin/env python3
"""Independent stdlib numeric audit for the nonauthorizing physical Router trial.

No Torch, trainer, weight-loader, original-signature, or promotion code is imported.
Audits final exact tiny FP32 weight bytes, predictions, metric arithmetic and
claimed row counts; does NOT authenticate underlying Encoder or training work.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import sys
from pathlib import Path
from typing import Any

SCHEMA = "hepta.cell-meta-physical-router-trial.v1"
PARTS = ("old_retention", "future_1", "future_2", "ood")
ARMS = ("no_change", "fixed_router", "learned_router", "adaptive_split")
EPS = 1e-6


class AuditError(ValueError):
    pass


def check(ok: bool, reason: str) -> None:
    if not ok:
        raise AuditError(reason)


def canonical(x: Any) -> bytes:
    return json.dumps(x, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(x: Any) -> str:
    return hashlib.sha256(canonical(x)).hexdigest()


def pairs_unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for key, value in pairs:
        check(key not in obj, "duplicate JSON key")
        obj[key] = value
    return obj


def load(path: Path, *, limit: int = 3 * 1024 * 1024) -> Any:
    import os
    import stat

    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        a = os.fstat(fd)
        check(stat.S_ISREG(a.st_mode) and 0 < a.st_size <= limit, "bounded regular file required")
        with os.fdopen(fd, "rb", closefd=False) as f:
            raw = f.read(limit + 1)
        b = os.fstat(fd)
        check(len(raw) == a.st_size and (a.st_dev, a.st_ino, a.st_mtime_ns, a.st_size)
              == (b.st_dev, b.st_ino, b.st_mtime_ns, b.st_size), "changed input file")
    finally:
        os.close(fd)
    try:
        return json.loads(raw, object_pairs_hook=pairs_unique,
                          parse_constant=lambda x: (_ for _ in ()).throw(AuditError("invalid number")))
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise AuditError("invalid JSON") from exc


def sigmoid(value: float) -> float:
    if value < 0:
        z = math.exp(value)
        return z / (1 + z)
    return 1 / (1 + math.exp(-value))


def decode_fp32_weights(arm: dict[str, Any], dim: int) -> tuple[list[float], list[float]]:
    objects = arm["weights_fp32"]
    check(type(objects) is dict and set(objects) == {"heads", "gate"}, "exact tensor inventory")
    sha = hashlib.sha256()
    decoded: dict[str, list[float]] = {}
    for name, shape in (("heads", [2, dim + 1]), ("gate", [dim + 1])):
        obj = objects[name]
        check(type(obj) is dict and set(obj) == {"shape", "data_le_hex"} and
              obj["shape"] == shape, "bad tensor schema")
        hx = obj["data_le_hex"]
        check(type(hx) is str and len(hx) == 8 * (2 * (dim + 1) if name == "heads" else dim + 1)
              and all(c in "0123456789abcdef" for c in hx), "bad tensor bytes")
        raw = bytes.fromhex(hx)
        count = len(raw) // 4
        values = list(struct.unpack(f"<{count}f", raw))
        check(all(math.isfinite(x) for x in values), "nonfinite learned tensor")
        sha.update(name.encode() + b"\0" + canonical(shape) + b"\0" + raw)
        decoded[name] = values
    check(sha.hexdigest() == arm["weights_sha256"], "learned weight digest mismatch")
    return decoded["heads"], decoded["gate"]


def predict(row: dict[str, Any], heads: list[float], gate: list[float],
            width: int, index: int, *, arm: str, split: bool) -> float:
    x = row["features"] + [1.0]
    n = width + 1
    p0 = sigmoid(sum(x[j] * heads[j] for j in range(n)))
    if not split:
        return min(1 - EPS, max(EPS, p0))
    p1 = sigmoid(sum(x[j] * heads[n + j] for j in range(n)))
    alpha = (1.0 if x[index] >= 0.0 else 0.0) if arm == "fixed_router" else (
        sigmoid(sum(x[j] * gate[j] for j in range(n))))
    return min(1 - EPS, max(EPS, p0 * (1 - alpha) + p1 * alpha))


def validate(panel: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    check(type(report) is dict and report.get("schema") == SCHEMA, "unregistered report")
    check(report.get("source_panel_sha256") == digest(panel), "source panel drift")
    check(report.get("source_kind") == panel["source"]["kind"] and
          report.get("source_scope") == panel["source"]["scope"] and
          report.get("seed") == panel["source"]["seed"], "source manifest drift")
    for k, v in {
        "shared_feature_input": True, "physically_executed_torch_fp32": True,
        "real_pretrained_encoder_executed": False,
        "independent_outcome_verified": False, "future_window_prospective": False,
        "total_compute_matched": False, "statistical_winner_certified": False,
        "ndu_selection_authorized": False, "authority_posture": "DENY_ALL",
        "production_admission": "BLOCKED",
    }.items():
        check(type(report.get(k)) is type(v) and report.get(k) == v, f"unauthorized {k}")
    check(type(report.get("pytorch_version")) is str and len(report["pytorch_version"]) < 40,
          "training library disclosure")
    steps = report.get("training_steps_each_stage")
    check(type(steps) is int and 2 <= steps <= 100, "bounded steps")
    results = report.get("results")
    check(type(results) is list and len(results) == 4 and
          [x.get("arm") for x in results if type(x) is dict] == list(ARMS), "complete paired arms")
    source = panel["partitions"]
    width = panel["source"]["dim"]
    route_index = panel["source"]["router_feature_index"]
    check(type(width) is int and 2 <= width <= 64 and type(route_index) is int
          and 0 <= route_index < width, "invalid source dimension")
    samples = sum(len(source[p]) for p in PARTS)
    for arm in results:
        name = arm["arm"]
        check(type(arm.get("split_proposed")) is bool, "split bool required")
        excess = arm.get("train_only_excess_brier")
        check(type(excess) is float and math.isfinite(excess) and -1 <= excess <= 1,
              "train-only decision disclosure")
        check(arm.get("registered_split_threshold") == 0.08 and
              type(arm.get("registered_split_threshold")) is float, "drifted prereg threshold")
        expected_split = name != "no_change" and (
            name != "adaptive_split" or excess > 0.08)
        check(arm["split_proposed"] == expected_split, "fabricated split selection")
        slots = 3 * (width + 1)
        check(arm.get("parameter_slots") == slots and
              arm.get("resident_weight_bytes_fp32") == 4 * slots,
              "matched resident parameter slots required")
        heads, router = decode_fp32_weights(arm, width)
        sealed = arm["predictions"]
        check(type(sealed) is dict and set(sealed) == set(PARTS) and
              digest(sealed) == arm["prediction_sha256"], "pre-score predictions not sealed")
        for part in PARTS:
            preds = sealed[part]
            rows = source[part]
            check(type(preds) is list and len(preds) == len(rows), "prediction coverage")
            probs = []
            for row, item in zip(rows, preds, strict=True):
                check(type(item) is dict and set(item) == {"id", "probability"} and
                      item["id"] == row["id"], "prediction row identity")
                p = item["probability"]
                check(type(p) is float and math.isfinite(p) and EPS <= p <= 1 - EPS,
                      "finite bounded probability required")
                replay = predict(row, heads, router, width, route_index,
                                 arm=name, split=arm["split_proposed"])
                check(abs(replay - p) < 3e-6, "final learned bytes do not reproduce predictions")
                probs.append(p)
            ys = [row["label"] for row in rows]
            accuracy = sum(int((p >= 0.5) == bool(y)) for p, y in zip(probs, ys, strict=True)) / len(rows)
            brier = sum((p - y)**2 for p, y in zip(probs, ys, strict=True)) / len(rows)
            nll = -sum(y * math.log(p) + (1 - y) * math.log1p(-p)
                       for p, y in zip(probs, ys, strict=True)) / len(rows)
            metric = arm["evaluation"][part]
            check(metric["count"] == len(rows) and
                  abs(metric["accuracy"] - accuracy) <= 1e-7 and
                  abs(metric["brier"] - brier) <= 1e-7 and
                  abs(metric["nll"] - nll) <= 1e-7, "scoring arithmetic altered")
        met = arm["meters"]
        n0, n1 = len(source["old_train"]), len(source["new_train"])
        factor = 2 if arm["split_proposed"] else 1
        check(met["head_forward_rows"] == steps*n0 + factor*steps*(n0+n1) + factor*samples,
              "head forward claim inconsistent with executed branch")
        check(met["router_forward_rows"] == (
            steps*(n0+n1)+samples if arm["split_proposed"] and name != "fixed_router" else 0),
            "router forward claim inconsistent")
        check(met["sample_exposures"] == steps*(2*n0+n1) and
              met["optimizer_steps"] == 2*steps, "training budget drift")
        cpu = met["train_cpu_seconds"]
        check(type(cpu) in (int, float) and math.isfinite(cpu) and cpu >= 0,
              "invalid self-reported CPU time")
    return {"outcome": "NUMERIC_REPLAY_ONLY", "arms": list(ARMS),
            "source_panel_sha256": digest(panel), "authority_posture": "DENY_ALL",
            "training_forward_provenance_independently_authenticated": False,
            "original_source_and_outcomes_authenticated": False,
            "production_selection_authorized": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    opts = parser.parse_args(argv)
    try:
        panel = load(opts.panel)
        report = load(opts.report)
        print(json.dumps(validate(panel, report), sort_keys=True))
        return 0
    except (AuditError, OSError, KeyError, TypeError, ValueError, OverflowError) as exc:
        print(f"AUDIT BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
