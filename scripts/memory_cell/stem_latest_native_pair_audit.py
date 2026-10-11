"""Compare TWO latest, fully completed strict-as-of native Stem runs.

Only opens the two externally pinned archived original executions, validates
each ZIP's complete internal SHA-256 manifest, and compares frozen/learned
decisions, Reader inputs+answers and persisted weights. No model, dataset,
remote reviewer, training, or production admission is invoked.
"""

from collections import Counter
import argparse
import json
from pathlib import Path

from stem_audit_archive import PinnedArchive, require
from stem_strict_repeatability import _indexed, compare_adapters

EARLIER = (
    "af08c3a82648578eb57054bb273c06ada320c36f",
    "53cf28ac8a7e7422046a823160914b63c5519e74",
    "29ecf0a7e4a5c08075aea1b0e70540116eb04aa2b51c6c79509c773744037ace",
    146,
)
LATER = (
    "a89652ec7f1b39dd7f9e2b6e60c93d704fa28268",
    "2357d5590871824a95d18c69894763665358fec5",
    "4c57054d93b8ffc35b973299d3f583e783bb8c4bcef670c2fe8c01b243ceed4d",
    146,
)
ARMS = (
    "frozen_rerank",
    "prototype",
    "linear",
    "gated",
    "lineage_lora_gated",
    "independent_lora_gated",
)
STAGES = (16, 32, 48)
PHASES = ("select", "retention", "test", "transfer")
TIMED_ROW = {"head_seconds", "inclusive_attempt_seconds"}
TIMED_READER = {"generation_seconds", "incremental_generation_seconds"}


def equal_policy(a, b):
    """Identical source and Reader answer; clocks may legitimately vary."""
    require(
        a["status"] == b["status"] == "succeeded",
        "full current strict policy must have succeeded twice",
    )
    require(set(a) == set(b), "policy keys added, lost, or changed")
    require(
        all(a[k] == b[k] for k in a if k not in TIMED_ROW | {"receipt"}),
        "actual Head, question, source selection, or answer changed between runs",
    )
    ra, rb = a["receipt"], b["receipt"]
    require(
        set(ra) == set(rb) and all(ra[k] == rb[k] for k in ra if k not in TIMED_READER),
        "Reader model/prompt/source, generated tokens or cache lineage changed",
    )
    require(
        ra["generator_parameter_updates"] == 0
        and ra["semantic_citation_precision"] is None
        and ra["production_accepted"] is False,
        "Reader unfrozen or false semantic/production claim",
    )


def audit_archives(old, new):
    for archive, (commit, tree, _, members) in (
        (old, EARLIER),
        (new, LATER),
    ):
        require(
            archive.read("tested-commit.txt").decode().strip() == commit
            and archive.read("tested-tree.txt").decode().strip() == tree
            and archive.manifest_entries == members,
            "ZIP source, tree, or complete member count mismatch",
        )
    plan_a = old.json("comparison/preregistered.json")
    plan_b = new.json("comparison/preregistered.json")
    require(
        set(plan_a) == set(plan_b)
        and plan_a["source_commit"] == EARLIER[0]
        and plan_b["source_commit"] == LATER[0]
        and all(plan_a[k] == plan_b[k] for k in plan_a if k != "source_commit")
        and plan_a["source_visibility_policy"]
        == "strict-as-of-before-index-and-every-Encoder-v1"
        and tuple(plan_a["arms"]) == ARMS
        and tuple(plan_a["curriculum_attempted_examples"]) == STAGES
        and len(plan_a["questions"]["train"]) == 48
        and all(len(plan_a["questions"][p]) == 8 for p in PHASES),
        "cohort, model, cut, Reader, or source visibility drift",
    )
    before = _indexed(old.jsonl("comparison/policy-predictions.jsonl"), plan_a)
    after = _indexed(new.jsonl("comparison/policy-predictions.jsonl"), plan_b)
    for key in sorted(before):
        equal_policy(before[key], after[key])
    for member in (
        "comparison/within-head-train-fit.json",
        "comparison/post-policy-native-source-ceiling.json",
        "comparison/reader-no-evidence-report.json",
        "comparison/reader-paired-no-evidence.json",
        "comparison/adapter-pair-opportunities.json",
        "comparison/train-heldout-gap.json",
        "comparison/shadow-source-ceiling.json",
    ):
        require(
            old.read(member) == new.read(member),
            "training fit, candidate ceiling, or held-out support report drift: "
            + member,
        )
    heads = {
        p for p in old.files if p.startswith("comparison/head-") and p.endswith(".json")
    }
    require(
        len(heads) == 36
        and heads.issubset(new.files)
        and all(old.read(f) == new.read(f) for f in heads),
        "persisted Head tensor/checkpoint change between strict runs",
    )
    adapters = {
        "comparison/adapter-" + tag + "/adapter.safetensors"
        for tag in ("lineage", "independent-general", "independent-temporal")
    }
    require(
        adapters.issubset(old.files & new.files)
        and all(old.read(f) == new.read(f) for f in adapters),
        "differentiated Encoder adapter tensor changed",
    )
    unique = compare_adapters(
        old.json("comparison/adapter-training.json"),
        new.json("comparison/adapter-training.json"),
    )
    reports = [x.json("comparison/report.json") for x in (old, new)]
    for report in reports:
        require(
            report["census"]["complete"] is True
            and report["census"]["recorded"] == 576
            and report["logical_policy_attempts"] == 576
            and report["reader"]["actual_successes"] == 48
            and report["reader"]["actual_failed_attempts"] == 0
            and report["reader"]["cache_hits"] == 543
            and report["production_accepted"] is False
            and report["superiority_claim"] is False
            and report["semantic_citation_precision"] is None,
            "original Reader census or nonproduction qualification drift",
        )
    arms = {}
    scored_a = {
        (row["stage"], row["phase"], row["question_id"], row["arm"]): row
        for row in old.json("comparison/scored-policy-attempts.json")
    }
    require(
        len(scored_a) == 576 and set(scored_a) == set(before),
        "incomplete paired native weak-source scoring",
    )
    for arm in ARMS[1:]:
        choices = answers = gains = regressions = 0
        details = []
        for (stage, phase, qid, candidate), item in before.items():
            if candidate != arm:
                continue
            frozen = before[stage, phase, qid, ARMS[0]]
            if item["selected"] != frozen["selected"]:
                choices += 1
                details.append(
                    dict(
                        checkpoint=stage,
                        phase=phase,
                        question_id=qid,
                        native_supported_before=scored_a[
                            stage, phase, qid, ARMS[0]
                        ].get("source_choice_correct"),
                        native_supported_after=scored_a[stage, phase, qid, arm].get(
                            "source_choice_correct"
                        ),
                    )
                )
            answers += item["answer"] != frozen["answer"]
            first = scored_a[stage, phase, qid, ARMS[0]].get("source_choice_correct")
            second = scored_a[stage, phase, qid, arm].get("source_choice_correct")
            if type(first) is int and type(second) is int:
                gains += second > first
                regressions += second < first
        require(
            (choices, answers, gains, regressions)
            == ((1, 0, 0, 0) if arm == "lineage_lora_gated" else (0, 0, 0, 0)),
            "source-supported frozen-matched benefit or answer changed",
        )
        arms[arm] = dict(
            matched_original_executions=96,
            changed_source_top1=choices,
            changed_answer_bytes=answers,
            native_weak_document_support_gains=gains,
            native_weak_document_support_regressions=regressions,
            flip_details=details,
        )
    ceiling = reports[1]["retrospective_weak_source_ceiling"]["phases"]
    require(
        all(ceiling[p]["attempted"] == 8 for p in PHASES),
        "post-policy source ceiling lost its original 32-case denominator",
    )
    considered = sum(ceiling[p]["native_source_resolved"] for p in PHASES)
    missed = sum(ceiling[p]["support_missing_from_pool"] for p in PHASES)
    rank_missed = sum(ceiling[p]["frozen_missed_available_support"] for p in PHASES)
    require(
        (considered, missed, rank_missed) == (25, 8, 4),
        "native retrieval and rank-Head opportunity changed",
    )
    shadow = reports[1]["shadow_source_support_postpolicy"]["results"]
    shadow_results = {}
    for arm in ARMS[1:]:
        groups = [
            v
            for k, v in shadow.items()
            if k.startswith("48/")
            and (k.endswith("/test") or k.endswith("/transfer"))
            and ("/" + arm + "/") in k
        ]
        require(len(groups) == 4, "incomplete final shadow test/transfer cohort")
        shadow_results[arm] = dict(
            shadow_weak_support_gains=sum(
                x["shadow_weak_source_gains"] for x in groups
            ),
            shadow_weak_support_regressions=sum(
                x["shadow_weak_source_regressions"] for x in groups
            ),
            shadow_rank_changes=sum(x["changed_source_top1"] for x in groups),
            shadow_not_original_reader_policy=True,
        )
    require(
        all(
            x["shadow_weak_support_gains"] <= x["shadow_weak_support_regressions"]
            for x in shadow_results.values()
        ),
        "previously source-pinned shadow heldout advantage changed",
    )
    return dict(
        schema="hepta.stem-two-latest-strict-completed-repeatability.v1",
        pinned_commits=[EARLIER[0], LATER[0]],
        pinned_trees=[EARLIER[1], LATER[1]],
        transport_sha256=[old.sha256, new.sha256],
        internally_verified_sha256_members=[old.manifest_entries, new.manifest_entries],
        registered_policy_answers_exactly_reproduced=len(before),
        identical_byte_persisted_head_checkpoints=len(heads),
        identical_lora_adapter_tensor_sets=len(adapters),
        real_reader_invocations=48,
        matched_reader_cache_hits=543,
        unique_lora_warm_positive_negative_pairs=unique,
        candidate_pool_native_source_labeled_count=considered,
        native_support_missing_before_Head_count=missed,
        frozen_top1_missed_retrieved_support_count=rank_missed,
        actual_frozen_matched_learned_arms=arms,
        train_selected_shadow_test_transfer=shadow_results,
        independently_reviewed_source_entailment=False,
        two_runs_are_same_dataset_not_independent_subjects=True,
        actual_pretrained_test_gain_demonstrated=False,
        production_accepted=False,
        semantic_citation_precision=None,
    )


def audit_two_paths(earlier, later):
    old = PinnedArchive(Path(earlier), EARLIER[2])
    try:
        new = PinnedArchive(Path(later), LATER[2])
        try:
            return audit_archives(old, new)
        finally:
            new.close()
    finally:
        old.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--earlier", type=Path, required=True)
    ap.add_argument("--later", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    report = audit_two_paths(args.earlier, args.later)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write("\n")
    print(json.dumps(report, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
