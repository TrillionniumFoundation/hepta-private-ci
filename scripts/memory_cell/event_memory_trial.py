"""Matched event-organization/reader experiment; no learned or deployed policy.

Calibration labels tune the common hybrid baseline. Final answer labels are
opened only by the post-journal scorer. Program-bound support is an explicit
controlled diagnostic, NOT a human-certified oracle. No stages 3/4 are invented.
"""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import time

from bundle_trial import write
from evidence_bundle import EvidenceBundle, EvidenceSpan
from event_experience import call_worker, question
from event_projection import EventProjection
from native import Document, Question, digest

ARMS = (
    "empty",
    "hybrid",
    "entity_time",
    "organized",
    "program_support",
    "without_prerequisite",
)
LIMIT = 2048


def read(path, expected):
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError("regular pinned input required")
    with path.open("rb") as stream:
        raw = stream.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("input bytes changed")

    def pairs(items):
        value = {}
        for k, v in items:
            if k in value:
                raise ValueError("duplicate event input field")
            value[k] = v
        return value

    def invalid(_):
        raise ValueError("nonfinite event input")

    return json.loads(raw.decode(), object_pairs_hook=pairs, parse_constant=invalid)


def stage_encoder(output):
    from huggingface_hub import HfApi, snapshot_download
    from pretrained import file_inventory
    from prepare import PINS
    from reader_reference import catalogue, verify_files

    output.mkdir()
    repo, revision = PINS["encoder"]
    entries = catalogue(
        HfApi().model_info(repo, revision=revision, files_metadata=True, token=False),
        revision,
    )
    if sum(v["bytes"] for v in entries.values()) > 512 * 1024 * 1024:
        raise ValueError("controlled encoder resource bound")
    write(
        output / "publisher.json",
        dict(repository=repo, revision=revision, files=entries),
    )
    snapshot_download(
        repo,
        revision=revision,
        allow_patterns=list(entries),
        local_dir=output / "encoder",
        token=False,
        max_workers=2,
    )
    verify_files(output / "encoder", entries)
    inventory = file_inventory(output / "encoder")
    if set(inventory) != set(entries):
        raise ValueError("unexpected encoder file")
    write(
        output / "inventory.json", dict(inventory=inventory, digest=digest(inventory))
    )


def plan(inputs, encoder_dir, output, *, collection_sha, encoder_sha):
    from index import PersistentIndex, RetrievalPolicy
    from pretrained import Encoder

    planning_started = time.perf_counter()
    collection = read(inputs / "collection.json", collection_sha)
    catalogue = read(encoder_dir / "inventory.json", encoder_sha)
    originals = tuple(
        Document(**(d | {"assets": tuple(d["assets"])}))
        for d in read(inputs / "sources.json", collection["files"]["sources.json"])
    )
    output.mkdir()
    write(output / "source-view.json", [asdict(d) for d in originals])
    encoder = Encoder(encoder_dir / "encoder")
    if encoder.identity != catalogue["digest"]:
        raise ValueError("encoder inventory detached")
    projections, indices, costs = {}, {}, {}
    for scope in sorted({d.scope for d in originals}):
        started = time.perf_counter()
        documents = tuple(d for d in originals if d.scope == scope)
        projection = EventProjection(documents)
        projected = time.perf_counter()
        vectors = encoder.encode([d.content for d in documents])
        encoded = time.perf_counter()
        path = output / (scope + ".sqlite")
        identity = PersistentIndex.build(
            path, documents, vectors, encoder.identity, projection.frontier
        )
        index = PersistentIndex(
            path,
            projection.frontier,
            set(),
            expected_file_digest=identity,
            expected_encoder=encoder.identity,
        )
        projections[scope], indices[scope] = projection, index
        costs[scope] = dict(
            projection_seconds=projected - started,
            encoding_seconds=encoded - projected,
            index_seconds=time.perf_counter() - encoded,
            index_bytes=path.stat().st_size,
            source_bytes=projection.source_bytes,
            index_digest=identity,
        )
    # No query, oracle or answer is an input to any event projection/index build.
    frozen = dict(
        collection_sha=collection_sha,
        encoder_sha=encoder_sha,
        costs=costs,
        frozen_at=datetime.now(timezone.utc).isoformat(),
        learned_policy=False,
    )
    write(output / "memory-frozen.json", frozen)
    public = read(inputs / "questions.json", collection["files"]["questions.json"])
    annotations = read(inputs / "labels.json", collection["files"]["labels.json"])
    if len(public) != 16 or {p["id"] for p in public} != set(projections):
        raise ValueError("unexpected controlled census")
    labels = {r["id"]: r for r in annotations}
    if len(labels) != len(annotations) or set(labels) != set(projections):
        raise ValueError("duplicate or missing controlled labels")
    now = datetime.now(timezone.utc).isoformat()
    queries = {p["id"]: question(p, now) for p in public}
    query_encoding_started = time.perf_counter()
    query_vectors = {
        qid: encoder.encode([q.content])[0] for qid, (q, _) in queries.items()
    }
    query_encoding_seconds = time.perf_counter() - query_encoding_started
    tuning = []
    for weight in (0.0, 0.25, 0.5, 0.75, 1.0):
        total = []
        for spec in public:
            if spec["phase"] != "calibration":
                continue
            q, _ = queries[spec["id"]]
            found, _ = indices[q.scope].query(
                q,
                query_vectors[q.identity],
                RetrievalPolicy(top_k=4, channel_k=32, lexical_weight=weight),
                current_cut=projections[q.scope].frontier,
                revoked=set(),
            )
            required = set(labels[q.identity]["support"])
            total.append(len(required & {d.identity for d in found}) / len(required))
        if len(total) != 8:
            raise ValueError("calibration count mismatch")
        tuning.append(dict(weight=weight, mean_support_recall=sum(total) / len(total)))
    chosen = max(
        tuning, key=lambda x: (x["mean_support_recall"], -abs(x["weight"] - 0.5))
    )
    cases = []
    for spec in public:
        if spec["phase"] != "test":
            continue
        q, lookup = queries[spec["id"]]
        proj = projections[q.scope]
        found, retrieval = indices[q.scope].query(
            q,
            query_vectors[q.identity],
            RetrievalPolicy(top_k=32, channel_k=32, lexical_weight=chosen["weight"]),
            current_cut=proj.frontier,
            revoked=set(),
        )
        candidates = tuple(d.identity for d in found)
        controls = {}
        for arm in ("hybrid", "entity_time", "organized"):
            selection_started = time.perf_counter()
            selected, info = proj.select(lookup, candidates, mode=arm, revoked=set())
            info["measured_selection_seconds"] = time.perf_counter() - selection_started
            controls[arm] = dict(selected=selected, selection=info)
        required = tuple(labels[q.identity]["support"])
        if not 1 <= len(required) <= 4 or not set(required).issubset(proj.facts):
            raise ValueError("invalid program support")
        controls.update(
            empty=dict(selected=(), selection={}),
            program_support=dict(selected=required, selection={}),
            without_prerequisite=dict(selected=required[1:], selection={}),
        )
        cases.append(
            dict(
                query=asdict(q),
                kind=spec["kind"],
                candidate_ids=candidates,
                candidate_digest=digest(candidates),
                frontier=proj.frontier,
                retrieval=retrieval,
                controls=controls,
            )
        )
    for index in indices.values():
        index.close()
    write(
        output / "plan.json",
        dict(
            schema="hepta.event-organization.plan.v1",
            arms=ARMS,
            cases=cases,
            frozen=frozen,
            source_view_sha=hashlib.sha256(
                (output / "source-view.json").read_bytes()
            ).hexdigest(),
            labels_sha=collection["files"]["labels.json"],
            baseline_tuning=tuning,
            total_planning_seconds=time.perf_counter() - planning_started,
            query_encoding_seconds=query_encoding_seconds,
            calibration_retrievals=40,
            selected_weight=chosen["weight"],
            token_limit=LIMIT,
            extraction=collection,
            prior_public_census_reused=False,
            authored_templates=True,
            independent_human_review=False,
            production_accepted=False,
        ),
    )


def strict_identifier(answer):
    """Narrow executable response grammar, NOT a semantic language judge."""
    match = re.fullmatch(
        r"\s*((?:site|mode)_[0-9a-f]{8})(?:\s*\[E[1-9][0-9]*\])*\s*\.?\s*", answer
    )
    return match[1] if match else None


def summarize(records, expected):
    if not expected or len(set(expected)) != len(expected):
        raise ValueError("unique nonempty question census required")
    if len(records) != len(expected) * len(ARMS) or {
        (r["question_id"], r["arm"]) for r in records
    } != {(q, a) for q in expected for a in ARMS}:
        raise ValueError("incomplete or duplicate actual result census")
    profiles, by_query = set(), {}
    for row in records:
        if row["status"] not in ("succeeded", "failed"):
            raise ValueError("invalid execution status")
        by_query.setdefault(row["question_id"], []).append(row)
        if row["status"] == "succeeded":
            receipt = row["receipt"]
            if (
                any(
                    type(row[k]) is not bool
                    for k in ("strict_task_success", "required_sources_covered")
                )
                or any(
                    type(receipt[k]) is not int or receipt[k] < 0
                    for k in ("input_tokens", "generated_tokens")
                )
                or not math.isfinite(receipt["seconds"])
                or receipt["seconds"] < 0
            ):
                raise ValueError("invalid measured result")
            profiles.add(
                (
                    receipt["reader_identity"],
                    receipt["reader_profile"],
                    receipt["token_limit"],
                )
            )
    if len(profiles) != 1:
        raise ValueError("mixed or absent reader identity")
    for group in by_query.values():
        if len({r["candidate_digest"] for r in group}) != 1:
            raise ValueError("different primary candidate pools")
    stats = {}
    for arm in ARMS:
        rows = [r for r in records if r["arm"] == arm]
        good = [r for r in rows if r["status"] == "succeeded"]
        stats[arm] = dict(
            planned=len(rows),
            succeeded=len(good),
            failed=len(rows) - len(good),
            strict_task_successes=sum(r["strict_task_success"] for r in good),
            grammar_valid=sum(r["parsed_identifier"] is not None for r in good),
            generated_citation_markers=sum(
                len(re.findall(r"\[E[0-9]+\]", r["answer"])) for r in good
            ),
            input_tokens=sum(r["receipt"]["input_tokens"] for r in good),
            generated_tokens=sum(r["receipt"]["generated_tokens"] for r in good),
            measured_read_seconds=sum(r["receipt"]["seconds"] for r in good),
            matched_program_support=sum(r["required_sources_covered"] for r in good),
            semantic_citation_precision=None,
        )
    return dict(
        arms=stats,
        reader_profiles=list(profiles),
        all_attempts=len(records),
        controlled_support_minus_empty=(
            stats["program_support"]["strict_task_successes"]
            - stats["empty"]["strict_task_successes"]
        )
        / len(expected),
        organization_minus_hybrid=(
            stats["organized"]["strict_task_successes"]
            - stats["hybrid"]["strict_task_successes"]
        )
        / len(expected),
        source_groups_are_authored_templates=True,
        significance_established=False,
        independent_human_review=False,
        parametric_optimizer_executed=False,
        production_accepted=False,
        new_prospective_windows=0,
    )


def run(plan_dir, inputs, model_dir, output, *, plan_sha, stage_sha):
    from native_citation import capture_native
    from reader_reference import ReferenceReader

    run_started = time.perf_counter()
    locked = read(plan_dir / "plan.json", plan_sha)
    if (
        locked["schema"] != "hepta.event-organization.plan.v1"
        or tuple(locked["arms"]) != ARMS
    ):
        raise ValueError("unknown event experiment")
    model = read(model_dir / "stage.json", stage_sha)
    inventory = read(model_dir / "inventory.json", model["inventory_sha256"])
    sources = tuple(
        Document(**(d | {"assets": tuple(d["assets"])}))
        for d in read(plan_dir / "source-view.json", locked["source_view_sha"])
    )
    originals = {d.identity: d for d in sources}
    output.mkdir()
    write(
        output / "execution.json",
        dict(
            plan_sha=plan_sha,
            stage_sha=stage_sha,
            model=inventory,
            model_staging=model,
            plan=locked,
            mode="frozen-reader-no-training",
        ),
    )
    reader = ReferenceReader(
        model_dir / "reader", expected_inventory=inventory["inventory_digest"]
    )
    rows = []
    with (output / "raw-answers.jsonl").open("x", encoding="utf-8") as journal:
        for case in locked["cases"]:
            q = Question(**case["query"])
            for arm in ARMS:
                control = case["controls"][arm]
                selected = tuple(
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
                    for d in (originals[k] for k in control["selected"])
                )
                bundle = EvidenceBundle(
                    digest(asdict(q)), case["frontier"], selected, arm
                )
                row = dict(
                    question_id=q.identity,
                    arm=arm,
                    kind=case["kind"],
                    selected=list(control["selected"]),
                    candidate_digest=case["candidate_digest"],
                )
                try:
                    answer, receipt = reader.answer(
                        q,
                        bundle,
                        originals,
                        frontier=case["frontier"],
                        revoked=set(),
                        token_limit=LIMIT,
                    )
                    queue = capture_native(
                        q,
                        answer,
                        dict(
                            input_ids_sha256=receipt["input_ids_digest"],
                            delivered_evidence=receipt["delivered_evidence"],
                        ),
                        experiment_digest=digest((plan_sha, arm)),
                        family_digest=digest(q.family),
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
                import os

                os.fsync(journal.fileno())
                rows.append(row)
    reader.verify_frozen()
    # Only now access final answer values and score actual returned text.
    labels = {r["id"]: r for r in read(inputs / "labels.json", locked["labels_sha"])}
    verification_seconds = 0.0
    for row in rows:
        truth = labels[row["question_id"]]
        if row["status"] != "succeeded":
            continue
        value = strict_identifier(row["answer"])
        row.update(
            parsed_identifier=value,
            strict_task_success=value == truth["expected"],
            required_sources_covered=set(truth["support"]).issubset(row["selected"]),
        )
        if truth["kind"] == "procedure":
            verification = call_worker(
                dict(
                    operation="execute",
                    recipe=truth["procedure"],
                    supplied=value or "invalid_response",
                )
            )
            row["procedure_verification"] = verification
            verification_seconds += verification["seconds"]
            row["strict_task_success"] = verification["exit_code"] == 0
    write(output / "scored-answers.json", rows)
    result = summarize(rows, [c["query"]["identity"] for c in locked["cases"]])
    result["costs"] = dict(
        extraction=locked["extraction"],
        write_and_index=locked["frozen"]["costs"],
        actual_run_wall_seconds=time.perf_counter() - run_started,
        plan_wall_seconds=locked["total_planning_seconds"],
        model_staging=model,
        verification_seconds=verification_seconds,
        training_seconds=0.0,
        retained_evidence_bytes=sum(
            p.stat().st_size for p in plan_dir.iterdir() if p.is_file()
        ),
        maintenance_and_real_recovery_seconds=None,
        total_lifecycle_cost=None,
        missing_costs_are_not_zero=True,
    )
    result["next_stages"] = dict(
        parameter_adaptation="not_executed_reader_and_independent_data_prerequisites",
        long_term_qualification="not_executed_no_real_prospective_windows_or_deployed_recovery",
    )
    write(output / "report.json", result)
    if any(r["status"] != "succeeded" for r in rows):
        raise ValueError("failed actual calls retained; experiment failed")
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("encoder", "plan", "run"))
    p.add_argument("paths", nargs="+", type=Path)
    p.add_argument("--input-sha")
    p.add_argument("--model-sha")
    args = p.parse_args()
    if args.command == "encoder" and len(args.paths) == 1:
        stage_encoder(*args.paths)
    elif args.command == "plan" and len(args.paths) == 3:
        plan(*args.paths, collection_sha=args.input_sha, encoder_sha=args.model_sha)
    elif args.command == "run" and len(args.paths) == 4:
        print(
            json.dumps(
                run(*args.paths, plan_sha=args.input_sha, stage_sha=args.model_sha)
            )
        )
    else:
        p.error("wrong positional argument count")
