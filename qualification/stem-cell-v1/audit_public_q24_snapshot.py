#!/usr/bin/env python3
"""Independent physical re-open of real public ModernBERT PCA32/Q24 files.

Verifies immutable file digest/shape, the training-only PCA fit, Q24 replay
and heldout-label absence. No model execution/producer signature here; the
original pretrained checkpoint must be executed in the separate hosted owner.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import stat
import sys

SOURCE_SCHEMA = "hepta.neuron.real-public-modernbert-q24-features.v1"
CASE_SCHEMA = "hepta.neuron.public-q24-case-registry.v1"
DATA_REV = "57ec275d8078af65b7731c2a98be812d844a6d6b"
HIDDEN = 768
Q = 1 << 24
FILES = frozenset([
    "pooled-f32.safetensors", "train-only-pca32.safetensors",
    "feature-q24.safetensors", "case-registry.json",
])


class Invalid(ValueError):
    pass


def need(condition, why):
    if not condition:
        raise Invalid(why)


def source_bytes(path, cap):
    path = Path(path)
    need(path.is_file() and not path.is_symlink(), "missing/linked input artifact")
    prior = path.stat()
    need(stat.S_ISREG(prior.st_mode) and 1 <= prior.st_size <= cap, "unbounded feature artifact")
    raw = path.read_bytes()
    after = path.stat()
    need(all(getattr(prior, k) == getattr(after, k) for k in (
        "st_ino", "st_dev", "st_size", "st_mtime_ns", "st_ctime_ns"
    )), "feature input modified during verification")
    return raw


def strict_json(raw):
    def pairs(items):
        seen = {}
        for k, v in items:
            need(k not in seen, "duplicate sealed record JSON key")
            seen[k] = v
        return seen
    def finite(token):
        val = float(token)
        need(math.isfinite(val), "nonfinite JSON")
        return val
    return json.loads(raw, object_pairs_hook=pairs, parse_float=finite,
                      parse_constant=lambda _: (_ for _ in ()).throw(Invalid("nonfinite JSON")))


def audit(snapshot, input_id_file=None):
    import torch
    from safetensors.torch import load
    from public_q24_feature_snapshot import fit_training_pca32, project_q24

    root = Path(snapshot)
    need(root.is_dir() and not root.is_symlink(), "missing/linked frozen snapshot")
    raw_seal = source_bytes(root / "SEALED.json", 160_000)
    seal = strict_json(raw_seal)
    need(type(seal) is dict and seal.get("schema") == SOURCE_SCHEMA
         and seal.get("authority") == "DENY_ALL"
         and seal.get("decision") == "NO_MODEL_PROMOTION"
         and seal.get("split_counts") == {"fit":64, "heldout":32}
         and seal.get("frozen_feature_width") == HIDDEN
         and seal.get("q24_feature_width") == 32
         and seal.get("physical_encoder_forward_calls_this_snapshot") == 96
         and seal.get("projection_fitted_on") == "UNLABELED_FIT_FEATURES_ONLY",
         "wrong fitted real physical FeatureSnapshot schema/source")
    for name in ("production_qualification", "ndu_eligible",
                 "heldout_predictions_or_labels_scored", "future_window_utility_verified",
                 "no_change_production_v1_baseline_verified",
                 "projection_trained_with_test_features_or_labels",
                 "real_task_quality_measured",
                 "source_group_or_temporal_independence_verified"):
        need(seal.get(name) is False, "forged source snapshot qualification: " + name)
    source_class = seal.get("source_class")
    need(source_class in ("REAL_PINNED_PUBLIC_ENCODER", "SYNTHETIC_UNIT_FIXTURE_ONLY"),
         "unregistered source evidence kind")
    identity = seal.get("source_identity")
    if source_class == "REAL_PINNED_PUBLIC_ENCODER":
        need(type(identity) is dict and
             identity.get("model_id") == "answerdotai/ModernBERT-base" and
             identity.get("model_revision") == "8949b909ec900327062f0ebf497f51aef5e6f0c8" and
             identity.get("dataset_revision") == DATA_REV and
             identity.get("public_pretrained_artifact_signature_verified") is False and
             seal.get("encoder_receipt",{}).get("snapshot_sha256") ==
             identity.get("snapshot_sha256"),
             "source provenance incomplete/overstated")
    else:
        need(identity is None, "fixture supplied a forged pretrained source identity")
    entries = seal.get("files")
    need(type(entries) is dict and set(entries) == FILES, "missing/foreign model files")
    raw = {}
    for filename, info in entries.items():
        cap = 500_000 if filename.endswith(".safetensors") else 100_000
        original = source_bytes(root / filename, cap)
        need(type(info) is dict and
             info.get("bytes") == len(original) and
             info.get("sha256") == hashlib.sha256(original).hexdigest(),
             "physical saved feature/projection SHA mismatch")
        raw[filename] = original
    registry = strict_json(raw["case-registry.json"])
    need(type(registry) is dict and registry.get("schema") == CASE_SCHEMA and
         registry.get("input_id") == seal.get("input_id") and
         registry.get("dataset_revision") == DATA_REV and
         registry.get("no_heldout_labels_in_feature_snapshot") is True and
         registry.get("no_future_window_claim") is True and
         registry.get("original_selected_v1_a0_verified") is False and
         registry.get("fit_count") == 64 and registry.get("heldout_count") == 32,
         "feature case registry scope/identity drift")
    fits, holds = registry.get("fit"), registry.get("heldout")
    need(type(fits) is list and len(fits) == 64 and
         type(holds) is list and len(holds) == 32, "missing original public case census")
    need(all(type(row) is dict and set(row) == {"id", "label"}
             and type(row["id"]) is str and type(row["label"]) is int
             and 0 <= row["label"] < 4 for row in fits),
         "bad training labels / source identity")
    need(all(type(row) is dict and set(row) == {"id"}
             and type(row["id"]) is str for row in holds),
         "heldout labels or fields leaked into Q24 source")
    ids = [r["id"] for r in fits + holds]
    need(len(set(ids)) == 96 and
         sum(1 for r in fits if r["label"] == 0) == 16 and
         all(sum(1 for r in fits if r["label"] == cls) == 16
             for cls in range(4)),
         "duplicate/non-stratified public case registry")
    if input_id_file is not None:
        original_inputs = strict_json(source_bytes(input_id_file, 1_000_000))
        need(type(original_inputs) is dict and
             original_inputs.get("input_id") == seal.get("input_id") and
             [r["id"] for r in original_inputs.get("fit",[])] == [r["id"] for r in fits] and
             [r["label"] for r in original_inputs.get("fit",[])] ==
             [r["label"] for r in fits] and
             [r["id"] for r in original_inputs.get("heldout",[])] ==
             [r["id"] for r in holds] and
             all(set(r) == {"id","text"} for r in original_inputs["heldout"]),
             "original public input/selected-case map changed")
        need(source_class != "REAL_PINNED_PUBLIC_ENCODER" or
             identity.get("inputs_sha256") ==
             hashlib.sha256(source_bytes(input_id_file, 1_000_000)).hexdigest(),
             "registered model input document SHA differs")
    import io
    fp32 = load(raw["pooled-f32.safetensors"])
    projection = load(raw["train-only-pca32.safetensors"])
    q24 = load(raw["feature-q24.safetensors"])
    need(set(fp32) == set(q24) == {"fit", "heldout"} and
         set(projection) == {"center", "components", "scale"},
         "missing physical Q24/F32 tensor name")
    need(fp32["fit"].shape == (64, 768) and
         fp32["heldout"].shape == (32, 768) and
         fp32["fit"].dtype == fp32["heldout"].dtype == torch.float32 and
         projection["center"].shape == (768,) and
         projection["components"].shape == (768,32) and
         projection["scale"].shape == (32,) and
         all(t.dtype == torch.float32 for t in projection.values()) and
         q24["fit"].shape == (64,32) and q24["heldout"].shape == (32,32) and
         all(v.dtype == torch.int64 for v in q24.values()),
         "non-native physical feature/projection tensor shape/dtype")
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    fit_only = fit_training_pca32(fp32["fit"])
    for key in projection:
        need(torch.equal(fit_only[key], projection[key]),
             "heldout-trained or altered PCA32 projection")
    for split in ("fit", "heldout"):
        reproduced, _ = project_q24(fp32[split], projection)
        need(torch.equal(q24[split], reproduced), "independent saved Q24 feature replay mismatch")
    return {
        "schema": "hepta.neuron.independent-public-q24-snapshot-reopen.v1",
        "sealed_sha256": hashlib.sha256(raw_seal).hexdigest(),
        "source_class": source_class,
        "input_id": seal["input_id"],
        "physical_model_source_identity_present": source_class == "REAL_PINNED_PUBLIC_ENCODER",
        "train_only_pca32_exact": True, "frozen_real_q24_feature_rows": 96,
        "heldout_labels_absent": True, "fit_heldout_overlap_count": 0,
        "real_pretrained_encoder_independently_reexecuted": False,
        "original_deployment_v1_verified": False,
        "future_window_efficacy_verified": False,
        "ndu_eligible": False, "production_qualification": False,
        "decision": "NO_MODEL_PROMOTION",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--input-id-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = audit(args.snapshot, args.input_id_file)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
        return 0
    except (Invalid, ValueError, OSError, KeyError, TypeError) as e:
        print("BLOCKED_INDEPENDENT_REAL_Q24_SNAPSHOT: " + str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
