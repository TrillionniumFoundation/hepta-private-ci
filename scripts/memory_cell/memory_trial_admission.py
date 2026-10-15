"""Evidence-bound four-stage MemoryCell diagnosis; never issues production approval.

The scorer consumes original model outputs, source receipts, and preregistered
metadata. Hashes provide byte identity, not independent reviewer authority.
No reader, optimizer, retriever or production owner is imported or invoked.
"""

import argparse
from collections import defaultdict
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path

from factorial_evidence_gate import (
    ARMS,
    CONDITIONS,
    COST_KEYS,
    READERS,
    TASKS,
    analyze as legacy_analyze,
    canonical,
    sha,
)

HEX = set("0123456789abcdef")
KEYS = ("id", "arm", "condition", "reader")


def ensure(ok, reason):
    if not ok:
        raise ValueError(reason)


def hexsha(value):
    return isinstance(value, str) and len(value) == 64 and set(value) <= HEX


def utc(value):
    ensure(isinstance(value, str) and value.endswith("Z"), "UTC timestamp required")
    try:
        time = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid frozen time") from exc
    ensure(
        time.tzinfo is not None and time.utcoffset().total_seconds() == 0,
        "UTC required",
    )
    return time


def bound_read(path, expected):
    path = Path(path)
    ensure(hexsha(expected), "external SHA-256 pin required")
    ensure(
        path.is_file()
        and not path.is_symlink()
        and 0 < path.stat().st_size <= 32 * 1024**2,
        "bounded non-symlink evidence file required",
    )
    raw = path.read_bytes()
    ensure(
        hashlib.sha256(raw).hexdigest() == expected,
        "original evidence file hash mismatch",
    )

    def unique(pairs):
        result = {}
        for k, v in pairs:
            ensure(k not in result, "duplicate JSON field")
            result[k] = v
        return result

    def constant(value):
        raise ValueError("nonfinite JSON literal: " + value)

    return json.loads(raw, object_pairs_hook=unique, parse_constant=constant)


def paired(rows, left, right, *, reader="frozen", condition="hybrid"):
    wins = losses = ties = 0
    by_root = defaultdict(list)
    for id_, case in rows.items():
        a = case[(left, condition, reader)]["success"]
        b = case[(right, condition, reader)]["success"]
        wins += a and not b
        losses += b and not a
        ties += a == b
        by_root[case["root"]].append(int(a) - int(b))
    root_delta = {root: sum(v) / len(v) for root, v in sorted(by_root.items())}
    return dict(
        wins=wins,
        losses=losses,
        ties=ties,
        case_delta=(wins - losses) / len(rows),
        root_macro_delta=sum(root_delta.values()) / len(root_delta),
        root_effects=root_delta,
        statistical_interval=None,
    )


def admit(plan, originals, scored, *, plan_pin, original_pin):
    """Require a complete matched matrix, frozen writes and original answer bytes."""
    ensure(
        hexsha(plan_pin) and sha(plan) == plan_pin,
        "external preregistration pin mismatch",
    )
    ensure(
        hexsha(original_pin) and sha(originals) == original_pin,
        "external original-journal pin mismatch",
    )
    ensure(plan.get("schema") == "hepta.memory-factorial.plan.v1", "unsupported plan")
    registered_at = utc(plan.get("cutoff"))
    ensure(
        isinstance(plan.get("reader_revisions"), dict)
        and set(plan["reader_revisions"]) == set(READERS),
        "frozen reader identities missing",
    )
    ensure(
        all(isinstance(v, str) and v for v in plan["reader_revisions"].values())
        and len(set(plan["reader_revisions"].values())) == 2,
        "reference Reader must be distinct",
    )
    for field in ("prompt_template_sha256", "tool_policy_sha256"):
        ensure(hexsha(plan.get(field)), "unfrozen " + field)
    ensure(
        type(plan.get("reader_budget", {}).get("total_tokens")) is int
        and 0 < plan["reader_budget"]["total_tokens"] <= 32768,
        "invalid common token budget",
    )
    ensure(isinstance(plan.get("cases"), list), "frozen cases required")
    ensure(
        isinstance(plan.get("arm_snapshots"), dict)
        and set(plan["arm_snapshots"]) == set(ARMS),
        "missing arm parameter snapshots",
    )
    for arm, state in plan["arm_snapshots"].items():
        ensure(
            isinstance(state, dict) and hexsha(state.get("sha256")),
            "invalid frozen arm parameter digest",
        )
        ensure(
            registered_at <= utc(state.get("frozen_at")),
            "arm parameters frozen before preregistration",
        )
        if arm in ("learned_read", "knowledge", "knowledge_only"):
            ensure(
                type(state.get("train_steps")) is int
                and state["train_steps"] > 0
                and hexsha(state.get("training_source_sha256")),
                "learned parameter lacks source-only training receipt",
            )
    ensure(
        plan["arm_snapshots"]["knowledge"]["sha256"]
        == plan["arm_snapshots"]["knowledge_only"]["sha256"],
        "knowledge-only must use the same parameter module",
    )
    for case in plan["cases"]:
        ensure(
            hexsha(case.get("write_snapshot_sha256")), "missing frozen write snapshot"
        )
        ensure(
            registered_at
            <= utc(case.get("write_completed_at"))
            < utc(case.get("task_revealed_at")),
            "write must be frozen before task exposure",
        )
        ensure(
            all(
                utc(state["frozen_at"]) < utc(case["task_revealed_at"])
                for state in plan["arm_snapshots"].values()
            ),
            "parameter training after task exposure",
        )
    ensure(
        isinstance(originals, list) and isinstance(scored, list),
        "original and scored arrays required",
    )
    # Bind model revisions before aggregate factor analysis so a swapped
    # Reader cannot be masked by a less specific across-arm error.
    for original in originals:
        ensure(isinstance(original, dict), "invalid original generation receipt")
        reader = original.get("reader")
        ensure(
            reader in READERS
            and original.get("reader_revision") == plan["reader_revisions"][reader],
            "reader model revision drift",
        )
    base = legacy_analyze(plan, scored)
    expected = {
        (case["id"], arm, condition, reader)
        for case in plan["cases"]
        for arm in ARMS
        for condition in CONDITIONS
        for reader in READERS
    }
    raw = {}
    model_call_ids = set()
    for row in originals:
        ensure(isinstance(row, dict), "invalid original generation receipt")
        key = tuple(row.get(k) for k in KEYS)
        ensure(
            key in expected and key not in raw, "unknown or duplicate original answer"
        )
        ensure(
            isinstance(row.get("answer"), str)
            and len(row["answer"].encode("utf-8")) <= 65536,
            "missing or oversized actual answer",
        )
        for field in (
            "source_digest",
            "prompt_digest",
            "tool_policy_sha256",
            "write_snapshot_sha256",
        ):
            ensure(hexsha(row.get(field)), "unbound original " + field)
        ensure(
            row.get("status") in ("succeeded", "failed"),
            "missing original attempt status",
        )
        ensure(
            isinstance(row.get("model_call_id"), str) and row["model_call_id"],
            "original model call identity absent",
        )
        ensure(
            row["model_call_id"] not in model_call_ids,
            "duplicate original model call receipt",
        )
        model_call_ids.add(row["model_call_id"])
        raw[key] = row
    ensure(set(raw) == expected, "incomplete original generation census")
    cases = {case["id"]: case for case in plan["cases"]}
    matrix = {id_: {"root": case["root"]} for id_, case in cases.items()}
    no_source_sha = hashlib.sha256(b"").hexdigest()
    for row in scored:
        key = tuple(row[k] for k in KEYS)
        original = raw[key]
        case = cases[row["id"]]
        ensure(
            row["reader_revision"]
            == plan["reader_revisions"][row["reader"]]
            == original.get("reader_revision"),
            "reader model revision drift",
        )
        ensure(
            row["prompt_digest"]
            == original["prompt_digest"]
            == plan["prompt_template_sha256"],
            "matched prompt template drift",
        )
        ensure(
            original["tool_policy_sha256"]
            == plan["tool_policy_sha256"]
            == row.get("tool_policy_sha256"),
            "tool permission asymmetry",
        )
        ensure(
            original["write_snapshot_sha256"]
            == case["write_snapshot_sha256"]
            == row.get("write_snapshot_sha256"),
            "post-task write or snapshot substitution",
        )
        ensure(
            row.get("memory_state_sha256")
            == original.get("memory_state_sha256")
            == plan["arm_snapshots"][row["arm"]]["sha256"],
            "unfrozen parameter state or policy",
        )
        if original["status"] != "succeeded":
            ensure(not row["success"], "failed model call promoted to task success")
        ensure(
            row["answer_digest"]
            == hashlib.sha256(original["answer"].encode()).hexdigest(),
            "scored answer differs from actual model output",
        )
        ensure(
            row["source_digest"] == original["source_digest"],
            "original evidence delivery modified after inference",
        )
        ensure(
            type(row.get("raw_source_bytes")) is int
            and row["raw_source_bytes"] >= 0
            and original.get("raw_source_bytes") == row["raw_source_bytes"],
            "source byte accounting missing",
        )
        if row["condition"] == "none" or row["arm"] == "knowledge_only":
            ensure(
                row["raw_source_bytes"] == 0 and row["source_digest"] == no_source_sha,
                "no-evidence or knowledge-only arm leaked raw source",
            )
        ensure(row["tokens"] == original.get("tokens"), "reader token receipt drift")
        ensure(
            type(row.get("generated_tokens")) is int
            and 0 <= row["generated_tokens"] <= plan["reader_budget"]["total_tokens"],
            "generated token receipt absent",
        )
        ensure(
            row["generated_tokens"] == original.get("generated_tokens"),
            "original generated token count drift",
        )
        ensure(
            row["tokens"] + row["generated_tokens"]
            <= plan["reader_budget"]["total_tokens"],
            "total input and output exceeds matched budget",
        )
        if case["task"] == "program":
            ensure(
                type(row.get("program_exit_code")) is int
                and type(row.get("program_test_count")) is int
                and row["program_test_count"] > 0
                and type(row.get("program_tests_passed")) is int
                and 0 <= row["program_tests_passed"] <= row["program_test_count"],
                "program verification must execute actual tests",
            )
            for bound in (
                "program_exit_code",
                "program_test_count",
                "program_tests_passed",
            ):
                ensure(
                    original.get(bound) == row[bound],
                    "program result changed after original execution",
                )
            ensure(
                not row["success"]
                or (
                    row["program_exit_code"] == 0
                    and row["program_tests_passed"] == row["program_test_count"]
                ),
                "text-only program answer falsely counted as success",
            )
            ensure(
                hexsha(row.get("tool_trace_sha256"))
                and row["tool_trace_sha256"] == original.get("tool_trace_sha256"),
                "missing actual program execution receipt",
            )
        ensure(
            row["cost"] == original.get("cost"), "cost changed from original receipt"
        )
        ensure(
            row["diagnostic_count"] == original.get("diagnostic_count")
            and row["recovery_success"] == original.get("recovery_success"),
            "execution counters changed from original receipt",
        )
        for cost_name in COST_KEYS:
            ensure(
                row["cost"][cost_name] is None or math.isfinite(row["cost"][cost_name]),
                "invalid cost value",
            )
        matrix[row["id"]][(row["arm"], row["condition"], row["reader"])] = row
    # Reader capacity is tested on byte-identical evidence across model tiers;
    # no performance improvement may be assigned to a MemoryCell model switch.
    for id_, case in matrix.items():
        for arm in ARMS:
            for condition in CONDITIONS:
                frozen = case[(arm, condition, "frozen")]
                reference = case[(arm, condition, "reference")]
                ensure(
                    frozen["source_digest"] == reference["source_digest"]
                    and frozen["raw_source_bytes"] == reference["raw_source_bytes"],
                    "reference reader received different evidence",
                )
        for reader in READERS:
            digest_set = {
                case[(arm, "hybrid", reader)]["prompt_digest"] for arm in ARMS
            }
            ensure(len(digest_set) == 1, "reader prompt changed across memory arms")
    # Parameter-memory credit requires the same delivered evidence in all
    # four conditions on both Reader tiers, not only frozen Reader / hybrid.
    mismatched_knowledge = [
        id_
        for id_, case in matrix.items()
        if any(
            (
                case[("knowledge", condition, reader)]["source_digest"],
                case[("knowledge", condition, reader)]["raw_source_bytes"],
            )
            != (
                case[("event_graph", condition, reader)]["source_digest"],
                case[("event_graph", condition, reader)]["raw_source_bytes"],
            )
            for reader in READERS
            for condition in CONDITIONS
        )
    ]
    reader_cases = {}
    for id_, case in matrix.items():
        frozen = case[("hybrid_rag", "oracle", "frozen")]["success"]
        reference = case[("hybrid_rag", "oracle", "reference")]["success"]
        hybrid = case[("hybrid_rag", "hybrid", "frozen")]["success"]
        ablated = case[("hybrid_rag", "ablated", "frozen")]["success"]
        reader_cases[id_] = dict(
            task=cases[id_]["task"],
            root=case["root"],
            adequate_reader_on_claimed_oracle=frozen,
            reference_helps=reference and not frozen,
            neither_reader_solves_claimed_oracle=not frozen and not reference,
            retrieval_or_packing_bottleneck=frozen and not hybrid,
            deletion_not_proven_necessary=frozen and ablated,
        )
    comparisons = {
        "organization_vs_hybrid": paired(matrix, "event_graph", "hybrid_rag"),
        "learned_read_vs_organization": paired(matrix, "learned_read", "event_graph"),
        "knowledge_vs_organization": paired(matrix, "knowledge", "event_graph"),
    }
    for item in base["arms"].values():
        for reader in item.values():
            for cell in reader.values():
                cell["cost_is_observation_sum_not_total_lifecycle_cost"] = True
    base.update(
        schema="hepta.memory-factorial.original-bound-audit.v2",
        preregistration_sha256=plan_pin,
        original_journal_sha256=original_pin,
        original_attempts=len(raw),
        self_asserted_review_not_independent_certification=True,
        chronology_verified_against_supplied_times_not_external_commit_history=True,
        observed_reader_diagnosis=reader_cases,
        paired_source_root_comparisons=comparisons,
        knowledge_same_evidence_comparable=not mismatched_knowledge,
        knowledge_evidence_mismatch_case_ids=mismatched_knowledge,
        stage_gates=dict(
            reader_capability="diagnostic_only_unreviewed_sufficiency",
            nonparametric="within_registered_source_roots_only",
            learned_policy="reject_unless_outperforms_organized_on_new_roots",
            parametric_knowledge=(
                "evidence_confounded"
                if mismatched_knowledge
                else "same_evidence_diagnostic_only"
            ),
            long_term="blocked_no_deployed_retention_revocation_and_recovery_receipt",
        ),
        amortized_tco=None,
        full_lifecycle_cost=dict(
            extraction=None,
            indexing=None,
            parameter_training=None,
            raw_evidence_storage=None,
            query_observed_only=True,
            maintenance=None,
            revocation=None,
            recovery=None,
            reusable_query_counts=(1, 10, 100, 1000),
            total_by_reuse=None,
        ),
        missing_lifecycle_cost_provenance=True,
        verified_model_execution_by_independent_runner=False,
        independent_human_oracle_certified=False,
        production_qualified=False,
    )
    return base


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("plan", "original", "scored", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--original-sha256", required=True)
    args = parser.parse_args()
    plan = bound_read(args.plan, args.plan_sha256)
    originals = bound_read(args.original, args.original_sha256)
    # Scored records must be original answer-bound, not a detached summary.
    ensure(
        args.scored.is_file()
        and not args.scored.is_symlink()
        and 0 < args.scored.stat().st_size <= 32 * 1024**2,
        "bounded scored records required",
    )
    scored_raw = args.scored.read_bytes()

    def unique_scored(pairs):
        record = {}
        for key, value in pairs:
            ensure(key not in record, "duplicate scored JSON field")
            record[key] = value
        return record

    def invalid_constant(value):
        raise ValueError("nonfinite scored JSON number: " + value)

    scored = json.loads(
        scored_raw, object_pairs_hook=unique_scored, parse_constant=invalid_constant
    )
    result = admit(
        plan, originals, scored, plan_pin=sha(plan), original_pin=sha(originals)
    )
    result["externally_pinned_file_sha256"] = dict(
        plan=args.plan_sha256, original=args.original_sha256
    )
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(
            result,
            output,
            sort_keys=True,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        output.write("\n")


if __name__ == "__main__":
    main()
