#!/usr/bin/env python3
"""Pinned AG News -> real Granite Q24 features -> **retrospective** Router panel.

Research-only. The CPU producer invokes the separately pinned FrozenCompactStem;
conversion never interprets retrospective rows as observed future-time episodes.
No model origin signer, NDU selector or production Cell Split authority is issued.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
import subprocess
from pathlib import Path
import stat
import sys
import time

MODEL_ID = "ibm-granite/granite-embedding-97m-multilingual-r2"
MODEL_ADAPTER_ID = "granite-97m-multilingual-r2"
MODEL_REVISION = "835ad14087e140460703cf0fae09f97d469d65c2"
REVIEWED_ENCODER_SOURCE = "e05f939f65fb76f6bdbf7470eef7e63b77284dcd"
SOURCE_PANEL_SHA = "2f7a013648e16b60c74614b0fcf1496aa06475f7285f215adddaa51fe29e01a4"
SOURCE_DATASET = "szhuggingface/ag_news"
SOURCE_DATASET_COMMIT = "98c532231d96ae10e176a909192ecac548949288"
SOURCE_BYTES = {
    "train": "cc35afe9d5e7ff01878c9aeba08bb0bdfa16947702789530b216a580a1bc09d5",
    "calibration_test": "3171d3aeee227372165bb0f9e84ebf2bfaf5fc870d034f33a5fc568e7995c672",
}
PANEL_SCHEMA = "hepta.stem.agnews-binary-capability-panel.v1"
TABLE_SCHEMA = "hepta.cell-meta-granite-q24-rows.v1"
TRIAL_SCHEMA = "hepta.cell-meta-router-panel.v1"
PROJECTION = "contiguous-six-q24-mean64-v1"
Q24 = 1 << 24
FEATURE_WIDTH = 384
TRIAL_WIDTH = 64
ROWS = {"train": 128, "calibration": 32, "test": 64}
MAX_FILE_BYTES = 4 * 1024 * 1024
SEEDS = (41, 47, 53)

class BridgeError(ValueError):
    """An input, source binding or physical Encoder observation is not admissible."""


def check(condition: bool, description: str) -> None:
    if not condition:
        raise BridgeError(description)


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha_object(value: object) -> str:
    return sha(canonical(value))


def unique(pairs: list[tuple[str, object]]) -> dict:
    out = {}
    for key, value in pairs:
        check(key not in out, "duplicate JSON member")
        out[key] = value
    return out


def read_json(path: Path) -> dict:
    # Open first, reject FIFOs/symlinks, and compare complete file metadata after read.
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                 | getattr(os, "O_NONBLOCK", 0))
    try:
        before = os.fstat(fd)
        check(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= MAX_FILE_BYTES,
              "bounded regular input required")
        raw = os.read(fd, MAX_FILE_BYTES + 1)
        after = os.fstat(fd)
        check(len(raw) == before.st_size and
              (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
              (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
              "source changed while reading")
    finally:
        os.close(fd)
    try:
        data = json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(BridgeError("nonfinite")))
    except (ValueError, UnicodeError, RecursionError, OverflowError) as exc:
        raise BridgeError("invalid JSON") from exc
    check(type(data) is dict, "top-level object required")
    return data


def create_json(path: Path, obj: dict) -> None:
    raw = canonical(obj) + b"\n"
    check(len(raw) <= MAX_FILE_BYTES, "output too large")
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as file:
        file.write(raw)
        file.flush()
        os.fsync(file.fileno())


def verify_panel(source: dict, *, registered_sha: str | None = None) -> list[dict]:
    if registered_sha is None:
        registered_sha = SOURCE_PANEL_SHA
    check(sha_object(source) == registered_sha, "pinned 224-case source manifest drift")
    check(source.get("schema") == PANEL_SCHEMA and
          source.get("dataset") == SOURCE_DATASET and
          source.get("dataset_commit_prefix") == SOURCE_DATASET_COMMIT[:7] and
          source.get("dataset_file_sha256") == SOURCE_BYTES and
          source.get("label_mapping") == {"world": 0, "sports": 1} and
          source.get("case_count") == 224 and
          source.get("cross_sectional_not_future") is True and
          source.get("production_promotion") == "DENY_ALL",
          "source policy or original data identity mismatch")
    cases = source.get("cases")
    check(type(cases) is list and len(cases) == 224, "exact source rows required")
    seen: set[str] = set()
    quota = Counter()
    for row in cases:
        check(type(row) is dict and row.get("split") in ROWS and
              type(row.get("label")) is int and row["label"] in (0, 1),
              "source row/split/label invalid")
        joint = row.get("joint_input")
        check(type(joint) is dict and set(joint) == {"state", "question", "options"} and
              joint["options"] == ["world", "sports"] and
              joint["question"] == "Which category does the news report describe?" and
              type(joint["state"]) is str and 1 <= len(joint["state"].encode("utf8")) <= 8192,
              "registered joint task changed")
        source_digest = sha(joint["state"].encode("utf8"))
        check(row.get("source_digest") == source_digest and
              row.get("group_id") == source_digest and
              row.get("case_id") == source_digest[:24] and
              row.get("joint_input_digest") == sha_object(joint) and
              row.get("label_name") == ("world", "sports")[row["label"]] and
              source_digest not in seen, "case/source/group binding drift")
        seen.add(source_digest)
        quota[(row["split"], row["label"])] += 1
    check(all(quota[(part, label)] == count // 2
              for part, count in ROWS.items() for label in (0, 1)), "source class quota")
    return cases


def feature_hash(case_id: str, source_digest: str, values: list[int]) -> str:
    return sha_object({"case_id": case_id, "source_digest": source_digest,
                       "feature_q24": values})


def table_row(case: dict, values: list[float], tokens: int) -> dict:
    check(len(values) == FEATURE_WIDTH and
          all(type(v) in (int, float) and math.isfinite(v) and -1.01 <= v <= 1.01
              for v in values), "real Encoder vector must be finite normalized 384D")
    check(type(tokens) is int and 1 <= tokens <= 512, "silent truncation or missing tokens")
    q = [int(round(v * Q24)) for v in values]
    check(any(v != 0 for v in q) and all(abs(v) <= Q24 for v in q) and
          .998 <= sum(v*v for v in q) / (Q24*Q24) <= 1.002,
          "invalid or non-unit quantized Encoder feature")
    return {"case_id": case["case_id"], "source_digest": case["source_digest"],
            "joint_input_digest": case["joint_input_digest"],
            "feature_q24": q, "original_tokens": tokens,
            "feature_sha256": feature_hash(case["case_id"], case["source_digest"], q)}


def encoder_table(source: dict, backend: object, *, snapshot_sha: str) -> dict:
    """Actual caller must supply reviewed FrozenCompactStem, never a mock CLI mode."""
    cases = verify_panel(source)
    check(type(snapshot_sha) is str and len(snapshot_sha) == 64 and
          set(snapshot_sha) <= set("0123456789abcdef") and int(snapshot_sha, 16) > 0,
          "missing immutable local model-file inventory")
    rows = []
    started = time.perf_counter()
    for case in cases:
        vec, _proof, meta = backend.encode(case["joint_input"], allow_truncation=False)
        check(meta["truncated"] is False, "physical token truncation")
        values = vec.detach().cpu().reshape(-1).tolist()
        rows.append(table_row(case, values, meta["original_tokens"]))
    return {"schema": TABLE_SCHEMA, "dataset_panel_sha256": SOURCE_PANEL_SHA,
            "model_id": MODEL_ID, "model_revision": MODEL_REVISION,
            "encoder_source_sha": REVIEWED_ENCODER_SOURCE,
            "snapshot_files_sha256": snapshot_sha,
            "pooling": "cls_l2_q24", "dim": FEATURE_WIDTH,
            "reported_physical_model_requests": len(rows),
            "observed_encoder_elapsed_seconds": round(time.perf_counter() - started, 5),
            "independent_model_origin_verified": False,
            "production_admission": "BLOCKED", "rows": rows}


def validate_table(table: dict, source_cases: list[dict]) -> list[dict]:
    check(type(table) is dict and set(table) == {
        "schema", "dataset_panel_sha256", "model_id", "model_revision", "encoder_source_sha",
        "snapshot_files_sha256", "pooling", "dim", "reported_physical_model_requests",
        "observed_encoder_elapsed_seconds", "independent_model_origin_verified",
        "production_admission", "rows"}, "feature-table exact fields")
    check(table["schema"] == TABLE_SCHEMA and
          table["dataset_panel_sha256"] == SOURCE_PANEL_SHA and
          table["model_id"] == MODEL_ID and table["model_revision"] == MODEL_REVISION and
          table["encoder_source_sha"] == REVIEWED_ENCODER_SOURCE and
          table["pooling"] == "cls_l2_q24" and table["dim"] == FEATURE_WIDTH and
          table["reported_physical_model_requests"] == 224 and
          type(table["independent_model_origin_verified"]) is bool and
          table["independent_model_origin_verified"] is False and
          table["production_admission"] == "BLOCKED", "real feature-table claim mismatch")
    s = table["snapshot_files_sha256"]
    check(type(s) is str and len(s) == 64 and set(s) <= set("0123456789abcdef") and
          any(v != "0" for v in s), "model snapshot inventory digest")
    elapsed = table["observed_encoder_elapsed_seconds"]
    check(type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0,
          "physical CPU claim must be finite")
    entries = table["rows"]
    check(type(entries) is list and len(entries) == 224, "unmatched physical row count")
    for case, entry in zip(source_cases, entries, strict=True):
        check(type(entry) is dict and set(entry) == {
            "case_id", "source_digest", "joint_input_digest", "feature_q24", "original_tokens",
            "feature_sha256"}, "complete per-case Encoder feature")
        check(entry["case_id"] == case["case_id"] and
              entry["source_digest"] == case["source_digest"] and
              entry["joint_input_digest"] == case["joint_input_digest"],
              "feature/source/case order mismatch")
        values = entry["feature_q24"]
        check(type(values) is list and len(values) == FEATURE_WIDTH and
              all(type(v) is int and abs(v) <= Q24 for v in values) and
              any(v != 0 for v in values) and
              .998 <= sum(v*v for v in values) / (Q24*Q24) <= 1.002,
              "invalid/non-unit Q24 feature row")
        check(feature_hash(entry["case_id"], entry["source_digest"], values) ==
              entry["feature_sha256"], "feature digest mismatch")
        check(type(entry["original_tokens"]) is int and
              1 <= entry["original_tokens"] <= 512, "model tokens missing or truncated")
    return entries


def slots(cases: list[dict]) -> dict[str, list[dict]]:
    by_split = {k: [row for row in cases if row["split"] == k] for k in ROWS}
    # Original public source order is sealed by the exact registered panel hash.
    check([len(by_split[k]) for k in ROWS] == [128, 32, 64], "source partition drift")
    return {
        "old_train": by_split["train"][:64], "new_train": by_split["train"][64:],
        "old_retention": by_split["calibration"][:16],
        "future_1": by_split["test"][:32], "future_2": by_split["test"][32:],
        "ood": by_split["calibration"][16:],
    }


def project(q24: list[int]) -> list[float]:
    # Fixed, label-free 384->64 projection; NOT lossless or measured OOD-preserving.
    check(type(q24) is list and len(q24) == FEATURE_WIDTH, "source Encoder width drift")
    return [sum(q24[6*i:6*i+6]) / (6 * Q24) for i in range(TRIAL_WIDTH)]


def convert(source: dict, table: dict, *, seed: int) -> tuple[dict, dict]:
    check(type(seed) is int and seed in SEEDS, "preregistered seed only")
    cases = verify_panel(source)
    entries = validate_table(table, cases)
    table_by_id = {entry["case_id"]: entry for entry in entries}
    converted = {}
    for slot, (name, case_rows) in enumerate(slots(cases).items()):
        converted[name] = []
        for index, case in enumerate(case_rows):
            item = table_by_id[case["case_id"]]
            converted[name].append({
                "id": case["case_id"], "source_group": case["source_digest"],
                "step": slot * 10_000 + index, "features": project(item["feature_q24"]),
                "label": case["label"],
            })
    manifest = {"model_id": MODEL_ID, "model_revision": MODEL_REVISION,
                "snapshot_files_sha256": table["snapshot_files_sha256"],
                "pooling": "cls_l2_q24", "projection": PROJECTION}
    panel = {"schema": TRIAL_SCHEMA, "source": {
        "kind": "external_unverified", "stem_sha256": sha_object(manifest),
        "scope": "public-agnews-retrospective-granite97m", "dim": TRIAL_WIDTH,
        "router_feature_index": 0, "seed": seed, "rule": "external",
    }, "partitions": converted}
    receipt = {"schema": "hepta.cell-meta-granite-retrospective-bind.v1",
               "source_panel_sha256": SOURCE_PANEL_SHA,
               "real_encoder_feature_table_sha256": sha_object(table),
               "meta_trial_panel_sha256": sha_object(panel),
               "projection": PROJECTION, "actual_encoder_calls_self_reported": 224,
               "source_cases": 224, "panel_seed": seed,
               "artificial_step_order_not_observation_time": True,
               "future_1_2_are_retrospective_test_slices": True,
               "ood_is_calibration_samesource_placeholder": True,
               "real_ood_verified": False, "future_window_prospective": False,
               "independent_model_origin_verified": False,
               "independent_scientific_outcomes_verified": False,
               "production_admission": "BLOCKED", "authority_posture": "DENY_ALL"}
    return panel, receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    e = sub.add_parser("encode", help="Real pinned offline Granite Encoder execution only")
    e.add_argument("--source-panel", required=True, type=Path)
    e.add_argument("--compact-checkout", required=True, type=Path)
    e.add_argument("--snapshot-files-sha256", required=True)
    e.add_argument("--out", required=True, type=Path)
    p = sub.add_parser("convert", help="Offline, stdlib-only 224-row to paired Router panel")
    p.add_argument("--source-panel", required=True, type=Path)
    p.add_argument("--features", required=True, type=Path)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        source = read_json(args.source_panel)
        verify_panel(source)
        if args.command == "encode":
            compact = args.compact_checkout.resolve(strict=True)
            observed = subprocess.check_output(["git", "-C", str(compact), "rev-parse", "HEAD"],
                                               text=True, timeout=5).strip()
            check(observed == REVIEWED_ENCODER_SOURCE,
                  "frozen compact Encoder source checkout changed")
            lib = compact / "qualification" / "neuron-stem"
            check(lib.is_dir(), "reviewed FrozenCompactStem path missing")
            sys.path.insert(0, str(lib))
            from compact_stem_trial import FrozenCompactStem
            import torch
            torch.set_num_threads(2)
            stem = FrozenCompactStem(MODEL_ADAPTER_ID, MODEL_REVISION, device="cpu", max_tokens=512)
            table = encoder_table(source, stem, snapshot_sha=args.snapshot_files_sha256)
            create_json(args.out, table)
            print(json.dumps({"rows": len(table["rows"]), "real_local_encoder_claimed": True,
                              "model_origin_authenticated": False, "production_admission": "BLOCKED"}))
        else:
            table = read_json(args.features)
            panel, receipt = convert(source, table, seed=args.seed)
            # Import the existing trial contract: conversion must not weaken it.
            from qualification.cell_meta_execution_af.physical_router_trial import validate
            validate(panel)
            check(not args.out.exists() and not args.receipt.exists(), "create-only outputs")
            create_json(args.out, panel)
            create_json(args.receipt, receipt)
            print(json.dumps({"panel_sha256": receipt["meta_trial_panel_sha256"],
                              "production_admission": "BLOCKED"}))
        return 0
    except (BridgeError, OSError, ValueError, RuntimeError, KeyError, TypeError,
            subprocess.SubprocessError) as exc:
        print(f"RESEARCH BLOCKED: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
