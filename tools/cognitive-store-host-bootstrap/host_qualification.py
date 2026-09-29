#!/usr/bin/env python3
"""Verify selected-host cognitive.store qualification receipts without granting effects.

This is a read-only verifier for externally executed host ceremonies. It does
not recover a store, issue authority, run a canary, publish a generation,
accept an SLO, activate a deployment or sign a receipt. Every successful report
still requires independent operator acceptance and release approval.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import time
import uuid

from lifecycle import digest, exact, identifier, integer, load_bounded, require
from lifecycle import sha256, validate_trust, verify_signature

PLAN_SCHEMA = "hepta.cognitive.host-qualification-plan.v2"
RECEIPT_SCHEMA = "hepta.cognitive.host-qualification-receipt.v2"
REPORT_SCHEMA = "hepta.cognitive.host-qualification-report.v3"
MAX_STEPS = 32
GIT_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")

STEP_DISPOSITIONS = {
    "bootstrap": "admitted_exact_cut",
    "publication_fsync_fault": "indeterminate_candidate_retained",
    "canary": "committed_cut_advanced",
    "crash_restart": "reopened_exact_successor",
    "witness_gap_reconcile": "stale_witness_rejected_and_current_reconciled",
    "revocation": "history_preserved_new_write_denied",
    "rollback": "fresh_generation_same_cut",
    "recovery_slo_256": "measurement_complete",
    "recovery_slo_16384": "measurement_complete",
}
STEP_ORDER = tuple(STEP_DISPOSITIONS)
ADVANCING_STEPS = frozenset({"canary", "witness_gap_reconcile"})
POST_CANARY_STEPS = (
    "crash_restart",
    "revocation",
    "rollback",
    "recovery_slo_256",
    "recovery_slo_16384",
)
POST_ROLLBACK_STEPS = frozenset({"recovery_slo_256", "recovery_slo_16384"})


def git_oid(value: object, label: str) -> str:
    require(isinstance(value, str) and GIT_OID.fullmatch(value) is not None
            and set(value) != {"0"}, f"invalid {label}")
    return value


def canonical_agent(value: object) -> str:
    require(isinstance(value, str), "invalid Agent identity")
    require(str(uuid.UUID(value)) == value, "noncanonical Agent identity")
    return value


def validate_anchor(anchor: object, owner: str) -> dict:
    exact(anchor, {"profile", "owner_agent_id", "schema_digest", "state_digest"})
    require(anchor["profile"] == "hepta:cognitive:exact-current-cut:v1",
            "unsupported recovery witness profile")
    require(anchor["owner_agent_id"] == owner, "recovery witness belongs to another owner")
    digest(anchor["schema_digest"])
    digest(anchor["state_digest"])
    return anchor


def validate_plan(plan: object, trust: dict, now: int) -> dict:
    exact(plan, {"schema", "request_id", "owner_agent_id", "source_commit", "source_tree",
                 "writer_generation", "authority_grant_sha256", "rollback_writer_generation",
                 "rollback_generation_floor", "rollback_authority_grant_sha256", "recovery_anchor",
                 "witness_custody_sha256", "host_identity_sha256", "filesystem_identity_sha256",
                 "slo_profile_sha256", "created_at", "expires_at", "steps"})
    require(plan["schema"] == PLAN_SCHEMA, "unsupported host qualification plan")
    identifier(plan["request_id"])
    owner = canonical_agent(plan["owner_agent_id"])
    git_oid(plan["source_commit"], "source commit")
    git_oid(plan["source_tree"], "source tree")
    require(len(plan["source_commit"]) == len(plan["source_tree"]),
            "source commit and tree use different object formats")
    integer(plan["writer_generation"])
    integer(plan["rollback_generation_floor"])
    integer(plan["rollback_writer_generation"])
    require(plan["rollback_generation_floor"] > plan["writer_generation"],
            "rollback generation floor must strictly exceed the initial writer generation")
    require(plan["rollback_writer_generation"] >= plan["rollback_generation_floor"],
            "rollback writer generation is below the signed rollback floor")
    for field in ("authority_grant_sha256", "rollback_authority_grant_sha256",
                  "witness_custody_sha256",
                  "host_identity_sha256", "filesystem_identity_sha256", "slo_profile_sha256"):
        digest(plan[field])
    require(plan["rollback_authority_grant_sha256"] != plan["authority_grant_sha256"],
            "rollback must use a fresh authority grant")
    validate_anchor(plan["recovery_anchor"], owner)
    integer(plan["created_at"])
    integer(plan["expires_at"])
    require(plan["created_at"] <= now < plan["expires_at"],
            "host qualification plan is future, expired or has an invalid interval")

    steps = plan["steps"]
    require(isinstance(steps, list) and len(steps) == len(STEP_DISPOSITIONS)
            and len(steps) <= MAX_STEPS, "host qualification step set is incomplete")
    trusted = validate_trust(trust, now)
    coordinator = trust["coordinator"]["signer_id"]
    observed = {}
    for row in steps:
        exact(row, {"step", "executor", "evidence_profile_sha256"})
        require(row["step"] in STEP_DISPOSITIONS and row["step"] not in observed,
                "unknown or duplicate host qualification step")
        identifier(row["executor"])
        require(row["executor"] in trusted and row["executor"] != coordinator,
                "host qualification executor is not an independent trusted owner")
        digest(row["evidence_profile_sha256"])
        observed[row["step"]] = row
    require(set(observed) == set(STEP_DISPOSITIONS), "host qualification steps are incomplete")
    return plan


def expected_writer_context(plan: dict, step_name: str) -> tuple[int, int, str, str]:
    initial_generation = plan["writer_generation"]
    rollback_generation = plan["rollback_writer_generation"]
    initial_grant = plan["authority_grant_sha256"]
    rollback_grant = plan["rollback_authority_grant_sha256"]
    if step_name == "rollback":
        return initial_generation, rollback_generation, initial_grant, rollback_grant
    if step_name in POST_ROLLBACK_STEPS:
        return rollback_generation, rollback_generation, rollback_grant, rollback_grant
    return initial_generation, initial_generation, initial_grant, initial_grant


def validate_receipt(receipt: object, plan: dict, step: dict, now: int) -> dict:
    exact(receipt, {"schema", "plan_sha256", "step", "executor", "source_commit", "source_tree",
                    "before_writer_generation", "after_writer_generation",
                    "before_authority_grant_sha256", "after_authority_grant_sha256",
                    "host_identity_sha256", "filesystem_identity_sha256",
                    "evidence_profile_sha256", "before_cut_sha256", "after_cut_sha256",
                    "status", "disposition", "observed_at", "evidence_sha256",
                    "metrics_sha256"})
    require(receipt["schema"] == RECEIPT_SCHEMA, "unsupported host qualification receipt")
    require(receipt["plan_sha256"] == sha256(plan), "receipt binds another qualification plan")
    require(receipt["step"] == step["step"] and receipt["executor"] == step["executor"],
            "receipt step or executor differs from the signed plan")
    require(receipt["evidence_profile_sha256"] == step["evidence_profile_sha256"],
            "receipt evidence profile differs from the signed plan")
    for field in ("source_commit", "source_tree", "host_identity_sha256",
                  "filesystem_identity_sha256"):
        require(receipt[field] == plan[field], "receipt identity differs from the signed plan: " + field)
    for field in ("before_writer_generation", "after_writer_generation"):
        integer(receipt[field])
    for field in ("before_authority_grant_sha256", "after_authority_grant_sha256",
                  "before_cut_sha256", "after_cut_sha256", "evidence_profile_sha256",
                  "evidence_sha256", "metrics_sha256"):
        digest(receipt[field])
    require(
        len({receipt["evidence_profile_sha256"], receipt["evidence_sha256"],
             receipt["metrics_sha256"]}) == 3,
        "host qualification profile, evidence and metrics identities overlap",
    )
    expected = expected_writer_context(plan, receipt["step"])
    observed = (receipt["before_writer_generation"], receipt["after_writer_generation"],
                receipt["before_authority_grant_sha256"],
                receipt["after_authority_grant_sha256"])
    require(observed == expected,
            "receipt writer generation or authority grant differs from the signed ceremony")
    integer(receipt["observed_at"])
    require(plan["created_at"] <= receipt["observed_at"] <= now,
            "host qualification receipt is stale or from the future")
    require(receipt["status"] in {"completed", "pending", "indeterminate", "failed"},
            "unknown host qualification status")
    identifier(receipt["disposition"])
    if receipt["status"] == "completed":
        require(receipt["disposition"] == STEP_DISPOSITIONS[receipt["step"]],
                "completed host step has the wrong disposition")
        if receipt["step"] in ADVANCING_STEPS:
            require(receipt["before_cut_sha256"] != receipt["after_cut_sha256"],
                    "advancing host step did not advance its cut")
        else:
            require(receipt["before_cut_sha256"] == receipt["after_cut_sha256"],
                    "non-advancing host step changed the semantic cut")
    return receipt


def validate_ceremony_chain(plan: dict, observed: dict[str, dict]) -> str | None:
    """Bind individually valid receipts into one coherent selected-host ceremony."""
    initial = plan["recovery_anchor"]["state_digest"]
    for name in ("bootstrap", "publication_fsync_fault"):
        receipt = observed.get(name)
        if receipt is not None and receipt["status"] == "completed":
            require(receipt["before_cut_sha256"] == initial
                    and receipt["after_cut_sha256"] == initial,
                    f"{name} receipt is not bound to the authenticated initial cut")

    canary = observed.get("canary")
    current = None
    if canary is not None and canary["status"] == "completed":
        require(canary["before_cut_sha256"] == initial,
                "canary does not start from the authenticated initial cut")
        current = canary["after_cut_sha256"]

    for name in POST_CANARY_STEPS:
        receipt = observed.get(name)
        if receipt is not None and receipt["status"] == "completed":
            require(current is not None, f"{name} completed without a completed canary")
            require(receipt["before_cut_sha256"] == current
                    and receipt["after_cut_sha256"] == current,
                    f"{name} receipt is not bound to the canary successor cut")

    witness = observed.get("witness_gap_reconcile")
    if witness is not None and witness["status"] == "completed":
        require(current is not None, "witness reconciliation completed without a completed canary")
        require(witness["before_cut_sha256"] == initial
                and witness["after_cut_sha256"] == current,
                "witness reconciliation does not bind the stale and current cuts")

    revocation = observed.get("revocation")
    rollback = observed.get("rollback")
    if rollback is not None and rollback["status"] == "completed":
        require(revocation is not None and revocation["status"] == "completed",
                "rollback completed without completed live revocation")
    for name in POST_ROLLBACK_STEPS:
        receipt = observed.get(name)
        if receipt is not None and receipt["status"] == "completed":
            require(rollback is not None and rollback["status"] == "completed",
                    f"{name} completed without completed fresh-generation rollback")

    last_observed = None
    for name in STEP_ORDER:
        receipt = observed.get(name)
        if receipt is None:
            continue
        if last_observed is not None:
            require(receipt["observed_at"] >= last_observed,
                    "host qualification receipts regress in ceremony time order")
        last_observed = receipt["observed_at"]
    return current


def reconcile(plan_envelope: object, receipt_envelopes: object, trust: dict,
              now: int, expected_plan_sha256: str) -> dict:
    integer(now)
    digest(expected_plan_sha256)
    trusted = validate_trust(trust, now)
    plan = verify_signature(plan_envelope, trust["coordinator"])
    validate_plan(plan, trust, now)
    require(sha256(plan) == expected_plan_sha256,
            "host qualification plan differs from the requested operation")
    require(isinstance(receipt_envelopes, list) and len(receipt_envelopes) <= MAX_STEPS,
            "host qualification receipt budget exceeded")
    expected = {row["step"]: row for row in plan["steps"]}
    observed = {}
    artifact_identities = set()
    for envelope in receipt_envelopes:
        require(isinstance(envelope, dict), "invalid host qualification receipt envelope")
        signer = trusted.get(envelope.get("signer_id"))
        require(signer is not None and signer["signer_id"] != trust["coordinator"]["signer_id"],
                "unknown or coordinator host qualification signer")
        receipt = verify_signature(envelope, signer)
        step_name = receipt.get("step") if isinstance(receipt, dict) else None
        require(step_name in expected and step_name not in observed,
                "unknown or duplicate host qualification receipt")
        require(signer["signer_id"] == expected[step_name]["executor"],
                "host receipt signer is not the planned executor")
        receipt = validate_receipt(receipt, plan, expected[step_name], now)
        for field in ("evidence_sha256", "metrics_sha256"):
            require(
                receipt[field] not in artifact_identities,
                "host qualification steps reuse one evidence or metrics identity",
            )
            artifact_identities.add(receipt[field])
        observed[step_name] = receipt

    qualified_cut = validate_ceremony_chain(plan, observed)
    rows = []
    for name in STEP_ORDER:
        receipt = observed.get(name)
        rows.append({
            "step": name,
            "executor": expected[name]["executor"],
            "status": receipt["status"] if receipt else "missing",
            "verified_receipt_sha256": sha256(receipt) if receipt else None,
            "verified_evidence_sha256": receipt["evidence_sha256"] if receipt else None,
            "verified_metrics_sha256": receipt["metrics_sha256"] if receipt else None,
        })
    complete = all(row["status"] == "completed" for row in rows)
    return {
        "schema": REPORT_SCHEMA,
        "plan_sha256": sha256(plan),
        "trust_sha256": sha256(trust),
        "observed_at": now,
        "initial_cut_sha256": plan["recovery_anchor"]["state_digest"],
        "qualified_cut_sha256": qualified_cut if complete else None,
        "initial_writer_generation": plan["writer_generation"],
        "rollback_generation_floor": plan["rollback_generation_floor"],
        "rollback_writer_generation": plan["rollback_writer_generation"],
        "qualified_writer_generation": plan["rollback_writer_generation"] if complete else None,
        "initial_authority_grant_sha256": plan["authority_grant_sha256"],
        "rollback_authority_grant_sha256": plan["rollback_authority_grant_sha256"],
        "qualified_authority_grant_sha256": (
            plan["rollback_authority_grant_sha256"] if complete else None
        ),
        "steps": rows,
        "all_required_owner_receipts_verified": complete,
        "result": "owner_attested_complete" if complete else "incomplete",
        "target_host_qualified": False,
        "slo_accepted": False,
        "activation_authorized": False,
        "release_authorized": False,
    }


def reconcile_files(plan_path: Path, receipts_path: Path, trust_path: Path,
                    expected_plan_sha256: str, expected_trust_sha256: str) -> dict:
    digest(expected_plan_sha256)
    digest(expected_trust_sha256)
    trust = load_bounded(trust_path)
    require(sha256(trust) == expected_trust_sha256,
            "host qualification trust differs from the installed identity")
    plan_envelope = load_bounded(plan_path)
    receipts = load_bounded(receipts_path)
    started = int(time.time())
    report = reconcile(plan_envelope, receipts, trust, started, expected_plan_sha256)
    require(sha256(load_bounded(plan_path)) == sha256(plan_envelope),
            "host qualification plan changed during verification")
    require(sha256(load_bounded(receipts_path)) == sha256(receipts),
            "host qualification receipt set changed during verification")
    current_trust = load_bounded(trust_path)
    finished = int(time.time())
    require(finished >= started, "clock regressed during host qualification verification")
    require(sha256(current_trust) == expected_trust_sha256,
            "host qualification trust changed during verification")
    validate_trust(current_trust, finished)
    report["observed_at"] = finished
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--receipts", type=Path, required=True)
    parser.add_argument("--trusted-owners", type=Path, required=True)
    parser.add_argument("--expected-plan-sha256", required=True)
    parser.add_argument("--expected-trust-sha256", required=True)
    args = parser.parse_args()
    report = reconcile_files(args.plan, args.receipts, args.trusted_owners,
                             args.expected_plan_sha256, args.expected_trust_sha256)
    print(json.dumps(report, sort_keys=True, indent=2))
    if not report["all_required_owner_receipts_verified"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
