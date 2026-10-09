"""Recompute a completed masked-span execution; not independent acceptance.

The auditor checks the entire frozen question/arm census, original window bytes,
unchanged answers, generator identity and registered paired diagnostic metrics.
It neither judges entailment nor uses labels to modify model answers.
"""

import argparse
import hashlib
import json
from pathlib import Path

from native import digest
from selector_answering import ARMS, GENERATION, choose
from selector_answer_metrics import matched_report
from selector_windows import Window
from span_supervision import strict_json

PROFILE = "external-span-masked-evidence-only-v1"
MAX_BYTES = 128 * 1024 * 1024


def load(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("regular audit input required")
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("audit input byte bound")
    return strict_json(raw), raw


def check_census(raw, scored, plan):
    expected = {
        (phase, qid, arm)
        for phase, queries in plan["questions"].items()
        if phase not in ("train", "select")
        for qid in queries
        for arm in ARMS
    }
    key = lambda row: (row["phase"], row["question_id"], row["arm"])
    if (
        len(raw) != len(expected)
        or len(scored) != len(expected)
        or {key(r) for r in raw} != expected
        or {key(r) for r in scored} != expected
    ):
        raise ValueError("incomplete or duplicated planned answer census")
    by_key = {key(row): row for row in scored}
    for row in raw:
        other = by_key[key(row)]
        if any(k not in other or other[k] != v for k, v in row.items()):
            raise ValueError("scoring modified an original answer or receipt")
    return expected


def check_same_input_outputs(raw):
    outputs = {}
    for row in raw:
        if row["status"] != "succeeded":
            continue
        receipt = row["receipt"]
        key = (
            receipt["generator_identity"],
            receipt["generator_profile"],
            receipt["input_ids_digest"],
        )
        value = (row["answer"], receipt["generated_ids_digest"])
        if key in outputs and outputs[key] != value:
            raise ValueError(
                "same deterministic generator input produced arm-dependent output"
            )
        outputs[key] = value
    return len(outputs)


def audit(experiment, expected_source):
    report, _ = load(experiment / "report.json")
    plan, _ = load(experiment / "preregistered.json")
    raw, raw_bytes = load(experiment / "raw-answers.json")
    scored, _ = load(experiment / "scored-answers.json")
    head, _ = load(experiment / "head.json")
    pools, _ = load(experiment / "candidate-pools.json")
    views, _ = load(experiment / "source-views.json")
    labels, _ = load(experiment / "training-window-labels.json")
    selection, _ = load(experiment / "selection.json")
    if (
        plan["source_commit"] != expected_source
        or plan["training_profile"] != PROFILE
        or report["training_profile"] != PROFILE
        or plan["generator_config"] != GENERATION
        or plan["null_parameters_optimized"] is not False
        or report["head_unchanged_during_evaluation"] is not True
        or report["native_transfer_parameter_updates"] != 0
        or report["native_transfer_recalibration"] is not False
        or report["production_accepted"] is not False
        or report["superiority_claim"] is not False
    ):
        raise ValueError("execution source, protocol or acceptance drift")
    expected = check_census(raw, scored, plan)
    expected_queries = list(dict.fromkeys(q for _, q, _ in sorted(expected)))
    recomputed = matched_report(scored, expected_queries)
    if any(report[k] != v for k, v in recomputed.items()):
        raise ValueError("paired report cannot be reproduced from saved predictions")
    if any(row["status"] != "succeeded" for row in raw):
        raise ValueError("failed attempts retained; complete success not established")
    with (experiment / "raw-answers.jsonl").open("rb") as stream:
        journal = [strict_json(line) for line in stream]
    if journal != raw:
        raise ValueError("raw-answer journal differs from published predictions")
    training = report["training"]
    if (
        head["training"] != training
        or training["objective"] != PROFILE
        or training["unknown_windows_in_loss"] is not False
        or training["null_parameters_unchanged"] is not True
        or training["encoder_updates"] != 0
        or training["trainable_parameters"] != 6177
        or training["total_head_parameters"] != 6562
        or not training["delta_squared_norm"] > 0
        or any(v != 0 for row in head["state"]["null.weight"] for v in row)
        or any(v != 0 for v in head["state"]["null.bias"])
    ):
        raise ValueError("evidence-only training receipt or frozen null state mismatch")
    if {r["question_id"] for r in labels} != set(plan["questions"]["train"]) or len(
        labels
    ) != len(plan["questions"]["train"]):
        raise ValueError("training label census is incomplete")
    for row in labels:
        pool = pools[row["question_id"]]
        ids = {Window(**w).identity() for w in pool["windows"]}
        p, n, u = (set(row[k]) for k in ("positive_ids", "negative_ids", "unknown_ids"))
        if p & n or p & u or n & u or p | n | u != ids:
            raise ValueError("tri-state labels do not partition the original pool")
        if (row["unanswerable"] and (p or u)) or (not row["unanswerable"] and n):
            raise ValueError("unlabelled answerable windows were treated as negatives")
    windows_checked, deliveries = 0, 0
    for qid, pool in pools.items():
        documents = {d["identity"]: d for d in views[qid]}
        for window in pool["windows"]:
            doc = documents[window["source_id"]]
            if (
                doc["content"].encode()[window["start"] : window["end"]].decode()
                != window["text"]
                or doc["root"] != window["root"]
                or doc["scope"] != window["scope"]
            ):
                raise ValueError("candidate detached from original source bytes")
            windows_checked += 1
    for row in raw:
        pool, receipt = pools[row["question_id"]], row["receipt"]
        if row["pool_digest"] != digest(pool) or row["candidate_ids"] != [
            Window(**w).identity() for w in pool["windows"]
        ]:
            raise ValueError("answer used a different candidate pool")
        if (
            receipt["generator_identity"] != report["generator_identity"]
            or receipt["generator_profile"] != report["generation_profile"]
            or receipt["question_digest"] != pool["query_digest"]
            or receipt["generator_parameter_updates"] != 0
            or receipt["answer_postprocessed"] is not False
            or not 1 <= receipt["input_tokens"] <= 1024
            or not 1 <= receipt["generated_tokens"] <= 96
        ):
            raise ValueError("generator identity, prompt or token budget drift")
        arm = row["arm"]
        offset = (
            selection["offsets"]["trained" if arm.startswith("trained") else "frozen"]
            if arm.endswith("calibrated")
            else 0.0
        )
        selected = choose(
            row["selector_logits"],
            row["candidate_ids"],
            allow_null=not arm.endswith("forced"),
            offset=offset,
        )
        if selected != row["selected"] or row["null_offset"] != offset:
            raise ValueError("saved decision does not match registered policy")
        sources = receipt["delivered_evidence"]
        if selected is None:
            if (
                sources
                or receipt["selector_abstention_was_still_generated"] is not True
            ):
                raise ValueError(
                    "abstention was not an actual empty-evidence generation"
                )
        else:
            window = pool["windows"][selected]
            if len(sources) != 1 or any(
                sources[0][a] != window[b]
                for a, b in (
                    ("original_id", "source_id"),
                    ("root", "root"),
                    ("scope", "scope"),
                    ("excerpt", "text"),
                    ("source_start", "start"),
                    ("source_end", "end"),
                )
            ):
                raise ValueError(
                    "generator did not receive exactly the selected window"
                )
            deliveries += 1
    return dict(
        schema="hepta.masked-span.execution-check.v1",
        source_commit=expected_source,
        question_counts={phase: len(qs) for phase, qs in plan["questions"].items()},
        answer_executions=len(raw),
        actual_empty_evidence_generations=len(raw) - deliveries,
        original_windows_checked=windows_checked,
        exact_window_deliveries_checked=deliveries,
        unique_generator_inputs=check_same_input_outputs(raw),
        raw_answers_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        objective=training["objective"],
        trainable_parameters=training["trainable_parameters"],
        actual_steps=training["steps"],
        parameter_delta_squared_norm=training["delta_squared_norm"],
        training_rows=training["rows"],
        training_families=len(training["families"]),
        summaries=report["summaries"],
        contrasts=report["contrasts"],
        independently_adjudicated=False,
        semantic_citation_precision=None,
        production_accepted=False,
        superiority_claim=False,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", type=Path)
    parser.add_argument("expected_source")
    args = parser.parse_args()
    result = audit(args.experiment, args.expected_source)
    with (args.experiment / "execution-check.json").open(
        "x", encoding="utf-8"
    ) as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
