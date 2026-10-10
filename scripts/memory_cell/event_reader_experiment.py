"""Source-preserving explanations on the fixed inherited event census.

The optional, externally pinned read policy is already trained before this command
opens tasks. The knowledge writer is not needed for this matched frozen-reader
experiment. Existing baseline behavior and production owners remain unchanged.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import time

from bundle_trial import write
from evidence_bundle import EvidenceBundle, EvidenceSpan
from event_experience import call_worker
from event_memory_trial import ARMS, LIMIT, read, strict_identifier, summarize
from event_reader_view import PROFILE, EventPresentationReader
from native import Document, Question, digest


def preflight(plan_dir, inputs, plan_sha):
    locked = read(plan_dir / "plan.json", plan_sha)
    if (
        locked["schema"] != "hepta.event-organization.plan.v1"
        or tuple(locked["arms"]) != ARMS
        or locked["token_limit"] != LIMIT
        or len(locked["cases"]) != 8
    ):
        raise ValueError("original complete controlled plan required")
    labels = inputs / "labels.json"
    if (
        labels.is_symlink()
        or not labels.is_file()
        or any(p.is_symlink() for p in labels.parents)
        or labels.stat().st_size > 4 * 1024 * 1024
    ):
        raise ValueError("bounded regular labels required")
    if hashlib.sha256(labels.read_bytes()).hexdigest() != locked["labels_sha"]:
        raise ValueError("label pin mismatch")
    sources = tuple(
        Document(**(d | {"assets": tuple(d["assets"])}))
        for d in read(plan_dir / "source-view.json", locked["source_view_sha"])
    )
    originals = {d.identity: d for d in sources}
    if len(originals) != len(sources):
        raise ValueError("duplicate original event")
    queries = [case["query"]["identity"] for case in locked["cases"]]
    if len(set(queries)) != len(queries):
        raise ValueError("duplicate controlled query")
    for case in locked["cases"]:
        if set(case["controls"]) != set(ARMS):
            raise ValueError("changed evidence condition census")
        pool = case["candidate_ids"]
        if (
            len(set(pool)) != len(pool)
            or digest(tuple(pool)) != case["candidate_digest"]
        ):
            raise ValueError("candidate pool identity drift")
        for control in case["controls"].values():
            if len(set(control["selected"])) != len(control["selected"]):
                raise ValueError("duplicate selected source")
            if not set(control["selected"]).issubset(originals):
                raise ValueError("missing selected original")
    return locked, originals


def run(
    plan_dir,
    inputs,
    model_dir,
    output,
    *,
    plan_sha,
    stage_sha,
    policy_path=None,
    policy_sha=None,
):
    from native_citation import capture_native

    source_commit = os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", "")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("exact generating source required")
    if (policy_path is None) != (policy_sha is None):
        raise ValueError("policy file and external pin must be supplied together")
    # The policy snapshot is read before opening tasks, and never updated here.
    policy = read(policy_path, policy_sha) if policy_path is not None else None
    locked, originals = preflight(plan_dir, inputs, plan_sha)
    stage = read(model_dir / "stage.json", stage_sha)
    inventory = read(model_dir / "inventory.json", stage["inventory_sha256"])
    active, arms = locked, ARMS
    if policy is not None:
        from policy_read_audit import ALL_ARMS, extend_controls

        active = extend_controls(
            locked,
            originals,
            policy,
            reader_identity=inventory["inventory_digest"],
            revoked=set(),
        )
        arms = ALL_ARMS
    output.mkdir()
    write(
        output / "execution.json",
        dict(
            schema="hepta.event-input-representation.v1",
            profile=PROFILE,
            source_commit=source_commit,
            plan_sha=plan_sha,
            stage_sha=stage_sha,
            plan=locked,
            model_staging=stage,
            model=inventory,
            original_answers_relabelled=False,
            optimizer_executed=False,
            independent_semantic_review=False,
            production_accepted=False,
            read_policy_sha=policy_sha,
            arms=arms,
            policy_trained_in_an_earlier_process=policy is not None,
        ),
    )
    if policy is not None:
        write(output / "read-policy.json", policy)
        write(output / "actual-controls.json", active)
    started = time.perf_counter()
    reader = EventPresentationReader(
        model_dir / "reader", expected_inventory=inventory["inventory_digest"]
    )
    rows = []
    with (output / "raw-answers.jsonl").open("x", encoding="utf-8") as journal:
        for case in active["cases"]:
            query = Question(**case["query"])
            for arm in arms:
                selected = case["controls"][arm]["selected"]
                spans = tuple(
                    EvidenceSpan(
                        d.identity,
                        d.root,
                        d.scope,
                        d.session,
                        d.observed_at,
                        0,
                        len(d.content.encode()),
                        d.content,
                        digest(d.content),
                    )
                    for d in (originals[key] for key in selected)
                )
                bundle = EvidenceBundle(
                    digest(asdict(query)), case["frontier"], spans, arm
                )
                row = dict(
                    question_id=query.identity,
                    arm=arm,
                    kind=case["kind"],
                    selected=list(selected),
                    candidate_digest=case["candidate_digest"],
                    selection_receipt=case["controls"][arm].get("selection", {}),
                )
                try:
                    answer, receipt = reader.answer(
                        query,
                        bundle,
                        originals,
                        frontier=case["frontier"],
                        revoked=set(),
                        token_limit=LIMIT,
                    )
                    queue = capture_native(
                        query,
                        answer,
                        dict(
                            input_ids_sha256=receipt["input_ids_digest"],
                            delivered_evidence=receipt["delivered_evidence"],
                        ),
                        experiment_digest=digest((plan_sha, PROFILE, arm, policy_sha)),
                        family_digest=digest(query.family),
                    )
                    row.update(
                        status="succeeded",
                        answer=answer,
                        receipt=receipt,
                        citation_audit=queue,
                    )
                except Exception as error:
                    row.update(
                        status="failed",
                        error_type=type(error).__name__,
                        error=str(error)[:1024],
                    )
                journal.write(
                    json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n"
                )
                journal.flush()
                os.fsync(journal.fileno())
                rows.append(row)
    reader.verify_frozen()
    # Only after ALL original answers are synced may the scorer open gold values.
    labels = {r["id"]: r for r in read(inputs / "labels.json", locked["labels_sha"])}
    verification_seconds = 0.0
    for row in rows:
        if row["status"] != "succeeded":
            continue
        truth = labels[row["question_id"]]
        value = strict_identifier(row["answer"])
        row.update(
            parsed_identifier=value,
            strict_task_success=value == truth["expected"],
            required_sources_covered=set(truth["support"]).issubset(row["selected"]),
        )
        if truth["kind"] == "procedure":
            receipt = call_worker(
                dict(
                    operation="execute",
                    recipe=truth["procedure"],
                    supplied=value or "invalid_response",
                )
            )
            row["procedure_verification"] = receipt
            row["strict_task_success"] = receipt["exit_code"] == 0
            verification_seconds += receipt["seconds"]
    write(output / "scored-answers.json", rows)
    expected = [case["query"]["identity"] for case in locked["cases"]]
    baseline = summarize([r for r in rows if r["arm"] in ARMS], expected)
    if policy is None:
        result = baseline
    else:
        from policy_read_audit import audit_policy

        result = audit_policy(rows, expected, policy)
        result["frozen_control_summary"] = baseline
    result.update(
        source_commit=source_commit,
        input_representation=PROFILE,
        actual_model_load_and_run_seconds=time.perf_counter() - started,
        procedure_verification_seconds=verification_seconds,
        inherited_extraction=locked["extraction"],
        inherited_index_and_projection=locked["frozen"]["costs"],
        reader_training_seconds=0.0,
        total_lifecycle_cost=None,
        unavailable_costs=["production retention", "deployed maintenance and recovery"],
        next_stage="no parameter or production adoption from this diagnostic",
    )
    write(output / "report.json", result)
    if any(row["status"] != "succeeded" for row in rows):
        raise ValueError("failed original attempts retained; experiment failed")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("plan", "inputs", "model", "output"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--plan-sha", required=True)
    parser.add_argument("--stage-sha", required=True)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--policy-sha")
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.plan,
                args.inputs,
                args.model,
                args.output,
                plan_sha=args.plan_sha,
                stage_sha=args.stage_sha,
                policy_path=args.policy,
                policy_sha=args.policy_sha,
            )
        )
    )
