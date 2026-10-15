"""Read-only paired order and answer-copy audit of an immutable frozen Reader run.

No new model invocation, training, optimization, selector choice or threshold tuning.
Each of the sixteen fictional relation-swap PAIRS, rather than each of 160
correlated Reader calls, is the unit of a paired-order contrast. This analysis
is descriptive; source-cited success and correct missing-evidence refusal
remain the actual qualification metrics, and those are not relaxed here.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from system2_multihop_counterfactual import ARMS, cases, select, source_manifest
from system2_multihop_counterfactual_trial import score
from system2_native_receipt import strict_json, verified_archive

PARENT_ARCHIVE_SHA256 = (
    "9ee9e63a725b3a5598ba6e89d728d6b17582d60853ee994151c1b58a15bf4a95"
)
PARENT_COMMIT = "f3609d11cbe715c0202cb09e1463fa4ad002bd3d"
PARENT_TREE = "4846438b33ccf78ef715011f9c181488848f850b"
PARENT_RAW_SHA256 = "cf3c06d54d86d6a9ea44e08a86083cd583fb319774468e6ad1acae7c57d4ec40"
FROZEN_READER_SHA256 = (
    "afb110c28d68c8956d372e428277fa8f164a2304f0ef9d9064a084f3fab7d94c"
)
CAP = 64
ORDER_ARMS = ("joined_top3", "reversed_join_top3")
ABSTENTION_ARMS = ("missing_start_top3", "terminal_only_top3")


def _hash32(value):
    return type(value) is str and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def read_original(archive):
    """Validate exact source identity, raw seal, entire census, and replay scoring."""
    files = verified_archive(Path(archive), PARENT_ARCHIVE_SHA256)
    if (
        files["tested-commit.txt"].decode().strip() != PARENT_COMMIT
        or files["tested-tree.txt"].decode().strip() != PARENT_TREE
    ):
        raise ValueError("unexpected generating source")
    data = files["native/raw-answers.jsonl"]
    seal = strict_json(files["native/raw-seal.json"])
    if hashlib.sha256(data).hexdigest() != PARENT_RAW_SHA256 or seal != dict(
        sha256=PARENT_RAW_SHA256, rows=160, scoring_started=False
    ):
        raise ValueError("historic frozen Reader output not sealed")
    plan = strict_json(files["native/plan.json"])
    pairs = cases()
    expected = {
        (case.question.identity, arm) for pair in pairs for case in pair for arm in ARMS
    }
    if (
        len(pairs) != 16
        or plan["source_commit"] != PARENT_COMMIT
        or plan["planned_reader_calls"] != 160
        or plan["pair_count"] != 16
        or plan["arms"] != list(ARMS)
        or plan["production_accepted"] is not False
    ):
        raise ValueError("unregistered historic cohort")
    raw = [strict_json(line) for line in data.splitlines()]
    recorded = {}
    profiles = set()
    for r in raw:
        key = (r["qid"], r["arm"])
        if (
            key not in expected
            or key in recorded
            or r["status"] != "succeeded"
            or not isinstance(r["answer"], str)
            or not r["answer"].strip()
        ):
            raise ValueError("missing, duplicated or failed historic output")
        receipt = r["reader"]
        if (
            receipt["reader_identity"] != FROZEN_READER_SHA256
            or receipt["trainable_parameters"] != 0
            or receipt["answer_postprocessed"] is not False
            or receipt["production_accepted"] is not False
            or receipt["token_limit"] != 1024
            or type(receipt["generated_tokens"]) is not int
            or not 1 <= receipt["generated_tokens"] <= CAP
            or type(receipt["input_tokens"]) is not int
            or not 1 <= receipt["input_tokens"] <= 1024
            or not _hash32(receipt["input_ids_digest"])
            or not _hash32(receipt["generated_ids_digest"])
        ):
            raise ValueError("unfrozen or invalid historical Reader receipt")
        profiles.add(receipt["reader_profile"])
        recorded[key] = r
    if set(recorded) != expected or len(profiles) != 1:
        raise ValueError("incomplete census or model-profile drift")
    saved_scores = strict_json(files["native/scored.json"])
    scores = {(s["qid"], s["arm"]): s for s in saved_scores}
    if len(scores) != 160 or set(scores) != expected:
        raise ValueError("missing or duplicate scored counterpart")
    for idx, pair in enumerate(pairs):
        for variant, case in enumerate(pair):
            for arm in ARMS:
                r = recorded[case.question.identity, arm]
                selected = select(arm, case.question, case.documents)
                if (
                    r["pair_index"] != idx
                    or r["variant"] != variant
                    or r["source_manifest"] != source_manifest(case)
                    or r["selected"] != [doc.identity for doc in selected]
                    or r["evidence_count"] != len(selected)
                    or [d["original_id"] for d in r["reader"]["delivered_evidence"]]
                    != r["selected"]
                    or r["reader"]["bundle_digest"] != r["bundle_digest"]
                ):
                    raise ValueError("delivered evidence changed after answer sealing")
                fresh = score(case, selected, r["answer"])
                if any(scores[r["qid"], arm].get(k) != v for k, v in fresh.items()):
                    raise ValueError("saved model scoring diverges from raw answer")
    return dict(
        rows=recorded,
        pairs=pairs,
        profile=next(iter(profiles)),
        archive_sha256=PARENT_ARCHIVE_SHA256,
        original_prediction_sha256=PARENT_RAW_SHA256,
        internal_verified_files=len(files) - 1,
    )


def summarize(data):
    """Preserve 16 causal pairs and split token mention from sourced success."""
    recorded, pairs = data["rows"], data["pairs"]
    if len(pairs) != 16:
        raise ValueError("frozen 16-pair registration required")
    per_arm = []
    for arm in ARMS:
        observations = [
            (case, recorded[case.question.identity, arm])
            for pair in pairs
            for case in pair
        ]
        outcomes = [
            score(case, select(arm, case.question, case.documents), r["answer"])
            for case, r in observations
        ]
        per_arm.append(
            dict(
                arm=arm,
                planned=32,
                exact_target_only=sum(s["raw_answer_exact"] for s in outcomes),
                strict_answer_and_complete_citation=sum(
                    s["strict_success"]
                    for s in outcomes
                    if s["programmatic_evidence_sufficient"]
                ),
                exact_abstentions=sum(s["raw_abstention_exact"] for s in outcomes),
                unsupported_exact_target_copy=sum(
                    s["copied_target_without_path"] for s in outcomes
                ),
                hit_generation_cap=sum(
                    r["reader"]["generated_tokens"] == CAP for _, r in observations
                ),
                total_input_tokens=sum(
                    r["reader"]["input_tokens"] for _, r in observations
                ),
                total_generated_tokens=sum(
                    r["reader"]["generated_tokens"] for _, r in observations
                ),
            )
        )
    cluster_rows = []
    for idx, pair in enumerate(pairs):
        for case in pair:
            forward = recorded[case.question.identity, ORDER_ARMS[0]]
            backward = recorded[case.question.identity, ORDER_ARMS[1]]
            if (
                backward["selected"] != list(reversed(forward["selected"]))
                or backward["reader"]["input_tokens"]
                != forward["reader"]["input_tokens"]
                or backward["reader"]["input_ids_digest"]
                == forward["reader"]["input_ids_digest"]
            ):
                raise ValueError("reversed arm changes more than evidence order")
        outcomes = {}
        for arm in ORDER_ARMS:
            outcomes[arm] = [
                score(
                    case,
                    select(arm, case.question, case.documents),
                    recorded[case.question.identity, arm]["answer"],
                )
                for case in pair
            ]
        cluster_rows.append(
            dict(
                pair_index=idx,
                hops=pair[0].hops,
                expected_answers_flipped=pair[0].answer != pair[1].answer,
                same_raw_answer_across_counterfactual={
                    arm: recorded[pair[0].question.identity, arm]["answer"]
                    == recorded[pair[1].question.identity, arm]["answer"]
                    for arm in ORDER_ARMS
                },
                exact_targets_by_order={
                    arm: sum(x["raw_answer_exact"] for x in outcomes[arm])
                    for arm in ORDER_ARMS
                },
                both_counterfactual_answers_exact={
                    arm: all(x["raw_answer_exact"] for x in outcomes[arm])
                    for arm in ORDER_ARMS
                },
                both_grounded_and_cited={
                    arm: all(x["strict_success"] for x in outcomes[arm])
                    for arm in ORDER_ARMS
                },
            )
        )
    changes = Counter(
        row["exact_targets_by_order"]["reversed_join_top3"]
        - row["exact_targets_by_order"]["joined_top3"]
        for row in cluster_rows
    )
    return dict(
        schema="hepta.system2.counterfactual-order-retrospective.v1",
        parent_generating_commit=PARENT_COMMIT,
        archive_sha256=data["archive_sha256"],
        original_prediction_sha256=data["original_prediction_sha256"],
        original_reader_profile=data["profile"],
        verified_historical_members=data["internal_verified_files"],
        distinct_causal_pairs=16,
        question_variants=32,
        original_model_calls=160,
        new_model_calls=0,
        source_answers_rewritten=False,
        group_by_arm=per_arm,
        paired_order=dict(
            pair_difference_counts={str(i): changes.get(i, 0) for i in range(-2, 3)},
            reversed_better_pairs=sum(
                row["exact_targets_by_order"]["reversed_join_top3"]
                > row["exact_targets_by_order"]["joined_top3"]
                for row in cluster_rows
            ),
            joined_better_pairs=sum(
                row["exact_targets_by_order"]["reversed_join_top3"]
                < row["exact_targets_by_order"]["joined_top3"]
                for row in cluster_rows
            ),
            equal_pairs=sum(
                row["exact_targets_by_order"]["reversed_join_top3"]
                == row["exact_targets_by_order"]["joined_top3"]
                for row in cluster_rows
            ),
            both_correct_pairs_by_order={
                arm: sum(
                    row["both_counterfactual_answers_exact"][arm]
                    for row in cluster_rows
                )
                for arm in ORDER_ARMS
            },
            both_grounded_pairs_by_order={
                arm: sum(row["both_grounded_and_cited"][arm] for row in cluster_rows)
                for arm in ORDER_ARMS
            },
            identical_answer_despite_target_flip={
                arm: sum(
                    row["same_raw_answer_across_counterfactual"][arm]
                    for row in cluster_rows
                )
                for arm in ORDER_ARMS
            },
            pairs=cluster_rows,
        ),
        correlated_synthetic_pairs=True,
        independent_natural_task_evidence=False,
        order_effect_is_not_evidence_grounded_reasoning=True,
        production_accepted=False,
        general_ndu_fbsde_gain=False,
    )


def run(archive, output):
    report = summarize(read_original(archive))
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError("append-only audit: output already exists")
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    report = run(args.archive, args.output)
    print(
        json.dumps(
            dict(
                source=report["parent_generating_commit"],
                reader_answers=report["original_model_calls"],
                new_calls=report["new_model_calls"],
                pair_difference_counts=report["paired_order"]["pair_difference_counts"],
            )
        )
    )
