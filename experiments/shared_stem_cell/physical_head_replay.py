"""Model-free independent replay of actual four-arm frozen-feature Cell Heads.

Reads the existing pinned offline execution producer; it neither loads a model
nor imports Torch/Transformers or the original fitting and Head implementations.
Checks checkpoint bytes, manifests, source-bound frozen features, and recomputes
all saved trained/frozen probabilities with NumPy from saved safetensors.
This is arithmetical consistency, not independent model/source attestation or NDU.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
from safetensors.numpy import load

from experiments.shared_stem_cell.preflight_review import (
    ARMS, PreflightError, checked_bytes, digest, require, review,
)
from experiments.shared_stem_cell.wire import canonical, decode, sha, write_once

SCHEMA = "hepta.stem.physical-head-replay.v1"
# Matching the separately declared scalar/grouped Head numerical tolerances.
ATOL, RTOL = 2e-5, 2e-4
MAX_FEATURE_BYTES = 64 * 1024 * 1024
MAX_HEAD_BYTES = 2 * 1024 * 1024


def matrix(raw: bytes, key: str, *, expected_width: int | None = None) -> np.ndarray:
    try:
        values = load(raw)
    except Exception as exc:
        raise PreflightError("invalid safe tensor materialization") from exc
    require(set(values) == {key}, "frozen feature tensor key mismatch")
    x = values[key]
    require(x.dtype == np.float32 and x.ndim == 2 and 1 <= x.shape[1] <= 8192
            and 1 <= x.shape[0] <= 16384 and x.nbytes <= MAX_FEATURE_BYTES
            and bool(np.isfinite(x).all()), "invalid frozen feature tensor")
    if expected_width is not None:
        require(x.shape[1] == expected_width, "frozen feature width mismatch")
    return x


def tensor_set(raw: bytes, kind: str, *, width: int, classes: int) -> dict[str, np.ndarray]:
    try:
        t = load(raw)
    except Exception as exc:
        raise PreflightError("invalid trained Head safe tensor materialization") from exc
    expected = {"base.weight": (classes, width), "base.bias": (classes,)}
    if kind in ("gated", "low_rank"):
        expected.update({"down.weight": None, "down.bias": None, "up.weight": None})
        if kind == "gated":
            expected.update({"gate.weight": (classes, width), "gate.bias": (classes,)})
        down = t.get("down.weight")
        require(isinstance(down, np.ndarray) and down.ndim == 2
                and down.shape[1] == width and 1 <= down.shape[0] <= 256,
                "invalid low-rank Head width")
        rank = down.shape[0]
        expected.update({"down.weight": (rank, width), "down.bias": (rank,),
                         "up.weight": (classes, rank)})
    elif kind == "sparse_expert":
        expected.update({"router.weight": (2, width), "router.bias": (2,)})
        for index in (0, 1):
            expected.update({f"experts.{index}.weight": (classes, width),
                             f"experts.{index}.bias": (classes,)})
    else:
        require(kind == "linear", "unknown Head formula")
    require(set(t) == set(expected), "unexpected checkpoint tensors")
    for key, shape in expected.items():
        v = t[key]
        require(v.dtype == np.float32 and tuple(v.shape) == shape and bool(np.isfinite(v).all()),
                "invalid Head tensor shape, dtype or value")
    return t


def softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - logits.max(axis=-1, keepdims=True)
    values = np.exp(shifted)
    return values / values.sum(axis=-1, keepdims=True)


def predict(x: np.ndarray, t: dict[str, np.ndarray], kind: str) -> np.ndarray:
    # Deliberately independent of execution.Head.forward and the fitter.
    out = x @ t["base.weight"].T + t["base.bias"]
    if kind in ("gated", "low_rank"):
        down = np.tanh(x @ t["down.weight"].T + t["down.bias"])
        residual = down @ t["up.weight"].T
        if kind == "gated":
            g = x @ t["gate.weight"].T + t["gate.bias"]
            positive = np.exp(-np.abs(g))
            sigmoid = np.where(g >= 0, 1 / (1 + positive), positive / (1 + positive))
            residual *= sigmoid
        out += residual
    elif kind == "sparse_expert":
        router = x @ t["router.weight"].T + t["router.bias"]
        chosen = router.argmax(axis=-1)
        for i in (0, 1):
            active = chosen == i
            if bool(active.any()):
                out[active] += x[active] @ t[f"experts.{i}.weight"].T + t[f"experts.{i}.bias"]
    return softmax(out)


def _head(producer: Path, report: dict, kind: str, cost: dict,
          role: str, width: int, classes: int, stem: str, dataset_sha: str):
    receipt = cost["offline_head_artifacts"][role]
    rel = receipt["relative_path"]
    require(rel == f"cell-{cost['cell']}/{role}", "Head role or Cell path drift")
    base = producer / "heads" / kind / rel
    manifest_raw = checked_bytes(base / "manifest.json", receipt["manifest_sha256"])
    weights_raw = checked_bytes(base / "weights.safetensors", receipt["weights_sha256"])
    require(len(weights_raw) <= MAX_HEAD_BYTES, "oversized Head artifact")
    m = decode(manifest_raw)
    binding = m.get("binding")
    require(m.get("schema") == "hepta.offline-cell-head.v1"
            and m.get("production_accepted") is False
            and m.get("optimizer_state_included") is False
            and binding == receipt["binding"]
            and binding.get("logical_cell") == str(cost["cell"])
            and binding.get("dataset_sha256") == dataset_sha
            and binding.get("stem_sha256") == stem
            and m.get("weights_sha256") == sha(weights_raw)
            and m.get("weights_bytes") == len(weights_raw)
            and m.get("architecture", {}).get("kind") == kind
            and m["architecture"].get("width") == width
            and m["architecture"].get("classes") == classes,
            "Head manifest/binding/weight drift")
    expected = cost if role == "learned" else cost["frozen"]
    params = m.get("parameters")
    require(type(params) is dict and params == {
        "parameters": expected["parameters"], "parameter_bytes": expected["parameter_bytes"],
        "sha256": expected["sha256"]
    } and m.get("weights_sha256") == receipt["weights_sha256"]
       and m.get("parameters", {}).get("parameter_bytes") == receipt["parameter_bytes"]
       and type(params["parameters"]) is int and 1 <= params["parameters"] <= 262144,
            "Head parameter/weight accounting drift")
    tensors = tensor_set(weights_raw, kind, width=width, classes=classes)
    actual_count = sum(v.size for v in tensors.values())
    actual_tensor_hashes = {
        key: sha(canonical(["torch.float32", list(tensors[key].shape)])
                 + tensors[key].tobytes(order="C")) for key in sorted(tensors)
    }
    require(actual_count == params["parameters"] and actual_count * 4 == params["parameter_bytes"]
            and params["sha256"] == sha(canonical(actual_tensor_hashes)),
            "Head materialized parameters do not equal recorded count or digest")
    return tensors, sha(weights_raw)


def replay(manifest_path: Path, producer: Path, report_sha256: str) -> dict:
    preflight = review(manifest_path, producer, report_sha256)
    plan = decode(checked_bytes(manifest_path))
    report = decode(checked_bytes(producer / "report.json", report_sha256))
    data = [decode(line) for line in checked_bytes(
        manifest_path.parent / plan["dataset"]["path"], plan["dataset"]["sha256"]).splitlines()]
    features_receipt = report.get("frozen_features")
    require(type(features_receipt) is dict and digest(features_receipt.get("manifest_sha256"))
            and features_receipt.get("relative_path") == "frozen-features"
            and features_receipt.get("simulated_encoder") is False,
            "real frozen feature snapshot required")
    feature_root = producer / "frozen-features"
    manifest_raw = checked_bytes(feature_root / "manifest.json", features_receipt["manifest_sha256"])
    fm = decode(manifest_raw)
    raw = checked_bytes(feature_root / "features.safetensors", fm.get("file_sha256"))
    require(len(raw) <= MAX_FEATURE_BYTES + 65536
            and fm.get("schema") == "hepta.offline-frozen-features.v1"
            and fm.get("contains_labels") is False
            and fm.get("production_accepted") is False
            and fm.get("simulated_encoder") is False
            and type(fm.get("rows")) is list and len(fm["rows"]) == len(data)
            and fm.get("file_bytes") == len(raw), "invalid frozen feature binding")
    for idx, (source, index) in enumerate(zip(data, fm["rows"])):
        require(index == {"case_id": source["case_id"], "group": source["group"],
                          "split": source["split"], "cell": source["cell"],
                          "scope": source["scope"], "observed_at": source["observed_at"],
                          "input_sha256": sha(canonical([source["scope"], source["text"]]))},
                f"frozen feature row drift at {idx}")
    x = matrix(raw, "features")
    require(x.shape[0] == len(data) and fm.get("shape") == list(x.shape)
            and fm.get("tensor_bytes") == x.nbytes
            and fm.get("binding", {}).get("stem_sha256") == preflight["model_manifest_sha256"]
            and fm["binding"].get("dataset_sha256") == preflight["dataset_sha256"],
            "frozen feature content/binding changed")
    # tensor hash: same torch.float32 naming/canonical data as original source.
    require(fm.get("tensor_sha256") == sha(canonical(["torch.float32", list(x.shape)])
                                          + x.tobytes(order="C")), "frozen feature tensor drift")
    packet = decode(checked_bytes(producer / "predictions.json", report["predictions_sha256"]))
    predictions = {(p["arm"], p["case_id"]): p for p in packet["predictions"]}
    require(type(report.get("training")) is dict and set(report["training"]) == set(ARMS),
            "missing physical Head training receipts")
    stems = report["training"]
    stem = report["encoding"]["model_digest"]
    require(digest(stem) and stem == preflight["model_manifest_sha256"], "physical stem drift")
    active_cells = {r["cell"] for r in data}
    test_by_cell = {cell: [i for i, row in enumerate(data)
                           if row["cell"] == cell and row["split"] in ("holdout", "retention")]
                    for cell in active_cells}
    require(all(test_by_cell.values()), "all measured Cells need held-out evidence")
    drift, artifact_digests, parameters = [], {}, {}
    for kind in ARMS:
        costs = stems[kind]
        require(type(costs) is list and {c["cell"] for c in costs} == active_cells
                and len(costs) == len(active_cells), "missing/duplicated Cell Head")
        for cost in costs:
            require(type(cost.get("steps")) is int and cost["steps"] == plan.get("steps", 40)
                    and type(cost.get("minibatch_sha256")) is str
                    and digest(cost["minibatch_sha256"]), "unfair or unmeasured training")
            cell = cost["cell"]
            ids = test_by_cell[cell]
            for role, field in (("learned", "probabilities"),
                                ("frozen", "frozen_probabilities")):
                t, weights_sha = _head(producer, report, kind, cost, role, x.shape[1],
                                       plan["classes"], stem, preflight["dataset_sha256"])
                artifact_digests[f"{kind}/cell-{cell}/{role}"] = weights_sha
                actual = predict(x[ids], t, kind)
                for index, probabilities in zip(ids, actual):
                    key = (kind, data[index]["case_id"])
                    want = predictions[key][field]
                    diff = float(np.max(np.abs(probabilities - np.asarray(want, dtype=np.float32))))
                    tolerance = ATOL + RTOL * float(np.max(np.abs(want)))
                    require(math.isfinite(diff) and diff <= tolerance
                            and int(np.argmax(probabilities)) == int(np.argmax(want)),
                            "physical Head logits disagree with sealed prediction")
                    drift.append(diff)
            parameters.setdefault(kind, {})[str(cell)] = cost["parameters"]
    return {"schema": SCHEMA, "source_report_sha256": report_sha256,
            "model_manifest_sha256": preflight["model_manifest_sha256"],
            "dataset_sha256": preflight["dataset_sha256"],
            "frozen_feature_manifest_sha256": features_receipt["manifest_sha256"],
            "checked_prediction_vectors": len(drift),
            "physical_head_checkpoint_count": len(artifact_digests),
            "max_prediction_probability_abs_error": max(drift),
            "head_parameters_by_cell": parameters,
            "checkpoint_weights_sha256": artifact_digests,
            "independent_from_training_code": True,
            "real_encoder_invocation_reverified": False,
            "real_model_weight_attestation_verified": False,
            "independent_future_ndu_verified": False,
            "native_host_cell_scale_verified": False,
            "production_accepted": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--producer", type=Path, required=True)
    parser.add_argument("--report-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    answer = replay(args.manifest, args.producer, args.report_sha256)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_once(args.output, answer)


if __name__ == "__main__":
    main()
