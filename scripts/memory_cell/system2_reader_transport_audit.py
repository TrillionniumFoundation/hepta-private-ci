"""Read-only, externally pinned audit of completed frozen Qwen evidence transport.

No model loading, inference, finetuning, or postprocessing of generated text.
Verify both actual hosted archives, exact task/source bindings, and all 240
paired JSON-vs-quoted-line observations before decomposing refusals and answers.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re

from native import digest as native_digest
from system2_multihop_trial import evidence
from system2_native_receipt import strict_json, verified_archive
from system2_reader_capacity_reference import (
    ARMS,
    MODEL_ID,
    MODEL_REV,
    outcome,
    selected,
)
from system2_reader_paired_capacity_audit import (
    STRONG_READER_ID,
    STRONG_ZIP_SHA,
    open_strong,
)
from system2_reader_transport_trial import (
    CASE_COUNT,
    FRESH_NAME,
    NEW_CALLS,
    REPEATED_COHORTS,
    REUSED_CALLS,
    SCHEMA as SOURCE_SCHEMA,
    VIEWS,
    registered_cohorts,
    score_pairs,
)

ZIP_SHA = "370181ca80deadf332ee2873ad1a2306038403338d64a726aff9f17bb05b5455"
SOURCE_COMMIT = "c73ea03d6dda2177d1c86f87249ca248e97424ff"
SOURCE_TREE = "e0427524868ac2c3cffe71715593fc358b866351"
AUDIT_SCHEMA = "hepta.system2.sealed-transport-audit.v1"
POSITIVES = ("single_fact", "target_decoy_two_first")


def write(path, value):
    with Path(path).open("x", encoding="utf8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def breakdown(rows):
    """Paired, descriptive counts. Never treat repeated arms as independent tasks."""
    groups = []
    for cohort in REPEATED_COHORTS:
        for arm in ARMS:
            items = [
                row for row in rows if row["cohort"] == cohort and row["arm"] == arm
            ]
            if len(items) != CASE_COUNT or len({r["qid"] for r in items}) != CASE_COUNT:
                raise ValueError("missing/duplicated paired source observations")
            json_only = lines_only = both = neither = 0
            for item in items:
                left = item["baseline_score"]["conditional_success"]
                right = item["new_score"]["conditional_success"]
                if type(left) is not bool or type(right) is not bool:
                    raise ValueError("unregistered conditional success flags")
                both += left and right
                json_only += left and not right
                lines_only += right and not left
                neither += not left and not right
            if both + json_only + lines_only + neither != CASE_COUNT:
                raise ValueError("paired result denominator drift")
            old_input = sum(r["baseline_input_tokens"] for r in items)
            new_input = sum(r["new_input_tokens"] for r in items)
            old_out = sum(r["baseline_output_tokens"] for r in items)
            new_out = sum(r["new_output_tokens"] for r in items)
            old_cpu = sum(r["baseline_cpu_ns"] for r in items)
            new_cpu = sum(r["new_cpu_ns"] for r in items)
            if any(
                type(x) is not int or x < 0
                for x in (old_input, new_input, old_out, new_out, old_cpu, new_cpu)
            ):
                raise ValueError("invalid model resource accounting")
            groups.append(
                dict(
                    cohort=cohort,
                    arm=arm,
                    tasks=CASE_COUNT,
                    both_success=int(both),
                    json_only_success=int(json_only),
                    lines_only_success=int(lines_only),
                    neither_success=int(neither),
                    json_exact_answers=sum(
                        r["baseline_score"]["exact_answer_only"] for r in items
                    ),
                    lines_exact_answers=sum(
                        r["new_score"]["exact_answer_only"] for r in items
                    ),
                    json_appropriate_refusals=sum(
                        r["baseline_score"]["correct_refusal"] for r in items
                    ),
                    lines_appropriate_refusals=sum(
                        r["new_score"]["correct_refusal"] for r in items
                    ),
                    json_overrefusals=sum(
                        r["baseline_score"]["correct_refusal"] for r in items
                    )
                    if arm in POSITIVES
                    else None,
                    lines_overrefusals=sum(
                        r["new_score"]["correct_refusal"] for r in items
                    )
                    if arm in POSITIVES
                    else None,
                    input_token_delta=new_input - old_input,
                    generated_token_delta=new_out - old_out,
                    decoder_cpu_delta_ns=new_cpu - old_cpu,
                    json_decoder_cpu_ns=old_cpu,
                    lines_decoder_cpu_ns=new_cpu,
                    compute_matched=False,
                    natural_tasks_independent=False,
                )
            )
    return groups


def authenticated_replay(transport, parent):
    files = verified_archive(Path(transport), ZIP_SHA)
    if (
        files["tested-commit.txt"].decode().strip() != SOURCE_COMMIT
        or files["tested-tree.txt"].decode().strip() != SOURCE_TREE
    ):
        raise ValueError("generating code/tree drift")
    prior_files, _, previous = open_strong(parent)
    if len(previous) != REUSED_CALLS:
        raise ValueError("incomplete archived Qwen JSON comparator")
    plan = strict_json(files["trial/plan.json"])
    summary = strict_json(files["trial/summary.json"])
    if (
        plan.get("schema") != SOURCE_SCHEMA
        or plan.get("source_commit") != SOURCE_COMMIT
        or plan.get("prior_0_5b_source_sha256") != STRONG_ZIP_SHA
        or plan.get("reused_json_calls") != REUSED_CALLS
        or plan.get("actual_new_calls") != NEW_CALLS
        or plan.get("frozen_revision") != MODEL_REV
        or plan.get("reference_reader_identity") != STRONG_READER_ID
        or plan.get("views") != list(VIEWS)
        or plan.get("arms") != list(ARMS)
        or plan.get("source_ids_never_replaced_or_truncated") is not True
        or plan.get("production_accepted") is not False
        or summary.get("source_commit") != SOURCE_COMMIT
        or summary.get("planned_new") != NEW_CALLS
        or summary.get("recorded_new") != NEW_CALLS
        or summary.get("failed_new") != 0
        or summary.get("prior_json_reused") != REUSED_CALLS
        or summary.get("production_accepted") is not False
    ):
        raise ValueError("transport experiment registration/source drift")
    raw = files["trial/raw-answers.jsonl"]
    seal = strict_json(files["trial/raw-seal.json"])
    if (
        seal
        != dict(
            sha256=hashlib.sha256(raw).hexdigest(),
            rows=NEW_CALLS,
            scoring_started=False,
        )
        or summary.get("prediction_sha256") != seal["sha256"]
    ):
        raise ValueError("unsealed/modified transport predictions")
    groups = registered_cohorts()
    if set(plan["cohorts"]) != set(groups) or any(
        plan["cohorts"][key] != [c.question.identity for c in value]
        for key, value in groups.items()
    ):
        raise ValueError("changed cohort identity")
    expected = set()
    for name, cases in groups.items():
        for case in cases:
            for arm in ARMS:
                expected.add((case.question.identity, arm, "lines"))
                if name == FRESH_NAME:
                    expected.add((case.question.identity, arm, "json"))
    if len(expected) != NEW_CALLS:
        raise ValueError("planned Reader positions altered")
    started = [strict_json(line) for line in files["trial/starts.jsonl"].splitlines()]
    starts = [(r["qid"], r["arm"], r["view"]) for r in started]
    if (
        len(starts) != NEW_CALLS
        or set(starts) != expected
        or len(set(starts)) != NEW_CALLS
        or any(r.get("status") != "started" for r in started)
    ):
        raise ValueError("incomplete/duplicated start journal")
    new = {}
    for raw_line in raw.splitlines():
        row = strict_json(raw_line)
        key = (row["qid"], row["arm"], row["view"])
        if (
            key in new
            or key not in expected
            or row.get("status") != "succeeded"
            or type(row.get("answer")) is not str
            or not row["answer"].strip()
        ):
            raise ValueError("incomplete/duplicated/failed transport row")
        new[key] = row
    if set(new) != expected:
        raise ValueError("missing planned Reader result")
    for name, cases in groups.items():
        for case in cases:
            for arm in ARMS:
                docs = selected(case, arm)
                bundle, _, _ = evidence(case, docs, arm)
                delivered = bundle.delivered()
                if name != FRESH_NAME:
                    earlier = previous[case.question.identity, arm]
                    if (
                        earlier.get("status") != "succeeded"
                        or earlier.get("cohort") != name
                        or earlier["selected"] != [d.identity for d in docs]
                        or earlier["reader"]["delivered_evidence"] != delivered
                        or earlier["reader"]["bundle_digest"] != bundle.seal()
                    ):
                        raise ValueError("reused JSON source bytes/identity changed")
                for view in VIEWS:
                    key = case.question.identity, arm, view
                    if key not in new:
                        if view == "json" and name != FRESH_NAME:
                            continue
                        raise ValueError("unregistered missing position")
                    row = new[key]
                    receipt = row["reader"]
                    expected_profile = (
                        previous[next(iter(previous))]["reader"]["reader_profile"]
                        if view == "json"
                        else None
                    )
                    if (
                        row["cohort"] != name
                        or row["selected"] != [d.identity for d in docs]
                        or receipt["reader_identity"] != STRONG_READER_ID
                        or receipt["model_id"] != MODEL_ID
                        or receipt["model_revision"] != MODEL_REV
                        or receipt["bundle_digest"] != bundle.seal()
                        or receipt["delivered_evidence"] != delivered
                        or receipt["question_digest"]
                        != native_digest(asdict(case.question))
                        or receipt["token_limit"] != 1024
                        or receipt["trainable_parameters"] != 0
                        or receipt["answer_postprocessed"] is not False
                        or receipt["production_accepted"] is not False
                        or type(receipt["input_tokens"]) is not int
                        or not 1 <= receipt["input_tokens"] <= 1024
                        or type(receipt["generated_tokens"]) is not int
                        or not 1 <= receipt["generated_tokens"] <= 64
                        or type(receipt["cpu_time_ns"]) is not int
                        or receipt["cpu_time_ns"] < 0
                        or not re.fullmatch(
                            r"[0-9a-f]{64}", receipt["input_ids_digest"]
                        )
                        or not re.fullmatch(
                            r"[0-9a-f]{64}", receipt["generated_ids_digest"]
                        )
                        or (
                            view == "json"
                            and receipt["reader_profile"] != expected_profile
                        )
                    ):
                        raise ValueError("Reader prompt/source/cost drift")
    rows = list(new.values())
    stats = score_pairs(rows, previous, groups)
    if summary.get("results") != stats:
        raise ValueError("archived paired summary was changed")
    saved_pairs = strict_json(files["trial/paired-scores.json"])
    pairs = []
    for name, cases in groups.items():
        for case in cases:
            for arm in ARMS:
                qid = case.question.identity
                before = (
                    new[qid, arm, "json"] if name == FRESH_NAME else previous[qid, arm]
                )
                after = new[qid, arm, "lines"]
                pairs.append(
                    dict(
                        qid=qid,
                        cohort=name,
                        arm=arm,
                        baseline_view="json",
                        new_view="lines",
                        baseline_score=outcome(case, arm, before["answer"]),
                        new_score=outcome(case, arm, after["answer"]),
                        baseline_input_tokens=before["reader"]["input_tokens"],
                        new_input_tokens=after["reader"]["input_tokens"],
                        baseline_output_tokens=before["reader"]["generated_tokens"],
                        new_output_tokens=after["reader"]["generated_tokens"],
                        baseline_cpu_ns=before["reader"]["cpu_time_ns"],
                        new_cpu_ns=after["reader"]["cpu_time_ns"],
                        sourced_original_answer=name != FRESH_NAME,
                    )
                )
    if saved_pairs != pairs or len(pairs) != REUSED_CALLS + CASE_COUNT * len(ARMS):
        raise ValueError("paired model proof/score/cost drift")
    fresh = [r for r in stats if r["cohort"] == FRESH_NAME]
    allowed = all(
        r["lines_conditional_success"] >= (15 if r["arm"] in POSITIVES else 18)
        for r in fresh
    ) and all(r["discordant_json_only"] == 0 for r in fresh)
    disposition = (
        "independent_confirmation_required"
        if allowed
        else "reader_transport_not_qualified"
    )
    if summary.get("candidate_disposition") != disposition:
        raise ValueError("retroactively modified promotion decision")
    report = dict(
        schema=AUDIT_SCHEMA,
        generating_commit=SOURCE_COMMIT,
        tested_tree=SOURCE_TREE,
        transport_archive_sha256=ZIP_SHA,
        original_archive_sha256=STRONG_ZIP_SHA,
        verified_new_archive_members=len(files) - 1,
        verified_old_archive_members=len(prior_files) - 1,
        new_model_calls=NEW_CALLS,
        old_model_calls_reused=REUSED_CALLS,
        complete_paired_conditions=len(pairs),
        raw_answer_sha256=seal["sha256"],
        breakdown=breakdown(pairs),
        candidate_disposition=disposition,
        model_calls_for_this_audit=0,
        compute_matched=False,
        independent_natural_semantic_review=False,
        production_accepted=False,
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transport", type=Path)
    parser.add_argument("original", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = authenticated_replay(args.transport, args.original)
    write(args.output, result)
    print(
        "SEALED_TRANSPORT_AUDIT="
        + json.dumps(
            dict(
                new_model_calls=result["new_model_calls"],
                old_reused=result["old_model_calls_reused"],
                disposition=result["candidate_disposition"],
                breakdown=result["breakdown"],
            ),
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
