"""Reload real trained tensor artifacts and re-encode held-out observations.

This is a read-only qualification command, not a selected production worker.
It does not train, dispatch effects, mint trust, or assert future-window efficacy.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from torch import nn
import decision_cell_bakeoff as bakeoff


def replay(receipt_path: Path, model_root: Path, device: str) -> dict:
    consumer_source = bakeoff.repository_source()
    receipt, receipt_digest = bakeoff.verified_receipt(receipt_path)
    name = receipt["model_name"]
    spec = bakeoff.MODEL_SPECS[name]
    head = receipt["head_artifact"]
    manifest = bakeoff._tensor_module.strict_json(Path(head["manifest_path"]).read_bytes())
    snapshot_path, base = bakeoff.model_snapshot(spec, model_root)
    if base["snapshot_digest"] != receipt["base_model"]["snapshot_digest"]:
        raise ValueError("base changed between training and replay")
    bundle = bakeoff._tensor_module.HeadTensorBundleV2(
        manifest_path=Path(head["manifest_path"]), manifest_sha256=head["manifest_sha256"],
        weights_path=Path(head["weights_path"]), weights_sha256=head["weights_sha256"],
        expected_base_snapshot=base["snapshot_digest"],
        expected_runtime_profile=manifest["runtime_profile"])
    rows = bakeoff.build_dataset()
    dataset_path = receipt_path.parent.parent / "dataset" / f"dataset-{receipt['dataset_sha256']}.json"
    dataset = json.loads(dataset_path.read_text())
    if [row.as_dict() for row in rows] != [dict(row, candidates=tuple(row["candidates"])) for row in dataset["examples"]]:
        raise ValueError("dataset generator changed; do not reinterpret historical inputs")
    selected = [row for row in rows if row.split == "test"]
    indices = [i for i, row in enumerate(rows) if row.split == "test"]
    # Stored arrays are input evidence only. Re-encode source observations again.
    with np.load(receipt["embedding_artifact"]["path"], allow_pickle=False) as old:
        expected_state = old["embeddings"][indices].copy()
        expected_targets = old["target_embeddings"][indices].copy()
    encoder = bakeoff.EncoderAdapter(name, snapshot_path, spec, device,
                                    expected_snapshot_digest=base["snapshot_digest"])
    try:
        expected_loader = receipt["model_load_validation"].get("loader_input_identity")
        actual_loader = encoder.loading_report.get("loader_input_identity")
        if actual_loader != expected_loader:
            raise ValueError("effective loader identity changed between training and replay")
        state, _ = encoder.encode([row.text for row in selected], batch_size=8)
        flat, _ = encoder.encode([row.text + "\nCandidate under evaluation: " + candidate
                                 for row in selected for candidate in row.candidates], batch_size=8)
        encoder.verify_loader_inputs()
    finally:
        encoder.close()
    targets = flat.reshape(len(selected), 4, state.shape[1])
    np.testing.assert_allclose(state, expected_state, rtol=1e-4, atol=1e-5)
    np.testing.assert_allclose(targets, expected_targets, rtol=1e-4, atol=1e-5)

    class ReplayedHeads(nn.Module):
        def forward(self, x, target_x):
            parts = [bundle.observe(x[i:i + 32], target_x[i:i + 32]) for i in range(0, len(x), 32)]
            return {key: torch.cat([part[key] for part in parts]) for key in parts[0]}

    metrics = bakeoff.evaluate(ReplayedHeads(), bakeoff.tensors(selected, state, targets), manifest["calibration"])
    for key, expected in receipt["test_metrics"].items():
        actual = metrics[key]
        if expected is None:
            if actual is not None:
                raise ValueError("replay metric nullability changed: " + key)
        elif not np.isclose(actual, expected, rtol=1e-4, atol=1e-6):
            raise ValueError(f"replay metric changed: {key}: {expected} -> {actual}")
    if bakeoff.repository_source() != consumer_source:
        raise ValueError("consumer source changed during replay")
    return {"schema": "hepta.decision-cell-artifact-replay.v1", "model": name,
            "training_source": receipt["source"], "consumer_source": consumer_source,
            "training_receipt_sha256": receipt_digest,
            "replay_script_sha256": bakeoff.sha256_file(Path(__file__)),
            "tensor_consumer_sha256": bakeoff.sha256_file(bakeoff._TENSOR_PATH),
            "base_snapshot_digest": base["snapshot_digest"],
            "base_upstream_identity": base["upstream_identity"],
            "head_manifest_sha256": head["manifest_sha256"],
            "parameter_group_sha256": manifest["parameter_group_sha256"],
            "test_metrics": metrics, "base_reencoded": True,
            "weights_reloaded_without_training": True,
            "state_maximum_absolute_error": float(np.max(np.abs(state - expected_state))),
            "target_maximum_absolute_error": float(np.max(np.abs(targets - expected_targets))),
            "production_activation": False, "selection_authority": False,
            "prospective_future_window_evidence": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = replay(args.receipt.resolve(strict=True), args.model_root, args.device)
    data = bakeoff.canonical_json(result)
    with args.output.open("xb") as stream:
        stream.write(data)
    print(json.dumps({"status": "PASS_DECISION_CELL_ARTIFACT_REPLAY", "output": str(args.output),
                      "sha256": bakeoff.sha256_bytes(data), **result}, sort_keys=True))
