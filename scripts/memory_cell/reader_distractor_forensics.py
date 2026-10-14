"""Source-bound diagnosis of EXISTING Qwen strong-RAG failures, no model calls.

Compare unchanged original model answers to their score overlays, then identify
literal values copied from unrelated entities or correct literals rendered with
invalid grammar. An authored source-value match is NOT semantic adjudication.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from disjoint_chain_disposition import checked_zip, rows, strict_json
from event_memory_trial import strict_identifier

SCHEMA = "hepta.memorycell.original-qwen-literal-failure-forensics.v1"
SOURCE_SHA = "31c6f191ecf62095779f7c9a5dd6c5b2f89c6ae408fe9c26f74e017a2d62c47a"
MODEL_SHA = "b6ccc6606bf9935d052fb78884560487d2030772572199d8a8fa38e516fcc8be"
PLAN_SHA = "9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897"
GENERATING_SHA = "bc76ac57ba972bf105c71ddd997cd215cec5df2e"
QWEN = "f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225"
ARMS = (
    "selected_k",
    "hybrid_k4",
    "hybrid_k6",
    "hybrid_k4_reversed",
    "single_hop",
    "entity_time",
    "organized",
    "program_support",
    "empty",
)
SCORER_ONLY = frozenset(
    ("parsed_identifier", "strict_task_success", "required_sources_covered",
     "procedure_verification")
)
VALUE = re.compile(r"(?<![a-zA-Z0-9_])(?:site|mode)_[0-9a-f]{8}(?![a-zA-Z0-9_])")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def classify_loss(row, label):
    """Classify only literal-output behavior, not task semantics or necessity."""
    if (
        row["status"] != "succeeded"
        or row["strict_task_success"] is not False
        or row["kind"] == "procedure"
    ):
        raise ValueError("only real failed nonprogram answers can be classified")
    answer = row["answer"]
    parsed = strict_identifier(answer)
    if parsed != row["parsed_identifier"]:
        raise ValueError("original response grammar audit drift")
    expected = label["expected"]
    if parsed is None:
        embedded = VALUE.findall(answer)
        if embedded == [expected]:
            return dict(
                cause="correct_literal_invalid_output_grammar",
                emitted_literal=expected,
                matching_original_sources=[],
            )
        return dict(
            cause="invalid_grammar_without_unique_expected_literal",
            emitted_literal=None,
            matching_original_sources=[],
        )
    found = []
    for delivered in row["receipt"]["delivered_evidence"]:
        event = strict_json(delivered["excerpt"].encode("utf-8"))
        if event.get("value") == parsed:
            found.append(
                dict(
                    source_id=delivered["original_id"],
                    evidence_label=delivered["label"],
                    entity=event.get("entity"),
                    attribute=event.get("attribute"),
                )
            )
    off_target = [source for source in found if source["entity"] != label["entity"]]
    if parsed != expected and off_target:
        return dict(
            cause="wrong_literal_copied_from_other_entity",
            emitted_literal=parsed,
            matching_original_sources=off_target,
        )
    return dict(
        cause="other_observed_or_unresolved_failure",
        emitted_literal=parsed,
        matching_original_sources=found,
    )


def reversal_control(by_task):
    """Verify matched Qwen Top-4 source-order reversal without new inference."""
    if not isinstance(by_task, dict) or not by_task:
        raise ValueError("nonempty complete paired task map required")
    pairs = []
    for qid, group in sorted(by_task.items()):
        direct, reverse = group["hybrid_k4"], group["hybrid_k4_reversed"]
        if (
            direct["question_id"] != qid
            or reverse["question_id"] != qid
            or direct["kind"] != reverse["kind"]
            or direct["status"] != "succeeded"
            or reverse["status"] != "succeeded"
            or direct["candidate_digest"] != reverse["candidate_digest"]
            or len(direct["selected"]) != 4
            or direct["selected"] != list(reversed(reverse["selected"]))
            or type(direct["strict_task_success"]) is not bool
            or type(reverse["strict_task_success"]) is not bool
            or not isinstance(direct["answer"], str)
            or not isinstance(reverse["answer"], str)
        ):
            raise ValueError("not a matched original four-source order intervention")
        one, two = direct["receipt"], reverse["receipt"]
        if any(
            one[key] != two[key]
            for key in (
                "reader_identity",
                "reader_profile",
                "token_limit",
                "input_tokens",
                "trainable_parameters",
                "answer_postprocessed",
                "independent_semantic_review",
            )
        ) or one["answer_postprocessed"] is not False:
            raise ValueError("order-only intervention changed Reader or budget")
        pairs.append(
            dict(
                question_id=qid,
                kind=direct["kind"],
                direct_task_success=direct["strict_task_success"],
                reverse_task_success=reverse["strict_task_success"],
                direct_parsed_literal=direct["parsed_identifier"],
                reverse_parsed_literal=reverse["parsed_identifier"],
                input_tokens=one["input_tokens"],
                original_source_count=4,
            )
        )
    return dict(
        paired_tasks=len(pairs),
        same_success_status=sum(
            p["direct_task_success"] == p["reverse_task_success"]
            for p in pairs
        ),
        source_order_reversal_changes_task_success=sum(
            p["direct_task_success"] != p["reverse_task_success"]
            for p in pairs
        ),
        same_parsed_literal=sum(
            p["direct_parsed_literal"] == p["reverse_parsed_literal"]
            for p in pairs
        ),
        changed_parsed_literal=sum(
            p["direct_parsed_literal"] != p["reverse_parsed_literal"]
            for p in pairs
        ),
        source_ids_exactly_reversed=True,
        matched_input_token_counts=True,
        prospective_generalization=False,
        semantic_review=False,
        per_task=pairs,
    )


def audit(source_zip, model_zip):
    source = checked_zip(source_zip, SOURCE_SHA, count=35)
    model = checked_zip(model_zip, MODEL_SHA, count=272)
    if sha(source["plan/plan.json"]) != PLAN_SHA:
        raise ValueError("source plan changed from pre-existing reader trial")
    plan = strict_json(source["plan/plan.json"])
    report = strict_json(model["evaluation/report.json"])
    if (
        plan.get("schema") != "hepta.event-organization.plan.v1"
        or plan["token_limit"] != 2048
        or len(plan["cases"]) != 8
        or plan["independent_human_review"] is not False
        or report.get("source_commit") != GENERATING_SHA
        or report.get("total_attempts") != 72
        or report.get("production_accepted") is not False
    ):
        raise ValueError("original task/model/research authority drift")
    if (
        sha(source["plan/source-view.json"]) != plan["source_view_sha"]
        or sha(source["observations/labels.json"]) != plan["labels_sha"]
        or sha(model["evaluation/raw-answers.jsonl"]) != report["raw_answers_sha256"]
    ):
        raise ValueError("source/label/raw answer pin drift")
    cases = {c["query"]["identity"]: c for c in plan["cases"]}
    labels = {
        row["id"]: row
        for row in strict_json(source["observations/labels.json"])
    }
    documents = {
        row["identity"]: row
        for row in strict_json(source["plan/source-view.json"])
    }
    original = rows(model, "evaluation/raw-answers.jsonl", 72)
    scored = strict_json(model["evaluation/scored-answers.json"])
    if len(original) != 72 or len(scored) != 72 or len(cases) != 8:
        raise ValueError("incomplete exact Qwen answer census")
    observed, by_task = set(), {}
    for before, after in zip(original, scored, strict=True):
        if (
            {key: value for key, value in after.items() if key not in SCORER_ONLY}
            != before
        ):
            raise ValueError("original model answer changed in scored replay")
        qid, arm = after["question_id"], after["arm"]
        if (qid, arm) in observed or qid not in cases or arm not in ARMS:
            raise ValueError("duplicate or extraneous original answer")
        observed.add((qid, arm))
        task, label = cases[qid], labels[qid]
        receipt = after["receipt"]
        if (
            after["status"] != "succeeded"
            or after["kind"] != label["kind"]
            or after["kind"] != task["kind"]
            or after["candidate_digest"] != task["candidate_digest"]
            or receipt.get("reader_identity") != QWEN
            or receipt.get("trainable_parameters") != 0
            or receipt.get("answer_postprocessed") is not False
            or receipt.get("independent_semantic_review") is not False
            or receipt.get("semantic_citation_precision") is not None
            or type(after["strict_task_success"]) is not bool
            or type(receipt.get("input_tokens")) is not int
            or not 0 < receipt["input_tokens"] <= 2048
            or type(receipt.get("generated_tokens")) is not int
            or not 0 <= receipt["generated_tokens"] <= 64
            or [r["original_id"] for r in receipt["delivered_evidence"]]
            != after["selected"]
            or set(label["support"]).issubset(after["selected"])
            is not after["required_sources_covered"]
        ):
            raise ValueError("original source/reader/score contract drift")
        if any(
            evidence["original_id"] not in documents
            or evidence["excerpt"] != documents[evidence["original_id"]]["content"]
            for evidence in receipt["delivered_evidence"]
        ):
            raise ValueError("reader did not receive exact source text")
        parsed = strict_identifier(after["answer"])
        if parsed != after["parsed_identifier"]:
            raise ValueError("score grammar differs from actual original answer")
        if after["kind"] != "procedure":
            if (parsed == label["expected"]) is not after["strict_task_success"]:
                raise ValueError("nonprogram original scoring is inconsistent")
        else:
            executed = after.get("procedure_verification")
            if not isinstance(executed, dict) or (
                executed["exit_code"] == 0
            ) is not after["strict_task_success"]:
                raise ValueError("program score detached from original worker")
        if arm == "hybrid_k4" and after["selected"] != list(
            task["controls"]["hybrid"]["selected"]
        ):
            raise ValueError("hybrid is not precommitted original Top-4")
        if arm == "organized" and after["selected"] != list(
            task["controls"]["organized"]["selected"]
        ):
            raise ValueError("organized evidence changed after generation")
        by_task.setdefault(qid, {})[arm] = after
    if observed != {(qid, arm) for qid in cases for arm in ARMS}:
        raise ValueError("missing original paired Qwen arm")
    losses = []
    for qid, group in sorted(by_task.items()):
        left, right = group["hybrid_k4"], group["organized"]
        if (
            left["strict_task_success"] is False
            and right["strict_task_success"] is True
        ):
            classification = classify_loss(left, labels[qid])
            losses.append(
                dict(
                    question_id=qid,
                    kind=left["kind"],
                    original_answer_sha256=sha(left["answer"].encode("utf-8")),
                    input_tokens_hybrid=left["receipt"]["input_tokens"],
                    input_tokens_organized=right["receipt"]["input_tokens"],
                    declared_sources_all_delivered=left[
                        "required_sources_covered"
                    ],
                    **classification,
                )
            )
    causes = Counter(item["cause"] for item in losses)
    reversed_hybrid_order = reversal_control(by_task)
    return dict(
        schema=SCHEMA,
        original_generating_commit=GENERATING_SHA,
        original_source_zip_sha256=SOURCE_SHA,
        original_model_zip_sha256=MODEL_SHA,
        original_model_answer_count=len(original),
        analyzed_unique_authored_tasks=len(cases),
        hybrid_success=sum(
            group["hybrid_k4"]["strict_task_success"]
            for group in by_task.values()
        ),
        organized_success=sum(
            group["organized"]["strict_task_success"]
            for group in by_task.values()
        ),
        hybrid_losses_to_organized=len(losses),
        loss_mechanism_counts=dict(sorted(causes.items())),
        reversed_hybrid_order_control=reversed_hybrid_order,
        losses=losses,
        independent_semantic_adjudication=False,
        writer_or_parameter_training_executed=False,
        new_model_calls=0,
        independent_source_families=0,
        prospective_real_project_tasks=0,
        production_accepted=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original_source_zip", type=Path)
    parser.add_argument("completed_model_zip", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    value = audit(args.original_source_zip, args.completed_model_zip)
    with args.report.open("x", encoding="utf-8") as output:
        json.dump(value, output, indent=2, sort_keys=True, allow_nan=False)
        output.write("\n")
    print(
        json.dumps(
            {
                "losses": value["hybrid_losses_to_organized"],
                "causes": value["loss_mechanism_counts"],
                "new_model_calls": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
