"""Eight-arm EXPOSED-native development trial using existing Hepta model ports.

Run only with --development: missing human controls cannot be silently waived
into a primary reasoning experiment. This is NOT untouched held-out qualification.
No new encoder, reader, index owner, signing key, or runtime writer is created.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import time

from bundle_reader import FrozenBundleReader
from evidence_bundle import EvidenceBundle, EvidenceSpan
from index import RetrievalPolicy
from native import digest, load
from pretrained import Encoder, file_inventory
from selector_encoder import FrozenPairEncoder
from selector_evaluation import diagnose, train_rows
from selector_head import TrainingCut
from selector_windows import WindowBudget, candidate_windows
from stem_cell import StemHead, route_text
from stem_cell_cache import SharedFeatureCache
from stem_cell_temporal import build_as_of_index
from stem_cell_trial import READER, RETRIEVER, select_questions
from system2_ablation import (
    ARMS,
    Continuation,
    Limits,
    census,
    execute_matrix,
    model_digest,
    train_continuation,
)
from system2_reader_controls import (
    CONDITIONS,
    diagnostic_census,
    load_pinned_json,
    reviewed_conditions,
)


def write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def append(path, value):
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def run(args):
    if not args.development:
        raise ValueError(
            "unqualified exposed-native run requires explicit --development"
        )
    content_mode = getattr(args, "content_preflight", False)
    if content_mode and args.learning_preflight:
        raise ValueError("content-only and Reader-first preflights are distinct")
    if content_mode and any(
        (args.reviews, args.trust, args.reviews_sha, args.trust_sha)
    ):
        raise ValueError("content-only preflight does not consume human review inputs")
    commit = os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", "")
    if not re.fullmatch("[0-9a-f]{40}", commit):
        raise ValueError("exact generating commit required")
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    staged = json.loads((args.staged / "staging.json").read_text())
    sources = {
        name: load(
            args.staged / f"{name}.json",
            name,
            staged[name]["sha256"],
            allow_unresolved_evidence=True,
            session_conflicts="retain-versioned",
            invalid_history="quarantine-question",
            empty_turns="preserve",
        )
        for name in ("locomo", "longmemeval")
    }
    qs = select_questions(sources)
    query_source = {
        q.identity: sources["longmemeval" if phase == "transfer" else "locomo"]
        for phase, group in qs.items()
        for q in group
    }
    training_queries = (
        [q for q in qs["train"] if route_text(q.content) == "general"]
        if content_mode
        else qs["train"]
    )
    if not training_queries:
        raise ValueError("missing preregistered training Cell")
    evaluations = [q for phase, group in qs.items() if phase != "train" for q in group]
    family = {
        q.identity: query_source[q.identity].families[q.family]
        for group in qs.values()
        for q in group
    }
    train_families = {family[q.identity] for q in qs["train"]}
    if train_families & {family[q.identity] for q in evaluations}:
        raise ValueError("native source-family training/evaluation overlap")
    if (
        not content_mode and digest(file_inventory(args.staged / "reader")) != READER
    ) or digest(file_inventory(args.staged / "encoder")) != RETRIEVER:
        raise ValueError("shared frozen model inventory mismatch")
    plan = dict(
        schema="hepta.system2.development.v1",
        source_commit=commit,
        arms=list(ARMS),
        checkpoints=[16, 32, 48],
        question_ids={p: [q.identity for q in group] for p, group in qs.items()},
        dataset_sha256={k: s.source_sha256 for k, s in sources.items()},
        limits=asdict(Limits()),
        reader_inventory=READER,
        reader_input_token_limit=4096,
        reader_calls_per_successful_policy=1,
        supervision="native-source-support-not-joint-semantic-sufficiency",
        data_status="previously-exposed-public-development-not-untouched-test",
        ordinary_value_vs_ndu_integrator_matched=True,
        primary_forward_backward_coupling=0.0,
        random_profile="declared-binomial-latent-model-not-calibrated-environment",
        production_accepted=False,
        reasoning_superiority=False,
    )
    if args.learning_preflight:
        plan.update(
            schema="hepta.system2.learning-preflight.v1",
            arms=[],
            inherited_primary_arms=list(ARMS),
            planned_policy_attempts=0,
            mode="single-cell-train-opportunity-after-reader-controls",
            cell="general",
            methods=["legacy", "shape_matched_random", "paired"],
            fresh_initialization_each_checkpoint=True,
            optimizer_updates_per_fit=96,
            paired_training_uses_two_forwards_per_update=True,
            matched_training_compute=False,
            full_matrix_completed=False,
        )
    if content_mode:
        plan.update(
            schema="hepta.system2.content-preflight.v1",
            arms=[],
            inherited_primary_arms=list(ARMS),
            planned_policy_attempts=0,
            mode="single-cell-train-content-vs-cardinality",
            cell="general",
            methods=["content", "content_erased"],
            planned_reader_calls=0,
            reader_calls_per_successful_policy=0,
            reader_input_token_limit=None,
            reader_model_loaded=False,
            reader_controls_executed=False,
            encoded_question_ids=[q.identity for q in training_queries],
            fresh_initialization_each_checkpoint=True,
            optimizer_updates_per_fit=96,
            equal_nonzero_cardinality_per_pair=True,
            pair_difference="one_candidate_replacement",
            frozen_train_comparator="max_frozen_score_over_each_set",
            confirmation_and_reader_adequacy_are_still_required=True,
            matched_training_compute=False,
            full_matrix_completed=False,
        )
    write(args.output / "plan.json", plan)
    encoder, ranker = Encoder(args.staged / "encoder"), FrozenPairEncoder(args.ranker)
    cache = SharedFeatureCache(ranker)
    features, pools, failures, indices, index_receipts = {}, {}, {}, {}, {}
    for group in [training_queries] if content_mode else qs.values():
        for q in group:
            source = query_source[q.identity]
            try:
                if q.identity in source.ingress_failures:
                    raise ValueError("native history ingress unavailable")
                key = (source.source_sha256, q.scope, q.observed_at)
                if key not in indices:
                    idx, admission = build_as_of_index(
                        source, q, encoder, args.output, revoked=set()
                    )
                    indices[key] = (idx, admission["as_of_cut"])
                    index_receipts[digest(key)] = admission
                idx, cut = indices[key]
                docs, retrieval = idx.query(
                    q,
                    encoder.encode([q.content])[0],
                    RetrievalPolicy(),
                    current_cut=cut,
                    revoked=set(),
                )
                pool = candidate_windows(
                    tuple(docs),
                    q,
                    revoked=set(),
                    budget=WindowBudget(),
                    profile="query_windows",
                )
                f, cost = cache.encode(q, family[q.identity], pool, revoked=set())
                features[q.identity], pools[q.identity] = f, pool
                append(
                    args.output / "shared-encoding.jsonl",
                    dict(question_id=q.identity, cost=cost, retrieval=retrieval),
                )
            except Exception as exc:
                failures[q.identity] = dict(
                    error_type=type(exc).__name__, error=str(exc)[:512]
                )
    write(args.output / "feature-failures.json", failures)
    write(args.output / "indices.json", index_receipts)
    if any(q.identity not in features for q in training_queries):
        raise ValueError("incomplete train features; no silent train replacement")
    train_roots = frozenset(
        root for q in training_queries for root in features[q.identity].roots
    )
    forbidden = frozenset(
        d.root for q in evaluations for d in query_source[q.identity].history(q)
    )
    cut = TrainingCut(
        frozenset(q.identity for q in training_queries),
        frozenset(family[q.identity] for q in training_queries),
        train_roots,
        forbidden,
        digest((plan, "train-only")),
    )
    rows, disposition = train_rows(
        training_queries, sources["locomo"].targets, pools, features, cut
    )
    write(args.output / "training-dispositions.json", disposition)
    if content_mode:
        from system2_content_probe import run_content_probe

        probes = []
        for checkpoint in (16, 32, 48):
            admitted = {q.identity for q in qs["train"][:checkpoint]}
            selected = tuple(r for r in rows if r.features.question_id in admitted)
            try:
                probe = run_content_probe(
                    selected,
                    cut,
                    ranker.dimension,
                    steps=96,
                    output=args.output / f"content-probe-{checkpoint}",
                )
                statuses = [m["status"] for m in probe["methods"].values()]
                status = (
                    "failed"
                    if "failed" in statuses
                    else "unavailable"
                    if "unavailable" in statuses
                    else "succeeded"
                )
                record = dict(
                    checkpoint=checkpoint, cell="general", status=status, probe=probe
                )
            except Exception as exc:
                record = dict(
                    checkpoint=checkpoint,
                    cell="general",
                    status="failed",
                    error_type=type(exc).__name__,
                    error=str(exc)[:512],
                )
            probes.append(record)
            append(args.output / "content-preflight.jsonl", record)
        result = dict(
            schema="hepta.system2.content-preflight-summary.v1",
            source_commit=commit,
            mode="single-cell-train-content-vs-cardinality",
            planned_policy_attempts=0,
            actual_policy_attempts=0,
            planned_reader_calls=0,
            actual_reader_calls=0,
            reader_model_loaded=False,
            reader_controls_executed=False,
            planned_probe_checkpoints=3,
            recorded_probe_checkpoints=len(probes),
            failed_probe_checkpoints=sum(r["status"] == "failed" for r in probes),
            unavailable_probe_checkpoints=sum(
                r["status"] == "unavailable" for r in probes
            ),
            encoded_training_questions=len(features),
            evaluation_target_annotations_used=False,
            elapsed_seconds=time.perf_counter() - started,
            full_matrix_completed=False,
            reader_adequacy_established=False,
            native_reasoning_superiority=False,
            production_accepted=False,
        )
        write(args.output / "run-summary.json", result)
        if result["failed_probe_checkpoints"]:
            raise RuntimeError("content preflight failed; partial artifacts retained")
        return
    reader = FrozenBundleReader(args.staged / "reader", expected_inventory=READER)
    reviews, registry = {}, None
    if any((args.reviews, args.trust, args.reviews_sha, args.trust_sha)):
        if not all((args.reviews, args.trust, args.reviews_sha, args.trust_sha)):
            raise ValueError(
                "review and separately pinned trust inputs required together"
            )
        reviews = load_pinned_json(args.reviews, args.reviews_sha)
        registry = load_pinned_json(args.trust, args.trust_sha)

    def context(q):
        originals = {d.identity: d for d in query_source[q.identity].history(q)}
        frontier = digest(
            [(k, digest(d.content)) for k, d in sorted(originals.items())]
        )

        def make(selected):
            pool = pools[q.identity]
            pool.revalidate(q, set())
            spans = []
            for i in selected:
                w = pool.windows[i]
                doc = originals[w.source_id]
                spans.append(
                    EvidenceSpan(
                        doc.identity,
                        doc.root,
                        doc.scope,
                        doc.session,
                        doc.observed_at,
                        w.start,
                        w.end,
                        w.text,
                        digest(doc.content),
                    )
                )
            return EvidenceBundle(
                digest(asdict(q)),
                frontier,
                tuple(spans),
                "system2-development",
                rounds=1,
            )

        def answer(selected):
            return reader.answer(
                q,
                make(selected),
                originals,
                frontier=frontier,
                revoked=set(),
                token_limit=4096,
            )

        return originals, frontier, make, answer

    # Reader controls happen before policy training; targets are not consulted here.
    controls = []
    for q in evaluations:
        for condition in CONDITIONS:
            record = dict(question_id=q.identity, condition=condition)
            call_started = time.perf_counter()
            try:
                if q.identity not in features:
                    raise ValueError("shared features unavailable")
                originals, frontier, make, answer = context(q)
                if condition == "no_evidence":
                    text, receipt = answer(())
                elif condition == "ordinary_retrieval":
                    f = features[q.identity]
                    selected = sorted(
                        range(len(f.candidate_ids)),
                        key=lambda i: (-float(f.frozen_scores[i]), f.candidate_ids[i]),
                    )[:3]
                    text, receipt = answer(selected)
                elif registry is None or q.identity not in reviews:
                    record.update(
                        status="unavailable",
                        reason="missing external authenticated sufficient-evidence review",
                    )
                    controls.append(record)
                    append(args.output / "reader-controls.jsonl", record)
                    continue
                else:
                    case = dict(
                        question=asdict(q),
                        originals=[asdict(d) for d in originals.values()],
                        frontier=frontier,
                    )
                    variants, authentication = reviewed_conditions(
                        case,
                        reviews[q.identity],
                        registry,
                        experiment_authors={"ProfHepta"},
                        revoked=set(),
                    )
                    data = variants[condition]["bundle"]
                    bundle = EvidenceBundle(
                        **(
                            data
                            | {
                                "selected": tuple(
                                    EvidenceSpan(**s) for s in data["selected"]
                                )
                            }
                        )
                    )
                    text, receipt = reader.answer(
                        q,
                        bundle,
                        originals,
                        frontier=frontier,
                        revoked=set(),
                        token_limit=4096,
                    )
                    receipt["authentication"] = authentication
                record.update(status="succeeded", answer=text, receipt=receipt)
            except Exception as exc:
                record.update(
                    status="failed", error_type=type(exc).__name__, error=str(exc)[:512]
                )
            record["elapsed_seconds"] = time.perf_counter() - call_started
            controls.append(record)
            append(args.output / "reader-controls.jsonl", record)
    write(
        args.output / "reader-control-census.json",
        diagnostic_census(controls, [q.identity for q in evaluations]),
    )
    if args.learning_preflight:
        from system2_learning_probe import run_probe

        qmap = {q.identity: q for q in qs["train"]}
        probes = []
        for checkpoint in (16, 32, 48):
            admitted = {q.identity for q in qs["train"][:checkpoint]}
            selected = tuple(
                r
                for r in rows
                if r.features.question_id in admitted
                and route_text(qmap[r.features.question_id].content) == "general"
            )
            try:
                probe = run_probe(selected, cut, ranker.dimension, steps=96)
                failed = any(m["status"] == "failed" for m in probe["methods"].values())
                record = dict(
                    checkpoint=checkpoint,
                    cell="general",
                    status="failed" if failed else "succeeded",
                    probe=probe,
                )
            except Exception as exc:
                record = dict(
                    checkpoint=checkpoint,
                    cell="general",
                    status="failed",
                    error_type=type(exc).__name__,
                    error=str(exc)[:512],
                )
            probes.append(record)
            append(args.output / "learning-preflight.jsonl", record)
        reader.verify_frozen()
        control_failures = sum(r["status"] == "failed" for r in controls)
        result = dict(
            source_commit=commit,
            schema="hepta.system2.learning-preflight-summary.v1",
            mode="single-cell-train-opportunity",
            planned_policy_attempts=0,
            actual_policy_attempts=0,
            planned_probe_checkpoints=3,
            recorded_probe_checkpoints=len(probes),
            failed_probe_checkpoints=sum(r["status"] == "failed" for r in probes),
            reader_control_census=diagnostic_census(
                controls, [q.identity for q in evaluations]
            ),
            successful_reader_controls=sum(
                r["status"] == "succeeded" for r in controls
            ),
            failed_reader_controls=control_failures,
            unavailable_reader_controls=sum(
                r["status"] == "unavailable" for r in controls
            ),
            elapsed_seconds=time.perf_counter() - started,
            evaluation_target_annotations_used=False,
            full_matrix_completed=False,
            reader_adequacy_established=False,
            native_reasoning_superiority=False,
            production_accepted=False,
        )
        write(args.output / "run-summary.json", result)
        if control_failures or result["failed_probe_checkpoints"]:
            raise RuntimeError(
                "preflight contains failures; all checkpoints/controls retained"
            )
        # No policy answers, test-label scoring, or production admission below.
        return
    # Explicit development continuation: these policy runs cannot bypass adequacy acceptance.
    heads = {
        route: {
            kind: StemHead(ranker.dimension, ranker.identity, kind=kind)
            for kind in ("linear", "gated")
        }
        for route in ("general", "temporal")
    }
    continuation = Continuation(ranker.dimension)
    attempts, training = [], []
    qmap = {q.identity: q for group in qs.values() for q in group}
    for checkpoint in (16, 32, 48):
        admitted = {q.identity for q in qs["train"][:checkpoint]}
        stage_rows = tuple(r for r in rows if r.features.question_id in admitted)
        stamp = time.perf_counter()
        for route, by_kind in heads.items():
            selected = tuple(
                r
                for r in stage_rows
                if route_text(qmap[r.features.question_id].content) == route
            )
            for kind, head in by_kind.items():
                try:
                    receipt = head.fit(
                        selected, cut, revoked=set(), steps=96, pair_ceiling=100000
                    )
                    training.append(
                        dict(
                            checkpoint=checkpoint,
                            route=route,
                            kind=kind,
                            receipt=receipt,
                        )
                    )
                except Exception as exc:
                    head.quarantined = True
                    training.append(
                        dict(
                            checkpoint=checkpoint,
                            route=route,
                            kind=kind,
                            status="failed",
                            error_type=type(exc).__name__,
                            error=str(exc)[:512],
                        )
                    )
        try:
            training.append(
                dict(
                    checkpoint=checkpoint,
                    kind="continuation",
                    receipt=train_continuation(continuation, stage_rows, cut, steps=96),
                )
            )
        except Exception as exc:
            continuation.quarantined = True
            training.append(
                dict(
                    checkpoint=checkpoint,
                    kind="continuation",
                    status="failed",
                    error_type=type(exc).__name__,
                    error=str(exc)[:512],
                )
            )
        append(
            args.output / "training-cost.jsonl",
            dict(checkpoint=checkpoint, seconds=time.perf_counter() - stamp),
        )
        append(
            args.output / "training-events.jsonl",
            dict(checkpoint=checkpoint, records=training),
        )
        # Save only data tensors with safetensors, not unsafe pickle checkpoints.
        from safetensors.torch import save_file

        tensors = {
            "continuation." + k: v.detach().contiguous()
            for k, v in continuation.state_dict().items()
        }
        for route, by_kind in heads.items():
            for kind, head in by_kind.items():
                tensors.update(
                    {
                        f"{route}.{kind}." + k: v.detach().contiguous()
                        for k, v in head.state_dict().items()
                    }
                )
        save_file(tensors, str(args.output / f"weights-{checkpoint}.safetensors"))
        for q in evaluations:
            if q.identity not in features:
                records = [
                    dict(
                        question_id=q.identity,
                        family=family[q.identity],
                        arm=a,
                        status="failed",
                        error_type="SharedFeatureUnavailable",
                        error=failures[q.identity],
                    )
                    for a in ARMS
                ]
            else:
                _, _, _, answer = context(q)
                records = execute_matrix(
                    features[q.identity],
                    heads[route_text(q.content)],
                    continuation,
                    answer,
                )
            for r in records:
                r.update(checkpoint=checkpoint, cell=route_text(q.content))
                attempts.append(r)
                append(args.output / "attempts.jsonl", r)
        stage_records = [r for r in attempts if r["checkpoint"] == checkpoint]
        write(
            args.output / f"census-{checkpoint}.json",
            census(stage_records, [q.identity for q in evaluations]),
        )
    reader.verify_frozen()
    # Evaluation labels are read only AFTER every policy answer is sealed.
    metrics = []
    for record in attempts:
        q = qmap[record["question_id"]]
        target = query_source[q.identity].targets[q.identity]
        score = (
            diagnose(record["answer"], target)
            if record["status"] == "succeeded"
            else 0.0
        )
        metrics.append(
            dict(
                question_id=q.identity,
                arm=record["arm"],
                checkpoint=record["checkpoint"],
                family=family[q.identity],
                diagnostic_f1=score,
                failure=record["status"] != "succeeded",
            )
        )
    write(args.output / "training.json", training)
    write(args.output / "diagnostic-scores.json", metrics)
    write(
        args.output / "run-summary.json",
        dict(
            source_commit=commit,
            attempted=len(attempts),
            failed=sum(r["status"] != "succeeded" for r in attempts),
            elapsed_seconds=time.perf_counter() - started,
            encoder_physical_work="shared-encoding.jsonl and indices.json; charged once",
            reader_control_census=diagnostic_census(
                controls, [q.identity for q in evaluations]
            ),
            continuation=model_digest(continuation),
            equal_observed_resource_use=False,
            native_reasoning_superiority=False,
            production_accepted=False,
        ),
    )
    if any(r["status"] != "succeeded" for r in attempts):
        raise RuntimeError(
            "native matrix contains failed attempts; all rows and summary retained"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("staged", type=Path)
    parser.add_argument("ranker", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--development", action="store_true")
    parser.add_argument(
        "--learning-preflight",
        action="store_true",
        help="single general Cell train-only legacy/random/paired diagnostic; no new full policy matrix",
    )
    parser.add_argument(
        "--content-preflight",
        action="store_true",
        help="train-only equal-size content/erased study; no Reader load, calls or new task answers",
    )
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--reviews-sha")
    parser.add_argument("--trust", type=Path)
    parser.add_argument("--trust-sha")
    args = parser.parse_args()
    try:
        run(args)
    except Exception as exc:
        if args.output.is_dir():
            append(
                args.output / "run-failures.jsonl",
                dict(
                    error_type=type(exc).__name__, error=str(exc)[:1024], complete=False
                ),
            )
        raise


if __name__ == "__main__":
    main()
