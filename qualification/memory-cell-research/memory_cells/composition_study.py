"""Executed fixed-scaffold composition study with learned cell values.

The writer stores random associations in small numerical models. Node kinds and
the three-step program are supplied, not discovered, and keys are canonicalized
before model input. This study makes no natural-language or topology-learning claim.
"""

from dataclasses import asdict, replace
from hashlib import sha256
import json
from pathlib import Path
import time

import numpy as np

from .data import MemoryEvent, dataset_from_events, make_associative, slot_key
from .encoding import FrozenEncoder, canonical_bytes
from .graph import CellEdge, CellNode, CellRead, TypedGraph
from .metrics import measure_bytes, summarize_predictions
from .model import MemoryCell


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )


def revision_id(event):
    return f"{event.record_id}@{event.revision}:{event.source_sha256}"


def typed_keys(queries):
    return [f"{query.domain} {query.key}" for query in queries]


def train_artifact(
    cell,
    dataset,
    encoder,
    directory,
    protocol,
    source_commit,
    *,
    parent=None,
    targets=None,
):
    """Fit only declared write examples and reload the saved tensor artifact."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    labels = (
        [query.target for query in dataset.train] if targets is None else list(targets)
    )
    training = {
        "source_revisions": [revision_id(event) for event in dataset.events],
        "inputs": typed_keys(dataset.train),
        "targets": [int(y) for y in labels],
        "query_ids": [query.query_id for query in dataset.train],
        "parent": parent,
        "source_commit": source_commit,
    }
    write_json(directory / "training-data.json", training)
    training_digest = sha256(canonical_bytes(training)).hexdigest()
    began = time.perf_counter()
    X = encoder.encode(training["inputs"])
    encoding_seconds = time.perf_counter() - began
    receipt = cell.fit(
        X,
        np.asarray(labels, dtype=np.int64),
        steps=protocol["optimizer_steps"],
        lr=protocol["learning_rate"],
    )
    lineage = {"dataset": training_digest, "source_commit": source_commit}
    if parent is not None:
        lineage["parent"] = parent
    began = time.perf_counter()
    manifest = cell.save(
        directory / "model", encoder_manifest=encoder.manifest(), lineage=lineage
    )
    save_seconds = time.perf_counter() - began
    began = time.perf_counter()
    loaded = MemoryCell.load(
        directory / "model", expected_encoder_digest=encoder.digest
    )
    receipt = {
        **receipt,
        "encoding_seconds": encoding_seconds,
        "save_seconds": save_seconds,
        "reload_seconds": time.perf_counter() - began,
        "training_data_sha256": training_digest,
        "artifact_manifest_sha256": manifest["manifest_sha256"],
    }
    write_json(directory / "training-receipt.json", receipt)
    return loaded, manifest, receipt


def predict_queries(cell, queries, encoder):
    began = time.perf_counter()
    predictions = cell.predict(encoder.encode(typed_keys(queries))).tolist()
    return predictions, time.perf_counter() - began


def _chain(seed, branch, size, classes):
    prefix = f"chain-{branch}"
    first = make_associative(
        seed + branch * 1009, (size,), classes, (f"episodic-{prefix}",)
    )
    rng = np.random.default_rng(np.random.SeedSequence([seed, branch, 419]))
    first_values, second_values, final_values = (
        rng.permutation(size),
        rng.permutation(size),
        rng.integers(classes, size=size),
    )
    first_events = tuple(
        replace(
            event,
            value=int(first_values[i]),
            source_sha256=sha256(
                canonical_bytes(
                    {"parent": event.source_sha256, "value": int(first_values[i])}
                )
            ).hexdigest(),
        )
        for i, event in enumerate(first.events)
    )
    stages = [dataset_from_events(first_events)]
    for kind, values in (("semantic", second_values), ("procedural", final_values)):
        events = []
        for index, value in enumerate(values):
            record = {
                "seed": seed,
                "branch": branch,
                "kind": kind,
                "key": slot_key(index),
                "value": int(value),
            }
            events.append(
                MemoryEvent(
                    f"composition:{seed}:{branch}:{kind}:{index}",
                    slot_key(index),
                    f"{kind}-{prefix}",
                    int(value),
                    1,
                    f"synthetic://composition/{seed}/{branch}/{kind}/{index}",
                    sha256(canonical_bytes(record)).hexdigest(),
                )
            )
        stages.append(dataset_from_events(events))
    # Evaluation labels are computed outside all cell-reader callbacks.
    final_by_key = {
        event.key: int(final_values[second_values[event.value]])
        for event in first_events
    }
    queries = tuple(replace(q, target=final_by_key[q.key]) for q in stages[0].test[::2])
    return stages, queries


def run_composition(
    protocol, output_dir: Path, source_commit: str, seeds: list[int]
) -> dict:
    profile = dict(protocol["composition_profile"])
    if profile["chains"] != 2 or profile["cells_per_chain"] != 3:
        raise ValueError("this frozen study requires two three-step chains")
    size, classes = profile["records_per_cell"], protocol["num_classes"]
    if not 1 <= size <= classes:
        raise ValueError("composition associations must fit fixed symbol vocabulary")
    directory = Path(output_dir) / "composition"
    directory.mkdir(parents=True, exist_ok=False)
    config = {
        "protocol": protocol,
        "profile": profile,
        "source_commit": source_commit,
        "seeds": seeds,
    }
    write_json(directory / "config.json", config)
    runs = []
    for seed in seeds:
        run_started = time.perf_counter()
        seed_dir = directory / f"seed-{seed}"
        seed_dir.mkdir()
        encoder = FrozenEncoder(protocol["feature_dim"], seed=0)
        models, manifests, receipts, domains, sources, queries, nodes, edges = (
            {},
            {},
            {},
            {},
            {},
            [],
            [],
            [],
        )
        for branch in range(2):
            datasets, branch_queries = _chain(seed, branch, size, classes)
            queries.extend((branch, query) for query in branch_queries)
            for index, (kind, dataset) in enumerate(
                zip(("episodic", "semantic", "procedural"), datasets)
            ):
                cell_id = f"{kind}-{branch}"
                cell = MemoryCell(
                    encoder.dim, profile["rank"], classes, seed + branch * 11 + index
                )
                models[cell_id], manifests[cell_id], receipts[cell_id] = train_artifact(
                    cell,
                    dataset,
                    encoder,
                    seed_dir / "candidates" / cell_id,
                    protocol,
                    source_commit,
                )
                domains[cell_id] = dataset.events[0].domain
                sources[cell_id] = dataset
                types = ("entity", "concept", "procedure", "answer")
                nodes.append(
                    CellNode(
                        cell_id,
                        kind,
                        types[index],
                        types[index + 1],
                        f"composition-{seed}",
                        manifests[cell_id]["manifest_sha256"],
                    )
                )
            edges.extend(
                (
                    CellEdge(f"episodic-{branch}", f"semantic-{branch}", "supports"),
                    CellEdge(f"semantic-{branch}", f"procedural-{branch}", "requires"),
                )
            )
        graph = TypedGraph(nodes, edges, max_steps=3)
        shuffled = graph.shuffled_edges(seed + 991)
        graph_metadata = {
            "nodes": [asdict(node) for node in graph.nodes],
            "edges": [asdict(edge) for edge in graph.edges],
            "shuffled_edges": [asdict(edge) for edge in shuffled.edges],
            "domains": domains,
            "scaffold": "supplied three-hop typed program",
            "learned_topology": False,
            "symbol_decoder": "slot_key(integer), data-independent",
        }
        write_json(seed_dir / "graph.json", graph_metadata)
        write_json(
            seed_dir / "corpus.json",
            {key: value.to_dict() for key, value in sources.items()},
        )
        exact_maps = {
            key: {e.key: e.value for e in dataset.events}
            for key, dataset in sources.items()
        }

        def read(cell_id, key):
            encoded_key = key if cell_id.startswith("episodic") else slot_key(int(key))
            probabilities = models[cell_id].proba(
                encoder.encode([f"{domains[cell_id]} {encoded_key}"])
            )[0]
            predicted = int(np.argmax(probabilities))
            return CellRead(str(predicted), float(probabilities[predicted]))

        observations, expected = [], [query.target for _, query in queries]
        predictions = {
            mode: [] for mode in ("typed", "no_edges", "shuffled", "exact_chained")
        }
        read_seconds = {mode: 0.0 for mode in predictions}
        calls = {mode: 0 for mode in predictions}
        for branch, query in queries:
            row = {
                "query_id": query.query_id,
                "key": query.key,
                "branch": branch,
                "target": query.target,
                "modes": {},
            }
            for mode, candidate in (
                ("typed", graph),
                ("no_edges", graph.no_edges()),
                ("shuffled", shuffled),
            ):
                started = time.perf_counter()
                result = candidate.run(
                    f"episodic-{branch}",
                    query.key,
                    read,
                    scope=f"composition-{seed}",
                    output_type="answer",
                )
                elapsed = time.perf_counter() - started
                value = int(result.value) if result.value is not None else None
                row["modes"][mode] = {
                    **asdict(result),
                    "prediction": value,
                    "seconds": elapsed,
                }
                predictions[mode].append(value)
                read_seconds[mode] += elapsed
                calls[mode] += result.calls
            started = time.perf_counter()
            intermediate = exact_maps[f"episodic-{branch}"][query.key]
            procedure = exact_maps[f"semantic-{branch}"][slot_key(intermediate)]
            value = exact_maps[f"procedural-{branch}"][slot_key(procedure)]
            elapsed = time.perf_counter() - started
            predictions["exact_chained"].append(value)
            read_seconds["exact_chained"] += elapsed
            calls["exact_chained"] += 3
            row["modes"]["exact_chained"] = {
                "prediction": value,
                "seconds": elapsed,
                "calls": 3,
            }
            observations.append(row)
        (seed_dir / "predictions.jsonl").write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in observations)
        )
        metrics = {
            mode: summarize_predictions(expected, values)
            for mode, values in predictions.items()
        }
        graph_change_count = sum(a != b for a, b in zip(graph.edges, shuffled.edges))
        run = {
            "seed": seed,
            "metrics": metrics,
            "read_seconds": read_seconds,
            "calls": calls,
            "source_records": 6 * size,
            "distinct_starting_queries": len(queries),
            "trainable_params": sum(cell.trainable_params for cell in models.values()),
            "parameter_bytes": sum(cell.parameter_bytes for cell in models.values()),
            "parameter_artifact_bytes": measure_bytes(
                [seed_dir / "candidates" / key / "model" for key in models]
            ),
            "graph_metadata_bytes": (seed_dir / "graph.json").stat().st_size,
            "source_corpus_bytes": (seed_dir / "corpus.json").stat().st_size,
            "training_seconds": sum(
                receipt["seconds"] for receipt in receipts.values()
            ),
            "total_candidate_write_seconds": sum(
                sum(
                    receipt[field]
                    for field in (
                        "seconds",
                        "encoding_seconds",
                        "save_seconds",
                        "reload_seconds",
                    )
                )
                for receipt in receipts.values()
            ),
            "study_wall_seconds": time.perf_counter() - run_started,
            "training_receipts": receipts,
            "changed_shuffled_edges": graph_change_count,
            "criterion_met": graph_change_count > 0
            and metrics["typed"]["accuracy"]
            > max(metrics["no_edges"]["accuracy"], metrics["shuffled"]["accuracy"]),
            "beats_exact_retrieval": metrics["typed"]["accuracy"]
            > metrics["exact_chained"]["accuracy"],
        }
        write_json(seed_dir / "summary.json", run)
        runs.append(run)
    result = {
        "stage": 3,
        "profile": profile,
        "runs": runs,
        "claim_scope": "learned numerical associations composed by a supplied three-hop graph; not learned graph topology, language understanding or a learned executable procedure",
    }
    write_json(directory / "summary.json", result)
    return result
