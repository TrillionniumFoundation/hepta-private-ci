#!/usr/bin/env python3
"""Source-sealed public BANKING77 32D Q24 task-input adapter (read-only).

This does NOT fabricate temporal trajectories, invoke the native Q24 kernel,
obtain future labels, authenticate an original V1 production owner, or select
a Cell. Every observed official test case remains unlabeled.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import stat
import sys

FROZEN_MODERNBERT = "8949b909ec900327062f0ebf497f51aef5e6f0c8"
FROZEN_BANKING77 = "57ec275d8078af65b7731c2a98be812d844a6d6b"
SOURCE_SCHEMA = "hepta.neuron.real-public-modernbert-q24-features.v1"
REGISTRY_SCHEMA = "hepta.neuron.public-q24-case-registry.v1"
INPUT_SCHEMA = "hepta.neuron.immutable-public-q24-independent-cases.v1"
Q = 1 << 24
FILES = ("case-registry.json", "pooled-f32.safetensors",
         "train-only-pca32.safetensors", "feature-q24.safetensors")


class Invalid(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise Invalid(message)


def file_bytes(path: Path, maximum: int) -> bytes:
    require(not path.is_symlink() and path.is_file(), "linked/missing source file")
    original = path.stat()
    require(stat.S_ISREG(original.st_mode) and 1 <= original.st_size <= maximum,
            "unbounded/nonregular real feature source")
    data = path.read_bytes()
    after = path.stat()
    require(all(getattr(original, k) == getattr(after, k) for k in (
        "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns"
    )), "source modified during input admission")
    return data


def strict_json(raw):
    def duplicate(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate public source JSON key")
            result[key] = value
        return result
    def finite(token):
        value = float(token)
        require(math.isfinite(value), "nonfinite public source numeric")
        return value
    return json.loads(raw, object_pairs_hook=duplicate, parse_float=finite,
                      parse_constant=lambda _: (_ for _ in ()).throw(Invalid("nonfinite JSON")))


def accept_public_snapshot(root: Path, *, synthetic_fixture_only: bool = False) -> dict:
    """Physically reopen and independently recount every frozen feature byte."""
    import torch
    from safetensors.torch import load

    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), "untrusted snapshot directory")
    seal_bytes = file_bytes(root / "SEALED.json", 180_000)
    seal = strict_json(seal_bytes)
    require(type(seal) is dict and seal.get("schema") == SOURCE_SCHEMA
            and seal.get("authority") == "DENY_ALL"
            and seal.get("decision") == "NO_MODEL_PROMOTION"
            and seal.get("split_counts") == {"fit": 64, "heldout": 32}
            and seal.get("frozen_feature_width") == 768
            and seal.get("q24_feature_width") == 32
            and seal.get("projection_fitted_on") == "UNLABELED_FIT_FEATURES_ONLY"
            and seal.get("physical_encoder_forward_calls_this_snapshot") == 96,
            "bad real source FeatureSnapshot identity")
    for key in ("production_qualification", "ndu_eligible",
                "projection_trained_with_test_features_or_labels",
                "heldout_predictions_or_labels_scored", "future_window_utility_verified",
                "no_change_production_v1_baseline_verified",
                "source_group_or_temporal_independence_verified"):
        require(seal.get(key) is False, "forged public snapshot authority: " + key)
    kind = seal.get("source_class")
    if synthetic_fixture_only:
        require(kind == "SYNTHETIC_UNIT_FIXTURE_ONLY" and
                seal.get("source_identity") is None,
                "synthetic regression must not claim real pretrained execution")
    else:
        source = seal.get("source_identity")
        receipt = seal.get("encoder_receipt")
        require(kind == "REAL_PINNED_PUBLIC_ENCODER" and type(source) is dict
                and type(receipt) is dict
                and source.get("model_id") == "answerdotai/ModernBERT-base"
                and source.get("model_revision") == FROZEN_MODERNBERT
                and source.get("dataset_revision") == FROZEN_BANKING77
                and source.get("public_pretrained_artifact_signature_verified") is False
                and receipt.get("snapshot_sha256") == source.get("snapshot_sha256")
                and receipt.get("pretrained_provenance_independently_verified") is False,
                "untrusted/missing actual publicly pretrained Encoder source")
        for key in ("snapshot_sha256","source_lock_sha256","material_sha256","inputs_sha256"):
            value = source.get(key)
            require(type(value) is str and len(value) == 64 and
                    all(c in "0123456789abcdef" for c in value),
                    "invalid pinned real Encoder/source digest")
    stored = seal.get("files")
    require(type(stored) is dict and set(stored) == set(FILES),
            "foreign or missing frozen physical tensors")
    physical = {}
    for name in FILES:
        data = file_bytes(root / name, 500_000)
        metadata = stored[name]
        require(type(metadata) is dict and metadata.get("bytes") == len(data)
                and metadata.get("sha256") == hashlib.sha256(data).hexdigest(),
                "physical public Q24 source hash/size mismatch")
        physical[name] = data
    registry = strict_json(physical["case-registry.json"])
    require(type(registry) is dict and registry.get("schema") == REGISTRY_SCHEMA
            and registry.get("input_id") == seal.get("input_id")
            and registry.get("dataset_revision") == FROZEN_BANKING77
            and registry.get("no_heldout_labels_in_feature_snapshot") is True
            and registry.get("no_future_window_claim") is True
            and registry.get("original_selected_v1_a0_verified") is False
            and registry.get("fit_count") == 64
            and registry.get("heldout_count") == 32,
            "feature registry isn't the frozen original public dataset")
    fit, held = registry.get("fit"), registry.get("heldout")
    require(type(fit) is list and len(fit) == 64
            and type(held) is list and len(held) == 32,
            "missing fit / heldout public cases")
    require(all(type(row) is dict and set(row) == {"id", "label"} and
                type(row["id"]) is str and row["id"].startswith("fit:") and
                type(row["label"]) is int and 0 <= row["label"] < 4 for row in fit),
            "invalid source training labels / IDs")
    require(all(type(row) is dict and set(row) == {"id"} and
                type(row["id"]) is str and row["id"].startswith("heldout:")
                for row in held), "official heldout source accidentally contains target label")
    keys = [r["id"] for r in fit + held]
    require(len(set(keys)) == 96 and all(
        sum(r["label"] == cls for r in fit) == 16 for cls in range(4)
    ), "training class balance or split independence changed")

    pooled = load(physical["pooled-f32.safetensors"])
    projector = load(physical["train-only-pca32.safetensors"])
    q24 = load(physical["feature-q24.safetensors"])
    require(set(pooled) == set(q24) == {"fit", "heldout"}
            and set(projector) == {"center", "components", "scale"},
            "wrong saved public pooled/projection/Q24 tensors")
    require(pooled["fit"].shape == (64,768) and pooled["heldout"].shape == (32,768)
            and pooled["fit"].dtype == pooled["heldout"].dtype == torch.float32
            and projector["center"].shape == (768,)
            and projector["components"].shape == (768,32)
            and projector["scale"].shape == (32,)
            and all(t.dtype == torch.float32 for t in projector.values())
            and q24["fit"].shape == (64,32)
            and q24["heldout"].shape == (32,32)
            and all(t.dtype == torch.int64 for t in q24.values()),
            "altered physically saved public model/FeatureSnapshot geometry")
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    mean = pooled["fit"].mean(dim=0)
    _, singular, vh = torch.linalg.svd(pooled["fit"] - mean, full_matrices=False)
    require(bool((singular[:32] > 1e-7).all()), "source training-only PCA32 rank insufficient")
    components = vh[:32].T.contiguous()
    for n in range(32):
        idx = int(torch.argmax(torch.abs(components[:, n])).item())
        if components[idx,n].item() < 0:
            components[:,n].neg_()
    fit32 = (pooled["fit"] - mean) @ components
    scale = torch.sqrt(torch.mean(fit32.square(),dim=0)).clamp_min(1e-6)
    require(torch.equal(mean, projector["center"])
            and torch.equal(components, projector["components"])
            and torch.equal(scale, projector["scale"]),
            "PCA32 used wrong training set or changed projector")
    for name in ("fit","heldout"):
        x = (pooled[name]-mean) @ components
        x = x / scale
        require(bool(torch.isfinite(x).all()), "nonfinite original public features")
        actual = torch.round(x.to(torch.float64).clamp(-8.0,8.0)*Q).to(torch.int64)
        require(torch.equal(actual, q24[name]), "physical real Q24 feature replay mismatch")

    fit_cases = [
        {"case_id": r["id"], "feature_q24": q24["fit"][i].tolist(),
         "class_label": r["label"]}
        for i,r in enumerate(fit)
    ]
    held_cases = [
        {"case_id": r["id"], "feature_q24": q24["heldout"][i].tolist()}
        for i,r in enumerate(held)
    ]
    return {
        "schema": INPUT_SCHEMA,
        "authority": "DENY_ALL",
        "source_class": kind,
        "frozen_feature_seal_sha256": hashlib.sha256(seal_bytes).hexdigest(),
        "frozen_source_input_id": seal["input_id"],
        "original_encoder_model_revision": FROZEN_MODERNBERT,
        "original_dataset_revision": FROZEN_BANKING77,
        "source_feature_width_q24": 32,
        "target_structure": "FOUR_CLASS_LABELS_TRAIN_ONLY",
        "classification_unit": "ONE_INDEPENDENT_UTTERANCE_PER_CASE_NOT_TIMESERIES",
        "train": fit_cases, "heldout": held_cases,
        "training_case_count": 64, "heldout_case_count": 32,
        "equivalent_to_hepta_temporal_training_input": False,
        "original_v1_no_change_checkpoint_verified": False,
        "future_window_utility_verified": False,
        "candidate_task_quality_measured": False,
        "real_model_reexecuted_by_consumer": False,
        "ndu_eligible": False, "production_qualification": False,
        "decision": "NO_MODEL_PROMOTION",
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--snapshot", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--synthetic-fixture-only", action="store_true")
    args = p.parse_args()
    try:
        result = accept_public_snapshot(args.snapshot,
                                        synthetic_fixture_only=args.synthetic_fixture_only)
        with args.output.open("x", encoding="utf-8") as out:
            json.dump(result, out, indent=2, sort_keys=True, allow_nan=False)
            out.write("\n")
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print("BLOCKED_PUBLIC_Q24_CELL_INPUT: "+str(exc),file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
