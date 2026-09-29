#!/usr/bin/env python3
"""Verify independently signed cognitive.store acceptance evidence without effects.

The verifier authenticates external semantic, durability, security, operations
and release review receipts for one exact candidate and evidence set. It does
not merge source, activate a host, publish a generation, delete data, issue
runtime authority or perform a release. Repository fixtures never satisfy the
current deployment's independent-acceptance gate.
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

PLAN_SCHEMA = "hepta.cognitive.acceptance-plan.v3"
RECEIPT_SCHEMA = "hepta.cognitive.acceptance-receipt.v3"
REPORT_SCHEMA = "hepta.cognitive.acceptance-report.v3"
QUALIFICATION_SCHEMA = "hepta.cognitive-store-qualification-manifest.v2"
HOST_REPORT_SCHEMA = "hepta.cognitive.host-qualification-report.v2"
RETENTION_REPORT_SCHEMA = "hepta.cognitive.retention-readiness-report.v3"
LIFECYCLE_REPORT_SCHEMA = "hepta.cognitive.lifecycle-reconciliation.v1"
GIT_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
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
EVIDENCE_FIELDS = (
    "source_head_manifest_sha256",
    "base_merge_manifest_sha256",
    "host_qualification_report_sha256",
    "retention_readiness_report_sha256",
    "lifecycle_reconciliation_report_sha256",
)


def require_false(report: dict, fields: tuple[str, ...], label: str) -> None:
    for field in fields:
        require(report.get(field) is False,
                f"{label} escalates or omits the forbidden claim: {field}")


def validate_qualification_manifest(report: object, plan: dict, lane: str) -> dict:
    require(isinstance(report, dict), "qualification evidence is not an object")
    require(report.get("schema") == QUALIFICATION_SCHEMA,
            "unsupported qualification manifest evidence")
    require(report.get("lane") == lane, "qualification evidence belongs to another lane")
    require(report.get("sourceSha") == plan["source_commit"]
            and report.get("sourceTree") == plan["source_tree"],
            "qualification evidence belongs to another source")
    require(report.get("result") == "terminal-success"
            and report.get("executionComplete") is True,
            "qualification evidence is not terminal-success")
    require(report.get("identityErrors") == [],
            "qualification evidence contains candidate identity errors")
    git_oid(report.get("testedSha"), "qualification tested commit")
    git_oid(report.get("testedTree"), "qualification tested tree")
    commands = report.get("commands")
    require(isinstance(commands, list) and commands
            and all(isinstance(row, dict) and row.get("status") == "passed" for row in commands),
            "qualification evidence contains missing or non-passing commands")
    command_names = [row.get("name") for row in commands]
    require(all(isinstance(name, str) and name for name in command_names)
            and len(command_names) == len(set(command_names)),
            "qualification evidence contains unnamed or duplicate command records")
    retained = report.get("evidence")
    require(isinstance(retained, list) and retained
            and all(isinstance(row, dict) and row.get("status") == "retained" for row in retained),
            "qualification evidence contains missing retained artifacts")
    require_false(report, ("targetHostQualified", "independentAcceptance", "release"),
                  "qualification evidence")
    if lane == "source-head":
        require(report.get("testedSha") == plan["source_commit"]
                and report.get("testedTree") == plan["source_tree"],
                "source-head evidence did not test the exact source")
    else:
        parents = report.get("parents")
        require(isinstance(parents, list) and len(parents) == 2
                and report.get("baseSha") == parents[0]
                and report.get("sourceSha") == parents[1]
                and parents[1] == plan["source_commit"]
                and report.get("testedSha") not in parents,
                "base-merge evidence does not bind its frozen base/source parents")
    return report


def validate_host_report(report: object) -> dict:
    require(isinstance(report, dict) and report.get("schema") == HOST_REPORT_SCHEMA,
            "unsupported selected-host qualification evidence")
    require(report.get("result") == "owner_attested_complete"
            and report.get("all_required_owner_receipts_verified") is True,
            "selected-host qualification evidence is incomplete")
    steps = report.get("steps")
    require(isinstance(steps, list)
            and tuple(row.get("step") for row in steps if isinstance(row, dict)) == HOST_STEPS
            and all(row.get("status") == "completed" for row in steps),
            "selected-host qualification evidence contains incomplete or reordered steps")
    for field in ("initial_cut_sha256", "qualified_cut_sha256",
                  "initial_authority_grant_sha256", "rollback_authority_grant_sha256",
                  "qualified_authority_grant_sha256"):
        digest(report.get(field))
    for field in ("initial_writer_generation", "rollback_generation_floor",
                  "rollback_writer_generation", "qualified_writer_generation"):
        integer(report.get(field))
    require(report["rollback_generation_floor"] > report["initial_writer_generation"]
            and report["rollback_writer_generation"] >= report["rollback_generation_floor"]
            and report["qualified_writer_generation"] == report["rollback_writer_generation"]
            and report["qualified_authority_grant_sha256"]
                == report["rollback_authority_grant_sha256"]
            and report["initial_authority_grant_sha256"]
                != report["rollback_authority_grant_sha256"],
            "selected-host qualification evidence has an invalid final writer context")
    require_false(report, ("target_host_qualified", "slo_accepted",
                           "activation_authorized", "release_authorized"),
                  "selected-host qualification evidence")
    return report


def validate_retention_report(report: object) -> dict:
    require(isinstance(report, dict) and report.get("schema") == RETENTION_REPORT_SCHEMA,
            "unsupported retention readiness evidence")
    require(report.get("result") == "retention_ready"
            and report.get("all_required_owner_receipts_verified") is True,
            "retention readiness evidence is incomplete")
    segments = report.get("segments")
    require(isinstance(segments, list) and segments
            and all(isinstance(row, dict) and row.get("status") == "completed" for row in segments)
            and report.get("rebuild_status") == "completed",
            "retention readiness evidence contains incomplete segment or rebuild receipts")
    integer(report.get("segment_count"))
    integer(report.get("segment_row_count"))
    digest(report.get("segment_set_sha256"))
    digest(report.get("verified_rebuild_receipt_sha256"))
    require(report["segment_count"] == len(segments),
            "retention readiness evidence segment count differs from its rows")
    require_false(report, ("successor_published", "hot_history_pruned", "predecessor_erased",
                           "physical_erasure_proved", "activation_authorized"),
                  "retention readiness evidence")
    return report


def validate_lifecycle_report(report: object) -> dict:
    require(isinstance(report, dict) and report.get("schema") == LIFECYCLE_REPORT_SCHEMA,
            "unsupported lifecycle reconciliation evidence")
    require(report.get("result") == "owner_attested_complete"
            and report.get("all_required_owner_receipts_verified") is True,
            "lifecycle reconciliation evidence is incomplete")
    obligations = report.get("obligations")
    require(isinstance(obligations, list) and obligations
            and all(isinstance(row, dict) and row.get("status") == "completed"
                    for row in obligations),
            "lifecycle reconciliation evidence contains incomplete obligations")
    require({row.get("storage_class") for row in obligations} == CLASSES,
            "lifecycle reconciliation evidence omits or invents a storage class")
    require_false(report, ("authorized_effects", "physical_erasure_independently_proved",
                           "target_host_qualified"),
                  "lifecycle reconciliation evidence")
    return report


def validate_evidence_bundle(bundle: object, plan: dict) -> dict:
    exact(bundle, set(EVIDENCE_FIELDS))
    validators = {
        "source_head_manifest_sha256": lambda report: validate_qualification_manifest(
            report, plan, "source-head"),
        "base_merge_manifest_sha256": lambda report: validate_qualification_manifest(
            report, plan, "base-merge"),
        "host_qualification_report_sha256": validate_host_report,
        "retention_readiness_report_sha256": validate_retention_report,
        "lifecycle_reconciliation_report_sha256": validate_lifecycle_report,
    }
    for field in EVIDENCE_FIELDS:
        report = bundle[field]
        require(sha256(report) == plan[field],
                "acceptance evidence digest differs from the signed plan: " + field)
        validators[field](report)
    return bundle


def git_oid(value: object, label: str) -> str:
    require(isinstance(value, str) and GIT_OID.fullmatch(value) is not None
            and set(value) != {"0"}, f"invalid {label}")
    return value


def canonical_agent(value: object) -> str:
    require(isinstance(value, str), "invalid Agent identity")
    require(str(uuid.UUID(value)) == value, "noncanonical Agent identity")
    return value


def validate_plan(plan: object, trust: dict, now: int) -> dict:
    exact(plan, {"schema", "request_id", "owner_agent_id", "source_commit", "source_tree",
                 *EVIDENCE_FIELDS, "created_at", "expires_at", "roles"})
    require(plan["schema"] == PLAN_SCHEMA, "unsupported acceptance plan")
    identifier(plan["request_id"])
    canonical_agent(plan["owner_agent_id"])
    git_oid(plan["source_commit"], "source commit")
    git_oid(plan["source_tree"], "source tree")
    require(len(plan["source_commit"]) == len(plan["source_tree"]),
            "source commit and tree use different object formats")
    for field in EVIDENCE_FIELDS:
        digest(plan[field])
    integer(plan["created_at"])
    integer(plan["expires_at"])
    require(plan["created_at"] <= now < plan["expires_at"],
            "acceptance plan is future, expired or has an invalid interval")

    trusted = validate_trust(trust, now)
    coordinator = trust["coordinator"]["signer_id"]
    roles = plan["roles"]
    require(isinstance(roles, list) and len(roles) == len(REQUIRED_ROLES)
            and len(roles) <= MAX_ROLES, "acceptance role set is incomplete")
    observed = {}
    reviewers = set()
    for row in roles:
        exact(row, {"role", "reviewer", "criteria_sha256"})
        require(row["role"] in REQUIRED_ROLES and row["role"] not in observed,
                "unknown or duplicate acceptance role")
        identifier(row["reviewer"])
        require(row["reviewer"] in trusted and row["reviewer"] != coordinator,
                "acceptance reviewer is not independently trusted")
        require(row["reviewer"] not in reviewers,
                "acceptance roles must use distinct independent reviewers")
        digest(row["criteria_sha256"])
        reviewers.add(row["reviewer"])
        observed[row["role"]] = row
    require(tuple(role for role in REQUIRED_ROLES if role in observed) == REQUIRED_ROLES,
            "acceptance roles are incomplete")
    return plan


def validate_receipt(receipt: object, plan: dict, role: dict, now: int) -> dict:
    exact(receipt, {"schema", "plan_sha256", "role", "reviewer", "criteria_sha256",
                    "owner_agent_id", "source_commit", "source_tree", *EVIDENCE_FIELDS,
                    "decision", "observed_at", "review_sha256"})
    require(receipt["schema"] == RECEIPT_SCHEMA, "unsupported acceptance receipt")
    require(receipt["plan_sha256"] == sha256(plan), "acceptance receipt binds another plan")
    require(receipt["role"] == role["role"] and receipt["reviewer"] == role["reviewer"],
            "acceptance receipt role or reviewer differs from the signed plan")
    require(receipt["criteria_sha256"] == role["criteria_sha256"],
            "acceptance receipt criteria differ from the signed plan")
    for field in ("owner_agent_id", "source_commit", "source_tree", *EVIDENCE_FIELDS):
        require(receipt[field] == plan[field],
                "acceptance receipt identity differs from the signed plan: " + field)
    require(receipt["decision"] in {"approved", "rejected", "pending", "indeterminate"},
            "unknown acceptance decision")
    integer(receipt["observed_at"])
    require(plan["created_at"] <= receipt["observed_at"] <= now,
            "acceptance receipt is stale or from the future")
    digest(receipt["review_sha256"])
    return receipt


def reconcile(plan_envelope: object, receipt_envelopes: object, evidence_bundle: object,
              trust: dict, now: int, expected_plan_sha256: str) -> dict:
    integer(now)
    digest(expected_plan_sha256)
    trusted = validate_trust(trust, now)
    plan = verify_signature(plan_envelope, trust["coordinator"])
    validate_plan(plan, trust, now)
    require(sha256(plan) == expected_plan_sha256,
            "acceptance plan differs from the requested operation")
    validate_evidence_bundle(evidence_bundle, plan)
    require(isinstance(receipt_envelopes, list) and len(receipt_envelopes) <= MAX_ROLES,
            "acceptance receipt budget exceeded")
    expected = {row["role"]: row for row in plan["roles"]}
    observed = {}
    for envelope in receipt_envelopes:
        require(isinstance(envelope, dict), "invalid acceptance receipt envelope")
        signer = trusted.get(envelope.get("signer_id"))
        require(signer is not None and signer["signer_id"] != trust["coordinator"]["signer_id"],
                "unknown or coordinator acceptance signer")
        receipt = verify_signature(envelope, signer)
        role_name = receipt.get("role") if isinstance(receipt, dict) else None
        require(role_name in expected and role_name not in observed,
                "unknown or duplicate acceptance receipt")
        require(signer["signer_id"] == expected[role_name]["reviewer"],
                "acceptance receipt signer is not the planned reviewer")
        observed[role_name] = validate_receipt(receipt, plan, expected[role_name], now)

    last_observed = None
    for index, name in enumerate(REQUIRED_ROLES):
        receipt = observed.get(name)
        if receipt is None:
            continue
        if receipt["decision"] == "approved":
            for predecessor_name in REQUIRED_ROLES[:index]:
                predecessor = observed.get(predecessor_name)
                if predecessor is not None:
                    require(predecessor["decision"] == "approved",
                            f"{name} approval follows non-approved prerequisite "
                            f"{predecessor_name}")
        if last_observed is not None:
            require(receipt["observed_at"] >= last_observed,
                    "acceptance approvals regress in required review order")
        last_observed = receipt["observed_at"]

    rows = []
    for name in REQUIRED_ROLES:
        receipt = observed.get(name)
        rows.append({
            "role": name,
            "reviewer": expected[name]["reviewer"],
            "decision": receipt["decision"] if receipt else "missing",
            "verified_receipt_sha256": sha256(receipt) if receipt else None,
        })
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
        "all_bound_evidence_reports_validated": True,
        "roles": rows,
        "all_required_independent_approvals_verified": complete,
        "result": "external_approval_set_verified" if complete else "incomplete",
        "independent_acceptance_verified": complete,
        "authorized_effects": False,
        "activation_performed": False,
        "release_performed": False,
    }


def reconcile_files(plan_path: Path, receipts_path: Path, evidence_path: Path,
                    trust_path: Path, expected_plan_sha256: str,
                    expected_trust_sha256: str) -> dict:
    digest(expected_plan_sha256)
    digest(expected_trust_sha256)
    trust = load_bounded(trust_path)
    require(sha256(trust) == expected_trust_sha256,
            "acceptance trust differs from the installed identity")
    plan_envelope = load_bounded(plan_path)
    receipts = load_bounded(receipts_path)
    evidence_bundle = load_bounded(evidence_path)
    started = int(time.time())
    report = reconcile(plan_envelope, receipts, evidence_bundle, trust, started,
                       expected_plan_sha256)
    require(sha256(load_bounded(plan_path)) == sha256(plan_envelope),
            "acceptance plan changed during verification")
    require(sha256(load_bounded(receipts_path)) == sha256(receipts),
            "acceptance receipt set changed during verification")
    require(sha256(load_bounded(evidence_path)) == sha256(evidence_bundle),
            "acceptance evidence bundle changed during verification")
    current_trust = load_bounded(trust_path)
    finished = int(time.time())
    require(finished >= started, "clock regressed during acceptance verification")
    require(sha256(current_trust) == expected_trust_sha256,
            "acceptance trust changed during verification")
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
    report = reconcile_files(args.plan, args.receipts, args.evidence_bundle,
                             args.trusted_owners, args.expected_plan_sha256,
                             args.expected_trust_sha256)
    print(json.dumps(report, sort_keys=True, indent=2))
    if not report["all_required_independent_approvals_verified"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
