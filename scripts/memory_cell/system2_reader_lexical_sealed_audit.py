"""No-inference external-SHA audit of the frozen Qwen 2x2 lexical experiment.

One exact Reader, twenty correlated synthetic questions, four source arms and
four preregistered lexical treatments. Do not credit an appropriate refusal
on insufficient evidence as positive answer yield. No postprocessing/learning.
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
from system2_reader_lexical_factorial import (
    ARMS,
    CALLS,
    MODEL_ID,
    MODEL_REV,
    POSITIVE,
    PROFILES,
    SCHEMA,
    base_cases,
    delivery,
    score,
)
from system2_reader_paired_capacity_audit import (
    STRONG_READER_ID,
    open_strong,
)

SOURCE_COMMIT = "4fe8ac3d75132a21abf2c3e9d172c637e1bb6f91"
SOURCE_TREE = "a128abb8082e86734aa0d573176a74d20fc0dcce"
ARCHIVE_SHA = "0fd2a2aa60c0c28bdd61a2566262558410bb66c6997355aa610fe98b89aabc19"
REFERENCE_SHA = "853afed48368b2c4e562191c7ed6d6bf28492bd80ec95634119b8afc7d43ab37"
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
METRICS = (
    "exact_answer",
    "exact_refusal",
    "over_refusal",
    "unsupported_token_copy",
    "task_success",
)


def read_jsonlines(raw):
    return [strict_json(line) for line in raw.splitlines()]


def verify_census(items, cases, *, field):
    expected = {
        (case.question.identity, arm, profile)
        for case in cases
        for arm in ARMS
        for profile in PROFILES
    }
    seen = {}
    for item in items:
        key = item["qid"], item["arm"], item["profile"]
        if key not in expected or key in seen:
            raise ValueError("duplicate/unknown " + field + " position")
        seen[key] = item
    if len(seen) != CALLS or set(seen) != expected:
        raise ValueError("incomplete " + field + " census")
    return seen


def authenticate(archive, original_archive, *, expected_digest=ARCHIVE_SHA):
    """Validate sealed output, source evidence, profile and all saved scores."""
    if not HEX64.fullmatch(expected_digest):
        raise ValueError("external completed-archive pin required")
    original_files, original_plan, original = open_strong(original_archive)
    if (
        len(original) != 160
        or original_plan["reference_reader_identity"] != STRONG_READER_ID
    ):
        raise ValueError("invalid old frozen model anchor")
    files = verified_archive(Path(archive), expected_digest)
    if (
        files["tested-commit.txt"].decode().strip() != SOURCE_COMMIT
        or files["tested-tree.txt"].decode().strip() != SOURCE_TREE
    ):
        raise ValueError("factorial generating Git commit/tree drift")
    raw = files["trial/raw-answers.jsonl"]
    sealed = strict_json(files["trial/raw-seal.json"])
    plan = strict_json(files["trial/plan.json"])
    stored = strict_json(files["trial/summary.json"])
    cases = base_cases()
    expected_source = [c.question.identity for c in cases]
    if (
        len(cases) != 20
        or len(set(expected_source)) != 20
        or plan.get("schema") != SCHEMA
        or plan.get("source_commit") != SOURCE_COMMIT
        or plan.get("reader_identity") != STRONG_READER_ID
        or plan.get("questions") != expected_source
        or plan.get("profiles") != list(PROFILES)
        or plan.get("arms") != list(ARMS)
        or plan.get("expected_model_calls") != CALLS
        or plan.get("production_accepted") is not False
        or plan.get("original_archive_sha256") != REFERENCE_SHA
        or plan.get("new_task_range") != [60, 80]
        or plan.get("learned_updates") != 0
        or plan.get("online_gold_labels") is not False
        or plan.get("actual_compute_matched") is not False
        or plan.get("same_model_weight_and_tokenizer") is not True
        or sealed.get("rows") != CALLS
        or sealed.get("scoring_started") is not False
        or sealed.get("sha256") != hashlib.sha256(raw).hexdigest()
    ):
        raise ValueError("factorial registration or raw seal changed")

    starts = verify_census(
        read_jsonlines(files["trial/starts.jsonl"]), cases, field="start"
    )
    answers = verify_census(read_jsonlines(raw), cases, field="answer")
    scores = verify_census(
        strict_json(files["trial/scored.json"]), cases, field="score"
    )
    old_inventory = strict_json(original_files["reference-inventory.json"])
    inventory = strict_json(files["reader-inventory.json"])
    if (
        old_inventory["model_snapshot_inventory"] != inventory.get("files")
        or old_inventory["model_id"] != inventory.get("model")
        or old_inventory["revision"] != inventory.get("revision")
        or inventory.get("model") != MODEL_ID
        or inventory.get("revision") != MODEL_REV
    ):
        raise ValueError("frozen model or tokenizer inventory changed")
    observed_profiles = set()
    known = {}
    for case in cases:
        for arm in ARMS:
            for profile in PROFILES:
                key = case.question.identity, arm, profile
                row, saved, started = answers[key], scores[key], starts[key]
                if (
                    started.get("status") != "started"
                    or row.get("status") != "succeeded"
                    or not isinstance(row.get("answer"), str)
                    or not row["answer"].strip()
                ):
                    raise ValueError("failed/blank or missing Reader output")
                variant, docs = delivery(case, arm, profile)
                bundle, originals, frontier = evidence(
                    variant, docs, "lexical:" + profile + ":" + arm
                )
                bundle.validate(
                    variant.question, originals, frontier=frontier, revoked=set()
                )
                receipt = row["reader"]
                expected_sources = bundle.delivered()
                if (
                    row.get("selected") != [d.identity for d in docs]
                    or receipt.get("delivered_evidence") != expected_sources
                    or receipt.get("bundle_digest") != bundle.seal()
                    or receipt.get("query_digest")
                    != native_digest(asdict(variant.question))
                    or receipt.get("reader_identity") != STRONG_READER_ID
                    or receipt.get("model_id") != MODEL_ID
                    or receipt.get("revision") != MODEL_REV
                    or receipt.get("trainable_parameters") != 0
                    or receipt.get("answer_postprocessed") is not False
                    or receipt.get("production_accepted") is not False
                ):
                    raise ValueError("Reader provenance/bundle/source drift")
                if (
                    type(receipt.get("input_tokens")) is not int
                    or not 1 <= receipt["input_tokens"] <= 1024
                    or type(receipt.get("generated_tokens")) is not int
                    or not 1 <= receipt["generated_tokens"] <= 64
                    or type(receipt.get("cpu_time_ns")) is not int
                    or receipt["cpu_time_ns"] < 0
                    or not HEX64.fullmatch(receipt.get("input_ids_digest", ""))
                    or not HEX64.fullmatch(receipt.get("generated_ids_digest", ""))
                ):
                    raise ValueError("invalid actual input/output compute receipt")
                observed_profiles.add(receipt.get("reader_profile"))
                expected_score = score(case, arm, profile, row["answer"])
                if saved != dict(
                    qid=key[0], arm=arm, profile=profile, **expected_score
                ):
                    raise ValueError("post-seal grading changed")
                known[key] = dict(
                    score=expected_score,
                    answer=row["answer"],
                    input_tokens=receipt["input_tokens"],
                    output_tokens=receipt["generated_tokens"],
                    cpu_time_ns=receipt["cpu_time_ns"],
                )
    if len(observed_profiles) != 1:
        raise ValueError("multiple or unregistered Reader profiles")
    if (
        stored.get("source_commit") != SOURCE_COMMIT
        or stored.get("raw_answer_sha256") != sealed["sha256"]
        or stored.get("completed") != CALLS
        or stored.get("model_calls") != CALLS
        or stored.get("failures") != 0
        or stored.get("production_accepted") is not False
    ):
        raise ValueError("original summary or denominator drift")

    official = {}
    for profile in PROFILES:
        for arm in ARMS:
            sub = [known[c.question.identity, arm, profile] for c in cases]
            official[profile, arm] = dict(
                profile=profile,
                arm=arm,
                questions=len(sub),
                exact_answers=sum(x["score"]["exact_answer"] for x in sub),
                refusal_outputs=sum(x["score"]["exact_refusal"] for x in sub),
                appropriate_refusals=sum(
                    x["score"]["exact_refusal"] and not x["score"]["sufficient"]
                    for x in sub
                ),
                over_refusals=sum(x["score"]["over_refusal"] for x in sub),
                strict_successes=sum(x["score"]["task_success"] for x in sub),
                unsupported_token_copies=sum(
                    x["score"]["unsupported_token_copy"] for x in sub
                ),
                input_tokens=sum(x["input_tokens"] for x in sub),
                output_tokens=sum(x["output_tokens"] for x in sub),
                decoder_cpu_ns=sum(x["cpu_time_ns"] for x in sub),
            )
    recorded = {(s["profile"], s["arm"]): s for s in stored["results"]}
    if len(recorded) != len(official) or recorded != official:
        raise ValueError("saved factorial summary differs from raw outputs")
    expected_pass = all(
        official["inventory_tag", arm]["strict_successes"]
        >= (15 if arm in POSITIVE else 18)
        for arm in ARMS
    )
    expected_disposition = (
        "independent_language_confirmation_required"
        if expected_pass
        else "lexical_factorial_not_qualified"
    )
    if stored.get("disposition") != expected_disposition:
        raise ValueError("stored post-hoc threshold/drift")
    return known, cases, sealed["sha256"], len(files) - 1


def paired_summary(known, cases):
    """One per-question block, not 320 independent benchmark samples."""
    results = []
    for arm in ARMS:

        def table(metric):
            rows = []
            for case in cases:
                qid = case.question.identity
                rows.append(
                    {p: bool(known[qid, arm, p]["score"][metric]) for p in PROFILES}
                )
            return rows

        metrics = {}
        for metric in METRICS:
            rows = table(metric)
            left = "credential_tok"
            right = "inventory_tok"
            ctag = "credential_tag"
            itag = "inventory_tag"
            metrics[metric] = dict(
                baseline_successes=sum(r[left] for r in rows),
                inventory_tok_successes=sum(r[right] for r in rows),
                credential_tag_successes=sum(r[ctag] for r in rows),
                inventory_tag_successes=sum(r[itag] for r in rows),
                inventory_gain_at_tok=sum(not r[left] and r[right] for r in rows),
                inventory_loss_at_tok=sum(r[left] and not r[right] for r in rows),
                inventory_gain_at_tag=sum(not r[ctag] and r[itag] for r in rows),
                inventory_loss_at_tag=sum(r[ctag] and not r[itag] for r in rows),
                identifier_gain_credential=sum(not r[left] and r[ctag] for r in rows),
                identifier_loss_credential=sum(r[left] and not r[ctag] for r in rows),
                identifier_gain_inventory=sum(not r[right] and r[itag] for r in rows),
                identifier_loss_inventory=sum(r[right] and not r[itag] for r in rows),
                descriptive_interaction=sum(
                    int(r[itag]) - int(r[right]) - int(r[ctag]) + int(r[left])
                    for r in rows
                ),
            )
        costs = {}
        for profile in PROFILES:
            rows = [known[c.question.identity, arm, profile] for c in cases]
            costs[profile] = dict(
                input_tokens=sum(x["input_tokens"] for x in rows),
                generated_tokens=sum(x["output_tokens"] for x in rows),
                decoder_cpu_ns=sum(x["cpu_time_ns"] for x in rows),
            )
        results.append(
            dict(
                arm=arm,
                distinct_questions=len(cases),
                metrics=metrics,
                cost_by_profile=costs,
                causal_safety_policy_not_identified=True,
                correlated_synthetic_tasks=True,
            )
        )
    return results


def run(archive, original_archive, output, *, expected_digest=ARCHIVE_SHA):
    known, cases, seal, count = authenticate(
        archive, original_archive, expected_digest=expected_digest
    )
    findings = dict(
        schema="hepta.system2.lexical-sealed-audit.v1",
        generating_commit=SOURCE_COMMIT,
        raw_seal=seal,
        archive_sha256=expected_digest,
        verified_internal_files=count,
        new_neural_calls=0,
        audited_neural_calls=CALLS,
        question_count=len(cases),
        profile_count=len(PROFILES),
        grouped_effects=paired_summary(known, cases),
        model_answer_weight_training=0,
        exact_cpu_matched=False,
        independently_reviewed_natural_questions=False,
        general_ndu_fbsde_gain=False,
        production_accepted=False,
    )
    Path(output).write_text(
        json.dumps(findings, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf8",
    )
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("completed_zip", type=Path)
    parser.add_argument("frozen_original_zip", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    r = run(args.completed_zip, args.frozen_original_zip, args.output)
    print(
        json.dumps(
            dict(
                questions=r["question_count"],
                audited_calls=r["audited_neural_calls"],
                new_model_calls=r["new_neural_calls"],
            ),
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
