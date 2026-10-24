"""Sealed, no-inference same-question 135M versus 0.5B Reader evidence audit.

Only 20 previously exposed fictional questions are paired here. The additional
20 tasks have completed 0.5B outputs but NO matching 135M results yet.
Do not claim same tokens, same FLOPs, new experiments or generalization.
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
    CASE_COUNT,
    COHORTS,
    MODEL_ID,
    MODEL_REV,
    READER_IDENTITY,
    cohorts,
    load_baseline_archives,
    outcome,
    selected,
)

NEW_135M_ZIP_SHA = "aaa8d1ee112ae8ad903834d0384f5de94cf19197d36e9ea4b6fce99d485715f0"
NEW_135M_COMMIT = "f6139d7b78b45add91caa491dc523ac8527fa633"
NEW_135M_TREE = "9271dc423235dd23d841c36dd178b1a6b182a099"
NEW_135M_RAW_SHA = "6b7cc60f0feb0fd2d8843db1ccb74a6453cefacd6df14de6764f93fffc6689ce"
STRONG_ZIP_SHA = "853afed48368b2c4e562191c7ed6d6bf28492bd80ec95634119b8afc7d43ab37"
STRONG_COMMIT = "dcd799fe0d90e05183701e336af76199dbc52f71"
STRONG_TREE = "4d698a667f6c56cc2575f4859bb08e1424329051"
STRONG_RAW_SHA = "de6d403fcf357000e07f9b235b1699ed85718e3954faf167b9fbb895a1e5405f"
STRONG_READER_ID = "ee402c424e3843108772cfb5e20798e858ff5fd38b9204d39539608c522b5301"
SCHEMA = "hepta.system2.sealed-reader-paired-capacity.v1"


def open_strong(archive):
    files = verified_archive(Path(archive), STRONG_ZIP_SHA)
    if (
        files["tested-commit.txt"].decode().strip() != STRONG_COMMIT
        or files["tested-tree.txt"].decode().strip() != STRONG_TREE
    ):
        raise ValueError("strong Reader original generating source changed")
    raw = files["trial/raw-answers.jsonl"]
    seal = strict_json(files["trial/raw-seal.json"])
    if (
        seal != dict(rows=160, scoring_started=False, sha256=STRONG_RAW_SHA)
        or hashlib.sha256(raw).hexdigest() != STRONG_RAW_SHA
    ):
        raise ValueError("strong Reader raw prediction seal changed")
    plan = strict_json(files["trial/plan.json"])
    if (
        plan["generating_commit"] != STRONG_COMMIT
        or plan["reference_model"] != MODEL_ID
        or plan["reference_revision"] != MODEL_REV
        or plan["reference_reader_identity"] != STRONG_READER_ID
        or plan["existing_135m_reader_id"] != READER_IDENTITY
        or plan["arms"] != list(ARMS)
        or set(plan["cohorts"]) != set(COHORTS)
        or plan["planned"] != 160
        or plan["learning_updates"] != 0
        or plan["production_accepted"] is not False
    ):
        raise ValueError("strong Reader model, study or admission changed")
    by_key = {}
    for line in raw.splitlines():
        row = strict_json(line)
        key = row["qid"], row["arm"]
        if (
            key in by_key
            or row.get("status") != "succeeded"
            or not isinstance(row.get("answer"), str)
            or not row["answer"].strip()
            or row.get("cohort") not in COHORTS
        ):
            raise ValueError("strong Reader census/status invalid")
        rec = row["reader"]
        if (
            rec["reader_identity"] != STRONG_READER_ID
            or rec["model_id"] != MODEL_ID
            or rec["model_revision"] != MODEL_REV
            or rec["trainable_parameters"] != 0
            or rec["answer_postprocessed"] is not False
            or rec["production_accepted"] is not False
            or type(rec["input_tokens"]) is not int
            or not 1 <= rec["input_tokens"] <= 1024
            or type(rec["generated_tokens"]) is not int
            or not 1 <= rec["generated_tokens"] <= 64
            or type(rec["cpu_time_ns"]) is not int
            or rec["cpu_time_ns"] < 0
        ):
            raise ValueError("strong Reader model/cost receipt changed")
        by_key[key] = row
    if len(by_key) != 160:
        raise ValueError("strong Reader missing/duplicated cells")
    return files, plan, by_key


def append_new_135m(archive, historical, groups):
    """Validate sealed new20 model outputs AND original 80 reused receipts."""
    files = verified_archive(Path(archive), NEW_135M_ZIP_SHA)
    if (
        files["tested-commit.txt"].decode().strip() != NEW_135M_COMMIT
        or files["tested-tree.txt"].decode().strip() != NEW_135M_TREE
    ):
        raise ValueError("new 135M generating source drift")
    raw = files["trial/raw-answers.jsonl"]
    seal = strict_json(files["trial/raw-seal.json"])
    if (
        seal != dict(sha256=NEW_135M_RAW_SHA, rows=80, posthoc_scoring_started=False)
        or hashlib.sha256(raw).hexdigest() != NEW_135M_RAW_SHA
    ):
        raise ValueError("new 135M answer seal drift")
    plan = strict_json(files["trial/plan.json"])
    summary = strict_json(files["trial/summary.json"])
    if (
        plan.get("source_commit") != NEW_135M_COMMIT
        or plan.get("actual_new_135m_model_calls") != 80
        or plan.get("original_135m_model_calls_reused") != 80
        or plan.get("original_reader_identity") != READER_IDENTITY
        or plan.get("old_135m_source_raw_sha256") != historical["raw_sha256"]
        or plan.get("arms") != list(ARMS)
        or plan.get("production_accepted") is not False
        or summary.get("recorded_new") != 80
        or summary.get("failed_new") != 0
        or summary.get("new_raw_sha256") != NEW_135M_RAW_SHA
        or summary.get("existing_parent_raw_sha256") != historical["raw_sha256"]
    ):
        raise ValueError("new 135M registered protocol drift")
    original = historical["by_key"]
    expected_old = {
        (c.question.identity, a) for c in groups["exposed_20"] for a in ARMS
    }
    parity = strict_json(files["trial/original-prompt-parity.json"])
    seen = set()
    for record in parity:
        key = record["qid"], record["arm"]
        presentation = "unlabeled" if record["arm"] == "no_evidence" else "labeled"
        if (
            key not in expected_old
            or key in seen
            or record["presentation"] != presentation
        ):
            raise ValueError("missing or changed previous 135M comparison")
        old = original[record["qid"], record["arm"], presentation]["reader"]
        if (
            record["input_ids_digest"] != old["input_ids_digest"]
            or record["input_tokens"] != old["input_tokens"]
            or record["response_ids_digest"] != old["generated_ids_digest"]
            or record["model_calls_reused"] != 1
            or record["new_model_calls"] != 0
        ):
            raise ValueError("reused 135M prompt token/content drift")
        seen.add(key)
    if seen != expected_old:
        raise ValueError("incomplete 80-position original 135M parity")
    expected_new = {
        (c.question.identity, a) for c in groups["fixed_new_20"] for a in ARMS
    }
    new = {}
    for line in raw.splitlines():
        item = strict_json(line)
        key = item["qid"], item["arm"]
        if (
            key not in expected_new
            or key in new
            or item.get("status") != "succeeded"
            or item.get("cohort") != "fixed_new_20"
        ):
            raise ValueError("missing, duplicate or failed 135M new cohort position")
        rec = item["reader"]
        presentation = "unlabeled" if item["arm"] == "no_evidence" else "labeled"
        if (
            item["presentation"] != presentation
            or rec["reader_identity"] != READER_IDENTITY
            or rec["answer_postprocessed"] is not False
            or rec["production_accepted"] is not False
            or rec["trainable_parameters"] != 0
            or rec["token_limit"] != 1024
            or not isinstance(item.get("answer"), str)
            or not item["answer"].strip()
            or type(rec["generated_tokens"]) is not int
            or not 1 <= rec["generated_tokens"] <= 64
            or item["source_bundle_digest"] != rec["bundle_digest"]
        ):
            raise ValueError("135M inference result/identity drift")
        new[key] = item
    if set(new) != expected_new:
        raise ValueError("incomplete 135M new positions")
    updated = dict(historical)
    updated["by_key"] = dict(original)
    for (qid, arm), item in new.items():
        presentation = "unlabeled" if arm == "no_evidence" else "labeled"
        updated["by_key"][qid, arm, presentation] = item
    updated["new_model_calls"] = len(new)
    updated["new_raw_sha256"] = NEW_135M_RAW_SHA
    updated["new_verified_files"] = len(files) - 1
    return updated


def paired_rows(strong, historical, plan, groups, scored):
    """Validate exact original excerpt identity before scoring each prompt."""
    planned = {
        (c.question.identity, a)
        for group in groups.values()
        for c in group
        for a in ARMS
    }
    if set(strong) != planned or set(scored) != planned:
        raise ValueError("missing/extra/duplicate Reader subjects")
    output = []
    for cohort in COHORTS:
        cases = groups[cohort]
        if (
            plan["cohorts"][cohort] != [c.question.identity for c in cases]
            or len(cases) != CASE_COUNT
        ):
            raise ValueError("question cohort changed")
        for case in cases:
            qid = case.question.identity
            original_signature = native_digest(
                [
                    (d.identity, d.root, d.scope, d.observed_at, d.content)
                    for d in case.documents
                ]
            )
            if plan["source_manifest"][qid] != original_signature:
                raise ValueError("strong Reader original source manifest changed")
            for arm in ARMS:
                result = strong[qid, arm]
                docs = selected(case, arm)
                bundle, _, _ = evidence(case, docs, arm)
                rec = result["reader"]
                expected_sources = bundle.delivered()
                if (
                    result["cohort"] != cohort
                    or result["selected"] != [d.identity for d in docs]
                    or rec["delivered_evidence"] != expected_sources
                    or rec["bundle_digest"] != bundle.seal()
                    or rec["question_digest"] != native_digest(asdict(case.question))
                ):
                    raise ValueError(
                        "strong Reader original prompt/excerpt bytes changed"
                    )
                res = outcome(case, arm, result["answer"])
                prior = scored[qid, arm]
                if prior.get("status") != "succeeded" or prior["cohort"] != cohort:
                    raise ValueError("archived scored status changed")
                for key, value in res.items():
                    if prior.get(key) != value:
                        raise ValueError("strong Reader scored record drift: " + key)
                item = dict(
                    cohort=cohort,
                    arm=arm,
                    question_id=qid,
                    strong=dict(
                        conditional_success=res["conditional_success"],
                        exact_answer_only=res["exact_answer_only"],
                        correct_refusal=res["correct_refusal"],
                        label_only_echo=res["label_only_echo"],
                        input_tokens=rec["input_tokens"],
                        generated_tokens=rec["generated_tokens"],
                        cpu_time_ns=rec["cpu_time_ns"],
                    ),
                )
                if cohort in COHORTS:
                    presentation = "unlabeled" if arm == "no_evidence" else "labeled"
                    old = historical["by_key"][qid, arm, presentation]
                    old_bundle, _, _ = evidence(case, docs, "answer-only:" + arm)
                    old_rec = old["reader"]
                    if (
                        old.get("status") != "succeeded"
                        or old["selected"] != result["selected"]
                        or old_rec["delivered_evidence"] != expected_sources
                        or old_rec["bundle_digest"] != old_bundle.seal()
                        or old_rec["reader_identity"] != READER_IDENTITY
                        or old_rec["query_digest"] != rec["question_digest"]
                    ):
                        raise ValueError(
                            "historical same-question Reader provenance drift"
                        )
                    old_score = outcome(case, arm, old["answer"])
                    item["old_135m"] = dict(
                        conditional_success=old_score["conditional_success"],
                        exact_answer_only=old_score["exact_answer_only"],
                        correct_refusal=old_score["correct_refusal"],
                        label_only_echo=old_score["label_only_echo"],
                        input_tokens=old_rec["input_tokens"],
                        generated_tokens=old_rec["generated_tokens"],
                    )
                output.append(item)
    if len(output) != 160:
        raise ValueError("bounded same-task census mismatch")
    return output


def summarize(items):
    groups = []
    for cohort in COHORTS:
        for arm in ARMS:
            subset = [x for x in items if x["cohort"] == cohort and x["arm"] == arm]
            if len(subset) != CASE_COUNT:
                raise ValueError("incomplete cohort/arm result")
            record = dict(
                cohort=cohort,
                arm=arm,
                planned=CASE_COUNT,
                strong_exact=sum(r["strong"]["exact_answer_only"] for r in subset),
                strong_correct_refusals=sum(
                    r["strong"]["correct_refusal"] for r in subset
                ),
                strong_task_success=sum(
                    r["strong"]["conditional_success"] for r in subset
                ),
                strong_input_tokens=sum(r["strong"]["input_tokens"] for r in subset),
                strong_output_tokens=sum(
                    r["strong"]["generated_tokens"] for r in subset
                ),
                strong_generation_cpu_ns=sum(
                    r["strong"]["cpu_time_ns"] for r in subset
                ),
                strong_only_comparison_not_matched_compute=True,
            )
            if cohort in COHORTS:
                old = [r["old_135m"]["conditional_success"] for r in subset]
                new = [r["strong"]["conditional_success"] for r in subset]
                record.update(
                    original_135m_success=sum(old),
                    both_success=sum(a and b for a, b in zip(old, new, strict=True)),
                    only_original_success=sum(
                        a and not b for a, b in zip(old, new, strict=True)
                    ),
                    only_strong_success=sum(
                        b and not a for a, b in zip(old, new, strict=True)
                    ),
                    neither_success=sum(
                        not a and not b for a, b in zip(old, new, strict=True)
                    ),
                    original_input_tokens=sum(
                        r["old_135m"]["input_tokens"] for r in subset
                    ),
                    original_output_tokens=sum(
                        r["old_135m"]["generated_tokens"] for r in subset
                    ),
                )
            groups.append(record)
    return groups


def run(
    strong_archive,
    cardinality_archive,
    label_archive,
    new_135m_archive,
    output,
    *,
    source_commit,
):
    if not isinstance(source_commit, str) or not re.fullmatch(
        "[0-9a-f]{40}", source_commit
    ):
        raise ValueError("exact audited Git source commit required")
    files, plan, strong = open_strong(strong_archive)
    old = load_baseline_archives(cardinality_archive, label_archive)
    groups = cohorts()
    old = append_new_135m(new_135m_archive, old, groups)
    scores = strict_json(files["trial/scored.json"])
    score_keys = [(r["qid"], r["arm"]) for r in scores]
    if len(score_keys) != 160 or len(set(score_keys)) != 160:
        raise ValueError("strong Reader scored census invalid")
    audited = paired_rows(
        strong, old, plan, groups, dict(zip(score_keys, scores, strict=True))
    )
    summary = summarize(audited)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise ValueError("refusing to overwrite a completed audit")
    receipt = dict(
        schema=SCHEMA,
        source_commit=source_commit,
        strong_model_id=MODEL_ID,
        strong_model_revision=MODEL_REV,
        strong_source_commit=STRONG_COMMIT,
        strong_archive_sha256=STRONG_ZIP_SHA,
        strong_raw_sha256=STRONG_RAW_SHA,
        original_135m_raw_sha256=old["raw_sha256"],
        strong_inner_verified_files=len(files) - 1,
        historical_archive_verified_files=old["verified_files"],
        completed_strong_attempts=len(audited),
        paired_same_question_subjects=40,
        paired_original_135m_conditions=160,
        previously_exposed_questions=20,
        fixed_new_questions=20,
        new_135m_archive_sha256=NEW_135M_ZIP_SHA,
        new_135m_raw_sha256=old["new_raw_sha256"],
        new_135m_verified_files=old["new_verified_files"],
        actual_new_135m_calls_from_completed_parent=80,
        model_calls_in_this_audit=0,
        neither_tokenizer_nor_compute_matched=True,
        independent_natural_semantics=False,
        production_accepted=False,
        by_arm=summary,
    )
    output.write_text(
        json.dumps(
            receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False
        )
        + "\n"
    )
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in (
        "strong_archive",
        "cardinality_archive",
        "label_archive",
        "new_135m_archive",
        "output",
    ):
        parser.add_argument(argument, type=Path)
    args = parser.parse_args()
    out = run(
        args.strong_archive,
        args.cardinality_archive,
        args.label_archive,
        args.new_135m_archive,
        args.output,
        source_commit=os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", ""),
    )
    print(
        json.dumps(
            dict(
                schema=out["schema"],
                paired=out["paired_original_135m_conditions"],
                completed=out["completed_strong_attempts"],
                by_arm=out["by_arm"],
            ),
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    import os

    main()
