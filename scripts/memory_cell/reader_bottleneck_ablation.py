"""Execute real frozen Reader counterfactuals on the *authored development* event cut.

Five arms share task, model, decoding, budget, tool ACL and original source pool.
"declared_support" is author-declared, NOT an independently reviewed sufficient
oracle. A separate process opens labels only after every original answer is sealed.
No parametric training, posthoc citation insertion or production admission.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
from unittest.mock import patch

from event_memory_trial import LIMIT, read
from native import digest
from strong_rag_trial import (
    HISTORIC_PLAN_SHA,
    _journal_answers,
    _score,
    _stats,
    documents,
    dump,
    file_sha,
)
from reader_reference import MODELS

SCHEMA = "hepta.memory-cell.reader-bottleneck-original.v1"
SOURCE_ZIP = "31c6f191ecf62095779f7c9a5dd6c5b2f89c6ae408fe9c26f74e017a2d62c47a"
ORIGINAL_GENERATION = "bc76ac57ba972bf105c71ddd997cd215cec5df2e"
QWEN_INVENTORY = "f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225"
TIERS = ("smol-1.7b", "qwen-3b")
ARMS = ("none", "selected_k", "hybrid_k4", "declared_support", "minus_one")
MAX_SECONDS = 5400.0


def _commit():
    value = os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", "")
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("exact generating commit required")
    return value


def _plan(plan_dir):
    """Open only frozen public tasks + original sources, never targets."""
    locked = read(plan_dir / "plan.json", HISTORIC_PLAN_SHA)
    if (
        locked.get("schema") != "hepta.event-organization.plan.v1"
        or locked.get("token_limit") != LIMIT
        or len(locked.get("cases", [])) != 8
        or locked.get("human_sufficient_context_census", 0) != 0
    ):
        raise ValueError("unexpected authored development plan")
    originals = documents(
        read(plan_dir / "source-view.json", locked["source_view_sha"])
    )
    ids = [case["query"]["identity"] for case in locked["cases"]]
    if len(ids) != len(set(ids)) or len(ids) != 8:
        raise ValueError("duplicate or missing development question")
    return locked, originals


def selection(case, originals):
    """Deterministic, label-blind prerequisite deletion registered in source."""
    ids = case["candidate_ids"]
    if (
        len(ids) != len(set(ids))
        or digest(tuple(ids)) != case["candidate_digest"]
        or not 4 <= len(ids) <= 32
    ):
        raise ValueError("changed retrieval candidates")
    controls = case["controls"]
    declared = tuple(controls["program_support"]["selected"])
    retrieved = tuple(ids[:1])  # frozen selected_k=1 from original 40-call calibration
    hybrid = tuple(ids[:4])
    if (
        not 1 <= len(declared) <= 8
        or len(set(declared)) != len(declared)
        or tuple(controls["hybrid"]["selected"]) != hybrid
        or tuple(controls["without_prerequisite"]["selected"]) != declared[1:]
        or tuple(controls["empty"]["selected"]) != ()
        or any(key not in originals for key in set(ids) | set(declared))
        or any(originals[key].scope != case["query"]["scope"] for key in declared)
    ):
        raise ValueError("unregistered declared support or retrieved source")
    critical = declared[0]  # predeclared position, never chosen from model answers
    arms = {
        "none": (),
        "selected_k": retrieved,
        "hybrid_k4": hybrid,
        "declared_support": declared,
        "minus_one": tuple(key for key in declared if key != critical),
    }
    if set(arms) != set(ARMS) or critical in arms["minus_one"]:
        raise ValueError("critical premise was not removed")
    return arms, critical


def freeze_case(plan_dir, index):
    if type(index) is not int or not 0 <= index < 8:
        raise ValueError("unregistered case index")
    locked, originals = _plan(plan_dir)
    case = locked["cases"][index]
    arms, critical = selection(case, originals)
    frozen = dict(
        schema=SCHEMA,
        original_plan_sha256=HISTORIC_PLAN_SHA,
        original_generation=ORIGINAL_GENERATION,
        case_index=index,
        case_id=case["query"]["identity"],
        kind=case["kind"],
        candidate_digest=case["candidate_digest"],
        frontier_digest=digest(case["frontier"]),
        critical_declared_id=critical,
        arms={name: list(arms[name]) for name in ARMS},
        declared_support_not_human_reviewed=True,
        public_authored_development=True,
        selected_k_originally_frozen=1,
        target_labels_exposed=False,
        independent_semantic_review=False,
        production_accepted=False,
    )
    return case, originals, arms, frozen


def generate(plan_dir, model_dir, output, *, index, tier, stage_sha):
    """Seal a task plan before loading weights; fsync each real inference."""
    from event_reader_view import EventPresentationReader
    from runtime_preflight import capture_runtime, configure_torch
    import torch

    if tier not in TIERS:
        raise ValueError("only preregistered frozen reader tiers")
    commit = _commit()
    case, originals, arms, frozen = freeze_case(plan_dir, index)
    output.mkdir()
    dump(output / "case-plan.json", frozen)
    stage = read(model_dir / "stage.json", stage_sha)
    model = read(model_dir / "inventory.json", stage["inventory_sha256"])
    if (
        stage["tier"] != tier
        or stage["revision"] != MODELS[tier][1]
        or model["revision"] != MODELS[tier][1]
        or model["repository"] != MODELS[tier][0]
        or (tier == "qwen-3b" and model["inventory_digest"] != QWEN_INVENTORY)
    ):
        raise ValueError("staged reader differs from preregistered identity")
    threads = configure_torch(torch, bounded=False)
    if threads["effective_intra_op"] != 2:
        raise ValueError("CPU Reader requires exactly two intra-op threads")
    reader = EventPresentationReader(
        model_dir / "reader", expected_inventory=model["inventory_digest"]
    )
    dump(output / "runtime-preflight.json", capture_runtime(torch, bounded=False))
    rows = _journal_with_guard(
        reader,
        [case],
        originals,
        ARMS,
        lambda _case, arm: arms[arm],
        output / "raw-answers.jsonl",
        seed=digest((HISTORIC_PLAN_SHA, tier, SCHEMA)),
    )
    dump(
        output / "run.json",
        dict(
            schema=SCHEMA,
            source_commit=commit,
            original_generation=ORIGINAL_GENERATION,
            case_index=index,
            tier=tier,
            reader_identity=model["inventory_digest"],
            original_plan_sha256=HISTORIC_PLAN_SHA,
            case_plan_sha256=file_sha(output / "case-plan.json"),
            stage_sha256=stage_sha,
            runtime_preflight_sha256=file_sha(output / "runtime-preflight.json"),
            raw_sha256=file_sha(output / "raw-answers.jsonl"),
            attempts=len(rows),
            actual_successes=sum(r["status"] == "succeeded" for r in rows),
            arms=list(ARMS),
            learned_parameters=0,
            target_labels_exposed=False,
            production_accepted=False,
        ),
    )
    if any(row["status"] != "succeeded" for row in rows):
        raise ValueError("failed inference retained; no complete result")
    return len(rows)


def _journal_with_guard(reader, cases, originals, arms, selections, journal, *, seed):
    """Capture the ORIGINAL guard before patching its call site.

    Original answers are fsynced before the guard checks elapsed time.
    Only the CPU latency bound changes; Reader, prompt, evidence and decoder do not.
    """
    from strong_rag_trial import fail_if_unviable_reader as original_guard

    def bounded(row):
        return original_guard(row, max_seconds=MAX_SECONDS)

    with patch("strong_rag_trial.fail_if_unviable_reader", bounded):
        return _journal_answers(
            reader, cases, originals, arms, selections, journal, seed=seed
        )


def validate_row(row, case, arms, identity):
    if (
        row["question_id"] != case["query"]["identity"]
        or row["kind"] != case["kind"]
        or row["arm"] not in ARMS
        or row["selected"] != list(arms[row["arm"]])
        or row["candidate_digest"] != case["candidate_digest"]
        or row["status"] not in ("succeeded", "failed")
    ):
        raise ValueError("original answer drift or unknown arm")
    if row["status"] != "succeeded":
        return
    receipt = row["receipt"]
    if (
        receipt["reader_identity"] != identity
        or receipt.get("trainable_parameters") != 0
        or receipt.get("answer_postprocessed") is not False
        or receipt.get("semantic_citation_precision") is not None
        or receipt.get("independent_semantic_review") is not False
        or [item["original_id"] for item in receipt["delivered_evidence"]]
        != row["selected"]
        or type(receipt["input_tokens"]) is not int
        or not 0 < receipt["input_tokens"] <= LIMIT
    ):
        raise ValueError("reader identity, budget or actual delivery changed")


def _journal(path, count):
    """The exact original journal is required, not a scored/relabelled copy."""
    from strong_rag_shards import _read_rows

    return _read_rows(path, count)


def _paired(group, left, right):
    wins = losses = ties = missing = 0
    for entries in group.values():
        a, b = entries[left], entries[right]
        if a["status"] != "succeeded" or b["status"] != "succeeded":
            missing += 1
        else:
            diff = int(b["strict_task_success"]) - int(a["strict_task_success"])
            wins += diff > 0
            losses += diff < 0
            ties += diff == 0
    return dict(wins=wins, losses=losses, ties=ties, missing=missing)


def collect(plan_dir, observations, shards, output, *, expected_commit):
    """Check all 80 original calls and their seals BEFORE opening target labels."""
    if not re.fullmatch(r"[0-9a-f]{40}", expected_commit):
        raise ValueError("exact generating source required")
    locked, originals = _plan(plan_dir)
    all_rows = {tier: [] for tier in TIERS}
    identities = {}
    census = []
    for tier in TIERS:
        for index, case in enumerate(locked["cases"]):
            arms, _ = selection(case, originals)
            folder = shards / f"{tier}-{index}"
            frozen = read(
                folder / "case-plan.json", file_sha(folder / "case-plan.json")
            )
            _, _, _, expected = freeze_case(plan_dir, index)
            if frozen != expected:
                raise ValueError("task or critical premise changed after freeze")
            run = read(folder / "run.json", file_sha(folder / "run.json"))
            if (
                run["schema"] != SCHEMA
                or run["source_commit"] != expected_commit
                or run["case_index"] != index
                or run["tier"] != tier
                or run["original_generation"] != ORIGINAL_GENERATION
                or run["original_plan_sha256"] != HISTORIC_PLAN_SHA
                or run["case_plan_sha256"] != file_sha(folder / "case-plan.json")
                or run["raw_sha256"] != file_sha(folder / "raw-answers.jsonl")
                or run["runtime_preflight_sha256"]
                != file_sha(folder / "runtime-preflight.json")
                or run["attempts"] != len(ARMS)
                or run["actual_successes"] != len(ARMS)
                or run["arms"] != list(ARMS)
                or run["learned_parameters"] != 0
                or run["target_labels_exposed"] is not False
                or run["production_accepted"] is not False
            ):
                raise ValueError("missing or unsealed original model execution")
            identity = run["reader_identity"]
            if tier == "qwen-3b" and identity != QWEN_INVENTORY:
                raise ValueError("different Qwen reader weights")
            if tier in identities and identities[tier] != identity:
                raise ValueError("model identity drift across source shards")
            identities[tier] = identity
            rows = _journal(folder / "raw-answers.jsonl", len(ARMS))
            if [r["arm"] for r in rows] != list(ARMS):
                raise ValueError("changed arm order or duplicate inference")
            for row in rows:
                validate_row(row, case, arms, identity)
            all_rows[tier].extend(rows)
            census.append(dict(tier=tier, case=index, raw_sha256=run["raw_sha256"]))
    if identities.get(TIERS[0]) == identities.get(TIERS[1]):
        raise ValueError("reference model is identical to baseline")
    # The first target read is after complete original journals from both Readers.
    collection = read(
        observations / "collection.json",
        "be47e85e87692fa0c5036ebf1aa6090e040334b70719a9103e880960e6a60da9",
    )
    labels = read(observations / "labels.json", collection["files"]["labels.json"])
    test_ids = {c["query"]["identity"] for c in locked["cases"]}
    if (
        len(labels) != 16
        or {l["id"] for l in labels if l["id"] in test_ids} != test_ids
    ):
        raise ValueError("incomplete original test gold")
    targets = [l for l in labels if l["id"] in test_ids]
    stats, contrasts = {}, {}
    for tier in TIERS:
        rows = _score(all_rows[tier], targets, expected=sorted(test_ids), arms=ARMS)
        per_arm, group = _stats(rows, ARMS, sorted(test_ids))
        stats[tier] = per_arm
        contrasts[tier] = {
            "selected_to_declared": _paired(group, "selected_k", "declared_support"),
            "hybrid_to_declared": _paired(group, "hybrid_k4", "declared_support"),
            "ablated_to_declared": _paired(group, "minus_one", "declared_support"),
        }
    cross = {}
    smol = {(r["question_id"], r["arm"]): r for r in all_rows[TIERS[0]]}
    qwen = {(r["question_id"], r["arm"]): r for r in all_rows[TIERS[1]]}
    for arm in ARMS:
        cross[arm] = _paired(
            {
                key[0]: {"smol": smol[key], "qwen": qwen[key]}
                for key in smol
                if key[1] == arm
            },
            "smol",
            "qwen",
        )
    output.mkdir()
    dump(
        output / "report.json",
        dict(
            schema=SCHEMA,
            generating_source_commit=expected_commit,
            original_generation=ORIGINAL_GENERATION,
            original_plan_sha256=HISTORIC_PLAN_SHA,
            reader_identities=identities,
            calls_planned=len(TIERS) * 8 * len(ARMS),
            calls_completed=sum(len(r) for r in all_rows.values()),
            source_shards=census,
            reader_stats=stats,
            contrasts=contrasts,
            stronger_reader_diagnostic_only=cross,
            sufficient_evidence_human_reviewed=False,
            current_tasks_are_authored_development=True,
            independent_source_family_count=0,
            future_windows=0,
            real_project_task_qualification=False,
            learned_memory_tested=False,
            lifecycle_cost_usd=None,
            semantic_citation_precision=None,
            production_accepted=False,
        ),
    )
    # These original scored answers are not rewritten by the reporting tool.
    for tier in TIERS:
        dump(output / f"{tier}-scored.json", all_rows[tier])
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    g = sub.add_parser("generate")
    g.add_argument("plan_dir", type=Path)
    g.add_argument("model_dir", type=Path)
    g.add_argument("output", type=Path)
    g.add_argument("--case", type=int, required=True)
    g.add_argument("--tier", choices=TIERS, required=True)
    g.add_argument("--stage-sha", required=True)
    c = sub.add_parser("collect")
    c.add_argument("plan_dir", type=Path)
    c.add_argument("observations", type=Path)
    c.add_argument("shards", type=Path)
    c.add_argument("output", type=Path)
    c.add_argument("--generating-commit", required=True)
    args = parser.parse_args()
    if args.command == "generate":
        generate(
            args.plan_dir,
            args.model_dir,
            args.output,
            index=args.case,
            tier=args.tier,
            stage_sha=args.stage_sha,
        )
    else:
        collect(
            args.plan_dir,
            args.observations,
            args.shards,
            args.output,
            expected_commit=args.generating_commit,
        )


if __name__ == "__main__":
    main()
