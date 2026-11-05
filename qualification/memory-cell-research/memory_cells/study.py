"""Measured single/multiple-cell experiments; no test-driven parameter search."""

from dataclasses import asdict
import gzip
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from .data import (
    active_events,
    exact_store_predict,
    lexical_retrieval_predict,
    make_associative,
    from_module_registry,
)
from .encoding import FrozenEncoder, canonical_bytes
from .metrics import paired_cluster_interval, summarize_predictions
from .model import MemoryCell
from .network import MemoryNetwork, write_network_manifest
from .routing import LearnedRouter, LiteralRouter, TypedRouter


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n"
    )


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def score(queries, predictions):
    return summarize_predictions(
        [q.target for q in queries], predictions, groups=[q.domain for q in queries]
    )


def fit_cell(
    events, encoder, protocol, rank, seed, output, source_commit, *, steps=None
):
    started = time.perf_counter()
    events = active_events(events)
    model = MemoryCell(encoder.dim, rank, protocol["num_classes"], seed)
    encode_started = time.perf_counter()
    features = encoder.encode([e.key for e in events])
    encoding_seconds = time.perf_counter() - encode_started
    receipt = model.fit(
        features,
        np.array([e.value for e in events]),
        steps=steps or protocol["optimizer_steps"],
        lr=protocol["learning_rate"],
    )
    save_started = time.perf_counter()
    manifest = model.save(
        output,
        encoder_manifest=encoder.manifest(),
        lineage={
            "dataset": digest([asdict(e) for e in events]),
            "source_commit": source_commit,
        },
    )
    receipt.update(
        encoding_seconds=encoding_seconds,
        save_seconds=time.perf_counter() - save_started,
        write_seconds_before_receipt=time.perf_counter() - started,
    )
    write_json(Path(output) / "training.json", receipt)
    return model, receipt, manifest


def batch_predict(model, encoder, queries):
    started = time.perf_counter()
    probabilities = model.proba(encoder.encode([q.key for q in queries]))
    predictions = probabilities.argmax(axis=1).tolist()
    return predictions, {
        "seconds": time.perf_counter() - started,
        "queries": len(queries),
        "cell_calls": len(queries),
    }


def routed_predict(cells, encoder, queries, routes):
    started = time.perf_counter()
    predictions = [None] * len(queries)
    calls = 0
    for domain, model in cells.items():
        indices = [i for i, route in enumerate(routes) if route == domain]
        if indices:
            values = model.predict(encoder.encode([queries[i].key for i in indices]))
            for i, value in zip(indices, values):
                predictions[i] = int(value)
            calls += len(indices)
    return predictions, {
        "seconds": time.perf_counter() - started,
        "queries": len(queries),
        "cell_calls": calls,
    }


def fresh_read(artifact, encoder, queries, output):
    artifact, output = Path(artifact).resolve(), Path(output).resolve()
    request = {
        "schema": "memory-cell-read.v1",
        "artifact": artifact.relative_to(output).as_posix(),
        "keys": [q.key for q in queries],
        "expected_encoder_digest": encoder.digest,
    }
    request_path = output / "fresh_request.json"
    write_json(request_path, request)
    entrypoint = Path(__file__).resolve().parents[1] / "read_parameters.py"
    started = time.perf_counter()
    process = subprocess.run(
        [sys.executable, "-I", str(entrypoint), str(request_path)],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
        cwd=artifact,
    )
    result = json.loads(process.stdout)
    result["process_wall_seconds"] = time.perf_counter() - started
    write_json(output / "fresh_read.json", result)
    return result


def tree_bytes(path):
    return sum(p.stat().st_size for p in Path(path).rglob("*") if p.is_file())


def run_case(dataset, protocol, output, source_commit, seed, *, multi=True, fresh=True):
    case_started = time.perf_counter()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "dataset.json", dataset.to_dict())
    events = active_events(dataset.events)
    queries = dataset.test
    encoder = FrozenEncoder(protocol["feature_dim"], seed=0)
    domains = tuple(sorted({e.domain for e in events}))
    multi = multi and len(domains) > 1
    rank = protocol["cell_rank"]
    router_params = 4 * (encoder.dim + len(domains)) if multi else 0
    multi_params = len(domains) * rank * (encoder.dim + protocol["num_classes"])
    single_rank = (
        math.ceil(
            (multi_params + router_params) / (encoder.dim + protocol["num_classes"])
        )
        if multi
        else rank
    )
    untrained = MemoryCell(encoder.dim, single_rank, protocol["num_classes"], seed)
    baseline_empty, empty_cost = batch_predict(untrained, encoder, queries)
    single, single_train, single_manifest = fit_cell(
        events, encoder, protocol, single_rank, seed, output / "single", source_commit
    )
    single_values, single_read = batch_predict(single, encoder, queries)
    predictions = {"untrained": baseline_empty, "single": single_values}
    exact_started = time.perf_counter()
    predictions["exact_store"] = exact_store_predict(events, queries)
    exact_seconds = time.perf_counter() - exact_started
    exact_build_started = time.perf_counter()
    exact_index = {(e.domain, e.key): e.value for e in active_events(dataset.events)}
    exact_build_seconds = time.perf_counter() - exact_build_started
    exact_hot_started = time.perf_counter()
    exact_hot_values = [exact_index.get((q.domain, q.key)) for q in queries]
    exact_hot_seconds = time.perf_counter() - exact_hot_started
    if exact_hot_values != predictions["exact_store"]:
        raise RuntimeError("prebuilt exact index disagrees with authoritative lookup")
    lexical_started = time.perf_counter()
    predictions["lexical"] = lexical_retrieval_predict(events, queries)
    lexical_seconds = time.perf_counter() - lexical_started
    metrics = {
        "seed": seed,
        "records": len(events),
        "query_count": len(queries),
        "independent_record_count": len({q.episode_id for q in queries}),
        "encoder": encoder.manifest(),
        "single_train": single_train,
        "single_read": single_read,
        "empty_read": empty_cost,
        "retrieval_read_seconds": {"exact": exact_seconds, "lexical": lexical_seconds},
        "retrieval_timing_scope": "exact and lexical above include index construction plus batch read",
        "exact_index_build_seconds": exact_build_seconds,
        "exact_hot_batch_read_seconds": exact_hot_seconds,
        "single_rank": single_rank,
        "single_manifest": single_manifest["manifest_sha256"],
        "label_catalog_bytes": dataset.metadata.get("label_catalog_bytes", 0),
        "language_understanding_claim": False,
        "effective_input_test_is_written_key_recall": True,
    }
    if fresh:
        cold = fresh_read(output / "single", encoder, queries, output)
        if cold["predictions"] != single_values:
            raise RuntimeError("fresh-process read differs from in-process predictions")
        if cold["opened_artifact_files"] != ["manifest.json", "tensors.npz"]:
            raise RuntimeError("fresh reader opened unexpected artifact files")
        if cold["artifact_digest"] != single_manifest["manifest_sha256"]:
            raise RuntimeError("fresh reader used a different model artifact")
        if cold["pid"] == __import__("os").getpid():
            raise RuntimeError("parameter-only read did not use a fresh process")
        metrics["fresh_process"] = {
            "pid": cold["pid"],
            "parent_pid_different": cold["pid"] != __import__("os").getpid(),
            "same_predictions": True,
            "accuracy": score(queries, cold["predictions"]),
            "process_wall_seconds": cold["process_wall_seconds"],
            "opened_artifact_files": cold["opened_artifact_files"],
            "audit_scope": cold["audit_scope"],
        }
    if multi:
        cells, training, manifests = {}, {}, {}
        for i, domain in enumerate(domains):
            cells[domain], training[domain], manifests[domain] = fit_cell(
                [e for e in events if e.domain == domain],
                encoder,
                protocol,
                rank,
                seed + 100 + i,
                output / "cells" / str(i),
                source_commit,
            )
        router = LearnedRouter(domains, encoder=encoder, rank=4, seed=seed + 200)
        router_train = router.fit(
            dataset.train,
            steps=protocol["optimizer_steps"],
            lr=protocol["learning_rate"],
        )
        router.save(output / "router")
        network_manifest = write_network_manifest(output, domains, scope="research")
        loaded_network = MemoryNetwork.load(output, expected_scope="research")
        routing = {}
        for name, instance in (
            ("typed", TypedRouter(domains)),
            ("literal", LiteralRouter(domains)),
            ("learned", router),
        ):
            started = time.perf_counter()
            routes = instance.route(queries)
            route_seconds = time.perf_counter() - started
            predictions[name], cost = routed_predict(cells, encoder, queries, routes)
            loaded_values, loaded_routes, _ = loaded_network.predict(
                queries, route=name
            )
            if loaded_values != predictions[name] or loaded_routes != routes:
                raise RuntimeError(
                    "reloaded network disagrees with original model composition"
                )
            routing[name] = {
                "correct_routes": sum(r == q.domain for r, q in zip(routes, queries)),
                "route_seconds": route_seconds,
                "read": cost,
                "manifest": instance.manifest(),
            }
        predictions["oracle"], oracle_cost = routed_predict(
            cells, encoder, queries, [q.domain for q in queries]
        )
        train_flops = sum(
            r["estimated_training_matmul_flops"] for r in training.values()
        )
        train_flops += router_train["estimated_training_matmul_flops"]
        # Full-batch fit also evaluates gradients before and after optimization.
        single_step_flops = single_train["estimated_training_matmul_flops"] / (
            protocol["optimizer_steps"] + 2
        )
        matched_steps = max(1, math.floor(train_flops / single_step_flops - 2))
        matched, matched_train, _ = fit_cell(
            events,
            encoder,
            protocol,
            single_rank,
            seed,
            output / "single-compute-matched",
            source_commit,
            steps=matched_steps,
        )
        predictions["single_compute_matched"], matched_read = batch_predict(
            matched, encoder, queries
        )
        deployed_bytes = (
            tree_bytes(output / "cells")
            + tree_bytes(output / "router")
            + (output / "network.json").stat().st_size
        )
        metrics.update(
            {
                "cell_training": training,
                "router_training": router_train,
                "routing": routing,
                "oracle_read": oracle_cost,
                "matched_train": matched_train,
                "matched_read": matched_read,
                "budget": {
                    "single_parameters": single.trainable_params,
                    "multi_parameters_including_router": multi_params + router_params,
                    "single_rounding_extra_parameters": single.trainable_params
                    - multi_params
                    - router_params,
                    "single_exposure_training_flops": single_train[
                        "estimated_training_matmul_flops"
                    ],
                    "multi_training_flops_including_router": train_flops,
                    "matched_single_training_flops": matched_train[
                        "estimated_training_matmul_flops"
                    ],
                    "equal_flops_is_approximate_integer_step_rounding": True,
                },
                "multi_deployed_artifact_bytes": deployed_bytes,
                "network_manifest": network_manifest["manifest_sha256"],
                "network_manifest_bytes": (output / "network.json").stat().st_size,
                "reloaded_network_all_routes_match": True,
                "multi_training_seconds_including_router": sum(
                    r["seconds"] for r in training.values()
                )
                + router_train["seconds"],
                "multi_write_seconds_before_router_save": sum(
                    r["write_seconds_before_receipt"] for r in training.values()
                )
                + router_train["seconds"]
                + router_train["encoding_seconds"],
                "total_deployment_bytes_are_measured_not_equalized": True,
            }
        )
    lookup = canonical_bytes(
        [{"domain": e.domain, "key": e.key, "value": e.value} for e in events]
    )
    metrics["storage"] = {
        "single_artifact_bytes_including_training_receipt": tree_bytes(
            output / "single"
        ),
        "common_source_event_bytes": len(canonical_bytes([asdict(e) for e in events])),
        "minimal_exact_lookup_json_bytes": len(lookup),
        "minimal_exact_lookup_gzip_bytes": len(gzip.compress(lookup, mtime=0)),
        "evaluation_dataset_bytes_not_deployed": (output / "dataset.json")
        .stat()
        .st_size,
        "sources_needed_for_replay_are_not_free": True,
    }
    metrics["scores"] = {
        name: score(queries, values) for name, values in predictions.items()
    }
    rows = [
        {
            "query_id": q.query_id,
            "episode_id": q.episode_id,
            "target": q.target,
            "predictions": {name: values[i] for name, values in predictions.items()},
        }
        for i, q in enumerate(queries)
    ]
    write_json(output / "predictions.json", rows)
    metrics["case_wall_seconds_before_metrics_serialization"] = (
        time.perf_counter() - case_started
    )
    write_json(output / "metrics.json", metrics)
    return metrics


def accuracy(case, arm):
    return case["scores"][arm]["known_accuracy"]


def run_core(protocol, output, source_commit, seeds=None, capacities=None):
    cases = []
    for seed in seeds or protocol["seeds"]:
        for sizes in capacities or protocol["capacity_domain_sizes"]:
            name = f"seed-{seed}-n-{sum(sizes)}"
            print(json.dumps({"event": "case_started", "case": name}), flush=True)
            dataset = make_associative(seed, tuple(sizes), protocol["num_classes"])
            result = run_case(
                dataset, protocol, Path(output) / name, source_commit, seed
            )
            cases.append(result)
            print(
                json.dumps(
                    {
                        "event": "case_finished",
                        "case": name,
                        "scores": {
                            k: v["known_accuracy"] for k, v in result["scores"].items()
                        },
                    }
                ),
                flush=True,
            )
    primary = [
        r for r in cases if r["records"] == sum(protocol["primary_domain_sizes"])
    ]
    interval = (
        paired_cluster_interval(
            [accuracy(r, "learned") for r in primary],
            [accuracy(r, "single") for r in primary],
            [str(r["seed"]) for r in primary],
        )
        if primary
        else None
    )
    comparisons = {}
    if primary:
        for name, candidate, baseline in (
            ("learned_minus_compute_matched", "learned", "single_compute_matched"),
            ("oracle_minus_learned", "oracle", "learned"),
            ("literal_minus_learned", "literal", "learned"),
        ):
            comparisons[name] = paired_cluster_interval(
                [accuracy(r, candidate) for r in primary],
                [accuracy(r, baseline) for r in primary],
                [str(r["seed"]) for r in primary],
            )
    result = {
        "cases": cases,
        "primary_paired_learned_minus_single": interval,
        "primary_paired_comparisons": comparisons,
        "single_criterion_met": bool(primary)
        and all(
            r["fresh_process"]["accuracy"]["known_accuracy"] >= 0.95 for r in primary
        ),
        "multi_criterion_met": bool(interval)
        and interval["paired_difference"] >= 0.02
        and interval["lower"] is not None
        and interval["lower"] > 0,
        "scope": "typed-address numerical memory; text routing separately measured",
    }
    write_json(Path(output) / "summary.json", result)
    return result


def run_transfer(protocol, output, source_commit, repo):
    cases = []
    names = ("inventory-items", "laboratory-samples", "project-issues", "device-parts")
    for seed in protocol["transfer_seeds"]:
        dataset = make_associative(
            seed,
            tuple(protocol["primary_domain_sizes"]),
            protocol["num_classes"],
            domain_names=names[: len(protocol["primary_domain_sizes"])],
        )
        cases.append(
            run_case(
                dataset, protocol, Path(output) / f"seed-{seed}", source_commit, seed
            )
        )
    real = from_module_registry(
        Path(repo) / "docs/modules/MODULES.json",
        protocol["baseline_commit"],
        field="owner",
        expected_blob_sha="e4a5965a06b0af917130bd929158e714684a91bc",
    )
    cases.append(
        run_case(
            real,
            protocol,
            Path(output) / "repository-facts",
            source_commit,
            seed=1021,
            multi=False,
        )
    )
    result = {
        "cases": cases,
        "real_source": real.metadata,
        "qualification": "independent synthetic streams and one pinned repository diagnostic",
        "broad_generalization_established": False,
        "natural_language_question_answering_established": False,
    }
    write_json(Path(output) / "summary.json", result)
    return result
