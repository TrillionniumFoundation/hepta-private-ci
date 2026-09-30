"""Qualify the real runtime encoder/heads on retained raw held-out observations.

No training, artifact selection, environment mutation or terminal truth is provided
by this command. Generated held-out examples are not prospective GUI evidence.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np
import torch
from torch import nn
import decision_cell_bakeoff as panel

WORKER = Path(__file__).resolve().parents[2] / "hepta-infer-worker-host/python"
sys.path.insert(0, str(WORKER))
from decision_cell_encoder import FrozenMdebertaDecisionCellV2


def probe(receipt_path: Path, model_root: Path) -> dict:
    source = panel.repository_source()
    receipt, receipt_digest = panel.verified_receipt(receipt_path)
    if receipt["model_name"] != "mdeberta-v3-base":
        raise ValueError("this runtime profile implements only the pinned mDeBERTa base")
    model_path, base = panel.model_snapshot(panel.MODEL_SPECS[receipt["model_name"]], model_root)
    if base["snapshot_digest"] != receipt["base_model"]["snapshot_digest"]:
        raise ValueError("base snapshot changed")
    artifact = receipt["head_artifact"]
    manifest = panel._tensor_module.strict_json(Path(artifact["manifest_path"]).read_bytes())
    dataset_path = receipt_path.parent.parent / "dataset" / f"dataset-{receipt['dataset_sha256']}.json"
    dataset_raw = dataset_path.read_bytes()
    if panel.sha256_bytes(dataset_raw) != receipt["dataset_sha256"]:
        raise ValueError("retained dataset content changed")
    dataset = json.loads(dataset_raw)
    expected = json.loads(panel.canonical_json([row.as_dict() for row in panel.build_dataset()]))
    if dataset["examples"] != expected:
        raise ValueError("dataset generator cannot reinterpret historical examples")
    selected = [row for row in panel.build_dataset() if row.split == "test"]
    observations = []
    model = FrozenMdebertaDecisionCellV2(
        model_path=model_path, manifest_path=Path(artifact["manifest_path"]),
        manifest_sha256=artifact["manifest_sha256"],
        weights_path=Path(artifact["weights_path"]), weights_sha256=artifact["weights_sha256"],
        expected_base_snapshot=base["snapshot_digest"],
        expected_runtime_profile=manifest["runtime_profile"])
    try:
        for start in range(0, len(selected), 16):
            rows = selected[start:start + 16]
            observations.append(model.observe(tuple(row.text for row in rows),
                tuple(tuple(row.candidates) for row in rows),
                deadline_ns=time.monotonic_ns() + 120 * 10**9))
        count = model.forward_passes
    finally:
        model.close()
    logits = {key: torch.cat([row["scores"][key] for row in observations])
              for key in observations[0]["scores"]}

    class ObservedScores(nn.Module):
        def forward(self, unused_features, unused_targets):
            # Evaluate already observed scores; these placeholders do not run a model.
            return logits

    labels = panel.tensors(selected, np.zeros((len(selected), 1), dtype=np.float32),
                          np.zeros((len(selected), 4, 1), dtype=np.float32))
    metrics = panel.evaluate(ObservedScores(), labels, manifest["calibration"])
    for key, expected_value in receipt["test_metrics"].items():
        actual = metrics[key]
        if expected_value is None:
            if actual is not None:
                raise ValueError("metric nullability changed: " + key)
        elif actual is None or not np.isclose(actual, expected_value, rtol=1e-4, atol=1e-6):
            raise ValueError("runtime encoder/head metric changed: " + key)
    if panel.repository_source() != source:
        raise ValueError("source changed during model execution")
    return {"schema": "hepta.frozen-encoder-probe.v1", "source": source,
            "training_receipt_sha256": receipt_digest,
            "base_snapshot_digest": base["snapshot_digest"],
            "base_upstream_identity": base["upstream_identity"],
            "head_manifest_sha256": artifact["manifest_sha256"],
            "worker_source_sha256": panel.sha256_file(WORKER / "decision_cell_encoder.py"),
            "tensor_source_sha256": panel.sha256_file(WORKER / "decision_cell_tensors.py"),
            "base_loads": 1, "base_forward_passes": count,
            "batch_latency_ns": [row["latency_ns"] for row in observations],
            "input_sha256": [row["input_sha256"] for row in observations],
            "parameter_groups_consumed": ["base_encoder", "organ_adapter", "cell_adapter", "typed_heads"],
            "test_metrics": metrics, "raw_observations_reencoded": True,
            "production_activation": False, "independent_acceptance": False,
            "prospective_future_window_evidence": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = probe(args.receipt.resolve(strict=True), args.model_root)
    data = panel.canonical_json(result)
    with args.output.open("xb") as stream:
        stream.write(data)
    print(json.dumps({"status": "PASS_FROZEN_ENCODER_RUNTIME_PROBE",
        "output": str(args.output), "sha256": panel.sha256_bytes(data),
        "base_forward_passes": result["base_forward_passes"],
        "test_metrics": result["test_metrics"]}, sort_keys=True))
