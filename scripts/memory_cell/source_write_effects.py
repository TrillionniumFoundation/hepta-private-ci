"""Seven-arm source-memory effects, distinct from execution or acceptance.

The actual source writer and reader remain unchanged. This consumer reuses their
original records, task parser, procedure worker and citation capture. It never
loads a model, selects a candidate, inserts a citation or invents missing costs.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import re

ARMS = (
    "hybrid",
    "organized",
    "knowledge",
    "parameter_only",
    "empty",
    "policy_initial",
    "policy",
)
PAIRS = {
    "organization_vs_hybrid": ("hybrid", "organized"),
    "policy_vs_initialization": ("policy_initial", "policy"),
    "policy_vs_organized": ("organized", "policy"),
    "knowledge_vs_same_evidence": ("organized", "knowledge"),
    "parameter_only_vs_empty": ("empty", "parameter_only"),
}
SCORING_FIELDS = {"parsed_identifier", "strict_task_success", "procedure_verification"}


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("finite nonnegative measured value required")
    return value


def align_records(raw, scored, cases):
    """Only post-generation task annotations may differ from the raw journal."""
    if not cases or len(cases) > 20000 or len(set(cases)) != len(cases):
        raise ValueError("bounded unique original task census required")
    expected = {(q, arm) for q in cases for arm in ARMS}
    if (
        len(raw) != len(expected)
        or len(scored) != len(expected)
        or {(r["question_id"], r["arm"]) for r in raw} != expected
    ):
        raise ValueError("missing or duplicate original task/arm")
    profiles = set()
    grouped = {q: {} for q in cases}
    for original, annotated in zip(raw, scored, strict=True):
        qid, arm = original["question_id"], original["arm"]
        case = cases[qid]
        if original["status"] not in ("succeeded", "failed"):
            raise ValueError("unknown execution outcome")
        needed = set()
        if original["status"] == "succeeded":
            needed = {"parsed_identifier", "strict_task_success"}
            if case["kind"] == "procedure":
                needed.add("procedure_verification")
        if (
            SCORING_FIELDS.intersection(original)
            or set(annotated) - set(original) != needed
            or any(annotated.get(k) != v for k, v in original.items())
            or set(original) - set(annotated)
            or original["kind"] != case["kind"]
            or original["candidate_digest"] != case["candidate_digest"]
        ):
            raise ValueError("raw answer, task or candidate identity drift")
        selected = original["selected"]
        if (
            not isinstance(selected, list)
            or len(set(selected)) != len(selected)
            or not set(selected) <= set(case["candidate_ids"])
        ):
            raise ValueError("selection not from the frozen candidate pool")
        if arm in ("organized", "knowledge", "hybrid", "empty", "parameter_only"):
            condition = {"knowledge": "organized", "parameter_only": "empty"}.get(
                arm, arm
            )
            if selected != case["controls"][condition]["selected"]:
                raise ValueError("fixed control selection changed")
        if original["status"] == "succeeded":
            if (
                not isinstance(original["answer"], str)
                or not original["answer"].strip()
            ):
                raise ValueError("missing actual answer")
            if type(annotated["strict_task_success"]) is not bool:
                raise ValueError("missing actual task result")
            receipt = original["receipt"]
            enabled = receipt["knowledge_module_enabled"]
            if type(enabled) is not bool or enabled != (
                arm in ("knowledge", "parameter_only")
            ):
                raise ValueError("declared arm and actual adapter state differ")
            profiles.add((receipt["reader_identity"], receipt["reader_profile"]))
            for key in ("input_tokens", "generated_tokens"):
                if type(receipt[key]) is not int or receipt[key] < 0:
                    raise ValueError("invalid observed token count")
            number(receipt["seconds"])
            sources = receipt["delivered_evidence"]
            if not isinstance(sources, list) or len(sources) != len(selected):
                raise ValueError("actual evidence count differs from selection")
            if arm in ("empty", "parameter_only") and sources:
                raise ValueError("parameter-only control received source text")
        grouped[qid][arm] = annotated
    if len(profiles) != 1:
        raise ValueError("mixed or missing reader identity/profile")
    for group in grouped.values():
        for a, b in (
            PAIRS["knowledge_vs_same_evidence"],
            PAIRS["parameter_only_vs_empty"],
        ):
            x, y = group[a], group[b]
            if x["selected"] != y["selected"]:
                raise ValueError("knowledge contrast changed selection")
            if x["status"] == y["status"] == "succeeded":
                for key in (
                    "input_ids_digest",
                    "delivered_evidence",
                    "derived_evidence",
                ):
                    if key not in x["receipt"] or key not in y["receipt"]:
                        raise ValueError("missing actual input binding")
                    if x["receipt"][key] != y["receipt"][key]:
                        raise ValueError("knowledge contrast changed actual input")
    return grouped


def effects(raw, scored, cases):
    grouped = align_records(raw, scored, cases)
    result = {}
    cohorts = {"all": tuple(cases)}
    for kind in sorted({c["kind"] for c in cases.values()}):
        cohorts["kind:" + kind] = tuple(
            q for q, c in cases.items() if c["kind"] == kind
        )
    for name, (baseline, candidate) in PAIRS.items():
        result[name] = {}
        for cohort, ids in cohorts.items():
            wins = losses = missing = changes = baseline_good = candidate_good = 0
            for qid in ids:
                a, b = grouped[qid][baseline], grouped[qid][candidate]
                if a["status"] != "succeeded" or b["status"] != "succeeded":
                    missing += 1
                    continue
                baseline_good += a["strict_task_success"]
                candidate_good += b["strict_task_success"]
                wins += b["strict_task_success"] and not a["strict_task_success"]
                losses += a["strict_task_success"] and not b["strict_task_success"]
                changes += a["answer"] != b["answer"]
            result[name][cohort] = dict(
                planned_pairs=len(ids),
                complete_pairs=len(ids) - missing,
                baseline_successes_on_complete_pairs=baseline_good,
                candidate_successes_on_complete_pairs=candidate_good,
                wins=wins,
                losses=losses,
                missing_pairs=missing,
                changed_answers=changes,
                all_planned_effect_bounds=[
                    (wins - losses - missing) / len(ids),
                    (wins - losses + missing) / len(ids),
                ],
                observed_win_without_loss=missing == 0 and wins > 0 and losses == 0,
                significance_established=False,
            )
    return dict(
        schema="hepta.source-write.effects.v1",
        actual_tasks=len(cases),
        original_answer_executions=len(raw),
        contrasts=result,
        diagnostic_answer_changes_are_not_task_gains=True,
        independently_admitted_sample_size=None,
        semantic_citation_precision=None,
        production_accepted=False,
    )


def audit(plan_dir, inputs, output_root, *, plan_sha, ready_sha, source_commit):
    """Recompute existing outcomes only; no successful receipt on corrupt input."""
    from event_experience import call_worker
    from event_memory_trial import read, strict_identifier
    from native import Document, Question, digest
    from native_citation import capture_native
    from experience_policy import INITIAL, choose, lookup_from_question, validate_policy
    from event_projection import EventProjection
    from span_supervision import strict_json

    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("exact generating source required")
    plan = read(plan_dir / "plan.json", plan_sha)
    ready = read(output_root / "snapshot/READY.json", ready_sha)
    task_dir = output_root / "tasks"
    execution = strict_json((task_dir / "execution.json").read_text())
    if (
        execution["source_commit"] != source_commit
        or execution["writer_source"] != ready["writer_source"]
        or execution["ready_sha"] != ready_sha
        or execution["plan_sha"] != plan_sha
        or execution["snapshot_loaded_before_task_payload"] is not True
        or ready["task_payload_consumed"] is not False
        or ready["schema"] != "hepta.source-knowledge.snapshot.v1"
        or ready["production_accepted"] is not False
    ):
        raise ValueError("source-before-task snapshot binding mismatch")
    documents = tuple(
        Document(**(d | {"assets": tuple(d["assets"])}))
        for d in read(inputs / "sources.json", ready["source_sha"])
    )
    if digest([asdict(d) for d in documents]) != ready["source_documents_digest"]:
        raise ValueError("changed source corpus")
    source_map = {d.identity: d for d in documents}
    if len(source_map) != len(documents):
        raise ValueError("duplicate original source")
    cases = {c["query"]["identity"]: c for c in plan["cases"]}
    if len(cases) != len(plan["cases"]):
        raise ValueError("duplicate case identity")
    raw_path = task_dir / "raw-answers.jsonl"
    if raw_path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("raw journal exceeds audit bound")
    raw = [strict_json(line) for line in raw_path.read_text().splitlines()]
    scored = strict_json((task_dir / "scored-answers.json").read_text())
    result = effects(raw, scored, cases)
    labels_list = read(inputs / "labels.json", plan["labels_sha"])
    labels = {r["id"]: r for r in labels_list}
    if len(labels) != len(labels_list) or not set(cases) <= set(labels):
        raise ValueError("incomplete label census")
    policy = execution["learned_policy_training"]
    if policy is None:
        raise ValueError("seven-arm run requires its actually learned policy")
    weights = validate_policy(
        policy,
        documents,
        reader_identity=ready["base_identity"],
        test_scopes={c["query"]["scope"] for c in cases.values()},
        revoked=set(),
    )
    procedure_replays = spans_checked = 0
    for row in scored:
        if row["status"] != "succeeded":
            continue
        case = cases[row["question_id"]]
        query = Question(**case["query"])
        if row["arm"] in ("policy_initial", "policy"):
            selected, _ = choose(
                EventProjection(tuple(d for d in documents if d.scope == query.scope)),
                lookup_from_question(query),
                case["candidate_ids"],
                INITIAL if row["arm"] == "policy_initial" else weights,
                revoked=set(),
            )
            if list(selected) != row["selected"]:
                raise ValueError("actual selection differs from frozen policy")
        for sid, span in zip(
            row["selected"], row["receipt"]["delivered_evidence"], strict=True
        ):
            doc = source_map[sid]
            if (
                span["root"] != doc.root
                or span["excerpt"] != doc.content
                or span["scope"] != query.scope
            ):
                raise ValueError("delivered source differs from original")
            spans_checked += 1
        queue = capture_native(
            query,
            row["answer"],
            dict(
                input_ids_sha256=row["receipt"]["input_ids_digest"],
                delivered_evidence=row["receipt"]["delivered_evidence"],
            ),
            experiment_digest=digest((ready_sha, plan_sha, row["arm"])),
            family_digest=digest(query.family),
        )
        if queue != row["citation_audit"]:
            raise ValueError("citation request differs from original delivery")
        truth = labels[row["question_id"]]
        parsed = strict_identifier(row["answer"])
        correct = parsed == truth["expected"]
        if truth["kind"] == "procedure":
            observed = call_worker(
                dict(
                    operation="execute",
                    recipe=truth["procedure"],
                    supplied=parsed or "invalid_response",
                )
            )
            old = row["procedure_verification"]
            if {k: v for k, v in observed.items() if k != "seconds"} != {
                k: v for k, v in old.items() if k != "seconds"
            }:
                raise ValueError("same procedural verifier produced different outcome")
            correct = observed["exit_code"] == 0
            procedure_replays += 1
        if row["parsed_identifier"] != parsed or row["strict_task_success"] != correct:
            raise ValueError(
                "task success differs from independently recomputed outcome"
            )
    result.update(
        generating_source=source_commit,
        writer_source=ready["writer_source"],
        raw_answers_sha256=hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        snapshot_sha256=ready_sha,
        source_spans_verified=spans_checked,
        repeated_procedure_checks=procedure_replays,
        new_model_calls=0,
        new_independent_observations=0,
    )
    path = task_dir / "source-effects.json"
    with path.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("plan", "inputs", "output_root"):
        parser.add_argument(name, type=Path)
    for name in ("plan-sha", "ready-sha", "source-commit"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    audit(
        args.plan,
        args.inputs,
        args.output_root,
        plan_sha=args.plan_sha,
        ready_sha=args.ready_sha,
        source_commit=args.source_commit,
    )
