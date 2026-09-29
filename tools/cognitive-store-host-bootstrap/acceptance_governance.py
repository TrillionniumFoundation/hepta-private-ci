#!/usr/bin/env python3
"""Verify independently signed cognitive.store acceptance evidence without effects.

The verifier authenticates external semantic, durability, security, operations
and release review receipts for one exact candidate and a coherent evidence
set. It never merges source, activates a host, publishes a generation, deletes
data, issues runtime authority or performs a release. Repository fixtures never
satisfy the current deployment's independent-acceptance gate.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import time
import uuid

from lifecycle import CLASSES, digest, exact, identifier, integer, load_bounded, require
from lifecycle import sha256, validate_trust, verify_signature

PLAN_SCHEMA = "hepta.cognitive.acceptance-plan.v5"
RECEIPT_SCHEMA = "hepta.cognitive.acceptance-receipt.v5"
REPORT_SCHEMA = "hepta.cognitive.acceptance-report.v5"
QUALIFICATION_PLAN_SCHEMA = "hepta.cognitive-store-qualification-plan.v1"
QUALIFICATION_SCHEMA = "hepta.cognitive-store-qualification-manifest.v2"
HOST_PLAN_SCHEMA = "hepta.cognitive.host-qualification-plan.v2"
HOST_REPORT_SCHEMA = "hepta.cognitive.host-qualification-report.v2"
RETENTION_PLAN_SCHEMA = "hepta.cognitive.retention-checkpoint-plan.v3"
RETENTION_REPORT_SCHEMA = "hepta.cognitive.retention-readiness-report.v3"
LIFECYCLE_PLAN_SCHEMA = "hepta.cognitive.lifecycle-plan.v1"
LIFECYCLE_REPORT_SCHEMA = "hepta.cognitive.lifecycle-reconciliation.v1"
GIT_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
QUALIFICATION_RECORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.json\Z")
SAFE_BASENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,255}\Z")
HOST_STEPS = (
    "bootstrap",
    "publication_fsync_fault",
    "canary",
    "crash_restart",
    "witness_gap_reconcile",
    "revocation",
    "rollback",
    "recovery_slo_256",
    "recovery_slo_16384",
)
REQUIRED_ROLES = (
    "semantic_review",
    "durability_review",
    "security_review",
    "operator_acceptance",
    "release_approval",
)
MAX_ROLES = 16
REPORT_EVIDENCE_FIELDS = (
    "source_head_manifest_sha256",
    "base_merge_manifest_sha256",
    "host_qualification_report_sha256",
    "retention_readiness_report_sha256",
    "lifecycle_reconciliation_report_sha256",
)
CONTEXT_PLAN_FIELDS = (
    "qualification_plan_sha256",
    "host_qualification_plan_sha256",
    "retention_checkpoint_plan_sha256",
    "lifecycle_plan_sha256",
)
EVIDENCE_FIELDS = REPORT_EVIDENCE_FIELDS + CONTEXT_PLAN_FIELDS


def git_oid(value: object, label: str) -> str:
    require(
        isinstance(value, str)
        and GIT_OID.fullmatch(value) is not None
        and set(value) != {"0"},
        f"invalid {label}",
    )
    return value


def canonical_agent(value: object) -> str:
    require(isinstance(value, str), "invalid Agent identity")
    require(str(uuid.UUID(value)) == value, "noncanonical Agent identity")
    return value


def require_false(report: dict, fields: tuple[str, ...], label: str) -> None:
    for field in fields:
        require(
            report.get(field) is False,
            f"{label} escalates or omits the forbidden claim: {field}",
        )


def validate_qualification_plan(plan: object) -> dict:
    exact(
        plan,
        {"schema", "module", "commands", "evidence", "targetHostQualification"},
    )
    require(
        plan["schema"] == QUALIFICATION_PLAN_SCHEMA
        and plan["module"] == "cognitive.store"
        and plan["targetHostQualification"] is False,
        "unsupported qualification plan evidence",
    )
    commands = plan["commands"]
    require(
        isinstance(commands, list) and 1 <= len(commands) <= 128,
        "qualification plan has missing or excessive commands",
    )
    records = {}
    for item in commands:
        required = {
            "record",
            "command",
            "cwd",
            "minimumTests",
            "native",
            "timeoutSeconds",
        }
        require(
            isinstance(item, dict)
            and required <= set(item) <= required | {"env"},
            "qualification plan command has missing or unknown fields",
        )
        record = item["record"]
        require(
            isinstance(record, str)
            and QUALIFICATION_RECORD.fullmatch(record) is not None
            and record not in records,
            "qualification plan has a duplicate or unsafe record",
        )
        argv = item["command"]
        require(
            isinstance(argv, list)
            and 1 <= len(argv) <= 128
            and all(isinstance(value, str) and value and "\0" not in value for value in argv),
            "qualification plan command is empty or malformed",
        )
        cwd = item["cwd"]
        require(
            isinstance(cwd, str)
            and cwd
            and not Path(cwd).is_absolute()
            and ".." not in Path(cwd).parts
            and "\\" not in cwd,
            "qualification plan working directory is unsafe",
        )
        minimum = item["minimumTests"]
        timeout = item["timeoutSeconds"]
        require(
            type(minimum) is int and 0 <= minimum <= 1_000_000,
            "qualification plan minimum test count is invalid",
        )
        require(
            type(timeout) is int and 1 <= timeout <= 21_600,
            "qualification plan timeout is invalid",
        )
        require(type(item["native"]) is bool, "qualification plan native flag is invalid")
        environment = item.get("env", {})
        require(
            isinstance(environment, dict)
            and len(environment) <= 32
            and all(
                isinstance(key, str)
                and isinstance(value, str)
                and key
                and value
                and "\0" not in key + value
                for key, value in environment.items()
            ),
            "qualification plan workload environment is invalid",
        )
        records[record] = item

    evidence = plan["evidence"]
    require(
        isinstance(evidence, list) and len(evidence) <= 128,
        "qualification plan evidence inventory is invalid",
    )
    evidence_names = []
    for value in evidence:
        require(
            isinstance(value, str) and value and "\0" not in value,
            "qualification plan evidence path is invalid",
        )
        name = Path(value).name
        require(
            QUALIFICATION_RECORD.fullmatch(name) is not None
            and name not in evidence_names,
            "qualification plan evidence name is duplicate or unsafe",
        )
        evidence_names.append(name)
    return {
        "plan": plan,
        "records": records,
        "evidence_names": frozenset(evidence_names),
    }


def validate_qualification_manifest(
    report: object,
    plan: dict,
    lane: str,
    qualification: dict,
) -> dict:
    exact(
        report,
        {
            "schema",
            "sourceSha",
            "sourceTree",
            "baseSha",
            "baseTree",
            "testedSha",
            "testedTree",
            "parents",
            "workflowBlob",
            "requestedIdentity",
            "identityErrors",
            "lane",
            "runId",
            "runAttempt",
            "job",
            "workflowSha",
            "workflowRef",
            "runner",
            "toolchain",
            "generatedAt",
            "commands",
            "evidence",
            "result",
            "executionComplete",
            "targetHostQualified",
            "independentAcceptance",
            "release",
        },
    )
    require(
        report.get("schema") == QUALIFICATION_SCHEMA,
        "unsupported qualification manifest evidence",
    )
    require(report.get("lane") == lane, "qualification evidence belongs to another lane")
    require(
        report.get("sourceSha") == plan["source_commit"]
        and report.get("sourceTree") == plan["source_tree"],
        "qualification evidence belongs to another source",
    )
    require(
        report.get("result") == "terminal-success"
        and report.get("executionComplete") is True,
        "qualification evidence is not terminal-success",
    )
    require(
        report.get("identityErrors") == [],
        "qualification evidence contains candidate identity errors",
    )
    git_oid(report.get("testedSha"), "qualification tested commit")
    git_oid(report.get("testedTree"), "qualification tested tree")
    git_oid(report.get("baseSha"), "qualification base commit")
    git_oid(report.get("baseTree"), "qualification base tree")
    git_oid(report.get("workflowBlob"), "qualification workflow blob")
    git_oid(report.get("workflowSha"), "qualification workflow source")
    require(
        isinstance(report["runId"], str)
        and report["runId"]
        and isinstance(report["runAttempt"], str)
        and report["runAttempt"]
        and isinstance(report["job"], str)
        and report["job"]
        and isinstance(report["workflowRef"], str)
        and report["workflowRef"],
        "qualification workflow identity is incomplete",
    )
    require(
        isinstance(report["generatedAt"], str) and report["generatedAt"],
        "qualification generation timestamp is absent",
    )
    requested = report["requestedIdentity"]
    exact(
        requested,
        {
            "tested_sha",
            "source_sha",
            "base_sha",
            "lane",
            "run_id",
            "run_attempt",
            "tested_tree",
        },
    )
    require(
        requested
        == {
            "tested_sha": report["testedSha"],
            "source_sha": report["sourceSha"],
            "base_sha": report["baseSha"],
            "lane": lane,
            "run_id": report["runId"],
            "run_attempt": report["runAttempt"],
            "tested_tree": report["testedTree"],
        },
        "qualification requested identity differs from the tested candidate",
    )
    runner = report["runner"]
    exact(runner, {"RUNNER_NAME", "RUNNER_OS", "RUNNER_ARCH", "ImageOS", "ImageVersion"})
    require(
        all(isinstance(value, str) and value for value in runner.values()),
        "qualification runner identity is incomplete",
    )
    toolchain = report["toolchain"]
    exact(toolchain, {"rustc", "cargo", "python"})
    require(
        all(isinstance(value, str) and value for value in toolchain.values()),
        "qualification toolchain identity is incomplete",
    )
    commands = report.get("commands")
    expected_records = qualification["records"]
    require(
        isinstance(commands, list)
        and tuple(row.get("name") for row in commands if isinstance(row, dict))
        == tuple(sorted(expected_records)),
        "qualification evidence command inventory differs from the committed plan",
    )
    logs = set()
    for row in commands:
        exact(
            row,
            {
                "name",
                "status",
                "reason",
                "recordSha256",
                "recordedStatus",
                "command",
                "commandExitCode",
                "wrapperExitCode",
                "observedPassedTests",
                "observedFailedTests",
                "minimumTests",
                "timedOut",
                "outputLimitExceeded",
                "diagnostic",
                "commandSpecSha256",
                "logName",
                "logBytes",
                "logSha256",
            },
        )
        expected = expected_records[row["name"]]
        require(
            row["status"] == "passed"
            and row["recordedStatus"] == "passed"
            and row["reason"] is None
            and row["commandExitCode"] == 0
            and row["wrapperExitCode"] == 0
            and row["timedOut"] is False
            and row["outputLimitExceeded"] is False
            and row["observedFailedTests"] == 0,
            "qualification evidence contains a non-passing command record",
        )
        require(
            isinstance(row["command"], list)
            and row["command"]
            and all(isinstance(value, str) and value for value in row["command"]),
            "qualification command record is malformed",
        )
        minimum = expected["minimumTests"]
        require(
            row["minimumTests"] == minimum
            and type(row["observedPassedTests"]) is int
            and row["observedPassedTests"] >= minimum,
            "qualification command test threshold differs from the committed plan",
        )
        for field in ("recordSha256", "commandSpecSha256", "logSha256"):
            digest(row[field])
        require(
            isinstance(row["logName"], str)
            and SAFE_BASENAME.fullmatch(row["logName"]) is not None
            and row["logName"] not in logs,
            "qualification command log identity is duplicate or unsafe",
        )
        logs.add(row["logName"])
        integer(row["logBytes"], 0)
    retained = report.get("evidence")
    require(
        isinstance(retained, list)
        and {row.get("name") for row in retained if isinstance(row, dict)}
        == qualification["evidence_names"]
        and len(retained) == len(qualification["evidence_names"]),
        "qualification retained-evidence inventory differs from the committed plan",
    )
    for row in retained:
        exact(row, {"name", "status", "bytes", "sha256"})
        require(row["status"] == "retained", "qualification evidence artifact is not retained")
        integer(row["bytes"], 0)
        digest(row["sha256"])
    require_false(
        report,
        ("targetHostQualified", "independentAcceptance", "release"),
        "qualification evidence",
    )
    if lane == "source-head":
        require(
            report.get("testedSha") == plan["source_commit"]
            and report.get("testedTree") == plan["source_tree"],
            "source-head evidence did not test the exact source",
        )
    else:
        parents = report.get("parents")
        require(
            isinstance(parents, list)
            and len(parents) == 2
            and report.get("baseSha") == parents[0]
            and report.get("sourceSha") == parents[1]
            and parents[1] == plan["source_commit"]
            and report.get("testedSha") not in parents,
            "base-merge evidence does not bind its frozen base/source parents",
        )
        git_oid(parents[0], "qualification frozen base")
    return report


def validate_host_plan(host_plan: object, acceptance_plan: dict) -> dict:
    exact(
        host_plan,
        {
            "schema",
            "request_id",
            "owner_agent_id",
            "source_commit",
            "source_tree",
            "writer_generation",
            "authority_grant_sha256",
            "rollback_writer_generation",
            "rollback_generation_floor",
            "rollback_authority_grant_sha256",
            "recovery_anchor",
            "witness_custody_sha256",
            "host_identity_sha256",
            "filesystem_identity_sha256",
            "slo_profile_sha256",
            "created_at",
            "expires_at",
            "steps",
        },
    )
    require(host_plan["schema"] == HOST_PLAN_SCHEMA, "unsupported selected-host plan evidence")
    require(
        host_plan["owner_agent_id"] == acceptance_plan["owner_agent_id"],
        "selected-host plan belongs to another Agent",
    )
    require(
        host_plan["source_commit"] == acceptance_plan["source_commit"]
        and host_plan["source_tree"] == acceptance_plan["source_tree"],
        "selected-host plan belongs to another source",
    )
    git_oid(host_plan["source_commit"], "selected-host source commit")
    git_oid(host_plan["source_tree"], "selected-host source tree")
    for field in ("writer_generation", "rollback_generation_floor", "rollback_writer_generation"):
        integer(host_plan[field])
    require(
        host_plan["rollback_generation_floor"] > host_plan["writer_generation"]
        and host_plan["rollback_writer_generation"] >= host_plan["rollback_generation_floor"],
        "selected-host plan has an invalid rollback generation context",
    )
    for field in (
        "authority_grant_sha256",
        "rollback_authority_grant_sha256",
        "witness_custody_sha256",
        "host_identity_sha256",
        "filesystem_identity_sha256",
        "slo_profile_sha256",
    ):
        digest(host_plan[field])
    require(
        host_plan["authority_grant_sha256"]
        != host_plan["rollback_authority_grant_sha256"],
        "selected-host plan reuses the initial authority grant",
    )
    anchor = host_plan["recovery_anchor"]
    exact(anchor, {"profile", "owner_agent_id", "schema_digest", "state_digest"})
    require(
        anchor["profile"] == "hepta:cognitive:exact-current-cut:v1"
        and anchor["owner_agent_id"] == acceptance_plan["owner_agent_id"],
        "selected-host plan has a foreign or unsupported recovery witness",
    )
    digest(anchor["schema_digest"])
    digest(anchor["state_digest"])
    steps = host_plan["steps"]
    require(
        isinstance(steps, list)
        and len(steps) == len(HOST_STEPS)
        and all(isinstance(row, dict) for row in steps)
        and {row.get("step") for row in steps} == set(HOST_STEPS),
        "selected-host plan contains incomplete or duplicate steps",
    )
    return host_plan


def validate_host_report(report: object, host_plan: dict) -> dict:
    exact(
        report,
        {
            "schema",
            "plan_sha256",
            "trust_sha256",
            "observed_at",
            "initial_cut_sha256",
            "qualified_cut_sha256",
            "initial_writer_generation",
            "rollback_generation_floor",
            "rollback_writer_generation",
            "qualified_writer_generation",
            "initial_authority_grant_sha256",
            "rollback_authority_grant_sha256",
            "qualified_authority_grant_sha256",
            "steps",
            "all_required_owner_receipts_verified",
            "result",
            "target_host_qualified",
            "slo_accepted",
            "activation_authorized",
            "release_authorized",
        },
    )
    require(report["schema"] == HOST_REPORT_SCHEMA, "unsupported selected-host qualification evidence")
    require(report["plan_sha256"] == sha256(host_plan), "selected-host report binds another plan")
    require(
        report["result"] == "owner_attested_complete"
        and report["all_required_owner_receipts_verified"] is True,
        "selected-host qualification evidence is incomplete",
    )
    steps = report["steps"]
    require(
        isinstance(steps, list)
        and tuple(row.get("step") for row in steps if isinstance(row, dict)) == HOST_STEPS
        and all(row.get("status") == "completed" for row in steps),
        "selected-host qualification evidence contains incomplete or reordered steps",
    )
    for row in steps:
        exact(row, {"step", "executor", "status", "verified_receipt_sha256"})
        identifier(row["executor"])
        digest(row["verified_receipt_sha256"])
    for field in (
        "initial_cut_sha256",
        "qualified_cut_sha256",
        "initial_authority_grant_sha256",
        "rollback_authority_grant_sha256",
        "qualified_authority_grant_sha256",
        "trust_sha256",
    ):
        digest(report[field])
    for field in (
        "initial_writer_generation",
        "rollback_generation_floor",
        "rollback_writer_generation",
        "qualified_writer_generation",
        "observed_at",
    ):
        integer(report[field])
    require(
        report["initial_cut_sha256"] == host_plan["recovery_anchor"]["state_digest"]
        and report["initial_writer_generation"] == host_plan["writer_generation"]
        and report["rollback_generation_floor"] == host_plan["rollback_generation_floor"]
        and report["rollback_writer_generation"] == host_plan["rollback_writer_generation"]
        and report["qualified_writer_generation"] == host_plan["rollback_writer_generation"]
        and report["initial_authority_grant_sha256"] == host_plan["authority_grant_sha256"]
        and report["rollback_authority_grant_sha256"]
        == host_plan["rollback_authority_grant_sha256"]
        and report["qualified_authority_grant_sha256"]
        == host_plan["rollback_authority_grant_sha256"],
        "selected-host qualification evidence has an invalid final writer context",
    )
    require_false(
        report,
        ("target_host_qualified", "slo_accepted", "activation_authorized", "release_authorized"),
        "selected-host qualification evidence",
    )
    return report


def validate_retention_plan(retention_plan: object, acceptance_plan: dict) -> dict:
    exact(
        retention_plan,
        {
            "schema",
            "request_id",
            "owner_agent_id",
            "source_commit",
            "source_tree",
            "writer_generation",
            "schema_sha256",
            "current_cut_sha256",
            "head_set_sha256",
            "tombstone_frontier",
            "source_frontier",
            "fact_frontier",
            "kg_frontier",
            "policy_sha256",
            "hold_state_sha256",
            "pending_operations_sha256",
            "predecessor_image_sha256",
            "successor_image_sha256",
            "successor_image_bytes",
            "segment_set_sha256",
            "segment_count",
            "segment_row_count",
            "first_segment_manifest_sha256",
            "last_segment_manifest_sha256",
            "rebuild_owner",
            "created_at",
            "expires_at",
            "segments",
        },
    )
    require(retention_plan["schema"] == RETENTION_PLAN_SCHEMA, "unsupported retention plan evidence")
    require(
        retention_plan["owner_agent_id"] == acceptance_plan["owner_agent_id"],
        "retention plan belongs to another Agent",
    )
    require(
        retention_plan["source_commit"] == acceptance_plan["source_commit"]
        and retention_plan["source_tree"] == acceptance_plan["source_tree"],
        "retention plan belongs to another source",
    )
    git_oid(retention_plan["source_commit"], "retention source commit")
    git_oid(retention_plan["source_tree"], "retention source tree")
    integer(retention_plan["writer_generation"])
    for field in (
        "schema_sha256",
        "current_cut_sha256",
        "head_set_sha256",
        "policy_sha256",
        "hold_state_sha256",
        "pending_operations_sha256",
        "predecessor_image_sha256",
        "successor_image_sha256",
        "segment_set_sha256",
        "first_segment_manifest_sha256",
        "last_segment_manifest_sha256",
    ):
        digest(retention_plan[field])
    for field in (
        "tombstone_frontier",
        "source_frontier",
        "fact_frontier",
        "kg_frontier",
    ):
        integer(retention_plan[field], 0)
    for field in ("successor_image_bytes", "segment_count", "segment_row_count"):
        integer(retention_plan[field])
    segments = retention_plan["segments"]
    require(
        isinstance(segments, list)
        and segments
        and retention_plan["segment_count"] == len(segments)
        and retention_plan["segment_set_sha256"] == sha256(segments)
        and retention_plan["segment_row_count"]
        == sum(row.get("row_count", 0) for row in segments if isinstance(row, dict)),
        "retention plan has an inconsistent segment aggregate",
    )
    return retention_plan


def validate_retention_report(report: object, retention_plan: dict) -> dict:
    exact(
        report,
        {
            "schema",
            "plan_sha256",
            "trust_sha256",
            "observed_at",
            "segment_set_sha256",
            "segment_count",
            "segment_row_count",
            "segments",
            "rebuild_status",
            "verified_rebuild_receipt_sha256",
            "all_required_owner_receipts_verified",
            "result",
            "successor_published",
            "hot_history_pruned",
            "predecessor_erased",
            "physical_erasure_proved",
            "activation_authorized",
        },
    )
    require(report["schema"] == RETENTION_REPORT_SCHEMA, "unsupported retention readiness evidence")
    require(report["plan_sha256"] == sha256(retention_plan), "retention report binds another plan")
    require(
        report["result"] == "retention_ready"
        and report["all_required_owner_receipts_verified"] is True,
        "retention readiness evidence is incomplete",
    )
    segments = report["segments"]
    require(
        isinstance(segments, list)
        and segments
        and all(isinstance(row, dict) and row.get("status") == "completed" for row in segments)
        and report["rebuild_status"] == "completed",
        "retention readiness evidence contains incomplete segment or rebuild receipts",
    )
    for row in segments:
        exact(row, {"segment_id", "storage_owner", "status", "verified_receipt_sha256"})
        identifier(row["segment_id"])
        identifier(row["storage_owner"])
        digest(row["verified_receipt_sha256"])
    for field in ("segment_count", "segment_row_count", "observed_at"):
        integer(report[field])
    for field in ("segment_set_sha256", "verified_rebuild_receipt_sha256", "trust_sha256"):
        digest(report[field])
    require(
        report["segment_count"] == len(segments)
        and report["segment_count"] == retention_plan["segment_count"]
        and report["segment_row_count"] == retention_plan["segment_row_count"]
        and report["segment_set_sha256"] == retention_plan["segment_set_sha256"],
        "retention readiness evidence differs from its signed segment aggregate",
    )
    require_false(
        report,
        (
            "successor_published",
            "hot_history_pruned",
            "predecessor_erased",
            "physical_erasure_proved",
            "activation_authorized",
        ),
        "retention readiness evidence",
    )
    return report


def validate_lifecycle_plan(lifecycle_plan: object, acceptance_plan: dict) -> dict:
    exact(
        lifecycle_plan,
        {
            "schema",
            "request_id",
            "owner_agent_id",
            "writer_generation",
            "cut_sha256",
            "policy_sha256",
            "inventory_sha256",
            "created_at",
            "obligations",
        },
    )
    require(lifecycle_plan["schema"] == LIFECYCLE_PLAN_SCHEMA, "unsupported lifecycle plan evidence")
    require(
        lifecycle_plan["owner_agent_id"] == acceptance_plan["owner_agent_id"],
        "lifecycle plan belongs to another Agent",
    )
    integer(lifecycle_plan["writer_generation"])
    for field in ("cut_sha256", "policy_sha256", "inventory_sha256"):
        digest(lifecycle_plan[field])
    obligations = lifecycle_plan["obligations"]
    require(
        isinstance(obligations, list)
        and obligations
        and {row.get("storage_class") for row in obligations if isinstance(row, dict)} == CLASSES,
        "lifecycle plan omits or invents a storage class",
    )
    return lifecycle_plan


def validate_lifecycle_report(report: object, lifecycle_plan: dict) -> dict:
    exact(
        report,
        {
            "schema",
            "plan_sha256",
            "trust_sha256",
            "observed_at",
            "obligations",
            "all_required_owner_receipts_verified",
            "result",
            "authorized_effects",
            "physical_erasure_independently_proved",
            "target_host_qualified",
        },
    )
    require(report["schema"] == LIFECYCLE_REPORT_SCHEMA, "unsupported lifecycle reconciliation evidence")
    require(report["plan_sha256"] == sha256(lifecycle_plan), "lifecycle report binds another plan")
    require(
        report["result"] == "owner_attested_complete"
        and report["all_required_owner_receipts_verified"] is True,
        "lifecycle reconciliation evidence is incomplete",
    )
    obligations = report["obligations"]
    require(
        isinstance(obligations, list)
        and obligations
        and all(isinstance(row, dict) and row.get("status") == "completed" for row in obligations),
        "lifecycle reconciliation evidence contains incomplete obligations",
    )
    require(
        {row.get("storage_class") for row in obligations} == CLASSES,
        "lifecycle reconciliation evidence omits or invents a storage class",
    )
    evidence_identities = set()
    for row in obligations:
        exact(
            row,
            {
                "storage_class",
                "storage_owner",
                "requirement",
                "inventory_sha256",
                "status",
                "verified_receipt_sha256",
                "verified_evidence_sha256",
            },
        )
        identifier(row["storage_owner"])
        require(
            row["requirement"] in {"erase", "unlearn", "not_applicable"},
            "lifecycle reconciliation evidence has an unknown requirement",
        )
        for field in (
            "inventory_sha256",
            "verified_receipt_sha256",
            "verified_evidence_sha256",
        ):
            digest(row[field])
        require(
            row["verified_evidence_sha256"] not in evidence_identities,
            "lifecycle reconciliation evidence reuses one owner evidence identity",
        )
        evidence_identities.add(row["verified_evidence_sha256"])
    digest(report["trust_sha256"])
    integer(report["observed_at"])
    require_false(
        report,
        ("authorized_effects", "physical_erasure_independently_proved", "target_host_qualified"),
        "lifecycle reconciliation evidence",
    )
    return report


def validate_evidence_bundle(bundle: object, plan: dict) -> dict:
    exact(bundle, set(EVIDENCE_FIELDS))
    for field in EVIDENCE_FIELDS:
        require(
            sha256(bundle[field]) == plan[field],
            "acceptance evidence digest differs from the signed plan: " + field,
        )

    qualification = validate_qualification_plan(bundle["qualification_plan_sha256"])
    validate_qualification_manifest(
        bundle["source_head_manifest_sha256"],
        plan,
        "source-head",
        qualification,
    )
    validate_qualification_manifest(
        bundle["base_merge_manifest_sha256"],
        plan,
        "base-merge",
        qualification,
    )

    host_plan = validate_host_plan(bundle["host_qualification_plan_sha256"], plan)
    host_report = validate_host_report(bundle["host_qualification_report_sha256"], host_plan)
    retention_plan = validate_retention_plan(bundle["retention_checkpoint_plan_sha256"], plan)
    retention_report = validate_retention_report(
        bundle["retention_readiness_report_sha256"], retention_plan
    )
    lifecycle_plan = validate_lifecycle_plan(bundle["lifecycle_plan_sha256"], plan)
    lifecycle_report = validate_lifecycle_report(
        bundle["lifecycle_reconciliation_report_sha256"], lifecycle_plan
    )

    qualified_cut = host_report["qualified_cut_sha256"]
    qualified_generation = host_report["qualified_writer_generation"]
    require(
        retention_plan["current_cut_sha256"] == qualified_cut
        and retention_plan["writer_generation"] == qualified_generation,
        "retention evidence is not bound to the selected-host qualified cut and writer generation",
    )
    require(
        lifecycle_plan["cut_sha256"] == qualified_cut
        and lifecycle_plan["writer_generation"] == qualified_generation,
        "lifecycle evidence is not bound to the selected-host qualified cut and writer generation",
    )
    require(
        retention_plan["current_cut_sha256"] == lifecycle_plan["cut_sha256"]
        and retention_plan["writer_generation"] == lifecycle_plan["writer_generation"],
        "retention and lifecycle evidence describe different owner contexts",
    )
    return {
        "qualified_cut_sha256": qualified_cut,
        "qualified_writer_generation": qualified_generation,
        "qualification_plan_sha256": sha256(qualification["plan"]),
        "host_plan_sha256": sha256(host_plan),
        "retention_plan_sha256": sha256(retention_plan),
        "lifecycle_plan_sha256": sha256(lifecycle_plan),
        "reports": {
            "host": host_report,
            "retention": retention_report,
            "lifecycle": lifecycle_report,
        },
    }


def validate_plan(plan: object, trust: dict, now: int) -> dict:
    exact(
        plan,
        {
            "schema",
            "request_id",
            "owner_agent_id",
            "source_commit",
            "source_tree",
            *EVIDENCE_FIELDS,
            "created_at",
            "expires_at",
            "roles",
        },
    )
    require(plan["schema"] == PLAN_SCHEMA, "unsupported acceptance plan")
    identifier(plan["request_id"])
    canonical_agent(plan["owner_agent_id"])
    git_oid(plan["source_commit"], "source commit")
    git_oid(plan["source_tree"], "source tree")
    require(
        len(plan["source_commit"]) == len(plan["source_tree"]),
        "source commit and tree use different object formats",
    )
    for field in EVIDENCE_FIELDS:
        digest(plan[field])
    integer(plan["created_at"])
    integer(plan["expires_at"])
    require(
        plan["created_at"] <= now < plan["expires_at"],
        "acceptance plan is future, expired or has an invalid interval",
    )

    trusted = validate_trust(trust, now)
    coordinator = trust["coordinator"]["signer_id"]
    roles = plan["roles"]
    require(
        isinstance(roles, list)
        and len(roles) == len(REQUIRED_ROLES)
        and len(roles) <= MAX_ROLES,
        "acceptance role set is incomplete",
    )
    observed = {}
    reviewers = set()
    for row in roles:
        exact(row, {"role", "reviewer", "criteria_sha256"})
        require(
            row["role"] in REQUIRED_ROLES and row["role"] not in observed,
            "unknown or duplicate acceptance role",
        )
        identifier(row["reviewer"])
        require(
            row["reviewer"] in trusted and row["reviewer"] != coordinator,
            "acceptance reviewer is not independently trusted",
        )
        require(
            row["reviewer"] not in reviewers,
            "acceptance roles must use distinct independent reviewers",
        )
        digest(row["criteria_sha256"])
        reviewers.add(row["reviewer"])
        observed[row["role"]] = row
    require(
        tuple(role for role in REQUIRED_ROLES if role in observed) == REQUIRED_ROLES,
        "acceptance roles are incomplete",
    )
    return plan


def validate_receipt(receipt: object, plan: dict, role: dict, now: int) -> dict:
    exact(
        receipt,
        {
            "schema",
            "plan_sha256",
            "role",
            "reviewer",
            "criteria_sha256",
            "owner_agent_id",
            "source_commit",
            "source_tree",
            *EVIDENCE_FIELDS,
            "decision",
            "observed_at",
            "review_sha256",
        },
    )
    require(receipt["schema"] == RECEIPT_SCHEMA, "unsupported acceptance receipt")
    require(receipt["plan_sha256"] == sha256(plan), "acceptance receipt binds another plan")
    require(
        receipt["role"] == role["role"] and receipt["reviewer"] == role["reviewer"],
        "acceptance receipt role or reviewer differs from the signed plan",
    )
    require(
        receipt["criteria_sha256"] == role["criteria_sha256"],
        "acceptance receipt criteria differ from the signed plan",
    )
    for field in ("owner_agent_id", "source_commit", "source_tree", *EVIDENCE_FIELDS):
        require(
            receipt[field] == plan[field],
            "acceptance receipt identity differs from the signed plan: " + field,
        )
    require(
        receipt["decision"] in {"approved", "rejected", "pending", "indeterminate"},
        "unknown acceptance decision",
    )
    integer(receipt["observed_at"])
    require(
        plan["created_at"] <= receipt["observed_at"] <= now,
        "acceptance receipt is stale or from the future",
    )
    digest(receipt["review_sha256"])
    return receipt


def reconcile(
    plan_envelope: object,
    receipt_envelopes: object,
    evidence_bundle: object,
    trust: dict,
    now: int,
    expected_plan_sha256: str,
) -> dict:
    integer(now)
    digest(expected_plan_sha256)
    trusted = validate_trust(trust, now)
    plan = verify_signature(plan_envelope, trust["coordinator"])
    validate_plan(plan, trust, now)
    require(
        sha256(plan) == expected_plan_sha256,
        "acceptance plan differs from the requested operation",
    )
    context = validate_evidence_bundle(evidence_bundle, plan)
    require(
        isinstance(receipt_envelopes, list) and len(receipt_envelopes) <= MAX_ROLES,
        "acceptance receipt budget exceeded",
    )
    expected = {row["role"]: row for row in plan["roles"]}
    observed = {}
    review_evidence = set()
    bound_evidence = {plan[field] for field in EVIDENCE_FIELDS}
    for envelope in receipt_envelopes:
        require(isinstance(envelope, dict), "invalid acceptance receipt envelope")
        signer = trusted.get(envelope.get("signer_id"))
        require(
            signer is not None and signer["signer_id"] != trust["coordinator"]["signer_id"],
            "unknown or coordinator acceptance signer",
        )
        receipt = verify_signature(envelope, signer)
        role_name = receipt.get("role") if isinstance(receipt, dict) else None
        require(
            role_name in expected and role_name not in observed,
            "unknown or duplicate acceptance receipt",
        )
        require(
            signer["signer_id"] == expected[role_name]["reviewer"],
            "acceptance receipt signer is not the planned reviewer",
        )
        receipt = validate_receipt(receipt, plan, expected[role_name], now)
        require(
            receipt["review_sha256"] not in review_evidence,
            "acceptance roles reuse one review evidence identity",
        )
        require(
            receipt["review_sha256"] not in bound_evidence,
            "acceptance review evidence reuses a bound plan or report identity",
        )
        review_evidence.add(receipt["review_sha256"])
        observed[role_name] = receipt

    last_observed = None
    for index, name in enumerate(REQUIRED_ROLES):
        receipt = observed.get(name)
        if receipt is None:
            continue
        if receipt["decision"] == "approved":
            for predecessor_name in REQUIRED_ROLES[:index]:
                predecessor = observed.get(predecessor_name)
                if predecessor is not None:
                    require(
                        predecessor["decision"] == "approved",
                        f"{name} approval follows non-approved prerequisite {predecessor_name}",
                    )
        if last_observed is not None:
            require(
                receipt["observed_at"] >= last_observed,
                "acceptance approvals regress in required review order",
            )
        last_observed = receipt["observed_at"]

    rows = []
    for name in REQUIRED_ROLES:
        receipt = observed.get(name)
        rows.append(
            {
                "role": name,
                "reviewer": expected[name]["reviewer"],
                "decision": receipt["decision"] if receipt else "missing",
                "verified_receipt_sha256": sha256(receipt) if receipt else None,
            }
        )
    complete = all(row["decision"] == "approved" for row in rows)
    return {
        "schema": REPORT_SCHEMA,
        "plan_sha256": sha256(plan),
        "trust_sha256": sha256(trust),
        "observed_at": now,
        "owner_agent_id": plan["owner_agent_id"],
        "source_commit": plan["source_commit"],
        "source_tree": plan["source_tree"],
        **{field: plan[field] for field in EVIDENCE_FIELDS},
        "qualified_cut_sha256": context["qualified_cut_sha256"],
        "qualified_writer_generation": context["qualified_writer_generation"],
        "all_bound_evidence_reports_validated": True,
        "all_bound_evidence_context_coherent": True,
        "roles": rows,
        "all_required_independent_approvals_verified": complete,
        "result": "external_approval_set_verified" if complete else "incomplete",
        "independent_acceptance_verified": complete,
        "authorized_effects": False,
        "activation_performed": False,
        "release_performed": False,
    }


def reconcile_files(
    plan_path: Path,
    receipts_path: Path,
    evidence_path: Path,
    trust_path: Path,
    expected_plan_sha256: str,
    expected_trust_sha256: str,
) -> dict:
    digest(expected_plan_sha256)
    digest(expected_trust_sha256)
    trust = load_bounded(trust_path)
    require(
        sha256(trust) == expected_trust_sha256,
        "acceptance trust differs from the installed identity",
    )
    plan_envelope = load_bounded(plan_path)
    receipts = load_bounded(receipts_path)
    evidence_bundle = load_bounded(evidence_path)
    started = int(time.time())
    report = reconcile(
        plan_envelope,
        receipts,
        evidence_bundle,
        trust,
        started,
        expected_plan_sha256,
    )
    require(
        sha256(load_bounded(plan_path)) == sha256(plan_envelope),
        "acceptance plan changed during verification",
    )
    require(
        sha256(load_bounded(receipts_path)) == sha256(receipts),
        "acceptance receipt set changed during verification",
    )
    require(
        sha256(load_bounded(evidence_path)) == sha256(evidence_bundle),
        "acceptance evidence bundle changed during verification",
    )
    current_trust = load_bounded(trust_path)
    finished = int(time.time())
    require(finished >= started, "clock regressed during acceptance verification")
    require(
        sha256(current_trust) == expected_trust_sha256,
        "acceptance trust changed during verification",
    )
    validate_trust(current_trust, finished)
    report["observed_at"] = finished
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--receipts", type=Path, required=True)
    parser.add_argument("--evidence-bundle", type=Path, required=True)
    parser.add_argument("--trusted-owners", type=Path, required=True)
    parser.add_argument("--expected-plan-sha256", required=True)
    parser.add_argument("--expected-trust-sha256", required=True)
    args = parser.parse_args()
    report = reconcile_files(
        args.plan,
        args.receipts,
        args.evidence_bundle,
        args.trusted_owners,
        args.expected_plan_sha256,
        args.expected_trust_sha256,
    )
    print(json.dumps(report, sort_keys=True, indent=2))
    if not report["all_required_independent_approvals_verified"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
