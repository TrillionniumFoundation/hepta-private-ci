"""Frozen pretrained Stem -> low-rank MemoryCell -> evidence Reader, research only.

Shadow-only / DENY_ALL. Parameter memory emits a latent vector and uses the
source-held embedding catalogue for source-ID readout. This is NOT parameter-
only natural-language memory, real-world ground truth, or final-use authority.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import hashlib
import json
import math
import sys
import time

import numpy as np
import torch

import associative_graph_causal as graph
from associative_cell import AssociativeCell, Experience, ReadQuery, TrainingCut, sha256
from associative_minilm_offline import MiniLMOfflineEncoder
from associative_text_bridge import PinnedTextProjection

SCHEMA = "hepta.parametric-stem-reader.shadow.v1"
READER_SCHEMA = "hepta.parametric-stem-reader.original-smol-fp32.v1"
ARMS = ("bm25", "temporal", "dense", "rrf", "frozen_cell", "trained_cell", "rrf_cell")
READER_ARMS = ("empty", "temporal", "rrf", "trained_cell", "rrf_cell")
SOURCE_PER_FAMILY = 512
DIMENSION = 64
RANK = 8
STEPS = 384
SEED = 2718
SNIPPET_CHARS = 180
READ_CHARS = 300
QUESTION_PER_FAMILY = 1
READER_TOKENS = 48


def source_text(doc):
    return doc["speaker"] + ": " + doc["text"][:SNIPPET_CHARS]


def source_question(doc):
    """Never use hidden benchmark questions, answers, or evidence identities."""
    terms = []
    for word in graph.words(doc["text"]):
        if 3 <= len(word) <= 28 and word not in graph.STOPWORDS and word not in terms:
            terms.append(word)
            if len(terms) == 5:
                break
    if not terms:
        terms = graph.words(doc["text"])[:3]
    if not terms:
        terms = ["event", str(doc["seq"])]
    return f"What did {doc['speaker'][:48]} say about {' '.join(terms)}?"


def _encode(projection, texts):
    rows = []
    for start in range(0, len(texts), 16):
        rows.extend(projection.encode(texts[start:start + 16]))
    vectors = np.asarray(rows, dtype=np.float32)
    if (vectors.shape != (len(texts), DIMENSION)
            or not np.isfinite(vectors).all()):
        raise ValueError("bad frozen Encoder feature readout")
    norms = np.linalg.norm(vectors, axis=1)
    if np.any(norms < 1e-7):
        raise ValueError("zero source embedding")
    return vectors / norms[:, None]


def _rank(scores, docs):
    return [docs[i]["id"] for i in sorted(
        range(len(docs)), key=lambda i: (-float(scores[i]), docs[i]["id"])
    )[:graph.TOP_K]]


def _rrf(*rankings):
    scores = Counter()
    for ranking in rankings:
        for n, sid in enumerate(ranking):
            scores[sid] += 1 / (60 + n + 1)
    return scores


def _pool(section):
    if len(section["sources"]) < 128:
        raise ValueError("complete bounded source training cut required")
    docs = section["sources"][:SOURCE_PER_FAMILY]
    if len({d["id"] for d in docs}) != len(docs):
        raise ValueError("duplicate source root")
    return docs


def train_section(section, projection):
    """All source cues and targets are from original chronological messages."""
    docs = _pool(section)
    family = section["family"]
    cues = _encode(projection, [source_question(d) for d in docs])
    values = _encode(projection, [source_text(d) for d in docs])
    identity = projection.identity
    parent = AssociativeCell(DIMENSION, RANK, identity, family, "mixed", seed=SEED)
    rows = [Experience(identity=d["id"], scope=family, family=family,
                       root=d["id"], kind="semantic", encoder_identity=identity,
                       observed_at=d["seq"], cue=tuple(map(float, cues[i])),
                       value=tuple(map(float, values[i])))
            for i, d in enumerate(docs)]
    roots = frozenset(d["id"] for d in docs)
    cut = TrainingCut(scope=family, encoder_identity=identity,
                      through=max(d["seq"] for d in docs), allowed_roots=roots,
                      allowed_families=frozenset({family}), forbidden_roots=frozenset(),
                      forbidden_families=frozenset(),
                      admission_digest=sha256(graph.canonical({
                          "scope": family, "roots": sorted(roots),
                          "source_sha256": graph.DATASET_SHA256,
                          "projection_identity": identity,
                      })))
    candidate, receipt = parent.propose_update(rows, cut, revoked=frozenset(),
                                                steps=STEPS, lr=0.15)
    if (candidate.roots != set(roots) or receipt["train_examples"] != len(docs)
            or receipt["trainable_parameters"] != 2 * DIMENSION * RANK):
        raise ValueError("train cut missing required source root")
    # Explicit clean-process artifact roundtrip; no input values or raw source
    # strings are allowed in the weight artifact.
    raw = candidate.export()
    restored = AssociativeCell.restore(
        raw, expected_sha256=sha256(raw), encoder_identity=identity,
        scope=family, allowed_roots=set(roots), revoked=frozenset())
    return docs, values, parent, restored, raw, receipt


def rank_section(section, projection):
    family = section["family"]
    docs, values, parent, cell, raw, receipt = train_section(section, projection)
    edges = graph.graph_edges(docs)
    scores_by_query = []
    q_vectors = _encode(projection, [q["text"] for q in section["questions"]])
    scope_clock = max(d["seq"] for d in docs) + 1
    for query, query_vector in zip(section["questions"], q_vectors):
        question = query["text"]
        # The explicit source pool is shared by all seven arms.
        bm25 = graph.bm25_scores([d["speaker"] + ": " + d["text"] for d in docs], question)
        baseline, _ = graph.rank_arms(docs, question, family, existing_edges=edges)
        dense = _rank(values @ query_vector, docs)
        bm25_ids = _rank(bm25, docs)
        dense_full = _rank(values @ query_vector, docs)
        temporal_edges = tuple(e for e in edges if e[0] == "temporal")
        boosts = graph.propagated(bm25, temporal_edges)
        maximum = max(bm25, default=0.0)
        temporal_scores = [(v / maximum if maximum else 0.0) + 0.92 * b
                           for v, b in zip(bm25, boosts)]
        temporal_full = _rank(temporal_scores, docs)
        temporal = baseline["temporal"]
        if temporal_full[:graph.TOP_K] != temporal:
            raise ValueError("temporal reexecution baseline drift")
        all_ids = [d["id"] for d in docs]
        query_input = ReadQuery(scope=family, kind="semantic", encoder_identity=projection.identity,
                                as_of=scope_clock, cue=tuple(map(float, query_vector)))
        frozen_output = np.asarray(parent.read(query_input, revoked=frozenset()), dtype=np.float32)
        trained_output = np.asarray(cell.read(query_input, revoked=frozenset()), dtype=np.float32)
        frozen_scores = values @ frozen_output
        trained_scores = values @ trained_output
        frozen_rank = _rank(frozen_scores, docs)
        param_rank = _rank(trained_scores, docs)
        rrf = _rrf(bm25_ids, dense_full, temporal_full)
        joint = _rrf(bm25_ids, dense_full, temporal_full, param_rank)
        order = lambda scores: sorted(all_ids, key=lambda x: (-scores.get(x, 0), x))[:graph.TOP_K]
        ranks = {"bm25": bm25_ids, "temporal": temporal, "dense": dense,
                 "rrf": order(rrf), "frozen_cell": frozen_rank,
                 "trained_cell": param_rank, "rrf_cell": order(joint)}
        if set(ranks) != set(ARMS) or any(len(x) != graph.TOP_K for x in ranks.values()):
            raise ValueError("incomplete fixed-budget source readout")
        scores_by_query.append({"family": family, "question_id": query["id"], "arms": ranks})
    return scores_by_query, raw, receipt


def generate_predictions(public, encoder_dir):
    graph.validate_public(public)
    encoder = MiniLMOfflineEncoder(encoder_dir)
    projection = PinnedTextProjection(encoder, dimension=DIMENSION, seed=SEED)
    rows, artifacts, receipts = [], {}, {}
    for section in public["families"]:
        predictions, artifact, receipt = rank_section(section, projection)
        rows.extend(predictions)
        artifacts[section["family"]] = artifact
        receipts[section["family"]] = receipt
    if len(rows) != 240 or len(artifacts) != 10:
        raise ValueError("source-only prediction census incomplete")
    manifest = {"schema": SCHEMA, "source_sha256": graph.DATASET_SHA256,
                "encoder_identity": encoder.identity,
                "projected_identity": projection.identity,
                "training_source_prefix_per_family": SOURCE_PER_FAMILY,
                "head_rank": RANK, "head_dimension": DIMENSION,
                "per_family_parameters": 2 * DIMENSION * RANK,
                "per_family_SGD_steps": STEPS,
                "frozen_encoder_calls": encoder.calls,
                "frozen_encoded_texts": projection.encoded_texts,
                "truncated_encoder_inputs": encoder.truncated_inputs,
                "catalogue_required_for_parametric_readout": True,
                "reader_calls": 0, "labels_visible": False,
                "production_accepted": False}
    return rows, artifacts, receipts, manifest


def run(public_dir, encoder_dir, output_dir):
    public, manifest = graph.load_public(public_dir)
    started = time.perf_counter()
    rows, artifacts, receipts, model = generate_predictions(public, encoder_dir)
    dest = Path(output_dir)
    dest.mkdir(exist_ok=False)
    candidates = dest / "cells"
    candidates.mkdir()
    cells = {}
    for family, raw in sorted(artifacts.items()):
        cells[family] = graph.create_only(candidates / f"{family}.json", raw)
    journal = {"schema": SCHEMA, "public_sha256": manifest["public_sha256"],
               "source_sha256": graph.DATASET_SHA256, "arms": list(ARMS),
               "top_k": graph.TOP_K, "rows": rows, "cells": cells,
               "training_receipts": receipts, "model": model}
    journal_digest = graph.create_only(dest / "predictions.json", journal)
    seal = {"schema": SCHEMA, "public_sha256": manifest["public_sha256"],
            "predictions_sha256": journal_digest, "number_questions": len(rows),
            "cells": cells, "model_identity": model["projected_identity"],
            "seconds": time.perf_counter() - started, "labels_visible": False,
            "production_accepted": False}
    graph.create_only(dest / "seal.json", seal)
    return seal


def verified_run(public_dir, run_dir, encoder_dir):
    """Independently reexecute original weights before authorizing any reference read."""
    public, m = graph.load_public(public_dir, reviewer=True)
    root = Path(run_dir)
    seal = graph.strict_load(graph.regular_bytes(root / "seal.json"))
    original_raw = graph.regular_bytes(root / "predictions.json", limit=8 * 1024 * 1024)
    journal = graph.strict_load(original_raw)
    if (not isinstance(seal, dict)
            or set(seal) != {"schema", "public_sha256", "predictions_sha256",
                                "number_questions", "cells", "model_identity", "seconds",
                                "labels_visible", "production_accepted"}
            or seal["schema"] != SCHEMA or seal["public_sha256"] != m["public_sha256"]
            or seal["predictions_sha256"] != graph.digest(original_raw)
            or seal["number_questions"] != 240
            or type(seal["seconds"]) not in (float, int)
            or not math.isfinite(seal["seconds"]) or seal["seconds"] < 0
            or seal["labels_visible"] is not False
            or seal["production_accepted"] is not False):
        raise ValueError("untrusted source-only model receipt")
    rows, artifacts, receipts, model = generate_predictions(public, encoder_dir)
    checksums = {family: graph.digest(raw) for family, raw in artifacts.items()}
    expected = {"schema": SCHEMA, "public_sha256": m["public_sha256"],
                "source_sha256": graph.DATASET_SHA256, "arms": list(ARMS),
                "top_k": graph.TOP_K, "rows": rows, "cells": checksums,
                "training_receipts": receipts, "model": model}
    if (journal != expected or graph.canonical(expected) != original_raw
            or seal["cells"] != checksums
            or seal["model_identity"] != model["projected_identity"]):
        raise ValueError("untrusted candidate or original inference mismatch")
    for family, raw in artifacts.items():
        if graph.regular_bytes(root / "cells" / f"{family}.json") != raw:
            raise ValueError("tampered Cell weights or ancestry")
    return public, m, journal, seal


def review(prepared, run_dir, encoder_dir, target):
    public, manifest, journal, seal = verified_run(prepared, run_dir, encoder_dir)
    # Reference-only input is first opened AFTER full real-Encoder reexecution.
    hidden_raw = graph.regular_bytes(Path(prepared) / "private.json")
    if graph.digest(hidden_raw) != manifest["private_sha256"]:
        raise ValueError("original reference digest mismatch")
    original = graph.strict_load(hidden_raw)
    if original.get("schema") != graph.SCHEMA or not isinstance(original.get("annotations"), dict):
        raise ValueError("unregistered retrospective annotation input")
    found, totals = set(), {arm: Counter() for arm in ARMS}
    available = {g["family"]: {d["id"] for d in _pool(g)} for g in public["families"]}
    for row in journal["rows"]:
        label = original["annotations"].get(row["question_id"])
        if not isinstance(label, dict) or set(label) != {"evidence", "unresolved_reference"}:
            raise ValueError("missing or foreign source label")
        if not isinstance(label["evidence"], list) or type(label["unresolved_reference"]) is not bool:
            raise ValueError("malformed source label")
        roots = set(label["evidence"])
        if not label["unresolved_reference"] and roots:
            found.add(row["question_id"])
            for arm in ARMS:
                totals[arm]["positive"] += 1
                totals[arm]["available"] += int(roots <= available[row["family"]])
                totals[arm]["complete_at_8"] += int(roots <= set(row["arms"][arm]))
                totals[arm]["any_at_8"] += int(bool(roots & set(row["arms"][arm])))
        else:
            for arm in ARMS:
                totals[arm]["unresolved_or_zero"] += 1
    if len(journal["rows"]) != 240 or len(found) != 238:
        raise ValueError("changed original full source evaluation denominator")
    report = {"schema": SCHEMA, "source_sha256": graph.DATASET_SHA256,
              "original_input_sha256": manifest["public_sha256"],
              "original_model_journal_sha256": seal["predictions_sha256"],
              "by_arm": {arm: dict(x) for arm, x in totals.items()},
              "source_families": 10, "questions": 240, "canonical_references": len(found),
              "genuine_frozen_encoder_used": True,
              "native_transformers_numerical_parity": False,
              "source_catalogue_required_for_all_parametric_readout": True,
              "reader_executed": False, "semantic_answer_evaluated": False,
              "prospective_source_families": False,
              "full_lifecycle_cost_measured": False,
              "statistical_superiority": False, "production_accepted": False}
    graph.create_only(target, report)
    return report


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) == 4 and args[0] == "run":
        result = run(args[1], args[2], args[3])
    elif len(args) == 5 and args[0] == "review":
        result = review(args[1], args[2], args[3], args[4])
    else:
        raise SystemExit("run PUBLIC ENCODER NEW_RUN | review PREPARED RUN ENCODER NEW_REVIEW")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
