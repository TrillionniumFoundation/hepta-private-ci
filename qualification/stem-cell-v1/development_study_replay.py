"""Recompute sealed Cell predictions from tensors without the fitter/runtime.

This checks numerical correspondence, not authenticity of Encoder observations,
causal quality, independent execution, signed CAS or production authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from development_study_data import StudyConfig, digest, phase, public_input, read_dataset, write_once
from study import (reject_duplicate_evidence_fields, reject_nonstandard_evidence_number,
                   parse_finite_evidence_float)

ARMS = {"frozen", "continued", "wider", "more_data", "split"}
TRAIN = {"base", "adapt", "extra", "calibration"}
MAX_ERROR = 1e-5  # Fixed before any public model execution, never tuned on held-out scores.


def read_bytes(path, maximum):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= maximum:
        raise ValueError("invalid bounded replay artifact")
    with path.open("rb") as handle:
        raw = handle.read(maximum + 1)
    if not 0 < len(raw) <= maximum:
        raise ValueError("replay artifact changed size")
    return raw


def record(path, maximum=1_048_576):
    raw = read_bytes(path, maximum)
    return json.loads(raw, object_pairs_hook=reject_duplicate_evidence_fields,
        parse_constant=reject_nonstandard_evidence_number, parse_float=parse_finite_evidence_float), hashlib.sha256(raw).hexdigest()


def verify_checkpoint_files(folder, sealed, selection):
    """Bind actual byte buffers once; the same buffers feed safetensors parsing."""
    folder = Path(folder)
    if (folder / "FAILED.json").exists():
        raise ValueError("failed run has no successful replay")
    checkpoints = selection["checkpoints"]
    if (type(checkpoints) is not dict or not ARMS - {"split"} <= set(checkpoints)
            or not set(checkpoints) <= ARMS or selection["selected_arm"] not in checkpoints):
        raise ValueError("invalid checkpoint arm census")
    buffers = {}
    for name, info in checkpoints.items():
        raw = read_bytes(folder / f"{name}.safetensors", 33_554_432)
        if hashlib.sha256(raw).hexdigest() != info["sha256"]:
            raise ValueError("sealed checkpoint bytes changed")
        buffers[name] = raw
    normalizer = read_bytes(folder / "normalizer.safetensors", 1_048_576)
    if hashlib.sha256(normalizer).hexdigest() != sealed.get("normalizer_sha256"):
        raise ValueError("normalizer is changed or not bound by this run")
    return buffers, normalizer


def tensor_forward(tensors, x, cells, classes):
    """Independent declared formula; imports neither RoutedBank nor BasisCellHeads."""
    import torch
    required = {"bank.base.weight", "bank.base.bias", "bank.basis", "bank.gate_axes",
                "bank.coefficients", "bank.gates"}
    if not required <= set(tensors) or set(tensors) - required not in (set(), {"centers"}):
        raise ValueError("unexpected checkpoint tensor inventory")
    if any(v.dtype != torch.float32 or not torch.isfinite(v).all() for v in tensors.values()):
        raise ValueError("invalid checkpoint dtype/value")
    width = x.shape[1]
    coefficients, gates = tensors["bank.coefficients"], tensors["bank.gates"]
    if coefficients.ndim != 2:
        raise ValueError("invalid Cell coefficient shape")
    rank = coefficients.shape[1]
    shapes = {"bank.base.weight": (classes, width), "bank.base.bias": (classes,),
              "bank.basis": (rank, width, classes), "bank.gate_axes": (rank, width),
              "bank.coefficients": (cells, rank), "bank.gates": (cells, rank + 1)}
    if (cells not in (1, 2) or not 1 <= rank <= 64
            or any(tuple(tensors[k].shape) != shape for k, shape in shapes.items())):
        raise ValueError("checkpoint shape mismatch")
    if "centers" in tensors:
        centers = tensors["centers"]
        if centers.shape != (2, width) or cells != 2:
            raise ValueError("invalid router centers")
        indices = (x[:, None, :] - centers[None, :, :]).square().sum(-1).argmin(-1)
    else:
        if cells != 1:
            raise ValueError("two Cells require a bound router")
        indices = torch.zeros(len(x), dtype=torch.long)
    gate = gates[indices]
    activation = torch.sigmoid((x @ tensors["bank.gate_axes"].T * gate[:, :-1]).sum(1) + gate[:, -1])
    residual = torch.einsum("bd,rdk,br->bk", x, tensors["bank.basis"], coefficients[indices])
    output = torch.nn.functional.linear(x, tensors["bank.base.weight"], tensors["bank.base.bias"]) + activation[:, None] * residual
    if not torch.isfinite(output).all():
        raise ValueError("nonfinite independently replayed logits")
    return output



def verify_serving_probe(folder, run, selection, config):
    """Check recorded probe identity/count consistency, not physical attestation."""
    if run["schema"] != "hepta.stem.structural-run.v3":
        return None
    probe, probe_sha = record(Path(folder) / "serving-probe.json", 8_388_608)
    fields = {"schema": "hepta.stem.trained-serving-probe.v1",
              "selected_arm": selection["selected_arm"],
              "selection_sha256": run["sealed"]["selection_sha256"],
              "head_sha256": selection["checkpoints"][selection["selected_arm"]]["sha256"],
              "normalizer_sha256": run["sealed"]["normalizer_sha256"],
              "encoder_digest": run["snapshot_sha256"], "generation": config.generation,
              "argmax_reversals": 0, "production_authorized": False,
              "quality_or_resource_superiority_established": False, "native_worker_executed": False}
    if (probe_sha != run.get("serving_probe_sha256")
            or any(type(probe.get(k)) is not type(v) or probe[k] != v for k, v in fields.items())
            or (run.get("real_weights_executed") is True and probe.get("simulated_encoder") is not False)):
        raise ValueError("serving probe identity differs from sealed run")
    import math
    max_error = probe.get("max_abs_logit_error")
    if type(max_error) not in (int, float) or not math.isfinite(max_error) or not 0 <= max_error <= 1e-4:
        raise ValueError("invalid serving output-parity error")
    trials = probe.get("trials")
    if type(trials) is not list or len(trials) != 9:
        raise ValueError("incomplete serving timing-repeat census")
    seen, requests, errors = set(), set(), []
    for trial in trials:
        key = (trial["repeat"], trial["path"])
        if (type(trial["repeat"]) is not int or trial["repeat"] not in range(3)
                or trial["path"] not in {"serial_no_cache", "serial_reuse", "batch_reuse"}
                or key in seen):
            raise ValueError("duplicate or unknown serving timing trial")
        seen.add(key)
        error = trial.get("max_abs_logit_error")
        if type(error) not in (int, float) or not math.isfinite(error) or not 0 <= error <= 1e-4:
            raise ValueError("invalid serving trial parity")
        errors.append(error)
        batches = trial["batches"]
        if type(batches) is not list or not 1 <= len(batches) <= 256:
            raise ValueError("invalid serving batch census")
        for batch in batches:
            if (any(type(batch.get(k)) is not int or batch[k] < 0 for k in
                    ("members", "backend_calls", "encoded_rows", "prior_cache_hits", "cpu_ns", "wall_ns"))
                    or not 1 <= batch["members"] <= (32 if trial["path"] == "batch_reuse" else 1)
                    or batch["backend_calls"] > 1 or batch["encoded_rows"] > batch["members"]
                    or batch["prior_cache_hits"] > batch["members"]):
                raise ValueError("invalid serving member accounting")
        expected = {"logical_requests": sum(b["members"] for b in batches),
                    "head_evaluated_rows": sum(b["members"] for b in batches),
                    "backend_calls": sum(b["backend_calls"] for b in batches),
                    "encoded_rows": sum(b["encoded_rows"] for b in batches)}
        if (any(type(trial.get(k)) is not int or trial[k] != v for k, v in expected.items())
                or any(type(trial.get(k)) is not int or trial[k] < sum(b[k] for b in batches)
                       for k in ("cpu_ns", "wall_ns"))):
            raise ValueError("serving totals differ from recorded batch work")
        requests.add(trial["logical_requests"])
    if len(requests) != 1 or not 1 <= next(iter(requests)) <= 256 or max(errors) != max_error:
        raise ValueError("unpaired serving request census")
    return {"sha256": probe_sha, "trials": 9, "logical_requests_per_trial": next(iter(requests)),
            "identity_and_counts_consistent": True, "physical_measurements_attested": False}


def replay(folder, dataset):
    import torch
    from safetensors.torch import load
    folder = Path(folder)
    run, run_sha = record(folder / "run.json")
    selection, selection_sha = record(folder / "selection.json")
    predictions, predictions_sha = record(folder / "predictions.json", 67_108_864)
    if (run.get("schema") not in {"hepta.stem.structural-run.v2", "hepta.stem.structural-run.v3"}
            or selection.get("schema") != "hepta.stem.structural-selection.v2"):
        raise ValueError("historical unbound schemas cannot be reinterpreted as replay-qualified")
    sealed = run["sealed"]
    if (selection_sha != sealed["selection_sha256"] or predictions_sha != sealed["predictions_sha256"]):
        raise ValueError("sealed records changed")
    buffers, normalizer_bytes = verify_checkpoint_files(folder, sealed, selection)
    config = StudyConfig(**selection["config"]).validate()
    if not config.seal_replay:
        raise ValueError("run did not opt in to scoped feature replay")
    probe_replay = verify_serving_probe(folder, run, selection, config)
    rows = read_dataset(dataset, run["dataset_sha256"], config)
    inputs, inputs_sha = record(folder / "replay-inputs.json", 8_388_608)
    feature_bytes = read_bytes(folder / "replay-features.safetensors", 16_777_216)
    if (inputs_sha != sealed["replay"]["inputs_sha256"]
            or hashlib.sha256(feature_bytes).hexdigest() != sealed["replay"]["features_sha256"]):
        raise ValueError("sealed feature/input correspondence changed")
    expected = [{"sample_id": r["sample_id"], "source_group": r["source_group"], "phase": phase(r),
                 "input_fingerprint": digest(public_input(r))} for r in rows]
    if inputs != expected:
        raise ValueError("feature row order differs from dataset")
    stored, normalizer = load(feature_bytes), load(normalizer_bytes)
    if set(stored) != {"features"} or set(normalizer) != {"mean", "scale"}:
        raise ValueError("unexpected replay tensor fields")
    features = stored["features"]
    if (features.ndim != 2 or features.shape[0] != len(rows) or not 1 <= features.shape[1] <= 512
            or any(v.dtype != torch.float32 or not torch.isfinite(v).all()
                   for v in [features, *normalizer.values()])
            or any(v.shape != (features.shape[1],) for v in normalizer.values())
            or not (normalizer["scale"] > 0).all()):
        raise ValueError("invalid feature/normalizer tensor shape or value")
    base = features[[i for i, r in enumerate(inputs) if r["phase"] == "base"]]
    for key, value in (("mean", base.mean(0)), ("scale", base.std(0, unbiased=False).clamp_min(1e-6))):
        if not torch.allclose(value, normalizer[key], atol=1e-6, rtol=1e-6):
            raise ValueError("normalizer not derived from base training only")
    normalized = (features - normalizer["mean"]) / normalizer["scale"]
    if not torch.isfinite(normalized).all():
        raise ValueError("nonfinite normalized replay features")
    decoded = {name: load(raw) for name, raw in buffers.items()}
    from development_selection_replay import verify_selection
    with torch.no_grad():
        selection_replay = verify_selection(selection, decoded, normalized, inputs,
            torch.tensor([r["label"] for r in rows if phase(r) == "calibration"], dtype=torch.long),
            config, tensor_forward)
    evaluated = [i for i, r in enumerate(inputs) if r["phase"] not in TRAIN]
    x = normalized[evaluated]
    if type(predictions) is not list or len(predictions) != len(evaluated) * len(buffers):
        raise ValueError("incomplete replay prediction census")
    by_key = {}
    for p in predictions:
        if type(p) is not dict or set(p) != {"sample_id", "arm", "input_fingerprint", "logits"}:
            raise ValueError("invalid replay prediction record")
        key = (p["arm"], p["sample_id"])
        if key in by_key:
            raise ValueError("duplicate replay prediction")
        by_key[key] = p
    error = 0.0
    with torch.no_grad():
        for name, raw in buffers.items():
            info = selection["checkpoints"][name]
            predicted = tensor_forward(decoded[name], x, len(info["cell_ids"]), config.classes)
            for index, logits in zip(evaluated, predicted):
                p = by_key.pop((name, inputs[index]["sample_id"]))
                if p["input_fingerprint"] != inputs[index]["input_fingerprint"]:
                    raise ValueError("replay input fingerprint mismatch")
                vector = torch.tensor(p["logits"], dtype=torch.float32)
                if vector.shape != (config.classes,) or not torch.isfinite(vector).all():
                    raise ValueError("invalid replay logits")
                delta = float((logits - vector).abs().max())
                if delta > MAX_ERROR or logits.argmax() != vector.argmax():
                    raise ValueError("sealed logits do not reproduce from checkpoint")
                error = max(error, delta)
    if by_key:
        raise ValueError("unmatched replay predictions")
    return {"schema": "hepta.stem.structural-replay.v2", "run_sha256": run_sha,
        "prediction_rows": len(predictions), "checkpoint_count": len(buffers), "max_abs_logit_error": error,
        "argmax_reversals": 0, "time_basis": config.time_basis,
        "selection_replay": selection_replay, "serving_probe": probe_replay,
        "encoder_execution_independently_attested": False, "production_authorized": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    write_once(args.output, replay(args.run, args.dataset))
