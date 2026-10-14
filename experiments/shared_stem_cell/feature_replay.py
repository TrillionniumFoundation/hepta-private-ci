"""Offline frozen-feature snapshots and original Head replay, not a serving cache.

No Encoder/tokenizer is instantiated on replay. An externally supplied producer
report digest anchors the manifest, row order, scope, representation and bytes.
Hashes do not attest that an Encoder computed the features correctly. Features
are derived source data, NOT anonymous; export is opt-in and preserves scope.
No labels are stored in the snapshot. The separate original dataset supplies
train labels to the unchanged fitter; holdout labels enter post-seal scoring.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import os
import platform

import torch
from safetensors.torch import load, save

from experiments.shared_stem_cell import execution as e
from experiments.shared_stem_cell.head_artifacts import _digest, _path, _read, _sync_directory

SCHEMA = "hepta.offline-frozen-features.v1"
MAX_TENSOR = 64 * 1024**2
MAX_INDEX = 8 * 1024**2
KINDS = ("linear", "gated", "low_rank", "sparse_expert")
# Same declared diagnostic tolerances as the existing grouped training profile.
ATOL, RTOL = 2e-5, 2e-4


def binding(config, width, producer_source_sha256):
    """The original Head feature profile, plus complete producer-plan/source identity."""
    stem = e.sha(e.canonical(config["model"]))
    _digest(producer_source_sha256)
    _digest(config["dataset"]["sha256"])
    return {"manifest_sha256": e.sha(e.canonical(config)), "stem_sha256": stem,
        "dataset_sha256": config["dataset"]["sha256"], "producer_source_sha256": producer_source_sha256,
        "feature_profile_sha256": e.sha(e.canonical({"width": width,
            "representation": "masked_mean_float32", "model": stem,
            "maximum_tokens": config.get("maximum_tokens", 512)}))}


def row_index(cases):
    """Preserve exact row order, Cell/fold/source identities; never include labels/text."""
    if not 4 <= len(cases) <= 16384 or len({c.case_id for c in cases}) != len(cases):
        raise e.InputError("bounded unique frozen-feature cases required")
    if len({c.scope for c in cases}) != 1:
        raise e.InputError("frozen features cannot cross scopes")
    rows = [{"case_id": c.case_id, "group": c.group, "split": c.split,
             "cell": c.cell, "scope": c.scope, "observed_at": c.observed_at,
             "input_sha256": c.input_digest} for c in cases]
    if len(e.canonical(rows)) > MAX_INDEX - 65536:
        raise e.InputError("feature row-index byte budget")
    return rows


def checked_shape(shape):
    if (not isinstance(shape, list) or len(shape) != 2
            or any(type(v) is not int for v in shape)
            or not 4 <= shape[0] <= 16384 or not 1 <= shape[1] <= 8192
            or shape[0] * shape[1] * 4 > MAX_TENSOR):
        raise e.InputError("bounded matrix feature shape required")


def export_features(directory, x, cases, config, *, producer_source_sha256, simulated):
    """Publish features then the complete manifest LAST. No model or gold arguments."""
    rows = row_index(cases)
    if (type(simulated) is not bool or not isinstance(x, torch.Tensor) or x.ndim != 2
            or x.dtype != torch.float32 or x.device.type != "cpu" or len(x) != len(rows)):
        raise e.InputError("CPU float32 frozen-feature matrix required")
    checked_shape(list(x.shape))
    if not bool(torch.isfinite(x).all()):
        raise e.InputError("nonfinite frozen features")
    identity = binding(config, x.shape[1], producer_source_sha256)
    directory = _path(directory)
    if directory.exists():
        raise e.InputError("feature snapshot cannot overwrite an existing directory")
    # Own storage so future in-process changes cannot alter the serialized bytes.
    owned = x.detach().clone().contiguous()
    raw = save({"features": owned})
    if len(raw) > MAX_TENSOR + 65536:
        raise e.InputError("feature file byte budget")
    manifest = {"schema": SCHEMA, "binding": identity, "rows": rows,
        "shape": list(x.shape), "dtype": "float32", "tensor_bytes": owned.numel() * 4,
        "file_bytes": len(raw), "file_sha256": e.sha(raw), "tensor_sha256": e.tensor_digest(owned),
        "simulated_encoder": simulated, "contains_labels": False, "production_accepted": False}
    directory.mkdir(parents=True, exist_ok=False)
    with (directory / "features.safetensors").open("xb") as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    digest = e.write_once(directory / "manifest.json", manifest)
    _sync_directory(directory)
    _sync_directory(directory.parent)
    return {"manifest_sha256": digest, "relative_path": "frozen-features",
            "shape": list(x.shape), "tensor_bytes": owned.numel() * 4, "simulated_encoder": simulated}


def load_features(directory, digest, cases, config, *, producer_source_sha256):
    """Reopen exactly one bounded, source-bound tensor using the verified byte buffer."""
    _digest(digest)
    directory = _path(directory)
    if not directory.is_dir() or {p.name for p in directory.iterdir()} != {"manifest.json", "features.safetensors"}:
        raise e.InputError("complete closed frozen-feature snapshot required")
    raw_manifest = _read(directory / "manifest.json", MAX_INDEX)
    if e.sha(raw_manifest) != digest:
        raise e.InputError("external feature manifest hash mismatch")
    m = e.decode(raw_manifest)
    keys = {"schema", "binding", "rows", "shape", "dtype", "tensor_bytes", "file_bytes", "file_sha256",
            "tensor_sha256", "simulated_encoder", "contains_labels", "production_accepted"}
    if (not isinstance(m, dict) or set(m) != keys or m["schema"] != SCHEMA
            or m["contains_labels"] is not False or m["production_accepted"] is not False
            or type(m["simulated_encoder"]) is not bool or m["dtype"] != "float32"):
        raise e.InputError("invalid frozen-feature schema/claims")
    checked_shape(m["shape"])
    if (m["rows"] != row_index(cases) or m["shape"][0] != len(cases)
            or m["binding"] != binding(config, m["shape"][1], producer_source_sha256)
            or type(m["tensor_bytes"]) is not int or m["tensor_bytes"] != 4 * m["shape"][0] * m["shape"][1]
            or type(m["file_bytes"]) is not int or not 1 <= m["file_bytes"] <= MAX_TENSOR + 65536):
        raise e.InputError("frozen-feature row/producer/profile binding drift")
    raw = _read(directory / "features.safetensors", MAX_TENSOR + 65536)
    if len(raw) != m["file_bytes"] or e.sha(raw) != _digest(m["file_sha256"]):
        raise e.InputError("frozen-feature bytes changed")
    tensors = load(raw)
    if set(tensors) != {"features"}:
        raise e.InputError("unexpected frozen-feature tensors")
    x = tensors["features"]
    if (list(x.shape) != m["shape"] or x.dtype != torch.float32 or not bool(torch.isfinite(x).all())
            or e.tensor_digest(x) != _digest(m["tensor_sha256"])):
        raise e.InputError("frozen-feature tensor identity mismatch")
    # Consistent owned Torch storage, not a mutable memory-mapped file view.
    return x.clone().contiguous(), m


def replay(manifest_path, producer, report_sha256, output, *, fitting_backend="scalar"):
    """Repeat only the four original Head fits, not controls, generators or new tuning."""
    if fitting_backend not in {"scalar", "grouped"}:
        raise e.InputError("explicit scalar/grouped replay backend required")
    config_raw = _read(manifest_path, MAX_INDEX)
    config = e.decode(config_raw)
    report = e.decode(e.bound_file(producer / "report.json", _digest(report_sha256), MAX_INDEX))
    if config.get("schema") != "hepta.shared-stem-execution.v1" or e.sha(config_raw) != report["manifest_sha256"]:
        raise e.InputError("original producer plan required")
    data_part = Path(config["dataset"]["path"])
    if data_part.is_absolute() or ".." in data_part.parts:
        raise e.InputError("replay dataset must be staged under the manifest")
    data = _path(manifest_path.parent / data_part)
    cases, labels = e.dataset(data, config["dataset"]["sha256"], config["classes"],
                             config["cells"], config.get("temporal", False))
    receipt = report.get("frozen_features")
    if not isinstance(receipt, dict) or receipt.get("relative_path") != "frozen-features":
        raise e.InputError("producer has no complete frozen-feature export")
    with e.measured() as reopening:
        x, archive = load_features(producer / "frozen-features", receipt["manifest_sha256"], cases, config,
                                   producer_source_sha256=report["source_sha256"])
    if (receipt.get("shape") != archive["shape"] or receipt.get("tensor_bytes") != archive["tensor_bytes"]
            or receipt.get("simulated_encoder") is not archive["simulated_encoder"]
            or report["encoding"]["simulated_encoder"] is not archive["simulated_encoder"]):
        raise e.InputError("producer/feature provenance mismatch")
    reference = e.decode(e.bound_file(producer / "predictions.json", report["predictions_sha256"], MAX_TENSOR))
    output.mkdir(parents=True, exist_ok=False)
    e.write_once(output / "plan.json", {"producer_report_sha256": report_sha256,
        "feature_manifest_sha256": receipt["manifest_sha256"], "fitting_backend": fitting_backend,
        "atol": ATOL, "rtol": RTOL, "new_independent_evidence": False, "production_accepted": False})
    try:
        train_labels = {c.case_id: labels[c.case_id] for c in cases if c.split == "train"}
        rows, costs = [], {}
        with torch.random.fork_rng(devices=[]), e.measured() as fitting:
            for kind in KINDS:
                predictions, costs[kind] = e.head_trial(x, cases, train_labels, classes=config["classes"],
                    kind=kind, steps=config.get("steps", 40), seed=config.get("seed", 17),
                    fitting_backend=fitting_backend)
                rows.extend(predictions)
        seal = e.write_once(output / "predictions.json", {"predictions": rows})
        scores = e.evaluate_sealed(output / "predictions.json", seal, labels, cases, expected_arms=KINDS)
        e.evaluate_sealed(producer / "predictions.json", report["predictions_sha256"], labels, cases, expected_arms=KINDS)
        saved = e.decode(e.bound_file(output / "predictions.json", seal, MAX_TENSOR))
        ref = {(r["arm"], r["case_id"]): r for r in reference["predictions"]}
        comparisons = []
        for kind in KINDS:
            current = [r for r in saved["predictions"] if r["arm"] == kind]
            errors, changes, close = [], [], []
            for name in ("probabilities", "frozen_probabilities"):
                a = torch.tensor([r[name] for r in current]); b = torch.tensor([ref[kind, r["case_id"]][name] for r in current])
                errors.append(float((a-b).abs().max())); changes.append(int((a.argmax(-1) != b.argmax(-1)).sum()))
                close.append(bool(torch.allclose(a, b, atol=ATOL, rtol=RTOL)))
            streams = {c["cell"]: c["minibatch_sha256"] for c in costs[kind]}
            source_streams = {c["cell"]: c["minibatch_sha256"] for c in report["training"][kind]}
            comparisons.append({"arm": kind, "max_probability_error_learned_frozen": errors,
                "changed_argmax_learned_frozen": changes, "within_tolerance": all(close),
                "exact_minibatch_streams": streams == source_streams})
        e.bound_file(data, config["dataset"]["sha256"])
        result = {"mode": "sealed_feature_head_replay", "producer_report_sha256": report_sha256,
            "features_manifest_sha256": receipt["manifest_sha256"], "predictions_sha256": seal,
            "source_sha256": e.sha(Path(__file__).read_bytes()), "scores": scores, "comparison": comparisons,
            "feature_reopen": reopening, "whole_head_fitting": fitting, "training": costs,
            "encoder_forward_calls": 0, "encoder_loaded": False, "source_simulated_encoder": archive["simulated_encoder"],
            "runtime": {"torch": torch.__version__, "python": platform.python_version()},
            "independent_evaluation": False, "optimizer_resume": False, "controls_rerun": False,
            "production_accepted": False}
        e.write_once(output / "report.json", result)
        if any(not c["within_tolerance"] or not c["exact_minibatch_streams"]
               or any(c["changed_argmax_learned_frozen"]) for c in comparisons):
            raise e.InputError("replay mismatch retained; no repair or promotion")
        return result
    except Exception as error:
        e.write_once(output / "failure.json", {"error": type(error).__name__, "message": str(error),
                                               "production_accepted": False})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--producer", type=Path, required=True)
    parser.add_argument("--report-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backend", choices=("scalar", "grouped"), default="scalar")
    args = parser.parse_args()
    torch.set_num_threads(2)
    replay(args.manifest, args.producer, args.report_sha256, args.output, fitting_backend=args.backend)
