"""Audit two byte-pinned historical stem runs without model or target access.

The earlier all-successful run does not establish learning: it used an earlier
Reader admission implementation, and all learning arms matched frozen choices.
Do NOT certify current-source success from either immutable historical ZIP.
"""

import argparse
from collections import Counter
import json
from pathlib import Path

from stem_audit_archive import PinnedArchive, require
from stem_audit_reader_condition import frozen_condition

ORIGINAL = (
    "e9c8f9c9cfc8df8887290db707598897cbc26ede",
    "197ea54ba9e2f11524d303825cdad17fc4e89933",
    "3e09533c535f6b847f9ec58d4f56055d3a2c6adb2eee68705873584a72aca909",
)
EARLIER_SUCCESS = (
    "306c2c8dc745b22f4dc137fdfec5e83158189964",
    "4e84e9443c68fa12cff3e4235d4dd18b0611ee77",
    "2f15aa0a6c4900b2cf19cc03051f2727c58c9c04c1d993eda6486e019d0d0014",
)
STAGES = (16, 32, 48)
PHASES = ("select", "retention", "test", "transfer")
ARMS = (
    "frozen_rerank",
    "prototype",
    "linear",
    "gated",
    "lineage_lora_gated",
    "independent_lora_gated",
)
REGISTRATION_KEYS = (
    "schema",
    "dataset_sha256",
    "questions",
    "question_families",
    "families",
    "routes",
    "arms",
    "curriculum_attempted_examples",
    "cells",
    "reader_inventory",
    "retriever_inventory",
    "generator_config",
    "generator_template_digest",
    "primary_policy",
)


def index_census(plan, rows):
    """Census every registered question/arm/stage; duplicate is a hard error."""
    require(tuple(plan["arms"]) == ARMS, "unregistered arm ordering")
    require(
        tuple(plan["curriculum_attempted_examples"]) == STAGES,
        "unregistered checkpoint schedule",
    )
    require(len(plan["questions"]["train"]) == 48, "training cut size drift")
    questions = {p: plan["questions"][p] for p in PHASES}
    require(
        all(len(ids) == 8 and len(set(ids)) == 8 for ids in questions.values()),
        "phase cohort count drift",
    )
    registered = [q for ids in plan["questions"].values() for q in ids]
    require(
        len(registered) == len(set(registered)) == 80,
        "question identity duplication across partitions",
    )
    expected = {
        (stage, phase, qid, arm)
        for stage in STAGES
        for phase in PHASES
        for qid in questions[phase]
        for arm in ARMS
    }
    indexed = {}
    for row in rows:
        key = row["stage"], row["phase"], row["question_id"], row["arm"]
        require(key not in indexed, "duplicate policy attempt")
        require(row["status"] in ("failed", "succeeded"), "unknown policy status")
        indexed[key] = row
    require(
        len(indexed) == 576 and set(indexed) == expected,
        "missing or unregistered policy identity",
    )
    return indexed


def candidate_distribution(plan, frozen_encoding):
    expected = {
        qid: phase for phase, group in plan["questions"].items() for qid in group
    }
    seen = {}
    for row in frozen_encoding:
        if row["backend"] != "frozen" or row["cost"]["cache_hit"]:
            continue
        qid = row["question_id"]
        require(qid in expected, "unknown frozen Encoder query")
        n = row["cost"]["extraction"]["pairs"]
        require(type(n) is int and 0 <= n <= 64, "invalid frozen candidate count")
        require(
            qid not in seen or seen[qid] == n,
            "candidate cardinality changed on repeated original encoding",
        )
        seen[qid] = n
    require(set(seen) == set(expected), "missing frozen question encoding")
    return {
        phase: dict(
            questions=len(qids),
            histogram={
                str(n): sum(seen[q] == n for q in qids)
                for n in sorted({seen[q] for q in qids})
            },
            no_candidates=sum(seen[q] == 0 for q in qids),
            one_candidate=sum(seen[q] == 1 for q in qids),
            competing_candidate_pools=sum(seen[q] >= 2 for q in qids),
        )
        for phase, qids in plan["questions"].items()
    }


def compare_receipts(
    original_plan, original_rows, legacy_plan, legacy_rows, legacy_encoding
):
    for field in REGISTRATION_KEYS:
        require(
            original_plan[field] == legacy_plan[field],
            "cohort, Reader, model or experiment registration drift: " + field,
        )
    first = index_census(original_plan, original_rows)
    later = index_census(legacy_plan, legacy_rows)
    before, after = (
        Counter(x["status"] for x in first.values()),
        Counter(x["status"] for x in later.values()),
    )
    require(
        before == {"succeeded": 396, "failed": 180},
        "original policy status totals changed",
    )
    require(
        after == {"succeeded": 576}, "legacy success artifact is not a complete matrix"
    )

    exact_answer_preservations = 0
    cross_run_selection_changes = []
    for key in sorted(first):
        old, new = first[key], later[key]
        require(new["status"] == "succeeded", "legacy score missing")
        if old.get("selected") != new.get("selected"):
            cross_run_selection_changes.append(key)
        if old["status"] == "succeeded":
            a, b = old["receipt"], new["receipt"]
            require(
                old["selected"] == new["selected"]
                and old["answer"] == new["answer"]
                and a["delivered_evidence"] == b["delivered_evidence"]
                and all(
                    a[name] == b[name]
                    for name in (
                        "generator_identity",
                        "generator_profile",
                        "input_ids_digest",
                        "generated_ids_digest",
                    )
                ),
                "previously successful raw Reader output or request was rewritten",
            )
            exact_answer_preservations += 1

    arm_effects = {}
    for arm in ARMS[1:]:
        total, changed, changed_answer = 0, 0, 0
        for stage in STAGES:
            for phase in PHASES:
                for qid in legacy_plan["questions"][phase]:
                    base = later[(stage, phase, qid, ARMS[0])]
                    candidate = later[(stage, phase, qid, arm)]
                    require(
                        base["family"] == candidate["family"],
                        "matched frozen source-family changed",
                    )
                    total += 1
                    changed += base["selected"] != candidate["selected"]
                    changed_answer += base["answer"] != candidate["answer"]
        arm_effects[arm] = dict(
            all_attempts_succeeded=total,
            changed_source_selection=changed,
            changed_original_answer_bytes=changed_answer,
            learned_benefit_independently_demonstrated=False,
        )
    return dict(
        schema="hepta.stem-historical-source-contrast.v1",
        originally_failed_source=ORIGINAL[0],
        legacy_success_source=EARLIER_SUCCESS[0],
        original_status=dict(before),
        legacy_status=dict(after),
        identical_old_success_answers_and_reader_inputs=exact_answer_preservations,
        cross_run_selection_change_count=len(cross_run_selection_changes),
        cross_run_selection_changes=[
            dict(stage=s, phase=p, question_id=q, arm=a)
            for s, p, q, a in cross_run_selection_changes
        ],
        all_80_questions_candidate_distribution=candidate_distribution(
            legacy_plan, legacy_encoding
        ),
        legacy_learned_arms=arm_effects,
        legacy_canonical_reader_admission_validated=False,
        current_source_or_asof_policy_verified=False,
        data_family_independence_authenticated=False,
        semantic_citation_precision=None,
        production_accepted=False,
    )


def audit_two_zip_paths(original_path, legacy_path):
    original = PinnedArchive(original_path, ORIGINAL[2])
    try:
        legacy = PinnedArchive(legacy_path, EARLIER_SUCCESS[2])
        try:
            for bundle, (source, tree, _) in (
                (original, ORIGINAL),
                (legacy, EARLIER_SUCCESS),
            ):
                require(
                    bundle.read("tested-commit.txt").decode().strip() == source,
                    "generating commit pin drift",
                )
                require(
                    bundle.read("tested-tree.txt").decode().strip() == tree,
                    "generating tree pin drift",
                )
            result = compare_receipts(
                original.json("comparison/preregistered.json"),
                original.jsonl("comparison/policy-predictions.jsonl"),
                legacy.json("comparison/preregistered.json"),
                legacy.jsonl("comparison/policy-predictions.jsonl"),
                legacy.jsonl("comparison/encoding.jsonl"),
            )
            # These source/Reader conditional tallies use only the archived
            # final-checkpoint frozen outputs and post-generation weak labels.
            # Neither version's literal oracle is independently certified.
            result["frozen_reader_conditional"] = dict(
                original=frozen_condition(
                    original.json("comparison/preregistered.json"),
                    original.json("comparison/scored-policy-attempts.json"),
                    original.jsonl("comparison/oracle-diagnostic.jsonl"),
                ),
                historically_complete=frozen_condition(
                    legacy.json("comparison/preregistered.json"),
                    legacy.json("comparison/scored-policy-attempts.json"),
                    legacy.jsonl("comparison/oracle-diagnostic.jsonl"),
                ),
                current_source_production_qualified=False,
            )
            result["transport"] = dict(
                original_zip_sha256=original.sha256,
                original_sha256_members=original.manifest_entries,
                legacy_zip_sha256=legacy.sha256,
                legacy_sha256_members=legacy.manifest_entries,
            )
            # The earlier successful runner called its generator directly,
            # without the later ExactReaderCache's before-call time admission.
            runner = legacy.read("source/stem_cell_trial.py").decode()
            require(
                "def generate(q, evidence, record_key):" in runner
                and "cache_key = digest(" in runner
                and "ExactReaderCache" not in runner
                and "source_not_after_question" not in runner,
                "legacy Reader-admission implementation unexpectedly changed",
            )
            return result
        finally:
            legacy.close()
    finally:
        original.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--legacy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit_two_zip_paths(args.original, args.legacy)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
