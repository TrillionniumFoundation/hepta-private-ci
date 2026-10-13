"""Serve the saved selected Head through the existing shared Encoder engine.

This is a bounded research comparison, not another runtime/owner. Cold-per-trial
feature caches, one resident Encoder and one saved Head are used by all paths.
No labels, training, selection, signatures or production effects enter the probe.
"""
from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import random
import time

import torch
from safetensors.torch import load

from development_study_data import digest
from development_study_replay import record, tensor_forward, verify_checkpoint_files
from shared_encoder_batch import FeatureRequest, SharedStemEngine

PATHS = ("serial_no_cache", "serial_reuse", "batch_reuse")
REPEATS = 3  # Each path occupies every execution position once.
MAX_LOGIT_ERROR = 1e-4


def probe_trained_head(folder, sealed, requests, backend, config):
    """Measure actual feature-to-trained-output work on label-free requests.

    Requests come from one declared held-out input set, without gold. Head and
    normalizer are loaded and byte-verified once; that preparation is separately
    charged. No process-isolated per-arm RSS, native Worker or energy claim.
    A repeat is a timing repeat, not an independent scientific observation.
    """
    total_cpu, total_wall = time.process_time_ns(), time.perf_counter_ns()
    config.validate()
    if not isinstance(requests, tuple) or not 1 <= len(requests) <= 4096:
        raise ValueError("invalid serving request census")
    seen, partitions = set(), set()
    for request in requests:
        if type(request) is not FeatureRequest:
            raise ValueError("invalid serving request")
        request.validate()
        if request.request_id in seen:
            raise ValueError("duplicate serving request")
        seen.add(request.request_id)
        partitions.add(request.cache_key()[:6] + (request.representation,))
        if (request.encoder_digest != backend.encoder_digest
                or request.preprocessor_digest != backend.preprocessor_digest
                or request.runtime_digest != backend.runtime_digest
                or request.generation != config.generation):
            raise ValueError("serving backend/version differs from request")
    if len(partitions) != 1:
        raise ValueError("mixed serving scope or generation")
    selection, selection_sha = record(folder / "selection.json")
    if selection_sha != sealed["selection_sha256"] or selection["config"] != asdict(config):
        raise ValueError("changed serving selection/configuration")
    buffers, normalizer_bytes = verify_checkpoint_files(folder, sealed, selection)
    chosen = selection["selected_arm"]
    state = load(buffers[chosen])
    normalizer = load(normalizer_bytes)
    if set(normalizer) != {"mean", "scale"}:
        raise ValueError("invalid serving normalizer")
    width = state["bank.base.weight"].shape[1]
    if (not 1 <= width <= 512 or any(t.shape != (width,) or t.dtype != torch.float32
            or not torch.isfinite(t).all() for t in normalizer.values())
            or not (normalizer["scale"] > 0).all()):
        raise ValueError("invalid serving normalization")
    cells = len(selection["checkpoints"][chosen]["cell_ids"])
    # Fail on malformed tensors before any expensive Encoder invocation.
    tensor_forward(state, torch.zeros(1, width), cells, config.classes)
    selected = requests[:config.benchmark_inputs]
    workload = tuple(replace(r, request_id=f"probe-{j}-{i}", cell_id=f"probe-cell-{j}")
        for j in range(config.benchmark_replicas) for i, r in enumerate(selected))
    # These aliases share one selected Head; they are not independently trained Cells.
    workload_sha = digest([asdict(r) for r in workload])
    preparation = {"cpu_ns": time.process_time_ns() - total_cpu,
                   "wall_ns": time.perf_counter_ns() - total_wall}
    order = list(PATHS)
    random.Random(config.seed).shuffle(order)
    trials, reference = [], None
    maximum_error = 0.0
    with torch.no_grad():
        for repeat in range(REPEATS):
            for name in order[repeat:] + order[:repeat]:
                engine = SharedStemEngine(backend, max_cache_bytes=0 if name == "serial_no_cache" else 64 * 1024 * 1024)
                batch_size = 32 if name == "batch_reuse" else 1
                outputs, batches = [], []
                cpu, wall = time.process_time_ns(), time.perf_counter_ns()
                for offset in range(0, len(workload), batch_size):
                    batch_cpu, batch_wall = time.process_time_ns(), time.perf_counter_ns()
                    observation, features = engine.run(workload[offset:offset+batch_size], return_features=True)
                    if any(len(v.values) != width for v in features):
                        raise ValueError("serving feature/Head width mismatch")
                    x = torch.tensor([v.values for v in features], dtype=torch.float32)
                    x = (x - normalizer["mean"]) / normalizer["scale"]
                    if not torch.isfinite(x).all():
                        raise ValueError("nonfinite serving features")
                    logits = tensor_forward(state, x, cells, config.classes)
                    if not torch.isfinite(logits).all():
                        raise ValueError("nonfinite trained serving output")
                    outputs.append(logits)
                    batches.append({"members": len(features), "backend_calls": observation.backend_calls,
                        "encoded_rows": sum(observation.backend_batch_widths),
                        "prior_cache_hits": observation.cache_hits,
                        "cpu_ns": time.process_time_ns() - batch_cpu,
                        "wall_ns": time.perf_counter_ns() - batch_wall})
                measured_cpu, measured_wall = time.process_time_ns() - cpu, time.perf_counter_ns() - wall
                output = torch.cat(outputs)
                if reference is None:
                    reference = output.clone()
                delta = float((output - reference).abs().max())
                if delta > MAX_LOGIT_ERROR or not torch.equal(output.argmax(1), reference.argmax(1)):
                    raise ValueError("trained output parity failed across shared serving paths")
                maximum_error = max(maximum_error, delta)
                trials.append({"repeat": repeat, "path": name, "batches": batches,
                    "cpu_ns": measured_cpu, "wall_ns": measured_wall,
                    "logical_requests": len(workload), "cache_bytes_after": engine.cache.size_bytes,
                    "backend_calls": sum(b["backend_calls"] for b in batches),
                    "encoded_rows": sum(b["encoded_rows"] for b in batches),
                    "head_evaluated_rows": len(output), "max_abs_logit_error": delta,
                    "output_sha256": hashlib.sha256(output.numpy().tobytes()).hexdigest()})
    report = {"schema": "hepta.stem.trained-serving-probe.v1", "selected_arm": chosen,
        "selection_sha256": selection_sha, "head_sha256": selection["checkpoints"][chosen]["sha256"],
        "normalizer_sha256": sealed["normalizer_sha256"], "workload_sha256": workload_sha,
        "scope_digest": requests[0].scope_digest, "generation": config.generation,
        "encoder_digest": backend.encoder_digest, "preprocessor_digest": backend.preprocessor_digest,
        "runtime_digest": backend.runtime_digest, "revocation_frontier_digest": requests[0].revocation_frontier_digest,
        "preparation": preparation, "trials": trials, "max_abs_logit_error": maximum_error,
        "argmax_reversals": 0, "cpu_ns": time.process_time_ns() - total_cpu,
        "wall_ns": time.perf_counter_ns() - total_wall,
        "numeric_head_normalizer_bytes": sum(v.numel() * v.element_size() for v in [*state.values(), *normalizer.values()]),
        "simulated_encoder": bool(getattr(backend, "simulated", True)),
        "head_shared_by_logical_aliases": True, "native_worker_executed": False,
        "encoder_residency": "one existing resident backend; prior study may have warmed kernels",
        "quality_or_resource_superiority_established": False, "production_authorized": False}
    return report
