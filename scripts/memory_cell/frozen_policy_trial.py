"""Use the existing learned policy through actual frozen-session lifetimes.

Separate freeze/read/replay commands preserve source-before-task ordering. All
four arms keep the existing candidate pool, reader and procedure worker. This
is controlled development, not new independent data or a production store.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import time

from evidence_bundle import EvidenceBundle, EvidenceSpan, observed_time
from event_experience import call_worker
from event_memory_trial import LIMIT, read, strict_identifier
from event_projection import EventProjection
from experience_policy import INITIAL, choose, lookup_from_question, validate_policy
from frozen_memory_session import FrozenMemorySession, freeze, publish
from native import Question, digest

ARMS = ("hybrid", "organized", "initial", "learned")
PROFILE = "hepta.frozen-policy-lifecycle.v1"


def withdrawals(path, expected):
    value = read(path, expected)
    if (
        not isinstance(value, list)
        or len(value) > 10000
        or any(not isinstance(v, str) or not v or len(v.encode()) > 4096 for v in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError("bounded current withdrawal view required")
    return set(value)


def freeze_all(sources, policy_path, output, *, source_sha, policy_sha, commit):
    from experience_write_trial import original_documents

    started = time.perf_counter()
    documents = original_documents(sources, source_sha)
    policy = read(policy_path, policy_sha)
    scopes = sorted({d.scope for d in documents} - set(policy["training_scopes"]))
    if len(scopes) != 8:
        raise ValueError("the complete eight held-out controlled scopes are required")
    weights = validate_policy(
        policy,
        documents,
        reader_identity=policy["reader_identity"],
        test_scopes=set(scopes),
        revoked=set(),
    )
    ancestors = tuple(d for d in documents if d.scope in policy["training_scopes"])
    through = max((d.observed_at for d in documents), key=observed_time)
    output.mkdir()
    snapshots = []
    for scope in scopes:
        local = tuple(d for d in documents if d.scope == scope)
        for arm in ARMS:
            mode = dict(
                profile=PROFILE,
                arm=arm,
                policy_sha=policy_sha,
                weights=list(weights if arm == "learned" else INITIAL)
                if arm in ("initial", "learned")
                else None,
            )
            directory = digest((scope, arm))
            snapshot = freeze(
                output / directory,
                local,
                through=through,
                policy_bytes=json.dumps(mode, sort_keys=True).encode(),
                # Conservatively retain calibration ancestors for all methods:
                # the shared hybrid mixing policy also used those sources.
                policy_roots=set(policy["roots"]),
                policy_sources=ancestors,
                reader_identity=policy["reader_identity"],
                source_commit=commit,
            )
            snapshots.append(
                dict(scope=scope, arm=arm, directory=directory, snapshot_sha=snapshot)
            )
    result = dict(
        schema=PROFILE,
        source_commit=commit,
        source_sha=source_sha,
        source_documents_digest=digest([asdict(d) for d in documents]),
        policy_sha=policy_sha,
        policy=policy,
        snapshots=snapshots,
        source_cutoff=through,
        freeze_seconds=time.perf_counter() - started,
        policy_training_precedes_task_input=True,
        task_payload_consumed=False,
        physical_snapshot_bytes=sum(
            p.stat().st_size for p in output.rglob("*") if p.is_file()
        ),
        independent_snapshots=0,
        prospective_windows=0,
        production_accepted=False,
    )
    return publish(output / "CATALOG.json", result)


def checked_catalog(directory, expected):
    value = read(directory / "CATALOG.json", expected)
    if value["schema"] != PROFILE or value["task_payload_consumed"] is not False:
        raise ValueError("wrong or task-conditioned frozen catalogue")
    entries = value["snapshots"]
    scopes = {r["scope"] for r in entries}
    if (
        len(scopes) != 8
        or len(entries) != 32
        or {(r["scope"], r["arm"]) for r in entries}
        != {(s, a) for s in scopes for a in ARMS}
        or any(r["directory"] != digest((r["scope"], r["arm"])) for r in entries)
    ):
        raise ValueError("incomplete or unsafe frozen session catalogue")
    return value


def run(
    plan_dir,
    inputs,
    model_dir,
    frozen,
    output,
    *,
    plan_sha,
    stage_sha,
    catalog_sha,
    withdrawal_path,
    withdrawal_sha,
):
    from event_reader_experiment import preflight
    from event_reader_view import EventPresentationReader
    from experience_write_trial import exact_source, model_inputs
    from frozen_policy_audit import summarize
    from native_citation import capture_native

    commit = exact_source()
    catalogue = checked_catalog(frozen, catalog_sha)
    sessions = {
        (r["scope"], r["arm"]): FrozenMemorySession(
            frozen / r["directory"], expected_snapshot=r["snapshot_sha"]
        )
        for r in catalogue["snapshots"]
    }
    # No task plan has been opened above this point; every session is immutable.
    locked, originals = preflight(plan_dir, inputs, plan_sha)
    if (
        digest([asdict(d) for d in originals.values()])
        != catalogue["source_documents_digest"]
    ):
        raise ValueError("task view differs from the frozen experience")
    if {c["query"]["scope"] for c in locked["cases"]} != {s for s, _ in sessions}:
        raise ValueError("missing or extra task scope")
    stage, inventory = model_inputs(model_dir, stage_sha)
    validate_policy(
        catalogue["policy"],
        tuple(originals.values()),
        reader_identity=inventory["inventory_digest"],
        test_scopes={s for s, _ in sessions},
        revoked=withdrawals(withdrawal_path, withdrawal_sha),
    )
    output.mkdir()
    publish(
        output / "execution.json",
        dict(
            schema=PROFILE,
            source_commit=commit,
            catalog_sha=catalog_sha,
            plan_sha=plan_sha,
            stage_sha=stage_sha,
            withdrawal_sha=withdrawal_sha,
            model=inventory,
            model_staging=stage,
            arms=ARMS,
            prior_public_task_exposure=True,
            optimizer_executed=False,
            production_accepted=False,
        ),
    )
    begin = time.perf_counter()
    reader = EventPresentationReader(
        model_dir / "reader", expected_inventory=inventory["inventory_digest"]
    )
    model_load_seconds = time.perf_counter() - begin
    rows, replay_items = [], []
    with (output / "raw-answers.jsonl").open("x", encoding="utf-8") as journal:
        for case in locked["cases"]:
            query = Question(**case["query"])
            for arm in ARMS:
                session = sessions[(query.scope, arm)]
                trace = {}

                def selector(q, docs, frontier, policy_bytes, revoked):
                    policy = json.loads(policy_bytes)
                    if policy["profile"] != PROFILE or policy["arm"] != arm:
                        raise ValueError("changed frozen policy mode")
                    started = time.perf_counter()
                    if arm in ("hybrid", "organized"):
                        selected = tuple(case["controls"][arm]["selected"])
                        detail = case["controls"][arm].get("selection", {})
                    else:
                        selected, detail = choose(
                            EventProjection(docs),
                            lookup_from_question(q),
                            case["candidate_ids"],
                            policy["weights"],
                            revoked=revoked,
                        )
                    if not set(selected) <= set(case["candidate_ids"]):
                        raise ValueError("policy injected out-of-pool sources")
                    trace.update(
                        selected=list(selected),
                        detail=detail,
                        seconds=time.perf_counter() - started,
                    )
                    local = {d.identity: d for d in docs}
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
                        for d in (local[k] for k in selected)
                    )
                    return EvidenceBundle(
                        digest(asdict(q)), frontier, spans, "stream_policy"
                    )

                row = dict(
                    question_id=query.identity,
                    query=asdict(query),
                    arm=arm,
                    kind=case["kind"],
                    candidate_digest=case["candidate_digest"],
                )
                try:
                    value = session.answer(
                        query,
                        selector,
                        reader,
                        withdrawals=lambda: withdrawals(
                            withdrawal_path, withdrawal_sha
                        ),
                        token_limit=LIMIT,
                    )
                    record = value["record"]
                    queue = capture_native(
                        query,
                        record["answer"],
                        dict(
                            input_ids_sha256=record["receipt"]["input_ids_digest"],
                            delivered_evidence=record["receipt"]["delivered_evidence"],
                        ),
                        experiment_digest=digest((catalog_sha, plan_sha, arm)),
                        family_digest=digest(query.family),
                    )
                    row.update(
                        status="succeeded",
                        answer=record["answer"],
                        receipt=record["receipt"],
                        session_record=record,
                        result_sha=value["result_sha256"],
                        selected=trace["selected"],
                        selection=trace,
                        citation_audit=queue,
                    )
                    replay_items.append(
                        dict(
                            query=asdict(query),
                            arm=arm,
                            snapshot_sha=session.expected_snapshot,
                            result_sha=value["result_sha256"],
                        )
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
    # Predictions are durable before final expected values or tool recipes are read.
    labels = {r["id"]: r for r in read(inputs / "labels.json", locked["labels_sha"])}
    for row in rows:
        if row["status"] != "succeeded":
            continue
        truth = labels[row["question_id"]]
        identifier = strict_identifier(row["answer"])
        row["strict_task_success"] = identifier == truth["expected"]
        if truth["kind"] == "procedure":
            verification = call_worker(
                dict(
                    operation="execute",
                    recipe=truth["procedure"],
                    supplied=identifier or "invalid_response",
                )
            )
            row["procedure_verification"] = verification
            row["strict_task_success"] = verification["exit_code"] == 0
    publish(output / "scored-answers.json", rows)
    result = summarize(rows, [c["query"]["identity"] for c in locked["cases"]])
    result.update(
        source_commit=commit,
        catalog_sha=catalog_sha,
        model_load_seconds=model_load_seconds,
        measured_read_stage_seconds=time.perf_counter() - begin,
        # Inclusive phase envelopes below do not add nested training/worker clocks.
        measured_prior_extraction_seconds=locked["extraction"]["extraction_seconds"],
        measured_prior_planning_seconds=locked["total_planning_seconds"],
        measured_policy_write_seconds=catalogue["policy"]["write_seconds"],
        measured_snapshot_freeze_seconds=catalogue["freeze_seconds"],
        inherited_cost_provenance=dict(
            plan_sha=plan_sha, policy_sha=catalogue["policy_sha"]
        ),
        physical_frozen_bytes=sum(
            p.stat().st_size for p in frozen.rglob("*") if p.is_file()
        ),
        original_source_bytes=sum(len(d.content.encode()) for d in originals.values()),
        original_index_bytes=sum(
            v["index_bytes"] for v in locked["frozen"]["costs"].values()
        ),
        model_bytes=sum(v["bytes"] for v in inventory["files"].values())
        if "files" in inventory
        else None,
        production_lifecycle_cost=None,
        retention_after_parameter_update=None,
        deployed_recovery_cost=None,
        semantic_citation_precision=None,
        independent_snapshots=0,
        prospective_windows=0,
        production_accepted=False,
    )
    publish(output / "report.json", result)
    receipt = dict(
        schema=PROFILE,
        catalog_sha=catalog_sha,
        results=replay_items,
        raw_answers_sha=hashlib.sha256(
            (output / "raw-answers.jsonl").read_bytes()
        ).hexdigest(),
        complete=len(replay_items) == 32,
        production_accepted=False,
    )
    receipt_sha = publish(output / "REPLAY.json", receipt)
    print(json.dumps(dict(report=result, replay_sha=receipt_sha), allow_nan=False))
    if any(r["status"] != "succeeded" for r in rows):
        raise ValueError("failed original tasks retained; experiment failed")


def replay_all(
    frozen,
    receipt_path,
    output,
    *,
    catalog_sha,
    receipt_sha,
    withdrawal_path,
    withdrawal_sha,
):
    catalogue = checked_catalog(frozen, catalog_sha)
    receipt = read(receipt_path, receipt_sha)
    if (
        receipt["schema"] != PROFILE
        or receipt["catalog_sha"] != catalog_sha
        or receipt["complete"] is not True
    ):
        raise ValueError("complete externally pinned read receipt required")
    entries = {(r["scope"], r["arm"]): r for r in catalogue["snapshots"]}
    items = receipt["results"]
    if len(items) != 32 or {(r["query"]["scope"], r["arm"]) for r in items} != set(
        entries
    ):
        raise ValueError("incomplete replay census")
    results, begin = [], time.perf_counter()
    for item in items:
        query = Question(**item["query"])
        entry = entries[(query.scope, item["arm"])]
        if item["snapshot_sha"] != entry["snapshot_sha"]:
            raise ValueError("replay snapshot identity drift")
        session = FrozenMemorySession(
            frozen / entry["directory"], expected_snapshot=entry["snapshot_sha"]
        )
        revoked = withdrawals(withdrawal_path, withdrawal_sha)
        must_block = bool(session.roots & revoked)
        try:
            value = session.replay(
                query,
                withdrawals=lambda: withdrawals(withdrawal_path, withdrawal_sha),
                expected_result_sha256=item["result_sha"],
            )
        except ValueError as error:
            if (
                not must_block
                or str(error) != "revoked snapshot requires owner rebuild"
            ):
                raise
            status = "withdrawn"
        else:
            if must_block or value["record"]["status"] != "succeeded":
                raise ValueError("revoked/failed result resurrected")
            status = "replayed"
        results.append(dict(query_id=query.identity, arm=item["arm"], status=status))
    result = dict(
        schema=PROFILE,
        results=results,
        replay_seconds=time.perf_counter() - begin,
        model_calls=0,
        is_new_task_evidence=False,
        production_accepted=False,
    )
    publish(output, result)
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    freezing = commands.add_parser("freeze")
    for name in ("sources", "policy", "output"):
        freezing.add_argument(name, type=Path)
    for name in ("source-sha", "policy-sha", "commit"):
        freezing.add_argument("--" + name, required=True)
    running = commands.add_parser("run")
    for name in ("plan", "inputs", "model", "frozen", "output"):
        running.add_argument(name, type=Path)
    for name in ("plan-sha", "stage-sha", "catalog-sha", "withdrawal-sha"):
        running.add_argument("--" + name, required=True)
    running.add_argument("--withdrawals", required=True, type=Path)
    replay = commands.add_parser("replay")
    for name in ("frozen", "receipt", "output"):
        replay.add_argument(name, type=Path)
    for name in ("catalog-sha", "receipt-sha", "withdrawal-sha"):
        replay.add_argument("--" + name, required=True)
    replay.add_argument("--withdrawals", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "freeze":
        print(
            freeze_all(
                args.sources,
                args.policy,
                args.output,
                source_sha=args.source_sha,
                policy_sha=args.policy_sha,
                commit=args.commit,
            )
        )
    elif args.command == "run":
        run(
            args.plan,
            args.inputs,
            args.model,
            args.frozen,
            args.output,
            plan_sha=args.plan_sha,
            stage_sha=args.stage_sha,
            catalog_sha=args.catalog_sha,
            withdrawal_path=args.withdrawals,
            withdrawal_sha=args.withdrawal_sha,
        )
    else:
        replay_all(
            args.frozen,
            args.receipt,
            args.output,
            catalog_sha=args.catalog_sha,
            receipt_sha=args.receipt_sha,
            withdrawal_path=args.withdrawals,
            withdrawal_sha=args.withdrawal_sha,
        )
