"""Execute TRAIN-selected, fixed-budget frozen retrieval RRF grid on pinned data.

Strict original source/time/index/Encoder artifacts are replayed; nothing here
calls the pretrained Reader, fits a Head, changes the original matrix or
chooses hyperparameters using the evaluation labels.
"""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import time

from native import digest, load
from sessions import source_id
from stem_audit_archive import PinnedArchive, require
from stem_frozen_retrieval_grid import (
    BASELINE,
    GRID,
    PHASES,
    annotate,
    evaluate_fixed,
    label_key,
    select_from_train,
    validate_unlabelled,
)

SOURCE = "675970bb610c70bb0ec30a2dee05c025440510e6"
TREE = "d280ba53070fb6457c04ff0d97fbb14ebbdbc3fb"
ZIP_SHA256 = "1db7f8f7c13a1f718d5065956f14d554d3fe328c415fac4bb145d1eaf9d913c8"


def write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


def write_jsonl(path, rows):
    with path.open("x", encoding="utf-8") as stream:
        for row in rows:
            stream.write(
                json.dumps(
                    row,
                    sort_keys=True,
                    ensure_ascii=False,
                    allow_nan=False,
                )
                + "\n"
            )


def verify_pinned_replay_question(
    question, benchmark, registered_ids, declared_families
):
    """Bind a replayed native question to its ORIGINAL frozen cohort.

    Do not call Benchmark.partition here: this is a verification of a
    preregistered question, not a new split of this evaluation dataset.
    Source-file SHA-256 and phase identity are already externally pinned.
    """
    require(
        isinstance(question.identity, str)
        and bool(question.identity)
        and question.identity in registered_ids
        and question.identity in declared_families
        and isinstance(question.scope, str)
        and bool(question.scope)
        and isinstance(question.family, str)
        and bool(question.family)
        and question.family in benchmark.families
        and benchmark.families[question.family] == declared_families[question.identity],
        "native question/Cell source family differs from frozen original plan",
    )
    return question.identity


def replay_pinned(artifact, staged, output):
    from index import PersistentIndex, RetrievalPolicy
    from pretrained import Encoder, file_inventory
    from selector_windows import WindowBudget, candidate_windows

    artifact, staged, output = Path(artifact), Path(staged), Path(output)
    output.mkdir(exist_ok=False, parents=True)
    archive = PinnedArchive(artifact, ZIP_SHA256)
    try:
        require(
            archive.read("tested-commit.txt").decode().strip() == SOURCE
            and archive.read("tested-tree.txt").decode().strip() == TREE,
            "strict original model/Reader/index source pin changed",
        )
        plan = archive.json("comparison/preregistered.json")
        require(
            plan["source_commit"] == SOURCE
            and plan["source_visibility_policy"]
            == "strict-as-of-before-index-and-every-Encoder-v1"
            and plan["calibration_or_final_label_hyperparameter_search"] is False,
            "not the originally registered frozen retrieval environment",
        )
        admiss = archive.json("comparison/source-admission.json")
        budgets = WindowBudget(**plan["window_budget"])
        original_encoding = {}
        for receipt in archive.jsonl("comparison/encoding.jsonl"):
            if receipt["backend"] != "frozen" or receipt["cost"]["cache_hit"]:
                continue
            qid = receipt["question_id"]
            require(qid not in original_encoding, "duplicate original frozen query")
            original_encoding[qid] = receipt["cost"]["extraction"]["pool_digest"]
        original_ids = {qid for phase in PHASES for qid in plan["questions"][phase]}
        require(
            set(original_encoding) == original_ids, "missing original frozen encoding"
        )

        sources = {
            kind: load(
                staged / f"{kind}.json",
                kind,
                plan["dataset_sha256"][kind],
                allow_unresolved_evidence=True,
                session_conflicts="retain-versioned",
                invalid_history="quarantine-question",
                empty_turns="preserve",
            )
            for kind in ("locomo", "longmemeval")
        }
        source_for = {}
        queries = {}
        for kind, benchmark in sources.items():
            for q in benchmark.questions:
                if q.identity in original_ids:
                    require(
                        q.identity not in queries, "duplicate native benchmark question"
                    )
                    verify_pinned_replay_question(
                        q, benchmark, original_ids, plan["question_families"]
                    )
                    queries[q.identity] = q
                    source_for[q.identity] = benchmark
        require(set(queries) == original_ids, "original native question identity drift")

        encoder = Encoder(staged / "encoder")
        require(
            encoder.identity == plan["retriever_inventory"]
            and digest(file_inventory(staged / "encoder"))
            == plan["retriever_inventory"],
            "frozen retrieval Encoder model file pin drift",
        )
        started = time.perf_counter()
        observations = []
        index_times = {}
        with tempfile.TemporaryDirectory() as temporary:
            opened = {}
            try:
                for phase in PHASES:
                    for qid in plan["questions"][phase]:
                        q = queries[qid]
                        source = source_for[qid]
                        key = digest((source.source_sha256, q.scope, q.observed_at))
                        if key not in opened:
                            required = admiss[key]
                            filename = f"comparison/index-{key}.sqlite"
                            raw = archive.read(filename)
                            disk = Path(temporary) / f"index-{key}.sqlite"
                            disk.write_bytes(raw)
                            opened[key] = PersistentIndex(
                                disk,
                                required["as_of_cut"],
                                set(),
                                expected_file_digest=required["verified_index_digest"],
                                expected_encoder=encoder.identity,
                            )
                            index_times[key] = dict(
                                scope=q.scope,
                                question_time=q.observed_at,
                                file_digest=required["verified_index_digest"],
                                cut=required["as_of_cut"],
                                as_of_eligible_docs=required["receipt"][
                                    "admitted_count"
                                ],
                                excluded_future_docs=required["receipt"][
                                    "excluded_future_count"
                                ],
                            )
                        index = opened[key]
                        vector = encoder.encode([q.content])[0]
                        for channel_k, lexical_weight in GRID:
                            policy = RetrievalPolicy(
                                top_k=8,
                                channel_k=channel_k,
                                lexical_weight=lexical_weight,
                                rrf_constant=60,
                            )
                            retrieved, cost = index.query(
                                q,
                                vector,
                                policy,
                                current_cut=admiss[key]["as_of_cut"],
                                revoked=set(),
                            )
                            pool = candidate_windows(
                                tuple(retrieved),
                                q,
                                revoked=set(),
                                budget=budgets,
                                profile="query_windows",
                            )
                            original = (
                                pool.seal() == original_encoding[qid]
                                if (channel_k, lexical_weight) == BASELINE
                                else None
                            )
                            if (channel_k, lexical_weight) == BASELINE:
                                require(original, "original pool SHA mismatch: " + qid)
                                require(
                                    cost["encoder_identity"] == encoder.identity
                                    and cost["projection_cut"]
                                    == admiss[key]["as_of_cut"],
                                    "frozen retrieval source/cut identity mismatch",
                                )
                            observations.append(
                                dict(
                                    phase=phase,
                                    question_id=qid,
                                    source_family=plan["question_families"][qid],
                                    policy=label_key((channel_k, lexical_weight)),
                                    retrieved_source_ids=[
                                        source_id(d.identity) for d in retrieved
                                    ],
                                    window_source_ids=sorted(
                                        {source_id(w.source_id) for w in pool.windows}
                                    ),
                                    pool_sha256=pool.seal(),
                                    original_as_of_index_sha256=cost[
                                        "index_artifact_digest"
                                    ],
                                    replayed_original_pool_sha256=original,
                                    candidate_windows=len(pool.windows),
                                    actual_retrieval_seconds=cost["query_ns"] / 1e9,
                                    source_text_exported=False,
                                    read_targets_for_retrieval=False,
                                )
                            )
            finally:
                for idx in opened.values():
                    idx.close()
        # Commit ALL 800 label-blind receipts BEFORE any score/label is read.
        write_jsonl(output / "all-label-blind-candidates.jsonl", observations)
        unlabelled = validate_unlabelled(plan, observations)
        labels = {
            qid: source_for[qid].targets[qid] for qid in plan["questions"]["train"]
        }
        calibration = select_from_train(plan, unlabelled, labels)
        write(output / "train-only-calibration.json", calibration)
        # No retrieval policy or candidate rows can change after this write.
        eval_targets = {
            qid: source_for[qid].targets[qid]
            for phase in PHASES[1:]
            for qid in plan["questions"][phase]
        }
        evaluated = evaluate_fixed(plan, unlabelled, eval_targets, calibration)
        write(output / "unseen-question-source-recall.json", evaluated)
        write(
            output / "experiment-manifest.json",
            dict(
                schema="hepta.stem-frozen-retrieval-grid-execution.v1",
                generating_source=SOURCE,
                generating_tree=TREE,
                generating_zip_sha256=archive.sha256,
                original_manifest_members=archive.manifest_entries,
                number_original_questions=80,
                number_label_blind_candidate_queries=len(observations),
                number_asof_immutable_indexes=len(index_times),
                original_pool_identities_replayed=80,
                immutable_source_cuts=list(index_times.values()),
                actual_frozen_query_encoder_seconds=time.perf_counter() - started,
                original_pretrained_reader_calls=0,
                original_pair_encoder_calls=0,
                independent_test_label_used_for_training=False,
                externally_reviewed_passage_entailment=False,
                product_metric_improvement_claimed=False,
                semantic_citation_precision=None,
                production_accepted=False,
            ),
        )
        return evaluated
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
            replay_pinned(
                args.strict_zip,
                args.staged,
                args.out,
            ),
            sort_keys=True,
            ensure_ascii=False,
        )
    )
