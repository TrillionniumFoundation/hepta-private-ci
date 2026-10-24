"""Matched-question frozen 135M Reader reference on the 0.5B study's new cohort.

Research only: 80 previously UNRUN 135M calls on predeclared questions 20:40;
old 20-question 135M responses are reused, not bought again. Both Readers use
identical system/user message TEXT and exact original evidence, but different
tokenizers, models and computation. This adds no Cell/NDU/FBSDE learning.
"""

from __future__ import annotations

from dataclasses import asdict
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time

from native import digest as native_digest
from system2_multihop_trial import evidence
from system2_onehop_label_ablation import (
    AnswerOnlyReader,
    READER_IDENTITY,
    SYSTEM,
    TOKEN_LIMIT,
    prompt_messages,
)
from system2_reader_capacity_reference import (
    ARMS,
    CASE_COUNT,
    COHORTS,
    cohorts,
    load_baseline_archives,
    outcome,
    selected,
)

SCHEMA = "hepta.system2.same-question-frozen-135m-reader.v1"
NEW_CALLS = CASE_COUNT * len(ARMS)
MODEL_NAME = "historical-frozen-135m"
REV_HASH = re.compile(r"[0-9a-f]{40}\Z")


def write(path, item):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(
            item, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
        )
        stream.write("\n")


def append(path, item):
    with Path(path).open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(item, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
        )
        stream.flush()
        os.fsync(stream.fileno())


def presentation_for(arm):
    if arm not in ARMS:
        raise ValueError("unregistered Reader arm")
    return "unlabeled" if arm == "no_evidence" else "labeled"


def original_prompt_parity(groups, original, wrappers, shared):
    """Re-tokenize 80 old prompts, but make ZERO redundant old Reader calls.

    This is the essential admission gate: before evaluating new tasks, ensure
    the current 135M message template, tokenizer and frozen checkpoint reproduce
    the original completed 20-question E-coded inputs exactly.
    """
    cohort = groups.get("exposed_20")
    if len(cohort) != CASE_COUNT or shared.identity != READER_IDENTITY:
        raise ValueError("historical frozen Reader/cohort identity drift")
    old = original["by_key"]
    receipts = []
    for case in cohort:
        for arm in ARMS:
            presentation = presentation_for(arm)
            key = (case.question.identity, arm, presentation)
            if key not in old:
                raise ValueError("missing previously completed 135M prompt")
            previous = old[key]
            if previous["status"] != "succeeded":
                raise ValueError("historical 135M attempt unavailable")
            docs = selected(case, arm)
            bundle, originals, frontier = evidence(case, docs, "answer-only:" + arm)
            ids, receipt = wrappers[presentation].compile_input(
                case.question,
                bundle,
                originals,
                frontier=frontier,
                revoked=set(),
                token_limit=TOKEN_LIMIT,
            )
            earlier = previous["reader"]
            if (
                previous["selected"] != [doc.identity for doc in docs]
                or earlier["bundle_digest"] != bundle.seal()
                or (
                    ("bundle_digest" in previous)
                    and previous["bundle_digest"] != earlier["bundle_digest"]
                )
                or receipt["input_ids_digest"] != earlier["input_ids_digest"]
                or receipt["input_tokens"] != earlier["input_tokens"]
                or earlier["reader_identity"] != shared.identity
                or earlier["reader_profile"] != wrappers[presentation].profile
                or receipt["bundle_digest"] != earlier["bundle_digest"]
                or receipt["query_digest"] != earlier["query_digest"]
                or receipt["delivered_evidence"] != earlier["delivered_evidence"]
                or receipt["token_limit"] != TOKEN_LIMIT
                or len(ids) != receipt["input_tokens"]
            ):
                raise ValueError("old exact encoded Reader prompt or source changed")
            receipts.append(
                dict(
                    qid=case.question.identity,
                    arm=arm,
                    presentation=presentation,
                    input_ids_digest=receipt["input_ids_digest"],
                    input_tokens=receipt["input_tokens"],
                    response_ids_digest=earlier["generated_ids_digest"],
                    model_calls_reused=1,
                    new_model_calls=0,
                )
            )
    if len(receipts) != NEW_CALLS:
        raise ValueError("incomplete original prompt parity census")
    return receipts


def plan(groups, source_commit, model, original_sha, parity):
    if not isinstance(source_commit, str) or not REV_HASH.fullmatch(source_commit):
        raise ValueError("exact generating Git SHA required")
    old, new = (tuple(groups[name]) for name in COHORTS)
    if (
        len(old) != CASE_COUNT
        or len(new) != CASE_COUNT
        or len(set(c.question.identity for c in old + new)) != 2 * CASE_COUNT
        or len(parity) != NEW_CALLS
    ):
        raise ValueError("cohort or frozen baseline parity drift")
    return dict(
        schema=SCHEMA,
        source_commit=source_commit,
        old_135m_source_raw_sha256=original_sha,
        already_completed_exposed_questions=[c.question.identity for c in old],
        new_question_ids=[c.question.identity for c in new],
        arms=list(ARMS),
        actual_new_135m_model_calls=NEW_CALLS,
        original_135m_model_calls_reused=NEW_CALLS,
        stronger_0_5b_model_calls_in_this_run=0,
        original_reader_identity=model.identity,
        original_reader_inventory=model.inventory,
        original_system_instruction=SYSTEM,
        presentation_for_each_arm={a: presentation_for(a) for a in ARMS},
        input_ceiling=TOKEN_LIMIT,
        greedy_decode_max_new_tokens=64,
        exact_source_and_message_text_shared_with_0_5b=True,
        different_model_tokenizer_and_compute_not_matched=True,
        no_training_no_online_gold_labels=True,
        same_synthetic_world_not_independent_natural_language=True,
        no_production_change=True,
        production_accepted=False,
        confirmed_stronger_0_5b_accuracy=False,
    )


def score(rows, groups):
    """Complete frozen 135M 40-question census, with old calls clearly marked."""
    expected = {
        (c.question.identity, arm)
        for cohort in groups.values()
        for c in cohort
        for arm in ARMS
    }
    if len(expected) != 2 * NEW_CALLS:
        raise ValueError("fixed 135M source census drift")
    seen = {}
    for row in rows:
        key = (row["qid"], row["arm"])
        if key in seen or key not in expected:
            raise ValueError("duplicate/extra frozen Reader prediction")
        seen[key] = row
    if set(seen) != expected:
        raise ValueError("missing Reader prediction; never impute failure")
    summaries = []
    for cohort_name, cases in groups.items():
        for arm in ARMS:
            sample = [seen[c.question.identity, arm] for c in cases]
            completed = [row for row in sample if row["status"] == "succeeded"]
            results = []
            for case in cases:
                row = seen[case.question.identity, arm]
                if row["cohort"] != cohort_name or row["status"] not in (
                    "succeeded",
                    "failed",
                ):
                    raise ValueError("incorrect cohort/status")
                if row["status"] == "succeeded":
                    if not isinstance(row["answer"], str) or not row["answer"].strip():
                        raise ValueError("empty successful Reader answer")
                    if row["selected"] != [d.identity for d in selected(case, arm)]:
                        raise ValueError("selected sources changed")
                    results.append(outcome(case, arm, row["answer"]))
            summaries.append(
                dict(
                    cohort=cohort_name,
                    arm=arm,
                    planned=CASE_COUNT,
                    completed=len(completed),
                    failed=CASE_COUNT - len(completed),
                    exact_answer_only=sum(r["exact_answer_only"] for r in results),
                    correct_refusals=sum(r["correct_refusal"] for r in results),
                    conditional_success=sum(r["conditional_success"] for r in results),
                    unsupported_token_copies=sum(
                        r["unsupported_token_copy"] for r in results
                    ),
                    label_only_echoes=sum(r["label_only_echo"] for r in results),
                    historical_calls_reused=CASE_COUNT
                    if cohort_name == "exposed_20"
                    else 0,
                    new_calls=CASE_COUNT if cohort_name == "fixed_new_20" else 0,
                    unknown_failures_not_zero_scored=True,
                )
            )
    return summaries


def run(
    output,
    shared,
    *,
    cardinality_archive,
    label_archive,
    source_commit,
    groups=None,
    wrappers=None,
    original=None,
):
    """Fail closed on source/model drift; write every new attempt durably."""
    if not isinstance(source_commit, str) or not REV_HASH.fullmatch(source_commit):
        raise ValueError("exact source commit required")
    groups = cohorts() if groups is None else groups
    original = (
        load_baseline_archives(cardinality_archive, label_archive)
        if original is None
        else original
    )
    if shared.identity != READER_IDENTITY:
        raise ValueError("different frozen 135M model identity")
    shared.verify_frozen()
    wrappers = (
        {p: AnswerOnlyReader(shared, p) for p in ("labeled", "unlabeled")}
        if wrappers is None
        else wrappers
    )
    for p in ("labeled", "unlabeled"):
        if p not in wrappers:
            raise ValueError("original labeled and unlabeled prompts required")
    parity = original_prompt_parity(groups, original, wrappers, shared)
    receipt = plan(groups, source_commit, shared, original["raw_sha256"], parity)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    write(output / "plan.json", receipt)
    write(output / "original-prompt-parity.json", parity)
    new_cases = groups["fixed_new_20"]
    ordered = [(case, arm) for case in new_cases for arm in ARMS]
    ordered.sort(
        key=lambda item: (
            item[0].question.identity,
            (
                ARMS.index(item[1])
                + int(native_digest(item[0].question.identity)[:8], 16)
            )
            % len(ARMS),
        )
    )
    observed = []
    try:
        for case, arm in ordered:
            position = dict(
                qid=case.question.identity,
                cohort="fixed_new_20",
                arm=arm,
                presentation=presentation_for(arm),
                status="started",
            )
            append(output / "starts.jsonl", position)
            start_cpu = time.process_time_ns()
            start_wall = time.perf_counter_ns()
            try:
                docs = selected(case, arm)
                bundle, originals, frontier = evidence(case, docs, "answer-only:" + arm)
                message = prompt_messages(
                    case.question, bundle.delivered(), position["presentation"]
                )
                answer, model_receipt = wrappers[position["presentation"]].answer(
                    case.question,
                    bundle,
                    originals,
                    frontier=frontier,
                    revoked=set(),
                    token_limit=TOKEN_LIMIT,
                )
                if (
                    not isinstance(answer, str)
                    or not answer.strip()
                    or model_receipt.get("reader_identity") != shared.identity
                    or model_receipt.get("reader_profile")
                    != wrappers[position["presentation"]].profile
                    or model_receipt.get("bundle_digest") != bundle.seal()
                    or model_receipt.get("query_digest")
                    != native_digest(asdict(case.question))
                    or model_receipt.get("delivered_evidence") != bundle.delivered()
                    or model_receipt.get("answer_postprocessed") is not False
                    or model_receipt.get("trainable_parameters") != 0
                    or model_receipt.get("token_limit") != TOKEN_LIMIT
                    or not 1 <= model_receipt.get("generated_tokens", 0) <= 64
                ):
                    raise ValueError("frozen baseline output/source receipt changed")
                position.update(
                    status="succeeded",
                    selected=[d.identity for d in docs],
                    source_bundle_digest=bundle.seal(),
                    message_digest=native_digest(message),
                    answer=answer,
                    reader=model_receipt,
                )
            except BaseException as exc:
                position.update(
                    status="failed",
                    error_type=type(exc).__name__,
                    error=str(exc)[:512],
                    unknown_inflight_work=True,
                )
                raise
            finally:
                position["process_cpu_ns"] = time.process_time_ns() - start_cpu
                position["whole_request_wall_ns"] = time.perf_counter_ns() - start_wall
                append(output / "raw-answers.jsonl", position)
            observed.append(position)
        if len(observed) != NEW_CALLS:
            raise ValueError("incomplete 80-call new-cohort census")
        raw = (output / "raw-answers.jsonl").read_bytes()
        seal = hashlib.sha256(raw).hexdigest()
        write(
            output / "raw-seal.json",
            dict(sha256=seal, rows=len(observed), posthoc_scoring_started=False),
        )
        all_rows = []
        baseline = original["by_key"]
        for case in groups["exposed_20"]:
            for arm in ARMS:
                presentation = presentation_for(arm)
                old = baseline[case.question.identity, arm, presentation]
                all_rows.append(
                    dict(
                        qid=case.question.identity,
                        arm=arm,
                        cohort="exposed_20",
                        status="succeeded",
                        answer=old["answer"],
                        selected=old["selected"],
                        historical=True,
                    )
                )
        all_rows += observed
        summaries = score(all_rows, groups)
        if (
            hashlib.sha256((output / "raw-answers.jsonl").read_bytes()).hexdigest()
            != seal
        ):
            raise ValueError("raw new-cohort Reader answers mutated after scoring")
        shared.verify_frozen()
        report = dict(
            schema=SCHEMA,
            source_commit=source_commit,
            planned_new=NEW_CALLS,
            recorded_new=len(observed),
            failed_new=0,
            historical_old_responses_reused=NEW_CALLS,
            existing_parent_raw_sha256=original["raw_sha256"],
            new_raw_sha256=seal,
            by_arm=summaries,
            new_cpu_ns=sum(row["process_cpu_ns"] for row in observed),
            full_request_cpu_not_same_scope_as_0_5b_generation_cpu=True,
            larger_reader_needs_separate_pinned_archive=True,
            equal_message_content_not_equal_tokenizer_or_compute=True,
            learned_cell_gain=False,
            independent_natural_tasks=False,
            production_accepted=False,
        )
        write(output / "summary.json", report)
        return report
    except BaseException as exc:
        write(
            output / "run-failure.json",
            dict(
                planned_new=NEW_CALLS,
                completed_new=len(observed),
                error_type=type(exc).__name__,
                error=str(exc)[:512],
                inflight_and_missing_work_not_free=True,
            ),
        )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cardinality_archive", type=Path)
    parser.add_argument("label_archive", type=Path)
    parser.add_argument("reader_dir", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--development", action="store_true")
    args = parser.parse_args()
    if not args.development:
        raise ValueError("original Reader new-cohort comparison is research only")
    from bundle_reader import FrozenBundleReader
    from stem_cell_trial import READER

    frozen = FrozenBundleReader(args.reader_dir, expected_inventory=READER)
    result = run(
        args.output,
        frozen,
        cardinality_archive=args.cardinality_archive,
        label_archive=args.label_archive,
        source_commit=os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", ""),
    )
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "planned_new",
                    "recorded_new",
                    "failed_new",
                    "historical_old_responses_reused",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
