"""Actual pinned MiniLM vectors + equal-parameter *research* Cell type-split lesion.

This is intentionally an authored single-family source fixture. A lower loss does
not establish natural-language memory, future-window gain, source independence,
production status, or superiority to an indexed RAG system.
"""
from __future__ import annotations

from datetime import datetime
import json
import math
from pathlib import Path
import os
import sys
import time

import torch

from associative_cell import (
    AssociativeCell, ExperimentalBank, ReadQuery, TrainingCut, propose_split,
    sha256,
)
from associative_text_bridge import (
    PinnedTextProjection, prepare_experiences, source_facts, train_scope, cosine,
)
from associative_minilm_offline import MiniLMOfflineEncoder
from associative_minilm_probe import fixture

PROFILE = "hepta.associative-minilm-type-split-lesion.v1"


def run(encoder_dir, output_dir, *, pre_steps=64, post_steps=64, rank=4, dimension=64):
    """Compare same-weight ancestry, split routing, swapped routing and source NN.

    Shared continued: post_steps updates of rank R = post_steps * 2*R*D
    Split continued: post_steps per child of rank R/2 = same total touches.
    These estimates do NOT establish equal end-to-end FLOPs/latency or equal
    examples-per-step. Both differently-budgeted controls must be retained.
    """
    if (type(pre_steps) is not int or not 1 <= pre_steps <= 256
        or type(post_steps) is not int or not 1 <= post_steps <= 256
        or type(rank) is not int or rank % 2 or not 2 <= rank <= 16
        or type(dimension) is not int or not 2 <= dimension <= 256):
        raise ValueError("bounded matched-split experiment")
    output = Path(output_dir)
    output.mkdir(exist_ok=False)
    start = time.perf_counter()
    source = fixture()
    facts, exclusions = source_facts(source, logical_revision=2)
    encoder = MiniLMOfflineEncoder(encoder_dir)
    projection = PinnedTextProjection(encoder, dimension=dimension)
    rows = prepare_experiences(facts, projection, scope="shadow_scope")
    if {e.kind for e in rows} != {"semantic", "procedural"}:
        raise ValueError("two real source-derived kinds required")
    prior_threads = torch.get_num_threads()
    try:
        torch.set_num_threads(2)
        trained, trained_receipt = train_scope(
            rows, source, projection, steps=pre_steps, rank=rank
        )
        parent_bytes = trained.export()
        cut = TrainingCut(
            "shadow_scope", projection.identity,
            max(int(datetime.fromisoformat(d.observed_at).timestamp()) for d in source),
            frozenset(d.root for d in source),
            frozenset(r.family for r in rows),
            frozenset(), frozenset(), sha256(b"type-split-readonly-registered-source-cut"),
        )
        shared, shared_receipt = trained.propose_update(
            rows, cut, revoked=set(), steps=post_steps, lr=0.25
        )
        children = propose_split(trained)
        candidates = []
        for child in children:
            typed = tuple(row for row in rows if row.kind == child.kind)
            candidate, receipt = child.propose_update(
                typed, cut, revoked=set(), steps=post_steps, lr=0.25
            )
            candidates.append((candidate, receipt))
    finally:
        torch.set_num_threads(prior_threads)
    if sum(c.parameter_count() for c, _ in candidates) != trained.parameter_count():
        raise ValueError("child parameter capacity inflation")
    if sha256(trained.export()) != sha256(parent_bytes):
        raise ValueError("mutable current parent or lineage drift")
    if set().union(*(c.roots for c, _ in candidates)) != set(trained.roots):
        raise ValueError("parent source revocation dependencies lost")
    # Model tensors are the only inference-time parameter-memory payload.
    restored = []
    for child, _ in candidates:
        payload = child.export()
        restored.append(AssociativeCell.restore(
            payload, expected_sha256=sha256(payload),
            encoder_identity=projection.identity, scope="shadow_scope",
            allowed_roots=set(trained.roots), revoked=set(),
        ))
    bank = ExperimentalBank(tuple(restored))
    test_texts = [
        f"At logical revision 2, what is the recorded {f.attribute} identifier for {f.entity}?"
        for f in facts
    ]
    test_vectors = projection.encode(test_texts)
    metrics = {k: [] for k in ("split_correct", "split_swapped",
                                "shared_continued", "parent_before_continuation",
                                "cached_source_vector_nn")}
    cases = []
    for fact, query in zip(facts, test_vectors, strict=True):
        q = ReadQuery("shadow_scope", fact.kind, projection.identity, 1_800_000_000, query)
        target = projection.encode([fact.target])[0]
        ranked = sorted(rows, key=lambda e: (
            -(-1.0 if cosine(query, e.cue) is None else cosine(query, e.cue)), e.identity
        ))
        responses = {
            "parent_before_continuation": trained.read(q, revoked=set()),
            "shared_continued": shared.read(q, revoked=set()),
            "split_correct": bank.read(q, revoked=set()),
            "split_swapped": bank.read(q, revoked=set(), ablation="swapped"),
            "cached_source_vector_nn": ranked[0].value,
        }
        errors = {key: math.fsum((float(a)-float(b))**2
                  for a,b in zip(value,target,strict=True)) / dimension
                  for key,value in responses.items()}
        for key,value in errors.items():
            metrics[key].append(value)
        cases.append({"kind":fact.kind, "source_id":fact.identity,
                      "source_root":fact.root, "error_mse":errors})
    # Ancestral root revocation must block BOTH children, not selectively ignore
    # the parent's inherited roots when a child was trained only on one kind.
    revoked = {sorted(trained.roots)[0]}
    revoked_rejected = 0
    for fact, test_vector in zip(facts, test_vectors, strict=True):
        query = ReadQuery("shadow_scope", fact.kind, projection.identity,
                          1_800_000_000, test_vector)
        try:
            bank.read(query, revoked=revoked)
        except ValueError:
            revoked_rejected += 1
    if revoked_rejected != len(facts):
        raise ValueError("inherited lineage revocation was not enforced")
    shared_post_updates = post_steps
    child_post_updates = post_steps * 2
    shared_touches = shared_post_updates * trained.parameter_count()
    child_touches = post_steps * sum(c.parameter_count() for c in restored)
    if shared_touches != child_touches:
        raise ValueError("matched estimated optimizer parameter touches changed")
    report = {
        "schema": PROFILE,
        "encoder_identity": encoder.identity,
        "projection_identity": projection.identity,
        "native_pretrained_weights_executed": True,
        "transformers_reference_parity_verified": False,
        "source_provenance": "six authored controlled events, one common template family",
        "source_family_count_effective": 1,
        "same_sources_reused_in_queries": True,
        "independent_semantic_judge_executed": False,
        "pretrained_language_reader_executed": False,
        "strong_indexed_rag_executed": False,
        "true_future_calendar_windows": 0,
        "production_qualified": False,
        "superiority_claim": False,
        "parameters": {"shared":trained.parameter_count(),
                       "split_total": sum(c.parameter_count() for c in restored)},
        "budget": {"pretraining_updates":pre_steps,
                   "shared_post_updates":shared_post_updates,
                   "split_post_updates":child_post_updates,
                   "estimated_shared_post_parameter_touches":shared_touches,
                   "estimated_split_post_parameter_touches":child_touches,
                   "equal_total_optimizer_updates": False,
                   "equal_total_optimizer_parameter_touches":True,
                   "equal_end_to_end_compute_proven":False},
        "source_root_inheritance_preserved": True,
        "revoked_ancestor_blocks_both_children": True,
        "parent_unchanged": sha256(trained.export()) == sha256(parent_bytes),
        "trained_parent_digest": sha256(parent_bytes),
        "shared_continued_digest": sha256(shared.export()),
        "children_digests": {c.kind:sha256(c.export()) for c in restored},
        "mean_latent_mse": {key: math.fsum(v)/len(v) for key,v in metrics.items()},
        "cases":cases,
        "resource_accounting": {
            "staged_pretrained_encoder_files": sum(f["bytes"] for f in encoder.files.values()),
            "parent_artifact_bytes":len(parent_bytes),
            "shared_candidate_artifact_bytes":len(shared.export()),
            "child_artifact_bytes":sum(len(c.export()) for c in restored),
            "source_utf8_bytes":sum(len(d.content.encode("utf-8")) for d in source),
            "observed_wall_seconds":time.perf_counter()-start,
        },
        "limitations": [
            "Same authored source family is used for training and later queries",
            "Swapped-child routing is a lesion, not a calibrated deployed policy",
            "Numerical latent MSE is neither exact fact recall nor cited QA",
            "Cosine-vector nearest neighbor retains all source value vectors",
            "Per-parameter touches do not measure full FLOPs, latency, or optimizer memory",
            "HF numerical parity and independent data are not established locally",
        ],
    }
    data = (json.dumps(report,sort_keys=True,indent=2,allow_nan=False)+"\n").encode()
    with (output/"split-report.json").open("xb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    return report


if __name__ == "__main__":
    if len(sys.argv)!=3:
        raise SystemExit("usage: associative_minilm_split_trial.py PINNED_ENCODER_DIR EMPTY_OUTPUT_DIR")
    result=run(sys.argv[1],sys.argv[2])
    print(json.dumps(result["mean_latent_mse"],indent=2))
