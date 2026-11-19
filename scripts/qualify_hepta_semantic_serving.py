#!/usr/bin/env python3
"""Run a small real MLX shared-base smoke and retain successes and failures.

Example on Apple Silicon, after an independently verified public model download:
  python scripts/qualify_hepta_semantic_serving.py --model-directory MODEL \
    --download-receipt RECEIPT --output NEW_OUTPUT_DIRECTORY

This compares individual calls with batching on the same loaded model. It is
neither a production model recommendation nor a replicated-model memory study.
"""

import argparse
import hashlib
import json
import platform
import resource
import sys
import time
import traceback
from pathlib import Path

import numpy as np

from hepta_cells.mlx_provider import (
    MLXLlamaFeatureProvider,
    file_sha256,
    json_digest,
    package_versions,
)
from hepta_cells.semantic import (
    LocalHead,
    LocalObjective,
    SemanticBudget,
    SemanticCell,
    SharedSemanticPool,
)
from hepta_cells.semantic_component import SemanticComponent, semantic_bundle


TEXTS = (
    "A unit test checks a small piece of software.",
    "A queue stores items in first in first out order.",
    "A failing test provides evidence about a regression.",
    "A stack removes the most recently added item first.",
    "A benchmark reports measurements for a declared workload.",
    "A dictionary maps a key to a corresponding value.",
    "A checksum detects changes in a stored artifact.",
    "A loop repeats a block until its condition changes.",
)


def source_manifest():
    scripts = Path(__file__).resolve().parent
    paths = [Path(__file__).resolve()] + [
        scripts / "hepta_cells" / name
        for name in (
            "__init__.py",
            "bundle.py",
            "component_types.py",
            "lifecycle.py",
            "semantic.py",
            "semantic_component.py",
            "mlx_provider.py",
        )
    ]
    return {str(path.relative_to(scripts)): file_sha256(path) for path in paths}


def max_rss_bytes():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def write_json(path, value):
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
    )
    temporary.replace(path)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def measure_calls(provider, pool, cells, requests, mode):
    event_start, guard_start = (
        len(provider.events),
        len(provider.fingerprint_measurements),
    )
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    if mode == "separate":
        outputs, features, pool_measurements = [], [], []
        for cell, inputs in requests:
            logits, measured = pool.predict_batch([(cell, inputs)])
            outputs.append(logits[0])
            features.append(provider.last_features())
            pool_measurements.extend(measured)
    else:
        outputs, pool_measurements = pool.predict_batch(requests)
        features = provider.last_features().reshape(len(cells), 2, provider.feature_dim)
    elapsed_wall, elapsed_cpu = (
        time.perf_counter_ns() - wall,
        time.process_time_ns() - cpu,
    )
    events, guards = (
        provider.events[event_start:],
        provider.fingerprint_measurements[guard_start:],
    )
    record = dict(
        mode=mode,
        pool_end_to_end_wall_ns=elapsed_wall,
        process_cpu_ns=elapsed_cpu,
        provider_encode_wall_ns=sum(event["wall_ns"] for event in events),
        fingerprint_guard_wall_ns=sum(guard["wall_ns"] for guard in guards),
        provider_calls=len(events),
        full_transformer_forwards=sum(
            event.get("transformer_forwards", 0) for event in events
        ),
        event_indices=list(range(event_start, len(provider.events))),
        pool_measurements=pool_measurements,
    )
    return np.asarray(outputs), np.asarray(features), record


def execute(args, result, raw, save):
    result["stage"] = "loading_verified_model"
    save()
    provider = MLXLlamaFeatureProvider(args.model_directory, args.download_receipt)
    result.update(
        provider=provider.info,
        binding=vars(provider.binding),
        stage="shared_model_loaded",
        provider_events=provider.events,
        parameter_fingerprint_costs=provider.fingerprint_measurements,
    )
    save()
    pool = SharedSemanticPool(
        max_batch_cells=4,
        max_batch_items=8,
        max_batch_input_bytes=4096,
        max_batch_working_bytes=2 * 1048576,
    )
    pool.register_backend(provider.backend)
    objective = LocalObjective(
        "mse",
        2,
        "declared two-row engineering fixture targets; no language-quality claim",
    )
    budget = SemanticBudget(
        max_items=8,
        max_input_bytes=4096,
        max_working_bytes=8 * 1048576,
        max_train_steps=64,
        max_total_items=256,
    )
    cells = []
    for index in range(4):
        random = np.random.default_rng(20261108 + index)
        head = LocalHead(
            random.normal(0, 0.03, (provider.feature_dim, 2)), random.normal(0, 0.01, 2)
        )
        cells.append(
            SemanticCell(
                "semantic-smoke-" + str(index),
                provider.binding,
                head,
                objective,
                budget,
                state={"owner": index, "marker": [index]},
                retrieval_view=("fixture-view-" + str(index),),
            )
        )
    requests = [(cell, TEXTS[2 * i : 2 * i + 2]) for i, cell in enumerate(cells)]
    heads_before = [cell.head.digest for cell in cells]
    state_before = [cell.state for cell in cells]
    views_before = [cell.retrieval_view for cell in cells]
    require(
        all(pool._resolve(cell)[0] is provider.backend for cell in cells),
        "cells did not share one backend",
    )
    require(
        all(
            not np.shares_memory(a.head.first, b.head.first)
            for i, a in enumerate(cells)
            for b in cells[i + 1 :]
        ),
        "private heads share mutable storage",
    )
    result.update(
        stage="warmup",
        cells=4,
        input_rows=8,
        input_texts=list(TEXTS),
        local_objective=vars(objective),
        comparison="individual requests versus batching using the same single loaded model",
        comparison_tolerance={"rtol": 0.005, "atol": 0.002},
        warmup=[],
        rounds=[],
    )
    save()
    for mode in ("separate", "batch"):
        logits, features, record = measure_calls(provider, pool, cells, requests, mode)
        raw["warmup_" + mode + "_logits"] = logits
        raw["warmup_" + mode + "_features"] = features
        result["warmup"].append(record)
    require(
        np.max(np.abs(raw["warmup_batch_logits"])) > 1e-8,
        "comparison heads were degenerate zero outputs",
    )
    result["stage"] = "interleaved_comparison"
    save()
    for round_index, order in enumerate(
        (("separate", "batch"), ("batch", "separate"), ("separate", "batch"))
    ):
        observed, measurements = {}, []
        for mode in order:
            logits, features, record = measure_calls(
                provider, pool, cells, requests, mode
            )
            prefix = "round_" + str(round_index) + "_" + mode
            raw[prefix + "_logits"], raw[prefix + "_features"] = logits, features
            observed[mode] = (logits, features)
            measurements.append(record)
        logits_equal = np.allclose(
            observed["separate"][0], observed["batch"][0], rtol=0.005, atol=0.002
        )
        features_equal = np.allclose(
            observed["separate"][1], observed["batch"][1], rtol=0.005, atol=0.002
        )
        timings = {
            record["mode"]: record["pool_end_to_end_wall_ns"] for record in measurements
        }
        result["rounds"].append(
            dict(
                round=round_index,
                order=list(order),
                measurements=measurements,
                logits_max_abs_difference=float(
                    np.max(np.abs(observed["separate"][0] - observed["batch"][0]))
                ),
                features_max_abs_difference=float(
                    np.max(np.abs(observed["separate"][1] - observed["batch"][1]))
                ),
                logits_within_tolerance=bool(logits_equal),
                features_within_tolerance=bool(features_equal),
                batch_to_separate_wall_ratio=timings["batch"] / timings["separate"],
            )
        )
        save()
        require(
            logits_equal and features_equal,
            "single and batch full-transformer outputs differ beyond declared tolerance",
        )
    result.update(stage="private_head_training", training=[])
    save()
    evaluation_profile = json_digest(
        dict(
            protocol="tiny-real-mlx-local-head-smoke-v1",
            generalization_evaluated=False,
            source=result["source_files"],
            seed=20261108,
            steps=64,
            learning_rate=0.4,
        )
    )
    for index, (cell, inputs) in enumerate(requests):
        targets = np.asarray(
            [[0.8 + 0.05 * index, -0.3], [-0.4, 0.7 - 0.03 * index]], dtype=np.float64
        )
        component = SemanticComponent(
            pool, cell, semantic_bundle(cell, cell.cell_id + "-source")
        )
        active_identity = component.identity
        source_bundle = component.bundle
        before_budget = [peer.used_items for peer in cells]
        candidate_component, candidate = component.propose(
            inputs,
            targets,
            artifact_id=cell.cell_id + "-candidate",
            evaluation_profile=evaluation_profile,
            steps=64,
            learning_rate=0.4,
        )
        prefix = "training_" + str(index)
        raw[prefix + "_features"] = provider.last_features()
        raw[prefix + "_targets"] = targets
        raw[prefix + "_source_head"] = cell.head.first
        raw[prefix + "_source_bias"] = cell.head.bias
        raw[prefix + "_candidate_head"] = candidate.head.first
        raw[prefix + "_candidate_bias"] = candidate.head.bias
        write_json(
            args.output / (prefix + "_source_bundle.json"), source_bundle.record()
        )
        write_json(
            args.output / (prefix + "_candidate_bundle.json"),
            candidate_component.bundle.record(),
        )
        record = dict(
            candidate.training_receipt,
            source_head_sha256=cell.head.digest,
            candidate_head_sha256=candidate.head.digest,
            candidate_component_identity=vars(candidate_component.identity),
            source_identity_unchanged=component.identity == active_identity,
            shared_pool_budgets_unchanged=[peer.used_items for peer in cells]
            == before_budget,
        )
        result["training"].append(record)
        save()
        require(
            candidate.loss_after < candidate.loss_before
            and candidate.head.digest != cell.head.digest,
            "local training did not produce a genuine loss-reducing head update",
        )
        require(
            record["source_identity_unchanged"]
            and record["shared_pool_budgets_unchanged"],
            "proposal mutated active component identity or another invocation's budget",
        )
    result.update(
        stage="final_checks",
        model_load_count=provider.load_count,
        host_array_report=pool.memory_report(cells),
        metal_memory=provider.memory_snapshot(),
        provider_events=provider.events,
        parameter_fingerprint_costs=provider.fingerprint_measurements,
    )
    checks = dict(
        one_model_load=provider.load_count == 1,
        frozen_parameter_values_unchanged=provider.fingerprint()
        == provider.binding.base,
        active_head_digests_unchanged=[cell.head.digest for cell in cells]
        == heads_before,
        independent_state_preserved=[cell.state for cell in cells] == state_before,
        independent_retrieval_views_preserved=[cell.retrieval_view for cell in cells]
        == views_before,
        source_files_unchanged=source_manifest() == result["source_files"],
        all_four_private_candidates_updated=len(result["training"]) == 4,
    )
    result["checks"] = checks
    require(all(checks.values()), "one or more shared-model isolation checks failed")
    result.update(
        status="success",
        stage="completed",
        energy_joules=None,
        metal_peak_scope="MLX active allocation high-water since provider initialization, including load and probe",
        process_max_rss_bytes=max_rss_bytes(),
        generalization_evaluated=False,
        replicated_model_memory_comparison=False,
        production_model_recommendation=False,
        timing_caveat="three engineering rounds; includes full frozen-parameter SHA guards; no significance claim",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-directory", type=Path, required=True)
    parser.add_argument("--download-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter(), time.process_time()
    result = dict(
        schema="hepta.cell.semantic-serving.v1",
        status="started",
        started_unix=time.time(),
        purpose="tiny language-model engineering probe",
        python=sys.version,
        platform=platform.platform(),
        packages=package_versions(),
        source_files=source_manifest(),
        download_receipt_sha256=file_sha256(args.download_receipt),
        process_max_rss_before_bytes=max_rss_bytes(),
        inference_concurrency=1,
    )
    raw = {}
    save = lambda: write_json(args.output / "result.json", result)
    save()
    try:
        execute(args, result, raw, save)
    except Exception as exc:
        result.update(
            status="failure",
            error_type=type(exc).__name__,
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        if hasattr(exc, "receipt"):
            result["failed_training_receipt"] = exc.receipt
    finally:
        result.update(
            finished_unix=time.time(),
            total_wall_seconds=time.perf_counter() - wall,
            total_process_cpu_seconds=time.process_time() - cpu,
            process_max_rss_bytes=max_rss_bytes(),
        )
        if raw:
            np.savez_compressed(args.output / "raw_arrays.npz", **raw)
            result["raw_array_artifact"] = dict(
                name="raw_arrays.npz",
                sha256=file_sha256(args.output / "raw_arrays.npz"),
                arrays={key: list(value.shape) for key, value in raw.items()},
            )
        save()
        manifest = {
            path.name: dict(bytes=path.stat().st_size, sha256=file_sha256(path))
            for path in args.output.iterdir()
            if path.is_file() and path.name != "artifact-manifest.json"
        }
        write_json(args.output / "artifact-manifest.json", manifest)
        print(
            json.dumps(
                dict(
                    status=result["status"],
                    output=str(args.output),
                    stage=result.get("stage"),
                    model_load_count=result.get("model_load_count"),
                    checks=result.get("checks"),
                    metal_memory=result.get("metal_memory"),
                    error=result.get("error"),
                ),
                sort_keys=True,
            )
        )
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
