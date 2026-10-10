"""Recompute the complete frozen-policy experiment from pinned original bytes.

This reads actual recorded model outputs; it cannot train, generate, repair an
answer or confer acceptance. Procedure verification and snapshot replay are
re-executed separately and never counted as new model/task observations.
"""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import re
import tempfile

from event_experience import call_worker
from event_memory_trial import strict_identifier
from event_projection import EventProjection
from experience_policy import INITIAL, choose, lookup_from_question, validate_policy
from frozen_memory_session import FrozenMemorySession
from frozen_policy_audit import summarize
from frozen_policy_trial import ARMS, replay_all
from lifecycle_accounting import Envelope, paired_task_contrasts, reuse_projection, summarize_envelopes
from native import Document, Question, digest
from native_citation import capture_native
from reader_reference_receipt import archive, sha
from span_supervision import strict_json

ANNOTATIONS = {"strict_task_success", "procedure_verification"}
PLAN_SHA = "9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897"


def align(raw, scored, cases):
    expected = {(q, a) for q in cases for a in ARMS}
    if (
        len(raw) != len(expected) or len(scored) != len(raw)
        or {(r["question_id"], r["arm"]) for r in raw} != expected
    ):
        raise ValueError("missing or duplicated original attempt")
    for original, row in zip(raw, scored, strict=True):
        case = cases[original["question_id"]]
        additions = set(row) - set(original)
        required = {"strict_task_success"} if original["status"] == "succeeded" else set()
        if original["status"] == "succeeded" and original["kind"] == "procedure":
            required.add("procedure_verification")
        if (
            ANNOTATIONS.intersection(original) or additions != required
            or any(row.get(key) != value for key, value in original.items())
            or set(original) - set(row)
            or original["query"] != case["query"]
            or original["kind"] != case["kind"]
            or original["candidate_digest"] != case["candidate_digest"]
        ):
            raise ValueError("original query, answer or metadata was changed")
    return scored


def replay(files, expected_source):
    def obj(name):
        return strict_json(files[name].decode("utf-8"))

    if not re.fullmatch(r"[0-9a-f]{40}", expected_source):
        raise ValueError("exact generating source required")
    if files["tested-commit.txt"].decode().strip() != expected_source:
        raise ValueError("generating source mismatch")
    execution = obj("experiment/execution.json")
    catalog = obj("sessions/CATALOG.json")
    plan_bytes = files["original-inputs/plan/plan.json"]
    if sha(plan_bytes) != PLAN_SHA or execution["plan_sha"] != PLAN_SHA:
        raise ValueError("fixed eight-case plan changed")
    if execution["catalog_sha"] != sha(files["sessions/CATALOG.json"]):
        raise ValueError("frozen catalogue pin changed")
    if execution["source_commit"] != expected_source or catalog["source_commit"] != expected_source:
        raise ValueError("source identity drift")
    plan = strict_json(plan_bytes.decode())
    if sha(files["original-inputs/plan/source-view.json"]) != plan["source_view_sha"]:
        raise ValueError("original source-view pin changed")
    if sha(files["original-inputs/observations/labels.json"]) != plan["labels_sha"]:
        raise ValueError("original label pin changed")
    originals = tuple(Document(**(d | {"assets": tuple(d["assets"])}))
                      for d in obj("original-inputs/plan/source-view.json"))
    if digest([asdict(d) for d in originals]) != catalog["source_documents_digest"]:
        raise ValueError("frozen source census drift")
    policy = obj("policy.json")
    if policy != catalog["policy"] or sha(files["policy.json"]) != catalog["policy_sha"]:
        raise ValueError("trained policy identity drift")
    inventory = obj("inventory.json")
    if digest(inventory["inventory"]) != inventory["inventory_digest"]:
        raise ValueError("reader inventory identity drift")
    cases = {c["query"]["identity"]: c for c in plan["cases"]}
    if len(cases) != 8 or len(plan["cases"]) != 8:
        raise ValueError("original eight-case census required")
    weights = validate_policy(policy, originals,
        reader_identity=inventory["inventory_digest"],
        test_scopes={c["query"]["scope"] for c in cases.values()}, revoked=set())
    raw = [strict_json(line) for line in files["experiment/raw-answers.jsonl"].decode().splitlines()]
    rows = align(raw, obj("experiment/scored-answers.json"), cases)
    replay_receipt = obj("experiment/REPLAY.json")
    if replay_receipt["raw_answers_sha"] != sha(files["experiment/raw-answers.jsonl"]):
        raise ValueError("result replay detached from raw answers")
    labels = {r["id"]: r for r in obj("original-inputs/observations/labels.json")}
    snapshots = {(r["scope"], r["arm"]): r for r in catalog["snapshots"]}
    selected_count = procedure_calls = 0
    with tempfile.TemporaryDirectory(prefix="hepta-policy-receipt-") as directory:
        root = Path(directory)
        # archive() already checks member paths, symlinks, sizes and inner hashes.
        for name, content in files.items():
            if name.startswith("sessions/") or name in {
                "experiment/REPLAY.json", "current-empty.json", "current-withdrawn.json"
            }:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
        for row in rows:
            if row["status"] != "succeeded":
                continue
            q = Question(**row["query"])
            case, arm = cases[q.identity], row["arm"]
            local = tuple(d for d in originals if d.scope == q.scope)
            if arm in ("hybrid", "organized"):
                selected = tuple(case["controls"][arm]["selected"])
            else:
                selected, _ = choose(EventProjection(local), lookup_from_question(q),
                    case["candidate_ids"], weights if arm == "learned" else INITIAL, revoked=set())
            if list(selected) != row["selected"] or not set(selected) <= set(case["candidate_ids"]):
                raise ValueError("actual selection differs from frozen policy")
            entry = snapshots[(q.scope, arm)]
            session = FrozenMemorySession(root / "sessions" / entry["directory"],
                                          expected_snapshot=entry["snapshot_sha"])
            value = session.replay(q, withdrawals=lambda: set(), expected_result_sha256=row["result_sha"])
            record = value["record"]
            if record != row["session_record"] or record["answer"] != row["answer"] or record["receipt"] != row["receipt"]:
                raise ValueError("raw answer detached from committed frozen session")
            spans = row["receipt"]["delivered_evidence"]
            source_map = {d.identity: d for d in local}
            if len(spans) != len(selected):
                raise ValueError("delivered source count drift")
            for span, source_id in zip(spans, selected, strict=True):
                doc = source_map[source_id]
                if span["root"] != doc.root or span["excerpt"] != doc.content:
                    raise ValueError("delivered original source bytes changed")
                selected_count += 1
            queue = capture_native(q, row["answer"],
                dict(input_ids_sha256=row["receipt"]["input_ids_digest"], delivered_evidence=spans),
                experiment_digest=digest((execution["catalog_sha"], PLAN_SHA, arm)),
                family_digest=digest(q.family))
            if queue != row["citation_audit"]:
                raise ValueError("citation request was repaired or detached")
            truth = labels[q.identity]
            identifier = strict_identifier(row["answer"])
            correct = identifier == truth["expected"]
            if truth["kind"] == "procedure":
                request = dict(operation="execute", recipe=truth["procedure"], supplied=identifier or "invalid_response")
                actual = call_worker(request)
                saved = row["procedure_verification"]
                if any(actual[k] != saved[k] for k in ("request", "stdout", "stderr", "exit_code")):
                    raise ValueError("fixed procedural outcome differs on replay")
                correct = actual["exit_code"] == 0
                procedure_calls += 1
            if row["strict_task_success"] != correct:
                raise ValueError("task score changed")
        for phase, expected_status in (("empty", "replayed"), ("withdrawn", "withdrawn")):
            output = root / (phase + "-result.json")
            replay_all(root / "sessions", root / "experiment/REPLAY.json", output,
                catalog_sha=execution["catalog_sha"], receipt_sha=sha(files["experiment/REPLAY.json"]),
                withdrawal_path=root / ("current-" + phase + ".json"),
                withdrawal_sha=sha(files["current-" + phase + ".json"]))
            replayed = strict_json(output.read_text())
            saved = obj("replay-" + phase + ".json")
            if replayed["results"] != saved["results"] or replayed["model_calls"] != 0 or any(r["status"] != expected_status for r in replayed["results"]):
                raise ValueError("restored-copy replay or current withdrawal differs")
    recomputed = summarize(rows, list(cases))
    report = obj("experiment/report.json")
    if any(report[k] != v for k, v in recomputed.items()):
        raise ValueError("published task summary differs from original records")
    for key in ("model_load_seconds", "measured_read_stage_seconds", "measured_snapshot_freeze_seconds"):
        if key not in report:
            raise ValueError("missing measured phase")
    report_sha, policy_sha = sha(files["experiment/report.json"]), sha(files["policy.json"])
    costs = summarize_envelopes([
        Envelope("extraction", "extract", report["measured_prior_extraction_seconds"], PLAN_SHA, "input-generation"),
        Envelope("index-and-plan", "index", report["measured_prior_planning_seconds"], PLAN_SHA, "input-generation"),
        Envelope("policy-write", "write", policy["write_seconds"], policy_sha, expected_source),
        Envelope("policy-train", "train", policy["training_seconds"], policy_sha, expected_source, "policy-write"),
        Envelope("snapshot-freeze", "write", catalog["freeze_seconds"], execution["catalog_sha"], expected_source),
        Envelope("read-stage", "read", report["measured_read_stage_seconds"], report_sha, expected_source),
        Envelope("model-load", "read", report["model_load_seconds"], report_sha, expected_source, "read-stage"),
        Envelope("backup-copy", "recover", obj("restore.json")["backup_restore_seconds"], sha(files["restore.json"]), expected_source),
        Envelope("backup-replay", "recover", obj("replay-empty.json")["replay_seconds"], sha(files["replay-empty.json"]), expected_source),
        Envelope("revoked-replay", "recover", obj("replay-withdrawn.json")["replay_seconds"], sha(files["replay-withdrawn.json"]), expected_source),
        Envelope("deployed-maintenance", "maintain", None, report_sha, "not-observed"),
    ])
    fixed = (report["measured_prior_extraction_seconds"] + report["measured_prior_planning_seconds"]
             + policy["write_seconds"] + catalog["freeze_seconds"] + report["model_load_seconds"])
    mean_read = (report["measured_read_stage_seconds"] - report["model_load_seconds"]) / len(rows)
    return dict(
        schema="hepta.frozen-policy.complete-cost-receipt.v1", generating_source=expected_source,
        raw_answers_sha256=sha(files["experiment/raw-answers.jsonl"]), all_attempts=len(rows),
        task_summary=recomputed, contrasts=paired_task_contrasts(rows, list(cases), ARMS, "learned"),
        delivered_original_spans_verified=selected_count, unsigned_citation_requests_reconstructed=len(rows),
        procedural_replay_calls=procedure_calls, new_model_calls=0,
        costs=costs,
        mixed_arm_study_projection=reuse_projection(fixed_seconds=fixed,
            read_seconds_per_query=mean_read, maintenance_seconds_per_query=None,
            recovery_seconds_per_query=None, queries=[1, 10, 100, 1000]),
        projection_is_not_per_arm_speedup=True,
        retained_archive_regular_bytes=sum(len(raw) for raw in files.values()),
        reader_bytes_referenced_not_downloaded=sum(v["bytes"] for v in inventory["inventory"].values()),
        retention_after_parameter_update=None, deployed_cross_host_recovery=None,
        independently_reviewed_sufficient_context=False, independent_snapshots=0,
        prospective_windows=0, semantic_citation_precision=None, production_accepted=False,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--archive-sha", required=True)
    parser.add_argument("--generating-source", required=True)
    args = parser.parse_args()
    files = archive(args.artifact, args.archive_sha)
    result = replay(files, args.generating_source)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
