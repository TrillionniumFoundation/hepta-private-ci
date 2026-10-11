"""Precommit family-disjoint PUBLIC native-reader inputs without test labels.

A source-family proxy is not an independently verified source family, a future
window, a human sufficiency judgement, or production admission. No model runs.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re

PROFILE = "hepta.memorycell.external-family-population.v1"
SOURCE_PINS = {
    "locomo": "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4",
    "longmemeval": "d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442",
}
SPLITS = ("train", "selection", "evaluation")
LIMITS = {"train": 128, "selection": 64, "evaluation": 64}
MAX_PER_FAMILY = 8


def canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def digest(value):
    return sha256(canonical(value)).hexdigest()


def _rank(*parts):
    return digest([PROFILE, *parts])


@dataclass(frozen=True)
class PublicCorpus:
    name: str
    source_sha256: str
    documents: tuple
    questions: tuple
    families: dict

    @classmethod
    def from_native(cls, benchmark):
        # Explicitly project AWAY targets/QA labels before building the plan.
        return cls(
            benchmark.name,
            benchmark.source_sha256,
            tuple(benchmark.documents),
            tuple(benchmark.questions),
            dict(benchmark.families),
        )


def _corpus_rows(corpus):
    if (
        corpus.name not in SOURCE_PINS
        or corpus.source_sha256 != SOURCE_PINS[corpus.name]
    ):
        raise ValueError("published native dataset bytes are not pinned")
    if len(corpus.questions) < 10 or len(corpus.documents) < 10:
        raise ValueError("insufficient published questions or history")
    questions = {q.identity: q for q in corpus.questions}
    docs = {d.identity: d for d in corpus.documents}
    if len(questions) != len(corpus.questions) or len(docs) != len(corpus.documents):
        raise ValueError("duplicate native identity")
    family_for = {}
    for q in questions.values():
        if q.family not in corpus.families:
            raise ValueError("unregistered native source-family proxy")
        family_for[q.identity] = corpus.families[q.family]
    groups = sorted(
        set(family_for.values()),
        key=lambda f: (_rank(corpus.name, corpus.source_sha256, f), f),
    )
    if len(groups) < 10:
        raise ValueError("fewer than ten family-disjoint published groups")
    n_train = max(1, math.floor(len(groups) * 0.6))
    n_select = max(1, math.floor(len(groups) * 0.2))
    if len(groups) - n_train - n_select < 2:
        raise ValueError("insufficient held-out family groups")
    assignment = {
        g: (
            "train"
            if i < n_train
            else "selection"
            if i < n_train + n_select
            else "evaluation"
        )
        for i, g in enumerate(groups)
    }
    # Reject a document root crossing any split. Native families already union
    # reused LongMemEval sessions; this is an additional defensive check.
    scope_family = {}
    for q in questions.values():
        proxy = family_for[q.identity]
        if q.scope in scope_family and scope_family[q.scope] != proxy:
            raise ValueError("one history scope mapped to two source-family proxies")
        scope_family[q.scope] = proxy
    root_split = {}
    scope_docs = {}
    for d in docs.values():
        if d.scope not in scope_family:
            raise ValueError("orphan history scope")
        split = assignment[scope_family[d.scope]]
        if d.root in root_split and root_split[d.root] != split:
            raise ValueError("original source root leaks across partitions")
        root_split[d.root] = split
        scope_docs.setdefault(d.scope, []).append(d)
    for q in questions.values():
        if q.scope not in scope_docs:
            raise ValueError("question without independently pinned history")
    buckets = {split: [] for split in SPLITS}
    by_group = {g: [] for g in groups}
    for q in questions.values():
        by_group[family_for[q.identity]].append(q)
    for group in groups:
        members = sorted(
            by_group[group], key=lambda q: (_rank(corpus.name, q.identity), q.identity)
        )
        for q in members[:MAX_PER_FAMILY]:
            documents = sorted(scope_docs[q.scope], key=lambda d: d.identity)
            document_census = [
                (
                    d.identity,
                    d.root,
                    d.observed_at,
                    sha256(d.content.encode()).hexdigest(),
                )
                for d in documents
            ]
            if any(d.scope != q.scope for d in documents):
                raise ValueError("cross-scope native document")
            buckets[assignment[group]].append(
                dict(
                    dataset=corpus.name,
                    question_id=q.identity,
                    native_family=q.family,
                    family_proxy_digest=digest([corpus.name, group]),
                    question=q.content,
                    observation_time=q.observed_at,
                    scope=q.scope,
                    source_ids=[d.identity for d in documents],
                    source_roots_digest=digest(sorted({d.root for d in documents})),
                    source_census_sha256=digest(document_census),
                )
            )
    return buckets, {
        "source_sha256": corpus.source_sha256,
        "total_questions": len(questions),
        "family_proxy_groups": len(groups),
        "split_family_proxies": {
            split: sum(v == split for v in assignment.values()) for split in SPLITS
        },
        "complete_history_sources": len(docs),
        "source_root_proxies": len(root_split),
    }


def source_only_family_capacity(corpora, *, source_commit):
    """Report genuine published family capacity without consulting QA labels.

    This is deliberately NOT a fallback that splits shared source families by
    question ID. A failure leaves all targets sealed and does not certify an
    independent or future population.
    """
    if (
        not isinstance(source_commit, str)
        or re.fullmatch(r"[0-9a-f]{40}", source_commit) is None
        or set(corpora) != set(SOURCE_PINS)
        or any(corpora[k].name != k for k in SOURCE_PINS)
    ):
        raise ValueError("pinned two-corpus source and tested commit required")
    census = {}
    for name in sorted(SOURCE_PINS):
        corpus = corpora[name]
        if corpus.source_sha256 != SOURCE_PINS[name]:
            raise ValueError("original published source byte pin differs")
        qids = [q.identity for q in corpus.questions]
        docids = [d.identity for d in corpus.documents]
        if len(set(qids)) != len(qids) or len(set(docids)) != len(docids):
            raise ValueError("duplicated native source or question identity")
        if any(q.family not in corpus.families for q in corpus.questions):
            raise ValueError("missing original native source-family proxy")
        groups = {corpus.families[q.family] for q in corpus.questions}
        n = len(groups)
        train_n = math.floor(n * 0.6)
        selection_n = math.floor(n * 0.2)
        evaluation_n = n - train_n - selection_n
        capacity = (
            len(qids) >= 10
            and len(docids) >= 10
            and n >= 10
            and train_n >= 1
            and selection_n >= 1
            and evaluation_n >= 2
        )
        census[name] = dict(
            pinned_source_sha256=corpus.source_sha256,
            native_question_count=len(qids),
            native_document_count=len(docids),
            actual_native_family_proxy_count=n,
            minimum_required_family_proxies=10,
            split_family_capacity=dict(
                train=train_n,
                selection=selection_n,
                evaluation=evaluation_n,
            ),
            family_capacity_sufficient=capacity,
            shortfall_from_ten=max(0, 10 - n),
            families_not_artificially_split_by_question=True,
        )
    ready = all(x["family_capacity_sufficient"] for x in census.values())
    return dict(
        schema="hepta.memorycell.external-family-capacity.v1",
        tested_source_commit=source_commit,
        source_only_preflight=True,
        original_source_sha256=dict(SOURCE_PINS),
        corpora=census,
        original_published_family_capacity_sufficient=ready,
        insufficient_source_families_block_promotion=not ready,
        targets_inspected_by_this_function=False,
        actual_future_observations=None,
        actual_prospective_window_measured=False,
        published_historical_data_not_future_observations=True,
        independent_source_authenticity_verified=False,
        independently_adjudicated_semantic_support=False,
        generated_answers=0,
        production_accepted=False,
    )


def prepare_population(corpora, *, source_commit, limits=None):
    """Do not accept targets as an input: question/corpus metadata only."""
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("exact tested source commit required")
    if set(corpora) != set(SOURCE_PINS) or any(corpora[k].name != k for k in corpora):
        raise ValueError("both pinned external benchmarks required")
    limits = dict(LIMITS if limits is None else limits)
    if set(limits) != set(SPLITS) or any(
        type(v) is not int or v < 1 or v > 1000 for v in limits.values()
    ):
        raise ValueError("unregistered split budget")
    # A shared native root across two purportedly distinct benchmarks is not
    # independently sourced, even if the provider's names differ.
    seen_roots = {}
    for dataset, corpus in corpora.items():
        for doc in corpus.documents:
            previous = seen_roots.setdefault(doc.root, dataset)
            if previous != dataset:
                raise ValueError("original source root reused across corpora")
    all_rows = {split: [] for split in SPLITS}
    census = {}
    for name in sorted(corpora):
        rows, info = _corpus_rows(corpora[name])
        census[name] = info
        for split in SPLITS:
            all_rows[split].extend(rows[split])
    # Stratified, round-robin across dataset and family rather than taking
    # the first N questions from one oversized native history.
    final = {}
    for split in SPLITS:
        buckets = {}
        for row in all_rows[split]:
            buckets.setdefault((row["dataset"], row["family_proxy_digest"]), []).append(
                row
            )
        order = sorted(buckets, key=lambda x: (_rank(split, *x), x))
        for key in order:
            buckets[key].sort(
                key=lambda row: (_rank(row["question_id"]), row["question_id"])
            )
        selected = []
        for index in range(MAX_PER_FAMILY):
            for key in order:
                if index < len(buckets[key]) and len(selected) < limits[split]:
                    selected.append(buckets[key][index])
        if not selected or {row["dataset"] for row in selected} != set(SOURCE_PINS):
            raise ValueError("missing either dataset in a family split")
        final[split] = selected
    qids = [row["question_id"] for rows in final.values() for row in rows]
    family_pairs = [
        (row["dataset"], row["family_proxy_digest"], split)
        for split, rows in final.items()
        for row in rows
    ]
    if len(qids) != len(set(qids)):
        raise ValueError("question ID crosses published corpora or partitions")
    for dataset, family, split in family_pairs:
        if any(
            ds == dataset and f == family and s != split for ds, f, s in family_pairs
        ):
            raise ValueError("near-family assignment crosses split")
    return dict(
        schema=PROFILE,
        tested_source_commit=source_commit,
        source_sha256=dict(SOURCE_PINS),
        cut_rule="native reused-source root union, hashed family proxy 60/20/20; no target-access",
        question_pick_rule="family round-robin, opaque SHA order, at most 8 per family",
        limits=limits,
        model_input_contains_answers=False,
        program_oracle_is_human_reviewed=False,
        published_benchmarks_are_future_observations=False,
        independent_source_authenticity_verified=False,
        independent_semantic_judgement=False,
        production_accepted=False,
        corpus_census=census,
        splits=final,
    )


def preflight_and_prepare(corpora, *, source_commit, output):
    """Emit a tamper-evident source-only failure receipt before opening labels.

    The parent output remains absent when family capacity fails, so no
    partial public/target artifact can be mistaken for a sealed population.
    """
    if not isinstance(output, Path) or output.exists():
        raise ValueError("fresh immutable output location required")
    capacity = source_only_family_capacity(
        corpora,
        source_commit=source_commit,
    )
    path = output.with_name(output.name + "-capacity.json")
    with path.open("xb") as stream:
        stream.write(canonical(capacity) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    if not capacity["original_published_family_capacity_sufficient"]:
        raise ValueError(
            "insufficient actual family-disjoint published source groups; "
            "no label/Reader experiment authorized: " + str(path)
        )
    return prepare_population(corpora, source_commit=source_commit)


def publish_and_seal(public, target_supplier, output):
    """Persist PUBLIC inputs first; only then open targets in a separate file."""
    if output.exists():
        raise FileExistsError("immutable population output required")
    output.mkdir(parents=True)
    pub = output / "public"
    private = output / "targets"
    pub.mkdir()
    private.mkdir()
    encoded = canonical(public) + b"\n"
    with (pub / "population.json").open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    labels = target_supplier()
    allowed = {row["question_id"] for rows in public["splits"].values() for row in rows}
    if set(labels) != allowed:
        raise ValueError("labels inconsistent with precommitted question census")
    reduced = {}
    for qid, target in labels.items():
        reduced[qid] = dict(
            answer=target.answer,
            support=list(target.evidence),
            category=target.category,
            unanswerable=target.unanswerable,
            unresolved_support=list(target.unresolved_evidence),
        )
    data = canonical(reduced) + b"\n"
    with (private / "targets.json").open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    manifest = dict(
        schema=PROFILE,
        public_population_sha256=sha256(encoded).hexdigest(),
        private_target_sha256=sha256(data).hexdigest(),
        question_count=len(allowed),
        independent_future_family_count=0,
        source_authenticity_reviewed=False,
        generated_answers=0,
        production_accepted=False,
    )
    with (output / "sealed-manifest.json").open("xb") as stream:
        stream.write(canonical(manifest) + b"\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("locomo", type=Path)
    parser.add_argument("longmemeval", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    from native import load

    corpora = {}
    benchmarks = {}
    for kind, path in (("locomo", args.locomo), ("longmemeval", args.longmemeval)):
        loaded = load(
            path,
            kind,
            SOURCE_PINS[kind],
            allow_unresolved_evidence=True,
            session_conflicts="retain-versioned",
            invalid_history="quarantine-question",
        )
        benchmarks[kind] = loaded
        corpora[kind] = PublicCorpus.from_native(loaded)
    public = preflight_and_prepare(
        corpora,
        source_commit=args.source_commit,
        output=args.output,
    )
    selected = {
        row["question_id"] for rows in public["splits"].values() for row in rows
    }

    def labels():
        return {
            qid: target
            for benchmark in benchmarks.values()
            for qid, target in benchmark.targets.items()
            if qid in selected
        }

    print(json.dumps(publish_and_seal(public, labels, args.output), sort_keys=True))


if __name__ == "__main__":
    main()
