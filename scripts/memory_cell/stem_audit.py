"""Reconcile original six-arm stem artifacts without a single model execution.

Audit success is not experiment success. Scores below are checked for accounting
consistency, NOT independently recomputed semantic correctness or entailment.
"""

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import re

from native import digest
from stem_audit_archive import PinnedArchive, require
from stem_audit_diagnosis import diagnose
from stem_audit_cost import audit_resources
from stem_audit_candidate import candidate_capacity
from stem_audit_adapter_warmstart import analyze_warmstart

ARMS = (
    "frozen_rerank",
    "prototype",
    "linear",
    "gated",
    "lineage_lora_gated",
    "independent_lora_gated",
)
PHASES = ("select", "retention", "test", "transfer")
CURVE = (16, 32, 48)
SCORE_FIELDS = {"source_choice_correct", "diagnostic_answer_f1", "citation_structure"}
REUSE_FIELDS = {
    "reused_from",
    "actual_reader_execution",
    "incremental_generation_seconds",
}


def policy_key(row):
    return (row["stage"], row["phase"], row["question_id"], row["arm"])


def record_key(row):
    if "arm" not in row:
        return f"oracle/{row['phase']}/{row['question_id']}"
    return f"{row['stage']}/{row['phase']}/{row['question_id']}/{row['arm']}"


def validate_records(plan, raw, scored, oracles, report):
    require(tuple(plan["arms"]) == ARMS, "six-arm identity mismatch")
    require(tuple(plan["curriculum_attempted_examples"]) == CURVE, "checkpoint drift")
    require(report["plan"] == plan, "report changed registered plan")
    require(report["production_accepted"] is False, "unexpected production acceptance")
    require(report["superiority_claim"] is False, "unexpected superiority claim")
    for phase in PHASES:
        ids = plan["questions"][phase]
        require(
            ids and len(ids) == len(set(ids)), "empty or duplicate registered questions"
        )
    expected = {
        (stage, phase, qid, arm)
        for stage in CURVE
        for phase in PHASES
        for qid in plan["questions"][phase]
        for arm in ARMS
    }
    raw_by_key, scored_by_key = {}, {}
    for rows, output in ((raw, raw_by_key), (scored, scored_by_key)):
        for row in rows:
            key = policy_key(row)
            require(
                key in expected and key not in output,
                "missing, duplicate or extra attempt",
            )
            require(
                row["family"] == plan["question_families"][row["question_id"]],
                "family drift",
            )
            require(row["status"] in ("succeeded", "failed"), "unknown policy status")
            output[key] = row
        require(set(output) == expected, "incomplete policy census")
    for key, row in scored_by_key.items():
        original = raw_by_key[key]
        require(
            set(row) == set(original) | SCORE_FIELDS,
            "unexpected score annotation fields",
        )
        require(
            {k: row[k] for k in original} == original, "scoring rewrote original output"
        )
        for field in ("source_choice_correct", "diagnostic_answer_f1"):
            value = row[field]
            require(
                value is None
                or (
                    type(value) in (int, float)
                    and math.isfinite(value)
                    and 0 <= value <= 1
                ),
                "invalid diagnostic score",
            )
        require(
            row["citation_structure"]["semantic_precision"] is None,
            "invented semantic verdict",
        )
    oracle_expected = {
        (phase, qid) for phase in PHASES for qid in plan["questions"][phase]
    }
    seen = set()
    for row in oracles:
        key = (row["phase"], row["question_id"])
        require(key in oracle_expected and key not in seen, "oracle census mismatch")
        require(
            row["status"] in ("succeeded", "failed", "unavailable"), "oracle status"
        )
        require(row["policy_comparator"] is False, "oracle promoted to policy")
        require(
            row["semantic_entailment_independently_verified"] is False,
            "invented gold oracle",
        )
        seen.add(key)
    require(seen == oracle_expected, "missing oracle records")

    executions, hits, generators, request_keys = {}, 0, set(), set()
    stage_counts = defaultdict(Counter)
    for row in raw + oracles:
        if row["status"] != "succeeded":
            continue
        receipt, key = row["receipt"], record_key(row)
        actual = receipt["actual_reader_execution"]
        require(type(actual) is bool, "actual-execution flag must be Boolean")
        query = receipt["observable_query"]
        require(query["identity"] == row["question_id"], "Reader query identity drift")
        canonical = digest(
            (
                receipt["generator_identity"],
                receipt["generator_profile"],
                query,
                receipt["delivered_evidence"],
            )
        )
        require(
            canonical == receipt["canonical_request_digest"],
            "canonical request mismatch",
        )
        generators.add((receipt["generator_identity"], receipt["generator_profile"]))
        request_keys.add(canonical)
        seconds = receipt["generation_seconds"]
        require(
            type(seconds) in (int, float) and math.isfinite(seconds) and seconds >= 0,
            "Reader time",
        )
        if actual:
            require(receipt["reused_from"] is None, "actual call claims reuse")
            require(
                receipt["incremental_generation_seconds"] == seconds,
                "actual timing mismatch",
            )
            executions[key] = row
        else:
            parent = receipt["reused_from"]
            require(
                parent in executions,
                "missing, forward, cyclic or indirect reuse reference",
            )
            first = executions[parent]
            require(first["answer"] == row["answer"], "reuse changed answer bytes")
            require(
                {k: v for k, v in receipt.items() if k not in REUSE_FIELDS}
                == {k: v for k, v in first["receipt"].items() if k not in REUSE_FIELDS},
                "reuse changed request or generation receipt",
            )
            require(
                receipt["incremental_generation_seconds"] == 0.0,
                "cache hit charged generation",
            )
            hits += 1
        if "stage" in row:
            stage_counts[row["stage"]]["actual" if actual else "reused"] += 1
    require(len(generators) == 1, "missing or mixed frozen Readers")
    claimed = report["reader"]
    for field in (
        "actual_attempts",
        "actual_successes",
        "actual_failed_attempts",
        "cache_hits",
    ):
        require(
            type(claimed[field]) is int and claimed[field] >= 0,
            "invalid Reader counter",
        )
    require(
        claimed["actual_successes"] == len(executions),
        "Reader success counter mismatch",
    )
    require(claimed["cache_hits"] == hits, "Reader reuse counter mismatch")
    require(
        claimed["actual_attempts"]
        == len(executions) + claimed["actual_failed_attempts"],
        "Reader attempted-call accounting mismatch",
    )
    # Old failed records lack an execution journal; never certify inferred work.
    failure_calls_verified = claimed["actual_failed_attempts"] == 0
    counts, groups, failure_reasons = Counter(), defaultdict(list), Counter()
    for row in scored:
        counts[row["status"]] += 1
        groups[(row["stage"], row["phase"], row["arm"])].append(row)
        if row["status"] == "failed":
            failure_reasons[f"{row.get('error_type')}: {row.get('error')}"] += 1
    require(
        report["logical_policy_attempts"] == len(expected), "logical count mismatch"
    )
    final_metrics = {}
    for key, rows in sorted(groups.items()):
        stored = report["metrics"]["/".join(map(str, key))]
        succeeded = sum(r["status"] == "succeeded" for r in rows)
        values = {
            "attempted": len(rows),
            "succeeded": succeeded,
            "failed": len(rows) - succeeded,
        }
        for field, value in values.items():
            require(
                type(stored[field]) is int and stored[field] == value,
                "metric census mismatch",
            )
        for score, mean_field in (
            ("source_choice_correct", "source_accuracy"),
            ("diagnostic_answer_f1", "diagnostic_f1"),
        ):
            known = [r[score] for r in rows if r[score] is not None]
            mean = None if not known else math.fsum(known) / len(known)
            saved = stored[mean_field]
            require(
                saved is None
                if mean is None
                else type(saved) in (int, float)
                and math.isfinite(saved)
                and math.isclose(saved, mean, abs_tol=1e-12),
                "metric mean inconsistent with unchanged scored rows",
            )
            values[mean_field] = mean
        if key[0] == CURVE[-1]:
            final_metrics["/".join(key[1:])] = values
    changes = {}
    for arm in ARMS[1:]:
        pairs = [
            (row, raw_by_key[(s, p, q, ARMS[0])])
            for (s, p, q, a), row in raw_by_key.items()
            if a == arm
        ]
        complete = [
            (a, b) for a, b in pairs if a["status"] == b["status"] == "succeeded"
        ]
        changes[arm] = dict(
            planned_pairs=len(pairs),
            complete_pairs=len(complete),
            changed_selections=sum(a["selected"] != b["selected"] for a, b in complete),
            changed_answers=sum(a["answer"] != b["answer"] for a, b in complete),
        )
    return dict(
        schema="hepta.stem-artifact-audit.v1",
        accounting_verified=True,
        policy_counts=dict(counts),
        logical_policy_attempts=len(expected),
        oracle_counts=dict(Counter(r["status"] for r in oracles)),
        reader_actual_successes=len(executions),
        reader_cache_hits=hits,
        reader_failed_calls_individually_verified=failure_calls_verified,
        reader_unique_requests=len(request_keys),
        checkpoint_reader_counts=dict(stage_counts),
        failure_reasons=dict(failure_reasons),
        final_checkpoint_metrics=final_metrics,
        paired_changes=changes,
        policy_citation_markers=sum(
            len(re.findall(r"\[E\d+\]", r.get("answer", ""))) for r in raw
        ),
        policy_matrix_succeeded=counts["failed"] == 0,
        diagnostic_scores_independently_recomputed=False,
        semantic_citation_precision=None,
        production_accepted=False,
        new_model_calls=0,
    )


def audit_zip(path, pin, source, tree):
    archive = PinnedArchive(path, pin)
    try:
        require(
            archive.read("tested-commit.txt").decode().strip() == source,
            "source commit mismatch",
        )
        require(
            archive.read("tested-tree.txt").decode().strip() == tree,
            "source tree mismatch",
        )
        plan = archive.json("comparison/preregistered.json")
        require(plan["source_commit"] == source, "generating source mismatch")
        raw = archive.jsonl("comparison/policy-predictions.jsonl")
        scored = archive.json("comparison/scored-policy-attempts.json")
        oracles = archive.jsonl("comparison/oracle-diagnostic.jsonl")
        report = archive.json("comparison/report.json")
        result = validate_records(plan, raw, scored, oracles, report)
        result["diagnosis"] = diagnose(
            plan,
            raw,
            scored,
            report,
            archive.json("comparison/training-dispositions.json"),
            archive.json("comparison/feature-failures.json"),
            archive.json("comparison/adapter-training.json"),
        )
        encoding = archive.jsonl("comparison/encoding.jsonl")
        result["resources"] = audit_resources(report, encoding)
        result["candidate_capacity"] = candidate_capacity(
            plan, encoding, raw, archive.json("comparison/feature-failures.json")
        )
        result["adapter_unique_example_census"] = analyze_warmstart(
            plan,
            archive.json("comparison/training-dispositions.json"),
            archive.json("comparison/adapter-training.json"),
            report,
        )
        tests = archive.read("tests.log").decode("utf-8")
        matched = re.findall(r"(?m)^Ran (\d+) tests in [^\n]+\n\s*\nOK(?:\n|$)", tests)
        require(len(matched) == 1, "unresolved original regression result")
        result.update(
            zip_sha256=archive.sha256,
            verified_manifest_entries=archive.manifest_entries,
            generating_source=source,
            generating_tree=tree,
            original_passed_tests=int(matched[0]),
            feature_failures=archive.json("comparison/feature-failures.json"),
            adapter_training=archive.json("comparison/adapter-training.json"),
        )
        return result
    finally:
        archive.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--tree", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit_zip(args.archive, args.sha256, args.source, args.tree)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
