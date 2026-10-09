"""Public-development ranking experiment with native family cuts.

Only LoCoMo training families supervise updates. Selection families choose the
adapter or the strong frozen comparator once; held-out-family and LongMemEval
labels are used after all predictions. Previously disclosed corpora are not new
prospective evidence. Every planned success/failure remains in the denominator.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np
import torch

from grounded_protocol import ABSTAIN, verify_output
from index import PersistentIndex, RetrievalPolicy
from native import digest, load
from native_citation import capture_native
from pretrained import Encoder, file_inventory, frozen_digest
from relevance_protocol import candidate_pool, choose, passages, training_pairs
from relevance_ranker import RelevanceRanker, RANKER_ID, RANKER_REVISION
from run_native import chunks, f1
from sessions import source_id

ARMS = ("dense_span", "cross_frozen", "cross_adapted", "selection_chosen")


def summary(rows, data):
    ok = [r for r in rows if r["status"] == "succeeded"]
    scores, hits, families = [], [], {}
    for r in rows:
        truth = data.targets[r["question_id"]]
        family = data.families[r["family"]]
        hit = None
        if truth.evidence and not truth.unresolved_evidence and not truth.unanswerable:
            hit = int(r["status"] == "succeeded" and r["source_id"] is not None
                      and source_id(r["source_id"]) in {source_id(i) for i in truth.evidence})
            hits.append(hit)
            families.setdefault(family, []).append(hit)
        if r["status"] == "succeeded":
            score = f1(r["answer"], truth.answer)
            if score is not None:
                scores.append(score)
    return dict(planned=len(rows), succeeded=len(ok), failed=len(rows) - len(ok),
                diagnostic_f1=sum(scores) / len(scores) if scores else None,
                diagnostic_scored_n=len(scores), annotated_source_top1=sum(hits) / len(hits) if hits else None,
                annotated_source_n=len(hits), source_family_means={k: sum(v) / len(v) for k, v in families.items()},
                abstained=sum(r["answer"] == ABSTAIN for r in ok),
                signed_semantic_precision=None, production_accepted=False)


def run(staged, ranker_dir, output):
    source = os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", "")
    if len(source) != 40 or any(c not in "0123456789abcdef" for c in source):
        raise ValueError("exact source required")
    output.mkdir()
    staging = json.loads((staged / "staging.json").read_text())
    data = {kind: load(staged / f"{kind}.json", kind, staging[kind]["sha256"],
            allow_unresolved_evidence=True, session_conflicts="retain-versioned",
            invalid_history="quarantine-question", empty_turns="preserve")
            for kind in ("locomo", "longmemeval")}
    locomo = data["locomo"]
    phases = {q.identity: locomo.partition(q) for q in locomo.questions}
    queries = {phase: sorted([q for q in locomo.questions if phases[q.identity] == phase],
                            key=lambda q: digest(q.identity))[:count]
               for phase, count in (("train", 64), ("select", 16), ("test", 16))}
    queries["transfer"] = sorted(data["longmemeval"].questions, key=lambda q: digest(q.identity))[:16]
    train_families = {locomo.families[q.family] for q in queries["train"]}
    forbidden_roots = {d.root for phase in ("select", "test", "transfer") for q in queries[phase]
                       for d in data["longmemeval" if phase == "transfer" else "locomo"].history(q)}
    plan = dict(schema="hepta.relevance.development.v1", source_commit=source,
                evaluation_use="previously-exposed-public-development-not-qualification",
                question_ids={phase: [q.identity for q in qs] for phase, qs in queries.items()},
                native_source_sha256={k: d.source_sha256 for k, d in data.items()},
                train_families=sorted(train_families), ranker_id=RANKER_ID,
                ranker_revision=RANKER_REVISION, ranker_inventory=file_inventory(ranker_dir),
                encoder_inventory=file_inventory(staged / "encoder"), arms=ARMS,
                maximum_steps=48, training_token_ceiling=24576,
                maximum_pair_tokens=512, maximum_candidates=64, maximum_sources=8,
                ranking_scope="same candidate pool; different scorer compute accounted separately",
                response_mode="structured-extractive-selection-not-autoregressive-generation",
                selection_rule="strict source-family mean gain and no family regression",
                production_accepted=False)
    (output / "preregistered.json").write_text(json.dumps(plan, indent=2) + "\n")
    encoder, ranker = Encoder(staged / "encoder"), RelevanceRanker(ranker_dir)
    ranker.reset("public-selector-development")
    indices, views, retrieval_receipts = {}, {}, {}
    started = time.perf_counter()
    try:
        for phase, qs in queries.items():
            native = data["longmemeval" if phase == "transfer" else "locomo"]
            for q in qs:
                if q.identity in native.ingress_failures:
                    views[q.identity] = ()
                    continue
                if q.scope not in indices:
                    docs = chunks(native.history(q))
                    vectors = encoder.encode([f"{d.observed_at}: {d.content}" for d in docs])
                    path = output / (digest(q.scope) + ".sqlite")
                    hashed = PersistentIndex.build(path, docs, vectors, encoder.identity, native.source_sha256)
                    indices[q.scope] = PersistentIndex(path, native.source_sha256, set(),
                        expected_file_digest=hashed, expected_encoder=encoder.identity)
                view, receipt = indices[q.scope].query(q, encoder.encode([q.content])[0], RetrievalPolicy(),
                                    current_cut=native.source_sha256, revoked=set())
                views[q.identity], retrieval_receipts[q.identity] = tuple(view), receipt
        pairs = training_pairs(queries["train"], views, locomo.targets, phases, locomo.families)
        (output / "training-pairs.json").write_text(json.dumps([p.content() for p in pairs], ensure_ascii=False, indent=2) + "\n")
        training = ranker.fit_pairs(pairs,
            permitted_questions=set(plan["question_ids"]["train"]), permitted_families=train_families,
            forbidden_roots=forbidden_roots, revoked=set())
        artifact = output / "selector-adapter"
        manifest_hash = ranker.save(artifact, training)
        ranker.reset("public-selector-development")
        ranker.load_candidate(artifact, expected_manifest_sha256=manifest_hash,
            scope="public-selector-development", allowed_roots=set(training["roots"]), revoked=set())

        def predict(q, phase, scorer):
            base = dict(question_id=q.identity, family=q.family, phase=phase, arm=scorer)
            try:
                sources, options = candidate_pool(views[q.identity], q, set())
                if not options:
                    return {**base, "status": "succeeded", "answer": ABSTAIN, "source_id": None,
                            "reason": "no bounded source candidates", "semantic_precision": None}
                texts = passages(options, sources)
                if scorer == "dense_span":
                    begun = time.perf_counter()
                    embeddings = encoder.encode([q.content, *texts])
                    logits = (embeddings[1:] @ embeddings[0]).tolist()
                    # Hash exactly the tensorized encoder inputs under its same batch policy.
                    inputs = []
                    for i in range(0, len(texts) + 1, 16):
                        x = encoder.tokenizer([q.content, *texts][i:i + 16], padding=True,
                            truncation=True, max_length=256, return_tensors="pt")
                        inputs.append({k: v.tolist() for k, v in sorted(x.items())})
                    compute = dict(seconds=time.perf_counter() - begun,
                        input_ids_sha256=digest(inputs), input_digest_schema="encoder-batches-v1",
                        pairs=len(texts), truncation_profile="encoder-256-explicit")
                else:
                    logits, compute = ranker.score(q.content, texts, revoked=set(),
                                                   disable_adapter=scorer == "cross_frozen")
                selected = options[choose(logits, options)]
                answer = selected.render()
                receipt = dict(**compute, delivered_evidence=sources,
                    response_mode="extractive-ranked-source-not-posthoc-answer-repair",
                    candidate_pool_sha256=digest([asdict(o) for o in options]),
                    structure=verify_output(answer, options), scores=logits,
                    source_choice_sha256=digest(asdict(selected)), production_accepted=False)
                audit = capture_native(q, answer, receipt, experiment_digest=digest((plan, scorer)),
                                       family_digest=digest(q.family))
                return {**base, "status": "succeeded", "answer": answer,
                        "source_id": selected.source_id, "receipt": receipt,
                        "citation_audit": audit, "retrieval": retrieval_receipts[q.identity]}
            except Exception as e:
                return {**base, "status": "failed", "error_type": type(e).__name__, "error": str(e)[:1024]}

        records = {}
        # Selection labels may choose the frozen comparator, never improve/train tensors.
        for arm in ("cross_frozen", "cross_adapted"):
            records[("select", arm)] = [predict(q, "select", arm) for q in queries["select"]]
        sel = {arm: summary(records[("select", arm)], locomo) for arm in ("cross_frozen", "cross_adapted")}
        f, a = (sel[k]["source_family_means"] for k in ("cross_frozen", "cross_adapted"))
        adopted = "cross_adapted" if len(f) >= 2 and set(f) == set(a) and all(a[k] >= f[k] for k in f) and sum(a.values()) > sum(f.values()) else "cross_frozen"
        (output / "selection.json").write_text(json.dumps(dict(chosen=adopted, metrics=sel,
                    adapter_sha256=manifest_hash, production_accepted=False), indent=2) + "\n")
        for phase in ("test", "transfer"):
            for arm in ARMS:
                records[(phase, arm)] = [predict(q, phase, adopted if arm == "selection_chosen" else arm) for q in queries[phase]]
                for row in records[(phase, arm)]:
                    row["arm"] = arm
        # Record predictions before consulting final answer/support annotations.
        with (output / "attempts.jsonl").open("x") as stream:
            for rows in records.values():
                for row in rows:
                    stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
        metrics = {f"{phase}/{arm}": summary(rows, data["longmemeval" if phase == "transfer" else "locomo"])
                   for (phase, arm), rows in records.items()}
        if frozen_digest(ranker.model) != ranker.base_digest:
            raise ValueError("base drift after complete evaluation")
        result = dict(plan=plan, training=training, chosen=adopted, metrics=metrics,
                      elapsed_seconds=time.perf_counter() - started,
                      retained_bytes=sum(p.stat().st_size for p in output.rglob("*") if p.is_file()),
                      trainable_parameters=ranker.trainable_parameters,
                      independent_semantic_acceptance=None, production_accepted=False,
                      superiority_claim=False, prospective_windows=0)
        (output / "report.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
        print(json.dumps(result, indent=2), flush=True)
        if any(m["failed"] for m in metrics.values()):
            raise RuntimeError("all evaluation failures retained; no qualification")
        return result
    finally:
        for index in indices.values():
            index.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("staged", type=Path)
    p.add_argument("ranker", type=Path)
    p.add_argument("output", type=Path)
    args = p.parse_args()
    torch.set_num_threads(2)
    run(args.staged, args.ranker, args.output)
