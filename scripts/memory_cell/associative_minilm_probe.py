"""Observed source-only ASCII CPU probe using pinned native MiniLM weights.

All six events are controlled fixtures, not independent families or real future
windows. Generated paraphrase queries reuse the same source roots: explicitly
NOT a cross-family generalization experiment. Reviewer targets are derived from
source event values; this code is for mechanics and resource diagnostics only.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import os
import sys
import time

import numpy as np
import torch

from associative_cell import AssociativeCell, ReadQuery, sha256
from associative_text_bridge import (
    PinnedTextProjection, source_facts, prepare_experiences, train_scope, cosine,
)
from associative_minilm_offline import MiniLMOfflineEncoder, PARITY_TEXTS

PROFILE = "hepta.associative-minilm-observed-ascii-shadow.v1"


@dataclass(frozen=True)
class Document:
    identity: str
    root: str
    scope: str
    observed_at: str
    content: str


def fixture():
    """No real-user facts, labels or hidden prompts. Source text supplies values."""
    source = (
        ("service_alpha", "owner", "team_red"),
        ("service_alpha", "location", "site_north"),
        ("service_alpha", "successful_mode", "mode_safe"),
        ("service_beta", "owner", "team_blue"),
        ("service_beta", "location", "site_east"),
        ("service_beta", "successful_mode", "mode_fast"),
    )
    documents = []
    for n,(entity, attribute, value) in enumerate(source):
        eid = f"evt_{n:02d}"
        event = dict(schema="hepta.controlled-event.v1", id=eid,
                     entity=entity, attribute=attribute, value=value,
                     revision=1, supersedes=[])
        documents.append(Document(eid, f"root_{n:02d}", "shadow_scope",
                            "2026-10-01T10:00:00+00:00",
                            json.dumps(event, sort_keys=True, separators=(",", ":"))))
    return tuple(documents)


def run(encoder_dir, output_dir, *, steps=160, rank=4, dimension=64):
    if (type(steps) is not int or not 1 <= steps <= 512
        or type(rank) is not int or not 1 <= rank <= 16
        or type(dimension) is not int or not 2 <= dimension <= 256):
        raise ValueError("bounded CPU probe configuration")
    result_path = Path(output_dir)
    result_path.mkdir(exist_ok=False)
    begin = time.perf_counter()
    encoder = MiniLMOfflineEncoder(encoder_dir)
    documents = fixture()
    facts, omitted = source_facts(documents)
    projection = PinnedTextProjection(encoder, dimension=dimension)
    experiences = prepare_experiences(facts, projection, scope="shadow_scope")
    parent = AssociativeCell(dimension, rank, projection.identity,
                             "shadow_scope", kind="mixed", seed=313)
    prior_threads = torch.get_num_threads()
    try:
        torch.set_num_threads(2)
        candidate, receipt = train_scope(experiences, documents, projection,
                                         steps=steps, rank=rank)
    finally:
        torch.set_num_threads(prior_threads)
    if sha256(parent.export()) != candidate.predecessor:
        raise ValueError("training parent identity drift")
    parent.roots.update(doc.root for doc in documents)
    raw = candidate.export()
    if any(f.value.encode() in raw for f in facts):
        raise ValueError("raw source value leaked into parameter artifact")
    model_path = result_path / "candidate.json"
    with model_path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    restored = AssociativeCell.restore(
        raw, expected_sha256=sha256(raw), encoder_identity=projection.identity,
        scope="shadow_scope", allowed_roots=set(candidate.roots), revoked=set())
    queries = [
        f"At logical revision 2, what is the recorded {f.attribute} identifier for {f.entity}?"
        for f in facts
    ]
    query_vectors = projection.encode(queries)
    rows = []
    for fact, x in zip(facts, query_vectors, strict=True):
        expected = projection.encode([fact.target])[0]
        q = ReadQuery("shadow_scope", fact.kind, projection.identity,
                      1_800_000_000, x)
        a = restored.read(q, revoked=set())
        b = parent.read(q, revoked=set())
        # This kNN retains the ENTIRE six-record source-derived vector table.
        # It is a vector control, not cached indexed strong RAG or an answer reader.
        def similarity(row):
            score = cosine(x, row.cue)
            return -1.0 if score is None else score
        ranked = sorted(experiences, key=lambda r: (-similarity(r), r.identity))
        neighbor = ranked[0]
        def mse(v):
            return sum((u-z)**2 for u,z in zip(v, expected, strict=True))/dimension
        rows.append(dict(kind=fact.kind, entity=fact.entity, attribute=fact.attribute,
                         observed_source=fact.identity, training_root=fact.root,
                         parametric_mse=mse(a), frozen_mse=mse(b),
                         cached_vector_nn_mse=mse(neighbor.value),
                         parametric_cosine=cosine(a, expected),
                         frozen_cosine=cosine(b, expected),
                         cached_vector_nn_cosine=cosine(neighbor.value, expected)))
    metrics = {arm: float(np.mean([r[arm] for r in rows])) for arm in (
        "parametric_mse", "frozen_mse", "cached_vector_nn_mse",
        "parametric_cosine", "frozen_cosine", "cached_vector_nn_cosine")}
    report = dict(schema=PROFILE, encoder_identity=encoder.identity,
                  native_weights_executed=True, transformers_parity_verified=False,
                  provenance="authored-controlled-source-fixture", source_family_count=1,
                  train_roots_reused_in_queries=True, real_future_windows=0,
                  pretrained_reader_executed=False, strong_tuned_rag_executed=False,
                  independent_semantic_adjudication=False, production_accepted=False,
                  superiority_claim=False, cases=rows, aggregate=metrics,
                  tensor_updates=receipt["tensor_delta_squared_norm"],
                  candidate_sha256=sha256(raw), frozen_parent_sha256=candidate.predecessor,
                  parameter_count=candidate.parameter_count(), training_steps=steps,
                  pretrained_model_inventory_bytes=sum(i["bytes"] for i in encoder.files.values()),
                  artifact_bytes=len(raw), actual_wall_seconds=time.perf_counter()-begin,
                  limitations=["Same source records enter training and reviewer-derived vector targets",
                               "The paraphrases are authored, not independently held-out human tasks",
                               "A retained-vector nearest-neighbor table is not strong cached RAG",
                               "Small parameter output cannot generate an exact or cited answer",
                               "Native/HF functional equivalence requires separate parity check"])
    packed = (json.dumps(report,sort_keys=True,indent=2,allow_nan=False)+"\n").encode()
    with (result_path / "report.json").open("xb") as stream:
        stream.write(packed)
        stream.flush()
        os.fsync(stream.fileno())
    return report


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: associative_minilm_probe.py PINNED_ENCODER_DIR EMPTY_OUTPUT_DIR")
    print(json.dumps(run(sys.argv[1],sys.argv[2])["aggregate"],indent=2))
