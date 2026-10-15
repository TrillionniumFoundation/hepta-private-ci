"""Research-only train/predict stages for pinned cross-modal stem alignment.

Train sees only TRAIN paired features. Predict sees only source features. Independent
held-out targets are consumed by multimodal_alignment_evaluator.py, never here.
This is an experiment on externally supplied feature bytes, not proof of a real
encoder, authorization, or measured multimodal understanding.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path
import time

import torch

from multimodal_bridge import ContractError, FrozenLinearBridge, ModalityFeature
from multimodal_alignment_contract import (
    SCHEMA, MAX_ROWS, SourceRow, _metadata, canonical, load_pinned_document,
    load_pinned_jsonl, parse_source, sha, write_new,
)

def _fit_projection(x: torch.Tensor, y: torch.Tensor, alpha: float, modality: str) -> FrozenLinearBridge:
    """Regularized CPU least squares, with unpenalized intercept, no gradients."""
    n, d = x.shape
    a = torch.cat((x, torch.ones(n, 1, dtype=torch.float64)), dim=1)
    gram = a.T @ a
    penalty = torch.eye(d + 1, dtype=torch.float64) * alpha
    penalty[d, d] = 0.0
    try:
        weights = torch.linalg.solve(gram + penalty, a.T @ y)
    except RuntimeError as exc:
        raise ContractError("projection solve failed") from exc
    if not bool(torch.isfinite(weights).all()):
        raise ContractError("nonfinite fitted coefficients")
    rows = tuple(tuple(float(v) for v in weights[:d, j]) for j in range(y.shape[1]))
    bias = tuple(float(v) for v in weights[d])
    return FrozenLinearBridge(modality, rows, bias)


def train(rows: list[dict], file_sha: str, *, alpha: float = 0.05) -> dict:
    if type(alpha) not in (float, int) or not math.isfinite(alpha) or not 0 < alpha <= 10:
        raise ContractError("strict positive bounded ridge penalty required")
    if not 8 <= len(rows) <= MAX_ROWS:
        raise ContractError("minimum eight train-only examples required")
    parsed = [parse_source(item, paired=True) for item in rows]
    inputs = [v[0] for v in parsed]
    targets = [v[1] for v in parsed]
    meta = _metadata(inputs)
    if len(meta["group_hashes"]) < 2:
        raise ContractError("independent train source groups required")
    if len({v.scope for v in inputs}) != 1 or len({v.source.modality for v in inputs}) != 1:
        raise ContractError("cross-scope or cross-modality training")
    if len({v.source.encoder_sha256 for v in inputs}) != 1 or len({v.encoder_sha256 for v in targets}) != 1:
        raise ContractError("unversioned training feature encoder")
    if len({len(v.source.values) for v in inputs}) != 1 or len({len(v.values) for v in targets}) != 1:
        raise ContractError("feature width drift")
    if len(inputs[0].source.values) > 512 or len(targets[0].values) > 512:
        raise ContractError("bounded training feature width")
    x = torch.tensor([row.source.values for row in inputs], dtype=torch.float64, device="cpu")
    y = torch.tensor([target.values for target in targets], dtype=torch.float64, device="cpu")
    started = time.perf_counter_ns()
    learned = _fit_projection(x, y, float(alpha), meta["modality"])
    # Deterministic, clearly marked shuffled-target control, TRAIN only.
    rotated = torch.roll(y, shifts=max(1, len(inputs) // 2), dims=0)
    control = _fit_projection(x, rotated, float(alpha), meta["modality"])
    unaligned = FrozenLinearBridge(
        meta["modality"],
        tuple(tuple(float(i == j) for j in range(x.shape[1])) for i in range(y.shape[1])),
        tuple(0.0 for _ in range(y.shape[1])),
    )
    elapsed = time.perf_counter_ns() - started
    for i in inputs:
        learned.project(i.source)
        control.project(i.source)
        unaligned.project(i.source)
    payload = {"schema": SCHEMA + ".fit-artifact", "file_sha256": file_sha,
               "train_target_input_sha256s": sorted({v.input_sha256 for v in targets}),
               "model_admission_verified": False, "independent_capability": False,
               "production_accepted": False, "train_examples": len(inputs),
               "source_width": x.shape[1], "target_width": y.shape[1],
               "target_encoder_sha256": targets[0].encoder_sha256,
               "alpha": float(alpha), "training_wall_ns": elapsed,
               "training_flops": None, "energy_joules": None,
               **meta,
               "bridges": {label: {"rows": [list(row) for row in bridge.rows],
                                   "bias": list(bridge.bias), "sha256": bridge.sha256}
                           for label, bridge in (("fitted", learned), ("rotated_target_control", control),
                                                 ("unaligned_identity", unaligned))}}
    return payload


def load_artifact(raw: dict) -> tuple[dict[str, FrozenLinearBridge], dict]:
    if (type(raw) is not dict or raw.get("schema") != SCHEMA + ".fit-artifact"
            or set(raw.get("bridges", {})) != {"fitted", "rotated_target_control", "unaligned_identity"}):
        raise ContractError("unknown or incomplete fit artifact")
    bridges = {}
    for label, record in raw["bridges"].items():
        bridge = FrozenLinearBridge(raw["modality"],
                                    tuple(tuple(row) for row in record["rows"]),
                                    tuple(record["bias"]))
        if bridge.sha256 != record["sha256"]:
            raise ContractError("bridge weight digest mismatch")
        bridges[label] = bridge
    return bridges, raw


def predict(artifact: dict, sources: list[dict], artifact_sha: str, inputs_sha: str) -> dict:
    bridges, metadata = load_artifact(artifact)
    rows = [parse_source(v, paired=False)[0] for v in sources]
    got = _metadata(rows)
    if (got["scope"] != metadata["scope"] or
            got["modality"] != metadata["modality"] or
            got["source_encoder_sha256"] != metadata["source_encoder_sha256"] or
            len({v.scope for v in rows}) != 1 or
            len({v.source.modality for v in rows}) != 1 or
            len({v.source.encoder_sha256 for v in rows}) != 1 or
            got["max_observed_at"] <= metadata["max_observed_at"] or
            min(v.observed_at for v in rows) <= metadata["max_observed_at"] or
            set(got["group_hashes"]) & set(metadata["group_hashes"]) or
            set(got["source_input_sha256s"]) & set(metadata["source_input_sha256s"])):
        raise ContractError("future phase, source, scope, or training lineage leakage")
    result = []
    for row in rows:
        preds = {label: list(bridge.project(row.source)) for label, bridge in bridges.items()}
        result.append({"case_id": row.case_id, "group_id": row.group_id,
                       "scope": row.scope, "observed_at": row.observed_at,
                       "source_input_sha256": row.source.input_sha256,
                       "predictions": preds})
    return {"schema": SCHEMA + ".sealed-predictions", "fit_artifact_sha256": artifact_sha,
            "future_sources_sha256": inputs_sha, "fit_file_sha256": metadata["file_sha256"],
            "train_group_hashes": metadata["group_hashes"],
            "train_source_input_sha256s": metadata["source_input_sha256s"],
            "train_target_input_sha256s": metadata["train_target_input_sha256s"],
            "max_train_observed_at": metadata["max_observed_at"],
            "target_encoder_sha256": metadata["target_encoder_sha256"],
            "scope": metadata["scope"], "modality": metadata["modality"],
            "source_encoder_sha256": metadata["source_encoder_sha256"],
            "production_accepted": False, "predictions": result}


def main() -> None:
    parser = argparse.ArgumentParser(description="Fitted stem bridge; research-only")
    sub = parser.add_subparsers(dest="action", required=True)
    fit = sub.add_parser("fit")
    fit.add_argument("--train", type=Path, required=True)
    fit.add_argument("--train-sha256", required=True)
    fit.add_argument("--alpha", type=float, default=0.05)
    fit.add_argument("--output", type=Path, required=True)
    pre = sub.add_parser("predict")
    pre.add_argument("--fit", type=Path, required=True)
    pre.add_argument("--fit-sha256", required=True)
    pre.add_argument("--future-inputs", type=Path, required=True)
    pre.add_argument("--future-inputs-sha256", required=True)
    pre.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "fit":
        inputs, digest = load_pinned_jsonl(args.train, args.train_sha256)
        write_new(args.output, train(inputs, digest, alpha=args.alpha))
    else:
        raw = load_pinned_document(args.fit, args.fit_sha256)
        inputs, digest = load_pinned_jsonl(args.future_inputs, args.future_inputs_sha256)
        write_new(args.output, predict(raw, inputs, args.fit_sha256, digest))




if __name__ == "__main__":
    main()
