#!/usr/bin/env python3
"""Physical CPU *research* trial of fixed MoE vs gated Cell split.

No model provenance, real-world outcome, NDU selection, topology mutation, or
production authority. The shared Encoder is represented by precomputed features.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import stat
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = "hepta.cell-meta-router-panel.v1"
ARMS = ("no_change", "fixed_router", "learned_router", "adaptive_split")
PARTITIONS = ("old_train", "new_train", "old_retention", "future_1", "future_2", "ood")
FIT_PARTITIONS = ("old_train", "new_train")
EVAL_PARTITIONS = ("old_retention", "future_1", "future_2", "ood")
MAX_BYTES = 3 * 1024 * 1024
MAX_ROWS = 8_192
MAX_WIDTH = 64
MIN_TRAIN = 32
EPS = 1.0e-6


class InvalidPanel(ValueError):
    """The nonauthorizing research source is invalid or not cohort-paired."""


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise InvalidPanel(reason)


def canonical(value: Any) -> bytes:
    return json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def read_panel(path: Path) -> dict[str, Any]:
    """Bounded, regular, non-symlink reader; no coercive JSON extensions."""
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        start = os.fstat(fd)
        require(stat.S_ISREG(start.st_mode) and 0 < start.st_size <= MAX_BYTES,
                "expected bounded regular source")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            raw = handle.read(MAX_BYTES + 1)
        end = os.fstat(fd)
        require(len(raw) == start.st_size and (start.st_ino, start.st_dev, start.st_mtime_ns,
                start.st_size) == (end.st_ino, end.st_dev, end.st_mtime_ns, end.st_size),
                "source changed during read")
    finally:
        os.close(fd)
    try:
        panel = json.loads(raw, object_pairs_hook=_unique_keys,
                           parse_constant=lambda x: (_ for _ in ()).throw(InvalidPanel(f"invalid {x}")))
    except (ValueError, UnicodeDecodeError, OverflowError, RecursionError) as exc:
        raise InvalidPanel("malformed JSON panel") from exc
    validate(panel)
    return panel


def validate(panel: Any) -> None:
    require(type(panel) is dict and set(panel) == {"schema", "source", "partitions"},
            "panel schema fields")
    require(panel["schema"] == SCHEMA, "unregistered panel schema")
    meta = panel["source"]
    require(type(meta) is dict and set(meta) == {
        "kind", "stem_sha256", "scope", "dim", "router_feature_index", "seed", "rule"},
        "source manifest required")
    require(meta["kind"] in ("synthetic", "external_unverified") and
            type(meta["kind"]) is str, "unverified source kind")
    require(type(meta["stem_sha256"]) is str and len(meta["stem_sha256"]) == 64 and
            all(ch in "0123456789abcdef" for ch in meta["stem_sha256"]) and
            any(ch != "0" for ch in meta["stem_sha256"]), "stem digest required")
    require(type(meta["scope"]) is str and 1 <= len(meta["scope"]) <= 96 and
            meta["scope"].strip() == meta["scope"], "bounded scope required")
    dim = meta["dim"]
    require(type(dim) is int and 2 <= dim <= MAX_WIDTH, "invalid feature dimension")
    require(type(meta["router_feature_index"]) is int and
            0 <= meta["router_feature_index"] < dim, "router coordinate required")
    require(type(meta["seed"]) is int and 0 <= meta["seed"] <= 2**31 - 1,
            "explicit bounded seed required")
    require(type(meta["rule"]) is str and meta["rule"] in ("stable", "conditional", "external"),
            "declared rule required")
    require((meta["kind"] == "synthetic") == (meta["rule"] != "external"),
            "synthetic and external rule must not be confused")
    groups: set[str] = set()
    ids: set[str] = set()
    partitions = panel["partitions"]
    require(type(partitions) is dict and set(partitions) == set(PARTITIONS),
            "complete frozen partition set required")
    total = 0
    for part in PARTITIONS:
        records = partitions[part]
        require(type(records) is list and (len(records) >= MIN_TRAIN if part in FIT_PARTITIONS
                else len(records) >= 16), f"{part}: insufficient rows")
        total += len(records)
        require(total <= MAX_ROWS, "panel row capacity exceeded")
        for record in records:
            require(type(record) is dict and set(record) == {
                "id", "source_group", "step", "features", "label"}, f"{part}: row contract")
            rid = record["id"]
            group = record["source_group"]
            require(type(rid) is str and 1 <= len(rid) <= 100 and rid not in ids,
                    "duplicate/invalid row ID")
            require(type(group) is str and 1 <= len(group) <= 100 and group not in groups,
                    "source family leakage or duplicate group")
            ids.add(rid)
            groups.add(group)
            tick = record["step"]
            require(type(tick) is int and tick >= 0, "nonnegative integer step required")
            require(type(record["label"]) is int and record["label"] in (0, 1),
                    "binary source label required")
            features = record["features"]
            require(type(features) is list and len(features) == dim,
                    "exact finite vector width required")
            require(all(type(x) in (int, float) and -32 <= x <= 32 and math.isfinite(x)
                        for x in features), "non-finite/out-of-range feature")
    bounds = {p: (min(r["step"] for r in partitions[p]),
                  max(r["step"] for r in partitions[p])) for p in PARTITIONS}
    require(bounds["old_train"][1] < bounds["new_train"][0] and
            bounds["new_train"][1] < bounds["old_retention"][0] and
            bounds["old_retention"][1] < bounds["future_1"][0] and
            bounds["future_1"][1] < bounds["future_2"][0] and
            bounds["future_2"][1] < bounds["ood"][0],
            "chronological train/holdout disjointness required")


def synthetic_panel(*, seed: int, rule: str, rows: int = 96) -> dict[str, Any]:
    """Declared toy panel only. Never a legitimate natural/longitudinal outcome."""
    import random

    require(rule in ("stable", "conditional") and 32 <= rows <= 256,
            "bounded fixture declaration")
    rng = random.Random(seed)
    parts: dict[str, list[dict[str, Any]]] = {}
    for slot, name in enumerate(PARTITIONS):
        cohort: list[dict[str, Any]] = []
        for i in range(rows):
            a, b, d = (rng.gauss(0, 1) for _ in range(3))
            context = 1.0 if (name == "old_train" or name == "old_retention" or i % 2 == 0) else -1.0
            if name == "ood":
                a += 1.5
                b -= 1.0
            score = (a if rule == "stable" or context > 0 else -a) + 0.35 * b
            cohort.append({
                "id": f"{name}-{i:04}", "source_group": f"toy-{seed}-{slot}-{i}",
                "step": slot * 10_000 + i, "features": [a, b, d, context],
                "label": int(score >= 0.0),
            })
        parts[name] = cohort
    panel = {"schema": SCHEMA, "source": {
        "kind": "synthetic", "stem_sha256": hashlib.sha256(b"synthetic-no-encoder").hexdigest(),
        "scope": f"research-toy-{rule}", "dim": 4, "router_feature_index": 3,
        "seed": seed, "rule": rule}, "partitions": parts}
    validate(panel)
    return panel


@dataclass
class Counter:
    head_rows: int = 0
    router_rows: int = 0
    optimizer_updates: int = 0
    input_rows_trained: int = 0


class TwoHeadBank:
    """Tiny real Torch FP32 bank with exact parent-copy split parity."""

    def __init__(self, width: int, feature_index: int, *, seed: int):
        import torch

        torch.manual_seed(seed)
        self.torch = torch
        self.width = width
        self.feature_index = feature_index
        self.weights = torch.nn.Parameter(torch.zeros((2, width + 1), dtype=torch.float32))
        self.gate = torch.nn.Parameter(torch.zeros((width + 1,), dtype=torch.float32))
        self.counter = Counter()
        self.split = False
        self.mode = "no_change"

    def _extend(self, x: Any) -> Any:
        return self.torch.cat((x, self.torch.ones((x.shape[0], 1))), dim=1)

    def forward(self, x: Any, *, count: bool = True) -> Any:
        torch = self.torch
        b = self._extend(x)
        p0 = torch.sigmoid(b @ self.weights[0])
        if count:
            self.counter.head_rows += len(x)
        if not self.split:
            return p0.clamp(EPS, 1 - EPS)
        p1 = torch.sigmoid(b @ self.weights[1])
        if count:
            self.counter.head_rows += len(x)
        if self.mode == "fixed_router":
            alpha = (x[:, self.feature_index] >= 0).to(torch.float32)
        else:
            alpha = torch.sigmoid(b @ self.gate)
            if count:
                self.counter.router_rows += len(x)
        return (p0 * (1 - alpha) + p1 * alpha).clamp(EPS, 1 - EPS)

    def specialize(self, mode: str, sample: Any) -> bool:
        require(mode in ARMS and mode != "no_change", "invalid specialization arm")
        with self.torch.no_grad():
            before = self.forward(sample, count=False).detach().clone()
            self.weights[1].copy_(self.weights[0])
            self.gate.zero_()
            # A fixed, predeclared initial routing preference (not a fitted label).
            self.gate[self.feature_index] = 1.0
            self.split = True
            self.mode = mode
            after = self.forward(sample, count=False).detach()
            require(bool(self.torch.allclose(before, after, atol=1e-7, rtol=0)),
                    "split fails parent-output parity")
        return True

    def weight_blobs(self) -> dict[str, dict[str, Any]]:
        """Small, complete, auditable learned FP32 bytes, never model-origin proof."""
        return {name: {"shape": list(weight.shape),
                       "data_le_hex": weight.detach().cpu().contiguous().numpy()
                       .astype("<f4", copy=False).tobytes().hex()}
                for name, weight in (("heads", self.weights), ("gate", self.gate))}

    def weight_sha(self) -> str:
        h = hashlib.sha256()
        for name, weight in (("heads", self.weights), ("gate", self.gate)):
            payload = weight.detach().cpu().contiguous().numpy().astype("<f4", copy=False)
            h.update(name.encode("ascii") + b"\0")
            h.update(canonical(list(payload.shape)) + b"\0")
            h.update(payload.tobytes())
        return h.hexdigest()


def vectors(panel: dict[str, Any], name: str, *, include_labels: bool = True) -> tuple[Any, Any]:
    import torch

    rows = panel["partitions"][name]
    x = torch.tensor([r["features"] for r in rows], dtype=torch.float32)
    y = (torch.tensor([r["label"] for r in rows], dtype=torch.float32)
         if include_labels else None)
    return x, y


def train_arm(panel: dict[str, Any], mode: str, *, steps: int = 24) -> dict[str, Any]:
    """Fit only old/new train. Predict eval BEFORE consulting eval labels."""
    import torch

    require(mode in ARMS and type(steps) is int and 2 <= steps <= 100, "registered arm/step ceiling")
    torch.set_num_threads(1)
    x0, y0 = vectors(panel, "old_train")
    x1, y1 = vectors(panel, "new_train")
    x_all, y_all = torch.cat((x0, x1), 0), torch.cat((y0, y1), 0)
    meta = panel["source"]
    bank = TwoHeadBank(meta["dim"], meta["router_feature_index"], seed=meta["seed"])
    optimizer = torch.optim.SGD((bank.weights, bank.gate), lr=0.6)
    start = time.process_time()
    for _ in range(steps):
        optimizer.zero_grad(set_to_none=True)
        probability = bank.forward(x0)
        loss = torch.nn.functional.binary_cross_entropy(probability, y0)
        require(bool(torch.isfinite(loss)), "nonfinite old training loss")
        loss.backward()
        optimizer.step()
        bank.counter.optimizer_updates += 1
        bank.counter.input_rows_trained += len(x0)
    with torch.no_grad():
        old_brier = float(((bank.forward(x0, count=False) - y0) ** 2).mean())
        new_brier = float(((bank.forward(x1, count=False) - y1) ** 2).mean())
    # This threshold is preregistered and deliberately does NOT look at holdout labels.
    excess_brier = new_brier - old_brier
    triggered = mode != "no_change" and (mode != "adaptive_split" or excess_brier > 0.08)
    if triggered:
        bank.specialize("fixed_router" if mode == "fixed_router" else "learned_router", x0)
    for _ in range(steps):
        optimizer.zero_grad(set_to_none=True)
        p = bank.forward(x_all)
        loss = torch.nn.functional.binary_cross_entropy(p, y_all)
        require(bool(torch.isfinite(loss)), "nonfinite joint training loss")
        loss.backward()
        optimizer.step()
        bank.counter.optimizer_updates += 1
        bank.counter.input_rows_trained += len(x_all)
    cpu_seconds = time.process_time() - start
    # Freeze the model weights. Prediction probabilities are sealed BEFORE scoring.
    weights_sha = bank.weight_sha()
    blobs = bank.weight_blobs()
    predictions: dict[str, list[dict[str, Any]]] = {}
    with torch.no_grad():
        for part in EVAL_PARTITIONS:
            x, _ = vectors(panel, part, include_labels=False)  # evaluation labels stay unopened
            ps = bank.forward(x).detach().tolist()
            require(all(math.isfinite(p) for p in ps), "nonfinite prediction")
            predictions[part] = [
                {"id": record["id"], "probability": round(float(p), 9)}
                for record, p in zip(panel["partitions"][part], ps, strict=True)
            ]
    seal = digest(predictions)
    return {
        "arm": mode, "weights_sha256": weights_sha, "weights_fp32": blobs,
        "prediction_sha256": seal, "predictions": predictions,
        "split_proposed": triggered, "train_only_excess_brier": round(excess_brier, 9),
        "registered_split_threshold": 0.08,
        "parameter_slots": int(bank.weights.numel() + bank.gate.numel()),
        "resident_weight_bytes_fp32": 4 * int(bank.weights.numel() + bank.gate.numel()),
        "meters": {"head_forward_rows": bank.counter.head_rows,
                   "router_forward_rows": bank.counter.router_rows,
                   "optimizer_steps": bank.counter.optimizer_updates,
                   "sample_exposures": bank.counter.input_rows_trained,
                   "train_cpu_seconds": round(cpu_seconds, 6)},
    }


def score_sealed(panel: dict[str, Any], fitted: dict[str, Any]) -> dict[str, Any]:
    """Read labels *only after* the paired pre-score prediction seal exists."""
    require(digest(fitted["predictions"]) == fitted["prediction_sha256"],
            "tampered pre-score prediction seal")
    summary: dict[str, Any] = {}
    for part in EVAL_PARTITIONS:
        rows = panel["partitions"][part]
        paired = fitted["predictions"][part]
        require(len(rows) == len(paired) and all(x["id"] == r["id"]
                for x, r in zip(paired, rows, strict=True)), "prediction/source case drift")
        p = [entry["probability"] for entry in paired]
        require(all(type(x) is float and EPS <= x <= 1 - EPS for x in p),
                "invalid postseal prediction")
        y = [r["label"] for r in rows]
        acc = sum(int((v >= 0.5) == bool(label)) for v, label in zip(p, y, strict=True)) / len(y)
        brier = sum((v - label) ** 2 for v, label in zip(p, y, strict=True)) / len(y)
        nll = -sum(label * math.log(v) + (1 - label) * math.log1p(-v)
                   for v, label in zip(p, y, strict=True)) / len(y)
        summary[part] = {"count": len(rows), "accuracy": round(acc, 7),
                         "brier": round(brier, 7), "nll": round(nll, 7)}
    return summary


def run(panel: dict[str, Any], *, steps: int = 24) -> dict[str, Any]:
    validate(panel)
    results = []
    for arm in ARMS:
        fitted = train_arm(panel, arm, steps=steps)
        summary = score_sealed(panel, fitted)
        # Never claim prospective independent future evidence from synthetic holdouts.
        results.append(fitted | {"evaluation": summary})
    return {
        "schema": "hepta.cell-meta-physical-router-trial.v1",
        "source_panel_sha256": digest(panel), "source_kind": panel["source"]["kind"],
        "source_scope": panel["source"]["scope"], "seed": panel["source"]["seed"],
        "training_steps_each_stage": steps,
        "shared_feature_input": True,
        "physically_executed_torch_fp32": True,
        "pytorch_version": str(__import__("torch").__version__),
        "real_pretrained_encoder_executed": False,
        "independent_outcome_verified": False,
        "future_window_prospective": False,
        "total_compute_matched": False,
        "statistical_winner_certified": False,
        "ndu_selection_authorized": False,
        "production_admission": "BLOCKED", "authority_posture": "DENY_ALL",
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--input", type=Path)
    choice.add_argument("--synthetic-rule", choices=("stable", "conditional"))
    parser.add_argument("--seed", type=int, default=41)
    parser.add_argument("--steps", type=int, default=24)
    parser.add_argument("--out", required=True, type=Path)
    opts = parser.parse_args(argv)
    try:
        panel = read_panel(opts.input) if opts.input else synthetic_panel(seed=opts.seed,
                                                                          rule=opts.synthetic_rule)
        result = run(panel, steps=opts.steps)
        payload = canonical(result) + b"\n"
        require(len(payload) <= MAX_BYTES, "report too large")
        # Create-only, never replace evidence or follow symlinks.
        out_fd = os.open(opts.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(out_fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        print(json.dumps({"research_report": str(opts.out), "sha256": hashlib.sha256(payload).hexdigest(),
                          "production_admission": "BLOCKED"}))
        return 0
    except (InvalidPanel, OSError, ValueError, RuntimeError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
