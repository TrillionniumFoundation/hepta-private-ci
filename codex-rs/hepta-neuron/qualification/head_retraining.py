"""Retrain existing typed heads from a frozen, verified real-encoder materialization.

This reuses the existing trainer and tensor consumer. It is NOT a new backbone
execution, full backend bakeoff, selected runtime, or prospective efficacy claim.
"""
from __future__ import annotations

import argparse
import io
import json
import platform
import re
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import torch

import decision_cell_bakeoff as bakeoff

SCHEMA = "hepta.decision-cell-head-retraining.v1"
MAX_FEATURE_BYTES = 128 * 1024 * 1024


def load_frozen_features(receipt: dict, receipt_root: Path):
    """Bind actual labels, row order and owned feature bytes before optimization."""
    dataset_digest = receipt["dataset_sha256"]
    dataset_path = receipt_root / "dataset" / f"dataset-{dataset_digest}.json"
    data = bakeoff._tensor_module.checked_bytes(dataset_path, dataset_digest, 8 * 1024 * 1024)
    dataset = bakeoff._tensor_module.strict_json(data)
    rows = bakeoff.build_dataset()
    if bakeoff.canonical_json(dataset.get("examples")) != bakeoff.canonical_json([row.as_dict() for row in rows]):
        raise ValueError("historical dataset cannot be reinterpreted")
    artifact = receipt["embedding_artifact"]
    raw = bakeoff._tensor_module.checked_bytes(Path(artifact["path"]), artifact["sha256"], MAX_FEATURE_BYTES)
    if len(raw) != artifact["bytes"]:
        raise ValueError("feature size binding mismatch")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if (len(entries) != 3 or {entry.filename for entry in entries} !=
                {"example_ids.npy", "embeddings.npy", "target_embeddings.npy"} or
                sum(entry.file_size for entry in entries) > MAX_FEATURE_BYTES):
            raise ValueError("unsupported or oversized feature archive")
    with np.load(io.BytesIO(raw), allow_pickle=False) as archive:
        identifiers = archive["example_ids"]
        state = archive["embeddings"]
        targets = archive["target_embeddings"]
        if identifiers.tolist() != [row.example_id for row in rows]:
            raise ValueError("feature row identity/order mismatch")
        if (state.ndim != 2 or state.shape[0] != len(rows) or not 1 <= state.shape[1] <= 4096 or
                targets.shape != (len(rows), bakeoff.TARGET_COUNT, state.shape[1]) or
                list(state.shape) != artifact["shape"] or list(targets.shape) != artifact["target_shape"] or
                artifact["dtype"] != "float32" or state.dtype != np.float32 or targets.dtype != np.float32 or
                not np.isfinite(state).all() or not np.isfinite(targets).all()):
            raise ValueError("invalid frozen feature shape, dtype or values")
        return rows, state.copy(), targets.copy()


def retrain(source_receipt: Path, expected_sha256: str, output_dir: Path) -> Path:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("invalid source receipt digest")
    source = bakeoff.repository_source()
    parent, parent_digest = bakeoff.verified_receipt(source_receipt)
    if parent_digest != expected_sha256:
        raise ValueError("source receipt identity mismatch")
    if parent.get("synthetic_panel_only") is not True:
        raise ValueError("this diagnostic profile only admits the declared synthetic corpus")
    rows, state, targets = load_frozen_features(parent, source_receipt.parent.parent)
    partitions = {}
    for split in ("train", "tuning", "calibration", "test", "ood_test"):
        selected, x, target_x = bakeoff.rows_and_embeddings(rows, state, targets, split)
        if not selected:
            raise ValueError("missing frozen partition")
        partitions[split] = bakeoff.tensors(selected, x, target_x)
    torch.manual_seed(bakeoff.SEED)
    initial_groups = bakeoff.parameter_group_digests(bakeoff.TypedHeads(state.shape[1]))
    started = time.perf_counter()
    heads, training = bakeoff.fit_heads(partitions["train"], partitions["tuning"])
    calibration = bakeoff.calibrate(heads, partitions["calibration"])
    metrics = bakeoff.evaluate(heads, partitions["test"], calibration)
    ood_metrics = bakeoff.evaluate(heads, partitions["ood_test"], calibration)
    groups = bakeoff.parameter_group_digests(heads)
    changed = {key: groups[key] != value for key, value in initial_groups.items()}
    if not all(changed.values()):
        raise ValueError("training did not update every claimed parameter group")
    if bakeoff.repository_source() != source:
        raise ValueError("source changed during head training")
    metadata = {
        "source": source, "script_sha256": bakeoff.sha256_file(Path(__file__)),
        "trainer_sha256": bakeoff.sha256_file(Path(bakeoff.__file__)),
        "tensor_consumer_sha256": bakeoff.sha256_file(bakeoff._TENSOR_PATH),
        "evaluation_profile": bakeoff.EVALUATION_PROFILE,
        "evaluation_implementation_sha256": bakeoff.sha256_file(Path(__file__).with_name("decision_cell_metrics.py")),
        "base_model": parent["base_model"], "base_materialization_source": parent["source"],
        "source_receipt_sha256": parent_digest, "dataset_sha256": parent["dataset_sha256"],
        "embedding_artifact": parent["embedding_artifact"], "training": training,
        "calibration": calibration, "base_reencoded_this_run": False,
        "base_upstream_reverified_this_run": False,
        "synthetic_panel_only": True,
    }
    _, artifact = bakeoff.save_head_artifact(output_dir, parent["model_name"], heads, metadata)
    manifest = bakeoff._tensor_module.strict_json(Path(artifact["manifest_path"]).read_bytes())
    bundle = bakeoff._tensor_module.HeadTensorBundleV2(
        manifest_path=Path(artifact["manifest_path"]), manifest_sha256=artifact["manifest_sha256"],
        weights_path=Path(artifact["weights_path"]), weights_sha256=artifact["weights_sha256"],
        expected_base_snapshot=parent["base_model"]["snapshot_digest"],
        expected_runtime_profile=manifest["runtime_profile"])
    x, target_x = partitions["test"]["x"][:32], partitions["test"]["target_x"][:32]
    with torch.inference_mode():
        expected = heads(x, target_x)
    observed = bundle.observe(x, target_x)
    if any(not torch.equal(expected[name], observed[name]) for name in expected):
        raise ValueError("reloaded trained tensor graph differs")
    report = {
        "schema": SCHEMA, **metadata, "model_name": parent["model_name"],
        "head_artifact": artifact, "parameter_group_sha256": groups,
        "parameter_groups_changed_from_initialization": changed,
        "test_metrics": metrics, "ood_test_metrics": ood_metrics,
        "diagnostic_quality_gates": bakeoff.eligibility({
            "evaluation_profile": bakeoff.EVALUATION_PROFILE,
            "test_metrics": metrics, "ood_test_metrics": ood_metrics}),
        "elapsed_seconds": time.perf_counter() - started,
        "process": {"python": sys.version, "torch": torch.__version__, "numpy": np.__version__,
                    "platform": platform.platform(), "device": "cpu", "threads": torch.get_num_threads()},
        "actual_head_training": True, "saved_weights_reloaded": True,
        "reload_logits_identical": True, "full_backend_bakeoff": False,
        "runtime_selection_eligible": False, "prospective_future_window_evidence": False,
        "production_activation": False, "operator_acceptance": False, "selected": False, "release": False,
    }
    if bakeoff.repository_source() != source:
        raise ValueError("source changed before training report publication")
    raw = bakeoff.canonical_json(report)
    directory = output_dir / "receipts"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"head-retraining-{parent['model_name']}-{bakeoff.sha256_bytes(raw)}.json"
    with path.open("xb") as stream:
        stream.write(raw)
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-receipt", required=True, type=Path)
    parser.add_argument("--source-receipt-sha256", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    torch.set_num_threads(2)
    path = retrain(args.source_receipt.resolve(strict=True), args.source_receipt_sha256, args.output_dir)
    print(json.dumps({"status": "PASS_REAL_HEAD_RETRAINING", "receipt": str(path),
                      "sha256": bakeoff.sha256_file(path), "full_backend_bakeoff": False,
                      "production_activation": False}, sort_keys=True))
