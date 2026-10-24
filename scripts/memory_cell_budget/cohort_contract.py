"""Frozen source/final separation and natural prospective enrollment rules."""

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import time

from budget_ledger import canonical, digest


def timestamp(value):
    value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("timezone-aware chronology required")
    return value


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def retain(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def load_registration(directory):
    directory = Path(directory)
    path = directory / "prospective-registration.json"
    receipt = json.loads((directory / "prospective-freeze-receipt.json").read_text())
    if file_sha(path) != receipt["protocol_sha256"]:
        raise ValueError("persisted prospective rules changed after registration")
    registration = json.loads(path.read_text())
    return registration, dict(receipt, canonical_protocol_sha256=digest(registration))


def failure_excerpt(raw, limit=1024):
    """Deterministic input compression, retaining original error/help statements.

    This is a bounded log excerpt task, not the complete multi-file repair context.
    No expected repair, final outcome or handcrafted question wording is accepted.
    """
    clean = re.sub(r"\x1b\[[0-9;]*m", "", raw.lstrip("\ufeff"))
    lines = [
        re.sub(r"^\d{4}-\d\d-\d\dT\S+Z\s*", "", line) for line in clean.splitlines()
    ]
    relevant = []
    for index, line in enumerate(lines):
        if re.search(
            r"^(?:error\b|F\d{3}\b|E\d{3}\b)|command not found|FAILED|OK \(skipped=|cannot update the lock",
            line,
            re.I,
        ):
            relevant.extend(lines[index : index + 3])
    text = "\n".join(dict.fromkeys(relevant or lines[-12:]))
    return text.encode()[:limit].decode("utf-8", errors="ignore")


def prospective_candidates(runs, registration, freeze_receipt, already_enrolled=()):
    if digest(registration) != freeze_receipt.get("canonical_protocol_sha256"):
        raise ValueError("prospective registration digest mismatch")
    start = max(
        timestamp(registration["registered_at"]),
        timestamp(freeze_receipt["effective_registered_at"]),
    )
    end = timestamp(registration["admission_deadline"])
    excluded = registration["exclusion"]
    seen = set(already_enrolled) | set(excluded["already_observed_run_ids"])
    candidates, rejected = [], []
    for run in sorted(runs, key=lambda r: (r["created_at"], r["id"])):
        reason = None
        created = timestamp(run["created_at"])
        if run["id"] in seen:
            reason = "already_seen_or_enrolled"
        elif {p["number"] for p in run.get("pull_requests", [])} & set(
            excluded.get("already_observed_prs", [])
        ):
            reason = "previously_observed_task_pr"
        elif not start < created <= end:
            reason = "outside_registered_future_window"
        elif run.get("status") != "completed" or run.get("conclusion") != "failure":
            reason = "not_a_completed_natural_failure_yet"
        elif any(
            x in run.get("head_branch", "")
            for x in excluded["this_research_branch_fragments"]
        ):
            reason = "own_research_branch"
        elif any(
            x in run.get("name", "").casefold()
            for x in excluded["this_research_workflow_fragments"]
        ):
            reason = "own_research_workflow"
        if reason:
            rejected.append(dict(run_id=run["id"], reason=reason))
        else:
            candidates.append(
                dict(
                    run_id=run["id"],
                    created_at=run["created_at"],
                    first_failure_updated_at=run["updated_at"],
                    head_sha=run["head_sha"],
                    workflow=run["path"],
                    branch=run["head_branch"],
                    group_annotation_pending=True,
                    repair_outcome="unresolved",
                    natural_origin_review_pending=True,
                    inference_completed=False,
                    scientific_confirmation=False,
                )
            )
    return dict(
        candidates=candidates,
        rejections=rejected,
        resolved_success_not_required=True,
        group_limit=registration["maximum_new_root_cause_groups"],
        candidate_rows_are_not_independent_groups=True,
    )


def seal(
    directory,
    *,
    protocol,
    source_documents,
    requests,
    task_metadata,
    code_paths,
    external_inputs=None,
):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    if len(requests) != len(task_metadata) or len(
        {r["task_id"] for r in requests}
    ) != len(requests):
        raise ValueError("one distinct original input per enrolled task required")
    for request, meta in zip(requests, task_metadata):
        if (
            set(request) != {"task_id", "text", "paths"}
            or request["task_id"] != meta["task_id"]
        ):
            raise ValueError("final requests cannot carry gold or outcome labels")
        if meta["classification"] not in (
            "historical_replay",
            "retrospective_time_holdout",
            "prospective_unresolved",
        ):
            raise ValueError("explicit evidence chronology required")
    source_groups = {r["group_id"] for r in source_documents}
    if source_groups & {m["root_cause_group"] for m in task_metadata}:
        raise ValueError("whole root-cause groups must be held out")
    for name, value in (
        ("protocol", protocol),
        ("source-documents", source_documents),
        ("requests", requests),
        ("task-metadata", task_metadata),
    ):
        retain(directory / f"{name}.json", value)
    code = {str(Path(p).resolve()): file_sha(p) for p in code_paths}
    retained = {p.name: file_sha(p) for p in sorted(directory.glob("*.json"))}
    receipt = dict(
        schema="hepta.memory-budget.seal.v1",
        files=retained,
        code=code,
        external_inputs=external_inputs or {},
        frozen_at_ns=time.time_ns(),
        final_predictions_exist=False,
        final_gold_in_inference_request=False,
        curator_has_seen_historical_repairs=True,
        blind_prospective_confirmation=False,
    )
    retain(directory / "seal.json", receipt)
    return receipt


def validate_seal(directory):
    directory = Path(directory)
    receipt = json.loads((directory / "seal.json").read_text())
    for name, expected in receipt["files"].items():
        if file_sha(directory / name) != expected:
            raise ValueError("frozen source, requests or method changed")
    for path, expected in receipt["code"].items():
        if file_sha(path) != expected:
            raise ValueError("executed evaluator source changed after freeze")
    for path, expected in receipt.get("external_inputs", {}).items():
        if file_sha(path) != expected:
            raise ValueError("original task log, fixture or registered tool changed")
    return receipt


def admit_prospective_score(meta, prediction, resolution):
    """A late-completed old run or a post-repair prediction cannot be future proof."""
    return bool(
        meta["classification"] == "prospective_unresolved"
        and not resolution["previously_seen_group"]
        and prediction["frozen_at_ns"] < resolution["earliest_repair_published_at_ns"]
        and prediction["frozen_at_ns"] < resolution["original_outcome_available_at_ns"]
        and resolution["original_execution_verified"] is True
    )
