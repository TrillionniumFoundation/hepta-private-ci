"""Registered DEVELOPMENT comparison, not a new untouched final benchmark.

The earlier public benchmark outcomes are already visible. No score from this
run can qualify production or tune an untouched holdout. Compare the same base,
same evidence, token ceilings and both decoding modes; retain every failure.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import resource
import time

import torch

from citation_audit import MARKER
from grounded_protocol import ABSTAIN, MAX_NEW_TOKENS
from index import PersistentIndex, RetrievalPolicy
from native import digest, load
from native_citation import capture_native
from pretrained import Encoder, file_inventory, frozen_digest
from grounded_reader import GroundedReader
from run_native import chunks, f1

ARMS = ("base_free", "base_span", "history_lm_span", "source_sft_free", "source_sft_span")
MAX_STEPS = 32
TOKEN_CEILING = MAX_STEPS * 192


def run(staged: Path, output: Path, kind: str, *, count: int) -> dict:
    if kind not in ("longmemeval", "locomo") or not 1 <= count <= 16:
        raise ValueError("registered development bounds")
    source = os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", "")
    if len(source) != 40 or any(c not in "0123456789abcdef" for c in source):
        raise ValueError("exact generator commit required")
    output.mkdir(parents=True, exist_ok=False)
    staging = json.loads((staged / "staging.json").read_text())
    data = load(staged / f"{kind}.json", kind, staging[kind]["sha256"],
                allow_unresolved_evidence=True, session_conflicts="retain-versioned",
                invalid_history="quarantine-question", empty_turns="preserve")
    queries = sorted(data.questions, key=lambda q: digest(q.identity))[:count]
    plan = {
        "schema": "hepta.grounded-memory.development.v1", "source_commit": source,
        "dataset_sha256": data.source_sha256, "question_ids": [q.identity for q in queries],
        "evaluation_use": "exposed-public-data-development-not-final-holdout",
        "arms": list(ARMS), "reader_identity": digest(file_inventory(staged / "reader")),
        "encoder_identity": digest(file_inventory(staged / "encoder")),
        "rank": 4, "maximum_steps": MAX_STEPS, "training_token_ceiling": TOKEN_CEILING,
        "input_token_ceiling": 1024, "generated_token_ceiling": MAX_NEW_TOKENS,
        "training_view": "retrieved-sources-only; no benchmark target or test question in supervision",
        "decoder_comparison": "free and finite exact-source quotations, same output ceiling",
        "no_posthoc_citation_repair": True, "production_accepted": False,
        "code_digest": digest({name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                               for name in ("grounded_protocol.py", "grounded_reader.py",
                                            "grounded_development.py", "pretrained.py", "index.py",
                                            "native.py", "sessions.py", "run_native.py")}),
    }
    # Freeze all IDs, arms and budgets before loading/learning/evaluating models.
    (output / "preregistered.json").write_text(json.dumps(plan, indent=2)+"\n")
    reader, encoder = GroundedReader(staged / "reader"), Encoder(staged / "encoder")
    records = {a: [] for a in ARMS}
    indexes = {}
    started = time.perf_counter()

    def emit(arm, query, candidates, decoder, training=None):
        try:
            answer, receipt = reader.answer_grounded(query, candidates, revoked=set(), decoder=decoder)
            queue = capture_native(query, answer, receipt,
                                   experiment_digest=digest((plan, arm)),
                                   family_digest=digest(data.families[query.family]))
            row = {"question_id": query.identity, "family": data.families[query.family],
                   "status": "succeeded", "answer": answer, "receipt": receipt,
                   "citation_audit": queue, "training": training}
        except Exception as error:
            row = {"question_id": query.identity, "status": "failed",
                   "error_type": type(error).__name__, "error": str(error)[:1024]}
        records[arm].append(row)
        with (output / "attempts.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"arm": arm, **row}, ensure_ascii=False, allow_nan=False)+"\n")

    def failure(arms, query, error):
        for arm in arms:
            row = {"question_id": query.identity, "status": "failed",
                   "error_type": type(error).__name__, "error": str(error)[:1024]}
            records[arm].append(row)
            with (output / "attempts.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"arm": arm, **row})+"\n")

    try:
        for query in queries:
            if query.identity in data.ingress_failures:
                failure(ARMS, query, ValueError(data.ingress_failures[query.identity]))
                continue
            try:
                if query.scope not in indexes:
                    documents = chunks(data.history(query))
                    vectors = encoder.encode([f"{d.observed_at}: {d.content}" for d in documents])
                    path = output / (digest(query.scope)+".sqlite")
                    index_hash = PersistentIndex.build(path, documents, vectors,
                                                       encoder.identity, data.source_sha256)
                    indexes[query.scope] = PersistentIndex(
                        path, data.source_sha256, set(), expected_file_digest=index_hash,
                        expected_encoder=encoder.identity,
                    )
                candidates, retrieval = indexes[query.scope].query(
                    query, encoder.encode([query.content])[0], RetrievalPolicy(),
                    current_cut=data.source_sha256, revoked=set(),
                )
                reader.reset(query.scope)
                _, delivered, _, _ = reader._prepare(query, candidates, set())
                # All methods get exactly the same bounded source content. Do not
                # train on hidden suffixes unavailable to the frozen comparator.
                by_id = {d.identity: d for d in candidates}
                from native import Document
                view = tuple(Document(**{**asdict(by_id[s["id"]]), "content": s["excerpt"]})
                             for s in delivered)
                (output / (digest(query.identity)+"-source-view.json")).write_text(
                    json.dumps({"sources": [asdict(d) for d in view], "retrieval": retrieval},
                               ensure_ascii=False, indent=2)+"\n")
            except Exception as error:
                failure(ARMS, query, error)
                continue
            emit("base_free", query, candidates, "free")
            emit("base_span", query, candidates, "span")
            for objective, target_arms in (("history", ("history_lm_span",)),
                                          ("sft", ("source_sft_free", "source_sft_span"))):
                try:
                    reader.reset(query.scope)
                    if objective == "history":
                        training = reader.adapt(view, steps=MAX_STEPS, revoked=set())
                    else:
                        training = reader.adapt_grounded(view, steps=MAX_STEPS,
                                                         revoked=set(), token_ceiling=TOKEN_CEILING)
                    if training["tokens"] > TOKEN_CEILING:
                        raise ValueError("training token ceiling exceeded")
                    artifact = output / (objective+"-"+digest(query.identity))
                    sealed = reader.save(artifact, training)
                    reader.reset(query.scope)
                    reader.load_candidate(artifact, expected_manifest_sha256=sealed,
                                          scope=query.scope, allowed_roots={d.root for d in view},
                                          revoked=set())
                    # Reused base + exact immutable adapter reload, no trainer buffers.
                except Exception as error:
                    failure(target_arms, query, error)
                    continue
                for arm in target_arms:
                    emit(arm, query, candidates, "free" if arm.endswith("free") else "span", training)
        if frozen_digest(reader.model) != reader.base_digest:
            raise ValueError("frozen base changed after comparison")
    finally:
        for index in indexes.values():
            index.close()
    # Gold is consulted only after every model arm and immutable artifact exists.
    metrics = {}
    for arm, rows in records.items():
        if {r["question_id"] for r in rows} != set(plan["question_ids"]) or len(rows) != count:
            raise ValueError("missing/duplicate comparison attempts")
        succeeded = [r for r in rows if r["status"] == "succeeded"]
        scored, unanswered, copies, markers, unknown = [], 0, 0, 0, 0
        for row in succeeded:
            truth = data.targets[row["question_id"]]
            row["diagnostic_token_f1"] = f1(row["answer"], truth.answer)
            if row["diagnostic_token_f1"] is not None:
                scored.append(row["diagnostic_token_f1"])
            unanswered += row["answer"] == ABSTAIN
            copies += row["receipt"]["structure"]["copy_verified"]
            present = list(MARKER.finditer(row["answer"].encode()))
            labels = {s["label"] for s in row["receipt"]["delivered_evidence"]}
            markers += len(present)
            unknown += sum(m.group()[1:-1].decode() not in labels for m in present)
        metrics[arm] = {"planned": count, "succeeded": len(succeeded),
                        "failed": count-len(succeeded), "abstentions": unanswered,
                        "exact_source_copies": copies, "emitted_markers": markers,
                        "undelivered_markers": unknown,
                        "diagnostic_f1": sum(scored)/len(scored) if scored else None,
                        "diagnostic_scored_n": len(scored),
                        "citation_semantic_precision": None, "relevance_verified": False}
    result = {"plan": plan, "metrics": metrics, "records": records,
              "elapsed_seconds": time.perf_counter()-started,
              "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              "source_family_groups": len({data.families[q.family] for q in queries}),
              "superiority_claim": False, "production_accepted": False,
              "independent_acceptance": None, "prospective_windows": 0,
              "notes": ["Constrained copies can be irrelevant or stale; not semantic entailment.",
                        "Equal ceilings are not equal actual FLOPs. Report token/time costs.",
                        "Previously exposed public cases are development, not new holdout evidence."]}
    (output / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+"\n")
    print(json.dumps(metrics, indent=2), flush=True)
    if any(m["failed"] for m in metrics.values()):
        raise RuntimeError("comparison failures retained in report and original attempts")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("staged", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("benchmark", choices=("longmemeval", "locomo"))
    parser.add_argument("--count", type=int, default=4)
    args = parser.parse_args()
    torch.set_num_threads(2)
    run(args.staged, args.output, args.benchmark, count=args.count)
