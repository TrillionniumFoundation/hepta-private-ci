#!/usr/bin/env python3
"""Offline, shadow-only Hepta Neuron model comparison. Never selects an artifact."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path

SCHEMA = "hepta.neuron.model-trial.v1"
SPLITS = ("train", "calibration", "holdout", "future_1", "future_2")
EVAL_SPLITS = SPLITS[2:]
ARMS = {
    "decisions": ("laya", "typed"),
    "multilingual": ("laya", "multilingual"),
    "heads": ("linear", "mlp", "swiglu"),
}
MODEL_IDS = {
    "laya": "convaiinnovations/laya",
    "typed": "convaiinnovations/laya-typed-decisions",
    "multilingual": "convaiinnovations/laya-multilingual",
}
Q24 = 1 << 24


class InvalidTrial(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise InvalidTrial(message)


def is_sha(value, length=64):
    return (isinstance(value, str) and len(value) == length and
            any(c != "0" for c in value) and all(c in "0123456789abcdef" for c in value))


def sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sha_tree(root, only_python=False):
    """Bind tokenizer, config, head and encoder files; reject escaping links."""
    root = Path(root).resolve(strict=True)
    h = hashlib.sha256()
    all_paths = list(root.rglob("*"))
    # Reject links including directory symlinks, even when pathlib would not
    # traverse those directories and would silently omit linked model bytes.
    require(not any(path.is_symlink() for path in all_paths), "symlink in artifact")
    paths = sorted(x for x in all_paths if x.is_file() and
                   (not only_python or x.suffix == ".py"))
    require(bool(paths), "empty model/SDK artifact")
    for path in paths:
        require(not path.is_symlink() and path.resolve().is_relative_to(root), "symlink in artifact")
        name = path.relative_to(root).as_posix().encode("utf-8")
        h.update(len(name).to_bytes(4, "big") + name)
        h.update(bytes.fromhex(sha_file(path)))
    return h.hexdigest()


def write_new(path, data):
    payload = (json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode()
    with open(path, "xb") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())


def strict_json_loads(data):
    """Reject duplicate keys and non-JSON float literals at trust boundaries."""
    def no_duplicates(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def invalid_constant(value):
        raise InvalidTrial(f"nonfinite JSON literal: {value}")

    return json.loads(data, object_pairs_hook=no_duplicates,
                      parse_constant=invalid_constant)


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return strict_json_loads(f.read())


def verify_checkout(expected_sha):
    result = subprocess.run(["git", "rev-parse", "HEAD"],
                            cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, check=False)
    require(result.returncode == 0 and result.stdout.strip() == expected_sha,
            "source checkout differs from frozen manifest")


def canonical_jsonl(rows):
    return b"".join((json.dumps(row, sort_keys=True, ensure_ascii=False,
                                 separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
                    for row in rows)


def blind_rows(rows, family):
    """Evaluator-only deterministic export: no holdout gold/OOD or future targets.

    This removes labels before the model runner receives the input file. The
    evaluator must retain the complete source file under separate permissions.
    """
    allow = {"id", "split", "source_group", "observed_at_ms", "language",
             "domain", "state", "question", "option_order", "features_q24", "target_q24"}
    result = []
    for original in rows:
        row = {key: value for key, value in original.items() if key in allow}
        if family == "heads" and row["split"] != "train":
            row.pop("target_q24", None)
        if family != "heads":
            row.pop("target_q24", None)
        result.append(row)
    return result


def load_inputs(manifest_file, dataset_file, role="evaluator"):
    require(role in ("evaluator", "runner"), "invalid dataset access role")
    manifest = read_json(manifest_file)
    require(manifest.get("schema") == SCHEMA and manifest.get("family") in ARMS, "invalid manifest")
    require(is_sha(manifest.get("source_sha"), 40), "source SHA must be a pinned Git commit")
    require(is_sha(manifest.get("dataset_sha256")) and
            is_sha(manifest.get("blind_dataset_sha256")), "sealed/blinded dataset SHA missing")
    expected = manifest["dataset_sha256" if role == "evaluator" else "blind_dataset_sha256"]
    require(sha_file(dataset_file) == expected, "dataset changed after freezing")
    require(is_sha(manifest.get("host_profile_digest")), "host profile missing")
    require(type(manifest.get("parameter_cap")) is int and manifest["parameter_cap"] > 0, "parameter cap missing")
    if manifest["family"] == "heads":
        h = manifest.get("head", {})
        require(type(h.get("input_dimension")) is int and
                type(h.get("state_width")) is int and
                1 <= h["input_dimension"] <= 512 and 5 <= h["state_width"] <= 256,
                "head shape is not within fixed Neuron dimensions")
        expected, _ = parameter_budget(h["input_dimension"], h["state_width"])
        require(manifest["parameter_cap"] == expected["linear"],
                "head cap differs from the exact Linear baseline")
    else:
        require(type(manifest.get("max_len")) is int and manifest["max_len"] == 512 and
                is_sha(manifest.get("sdk_tree_sha256")) and
                is_sha(manifest.get("upstream_lock_sha256")) and
            for field in ("language", "domain"):
                labels = sorted({source[field] for source, _ in batch})
                cohort_scores[field] = {
                    label: {
                        "count": sum(source[field] == label for source, _ in batch),
                        "accuracy": statistics.mean(int(max(range(len(pred["probabilities"])),
                               key=pred["probabilities"].__getitem__) ==
                               source["option_order"].index(source["gold"]))
                               for source, pred in batch if source[field] == label),
                    } for label in labels
                }
            result.update({"cohorts": cohort_scores,
                           "accuracy": statistics.mean(correct), "brier_multiclass": statistics.mean(bs),
                           "ece10": sum(len(b) * abs(statistics.mean(x for x, _ in b) -
                                                      statistics.mean(y for _, y in b)) for b in bins if b) / len(batch),
                           "ood_samples": ood_count,
                           "ood_false_accept_at_0_8": accepted / ood_count if ood_count else None})
        else:
            squares, absolute = [], []
            for source, pred in batch:
                p = pred["prediction_q24"]
                require(isinstance(p, list) and len(p) == len(source["target_q24"]) and
                        all(type(v) is int and abs(v) <= 8 * Q24 for v in p), "invalid q24 output")
                for a, b in zip(p, source["target_q24"]):
                    delta = (a - b) / Q24
                    squares.append(delta * delta)
                    absolute.append(abs(delta))
            result.update({"mse": statistics.mean(squares), "mae": statistics.mean(absolute)})
        summary[split] = result
    return summary


def compare(manifest, rows, packets, baseline_sha):
    family = manifest["family"]
    require(set(packets) == set(ARMS[family]) and is_sha(baseline_sha), "complete arms/frozen baseline required")
    baseline_arm = ARMS[family][0]
    require(sha_file(packets[baseline_arm]) == baseline_sha, "no-change baseline receipt changed")
    receipts = {arm: read_json(file) for arm, file in packets.items()}
    ids = {r["id"] for r in rows if r["split"] in EVAL_SPLITS}
    results = {}
    for arm, receipt in receipts.items():
        require(receipt.get("schema") == SCHEMA and receipt.get("family") == family and
                receipt.get("arm") == arm and receipt.get("source_sha") == manifest["source_sha"] and
                receipt.get("dataset_sha256") == manifest["dataset_sha256"] and
                receipt.get("blind_dataset_sha256") == manifest["blind_dataset_sha256"] and
                receipt.get("host_profile_digest") == manifest["host_profile_digest"],
                "model/dataset/host identity drift")
        if family != "heads":
            model = manifest.get("models", {}).get(arm, {})
            require(receipt.get("runtime", {}).get("upstream_lock_sha256") ==
                    manifest.get("upstream_lock_sha256"),
                    "experiment receipt lost upstream source-lock binding")
