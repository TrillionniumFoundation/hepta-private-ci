"""Real frozen Reader source-inclusion factorial on ONE post-observed authored task.

Chosen AFTER observing the original Smol case-1 answers: NOT an independent
prospective task family, not parameter learning and not a production gate.
No gold labels are opened during generation or read-only answer auditing.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re

from native import digest
from reader_bottleneck_ablation import (
    _journal_with_guard,
    _plan,
    QWEN_INVENTORY,
    TIERS,
)
from reader_reference import MODELS
from strong_rag_trial import dump, file_sha

SCHEMA = "hepta.memory-cell.reader-case1-posthoc-distractor.v1"
CASE_ID = "controlled_cbfd4ba5"
SUPPORT = "event_cbfd4ba5_2"
HYBRID = (
    "event_cbfd4ba5_1",
    "event_cbfd4ba5_2",
    "event_cbfd4ba5_4",
    "event_cbfd4ba5_5",
)
SMOL_ID = "78ad24ab45f9620ada47df17a7de446f24ab4082fb993dd143ee30fce422acec"
ORIGINAL_SOURCE = "31c6f191ecf62095779f7c9a5dd6c5b2f89c6ae408fe9c26f74e017a2d62c47a"
ORIGINAL_PLAN = "9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897"
ORIGINAL_OBSERVER = "5b0dead3b766bdc5e56c09e024a8f82c50ccbdd6"
ORIGINAL_ARTIFACT = 11892028435
ARMS = tuple(f"support_plus_{n:03b}" for n in range(8))
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def strict(raw):
    def unique(items):
        found = {}
        for key, value in items:
            if key in found:
                raise ValueError("duplicate original JSON key")
            found[key] = value
        return found

    def bad(value):
        raise ValueError("nonfinite JSON: " + value)

    return json.loads(raw, object_pairs_hook=unique, parse_constant=bad)


def choices(case, originals):
    """Three binary distractor insertions, original Top-4 rank preserved."""
    docs = case["candidate_ids"]
    support = case["controls"]["program_support"]["selected"]
    hybrid = case["controls"]["hybrid"]["selected"]
    query = case["query"]
    if (
        query["identity"] != CASE_ID
        or query["scope"] != CASE_ID
        or case["kind"] != "correction"
        or support != [SUPPORT]
        or tuple(hybrid) != HYBRID
        or tuple(docs[:4]) != HYBRID
        or digest(tuple(docs)) != case["candidate_digest"]
        or any(key not in originals or originals[key].scope != CASE_ID for key in HYBRID)
    ):
        raise ValueError("post-observation selection changed from original public task")
    other = [key for key in HYBRID if key != SUPPORT]
    masks = {}
    for n, arm in enumerate(ARMS):
        keep = {SUPPORT} | {other[bit] for bit in range(3) if n & (1 << bit)}
        masks[arm] = tuple(key for key in HYBRID if key in keep)
    if (
        len(set(masks.values())) != 8
        or masks[ARMS[0]] != (SUPPORT,)
        or masks[ARMS[-1]] != HYBRID
        or any(SUPPORT not in selected for selected in masks.values())
    ):
        raise ValueError("mask identities are not frozen")
    return masks


def freeze(plan_directory):
    original, docs = _plan(plan_directory)
    case = original["cases"][1]
    selection = choices(case, docs)
    manifest = dict(
        schema=SCHEMA,
        original_source_zip_sha256=ORIGINAL_SOURCE,
        authored_plan_sha256=ORIGINAL_PLAN,
        originally_observed_generating_commit=ORIGINAL_OBSERVER,
        originally_observed_artifact=ORIGINAL_ARTIFACT,
        case_id=CASE_ID,
        case_index=1,
        case_kind="correction",
        candidate_digest=case["candidate_digest"],
        frontier_digest=digest(case["frontier"]),
        arms=list(ARMS),
        selected={arm: list(selection[arm]) for arm in ARMS},
        registered_after_observing_original_answer=True,
        author_declared_support_not_human_reviewed=True,
        independent_source_family_count=0,
        original_eighty_call_matrix_membership=False,
        not_statistically_independent=True,
        original_reader_prompt_and_decoder_unchanged=True,
        target_labels_opened=False,
        trainable_parameters=0,
        production_accepted=False,
    )
    return case, docs, selection, manifest


def generate(plan, model_dir, out, *, tier, stage_sha):
    """Use the already-proven BF16 reader + 2048/64 budgets, fsync each answer."""
    from event_memory_trial import read
    from event_reader_view import EventPresentationReader
    from runtime_preflight import capture_runtime, configure_torch
    import torch

    commit = os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", "")
    if (
        not HEX40.fullmatch(commit)
        or tier not in TIERS
        or not HEX64.fullmatch(stage_sha)
    ):
        raise ValueError("unregistered generator checkout or model stage")
    case, docs, selection, manifest = freeze(plan)
    out.mkdir()
    dump(out / "case-plan.json", manifest)
    staged = read(model_dir / "stage.json", stage_sha)
    model = read(model_dir / "inventory.json", staged["inventory_sha256"])
    required_id = SMOL_ID if tier == "smol-1.7b" else QWEN_INVENTORY
    if (
        staged["tier"] != tier
        or staged["revision"] != MODELS[tier][1]
        or model["revision"] != MODELS[tier][1]
        or model["repository"] != MODELS[tier][0]
        or model["inventory_digest"] != required_id
    ):
        raise ValueError("actual frozen original Reader weights differ")
    if configure_torch(torch, bounded=False)["effective_intra_op"] != 2:
        raise ValueError("original Reader CPU thread budget changed")
    reader = EventPresentationReader(
        model_dir / "reader", expected_inventory=required_id
    )
    dump(out / "runtime-preflight.json", capture_runtime(torch, bounded=False))
    rows = _journal_with_guard(
        reader,
        [case],
        docs,
        ARMS,
        lambda unused_case, arm: selection[arm],
        out / "raw-answers.jsonl",
        seed=digest((ORIGINAL_PLAN, commit, tier, SCHEMA)),
    )
    dump(
        out / "run.json",
        dict(
            schema=SCHEMA,
            generating_commit=commit,
            tier=tier,
            reader_identity=required_id,
            authored_plan_sha256=ORIGINAL_PLAN,
            frozen_case_sha256=file_sha(out / "case-plan.json"),
            stage_sha256=stage_sha,
            runtime_preflight_sha256=file_sha(out / "runtime-preflight.json"),
            raw_answers_sha256=file_sha(out / "raw-answers.jsonl"),
            arms=list(ARMS),
            attempted=len(rows),
            succeeded=sum(row["status"] == "succeeded" for row in rows),
            gold_labels_opened=False,
            original_eighty_call_matrix_membership=False,
            learned_parameters=0,
            production_accepted=False,
        ),
    )
    if len(rows) != 8 or any(row["status"] != "succeeded" for row in rows):
        raise ValueError("incomplete genuine generation; original rows retained")
    return len(rows)


def audit_rows(files, *, case, docs, tier, checkout):
    """Only count source-identity-verified original calls, never score gold."""
    if tier not in TIERS or not HEX40.fullmatch(checkout):
        raise ValueError("exact cohort and frozen Reader required")
    selected = choices(case, docs)
    if "case-plan.json" not in files:
        if "raw-answers.jsonl" in files or "run.json" in files:
            raise ValueError("unregistered model answers without frozen task")
        return dict(tier=tier, attempted=0, succeeded=0, complete=False)
    manifest = freeze_manifest_for_case(case, selected)
    if strict(files["case-plan.json"]) != manifest:
        raise ValueError("changed registered distractor intervention")
    raw = files.get("raw-answers.jsonl")
    if raw is None:
        if "run.json" in files:
            raise ValueError("run manifest with no answer journal")
        return dict(tier=tier, attempted=0, succeeded=0, complete=False)
    if not raw.endswith(b"\n"):
        raise ValueError("truncated original answer journal")
    answers = [strict(line) for line in raw.splitlines()]
    if not 1 <= len(answers) <= 8:
        raise ValueError("original model attempt count changed")
    inventory = SMOL_ID if tier == "smol-1.7b" else QWEN_INVENTORY
    for arm, record in zip(ARMS, answers):
        if (
            record.get("question_id") != CASE_ID
            or record.get("kind") != "correction"
            or record.get("arm") != arm
            or record.get("candidate_digest") != case["candidate_digest"]
            or record.get("selected") != list(selected[arm])
            or record.get("status") not in ("succeeded", "failed")
            or "strict_task_success" in record
        ):
            raise ValueError("shard changed arm, task or opened gold labels")
        if record["status"] == "failed":
            continue
        receipt = record.get("receipt")
        if (
            not isinstance(receipt, dict)
            or receipt.get("reader_identity") != inventory
            or receipt.get("view_profile")
            != "hepta.controlled-event.schema-expansion.v1"
            or receipt.get("query_digest") != digest(case["query"])
            or receipt.get("token_limit") != 2048
            or receipt.get("trainable_parameters") != 0
            or receipt.get("answer_postprocessed") is not False
            or receipt.get("production_accepted") is not False
            or type(receipt.get("input_tokens")) is not int
            or not 0 < receipt["input_tokens"] <= 2048
            or type(receipt.get("generated_tokens")) is not int
            or not 0 < receipt["generated_tokens"] <= 64
            or any(not HEX64.fullmatch(str(receipt.get(k))) for k in (
                "input_ids_digest",
                "generated_ids_digest",
                "reader_profile",
            ))
            or type(receipt.get("seconds")) not in (int, float)
            or not math.isfinite(receipt["seconds"])
            or receipt["seconds"] < 0
            or not isinstance(record.get("answer"), str)
            or not record["answer"].strip()
        ):
            raise ValueError("non-original or unbounded Reader answer receipt")
        delivered = receipt.get("delivered_evidence")
        if (
            not isinstance(delivered, list)
            or [item.get("original_id") for item in delivered] != list(selected[arm])
            or any(
                item.get("excerpt") != docs[item["original_id"]].content
                for item in delivered
            )
        ):
            raise ValueError("delivered original evidence was changed")
        citation = record.get("citation_audit")
        if (
            not isinstance(citation, dict)
            or not isinstance(citation.get("request"), dict)
            or citation["request"].get("query_id") != CASE_ID
            or citation["request"].get("prompt_digest")
            != receipt["input_ids_digest"]
            or citation["request"].get("answer") != record["answer"]
            or citation.get("semantic_precision") is not None
        ):
            raise ValueError("original answer/citation request drift")
    runner = files.get("run.json")
    if runner is not None:
        receipt = strict(runner)
        if (
            receipt.get("schema") != SCHEMA
            or receipt.get("generating_commit") != checkout
            or receipt.get("tier") != tier
            or receipt.get("reader_identity") != inventory
            or receipt.get("authored_plan_sha256") != ORIGINAL_PLAN
            or receipt.get("frozen_case_sha256")
            != hashlib.sha256(files["case-plan.json"]).hexdigest()
            or receipt.get("raw_answers_sha256")
            != hashlib.sha256(raw).hexdigest()
            or receipt.get("attempted") != len(answers)
            or receipt.get("succeeded")
            != sum(row["status"] == "succeeded" for row in answers)
            or receipt.get("gold_labels_opened") is not False
            or receipt.get("original_eighty_call_matrix_membership") is not False
            or receipt.get("learned_parameters") != 0
            or receipt.get("production_accepted") is not False
        ):
            raise ValueError("generator run receipt changed or forged")
    return dict(
        tier=tier,
        attempted=len(answers),
        succeeded=sum(row["status"] == "succeeded" for row in answers),
        complete=runner is not None and len(answers) == 8
        and all(row["status"] == "succeeded" for row in answers),
        total_input_tokens=sum(
            row["receipt"]["input_tokens"]
            for row in answers if row["status"] == "succeeded"
        ),
        measured_inference_seconds=sum(
            row["receipt"]["seconds"]
            for row in answers if row["status"] == "succeeded"
        ),
        original_answers=[
            dict(
                arm=row["arm"], selected=row["selected"], status=row["status"],
                answer=row.get("answer"),
            ) for row in answers
        ],
        post_observation_development_diagnostic=True,
        learned_memory_gain=None,
        production_accepted=False,
    )


def freeze_manifest_for_case(case, selected):
    """The only evidence selectors are declared original source IDs."""
    return dict(
        schema=SCHEMA,
        original_source_zip_sha256=ORIGINAL_SOURCE,
        authored_plan_sha256=ORIGINAL_PLAN,
        originally_observed_generating_commit=ORIGINAL_OBSERVER,
        originally_observed_artifact=ORIGINAL_ARTIFACT,
        case_id=CASE_ID,
        case_index=1,
        case_kind="correction",
        candidate_digest=case["candidate_digest"],
        frontier_digest=digest(case["frontier"]),
        arms=list(ARMS),
        selected={arm: list(selected[arm]) for arm in ARMS},
        registered_after_observing_original_answer=True,
        author_declared_support_not_human_reviewed=True,
        independent_source_family_count=0,
        original_eighty_call_matrix_membership=False,
        not_statistically_independent=True,
        original_reader_prompt_and_decoder_unchanged=True,
        target_labels_opened=False,
        trainable_parameters=0,
        production_accepted=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    gate = commands.add_parser("freeze")
    gate.add_argument("public_plan", type=Path)
    gate.add_argument("report", type=Path)
    gen = commands.add_parser("generate")
    gen.add_argument("public_plan", type=Path)
    gen.add_argument("model", type=Path)
    gen.add_argument("output", type=Path)
    gen.add_argument("--tier", choices=TIERS, required=True)
    gen.add_argument("--stage-sha", required=True)
    audit = commands.add_parser("audit")
    audit.add_argument("public_plan", type=Path)
    audit.add_argument("original_shard", type=Path)
    audit.add_argument("output", type=Path)
    audit.add_argument("--tier", choices=TIERS, required=True)
    audit.add_argument("--checkout", required=True)
    args = parser.parse_args()
    case, originals, _, manifest = freeze(args.public_plan)
    if args.command == "freeze":
        dump(args.report, manifest)
        return
    if args.command == "generate":
        generate(
            args.public_plan, args.model, args.output,
            tier=args.tier, stage_sha=args.stage_sha
        )
        return
    directory = args.original_shard
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("original shard directory is missing")
    files = {
        p.name: p.read_bytes()
        for p in directory.iterdir()
        if p.is_file() and not p.is_symlink()
    }
    if files.get("checkout-commit.txt", b"").decode().strip() != args.checkout:
        raise ValueError("mismatched original generator checkout")
    if "host-gate.json" not in files:
        raise ValueError("missing true BF16 host evidence")
    host = strict(files["host-gate.json"])
    if (
        host.get("schema") != "hepta.memory-strong-rag.bf16-host-gate.v1"
        or type(host.get("host_eligible")) is not bool
        or host.get("new_model_calls") != 0
        or host.get("production_accepted") is not False
        or (not host["host_eligible"] and "raw-answers.jsonl" in files)
    ):
        raise ValueError("unqualified BF16 host provenance")
    result = audit_rows(
        files, case=case, docs=originals, tier=args.tier,
        checkout=args.checkout
    )
    result.update(
        generating_commit=args.checkout,
        original_eighty_call_trial_unchanged=True,
        actual_independent_human_review=False,
        host_eligible=host["host_eligible"],
        source_plan_sha256=ORIGINAL_PLAN,
    )
    dump(args.output, result)


if __name__ == "__main__":
    main()
