"""Derive MemoryCell strict task outcomes from sealed original Reader answers.

Run only AFTER the original model-call journal was closed and independently
SHA-pinned. QA labels are read in a separate scoring phase, never passed to a
Reader, source selector, or optimizer. Exact-identifier scoring is NOT human
semantic entailment, evidence sufficiency, or independent program execution.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re

from factorial_evidence_gate import ARMS, CONDITIONS, COST_KEYS, READERS, sha
from memory_trial_admission import admit, bound_read, ensure, hexsha

ANSWER = re.compile(r"\s*([A-Za-z][A-Za-z0-9_.-]{0,127})(?:\s+\[E[1-9][0-9]*\])*\s*\Z")
ID_FIELDS = ("id", "arm", "condition", "reader")
COPY_FIELDS = (
    "id",
    "root",
    "arm",
    "condition",
    "reader",
    "reader_revision",
    "prompt_digest",
    "tool_policy_sha256",
    "write_snapshot_sha256",
    "memory_state_sha256",
    "source_digest",
    "raw_source_bytes",
    "tokens",
    "generated_tokens",
)
PROGRAM_FIELDS = (
    "program_exit_code",
    "program_test_count",
    "program_tests_passed",
    "tool_trace_sha256",
)
COMMITMENT_SCHEME = "hepta.memory-cell.answer-commitment.nonce-v2"
COMMITMENT_DOMAIN = b"hepta.memory-cell.exact-answer.v2\0"


def commit_identifier(value, nonce):
    """Bind a low-entropy identifier to a secret pre-exposure random nonce."""
    ensure(
        isinstance(value, str) and hexsha(nonce) and nonce != "0" * 64,
        "secret nonzero 256-bit label nonce required",
    )
    return hashlib.sha256(
        COMMITMENT_DOMAIN + bytes.fromhex(nonce) + b"\0" + value.encode("utf-8")
    ).hexdigest()


FORBIDDEN_ORIGINAL = frozenset(
    (
        "success",
        "verified",
        "target",
        "expected",
        "gold",
        "gold_answer",
        "strict_task_success",
        "label",
        "answer_sha256",
    )
)


def _answer(text):
    if not isinstance(text, str) or len(text.encode("utf-8")) > 65536:
        raise ValueError("missing or oversized original answer")
    match = ANSWER.fullmatch(text)
    return match.group(1) if match else None


def preflight_originals(plan, originals):
    """Check raw source/model/tool provenance before opening protected gold.

    A provisional all-false score matrix reuses the complete original-bound
    factorial audit. These provisional scores are NEVER research outcomes.
    """
    ensure(isinstance(originals, list), "original journal array required")
    shadow = []
    cases = {case["id"]: case for case in plan["cases"]}
    for original in originals:
        ensure(
            isinstance(original, dict)
            and not FORBIDDEN_ORIGINAL.intersection(original),
            "original journal leaked scoring outcome or target",
        )
        ensure(isinstance(original.get("answer"), str), "missing original answer")
        ensure(isinstance(original.get("cost"), dict), "original cost receipt required")
        row = {field: original[field] for field in COPY_FIELDS}
        row.update(
            plan_sha256=sha(plan),
            answer_digest=hashlib.sha256(original["answer"].encode()).hexdigest(),
            verified=True,
            success=False,
            cost=dict(original["cost"]),
            diagnostic_count=original["diagnostic_count"],
            recovery_success=original["recovery_success"],
        )
        if cases[original["id"]]["task"] == "program":
            row.update({field: original[field] for field in PROGRAM_FIELDS})
        shadow.append(row)
    receipt = admit(
        plan, originals, shadow, plan_pin=sha(plan), original_pin=sha(originals)
    )
    ensure(
        receipt["original_attempts"] == len(originals),
        "incomplete original prelabel verification",
    )
    return receipt


def score(plan, originals, labels):
    """Return complete recomputed scored matrix plus an unpromoted audit.

    `originals` must be original model receipts, not previously scored rows.
    The only accepted gold format is an exact precommitted output identifier.
    """
    ensure(
        isinstance(plan, dict)
        and plan.get("schema") == "hepta.memory-factorial.plan.v1",
        "preregistered factorial plan required",
    )
    ensure(
        isinstance(originals, list) and isinstance(labels, list),
        "original journal and protected label array required",
    )
    ensure(
        plan.get("answer_commitment_scheme") == COMMITMENT_SCHEME,
        "salted pre-exposure answer commitment required",
    )
    cases = plan.get("cases")
    ensure(isinstance(cases, list) and cases, "missing preregistered cases")
    by_case = {}
    for case in cases:
        ensure(
            isinstance(case, dict)
            and isinstance(case.get("id"), str)
            and case["id"] not in by_case
            and hexsha(case.get("answer_sha256")),
            "invalid or duplicate preregistered case",
        )
        by_case[case["id"]] = case
    expected = {
        (cid, arm, condition, reader)
        for cid in by_case
        for arm in ARMS
        for condition in CONDITIONS
        for reader in READERS
    }
    # Validate the original answer census BEFORE any label is consulted.
    seen = set()
    for row in originals:
        ensure(
            isinstance(row, dict) and not FORBIDDEN_ORIGINAL.intersection(row),
            "original journal leaked scoring outcome or target",
        )
        key = tuple(row.get(k) for k in ID_FIELDS)
        ensure(
            key in expected and key not in seen,
            "incomplete or duplicate original matrix",
        )
        seen.add(key)
        ensure(row.get("status") in ("succeeded", "failed"), "invalid original status")
        _answer(row.get("answer"))
        ensure(
            isinstance(row.get("cost"), dict) and set(row["cost"]) == set(COST_KEYS),
            "cost receipt absent (unknown categories must be null)",
        )
        ensure(
            type(row.get("diagnostic_count")) is int
            and row["diagnostic_count"] >= 0
            and type(row.get("recovery_success")) is bool,
            "execution counters absent",
        )
    ensure(seen == expected, "incomplete original generation census")
    # Validate every original receipt before accessing scorer-only target keys.
    preflight_originals(plan, originals)
    # Labels are a separate protected input; the plan contains their pre-exposure
    # SHA digests, not the literal answers. Any mismatch rejects the whole run.
    targets, nonces = {}, set()
    for item in labels:
        ensure(
            isinstance(item, dict) and set(item) == {"id", "expected", "nonce"},
            "protected label fields must be id, expected and nonce",
        )
        cid, value, nonce = item["id"], item["expected"], item["nonce"]
        ensure(
            isinstance(cid, str) and cid in by_case and cid not in targets,
            "unexpected or duplicate protected label",
        )
        ensure(
            hexsha(nonce) and nonce != "0" * 64 and nonce not in nonces,
            "absent, zero or reused protected answer nonce",
        )
        nonces.add(nonce)
        ensure(
            isinstance(value, str)
            and ANSWER.fullmatch(value) is not None
            and _answer(value) == value,
            "gold must be one exact identifier",
        )
        ensure(
            commit_identifier(value, nonce) == by_case[cid]["answer_sha256"],
            "gold differs from frozen plan",
        )
        targets[cid] = value
    ensure(set(targets) == set(by_case), "incomplete protected label census")
    rows, derived_successes = [], 0
    for original in originals:
        cid = original["id"]
        parsed = _answer(original["answer"])
        correct = original["status"] == "succeeded" and parsed == targets[cid]
        scored = {key: original[key] for key in COPY_FIELDS}
        scored.update(
            plan_sha256=sha(plan),
            answer_digest=hashlib.sha256(
                original["answer"].encode("utf-8")
            ).hexdigest(),
            verified=True,
            success=correct,
            cost=dict(original["cost"]),
            diagnostic_count=original["diagnostic_count"],
            recovery_success=original["recovery_success"],
        )
        if by_case[cid]["task"] == "program":
            ensure(
                all(field in original for field in PROGRAM_FIELDS),
                "program requires original execution receipt",
            )
            scored.update({field: original[field] for field in PROGRAM_FIELDS})
            correct = (
                correct
                and type(original["program_exit_code"]) is int
                and original["program_exit_code"] == 0
                and type(original["program_test_count"]) is int
                and original["program_test_count"] > 0
                and type(original["program_tests_passed"]) is int
                and original["program_tests_passed"] == original["program_test_count"]
                and hexsha(original["tool_trace_sha256"])
            )
            scored["success"] = correct
        derived_successes += correct
        rows.append(scored)
    report = admit(
        plan, originals, rows, plan_pin=sha(plan), original_pin=sha(originals)
    )
    report.update(
        strict_scoring="salted-precommitted-exact-identifier-with-program-receipt-v2",
        answer_commitment_scheme=COMMITMENT_SCHEME,
        salt_revealed_only_after_original_journal_verified=True,
        recomputed_strict_successes=derived_successes,
        labels_preexposure_hashes_checked=len(targets),
        generated_answer_mutation_permitted=False,
        original_success_flags_accepted=False,
        model_inference_performed=False,
        human_semantic_review_performed=False,
        program_execution_independently_replayed=False,
        production_qualified=False,
    )
    return rows, report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("plan", "original", "labels", "scored", "report"):
        p.add_argument("--" + name, type=Path, required=True)
    for name in ("plan", "original", "labels"):
        p.add_argument("--" + name + "-sha256", required=True)
    p.add_argument("--program-spec", type=Path)
    p.add_argument("--program-spec-sha256")
    p.add_argument("--program-receipts", type=Path)
    p.add_argument("--program-receipts-sha256")
    args = p.parse_args()
    ensure(
        not args.scored.exists() and not args.report.exists(),
        "never overwrite existing evidence",
    )
    # Original journal is validated before opening protected labels.
    plan = bound_read(args.plan, args.plan_sha256)
    originals = bound_read(args.original, args.original_sha256)
    ensure(sha(plan) and sha(originals), "canonical original journal required")
    # The CLI must not OPEN the protected file before completing raw preflight.
    preflight_originals(plan, originals)
    # Reexecute fixed program traces before private gold can be opened.
    supplied = (
        args.program_spec,
        args.program_spec_sha256,
        args.program_receipts,
        args.program_receipts_sha256,
    )
    ensure(
        all(v is None for v in supplied) or all(v is not None for v in supplied),
        "program manifest and original receipt pins must be supplied together",
    )
    if all(v is not None for v in supplied):
        from memory_trial_program_replay import audit as replay_program

        spec = bound_read(args.program_spec, args.program_spec_sha256)
        original_receipts = bound_read(
            args.program_receipts, args.program_receipts_sha256
        )
        replay = replay_program(plan, originals, spec, original_receipts)
    else:
        replay = None
    labels = bound_read(args.labels, args.labels_sha256)
    rows, audit = score(plan, originals, labels)
    audit["external_byte_pins"] = dict(
        plan=args.plan_sha256, original=args.original_sha256, labels=args.labels_sha256
    )
    audit["controlled_program_replay"] = replay
    audit["program_execution_independently_replayed"] = replay is not None
    audit["general_project_program_skill_qualified"] = False
    with args.scored.open("x", encoding="utf-8") as dest:
        json.dump(rows, dest, sort_keys=True, ensure_ascii=False, allow_nan=False)
        dest.write("\n")
    with args.report.open("x", encoding="utf-8") as dest:
        json.dump(
            audit, dest, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False
        )
        dest.write("\n")


if __name__ == "__main__":
    main()
