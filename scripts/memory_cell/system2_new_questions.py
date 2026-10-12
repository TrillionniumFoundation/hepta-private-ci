"""Native new-question trial on original train families, with a real fixed Reader.

This is a phase-separated DEVELOPMENT cohort, not new independent sources or
historical online learning. Benchmark targets are parsed by existing ingress;
the model-facing Benchmark has no target mapping. Only fixed support targets
are provided for fitting; evaluation scoring starts after the raw-answer seal.
"""
import argparse
from dataclasses import asdict, replace
import hashlib
import os
from pathlib import Path
import re
import time

from system2_content_replay import ARCHIVE, audit_content
from system2_frozen_cohort import Ports, execute, plan_cohort
from system2_fewshot_cells import journal
from system2_linear_solver import write
from system2_native_receipt import strict_json, verified_archive

LOCOMO_SHA = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"


def run(staged, ranker_dir, archive, output, *, source_commit):
    if not re.fullmatch("[0-9a-f]{40}", source_commit or ""):
        raise ValueError("exact generating source required")
    output.mkdir(exist_ok=False)
    started = time.perf_counter()
    from bundle_reader import FrozenBundleReader
    from evidence_bundle import EvidenceBundle, EvidenceSpan
    from index import RetrievalPolicy
    from native import digest, load
    from pretrained import Encoder, file_inventory
    from selector_encoder import FrozenPairEncoder
    from selector_evaluation import diagnose, support_indices, train_rows
    from selector_head import TrainingCut
    from selector_windows import WindowBudget, candidate_windows
    from stem_cell_cache import SharedFeatureCache
    from stem_cell_temporal import build_as_of_index
    from stem_cell_trial import READER, RETRIEVER

    datasets, audit = audit_content(archive)
    files = verified_archive(archive, ARCHIVE)
    old_plan = strict_json(files["native/plan.json"])
    rows, original = datasets[48]
    raw = load(staged/"locomo.json", "locomo", LOCOMO_SHA, allow_unresolved_evidence=True,
        session_conflicts="retain-versioned", invalid_history="quarantine-question", empty_turns="preserve")
    labels, source = raw.targets, replace(raw, targets={})
    plan = plan_cohort(source.questions, old_plan) | dict(source_commit=source_commit,
        locomo_sha256=LOCOMO_SHA, cached_prior_archive=ARCHIVE, reader_inventory=READER,
        encoded_representation=rows[0].features.encoder_identity,
        target_mapping_removed_from_model_facing_benchmark=True,
        executing_file_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    if any(r.features.question_id in {q for g in plan["groups"] for q in g["query_ids"]+g["support_ids"]} for r in rows):
        raise ValueError("old fitting queries overlap new cohort")
    write(output/"registered-plan.json", plan)
    write(output/"prior-content-audit.json", audit)
    if digest(file_inventory(staged/"encoder")) != RETRIEVER or digest(file_inventory(staged/"reader")) != READER:
        raise ValueError("frozen model inventories changed")
    encoder, ranker = Encoder(staged/"encoder"), FrozenPairEncoder(ranker_dir)
    if ranker.identity != rows[0].features.encoder_identity:
        raise ValueError("new encodings incompatible with saved shared priors")
    cache, features, pools, indices, reader = SharedFeatureCache(ranker), {}, {}, {}, None
    query_map = {q.identity:q for q in source.questions}
    bindings = {k:v for g in plan["groups"] for k,v in g["question_bindings"].items()}
    index_dir = output/"indices"
    index_dir.mkdir()
    trial_dir = output/"trial"

    def encode(qid):
        if qid not in bindings:
            raise ValueError("query not in fixed cohort")
        q = query_map[qid]
        if digest((q.content, q.observed_at, q.scope)) != bindings[qid]:
            raise ValueError("registered question changed")
        history = source.history(q)
        if any(d.root in original.forbidden_roots for d in history):
            raise ValueError("old forbidden root cannot become local support")
        if qid in features:
            pools[qid].revalidate(q, set())
            return features[qid]
        key = (q.scope, q.observed_at)
        if key not in indices:
            idx, admission = build_as_of_index(source, q, encoder, index_dir, revoked=set())
            indices[key] = idx, admission["as_of_cut"]
            journal(output/"index-receipts.jsonl", admission)
        idx, cut = indices[key]
        docs, receipt = idx.query(q, encoder.encode([q.content])[0], RetrievalPolicy(), current_cut=cut, revoked=set())
        pool = candidate_windows(tuple(docs), q, revoked=set(), budget=WindowBudget(), profile="query_windows")
        feature, cost = cache.encode(q, source.families[q.family], pool, revoked=set())
        pools[qid], features[qid] = pool, feature
        journal(output/"encoding.jsonl", dict(query_id=qid, cost=cost, retrieval=receipt,
            feature_digest=feature.seal(), after_snapshot_freeze=(trial_dir/"snapshot-freeze.json").exists()))
        return feature

    def support(group):
        qs = [query_map[q] for q in group["support_ids"]]
        fs = [encode(q.identity) for q in qs]
        roots = frozenset(root for f in fs for root in f.roots)
        cut = TrainingCut(frozenset(group["support_ids"]), frozenset({group["family"]}), roots,
            original.forbidden_roots, digest((plan, "fixed-local-support", group["support_ids"])))
        # Evaluation labels are not provided to the fitting-side adapter.
        support_labels = {q.identity: labels[q.identity] for q in qs}
        trained, disposition = train_rows(qs, support_labels, pools, features, cut)
        return trained, cut, disposition

    def answer(qid, selected):
        nonlocal reader
        if not (trial_dir/"snapshot-freeze.json").is_file():
            raise ValueError("Reader invoked before all Cell snapshots frozen")
        if reader is None:
            reader = FrozenBundleReader(staged/"reader", expected_inventory=READER)
        q = query_map[qid]
        originals = {d.identity:d for d in source.history(q)}
        frontier = digest([(k, digest(d.content)) for k,d in sorted(originals.items())])
        spans = []
        if selected:
            pool = pools[qid]
            pool.revalidate(q, set())
            for i in selected:
                w = pool.windows[i]
                d = originals[w.source_id]
                spans.append(EvidenceSpan(d.identity, d.root, d.scope, d.session, d.observed_at,
                    w.start, w.end, w.text, digest(d.content)))
        bundle = EvidenceBundle(digest(asdict(q)), frontier, tuple(spans), "system2-new-question-development", rounds=1)
        journal(output/"reader-inputs.jsonl", dict(query=asdict(q), bundle=asdict(bundle),
            selected_originals=[asdict(originals[s.source_id]) for s in spans]))
        return reader.answer(q, bundle, originals, frontier=frontier, revoked=set(), token_limit=4096)

    def score(record):
        if not (trial_dir/"answer-seal.json").is_file():
            raise ValueError("evaluation target access before all answers durable")
        target = labels[record["query_id"]]
        hit = None
        if not target.unanswerable and not target.unresolved_evidence and target.evidence and record["query_id"] in pools:
            hit = bool(set(record["selected"]) & set(support_indices(pools[record["query_id"]], target)))
        return dict(diagnostic_f1=diagnose(record["answer"], target), weak_source_hit=hit,
            native_unanswerable=target.unanswerable, source_labels_unresolved=bool(target.unresolved_evidence),
            semantic_correctness_independently_verified=False)

    try:
        report = execute(plan, rows, original, Ports(support, encode, answer, score), trial_dir)
        if reader is not None:
            reader.verify_frozen()
        ranker.verify_frozen()
        write(output/"run-summary.json", report | dict(encoded_questions=len(features),
            elapsed_seconds=time.perf_counter()-started, reader_model_loaded=reader is not None,
            old_question_ids_reused=0, new_independent_source_families=0,
            natural_chronology_verified=False, real_reader_trial=True))
    except Exception as exc:
        journal(output/"failures.jsonl", dict(error_type=type(exc).__name__, error=str(exc)[:1024],
            elapsed_seconds=time.perf_counter()-started, production_accepted=False))
        raise
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("staged", "ranker", "archive", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    run(args.staged, args.ranker, args.archive, args.output,
        source_commit=os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", ""))
