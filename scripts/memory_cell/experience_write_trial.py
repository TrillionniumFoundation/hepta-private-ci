"""Separate write/read processes on pinned controlled experience.

Source-only write commits an adapter before the read command opens task payloads.
Original retrieval controls are frozen inputs; this is NOT a fresh calendar window,
independent review, full natural-language benchmark, or production deployment.
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
from event_memory_trial import LIMIT, read, strict_identifier
from experience_memory import ExperienceReader, PROFILE, STEPS, TOKEN_CEILING
from native import Document, Question, digest

ARMS = {
    "hybrid": ("hybrid", "base"),
    "organized": ("organized", "base"),
    "knowledge": ("organized", "memory"),
    "parameter_only": ("empty", "memory"),
    "empty": ("empty", "base"),
}


def exact_source():
    value = os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", "")
    if not re.fullmatch("[0-9a-f]{40}", value):
        raise ValueError("exact execution commit required")
    return value


def original_documents(path, expected):
    values = read(path, expected)
    if not isinstance(values, list) or not 1 <= len(values) <= 2048:
        raise ValueError("bounded original source census required")
    documents = tuple(Document(**(r | {"assets": tuple(r["assets"])})) for r in values)
    if len({r.identity for r in documents}) != len(documents):
        raise ValueError("duplicate source identity")
    return documents


def model_inputs(model_dir, stage_sha):
    from reader_reference import MODELS

    stage = read(model_dir / "stage.json", stage_sha)
    if (stage["repository"], stage["revision"]) != MODELS[stage["tier"]]:
        raise ValueError("unregistered model tier/revision")
    inventory = read(model_dir / "inventory.json", stage["inventory_sha256"])
    return stage, inventory


def write_memory(sources, model_dir, output, *, source_sha, stage_sha):
    from pretrained import LoRAReader

    commit = exact_source()
    documents = original_documents(sources, source_sha)
    stage, inventory = model_inputs(model_dir, stage_sha)
    output.mkdir()
    write(
        output / "write-plan.json",
        dict(
            profile=PROFILE,
            source_commit=commit,
            source_sha=source_sha,
            model_staging=stage,
            revision=2,
            maximum_steps=STEPS,
            token_ceiling=TOKEN_CEILING,
            evaluation_query_input=False,
            source_documents_digest=digest([asdict(d) for d in documents]),
            authored_controlled_sources=True,
            production_accepted=False,
        ),
    )
    started = time.perf_counter()
    reader = ExperienceReader(
        model_dir / "reader",
        expected_inventory=inventory["inventory_digest"],
    )
    loaded = time.perf_counter()
    training = reader.fit_sources(
        documents,
        revision=2,
        allowed_roots={d.root for d in documents},
        revoked=set(),
    )
    manifest = LoRAReader.save(reader, output / "adapter", training)
    reader.verify_frozen()
    # Durably finish every weight/manifest file before the commit marker.
    for path in output.rglob("*"):
        if path.is_file():
            with path.open("rb") as stream:
                os.fsync(stream.fileno())
    retained = sum(p.stat().st_size for p in output.rglob("*") if p.is_file())
    ready = dict(
        schema="hepta.source-knowledge.snapshot.v1",
        writer_source=commit,
        source_sha=source_sha,
        source_documents_digest=digest([asdict(d) for d in documents]),
        base_identity=reader.identity,
        reader_profile=reader.profile,
        manifest_sha=manifest,
        scopes=sorted(reader.scopes),
        roots=sorted(reader.roots),
        training=training,
        model_load_seconds=loaded - started,
        write_seconds=time.perf_counter() - started,
        retained_snapshot_bytes_before_marker=retained,
        retained_original_source_bytes=sum(len(d.content.encode()) for d in documents),
        task_payload_consumed=False,
        independently_observed=False,
        production_accepted=False,
    )
    write(output / "READY.json", ready)
    fd = os.open(output, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    print(json.dumps({k: v for k, v in ready.items() if k != "training"}))
    return ready


def summarize(rows, expected):
    if (
        not expected
        or len(set(expected)) != len(expected)
        or len(rows) != len(expected) * len(ARMS)
        or {(r["question_id"], r["arm"]) for r in rows}
        != {(q, a) for q in expected for a in ARMS}
    ):
        raise ValueError("complete paired census required")
    profiles, by_query = set(), {}
    for row in rows:
        if row["status"] not in ("succeeded", "failed"):
            raise ValueError("unregistered outcome")
        by_query.setdefault(row["question_id"], {})[row["arm"]] = row
        if row["status"] == "succeeded":
            receipt = row["receipt"]
            profiles.add((receipt["reader_identity"], receipt["reader_profile"]))
            if type(row["strict_task_success"]) is not bool:
                raise ValueError("unscored successful task")
    if len(profiles) != 1:
        raise ValueError("mixed/missing actual shared reader")
    for pair in by_query.values():
        if len({r["candidate_digest"] for r in pair.values()}) != 1:
            raise ValueError("candidate pool drift")
        for a, b in (("organized", "knowledge"), ("empty", "parameter_only")):
            x, y = pair[a], pair[b]
            if x["selected"] != y["selected"]:
                raise ValueError("parameter contrast changed evidence")
            if x["status"] == y["status"] == "succeeded" and any(
                x["receipt"][key] != y["receipt"][key]
                for key in ("input_ids_digest", "delivered_evidence")
            ):
                raise ValueError("parameter contrast changed actual prompt")
    result = {}
    for arm in ARMS:
        attempts = [r for r in rows if r["arm"] == arm]
        good = [r for r in attempts if r["status"] == "succeeded"]
        result[arm] = dict(
            planned=len(attempts),
            succeeded=len(good),
            failed=len(attempts) - len(good),
            strict_task_successes=sum(r["strict_task_success"] for r in good),
            citation_markers=sum(
                len(re.findall(r"\[E[0-9]+\]", r["answer"])) for r in good
            ),
            input_tokens=sum(r["receipt"]["input_tokens"] for r in good),
            generated_tokens=sum(r["receipt"]["generated_tokens"] for r in good),
            measured_read_seconds=sum(r["receipt"]["seconds"] for r in good),
            semantic_citation_precision=None,
        )
    return dict(
        arms=result,
        all_attempts=len(rows),
        source_groups_are_authored_templates=True,
        significance_established=False,
        production_accepted=False,
        knowledge_minus_organized=(
            result["knowledge"]["strict_task_successes"]
            - result["organized"]["strict_task_successes"]
        )
        / len(expected),
        organization_minus_hybrid=(
            result["organized"]["strict_task_successes"]
            - result["hybrid"]["strict_task_successes"]
        )
        / len(expected),
        learned_policy_control="not implemented in this experiment",
    )


def read_memory(
    plan_dir, inputs, model_dir, snapshot, output, *, plan_sha, stage_sha, ready_sha
):
    from event_reader_experiment import preflight
    from native_citation import capture_native
    from pretrained import LoRAReader, frozen_digest

    commit = exact_source()
    # The externally pinned snapshot must exist BEFORE opening task-plan payloads.
    ready = read(snapshot / "READY.json", ready_sha)
    if (
        ready["schema"] != "hepta.source-knowledge.snapshot.v1"
        or ready["task_payload_consumed"] is not False
    ):
        raise ValueError("uncommitted or task-conditioned writer")
    documents = original_documents(inputs / "sources.json", ready["source_sha"])
    if digest([asdict(d) for d in documents]) != ready["source_documents_digest"]:
        raise ValueError("written source view drift")
    stage, inventory = model_inputs(model_dir, stage_sha)
    if inventory["inventory_digest"] != ready["base_identity"]:
        raise ValueError("new process must use exactly the written base")
    output.mkdir()
    reader = ExperienceReader(
        model_dir / "reader",
        expected_inventory=ready["base_identity"],
    )
    LoRAReader.load_candidate(
        reader,
        snapshot / "adapter",
        expected_manifest_sha256=ready["manifest_sha"],
        scope=reader.scope,
        allowed_roots={d.root for d in documents},
        revoked=set(),
    )
    reader.scopes = set(ready["scopes"])
    if reader.scopes != {d.scope for d in documents}:
        raise ValueError("written scope drift")
    for parameter in reader.model.parameters():
        parameter.requires_grad_(False)
    if reader.profile != ready["reader_profile"]:
        raise ValueError("writer/read prompt profile drift")
    # The write command cannot call preflight: it has no plan/query/label argument.
    locked, originals = preflight(plan_dir, inputs, plan_sha)
    if (
        digest([asdict(d) for d in originals.values()])
        != ready["source_documents_digest"]
    ):
        raise ValueError("retrieval and module learned different source views")
    write(
        output / "execution.json",
        dict(
            source_commit=commit,
            writer_source=ready["writer_source"],
            ready_sha=ready_sha,
            plan_sha=plan_sha,
            stage_sha=stage_sha,
            snapshot_loaded_before_task_payload=True,
            model_staging=stage,
            separate_write_process=True,
            prior_public_census_exposure=True,
            production_accepted=False,
        ),
    )
    rows = []
    with (output / "raw-answers.jsonl").open("x", encoding="utf-8") as journal:
        for case in locked["cases"]:
            query = Question(**case["query"])
            for arm, (condition, mode) in ARMS.items():
                selected = case["controls"][condition]["selected"]
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
                    for d in (originals[k] for k in selected)
                )
                bundle = EvidenceBundle(
                    digest(asdict(query)), case["frontier"], spans, condition
                )
                row = dict(
                    question_id=query.identity,
                    arm=arm,
                    kind=case["kind"],
                    selected=list(selected),
                    candidate_digest=case["candidate_digest"],
                )
                try:
                    answer, receipt = reader.answer_with_memory(
                        query,
                        bundle,
                        originals,
                        mode=mode,
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
                        experiment_digest=digest((ready_sha, plan_sha, arm)),
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
    labels = {r["id"]: r for r in read(inputs / "labels.json", locked["labels_sha"])}
    procedure_seconds, procedure_calls = 0.0, 0
    for row in rows:
        if row["status"] != "succeeded":
            continue
        truth = labels[row["question_id"]]
        value = strict_identifier(row["answer"])
        row.update(
            parsed_identifier=value, strict_task_success=value == truth["expected"]
        )
        if truth["kind"] == "procedure":
            observed = call_worker(
                dict(
                    operation="execute",
                    recipe=truth["procedure"],
                    supplied=value or "invalid_response",
                )
            )
            row["procedure_verification"] = observed
            row["strict_task_success"] = observed["exit_code"] == 0
            procedure_seconds += observed["seconds"]
            procedure_calls += 1
    # Same valid snapshot, now a newer supplied withdrawal: no fresh load is legal.
    start = time.perf_counter()
    try:
        LoRAReader.load_candidate(
            reader,
            snapshot / "adapter",
            expected_manifest_sha256=ready["manifest_sha"],
            scope=reader.scope,
            allowed_roots={d.root for d in documents},
            revoked={sorted(reader.roots)[0]},
        )
    except ValueError:
        withdrawal_rejected = True
    else:
        raise ValueError("withdrawn source resurrected through old adapter")
    withdrawal_seconds = time.perf_counter() - start
    if frozen_digest(reader.model) != reader.base_digest:
        raise ValueError("evaluation changed the base")
    write(output / "scored-answers.json", rows)
    result = summarize(rows, [c["query"]["identity"] for c in locked["cases"]])
    result.update(
        source_commit=commit,
        writer_source=ready["writer_source"],
        training=ready["training"],
        write_seconds=ready["write_seconds"],
        original_source_bytes=ready["retained_original_source_bytes"],
        snapshot_bytes=ready["retained_snapshot_bytes_before_marker"],
        inherited_extraction=locked["extraction"],
        inherited_index_costs=locked["frozen"]["costs"],
        procedure_verification_seconds=procedure_seconds,
        procedure_execution_calls=procedure_calls,
        measured_withdrawal_check_seconds=withdrawal_seconds,
        old_artifact_rejected_under_withdrawal=withdrawal_rejected,
        total_lifecycle_cost=None,
        unknown_costs=[
            "deployed maintenance",
            "longitudinal retention",
            "cross-host recovery",
        ],
        actual_prospective_windows=0,
        independent_review=False,
    )
    write(output / "report.json", result)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    if any(r["status"] != "succeeded" for r in rows):
        raise ValueError("failed attempts retained; experiment failed")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    p = sub.add_parser("write")
    for name in ("sources", "model", "output"):
        p.add_argument(name, type=Path)
    p.add_argument("--source-sha", required=True)
    p.add_argument("--stage-sha", required=True)
    p = sub.add_parser("read")
    for name in ("plan", "inputs", "model", "snapshot", "output"):
        p.add_argument(name, type=Path)
    for name in ("plan-sha", "stage-sha", "ready-sha"):
        p.add_argument("--" + name, required=True)
    a = parser.parse_args()
    if a.mode == "write":
        write_memory(
            a.sources, a.model, a.output, source_sha=a.source_sha, stage_sha=a.stage_sha
        )
    else:
        read_memory(
            a.plan,
            a.inputs,
            a.model,
            a.snapshot,
            a.output,
            plan_sha=a.plan_sha,
            stage_sha=a.stage_sha,
            ready_sha=a.ready_sha,
        )
