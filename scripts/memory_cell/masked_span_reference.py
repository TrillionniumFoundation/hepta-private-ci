"""Replay published annotations after generation, not a semantic judge.

The existing execution auditor checks raw answers and receipts. This layer also
rebuilds windows from pinned ORIGINAL datasets and recomputes every diagnostic
score/label. Re-signing a report with changed scores cannot satisfy this check.
It never trains, generates, repairs outputs or issues production authority.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
import os
import re

from masked_span_audit import audit, load
from native import digest, load as load_native
from selector_answer_metrics import answer_scores
from selector_windows import WindowBudget, candidate_windows
from span_supervision import SQUAD_REVISION, load_corpus, partitions


def planned_questions(plan, train, dev, native):
    if plan["external_annotation_revision"] != SQUAD_REVISION:
        raise ValueError("publisher revision changed")
    cuts = partitions(train, dev)
    for name, data in native.items():
        cuts[name] = tuple(sorted(data.questions, key=lambda q: digest(q.identity))[:8])
    if plan["questions"] != {p: [q.identity for q in qs] for p, qs in cuts.items()}:
        raise ValueError("planned census differs from fixed dataset sampling")
    identities = [q.identity for qs in cuts.values() for q in qs]
    if len(identities) != len(set(identities)):
        raise ValueError("question repeats across phases")
    return cuts


def original_pool(query, documents, serialized_pool, serialized_view, budget):
    """The retained view must be a byte-identical subset of eligible sources."""
    eligible = {d.identity: d for d in documents}
    if len(eligible) != len(documents):
        raise ValueError("ambiguous original document identity")
    chosen = []
    for record in serialized_view:
        source = eligible.get(record["identity"])
        if source is None or digest(asdict(source)) != digest(record):
            raise ValueError("retained evidence differs from eligible original source")
        chosen.append(source)
    pool = candidate_windows(tuple(chosen), query, revoked=set(), budget=budget)
    if digest(asdict(pool)) != digest(serialized_pool):
        raise ValueError("saved candidate pool cannot be reconstructed")
    return pool


def score_fields(row, target, query, pool, *, external):
    if row["status"] != "succeeded":
        raise ValueError("failed attempt cannot be reference-verified as success")
    if external:
        answers = tuple(span[2] for span in target.spans)
        null = target.unanswerable
        positives = target.indices(query, pool)
        contains = row["selected"] in positives
        visible = bool(positives) if not null else None
    else:
        answers = (target.answer,) if target.answer is not None else None
        null = target.unanswerable if answers is not None else None
        contains, visible = None, None
    expected = dict(
        target_unanswerable=null,
        selected_window_contains_annotated_answer=contains,
        annotated_answer_visible_in_pool=visible,
        **answer_scores(row["answer"], answers, null),
    )
    # Canonical comparison also rejects bool masquerading as a numeric score.
    if any(k not in row or digest(row[k]) != digest(v) for k, v in expected.items()):
        raise ValueError(
            "diagnostic score or support label differs from original annotation"
        )
    return expected


def training_fields(note, query, target, pool):
    ids = [w.identity() for w in pool.windows]
    positive = target.indices(query, pool)
    negative = tuple(range(len(ids))) if target.unanswerable else ()
    unknown = tuple(i for i in range(len(ids)) if i not in positive + negative)
    expected = dict(
        question_id=query.identity,
        annotation_digest=target.annotation_digest,
        pool_digest=pool.seal(),
        positive_ids=[ids[i] for i in positive],
        negative_ids=[ids[i] for i in negative],
        unknown_ids=[ids[i] for i in unknown],
        unanswerable=target.unanswerable,
        negative_scope="only the externally annotated unanswerable paragraph",
        status=(
            "external_tri_state_window_supervision"
            if positive or negative
            else "no_candidate_no_gradient"
            if target.unanswerable
            else "annotated_span_not_visible_not_a_null_target"
        ),
    )
    if digest(note) != digest(expected):
        raise ValueError(
            "training window supervision differs from original human spans"
        )


def verify(experiment, expected_source, staged, external):
    if not re.fullmatch(r"[0-9a-f]{40}", expected_source):
        raise ValueError("exact executed source required")
    structural = audit(experiment, expected_source)
    plan, plan_bytes = load(experiment / "preregistered.json")
    scored, _ = load(experiment / "scored-answers.json")
    views, _ = load(experiment / "source-views.json")
    pools, _ = load(experiment / "candidate-pools.json")
    notes, _ = load(experiment / "training-window-labels.json")
    train, dev = (
        load_corpus(external / "train-v2.0.json", "train"),
        load_corpus(external / "dev-v2.0.json", "dev"),
    )
    if (train.sha256, dev.sha256) != (
        plan["dataset_sha256"]["squad_train"],
        plan["dataset_sha256"]["squad_dev"],
    ):
        raise ValueError("publisher bytes differ from preregistered inputs")
    native = {
        name: load_native(
            staged / f"{name}.json",
            name,
            plan["dataset_sha256"][name],
            allow_unresolved_evidence=True,
            session_conflicts="retain-versioned",
            invalid_history="quarantine-question",
            empty_turns="preserve",
        )
        for name in ("locomo", "longmemeval")
    }
    cuts = planned_questions(plan, train, dev, native)
    budget = WindowBudget(**plan["window_budget"])
    expected_ids = {q.identity for qs in cuts.values() for q in qs}
    if set(pools) != expected_ids or set(views) != expected_ids:
        raise ValueError("source/feature census is incomplete or has extra questions")
    rebuilt, questions = {}, {}
    for phase, queries in cuts.items():
        for query in queries:
            corpus = (
                train
                if phase in ("train", "select")
                else dev
                if phase == "squad_test"
                else native[phase]
            )
            docs = (
                (corpus.documents[query.scope],)
                if phase in ("train", "select", "squad_test")
                else corpus.history(query)
            )
            rebuilt[query.identity] = original_pool(
                query, docs, pools[query.identity], views[query.identity], budget
            )
            questions[query.identity] = query
    by_note = {n["question_id"]: n for n in notes}
    for query in cuts["train"]:
        training_fields(
            by_note[query.identity],
            query,
            train.targets[query.identity],
            rebuilt[query.identity],
        )
    summary = {}
    for row in scored:
        phase, qid = row["phase"], row["question_id"]
        query = questions[qid]
        corpus = dev if phase == "squad_test" else native[phase]
        family = (
            query.family if phase == "squad_test" else corpus.families[query.family]
        )
        if row["family"] != family:
            raise ValueError("answer family differs from original dataset grouping")
        fields = score_fields(
            row,
            corpus.targets[qid],
            query,
            rebuilt[qid],
            external=phase == "squad_test",
        )
        counts = summary.setdefault(phase, dict(attempts=0, scored=0, unscored=0))
        counts["attempts"] += 1
        counts["scored"] += fields["f1"] is not None
        counts["unscored"] += fields["f1"] is None
    return dict(
        schema="hepta.masked-span.publisher-reference-check.v1",
        executed_source=expected_source,
        preregistered_sha256=hashlib.sha256(plan_bytes).hexdigest(),
        dataset_sha256=plan["dataset_sha256"],
        original_candidate_pools_rebuilt=len(rebuilt),
        externally_recomputed_training_labels=len(notes),
        externally_recomputed_answer_scores=len(scored),
        phases=summary,
        raw_answers_sha256=structural["raw_answers_sha256"],
        retrieval_optimality_verified=False,
        official_judge_executed=False,
        independently_adjudicated=False,
        semantic_citation_precision=None,
        production_accepted=False,
        superiority_claim=False,
    )


if __name__ == "__main__":
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", type=Path)
    parser.add_argument("expected_source")
    parser.add_argument("staged", type=Path)
    parser.add_argument("external", type=Path)
    args = parser.parse_args()
    result = verify(args.experiment, args.expected_source, args.staged, args.external)
    with (args.experiment / "publisher-reference-check.json").open(
        "x", encoding="utf-8"
    ) as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
