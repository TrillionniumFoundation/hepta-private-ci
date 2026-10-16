#!/usr/bin/env python3
"""Physically export real, frozen ModernBERT BANKING77 pooled features to Q24.

Public research only. The PCA32 projection is fitted on unlabeled training
features; the official test split never contributes to fit statistics, and
test labels never reach the Encoder worker. This is NOT deployed FeatureSnapshot
authority, production V1 provenance or independently evaluated model efficacy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

MODEL_REV = "8949b909ec900327062f0ebf497f51aef5e6f0c8"
DATA_REV = "57ec275d8078af65b7731c2a98be812d844a6d6b"
Q = 1 << 24
FEAT_WIDTH = 768
OUTPUT_WIDTH = 32
FIT = 64
HELDOUT = 32
SCHEMA = "hepta.neuron.real-public-modernbert-q24-features.v1"


def checked(ok, why):
    if not ok:
        raise ValueError(why)


def strict_json_bytes(raw):
    def unique(pairs):
        result = {}
        for k, v in pairs:
            checked(k not in result, "duplicate input JSON key")
            result[k] = v
        return result
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    path = Path(path)
    checked(path.is_file() and not path.is_symlink()
            and 0 < path.stat().st_size <= 2_000_000, "unbounded source file")
    return path.read_bytes()


def frozen_inputs(data_root: Path, selection_path: Path, output: Path):
    """Dataset owner: rederive exactly the original public train/test selection.

    Produces public Encoder-only inputs (heldout rows have *no* label). This
    subprocess does NOT load the pretrained model or evaluate outcomes.
    """
    from banking77_material import prepare, REVISION
    from matrix_materials import file_sha256
    from matrix_runtime import write_json_exclusive
    from public_cell_learning import validate_inputs

    checked(REVISION == DATA_REV, "public BANKING77 Git commit changed")
    root = Path(data_root)
    lock = strict_json_bytes(read(root / "SOURCE.json"))
    material = strict_json_bytes(read(root / "MATERIAL.json"))
    checked(lock.get("revision") == DATA_REV and
            lock.get("license") == "CC-BY-4.0" and
            material.get("source") == lock, "source lock/license drift")
    train_path, held_path = (root / "banking_data/train.csv",
                            root / "banking_data/test.csv")
    train_bytes, held_bytes = read(train_path), read(held_path)
    checked(material["sha256"].get("banking_data/train.csv") == sha(train_bytes)
            and material["sha256"].get("banking_data/test.csv") == sha(held_bytes),
            "original physically acquired public CSV hashes changed")
    inputs, _unused_heldout_answers, selection = prepare(train_bytes, held_bytes)
    original = strict_json_bytes(read(selection_path))
    checked(original == selection, "source case selection differs from actual original learning run")
    validate_inputs(inputs)
    checked(len(inputs["fit"]) == FIT and len(inputs["heldout"]) == HELDOUT
            and all("label" not in row for row in inputs["heldout"]),
            "incomplete / tainted public official-test input")
    write_json_exclusive(Path(output), inputs)
    return {"data_revision": DATA_REV, "input_id": inputs["input_id"],
            "selected_ids": selection["selected_ids"],
            "heldout_labels_released_to_encoder": False,
            "encoder_executed": False, "production_qualification": False}


def fit_training_pca32(train):
    """SVD of FIT data only; no test features, labels or classifier gradients."""
    import torch
    checked(isinstance(train, torch.Tensor) and train.dtype == torch.float32
            and train.shape == (FIT, FEAT_WIDTH)
            and bool(torch.isfinite(train).all()),
            "training-only real Encoder PCA requires 64 finite 768D vectors")
    mean = train.mean(dim=0)
    centered = train - mean
    _u, singular, vh = torch.linalg.svd(centered, full_matrices=False)
    checked(bool(torch.isfinite(singular).all())
            and bool((singular[:OUTPUT_WIDTH] > 1e-7).all()),
            "train-only feature rank too small for independent 32D PCA")
    components = vh[:OUTPUT_WIDTH].T.contiguous()
    # A deterministic sign convention removes the usual independent SVD
    # singular-vector sign ambiguity without seeing heldout examples.
    for i in range(OUTPUT_WIDTH):
        index = int(torch.argmax(torch.abs(components[:, i])).item())
        if components[index, i].item() < 0:
            components[:, i].neg_()
    fit32 = centered @ components
    scales = torch.sqrt(torch.mean(fit32.square(), dim=0)).clamp_min(1e-6)
    checked(bool(torch.isfinite(scales).all()) and bool((scales > 0).all()),
            "invalid train-only projection normalization")
    return {"center": mean.contiguous(), "components": components, "scale": scales.contiguous()}


def project_q24(features, projector):
    import torch
    checked(type(features) is torch.Tensor and features.dtype == torch.float32
            and features.ndim == 2 and features.shape[1] == FEAT_WIDTH
            and bool(torch.isfinite(features).all()),
            "untrusted frozen Encoder feature matrix")
    y = (features - projector["center"]) @ projector["components"]
    y = y / projector["scale"]
    checked(bool(torch.isfinite(y).all()), "nonfinite real projected feature")
    clipping = int((torch.abs(y) > 8).sum().item())
    integer = torch.round(y.to(torch.float64).clamp(-8.0, 8.0) * Q).to(torch.int64)
    checked(integer.shape[1] == OUTPUT_WIDTH and
            bool((integer.abs() <= 8 * Q).all()), "invalid Q24 export")
    return integer.contiguous(), clipping


def physical_snapshot(inputs: dict, backend, dest: Path,
                      *, source_identity: dict | None = None):
    """Exactly one independently measured physical Encoder pass per snapshot.

    Called with the real LocalHFEncoder in hosted CI, or an explicitly marked
    synthetic fixture in *unit tests only*. A fixture cannot be called a real
    pretrained execution and cannot receive production authority.
    """
    import torch
    from safetensors.torch import save_file, load_file
    from banking77_material import INTENTS
    from matrix_runtime import write_json_exclusive
    from public_cell_learning import validate_inputs

    validate_inputs(inputs)
    checked(len(inputs["fit"]) == FIT and len(inputs["heldout"]) == HELDOUT,
            "selected public case census must be exactly 64/32")
    checked(backend.dimension == FEAT_WIDTH,
            "real public ModernBERT has expected 768D pooled feature dimension")
    if source_identity is not None:
        checked(source_identity.get("model_revision") == MODEL_REV
                and source_identity.get("dataset_revision") == DATA_REV
                and source_identity.get("snapshot_sha256") == backend.receipt.get("snapshot_sha256")
                and backend.receipt.get("pretrained_provenance_independently_verified") is False,
                "real physical source provenance must not be invented")
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    root = Path(dest)
    root.mkdir(exist_ok=False)
    matrices, tokens = {}, {}
    try:
        for name, rows in (("fit", inputs["fit"]), ("heldout", inputs["heldout"])):
            features = torch.empty((len(rows), FEAT_WIDTH), dtype=torch.float32)
            lengths = []
            for i, row in enumerate(rows):
                # The original public Encoder prompt, options and text only.
                request = {"state": row["text"],
                           "question": "Select the customer service intent.",
                           "options": list(INTENTS)}
                vector, length = backend.encode(request)
                checked(type(vector) is torch.Tensor
                        and vector.shape == (FEAT_WIDTH,)
                        and vector.dtype == torch.float32
                        and not vector.requires_grad
                        and bool(torch.isfinite(vector).all())
                        and type(length) is int and 0 < length <= 256,
                        "real Encoder emitted wrong width/tokens/precision")
                features[i].copy_(vector)
                lengths.append(length)
            matrices[name], tokens[name] = features, lengths
        backend.reverify()
        projection = fit_training_pca32(matrices["fit"])
        fit_q24, fit_clipped = project_q24(matrices["fit"], projection)
        held_q24, held_clipped = project_q24(matrices["heldout"], projection)
        data_files = {
            "pooled-f32.safetensors": {
                "fit": matrices["fit"], "heldout": matrices["heldout"],
            },
            "train-only-pca32.safetensors": projection,
            "feature-q24.safetensors": {
                "fit": fit_q24, "heldout": held_q24,
            },
        }
        for filename, tensors in data_files.items():
            target = root / filename
            checked(not target.exists(), "feature file already exists")
            save_file(tensors, str(target))
            reopened = load_file(str(target), device="cpu")
            checked(set(tensors) == set(reopened) and all(
                torch.equal(value, reopened[k]) for k, value in tensors.items()
            ), "physical saved feature/projection differs from reloaded tensors")
        registry = {
            "schema": "hepta.neuron.public-q24-case-registry.v1",
            "input_id": inputs["input_id"], "dataset_revision": DATA_REV,
            "real_pretrained_source_provenance_independently_verified": False,
            "fit": [{"id": r["id"], "label": r["label"]} for r in inputs["fit"]],
            "heldout": [{"id": r["id"]} for r in inputs["heldout"]],
            "no_heldout_labels_in_feature_snapshot": True,
            "fit_count": FIT, "heldout_count": HELDOUT,
            "tokens": tokens, "clipped_coordinates": {"fit": fit_clipped, "heldout": held_clipped},
            "no_future_window_claim": True, "original_selected_v1_a0_verified": False,
        }
        write_json_exclusive(root / "case-registry.json", registry)
        # Independently rehydrate saved F32+fitted projection, not the in-memory
        # intermediate tensors, and prove Q24 exact equality at both splits.
        pooled = load_file(str(root / "pooled-f32.safetensors"), device="cpu")
        fitted = load_file(str(root / "train-only-pca32.safetensors"), device="cpu")
        exported = load_file(str(root / "feature-q24.safetensors"), device="cpu")
        for name in ("fit", "heldout"):
            replay, _ = project_q24(pooled[name], fitted)
            checked(torch.equal(replay, exported[name]), "saved real feature Q24 replay differs")
        from matrix_materials import file_sha256
        files = {name: {"sha256": file_sha256(root / name),
                        "bytes": (root / name).stat().st_size}
                 for name in (*data_files, "case-registry.json")}
        report = {
            "schema": SCHEMA, "source_class": "REAL_PINNED_PUBLIC_ENCODER"
            if source_identity is not None else "SYNTHETIC_UNIT_FIXTURE_ONLY",
            "authority": "DENY_ALL", "decision": "NO_MODEL_PROMOTION",
            "source_identity": source_identity,
            "encoder_receipt": backend.receipt,
            "input_id": inputs["input_id"], "projection_fitted_on": "UNLABELED_FIT_FEATURES_ONLY",
            "frozen_feature_width": FEAT_WIDTH, "q24_feature_width": OUTPUT_WIDTH,
            "split_counts": {"fit": FIT, "heldout": HELDOUT},
            "physical_encoder_forward_calls_this_snapshot": FIT + HELDOUT,
            "projection_trained_with_test_features_or_labels": False,
            "heldout_predictions_or_labels_scored": False,
            "real_task_quality_measured": False,
            "future_window_utility_verified": False,
            "no_change_production_v1_baseline_verified": False,
            "source_group_or_temporal_independence_verified": False,
            "production_qualification": False, "ndu_eligible": False,
            "files": files,
        }
        write_json_exclusive(root / "SEALED.json", report)
        return report
    except Exception as e:
        write_json_exclusive(root / "FAILED.json", {
            "error_type": type(e).__name__, "source_kind": "NONPRODUCTION",
            "production_qualification": False,
        })
        raise


def main() -> int:
    from matrix_materials import file_sha256
    from hf_encoder_kernel import snapshot_digest
    from hf_complete_checkpoint import ENCODER_PROFILE
    from matrix_runtime import LocalHFEncoder
    parser = argparse.ArgumentParser(description=__doc__)
    cmd = parser.add_subparsers(dest="command", required=True)
    prep = cmd.add_parser("prepare", help="freeze selected IDs and strip heldout labels")
    prep.add_argument("--data-root", type=Path, required=True)
    prep.add_argument("--selection", type=Path, required=True)
    prep.add_argument("--output", type=Path, required=True)
    produce = cmd.add_parser("encode", help="execute real pretrained public ModernBERT")
    produce.add_argument("--inputs", type=Path, required=True)
    produce.add_argument("--public-probe", type=Path, required=True)
    produce.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            result = frozen_inputs(args.data_root, args.selection, args.output)
        else:
            from public_encoder_probe import MODEL_ID
            source = args.public_probe
            lock = strict_json_bytes(read(source / "source-lock.json"))
            material = strict_json_bytes(read(source / "downloaded-material.json"))
            checked(lock.get("model_id") == MODEL_ID
                    and lock.get("upstream_revision") == MODEL_REV
                    and material.get("source_lock_sha256") ==
                    file_sha256(source / "source-lock.json"), "wrong pinned pretrained source")
            snapshot = source / "snapshot"
            fingerprint = snapshot_digest(snapshot)
            checked(material.get("snapshot_sha256") == fingerprint,
                    "real pretrained public weights changed")
            cfg = {
                "snapshot_sha256": fingerprint, "context_tokens": 256,
                "encoder_profile": ENCODER_PROFILE,
                "upstream_revision": MODEL_REV, "material_approval_sha256": None,
            }
            backend = LocalHFEncoder(snapshot, cfg, {"stem": "smaller_control"})
            inputs = strict_json_bytes(read(args.inputs))
            result = physical_snapshot(inputs, backend, args.output, source_identity={
                "model_id": MODEL_ID, "model_revision": MODEL_REV,
                "dataset_revision": DATA_REV, "snapshot_sha256": fingerprint,
                "source_lock_sha256": file_sha256(source / "source-lock.json"),
                "material_sha256": file_sha256(source / "downloaded-material.json"),
                "inputs_sha256": file_sha256(args.inputs),
                "public_pretrained_artifact_signature_verified": False,
            })
        print(json.dumps({"schema": SCHEMA, "decision": "NO_MODEL_PROMOTION",
                          "input_id": result["input_id"]}, sort_keys=True))
        return 0
    except (ValueError, OSError) as e:
        print("BLOCKED_REAL_PUBLIC_Q24_SNAPSHOT: " + str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
