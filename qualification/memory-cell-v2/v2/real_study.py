"""Real-source parameter reads and supplied typed composition, with full costs.

Addresses resolve versions outside the weights; catalogs decode class IDs and
are charged in full. Procedure heads recall rules, then a supplied interpreter
executes new inputs. Public task-header routing is not open-domain QA, and the
two graph edges are given rather than learned. Seeds reuse the same real sources.
"""

from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import numpy as np

from memory_cells.model import MemoryCell
from .adapter import load_cell, save_cell
from .addressing import AddressIndex, KINDS, address_text
from .encoder import MiniLMEncoder, canonical, sha
from .real_routing import TASK_KINDS, fit_router, route_queries
from .tasks import build_real_tasks, compose, execute_rule


DEFAULT_PROFILE = {
    "rank_per_type": 8,
    "steps": 600,
    "learning_rate": 0.03,
    "feature_dim": 384,
    "fresh_process": True,
    "composition_edges": "given_typed_ports",
    "max_training_events": 8192,
    "router_steps": 600,
    "router_learning_rate": 0.03,
    "router_threshold": 0.8,
    "router_margin": 0.25,
}
PACKAGE = Path(__file__).resolve().parents[1]


def _json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value) + b"\n")


def _bytes(path):
    path = Path(path)
    return (
        sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
        if path.is_dir()
        else path.stat().st_size
    )


class ValueCatalog:
    """A charged value vocabulary, with no keys, timestamps or query lookup map."""

    def __init__(self, values):
        encoded = sorted({canonical(value) for value in values})
        if not 1 <= len(encoded) <= 4096:
            raise ValueError("catalog must contain 1..4096 distinct values")
        self.values = [json.loads(value) for value in encoded]
        self._ids = {value: index for index, value in enumerate(encoded)}

    @property
    def classes(self):
        return max(2, len(self.values))

    def encode(self, value):
        return self._ids[canonical(value)]

    def decode(self, index):
        return (
            json.loads(canonical(self.values[index]))
            if 0 <= index < len(self.values)
            else None
        )

    def save(self, path):
        _json(
            path,
            {
                "schema": "memory-cell-v2.value-catalog.v1",
                "values": self.values,
                "sha256": sha(canonical(self.values)),
            },
        )

    @classmethod
    def load(cls, path):
        payload = json.loads(Path(path).read_bytes())
        if not isinstance(payload, dict) or set(payload) != {
            "schema",
            "values",
            "sha256",
        }:
            raise ValueError("invalid value catalog")
        result = cls(payload["values"])
        if (
            payload["schema"] != "memory-cell-v2.value-catalog.v1"
            or payload["values"] != result.values
            or payload["sha256"] != sha(canonical(result.values))
        ):
            raise ValueError("catalog identity or class ordering mismatch")
        return result


def union_events(bundles):
    """Deduplicate identical writes; conflicting value or provenance is an error."""
    unique = {}
    for bundle in bundles.values():
        for event in bundle.events:
            identity = event.cell_type, event.key, event.revision
            if identity in unique and canonical(asdict(unique[identity])) != canonical(
                asdict(event)
            ):
                raise ValueError("conflicting duplicate write identity")
            unique[identity] = event
    return tuple(unique[key] for key in sorted(unique))


class ParameterRead:
    """The complete parameter path; no events or oracle targets are accepted.

    An ephemeral cache batches unique addresses within one evaluation batch. It
    is cleared between arms/ablations, never persisted, and populated only from
    encoder -> model -> catalog. Online timing includes both graph lookup rounds.
    """

    def __init__(self, index, encoder, models, catalogs, single=False):
        self.index, self.encoder, self.models, self.catalogs = (
            index,
            encoder,
            models,
            catalogs,
        )
        self.single = single
        self.reset()

    def reset(self):
        self.cache = {}
        self.encoder_seconds = self.parameter_seconds = 0.0
        self.encoder_batches = self.encoded_addresses = 0

    def prefetch(self, requests):
        pending = {}
        for kind, key, cut in requests:
            address = self.index.resolve(kind, key, cut)
            if address is not None and address not in self.cache:
                pending.setdefault("single" if self.single else kind, set()).add(
                    address
                )
        for kind, addresses in sorted(pending.items()):
            texts = sorted(addresses)
            started = time.perf_counter()
            features = self.encoder.encode(texts)
            self.encoder_seconds += time.perf_counter() - started
            started = time.perf_counter()
            ids = self.models[kind].predict(features)
            self.cache.update(
                (text, self.catalogs[kind].decode(int(index)))
                for text, index in zip(texts, ids)
            )
            self.parameter_seconds += time.perf_counter() - started
            self.encoder_batches += 1
            self.encoded_addresses += len(texts)

    def read(self, kind, key, cut=None):
        address = self.index.resolve(kind, key, cut)
        if address is None:
            return None
        if address not in self.cache:
            self.prefetch([(kind, key, cut)])
        return self.cache[address]


class ExactRead:
    """Prebuilt exact address/value store; lookup is constant-time after index resolution."""

    def __init__(self, index, events):
        self.index = index
        self.values = {
            address_text(event.cell_type, event.key, event.revision): event.value
            for event in events
            if not event.deleted
        }

    def reset(self):
        pass

    def prefetch(self, requests):
        del requests

    def read(self, kind, key, cut=None):
        return self.values.get(self.index.resolve(kind, key, cut))


def _first(query, route):
    if route is None or (
        query.cell_type == "composition" and route != TASK_KINDS[query.task]
    ):
        return None
    return route, query.key, query.as_of


def _second(query, first, transform):
    if query.task == "schema_chain":
        pointer = transform(first, "schema_pointer")
        return ("procedural", pointer, None) if isinstance(pointer, str) else None
    if query.task == "commit_owner_chain":
        module = transform(first, "module_id")
        return (
            ("semantic", "module.owner:" + module, None)
            if isinstance(module, str)
            else None
        )
    return None


def evaluate(queries, reader, oracle, router, route_mode="typed", transform=None):
    """Scores are outside the timed service path and never enter reader callbacks."""
    transform = (lambda value, kind: value) if transform is None else transform
    started = time.perf_counter()
    reader.reset()
    routed_at = time.perf_counter()
    decisions = route_queries(router, queries, route_mode)
    routing_seconds = time.perf_counter() - routed_at
    requests = [
        _first(query, decision.route_id) for query, decision in zip(queries, decisions)
    ]
    reader.prefetch([request for request in requests if request is not None])
    first_values = [
        reader.read(*request) if request is not None else None for request in requests
    ]
    second_requests = [
        _second(query, value, transform) if request is not None else None
        for query, value, request in zip(queries, first_values, requests)
    ]
    reader.prefetch([request for request in second_requests if request is not None])
    second_values = [
        reader.read(*request) if request is not None else None
        for request in second_requests
    ]
    predictions = []
    for query, value, request in zip(queries, first_values, requests):
        if query.cell_type == "composition":
            value = (
                compose(query, reader.read, transform) if request is not None else None
            )
        elif query.cell_type == "procedural" and value is not None:
            try:
                value = execute_rule(value, query.inputs["value"])
            except (TypeError, ValueError):
                value = None
        predictions.append(value)
    service_seconds = time.perf_counter() - started
    rows, groups = [], {}
    for query, first, second, prediction, decision in zip(
        queries, first_values, second_values, predictions, decisions
    ):
        intended_first = oracle.read(TASK_KINDS[query.task], query.key, query.as_of)
        identities = [canonical(first) == canonical(intended_first)]
        intended_second = _second(query, intended_first, lambda value, kind: value)
        if query.cell_type == "composition":
            truth = (
                oracle.read(*intended_second) if intended_second is not None else None
            )
            identities.append(canonical(second) == canonical(truth))
        correct = canonical(prediction) == canonical(query.target)
        routed = decision.route_id == TASK_KINDS[query.task]
        groups.setdefault(query.task, []).append(
            (correct, identities, routed, decision.route_id is not None)
        )
        rows.append(
            {
                "query": asdict(query),
                "prediction": prediction,
                "correct": correct,
                "first_value_prediction": first,
                "second_value_prediction": second,
                "intended_event_value_identity": identities,
                "route": asdict(decision),
            }
        )
    metrics = {}
    for task, observations in sorted(groups.items()):
        identities = [flag for _, values, _, _ in observations for flag in values]
        metrics[task] = {
            "queries": len(observations),
            "correct": sum(row[0] for row in observations),
            "final_accuracy": sum(row[0] for row in observations) / len(observations),
            "event_value_identity_accuracy": sum(identities) / len(identities),
            "event_value_comparisons": len(identities),
            "all_required_values_exact": sum(all(row[1]) for row in observations)
            / len(observations),
            "routing_accuracy": sum(row[2] for row in observations) / len(observations),
            "routing_coverage": sum(row[3] for row in observations) / len(observations),
        }
    return {
        "tasks": metrics,
        "batch_queries": len(queries),
        "read_seconds": service_seconds,
        "routing_seconds": routing_seconds,
        "encoder_seconds": getattr(reader, "encoder_seconds", 0.0),
        "head_and_decode_seconds": getattr(reader, "parameter_seconds", 0.0),
        "encoder_batches": getattr(reader, "encoder_batches", 0),
        "unique_address_encodings": getattr(reader, "encoded_addresses", 0),
        "encoder_batch_counter_scope": "encode request groups; MiniLM native execution is one independent text per call",
        "timing_scope": "warm session; unique addresses grouped per graph hop, each text tokenized/inferred independently; scoring excluded",
    }, rows


def _shuffle(index, seed):
    inventories = {
        "schema_pointer": sorted(
            {row["key"] for row in index.entries if row["kind"] == "procedural"}
        ),
        "module_id": sorted(
            {
                row["key"].removeprefix("module.owner:")
                for row in index.entries
                if row["kind"] == "semantic" and row["key"].startswith("module.owner:")
            }
        ),
    }
    rng, mappings = np.random.default_rng(seed), {}
    for kind, values in inventories.items():
        if len(values) < 2:
            raise ValueError(
                "edge ablation requires at least two registered IDs per port type"
            )
        values = [values[int(index)] for index in rng.permutation(len(values))]
        mappings[kind] = dict(zip(values, values[1:] + values[:1]))
    return (
        lambda value, kind: (
            mappings[kind].get(value) if isinstance(value, str) else None
        ),
        mappings,
    )


def _fresh(
    artifact, texts, cell, encoder, base_path, directory, *, cached_features=None
):
    """Preserve every result before checking exact reload and batch invariance."""
    directory.mkdir(parents=True, exist_ok=False)
    request = {
        "schema": "memory-cell-v2.read.v1",
        "artifact": str(artifact.resolve()),
        "base_path": str(Path(base_path).resolve()),
        "texts": texts,
        "expected_encoder_digest": encoder.digest,
    }
    _json(directory / "request.json", request)
    manifest = json.loads((artifact / "manifest.json").read_bytes())
    started = time.perf_counter()
    request_features = encoder.encode(texts)
    expected = cell.predict(request_features).tolist()
    in_process_seconds = time.perf_counter() - started
    batch_details = {"checked_against_training_features": cached_features is not None}
    if cached_features is not None:
        same_shape = cached_features.shape == request_features.shape
        differences = np.abs(cached_features - request_features) if same_shape else None
        batch_details.update(
            exact_features_equal=bool(
                np.array_equal(cached_features, request_features)
            ),
            feature_max_abs_difference=float(differences.max()) if same_shape else None,
            changed_feature_rows=int(np.any(differences != 0, axis=1).sum())
            if same_shape
            else None,
            training_feature_sha256=sha(
                np.asarray(cached_features, dtype="<f8").tobytes()
            ),
        )
    _json(
        directory / "expected.json",
        {
            "predictions": expected,
            "query_count": len(texts),
            "expected_from": "same request texts, order and current encoder contract; independently reencoded",
            "encoder_digest": encoder.digest,
            "artifact_digest": manifest["manifest_sha256"],
            "request_feature_sha256": sha(
                np.asarray(request_features, dtype="<f8").tobytes()
            ),
            "batch_contract": batch_details,
            "in_process_validation_seconds": in_process_seconds,
        },
    )
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                str(PACKAGE / "read_parameters.py"),
                str((directory / "request.json").resolve()),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired as error:
        _json(
            directory / "process.json",
            {
                "execution": "timeout",
                "timeout_seconds": error.timeout,
                "stdout": str(error.stdout),
                "stderr": str(error.stderr),
            },
        )
        _json(
            directory / "validation.json",
            {
                "passed": False,
                "reason": "process_timeout",
                "batch_contract": batch_details,
            },
        )
        raise RuntimeError(
            "fresh parameter read timed out; evidence retained"
        ) from error
    wall_seconds = time.perf_counter() - started
    (directory / "stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (directory / "stderr.txt").write_text(completed.stderr, encoding="utf-8")
    _json(
        directory / "process.json",
        {"returncode": completed.returncode, "cold_process_seconds": wall_seconds},
    )
    try:
        actual = json.loads(completed.stdout)
    except json.JSONDecodeError:
        actual = None
    _json(directory / "actual-result.json", actual)
    output = dict(actual) if isinstance(actual, dict) else {}
    actual_predictions = output.get("predictions")
    checks = {
        "process_succeeded": completed.returncode == 0,
        "json_object": isinstance(actual, dict),
        "pid_is_fresh": type(output.get("pid")) is int and output["pid"] != os.getpid(),
        "predictions_equal": actual_predictions == expected,
        "artifact_digest_equal": output.get("artifact_digest")
        == manifest["manifest_sha256"],
        "encoder_digest_equal": output.get("encoder_digest") == encoder.digest,
        "artifact_files_equal": output.get("opened_artifact_files")
        == ["manifest.json", "tensors.npz"],
        "base_files_equal": output.get("opened_base_files")
        == sorted(["source.json", *encoder.source["files"]]),
    }
    if cached_features is not None:
        checks["training_and_request_batch_features_equal"] = batch_details[
            "exact_features_equal"
        ]
    predictions = actual_predictions if isinstance(actual_predictions, list) else []
    mismatches = [
        {
            "index": i,
            "expected": expected[i] if i < len(expected) else None,
            "actual": predictions[i] if i < len(predictions) else None,
        }
        for i in range(max(len(expected), len(predictions)))
        if i >= len(expected) or i >= len(predictions) or expected[i] != predictions[i]
    ]
    _json(
        directory / "validation.json",
        {
            "passed": all(checks.values()),
            "checks": checks,
            "prediction_mismatches": mismatches,
            "batch_contract": batch_details,
        },
    )
    output.update(
        cold_process_seconds=wall_seconds,
        in_process_validation_seconds=in_process_seconds,
        predictions_match_in_process=checks["predictions_equal"],
        query_count=len(texts),
        validation_passed=all(checks.values()),
        batch_contract=batch_details,
    )
    _json(directory / "result.json", output)
    if not all(checks.values()):
        failed = ", ".join(name for name, passed in checks.items() if not passed)
        raise ValueError("fresh read validation failed; evidence retained: " + failed)
    return output


def _run_seed(profile, output, source_commit, seed, encoder, base_path):
    started = time.perf_counter()
    output.mkdir(parents=True, exist_ok=False)
    bundles = build_real_tasks(development_seed=seed)
    events = union_events(bundles)
    if len(events) > profile["max_training_events"]:
        raise ValueError("real-source write set exceeds the frozen capacity bound")
    source_bindings = bundles["semantic"].sources
    if any(bundle.sources != source_bindings for bundle in bundles.values()):
        raise ValueError("task families disagree about their source identities")
    provenance_path = PACKAGE / "sources" / "SOURCES.json"
    provenance = provenance_path.read_bytes()
    source_bindings = (
        *source_bindings,
        {
            "source_id": "SOURCES.json",
            "bytes": len(provenance),
            "sha256": sha(provenance),
            "source_kind": "pinned_source_provenance_manifest",
        },
    )
    index = AddressIndex.from_events(events)
    index.save(output / "common" / "address-index.json")
    index = AddressIndex.load(output / "common" / "address-index.json")
    _json(
        output / "common" / "retained-writes.json", [asdict(event) for event in events]
    )
    _json(output / "common" / "source-bindings.json", source_bindings)
    _json(
        output / "common" / "given-edges.json", bundles["composition"].metadata["edges"]
    )
    source_setup_seconds = time.perf_counter() - started
    _json(
        output / "evaluation" / "task-metadata.json",
        {name: bundle.metadata for name, bundle in bundles.items()},
    )
    for split in ("train", "selection", "test"):
        _json(
            output / "evaluation" / f"{split}-queries.json",
            [
                asdict(query)
                for bundle in bundles.values()
                for query in getattr(bundle, split)
            ],
        )
    training = [event for event in events if not event.deleted]
    texts = [
        address_text(event.cell_type, event.key, event.revision) for event in training
    ]
    started = time.perf_counter()
    features = encoder.encode(texts)
    training_encoding_seconds = time.perf_counter() - started
    started = time.perf_counter()
    catalogs = {}
    for kind in KINDS:
        catalog = ValueCatalog(
            [event.value for event in training if event.cell_type == kind]
        )
        path = output / "multi" / "catalogs" / f"{kind}.json"
        catalog.save(path)
        catalogs[kind] = ValueCatalog.load(path)
    multi_catalog_seconds = time.perf_counter() - started
    started = time.perf_counter()
    global_catalog = ValueCatalog([event.value for event in training])
    global_catalog.save(output / "single" / "catalog.json")
    global_catalog = ValueCatalog.load(output / "single" / "catalog.json")
    single_catalog_seconds = time.perf_counter() - started
    started = time.perf_counter()
    router, routing_receipt, _ = fit_router(
        bundles, profile, seed, output / "multi" / "router"
    )
    router_write_seconds = time.perf_counter() - started
    _json(output / "multi" / "routing-training.json", routing_receipt)

    models, untrained, receipts, positions = {}, {}, {}, {}
    multi_write_seconds, untrained_write_seconds = 0.0, 0.0
    for offset, kind in enumerate(KINDS):
        positions[kind] = [
            i for i, event in enumerate(training) if event.cell_type == kind
        ]
        members = [training[i] for i in positions[kind]]
        support_digest = sha(
            canonical(
                {
                    "events": [asdict(event) for event in members],
                    "sources": source_bindings,
                }
            )
        )
        cell = MemoryCell(
            encoder.dim, profile["rank_per_type"], catalogs[kind].classes, seed + offset
        )
        started = time.perf_counter()
        save_cell(
            cell,
            output / "untrained" / "cells" / kind,
            encoder.manifest(),
            source_commit=source_commit,
            support_digest=support_digest,
        )
        untrained[kind], _ = load_cell(
            output / "untrained" / "cells" / kind,
            expected_encoder_digest=encoder.digest,
        )
        untrained_write_seconds += time.perf_counter() - started
        started = time.perf_counter()
        targets = np.asarray([catalogs[kind].encode(event.value) for event in members])
        receipts[kind] = cell.fit(
            features[positions[kind]],
            targets,
            steps=profile["steps"],
            lr=profile["learning_rate"],
        )
        save_cell(
            cell,
            output / "multi" / "cells" / kind,
            encoder.manifest(),
            source_commit=source_commit,
            support_digest=support_digest,
        )
        models[kind], _ = load_cell(
            output / "multi" / "cells" / kind, expected_encoder_digest=encoder.digest
        )
        multi_write_seconds += time.perf_counter() - started
    _json(output / "multi" / "training.json", receipts)
    multi_parameters = (
        sum(cell.trainable_params for cell in models.values()) + router.trainable_params
    )
    single_rank = math.ceil(multi_parameters / (encoder.dim + global_catalog.classes))
    single = MemoryCell(encoder.dim, single_rank, global_catalog.classes, seed)
    started = time.perf_counter()
    single_receipt = single.fit(
        features,
        np.asarray([global_catalog.encode(event.value) for event in training]),
        steps=profile["steps"],
        lr=profile["learning_rate"],
    )
    save_cell(
        single,
        output / "single" / "cell",
        encoder.manifest(),
        source_commit=source_commit,
        support_digest=sha(
            canonical(
                {
                    "events": [asdict(event) for event in training],
                    "sources": source_bindings,
                }
            )
        ),
    )
    single, _ = load_cell(
        output / "single" / "cell", expected_encoder_digest=encoder.digest
    )
    single_write_seconds = time.perf_counter() - started
    _json(output / "single" / "training.json", single_receipt)
    started = time.perf_counter()
    exact = ExactRead(index, events)
    _json(
        output / "exact" / "store.json",
        {"schema": "memory-cell-v2.explicit-store.v1", "address_values": exact.values},
    )
    exact_setup_seconds = time.perf_counter() - started

    fresh = {}
    for kind in KINDS:
        member_texts = [texts[i] for i in positions[kind]]
        fresh[kind] = _fresh(
            output / "multi" / "cells" / kind,
            member_texts,
            models[kind],
            encoder,
            base_path,
            output / "evaluation" / "fresh" / kind,
            cached_features=features[positions[kind]],
        )
    fresh["single"] = _fresh(
        output / "single" / "cell",
        texts[:128],
        single,
        encoder,
        base_path,
        output / "evaluation" / "fresh" / "single",
        cached_features=features[:128],
    )
    _json(
        output / "deployment-bindings.json",
        {
            "schema": "memory-cell-v2.real-deployment.v1",
            "source_commit": source_commit,
            "encoder_digest": encoder.digest,
            "address_index_sha256": index.to_dict()["sha256"],
            "catalog_sha256": {
                kind: sha(canonical(catalog.values))
                for kind, catalog in catalogs.items()
            },
            "global_catalog_sha256": sha(canonical(global_catalog.values)),
            "router_digest": router.manifest()["artifact_digest"],
            "given_edges": bundles["composition"].metadata["edges"],
        },
    )
    multi_read = ParameterRead(index, encoder, models, catalogs)
    single_read = ParameterRead(
        index, encoder, {"single": single}, {"single": global_catalog}, single=True
    )
    untrained_read = ParameterRead(index, encoder, untrained, catalogs)
    queries = [query for bundle in bundles.values() for query in bundle.test]
    results = {}
    arms = {
        "multi_typed": (multi_read, "typed"),
        "multi_literal": (multi_read, "literal"),
        "multi_learned": (multi_read, "learned"),
        "single_schema": (single_read, "typed"),
        "single_learned_route": (single_read, "learned"),
        "exact": (exact, "typed"),
        "untrained_typed": (untrained_read, "typed"),
    }
    for name, (reader, route_mode) in arms.items():
        result, rows = evaluate(queries, reader, exact, router, route_mode)
        results[name] = result
        _json(output / "evaluation" / f"{name}.json", {"metrics": result, "rows": rows})
    transform, mapping = _shuffle(index, seed)
    _json(output / "evaluation" / "edge-permutation.json", mapping)
    for model_name, reader, route_mode in (
        ("multi", multi_read, "learned"),
        ("exact", exact, "typed"),
    ):
        for ablation, edge_transform in (
            ("no_edges", lambda value, kind: None),
            ("shuffled_edges", transform),
        ):
            name = f"{model_name}_{ablation}"
            result, rows = evaluate(
                list(bundles["composition"].test),
                reader,
                exact,
                router,
                route_mode,
                edge_transform,
            )
            results[name] = result
            _json(
                output / "evaluation" / f"{name}.json",
                {"metrics": result, "rows": rows},
            )

    bindings_bytes = _bytes(output / "deployment-bindings.json")
    shared_bytes = (
        _bytes(output / "common")
        + bindings_bytes
        + sum(source["bytes"] for source in source_bindings)
    )
    catalogs_bytes = _bytes(output / "multi" / "catalogs")
    reader_manifest_bytes = _bytes(PACKAGE / "MODEL_SOURCE.json")
    standalone = {
        "multi": {
            "retained_bytes": shared_bytes
            + encoder.base_bytes
            + reader_manifest_bytes
            + _bytes(output / "multi"),
            "parameter_bytes": sum(cell.parameter_bytes for cell in models.values())
            + router.parameter_bytes,
            "model_write_seconds": multi_write_seconds
            + router_write_seconds
            + multi_catalog_seconds,
            "validation_in_process_seconds": sum(
                fresh[kind]["in_process_validation_seconds"] for kind in KINDS
            ),
            "validation_cold_seconds": sum(
                fresh[kind]["cold_process_seconds"] for kind in KINDS
            ),
        },
        "single": {
            "retained_bytes": shared_bytes
            + encoder.base_bytes
            + reader_manifest_bytes
            + _bytes(output / "single"),
            "parameter_bytes": single.parameter_bytes,
            "model_write_seconds": single_write_seconds + single_catalog_seconds,
            "validation_in_process_seconds": fresh["single"][
                "in_process_validation_seconds"
            ],
            "validation_cold_seconds": fresh["single"]["cold_process_seconds"],
        },
        "exact": {
            "retained_bytes": shared_bytes + _bytes(output / "exact"),
            "parameter_bytes": 0,
            "model_write_seconds": exact_setup_seconds,
            "validation_cold_seconds": 0.0,
            "validation_in_process_seconds": 0.0,
        },
        "untrained": {
            "retained_bytes": shared_bytes
            + encoder.base_bytes
            + reader_manifest_bytes
            + _bytes(output / "untrained")
            + catalogs_bytes,
            "parameter_bytes": sum(cell.parameter_bytes for cell in untrained.values()),
            "model_write_seconds": untrained_write_seconds + multi_catalog_seconds,
            "validation_cold_seconds": 0.0,
            "validation_in_process_seconds": 0.0,
        },
    }
    cost = {
        "standalone_arms": standalone,
        "shared_base_bytes_once": encoder.base_bytes,
        "source_content_bytes": sum(source["bytes"] for source in source_bindings),
        "source_provenance_manifest_bytes_included": len(provenance),
        "reader_pinned_base_manifest_bytes": reader_manifest_bytes,
        "source_bindings_bytes": _bytes(output / "common" / "source-bindings.json"),
        "deployment_bindings_bytes": bindings_bytes,
        "address_index_bytes": _bytes(output / "common" / "address-index.json"),
        "retained_write_bytes": _bytes(output / "common" / "retained-writes.json"),
        "multi_catalog_bytes": catalogs_bytes,
        "single_catalog_bytes": _bytes(output / "single" / "catalog.json"),
        "router_artifact_bytes": _bytes(output / "multi" / "router"),
        "multi_adapter_bytes": _bytes(output / "multi" / "cells"),
        "single_adapter_bytes": _bytes(output / "single" / "cell"),
        "source_and_index_setup_seconds": source_setup_seconds,
        "shared_training_encoding_seconds": training_encoding_seconds,
        "training_feature_bytes_ephemeral": features.nbytes,
        "accounting_scope": "standalone arm includes base once when used, complete source content, retained writes, index, given edges, shared deployment bindings, catalogs, adapters and training receipts; evaluation logs excluded; dependency runtime binaries excluded",
        "single_learned_route_diagnostic_extra_router_bytes": _bytes(
            output / "multi" / "router"
        ),
        "single_learned_route_diagnostic_extra_trainable_params": router.trainable_params,
    }
    summary = {
        "seed": seed,
        "write_events": len(events),
        "training_events": len(training),
        "type_counts": {kind: len(positions[kind]) for kind in KINDS},
        "class_counts": {
            **{kind: catalogs[kind].classes for kind in KINDS},
            "global": global_catalog.classes,
        },
        "multi_trainable_params_including_router": multi_parameters,
        "single_trainable_params": single.trainable_params,
        "single_rank": single_rank,
        "budget_rounding_extra_single_params": single.trainable_params
        - multi_parameters,
        "routing_training": routing_receipt,
        "training": {"multi": receipts, "single": single_receipt},
        "results": results,
        "cost": cost,
        "fresh_process_validation": {
            name: {
                key: result[key]
                for key in (
                    "pid",
                    "artifact_digest",
                    "query_count",
                    "predictions_match_in_process",
                    "validation_passed",
                    "batch_contract",
                    "in_process_validation_seconds",
                    "cold_process_seconds",
                    "load_seconds",
                    "read_seconds",
                )
            }
            for name, result in fresh.items()
        },
        "oracle_route_gaps": {
            task: results["multi_typed"]["tasks"][task]["final_accuracy"]
            - metrics["final_accuracy"]
            for task, metrics in results["multi_learned"]["tasks"].items()
        },
        "learned_multi_minus_single": {
            task: metrics["final_accuracy"]
            - results["single_schema"]["tasks"][task]["final_accuracy"]
            for task, metrics in results["multi_learned"]["tasks"].items()
        },
    }
    _json(output / "metrics.json", summary)
    return summary


def run_real(protocol, out, source_commit, seeds, base_path, development=False):
    """Run a frozen real-source profile; development is confined to 8001/8003."""
    overrides = protocol.get("real_v2_profile", {})
    if set(overrides) - set(DEFAULT_PROFILE):
        raise ValueError("unknown real-study profile field")
    profile = {**DEFAULT_PROFILE, **overrides}
    if any(
        profile[key] != value
        for key, value in DEFAULT_PROFILE.items()
        if key != "steps"
    ):
        raise ValueError("real-study architecture and routing policy must stay frozen")
    if type(profile["steps"]) is not int or not 1 <= profile["steps"] <= 10000:
        raise ValueError("invalid real-study training schedule")
    if (
        type(development) is not bool
        or not isinstance(seeds, (list, tuple))
        or not seeds
        or len(set(seeds)) != len(seeds)
    ):
        raise ValueError("explicit development mode and distinct seeds are required")
    allowed = {8001, 8003} if development else set(protocol.get("seeds", ()))
    if any(type(seed) is not int or seed not in allowed for seed in seeds) or (
        not development and profile["steps"] != 600
    ):
        raise ValueError(
            "seed or schedule is outside the declared development/frozen protocol"
        )
    if (
        not isinstance(source_commit, str)
        or re.fullmatch(r"[0-9a-f]{40}", source_commit) is None
    ):
        raise ValueError("source_commit must identify the implementation")
    out = Path(out) / "real"
    out.mkdir(parents=True, exist_ok=False)
    pinned = json.loads((PACKAGE / "MODEL_SOURCE.json").read_bytes())
    started = time.perf_counter()
    encoder = MiniLMEncoder(base_path, expected_source_digest=sha(canonical(pinned)))
    base_load_seconds = time.perf_counter() - started
    _json(
        out / "config.json",
        {
            "profile": profile,
            "seeds": list(seeds),
            "development": development,
            "source_commit": source_commit,
            "encoder": encoder.manifest(),
            "encoder_digest": encoder.digest,
        },
    )
    runs = [
        _run_seed(
            profile, out / f"seed-{seed}", source_commit, seed, encoder, base_path
        )
        for seed in seeds
    ]
    aggregate = {}
    for arm, result in runs[0]["results"].items():
        aggregate[arm] = {}
        for task in result["tasks"]:
            rows = [run["results"][arm]["tasks"][task] for run in runs]
            aggregate[arm][task] = {
                "per_seed_queries": [row["queries"] for row in rows],
                "queries_total": sum(row["queries"] for row in rows),
                "seed_mean_final_accuracy": float(
                    np.mean([row["final_accuracy"] for row in rows])
                ),
                "seed_mean_event_value_identity": float(
                    np.mean([row["event_value_identity_accuracy"] for row in rows])
                ),
                "seed_mean_routing_accuracy": float(
                    np.mean([row["routing_accuracy"] for row in rows])
                ),
            }
    summary = {
        "schema": "memory-cell-v2.real-study.v1",
        "development": development,
        "development_only": development,
        "profile": profile,
        "seeds": list(seeds),
        "runs": runs,
        "task_summary": aggregate,
        "shared_base_load_seconds_once": base_load_seconds,
        "shared_base_bytes_once": encoder.base_bytes,
        "scope": "written repository facts plus primitive-rule execution on unseen inputs and two supplied typed chains",
        "routing_scope": "known public task cues; keys removed; not open-domain natural-language addressing",
        "selection_policy": "fixed profile; no selection-query feedback or hidden-test tuning",
        "independence": "seeds change query partitions, procedure probes and initialization; the source repository is shared",
        "temporal_reasoning_in_parameters": False,
        "graph_edges_learned": False,
        "stage3_learned_edge_selection": "partial-not-implemented",
        "general_memory_established": False,
    }
    _json(out / "summary.json", summary)
    return summary
