#!/usr/bin/env python3
"""Verify ancestry-safe retention checkpoint evidence without effects.

The verifier authenticates an externally authored checkpoint plan, immutable
segment-owner receipts and one unpublished successor-generation rebuild
receipt. It never opens SQLite, deletes hot rows, uploads a segment, publishes
an active pointer, erases a predecessor, signs evidence or grants recovery
authority.
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

PLAN_SCHEMA = "hepta.cognitive.retention-checkpoint-plan.v3"
SEGMENT_RECEIPT_SCHEMA = "hepta.cognitive.retention-segment-receipt.v3"
REBUILD_RECEIPT_SCHEMA = "hepta.cognitive.retention-rebuild-receipt.v3"
REPORT_SCHEMA = "hepta.cognitive.retention-readiness-report.v3"
MAX_SEGMENTS = 128
MAX_IMAGE_BYTES = 128 * 1024 * 1024
GIT_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


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


def validate_segment(
    segment: object,
    ordinal: int,
    previous_manifest: str | None,
    previous_last_key: str | None,
    trusted: dict,
    coordinator: str,
) -> dict:
    exact(
        segment,
        {
            "segment_id",
            "storage_owner",
            "ordinal",
            "first_key_sha256",
            "last_key_sha256",
            "row_count",
            "plaintext_sha256",
            "ciphertext_sha256",
            "manifest_sha256",
            "predecessor_manifest_sha256",
        },
    )
    identifier(segment["segment_id"])
    identifier(segment["storage_owner"])
    require(
        segment["storage_owner"] in trusted
        and segment["storage_owner"] != coordinator,
        "retention segment has no independent trusted storage owner",
    )
    require(
        type(segment["ordinal"]) is int and segment["ordinal"] == ordinal,
        "retention segment ordinal is missing or reordered",
    )
    integer(segment["row_count"])
    for field in (
        "first_key_sha256",
        "last_key_sha256",
        "plaintext_sha256",
        "ciphertext_sha256",
        "manifest_sha256",
    ):
        digest(segment[field])
    require(
        len(
            {
                segment["plaintext_sha256"],
                segment["ciphertext_sha256"],
                segment["manifest_sha256"],
            }
        )
        == 3,
        "retention segment data, ciphertext and manifest identities overlap",
    )
    if segment["row_count"] == 1:
        require(
            segment["first_key_sha256"] == segment["last_key_sha256"],
            "single-row segment must bind one exact key",
        )
    else:
        require(
            segment["first_key_sha256"] < segment["last_key_sha256"],
            "multi-row segment has an invalid declared key range",
        )
    if previous_last_key is not None:
        require(
            previous_last_key < segment["first_key_sha256"],
            "retention segment key ranges are not strictly ordered and disjoint",
        )
    if previous_manifest is None:
        require(
            segment["predecessor_manifest_sha256"] is None,
            "first retention segment unexpectedly has a predecessor",
        )
    else:
        require(
            segment["predecessor_manifest_sha256"] == previous_manifest,
            "retention segment chain is broken",
        )
    return segment


def validate_plan(plan: object, trust: dict, now: int) -> dict:
    exact(
        plan,
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
    require(plan["schema"] == PLAN_SCHEMA, "unsupported retention checkpoint plan")
    identifier(plan["request_id"])
    canonical_agent(plan["owner_agent_id"])
    git_oid(plan["source_commit"], "source commit")
    git_oid(plan["source_tree"], "source tree")
    require(
        len(plan["source_commit"]) == len(plan["source_tree"]),
        "source commit and tree use different object formats",
    )
    integer(plan["writer_generation"])
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
        digest(plan[field])
    require(
        plan["predecessor_image_sha256"] != plan["successor_image_sha256"],
        "retention rebuild did not create a distinct successor image",
    )
    for field in (
        "tombstone_frontier",
        "source_frontier",
        "fact_frontier",
        "kg_frontier",
    ):
        integer(plan[field], 0)
    integer(plan["successor_image_bytes"])
    require(
        plan["successor_image_bytes"] <= MAX_IMAGE_BYTES,
        "retention successor exceeds the existing owner profile",
    )
    integer(plan["segment_count"])
    integer(plan["segment_row_count"])
    integer(plan["created_at"])
    integer(plan["expires_at"])
    require(
        plan["created_at"] <= now < plan["expires_at"],
        "retention plan is future, expired or has an invalid interval",
    )

    trusted = validate_trust(trust, now)
    coordinator = trust["coordinator"]["signer_id"]
    identifier(plan["rebuild_owner"])
    require(
        plan["rebuild_owner"] in trusted and plan["rebuild_owner"] != coordinator,
        "retention rebuild owner is not independently trusted",
    )
    segments = plan["segments"]
    require(
        isinstance(segments, list) and 1 <= len(segments) <= MAX_SEGMENTS,
        "retention plan has no segments or exceeds the segment budget",
    )
    identities: set[str] = set()
    content_digests: set[str] = set()
    previous_manifest = None
    previous_last_key = None
    total_rows = 0
    for ordinal, segment in enumerate(segments):
        validate_segment(
            segment,
            ordinal,
            previous_manifest,
            previous_last_key,
            trusted,
            coordinator,
        )
        require(
            segment["segment_id"] not in identities,
            "duplicate retention segment identity",
        )
        segment_digests = (
            segment["plaintext_sha256"],
            segment["ciphertext_sha256"],
            segment["manifest_sha256"],
        )
        require(
            all(value not in content_digests for value in segment_digests),
            "duplicate retention segment content identity",
        )
        identities.add(segment["segment_id"])
        content_digests.update(segment_digests)
        previous_manifest = segment["manifest_sha256"]
        previous_last_key = segment["last_key_sha256"]
        total_rows += segment["row_count"]
    require(
        plan["segment_set_sha256"] == sha256(segments),
        "retention segment-set digest does not match the signed segment inventory",
    )
    require(
        plan["segment_count"] == len(segments),
        "retention segment count does not match the signed segment inventory",
    )
    require(
        plan["segment_row_count"] == total_rows,
        "retention row count does not match the signed segment inventory",
    )
    require(
        plan["first_segment_manifest_sha256"] == segments[0]["manifest_sha256"]
        and plan["last_segment_manifest_sha256"] == segments[-1]["manifest_sha256"],
        "retention segment chain endpoints do not match the signed inventory",
    )
    require(
        plan["rebuild_owner"]
        not in {row["storage_owner"] for row in segments},
        "retention rebuild owner must be independent of every segment owner",
    )
    return plan


def validate_segment_receipt(
    receipt: object, plan: dict, segment: dict, now: int
) -> dict:
    exact(
        receipt,
        {
            "schema",
            "plan_sha256",
            "segment_id",
            "storage_owner",
            "ordinal",
            "first_key_sha256",
            "last_key_sha256",
            "row_count",
            "plaintext_sha256",
            "manifest_sha256",
            "ciphertext_sha256",
            "predecessor_manifest_sha256",
            "status",
            "method",
            "observed_at",
            "evidence_sha256",
        },
    )
    require(
        receipt["schema"] == SEGMENT_RECEIPT_SCHEMA,
        "unsupported retention segment receipt",
    )
    require(receipt["plan_sha256"] == sha256(plan), "segment receipt binds another plan")
    for field in (
        "segment_id",
        "storage_owner",
        "ordinal",
        "first_key_sha256",
        "last_key_sha256",
        "row_count",
        "plaintext_sha256",
        "manifest_sha256",
        "ciphertext_sha256",
        "predecessor_manifest_sha256",
    ):
        require(
            receipt[field] == segment[field],
            "segment receipt identity mismatch: " + field,
        )
    require(
        receipt["status"] in {"completed", "pending", "indeterminate", "failed"},
        "unknown retention segment status",
    )
    identifier(receipt["method"])
    if receipt["status"] == "completed":
        require(
            receipt["method"] == "immutable_encrypted_segment",
            "completed segment is not an immutable encrypted publication",
        )
    integer(receipt["observed_at"])
    require(
        plan["created_at"] <= receipt["observed_at"] <= now,
        "retention segment receipt is stale or from the future",
    )
    digest(receipt["evidence_sha256"])
    return receipt


def validate_rebuild_receipt(receipt: object, plan: dict, now: int) -> dict:
    exact(
        receipt,
        {
            "schema",
            "plan_sha256",
            "rebuild_owner",
            "owner_agent_id",
            "source_commit",
            "source_tree",
            "writer_generation",
            "schema_sha256",
            "predecessor_image_sha256",
            "successor_image_sha256",
            "successor_image_bytes",
            "before_cut_sha256",
            "after_cut_sha256",
            "head_set_sha256",
            "tombstone_frontier",
            "source_frontier",
            "fact_frontier",
            "kg_frontier",
            "segment_set_sha256",
            "segment_count",
            "segment_row_count",
            "first_segment_manifest_sha256",
            "last_segment_manifest_sha256",
            "segments_resolved",
            "integrity_check",
            "foreign_key_check",
            "projection_check",
            "pending_operation_check",
            "published",
            "status",
            "observed_at",
            "evidence_sha256",
        },
    )
    require(
        receipt["schema"] == REBUILD_RECEIPT_SCHEMA,
        "unsupported retention rebuild receipt",
    )
    require(receipt["plan_sha256"] == sha256(plan), "rebuild receipt binds another plan")
    for field in (
        "rebuild_owner",
        "owner_agent_id",
        "source_commit",
        "source_tree",
        "writer_generation",
        "schema_sha256",
        "predecessor_image_sha256",
        "successor_image_sha256",
        "successor_image_bytes",
        "head_set_sha256",
        "tombstone_frontier",
        "source_frontier",
        "fact_frontier",
        "kg_frontier",
        "segment_set_sha256",
        "segment_count",
        "segment_row_count",
        "first_segment_manifest_sha256",
        "last_segment_manifest_sha256",
    ):
        require(
            receipt[field] == plan[field],
            "rebuild receipt identity mismatch: " + field,
        )
    require(
        receipt["before_cut_sha256"] == plan["current_cut_sha256"]
        and receipt["after_cut_sha256"] == plan["current_cut_sha256"],
        "retention rebuild changed the authenticated semantic cut",
    )
    for field in (
        "segments_resolved",
        "integrity_check",
        "foreign_key_check",
        "projection_check",
        "pending_operation_check",
    ):
        require(type(receipt[field]) is bool, "invalid rebuild check flag")
    require(type(receipt["published"]) is bool, "invalid rebuild publication flag")
    require(
        receipt["status"] in {"completed", "pending", "indeterminate", "failed"},
        "unknown retention rebuild status",
    )
    if receipt["status"] == "completed":
        require(
            all(
                receipt[field] is True
                for field in (
                    "segments_resolved",
                    "integrity_check",
                    "foreign_key_check",
                    "projection_check",
                    "pending_operation_check",
                )
            ),
            "completed retention rebuild failed an oracle check",
        )
        require(
            receipt["published"] is False,
            "readiness evidence must not publish the successor generation",
        )
    integer(receipt["observed_at"])
    require(
        plan["created_at"] <= receipt["observed_at"] <= now,
        "retention rebuild receipt is stale or from the future",
    )
    digest(receipt["evidence_sha256"])
    return receipt


def reconcile(
    plan_envelope: object,
    receipt_bundle: object,
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
        "retention plan differs from the requested operation",
    )
    exact(receipt_bundle, {"segments", "rebuild"})
    segment_envelopes = receipt_bundle["segments"]
    require(
        isinstance(segment_envelopes, list)
        and len(segment_envelopes) <= MAX_SEGMENTS,
        "retention segment receipt budget exceeded",
    )
    expected = {row["segment_id"]: row for row in plan["segments"]}
    observed = {}
    for envelope in segment_envelopes:
        require(isinstance(envelope, dict), "invalid retention segment receipt envelope")
        signer = trusted.get(envelope.get("signer_id"))
        require(
            signer is not None
            and signer["signer_id"] != trust["coordinator"]["signer_id"],
            "unknown or coordinator retention segment signer",
        )
        receipt = verify_signature(envelope, signer)
        identity = receipt.get("segment_id") if isinstance(receipt, dict) else None
        require(
            identity in expected and identity not in observed,
            "unknown or duplicate retention segment receipt",
        )
        require(
            signer["signer_id"] == expected[identity]["storage_owner"],
            "segment receipt signer is not the planned storage owner",
        )
        observed[identity] = validate_segment_receipt(
            receipt, plan, expected[identity], now
        )

    rebuild_envelope = receipt_bundle["rebuild"]
    require(
        isinstance(rebuild_envelope, dict),
        "missing retention rebuild receipt envelope",
    )
    rebuild_signer = trusted.get(rebuild_envelope.get("signer_id"))
    require(
        rebuild_signer is not None
        and rebuild_signer["signer_id"] == plan["rebuild_owner"],
        "retention rebuild signer is not the planned owner",
    )
    rebuild = validate_rebuild_receipt(
        verify_signature(rebuild_envelope, rebuild_signer), plan, now
    )
    if rebuild["status"] == "completed" and observed:
        require(
            rebuild["observed_at"]
            >= max(row["observed_at"] for row in observed.values()),
            "retention rebuild predates an observed segment publication",
        )

    rows = []
    for segment in plan["segments"]:
        receipt = observed.get(segment["segment_id"])
        rows.append(
            {
                "segment_id": segment["segment_id"],
                "storage_owner": segment["storage_owner"],
                "status": receipt["status"] if receipt else "missing",
                "verified_receipt_sha256": sha256(receipt) if receipt else None,
            }
        )
    complete = (
        all(row["status"] == "completed" for row in rows)
        and rebuild["status"] == "completed"
    )
    return {
        "schema": REPORT_SCHEMA,
        "plan_sha256": sha256(plan),
        "trust_sha256": sha256(trust),
        "observed_at": now,
        "segment_set_sha256": plan["segment_set_sha256"],
        "segment_count": plan["segment_count"],
        "segment_row_count": plan["segment_row_count"],
        "segments": rows,
        "rebuild_status": rebuild["status"],
        "verified_rebuild_receipt_sha256": sha256(rebuild),
        "all_required_owner_receipts_verified": complete,
        "result": "retention_ready" if complete else "incomplete",
        "successor_published": False,
        "hot_history_pruned": False,
        "predecessor_erased": False,
        "physical_erasure_proved": False,
        "activation_authorized": False,
    }


def reconcile_files(
    plan_path: Path,
    receipts_path: Path,
    trust_path: Path,
    expected_plan_sha256: str,
    expected_trust_sha256: str,
) -> dict:
    digest(expected_plan_sha256)
    digest(expected_trust_sha256)
    trust = load_bounded(trust_path)
    require(
        sha256(trust) == expected_trust_sha256,
        "retention trust differs from the installed identity",
    )
    plan_envelope = load_bounded(plan_path)
    receipt_bundle = load_bounded(receipts_path)
    started = int(time.time())
    report = reconcile(
        plan_envelope, receipt_bundle, trust, started, expected_plan_sha256
    )
    require(
        sha256(load_bounded(plan_path)) == sha256(plan_envelope),
        "retention plan changed during verification",
    )
    require(
        sha256(load_bounded(receipts_path)) == sha256(receipt_bundle),
        "retention receipt bundle changed during verification",
    )
    current_trust = load_bounded(trust_path)
    finished = int(time.time())
    require(finished >= started, "clock regressed during retention verification")
    require(
        sha256(current_trust) == expected_trust_sha256,
        "retention trust changed during verification",
    )
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
    report = reconcile_files(
        args.plan,
        args.receipts,
        args.trusted_owners,
        args.expected_plan_sha256,
        args.expected_trust_sha256,
    )
    print(json.dumps(report, sort_keys=True, indent=2))
    if not report["all_required_owner_receipts_verified"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
