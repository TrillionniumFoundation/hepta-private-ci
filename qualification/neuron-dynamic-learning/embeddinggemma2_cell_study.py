"""Offline real-weight Stem -> existing dynamic Cell Head learning study.

This module consumes externally labelled, source-bound time windows and frozen
no-change predictions; it does not synthesize labels, outcomes or future rows.
Even a favorable result is observational, unsigned, and DENY_ALL for promotion.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import time

import numpy as np

from cell_learning import budgeted_cell, paired_future_score, rust_candidate_digest
from embeddinggemma2_shadow import (
    FrozenGemmaShadow, QualificationError, canonical_bytes, is_sha, sha256,
)

SPLITS = ("train", "calibration", "test", "future1", "future2", "future3")
MAX_ROWS = 1024
MAX_BATCH = 32
Q24 = 1 << 24


def _utc(instant: str) -> datetime:
    if not isinstance(instant, str):
        raise QualificationError("time is not an ISO8601 UTC source event")
    try:
        parsed = datetime.fromisoformat(instant.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
            raise ValueError("not UTC")
        return parsed.astimezone(timezone.utc)
    except ValueError as exc:
        raise QualificationError("non-UTC or invalid event timestamp") from exc


def validate_study(study: dict) -> dict:
    """Check strict cohort identity, time ordering and independent baseline input.

    External source/outcome signatures remain the original learning owner job.
    """
    if (not isinstance(study, dict) or set(study) != {
        "schema", "scope_id", "principal_id", "purpose_id", "source_manifest_digest",
        "baseline_model_digest", "cases",
    } or study["schema"] != "hepta.gemma2.binary-cell-study.v1"):
        raise QualificationError("unknown study protocol")
    if not is_sha(study["source_manifest_digest"], 64) or not is_sha(study["baseline_model_digest"], 64):
        raise QualificationError("source or real no-change model identity unbound")
    cases = study["cases"]
    if not isinstance(cases, list) or not 48 <= len(cases) <= MAX_ROWS:
        raise QualificationError("study requires 6 genuinely distinct cohort windows")
    cohorts = {name: [] for name in SPLITS}
    ids, seen_group, seen_source = set(), {}, {}
    owner = tuple(study[k] for k in ("scope_id", "principal_id", "purpose_id"))
    for case in cases:
        if not isinstance(case, dict) or set(case) != {
            "case_id", "group_id", "observed_utc", "split", "label",
            "production_probability", "request",
        }:
            raise QualificationError("unknown case fields")
        cid, group, split = case["case_id"], case["group_id"], case["split"]
        if (not isinstance(cid, str) or not 1 <= len(cid) <= 128 or cid in ids
                or not isinstance(group, str) or not group or len(group) > 128
                or split not in SPLITS):
            raise QualificationError("duplicated or malformed case identity")
        ids.add(cid)
        observed = _utc(case["observed_utc"])
        if type(case["label"]) is not int or case["label"] not in (0, 1):
            raise QualificationError("observed binary task outcome required")
        prob = case["production_probability"]
        if type(prob) not in (int, float) or not math.isfinite(prob) or not 0 < prob < 1:
            raise QualificationError("actual frozen production baseline probability required")
        r = case["request"]
        if not isinstance(r, dict) or set(r) != {
            "scope_id", "principal_id", "purpose_id", "cell_id", "generation",
            "authority_epoch", "input",
        }:
            raise QualificationError("invalid cell request")
        if tuple(r.get(k) for k in ("scope_id", "principal_id", "purpose_id")) != owner:
            raise QualificationError("cross-scope study forbidden")
        if type(r["generation"]) is not int or type(r["authority_epoch"]) is not int or r["generation"] < 1 or r["authority_epoch"] < 1:
            raise QualificationError("unbound generation or epoch")
        inp = r["input"]
        if not isinstance(inp, dict) or set(inp) != {"modality", "role", "value", "sha256"}:
            raise QualificationError("text input or proof missing")
        if inp["modality"] != "text" or inp["role"] != "classification":
            raise QualificationError("study requires matched text classification representations")
        raw = inp["value"]
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise QualificationError("task must contain complete typed joint input") from exc
        if (not isinstance(parsed, dict) or set(parsed) != {"question", "options", "state"}
                or not isinstance(parsed["question"], str) or not parsed["question"]
                or not isinstance(parsed["state"], str)
                or not isinstance(parsed["options"], list) or not 1 <= len(parsed["options"]) <= 32
                or any(not isinstance(o, str) or not o for o in parsed["options"])
                or canonical_bytes(parsed).decode("utf-8") != raw):
            raise QualificationError("partial, ambiguous or noncanonical question/options/state")
        if not is_sha(inp["sha256"], 64) or sha256(raw.encode("utf-8")) != inp["sha256"]:
            raise QualificationError("wrong source digest")
        for value, mapping in ((group, seen_group), (inp["sha256"], seen_source)):
            if mapping.setdefault(value, split) != split:
                raise QualificationError("source groups or exact input bytes crossed holdout windows")
        cohorts[split].append((case, observed))
    for split in SPLITS:
        if len(cohorts[split]) < 8 or len({c["group_id"] for c, _ in cohorts[split]}) < 2:
            raise QualificationError("minimum independent examples/groups per window absent")
    for earlier, later in zip(SPLITS, SPLITS[1:]):
        if max(t for _, t in cohorts[earlier]) >= min(t for _, t in cohorts[later]):
            raise QualificationError("future holdout or calibration chronology breached")
    return {"cohorts": cohorts, "groups": len(seen_group), "rows": len(cases),
            "dataset_digest": sha256(canonical_bytes(study))}


def run_study(runner: FrozenGemmaShadow, study: dict, *, head_budget: int = 2048,
              steps: int = 40, lr: float = 0.15, seed: int = 17) -> dict:
    check = validate_study(study)
    if not getattr(runner, "_verified_local_weights", False):
        raise QualificationError("real locally checked pretrained weights required")
    if (runner.manifest["dimension"] != 256 or runner.manifest["profile"] not in ("text", "all", "vision", "audio")
            or head_budget not in (2048, 8192, 16384)
            or type(steps) is not int or not 1 <= steps <= 1000
            or type(seed) is not int or not 0 <= seed < 2**32
            or type(lr) is not float or not 0 < lr <= 1):
        raise QualificationError("unregistered model, feature, training or budget profile")
    start = time.perf_counter_ns()
    slices = {}
    api_calls = 0
    for split in SPLITS:
        records = [c for c, _ in check["cohorts"][split]]
        vectors = []
        # Isolation-safe microbatches; never claim one forward over all
        # different questions/choices, even when the shared weights are resident.
        for offset in range(0, len(records), MAX_BATCH):
            chunk = records[offset:offset + MAX_BATCH]
            batch = []
            for i, case in enumerate(chunk):
                request = case["request"]
                batch.append({**request, "cell_id": f"shadow.study.{i:03d}"})
            block = runner.encode_cells(batch)
            if not block["physical_local_model_execution"] or block["evidence_type"] != "local_weight_execution_unverified_origin":
                raise QualificationError("unsigned numeric stub substituted for pretrained features")
            api_calls += block["sentence_transformer_encode_calls"]
            vectors.extend(item["features_q24"] for item in block["rows"])
        if any(not isinstance(x, list) or len(x) != 256 for x in vectors):
            raise QualificationError("missing complete Q24 Stem output")
        x = np.asarray(vectors, dtype=np.float64) / Q24
        y = np.asarray([c["label"] for c in records], dtype=np.float64)
        baseline = np.asarray([c["production_probability"] for c in records], dtype=np.float64)
        slices[split] = (x, y, baseline)
    train_x, train_y, _ = slices["train"]
    if len(set(train_y.tolist())) != 2:
        raise QualificationError("train split missing both label classes")
    cell = budgeted_cell("shadow.stem.binary", runner.profile_digest, 256, head_budget, seed)
    frozen = cell.clone_frozen()
    start_learning = time.perf_counter_ns()
    for _ in range(steps):
        cell.learn(train_x, train_y, lr)
    head_train_nanos = time.perf_counter_ns() - start_learning
    metrics = {}
    for split in SPLITS[1:]:
        x, y, baseline = slices[split]
        metrics[split] = paired_future_score(cell, frozen, x, y, baseline)
    return {
        "schema": "hepta.embeddinggemma2.cell-study.shadow.v1",
        "evidence_type": "real_local_model_features_and_numpy_head_unsigned",
        "model_revision": runner.manifest["revision"],
        "stem_digest": runner.profile_digest,
        "study_digest": check["dataset_digest"],
        "source_manifest_digest": study["source_manifest_digest"],
        "baseline_model_digest": study["baseline_model_digest"],
        "train_groups": len({c["group_id"] for c, _ in check["cohorts"]["train"]}),
        "future_windows": 3,
        "future_groups_independently_authenticated": False,
        "no_change_predictions_independently_authenticated": False,
        "trainable_head_parameters": cell.parameter_count(),
        "head_candidate_digest": rust_candidate_digest(cell.export_q24()),
        "matched_head_optimizer_steps": steps,
        "head_train_nanos": head_train_nanos,
        "model_encode_api_calls": api_calls,
        "physical_transformer_forward_calls": None,
        "wall_excluding_model_initialization_nanos": time.perf_counter_ns() - start,
        "held_out": metrics,
        "source_tensor_mutated": False,
        "selected_artifact_mutation": False,
        "production_promotion": "DENY_ALL",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--head-budget", type=int, choices=(2048, 8192, 16384), default=2048)
    parser.add_argument("--steps", type=int, default=40)
    a = parser.parse_args()
    dataset = json.loads(a.cases.read_text(encoding="utf-8"))
    result = run_study(FrozenGemmaShadow(a.manifest, device=a.device), dataset,
                       head_budget=a.head_budget, steps=a.steps)
    print(json.dumps(result, sort_keys=True))
