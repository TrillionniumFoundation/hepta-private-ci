"""Offline real-weight entrypoint for shared encoding and structural learning.

Uses the existing strict FrozenLocalHfBackend; no model download, pickle loader,
synthetic fallback, parallel runtime or production promotion is introduced.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import time

import torch

from development_study_data import (StudyConfig, canonical, digest, phase,
                                    public_input, read_dataset, write_once)
from development_study_fit import fit_candidates, select_candidate
from model_runner import snapshot_digest
from shared_encoder_batch import FeatureRequest, FrozenLocalHfBackend, SharedStemEngine


TRAIN_PHASES = {"base", "adapt", "extra", "calibration"}


def prepare_views(rows):
    """The fitter has no argument containing held-out/future/OOD truth."""
    inputs = tuple({"sample_id": r["sample_id"], "source_group": r["source_group"],
                    "phase": phase(r), "input_fingerprint": digest(public_input(r))} for r in rows)
    training = {r["sample_id"]: r["label"] for r in rows if phase(r) in TRAIN_PHASES}
    return inputs, training


def fit_and_seal(inputs, training_labels, features, config, output):
    """Write calibration selection/checkpoints BEFORE sealed evaluation logits."""
    from development_tensors import checked_tensor

    config.validate()
    checked_tensor(features, 2, "study features")
    if (len(features) != len(inputs) or not 1 <= features.shape[1] <= 512
            or len({r["sample_id"] for r in inputs}) != len(inputs)
            or set(training_labels) != {r["sample_id"] for r in inputs if r["phase"] in TRAIN_PHASES}):
        raise ValueError("features or training-label boundary mismatch")
    if any(type(v) is not int or not 0 <= v < config.classes for v in training_labels.values()):
        raise ValueError("invalid training truth")
    blocks = {}
    for p in ("base", "adapt", "extra", "calibration"):
        indices = [i for i, r in enumerate(inputs) if r["phase"] == p]
        if len(indices) < 2:
            raise ValueError("insufficient training/calibration phase")
        blocks[p] = (features[indices].clone(), torch.tensor(
            [training_labels[inputs[i]["sample_id"]] for i in indices], dtype=torch.long))
    output = Path(output)
    # Caller creates the experiment directory once. Existing evidence is never replaced.
    reserved = [output / p for p in ("selection.json", "predictions.json", "normalizer.safetensors")]
    if config.seal_replay:
        reserved.extend(output / p for p in ("replay-features.safetensors", "replay-inputs.json"))
    if any(p.exists() for p in reserved):
        raise FileExistsError("immutable experiment already contains output")
    with torch.random.fork_rng(devices=[]):
        models, costs, mean, scale = fit_candidates(*blocks["base"], *blocks["adapt"],
                                                   *blocks["extra"], config)
    calibration_x = (blocks["calibration"][0] - mean) / scale
    with torch.no_grad():
        calibration_logits = {n: m(calibration_x) for n, m in models.items()}
    selection = select_candidate(calibration_logits, blocks["calibration"][1],
        [r["source_group"] for r in inputs if r["phase"] == "calibration"], costs["adaptation"], config)
    inventory = {}
    for name, model in models.items():
        path = output / f"{name}.safetensors"
        with path.open("xb") as handle:
            # Create-only checkpoint bytes, not a signed Artifact CAS publication.
            from safetensors.torch import save
            handle.write(save({k: v.detach().contiguous() for k, v in model.state_dict().items()}))
        inventory[name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                           "generation": model.bank.generation, "cell_ids": model.bank.cell_ids}
    with (output / "normalizer.safetensors").open("xb") as handle:
        from safetensors.torch import save
        handle.write(save({"mean": mean, "scale": scale}))
    selection.update({"schema": "hepta.stem.structural-selection.v2", "config": asdict(config),
                      "training_input_digest": digest([r for r in inputs if r["phase"] in TRAIN_PHASES]),
                      "costs": costs, "checkpoints": inventory})
    selection_sha = write_once(output / "selection.json", selection)
    replay = {}
    if config.seal_replay:
        # Explicit opt-in: these are scoped derived features, not public by default.
        with (output / "replay-features.safetensors").open("xb") as handle:
            handle.write(save({"features": features.detach().contiguous()}))
        replay = {"features_sha256": hashlib.sha256((output / "replay-features.safetensors").read_bytes()).hexdigest(),
                  "inputs_sha256": write_once(output / "replay-inputs.json", inputs)}
    evaluated = [i for i, r in enumerate(inputs) if r["phase"] not in TRAIN_PHASES]
    if not evaluated:
        raise ValueError("no held-out evaluation input")
    x = (features[evaluated] - mean) / scale
    predictions = []
    with torch.no_grad():
        for name, model in models.items():
            start = time.perf_counter_ns()
            logits = model(x)
            wall_ns = time.perf_counter_ns() - start
            if not torch.isfinite(logits).all():
                raise ValueError("nonfinite prediction")
            for idx, vector in zip(evaluated, logits.tolist()):
                predictions.append({"sample_id": inputs[idx]["sample_id"], "arm": name,
                    "input_fingerprint": inputs[idx]["input_fingerprint"], "logits": vector})
            selection["costs"]["adaptation"][name]["evaluation_batch_wall_ns"] = wall_ns
    predictions_sha = write_once(output / "predictions.json", predictions)
    return {"selection_sha256": selection_sha, "predictions_sha256": predictions_sha,
            "normalizer_sha256": hashlib.sha256((output / "normalizer.safetensors").read_bytes()).hexdigest(),
            "replay": replay,
            "evaluation_wall_ns": {n: selection["costs"]["adaptation"][n]["evaluation_batch_wall_ns"]
                                    for n in models}, "production_authorized": False}


def feature_requests(rows, backend, config, frontier):
    scope_digest = digest(rows[0]["scope"])
    return tuple(FeatureRequest(r["sample_id"], "structural-parent", scope_digest,
        config.generation, frontier, backend.encoder_digest, backend.preprocessor_digest,
        backend.runtime_digest, hashlib.sha256(canonical(public_input(r))).hexdigest(),
        canonical(public_input(r)).decode()) for r in rows)


def benchmark_reuse(requests, backend, config):
    """Same resident Encoder: serial/no-cache vs shared batch/coalescing.

    This does NOT measure duplicated model residency, an entire Worker, GPU,
    process-isolated per-arm RSS, or independently attested target-host cost.
    """
    from dataclasses import replace
    selected = requests[:config.benchmark_inputs]
    workload = tuple(replace(r, request_id=f"bench-{j}-{i}", cell_id=f"cell-{j}")
                     for j in range(config.benchmark_replicas) for i, r in enumerate(selected))
    results, saved = {}, {}
    # Deterministic randomized order, with all actual preparation charged elsewhere.
    import random
    order = ["serial_no_cache", "shared_batch"]
    random.Random(config.seed).shuffle(order)
    for arm in order:
        engine = SharedStemEngine(backend, max_cache_bytes=64 * 1024 * 1024 if arm == "shared_batch" else 0)
        width = 32 if arm == "shared_batch" else 1
        receipts, vectors = [], []
        start_cpu, start_wall = time.process_time_ns(), time.perf_counter_ns()
        for offset in range(0, len(workload), width):
            receipt, values = engine.run(workload[offset:offset+width], return_features=True)
            receipts.append(receipt)
            vectors.extend(values)
        results[arm] = {"cpu_ns": time.process_time_ns() - start_cpu,
            "wall_ns": time.perf_counter_ns() - start_wall,
            "backend_calls": sum(x.backend_calls for x in receipts),
            "encoded_rows": sum(sum(x.backend_batch_widths) for x in receipts),
            "logical_requests": len(workload), "cache_bytes": engine.cache.size_bytes}
        saved[arm] = torch.tensor([v.values for v in vectors])
    delta = (saved[order[0]] - saved[order[1]]).abs().max().item()
    if delta > 1e-4:
        raise ValueError("serial/shared feature parity exceeds fixed tolerance")
    return {"arms": results, "order": order, "max_abs_feature_error": delta,
            "simulated_encoder": bool(getattr(backend, "simulated", True)),
            "quality_or_production_superiority_established": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--dataset-sha256", required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--snapshot-sha256", required=True)
    parser.add_argument("--config", type=Path, required=True, help="one strict JSONL StudyConfig object")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--revocation-frontier-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from study import load_jsonl
    configurations = list(load_jsonl(args.config))
    if len(configurations) != 1:
        raise ValueError("one bounded configuration object required")
    config = StudyConfig(**configurations[0]).validate()
    if config.origin == "synthetic_fixture":
        raise ValueError("real-weight CLI cannot qualify synthetic input data")
    source = subprocess.check_output(["git", "-C", str(args.source_root), "rev-parse", "HEAD"], text=True).strip()
    if (source != args.expected_source_sha or len(source) != 40
            or any(c not in "0123456789abcdef" for c in source)):
        raise ValueError("unexpected source commit")
    import model_runner, study
    for module in (model_runner, study):
        if Path(module.__file__).resolve().parent != (args.source_root / "qualification/stem-cell-v1").resolve():
            raise ValueError("external module shadowing is not a source-qualified execution")
    if Path(__file__).resolve() != (args.source_root / "qualification/stem-cell-v1/development_study.py").resolve():
        raise ValueError("executed script is outside the checked source tree")
    status = subprocess.check_output(["git", "-C", str(args.source_root), "status", "--porcelain",
        "--untracked-files=all", "--", "qualification/stem-cell-v1"], text=True)
    if status:
        raise ValueError("experiment source tree is not clean")
    if args.output.resolve().is_relative_to(args.source_root.resolve()):
        raise ValueError("experiment output must be outside source tree")
    rows = read_dataset(args.dataset, args.dataset_sha256, config)
    if snapshot_digest(args.snapshot) != args.snapshot_sha256:
        raise ValueError("unreviewed snapshot bytes")
    args.output.mkdir(parents=True, exist_ok=False)
    write_once(args.output / "plan.json", {"source_sha": source, "dataset_sha256": args.dataset_sha256,
        "snapshot_sha256": args.snapshot_sha256, "config": asdict(config), "config_sha256": hashlib.sha256(args.config.read_bytes()).hexdigest(),
        "production_authorized": False})
    start_cpu, start_wall = time.process_time_ns(), time.perf_counter_ns()
    try:
        versions = {n: importlib.metadata.version(n) for n in ("torch", "transformers", "safetensors")}
        runtime = digest({"versions": versions, "source_sha": source, "platform": platform.platform()})
        preprocess = digest({"input": "canonical-state-question-ordered-options-v1", "max_tokens": config.max_tokens})
        torch.set_num_threads(4)
        torch.use_deterministic_algorithms(True)
        backend = FrozenLocalHfBackend(args.snapshot, expected_snapshot_digest=args.snapshot_sha256,
            preprocessor_digest=preprocess, runtime_digest=runtime, max_tokens=config.max_tokens, device="cpu")
        load_cpu, load_wall = time.process_time_ns() - start_cpu, time.perf_counter_ns() - start_wall
        requests = feature_requests(rows, backend, config, args.revocation_frontier_sha256)
        benchmark = benchmark_reuse(requests, backend, config)
        engine = SharedStemEngine(backend)
        features, observations = [], []
        for offset in range(0, len(requests), 32):
            receipt, values = engine.run(requests[offset:offset+32], return_features=True)
            if any(len(v.values) > 512 for v in values):
                raise ValueError("explicit audited projection required; no truncation")
            features.extend(values)
            observations.append(receipt)
        # Recheck physical tensors AND source/data bytes before publishing trained evidence.
        from hf_joint_decision_runner import verify_loaded_safetensors
        verify_loaded_safetensors(torch, backend.model, args.snapshot)
        if snapshot_digest(args.snapshot) != args.snapshot_sha256:
            raise ValueError("snapshot changed during execution")
        inputs, training = prepare_views(rows)
        sealed = fit_and_seal(inputs, training, torch.tensor([f.values for f in features]), config, args.output)
        verify_loaded_safetensors(torch, backend.model, args.snapshot)
        if snapshot_digest(args.snapshot) != args.snapshot_sha256:
            raise ValueError("snapshot changed during Head training")
        if hashlib.sha256(args.dataset.read_bytes()).hexdigest() != args.dataset_sha256:
            raise ValueError("dataset changed during experiment")
        import resource
        report = {"schema": "hepta.stem.structural-run.v2", "source_sha": source,
            "dataset_sha256": args.dataset_sha256, "snapshot_sha256": args.snapshot_sha256,
            "sealed": sealed, "benchmark": benchmark, "load_cpu_ns": load_cpu, "load_wall_ns": load_wall,
            "training_feature_backend_calls": sum(o.backend_calls for o in observations),
            "encoder_parameters": sum(p.numel() for p in backend.model.parameters()),
            "versions": versions, "cpu_ns": time.process_time_ns() - start_cpu,
            "wall_ns": time.perf_counter_ns() - start_wall,
            "linux_process_lifetime_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
                if platform.system() == "Linux" else None,
            "real_weights_executed": True, "origin_independently_verified": False,
            "time_basis": config.time_basis, "genuine_future_windows_authenticated": False,
            "encoder_loading": backend.verified_loading,
            "encoder_materialization": backend.verified_materialization,
            "production_authorized": False}
        write_once(args.output / "run.json", report)
    except Exception as error:
        write_once(args.output / "FAILED.json", {"error_type": type(error).__name__, "message": str(error),
                   "cpu_ns": time.process_time_ns() - start_cpu, "wall_ns": time.perf_counter_ns() - start_wall,
                   "production_authorized": False})
        raise


if __name__ == "__main__":
    main()
