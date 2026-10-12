"""Paired, source-only cost accounting for the frozen LoCoMo k4/k8 Reader.

Use original completed raw output receipts. Neither this code nor its tests
call a model, open answer targets, choose k, certify a citation, or assume that
a failed generation costs zero. Matched-only deltas have a separate denominator.
"""

from collections import Counter, defaultdict
import hashlib
import json
import math
import re

ARMS = ("lexical_k4", "lexical_k8")
SCHEMA = "hepta.memorycell.locomo-reader-matched-cost.v1"


def _success_cost(row):
    receipt = row["receipt"]
    if (
        not isinstance(row.get("answer"), str) or not row["answer"].strip()
        or not isinstance(receipt, dict)
        or type(receipt.get("input_tokens")) is not int
        or not 0 < receipt["input_tokens"] <= 2048
        or type(receipt.get("generated_tokens")) is not int
        or not 0 <= receipt["generated_tokens"] <= 64
        or type(receipt.get("seconds")) not in (float, int)
        or not math.isfinite(receipt["seconds"])
        or receipt["seconds"] < 0
        or not isinstance(receipt.get("delivered_evidence"), list)
        or len(receipt["delivered_evidence"]) != len(row["selected"])
        or any(
            not isinstance(doc, dict)
            or not isinstance(doc.get("excerpt"), str)
            or doc.get("original_id") != key
            for doc, key in zip(
                receipt["delivered_evidence"], row["selected"], strict=True
            )
        )
    ):
        raise ValueError("unbound actual Reader cost or delivered source receipt")
    return dict(
        input_tokens=receipt["input_tokens"],
        generated_tokens=receipt["generated_tokens"],
        seconds=receipt["seconds"],
        source_utf8_bytes=sum(
            len(doc["excerpt"].encode("utf-8", "strict"))
            for doc in receipt["delivered_evidence"]
        ),
    )


def audit_matched_costs(cases, rows):
    """Only compare *both-successful* pairs; retain 16 planned failure classes."""
    expected = [(case["question_id"], arm) for case in cases for arm in ARMS]
    observed = [(row["question_id"], row["arm"]) for row in rows]
    families = [case["family_proxy_digest"] for case in cases]
    if (
        len(cases) != 16
        or len({q for q, _ in expected}) != 16
        or len(set(families)) != 2
        or observed != expected
    ):
        raise ValueError("noncanonical sixteen-question original Reader pair census")

    paired, per_family = [], defaultdict(list)
    only4 = only8 = both_failed = 0
    failures = Counter()
    counts = {arm: Counter() for arm in ARMS}
    for i, case in enumerate(cases):
        a, b = rows[2 * i : 2 * i + 2]
        if (
            a.get("family_proxy_digest") != case["family_proxy_digest"]
            or b.get("family_proxy_digest") != case["family_proxy_digest"]
            or a.get("source_census_sha256") != case["source_census_sha256"]
            or b.get("source_census_sha256") != case["source_census_sha256"]
            or len(a["selected"]) != 4 or len(b["selected"]) != 8
            or a["selected"] != b["selected"][:4]
        ):
            raise ValueError("source-family or registered nested retrieval drift")
        data = []
        for row in (a, b):
            status = row.get("status")
            if status not in ("succeeded", "failed"):
                raise ValueError("invalid original Reader completion state")
            if status == "failed":
                if "answer" in row or "receipt" in row:
                    raise ValueError("failed Reader request has a fabricated success")
                failure = row.get("error_type")
                if not isinstance(failure, str) or not failure:
                    raise ValueError("missing actual failure classification")
                failures[(row["arm"], failure)] += 1
                counts[row["arm"]]["failed"] += 1
                data.append(None)
            else:
                data.append(_success_cost(row))
                counts[row["arm"]]["succeeded"] += 1
        cost4, cost8 = data
        if cost4 is None and cost8 is None:
            both_failed += 1
        elif cost4 is None:
            only8 += 1
        elif cost8 is None:
            only4 += 1
        else:
            if (
                a["receipt"].get("reader_identity") != b["receipt"].get("reader_identity")
                or a["receipt"].get("reader_profile") != b["receipt"].get("reader_profile")
                or not a["receipt"].get("reader_identity")
                or not a["receipt"].get("reader_profile")
                or cost8["source_utf8_bytes"] < cost4["source_utf8_bytes"]
                or cost8["input_tokens"] < cost4["input_tokens"]
            ):
                raise ValueError("model identity, source bytes or token monotonicity drift")
            row = dict(
                question_id=case["question_id"],
                family_proxy_digest=case["family_proxy_digest"],
                extra_source_utf8_bytes=(
                    cost8["source_utf8_bytes"] - cost4["source_utf8_bytes"]
                ),
                extra_prompt_tokens=cost8["input_tokens"] - cost4["input_tokens"],
                extra_generated_tokens=(
                    cost8["generated_tokens"] - cost4["generated_tokens"]
                ),
                extra_generation_seconds=cost8["seconds"] - cost4["seconds"],
                both_real_model_calls_succeeded=True,
            )
            paired.append(row)
            per_family[row["family_proxy_digest"]].append(row)

    def stats(batch):
        return dict(
            complete_paired_question_count=len(batch),
            mean_extra_source_utf8_bytes=(
                math.fsum(x["extra_source_utf8_bytes"] for x in batch) / len(batch)
                if batch else None
            ),
            mean_extra_prompt_tokens=(
                math.fsum(x["extra_prompt_tokens"] for x in batch) / len(batch)
                if batch else None
            ),
            mean_extra_generation_seconds=(
                math.fsum(x["extra_generation_seconds"] for x in batch) / len(batch)
                if batch else None
            ),
        )
    family_results = {k: stats(per_family[k]) for k in sorted(set(families))}
    return dict(
        schema=SCHEMA,
        original_planned_question_pairs=16,
        logical_reader_attempts=32,
        completed_paired_questions=len(paired),
        k4_success_k8_failure=only4,
        k8_success_k4_failure=only8,
        both_reader_calls_failed=both_failed,
        per_arm={arm: dict(counts[arm]) for arm in ARMS},
        error_type_counts={
            f"{arm}/{reason}": n for (arm, reason), n in sorted(failures.items())
        },
        matched_only_cost=stats(paired),
        per_family_proxy_matched_only=family_results,
        paired_cost_rows=paired,
        missing_pair_costs_not_treated_as_zero=True,
        source_utf8_bytes_not_actual_prompt_tokens=True,
        generation_time_does_not_include_cold_load=True,
        independent_source_family_significance=False,
        reader_task_gain_measured_by_this_module=False,
        independently_adjudicated_citation_precision=None,
        production_accepted=False,
    )


def verify_immutable_generation_record(
    manifest, raw_bytes, rows, *, expected_commit,
    public_zip_sha256, decisions_zip_sha256,
):
    """Validate source-bound run totals BEFORE a scorer opens any QA labels.

    The trusted expected Git commit and both immutable original ZIP hashes are
    supplied independently, not learned from the artifact under review.
    """
    def pin(value, size):
        return isinstance(value, str) and re.fullmatch(
            r"[a-f0-9]{" + str(size) + r"}", value
        ) is not None

    if (
        not isinstance(manifest, dict)
        or not isinstance(raw_bytes, bytes)
        or not isinstance(rows, list)
        or not pin(expected_commit, 40)
        or not pin(public_zip_sha256, 64)
        or not pin(decisions_zip_sha256, 64)
        or manifest.get("schema") !=
        "hepta.memorycell.locomo-frozen-reader-pair.v1"
        or manifest.get("generating_commit") != expected_commit
        or manifest.get("original_source_sha256") != public_zip_sha256
        or manifest.get("original_six_decisions_sha256") != decisions_zip_sha256
        or manifest.get("raw_journal_sha256") != hashlib.sha256(raw_bytes).hexdigest()
        or not pin(manifest.get("model_stage_sha256"), 64)
        or not pin(manifest.get("model_identity"), 64)
        or not pin(manifest.get("model_profile"), 64)
        or manifest.get("planned_questions") != 16
        or manifest.get("planned_arms") != list(ARMS)
        or manifest.get("planned_model_calls") != 32
        or manifest.get("actual_model_calls") != len(rows)
        or len(rows) != 32
        or manifest.get("input_token_ceiling") != 2048
        or manifest.get("generated_token_ceiling") != 64
        or manifest.get("weight_updates") != 0
        or manifest.get("labels_seen_during_generation") is not False
        or manifest.get("original_answers_rewritten") is not False
        or manifest.get("production_accepted") is not False
        or manifest.get("semantic_citation_precision") is not None
    ):
        raise ValueError("untrusted or incomplete immutable Qwen generation journal")
    if (
        not raw_bytes.endswith(b"\n")
        or len(raw_bytes) > 4 * 1024 * 1024
        or len(raw_bytes.splitlines()) != len(rows)
    ):
        raise ValueError("incomplete or oversized original raw Reader journal")

    def unique(values):
        output = {}
        for k, value in values:
            if k in output:
                raise ValueError("duplicate JSON property in Reader record")
            output[k] = value
        return output

    def bad_constant(value):
        raise ValueError("nonfinite Reader record constant: " + value)

    original_rows = [
        json.loads(line, object_pairs_hook=unique, parse_constant=bad_constant)
        for line in raw_bytes.splitlines()
    ]
    if original_rows != rows:
        raise ValueError("scored Reader rows do not match immutable raw bytes")
    statuses = Counter(row.get("status") for row in rows)
    if (
        set(statuses) - {"succeeded", "failed"}
        or statuses["succeeded"] != manifest.get("succeeded")
        or statuses["failed"] != manifest.get("failed")
    ):
        raise ValueError("generation success/failure totals differ from raw records")
    for row in rows:
        if row["status"] == "failed":
            if "answer" in row or "receipt" in row:
                raise ValueError("failed generation contained fabricated output")
        else:
            receipt = row.get("receipt")
            if (
                not isinstance(receipt, dict)
                or receipt.get("reader_identity") != manifest["model_identity"]
                or receipt.get("reader_profile") != manifest["model_profile"]
            ):
                raise ValueError("Reader identity differs from pinned source model")
    return dict(
        generation_commit_verified=expected_commit,
        source_zip_and_decisions_sha256_verified=True,
        actual_logical_attempts=len(rows),
        actual_completed_answers=statuses["succeeded"],
        actual_failed_or_rejected_requests=statuses["failed"],
        score_only_no_generated_answer_modified=True,
        model_executions_not_equated_to_logical_attempts=True,
        production_accepted=False,
    )
