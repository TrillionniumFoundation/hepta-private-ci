"""Strict native source-only TRAIN-selected FTS term ablation.

Reopen the ORIGINAL pretrained MiniLM/as-of SQLite snapshot. All 160 original
and candidate source decisions are written before any native target is read.
No Reader call, Head training, production fallback or semantic judgment.
"""

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile
import time

from native import digest, load
from sessions import source_id
from stem_audit_archive import PinnedArchive, require
from stem_frozen_retrieval_grid_trial import (
    SOURCE,
    TREE,
    ZIP_SHA256,
    verify_pinned_replay_question,
)
from stem_lexical_terms import PROFILE, query_filtered

PHASES = ("train", "select", "retention", "test", "transfer")
ARMS = ("legacy", "filtered")


def write(path, obj):
    with path.open("x", encoding="utf-8") as out:
        json.dump(
            obj, out, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2
        )
        out.write("\n")
        out.flush()
        os.fsync(out.fileno())


def write_rows(path, rows):
    with path.open("x", encoding="utf-8") as out:
        for row in rows:
            out.write(
                json.dumps(row, sort_keys=True, ensure_ascii=False, allow_nan=False)
                + "\n"
            )
        out.flush()
        os.fsync(out.fileno())


def census(plan, rows):
    ids = plan["questions"]
    require(
        set(ids) == set(PHASES)
        and len(ids["train"]) == 48
        and all(len(ids[p]) == 8 for p in PHASES[1:])
        and len({q for group in ids.values() for q in group}) == 80,
        "not the original registered 80 questions",
    )
    original = {}
    expected = {(p, q, a) for p in PHASES for q in ids[p] for a in ARMS}
    for row in rows:
        key = row["phase"], row["question_id"], row["arm"]
        require(
            key in expected
            and key not in original
            and row["source_family"] == plan["question_families"][key[1]]
            and isinstance(row["index_sha256"], str)
            and len(row["index_sha256"]) == 64
            and isinstance(row["pool_sha256"], str)
            and len(row["pool_sha256"]) == 64
            and isinstance(row["retrieved_source_ids"], list)
            and 1 <= len(row["retrieved_source_ids"]) <= 8
            and len(set(row["retrieved_source_ids"]))
            == len(row["retrieved_source_ids"])
            and set(row["window_source_ids"]).issubset(row["retrieved_source_ids"])
            and row["labels_unread"] is True
            and row["reader_calls"] == 0,
            "unsealed or label-bearing source-choice record",
        )
        original[key] = row
    require(set(original) == expected, "missing exact 160 source choices")
    for phase in PHASES:
        for qid in ids[phase]:
            a = original[phase, qid, "legacy"]
            b = original[phase, qid, "filtered"]
            require(
                a["index_sha256"] == b["index_sha256"]
                and a["encoder_identity"] == b["encoder_identity"]
                and a["top_k"] == b["top_k"] == 8
                and a["channel_k"] == b["channel_k"] == 64
                and a["lexical_weight"] == b["lexical_weight"] == 0.5
                and a["pool_matches_original"] is True,
                "source/Encoder/budget drift or missing frozen original parity",
            )
    return original


def weak_hit(row, target):
    if target.unanswerable or target.unresolved_evidence or not target.evidence:
        return None
    parents = {source_id(s) for s in target.evidence}
    # A single matched prerequisite cannot count as a complete multi-hop set.
    return parents.issubset(set(row["window_source_ids"]))


def choose_from_train(plan, records, targets):
    """Only the original 48 TRAIN labels may select the lexical term policy."""
    cohort = plan["questions"]["train"]
    require(set(targets) == set(cohort), "TRAIN-only exact source labels required")
    summaries = {}
    for arm in ARMS:
        families = {}
        scored = 0
        for qid in cohort:
            row = records["train", qid, arm]
            hit = weak_hit(row, targets[qid])
            if hit is not None:
                families.setdefault(row["source_family"], []).append(float(hit))
                scored += 1
        require(families and scored > 0, "no TRAIN native support labels")
        macro = sum(sum(v) / len(v) for v in families.values()) / len(families)
        summaries[arm] = dict(
            family_macro_window_weak_hit=macro,
            scored=scored,
            unscored=len(cohort) - scored,
            families=len(families),
        )
    # Ties and non-improvement retain original frozen RAG.
    chosen = (
        "filtered"
        if summaries["filtered"]["family_macro_window_weak_hit"]
        > summaries["legacy"]["family_macro_window_weak_hit"] + 1e-12
        else "legacy"
    )
    return dict(
        schema="hepta.stem.lexical-query-train-choice.v1",
        selected=chosen,
        scores=summaries,
        trained_on_only_48_development_questions=True,
        no_heldout_question_labels_seen=True,
        unchanged_index_encoder_and_reader=True,
        production_accepted=False,
    )


def assess(plan, records, targets, chosen):
    expected = {q for p in PHASES[1:] for q in plan["questions"][p]}
    require(
        set(targets) == expected and chosen["selected"] in ARMS,
        "held-out labels or selection configuration drift",
    )
    results = {}
    for phase in PHASES[1:]:
        counts = dict(
            planned=8,
            resolved=0,
            unscored=0,
            original_hits=0,
            selected_hits=0,
            gains=0,
            losses=0,
            changed_top8=0,
        )
        for qid in plan["questions"][phase]:
            a = records[phase, qid, "legacy"]
            b = records[phase, qid, chosen["selected"]]
            x, y = weak_hit(a, targets[qid]), weak_hit(b, targets[qid])
            counts["changed_top8"] += (
                a["retrieved_source_ids"] != b["retrieved_source_ids"]
            )
            if x is None or y is None:
                require(x is None and y is None, "label drift between arms")
                counts["unscored"] += 1
            else:
                counts["resolved"] += 1
                counts["original_hits"] += int(x)
                counts["selected_hits"] += int(y)
                counts["gains"] += int(y and not x)
                counts["losses"] += int(x and not y)
        results[phase] = counts
    return dict(
        schema="hepta.stem.lexical-query-native-recall.v1",
        frozen_train_choice=chosen["selected"],
        source_only_original_reader_calls=0,
        baseline_unchanged=True,
        native_document_weak_support_not_entailment=True,
        requires_all_declared_native_support_sources=True,
        observed_original_answer_quality_gain=False,
        independently_authenticated_future_families=0,
        independent_semantic_citation_precision=None,
        production_accepted=False,
        by_phase=results,
    )


def replay(artifact, staged, output):
    from index import PersistentIndex, RetrievalPolicy
    from pretrained import Encoder, file_inventory
    from selector_windows import WindowBudget, candidate_windows

    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    archive = PinnedArchive(Path(artifact), ZIP_SHA256)
    try:
        require(
            archive.read("tested-commit.txt").decode().strip() == SOURCE
            and archive.read("tested-tree.txt").decode().strip() == TREE,
            "original strict as-of run identity changed",
        )
        plan = archive.json("comparison/preregistered.json")
        require(
            plan["source_commit"] == SOURCE
            and plan["source_visibility_policy"]
            == "strict-as-of-before-index-and-every-Encoder-v1"
            and plan["calibration_or_final_label_hyperparameter_search"] is False,
            "original source/query split changed",
        )
        admiss = archive.json("comparison/source-admission.json")
        originals = {}
        for row in archive.jsonl("comparison/encoding.jsonl"):
            if row["backend"] == "frozen" and row["cost"]["cache_hit"] is False:
                qid = row["question_id"]
                require(qid not in originals, "duplicate original pool")
                originals[qid] = row["cost"]["extraction"]["pool_digest"]
        ids = {q for phase in PHASES for q in plan["questions"][phase]}
        require(set(originals) == ids, "original 80 pool identities missing")
        sources = {
            kind: load(
                Path(staged) / f"{kind}.json",
                kind,
                plan["dataset_sha256"][kind],
                allow_unresolved_evidence=True,
                session_conflicts="retain-versioned",
                invalid_history="quarantine-question",
                empty_turns="preserve",
            )
            for kind in ("locomo", "longmemeval")
        }
        questions, benchmark_for = {}, {}
        for source in sources.values():
            for question in source.questions:
                if question.identity in ids:
                    require(
                        question.identity not in questions, "duplicate dataset query"
                    )
                    verify_pinned_replay_question(
                        question, source, ids, plan["question_families"]
                    )
                    questions[question.identity] = question
                    benchmark_for[question.identity] = source
        require(set(questions) == ids, "original native query census mismatch")
        encoder = Encoder(Path(staged) / "encoder")
        require(
            encoder.identity == plan["retriever_inventory"]
            and digest(file_inventory(Path(staged) / "encoder"))
            == plan["retriever_inventory"],
            "pinned MiniLM drift",
        )
        budgets = WindowBudget(**plan["window_budget"])
        policies = RetrievalPolicy(
            top_k=8, channel_k=64, lexical_weight=0.5, rrf_constant=60
        )
        rows, indices = [], {}
        started = time.perf_counter()
        with tempfile.TemporaryDirectory() as temp:
            try:
                for phase in PHASES:
                    for qid in plan["questions"][phase]:
                        q = questions[qid]
                        source = benchmark_for[qid]
                        key = digest((source.source_sha256, q.scope, q.observed_at))
                        if key not in indices:
                            pin = admiss[key]
                            raw = archive.read(f"comparison/index-{key}.sqlite")
                            dbfile = Path(temp) / f"index-{key}.sqlite"
                            dbfile.write_bytes(raw)
                            indices[key] = PersistentIndex(
                                dbfile,
                                pin["as_of_cut"],
                                set(),
                                expected_file_digest=pin["verified_index_digest"],
                                expected_encoder=encoder.identity,
                            )
                        index = indices[key]
                        vector = encoder.encode([q.content])[0]
                        legacy, receipt = index.query(
                            q,
                            vector,
                            policies,
                            current_cut=admiss[key]["as_of_cut"],
                            revoked=set(),
                        )
                        filtered, freceipt = query_filtered(
                            index,
                            q,
                            vector,
                            policies,
                            current_cut=admiss[key]["as_of_cut"],
                            revoked=set(),
                        )
                        for arm, docs in (
                            ("legacy", tuple(legacy)),
                            ("filtered", filtered),
                        ):
                            pool = candidate_windows(
                                docs,
                                q,
                                revoked=set(),
                                budget=budgets,
                                profile="query_windows",
                            )
                            matches = (
                                pool.seal() == originals[qid]
                                if arm == "legacy"
                                else None
                            )
                            if arm == "legacy":
                                require(
                                    matches
                                    and receipt["projection_cut"]
                                    == admiss[key]["as_of_cut"],
                                    "legacy original source/candidate parity failed",
                                )
                            rows.append(
                                dict(
                                    phase=phase,
                                    question_id=qid,
                                    arm=arm,
                                    source_family=plan["question_families"][qid],
                                    index_sha256=receipt["index_artifact_digest"],
                                    encoder_identity=encoder.identity,
                                    top_k=8,
                                    channel_k=64,
                                    lexical_weight=0.5,
                                    original_pool_sha256=originals[qid],
                                    pool_sha256=pool.seal(),
                                    pool_matches_original=matches,
                                    retrieved_source_ids=[
                                        source_id(d.identity) for d in docs
                                    ],
                                    window_source_ids=sorted(
                                        {source_id(w.source_id) for w in pool.windows}
                                    ),
                                    labels_unread=True,
                                    reader_calls=0,
                                    filtered_lexical_term_count=(
                                        freceipt["lexical_term_count"]
                                        if arm == "filtered"
                                        else None
                                    ),
                                )
                            )
            finally:
                for index in indices.values():
                    index.close()
        records = census(plan, rows)
        # THIS receipt must be durable before the post-policy gold label cut.
        write_rows(output / "all-label-blind-choices.jsonl", rows)
        train = {
            qid: benchmark_for[qid].targets[qid] for qid in plan["questions"]["train"]
        }
        selected = choose_from_train(plan, records, train)
        write(output / "train-only-choice.json", selected)
        later = {
            qid: benchmark_for[qid].targets[qid]
            for phase in PHASES[1:]
            for qid in plan["questions"][phase]
        }
        report = assess(plan, records, later, selected)
        report.update(
            tested_source_sha256=archive.sha256,
            registered_source_commit=SOURCE,
            registered_source_tree=TREE,
            tested_commit=__import__("os").environ.get("HEPTA_MEMORY_TESTED_COMMIT"),
            original_reader_calls=0,
            original_index_count=len(indices),
            original_question_count=80,
            original_candidate_attempts=len(rows),
            actual_mini_lm_query_seconds=time.perf_counter() - started,
            fixed_lexical_profile=PROFILE,
        )
        write(output / "report.json", report)
        return report
    finally:
        archive.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict-zip", type=Path, required=True)
    parser.add_argument("--staged", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            replay(args.strict_zip, args.staged, args.out),
            sort_keys=True,
            ensure_ascii=False,
        )
    )
