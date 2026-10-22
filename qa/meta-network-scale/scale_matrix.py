#!/usr/bin/env python3
"""Generate and validate the Hepta cell/meta-network qualification matrix.

This tool validates experiment shape and evidence completeness only. A valid
manifest is not an efficacy result and cannot promote a topology.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from typing import Any

SIZES = (1, 8, 64, 256, 1024, 4096)
ARMS = (
    "no_change",
    "fixed_routing",
    "learned_routing",
    "single_head",
    "shared_encoder",
    "duplicated_encoder",
)
REQUIRED_EVIDENCE = (
    "future_window",
    "negative_transfer",
    "lesion_ablation",
    "crash_reopen",
    "stale_generation_rejection",
    "rollback",
    "resource_cost",
)
REQUIRED_METRICS = (
    "task_utility",
    "future_window_utility",
    "negative_transfer_rate",
    "p50_ms",
    "p95_ms",
    "p99_ms",
    "throughput_per_host",
    "queue_age_ms",
    "starvation_count",
    "gpu_peak_bytes",
    "rss_bytes",
    "immutable_buffer_reuse_rate",
    "cache_invalidation_count",
    "migration_recovery_ms",
    "rollback_recovery_ms",
)
LIFECYCLE = (
    "candidate",
    "independent_evaluation",
    "selector",
    "signed_successor_snapshot",
    "state_migration",
    "old_writer_fence",
    "route_cutover",
    "canary",
    "rollback_rehearsal",
    "production_admission",
)

# A scale result is only a qualification-shaped record.  It still has to bind
# the observations to immutable source/host evidence so that a fixture cannot
# be mistaken for an exact-head or target-host run.  The validator cannot
# authenticate these values; that remains the workflow/host owner's job.
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
PROVENANCE_FIELDS = (
    "source_commit",
    "source_tree",
    "target_host_digest",
    "runtime_digest",
    "measurement_digest",
)

# P5 is an evidence-shape validator, never an authority or release issuer.
# Reject unknown members at every schema level so "qualified" extras cannot
# be laundered into the evidence record by a later permissive consumer.
RESULT_FIELDS = (
    "schema",
    "size",
    "arm",
    "authority",
    "provenance",
    "evidence",
    "evidence_receipts",
    "metrics",
    "metrics_receipt",
    "topology_lifecycle",
)
MATRIX_FIELDS = ("schema", "authority", "results")
MAX_INPUT_BYTES = 2 * 1024 * 1024


def _reject_unregistered_keys(
    record: dict[str, Any], allowed: tuple[str, ...], scope: str
) -> list[str]:
    return [
        f"{scope}.{key} is not a registered field"
        for key in record
        if key not in allowed
    ]


def _reject_duplicate_json_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def _reject_non_finite_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def build_plan() -> dict[str, Any]:
    return {
        "schema": "hepta.cell-execution-scale-plan.v1",
        "authority": "qualification_only",
        "sizes": list(SIZES),
        "arms": list(ARMS),
        "required_evidence": list(REQUIRED_EVIDENCE),
        "required_metrics": list(REQUIRED_METRICS),
        "required_provenance": list(PROVENANCE_FIELDS),
        "required_evidence_receipts": list(REQUIRED_EVIDENCE),
        "topology_lifecycle": list(LIFECYCLE),
        "claims": [
            "expressivity",
            "learnability",
            "unseen_task_adaptation",
            "resource_scaling",
        ],
    }


def _finite_number(value: Any) -> bool:
    """Return whether a JSON number is finite without coercion crashes."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, ValueError):
        return False


def validate_result(result: dict[str, Any]) -> list[str]:
    if not isinstance(result, dict):
        return ["result must be an object"]
    errors: list[str] = []
    errors.extend(_reject_unregistered_keys(result, RESULT_FIELDS, "result"))
    if result.get("schema") != "hepta.cell-execution-scale-result.v1":
        errors.append("schema must be hepta.cell-execution-scale-result.v1")
    if type(result.get("size")) is not int or result.get("size") not in SIZES:
        errors.append("size must be one of 1, 8, 64, 256, 1024, 4096")
    if result.get("arm") not in ARMS:
        errors.append("arm is not in the registered comparison arms")
    if result.get("authority") != "qualification_only":
        errors.append("authority must remain qualification_only")

    provenance = result.get("provenance")
    if not isinstance(provenance, dict):
        errors.append("provenance must be an object")
    else:
        errors.extend(
            _reject_unregistered_keys(provenance, PROVENANCE_FIELDS, "provenance")
        )
        for key in PROVENANCE_FIELDS:
            value = provenance.get(key)
            pattern = _HEX40 if key in {"source_commit", "source_tree"} else _HEX64
            if not isinstance(value, str) or pattern.fullmatch(value) is None:
                errors.append(
                    f"provenance.{key} must be a lowercase hexadecimal digest"
                )
            elif not any(character != "0" for character in value):
                errors.append(f"provenance.{key} cannot be a zero digest")

    evidence = result.get("evidence")
    if not isinstance(evidence, dict):
        errors.append("evidence must be an object")
    else:
        errors.extend(
            _reject_unregistered_keys(evidence, REQUIRED_EVIDENCE, "evidence")
        )
        for key in REQUIRED_EVIDENCE:
            if evidence.get(key) is not True:
                errors.append(f"evidence.{key} must be true")

    evidence_receipts = result.get("evidence_receipts")
    if not isinstance(evidence_receipts, dict):
        errors.append("evidence_receipts must be an object")
    else:
        errors.extend(
            _reject_unregistered_keys(
                evidence_receipts, REQUIRED_EVIDENCE, "evidence_receipts"
            )
        )
        # Each evidence claim must have its own retained receipt. Reusing one
        # digest for both future-window and rollback, for example, obscures
        # which independent observation supports which claim.
        claim_by_receipt: dict[str, str] = {}
        for key in REQUIRED_EVIDENCE:
            value = evidence_receipts.get(key)
            if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
                errors.append(
                    f"evidence_receipts.{key} must be a lowercase SHA-256 digest"
                )
            elif not any(character != "0" for character in value):
                errors.append(f"evidence_receipts.{key} cannot be a zero digest")
            else:
                previous_claim = claim_by_receipt.get(value)
                if previous_claim is not None:
                    errors.append(
                        f"evidence_receipts.{key} reuses the {previous_claim} claim receipt"
                    )
                claim_by_receipt[value] = key

    metrics = result.get("metrics")
    if not isinstance(metrics, dict):
        errors.append("metrics must be an object")
    else:
        errors.extend(_reject_unregistered_keys(metrics, REQUIRED_METRICS, "metrics"))
        for key in REQUIRED_METRICS:
            if key not in metrics:
                errors.append(f"metrics.{key} is required")
                continue
            value = metrics[key]
            if not _finite_number(value):
                errors.append(f"metrics.{key} must be a finite number")
            elif key not in {"task_utility", "future_window_utility"} and value < 0:
                errors.append(f"metrics.{key} must be non-negative")
            elif (
                key in {"negative_transfer_rate", "immutable_buffer_reuse_rate"}
                and value > 1
            ):
                errors.append(f"metrics.{key} must be a unit-interval rate")

        # Physical byte sizes and event counts cannot be fractional.
        for key in (
            "rss_bytes",
            "gpu_peak_bytes",
            "starvation_count",
            "cache_invalidation_count",
        ):
            if key in metrics and type(metrics[key]) is not int:
                errors.append(f"metrics.{key} must be an integer count")
        percentiles = ("p50_ms", "p95_ms", "p99_ms")
        if all(_finite_number(metrics.get(key)) for key in percentiles):
            if not (metrics["p50_ms"] <= metrics["p95_ms"] <= metrics["p99_ms"]):
                errors.append(
                    "metrics latency percentiles must satisfy p50 <= p95 <= p99"
                )

    metrics_receipt = result.get("metrics_receipt")
    if (
        not isinstance(metrics_receipt, str)
        or _HEX64.fullmatch(metrics_receipt) is None
    ):
        errors.append("metrics_receipt must be a lowercase SHA-256 digest")
    elif not any(character != "0" for character in metrics_receipt):
        errors.append("metrics_receipt cannot be a zero digest")
    elif isinstance(evidence_receipts, dict) and metrics_receipt in evidence_receipts.values():
        errors.append("metrics_receipt cannot reuse an evidence claim receipt")
    # The measurement bytes, a metrics receipt and independently retained
    # evidence claims are distinct proof roles. Do not let one raw digest
    # masquerade as multiple roles even within a single experiment result.
    measurement_digest = (
        provenance.get("measurement_digest")
        if isinstance(provenance, dict)
        else None
    )
    if isinstance(measurement_digest, str) and _HEX64.fullmatch(measurement_digest):
        if metrics_receipt == measurement_digest:
            errors.append("metrics_receipt cannot reuse provenance measurement digest")
        if isinstance(evidence_receipts, dict):
            for claim in REQUIRED_EVIDENCE:
                if evidence_receipts.get(claim) == measurement_digest:
                    errors.append(
                        f"evidence_receipts.{claim} cannot reuse provenance measurement digest"
                    )
    # Host/runtime identity and measured/evaluated receipts are independent
    # proof domains. A reused digest cannot establish two distinct claims.
    if isinstance(provenance, dict):
        host_digest = provenance.get("target_host_digest")
        runtime_digest = provenance.get("runtime_digest")
        if (
            isinstance(host_digest, str)
            and _HEX64.fullmatch(host_digest)
            and host_digest == runtime_digest
        ):
            errors.append(
                "provenance.runtime_digest cannot reuse provenance.target_host_digest"
            )
        for identity_role in ("target_host_digest", "runtime_digest"):
            identity_digest = provenance.get(identity_role)
            if not isinstance(identity_digest, str) or not _HEX64.fullmatch(
                identity_digest
            ):
                continue
            if identity_digest == measurement_digest:
                errors.append(
                    f"provenance.measurement_digest cannot reuse provenance.{identity_role}"
                )
            if identity_digest == metrics_receipt:
                errors.append(
                    f"metrics_receipt cannot reuse provenance.{identity_role}"
                )
            if isinstance(evidence_receipts, dict):
                for claim in REQUIRED_EVIDENCE:
                    if evidence_receipts.get(claim) == identity_digest:
                        errors.append(
                            f"evidence_receipts.{claim} cannot reuse provenance.{identity_role}"
                        )
    lifecycle = result.get("topology_lifecycle")
    if lifecycle != list(LIFECYCLE):
        errors.append("topology_lifecycle must contain the complete ordered lifecycle")
    return errors


def validate_matrix(matrix: dict[str, Any]) -> list[str]:
    """Validate a COMPLETE comparable qualification cohort, not host authenticity.

    Each of the six cell scales must contain one result per registered arm.
    Model/runtime digests can differ across arms, but all arms must bind the
    same code revision, source tree and target host. The external observer
    must still authenticate the digests and independently verify metrics.
    """
    if not isinstance(matrix, dict):
        return ["matrix must be an object"]
    errors: list[str] = []
    errors.extend(_reject_unregistered_keys(matrix, MATRIX_FIELDS, "matrix"))
    if matrix.get("schema") != "hepta.cell-execution-scale-matrix-result.v1":
        errors.append("matrix schema mismatch")
    if matrix.get("authority") != "qualification_only":
        errors.append("matrix authority must remain qualification_only")
    results = matrix.get("results")
    required_count = len(SIZES) * len(ARMS)
    if not isinstance(results, list):
        return errors + ["matrix results must be a list"]
    if len(results) != required_count:
        errors.append(f"matrix must contain exactly {required_count} results")
    # Fail closed without processing an arbitrarily large caller-supplied list.
    if len(results) > required_count:
        return errors

    expected = {(size, arm) for size in SIZES for arm in ARMS}
    seen: set[tuple[int, str]] = set()
    source_host: tuple[str, str, str] | None = None
    # Distinct arms/sizes cannot reuse the same retained measurement.
    metrics_receipts_seen: set[str] = set()
    measurement_digests_seen: set[str] = set()
    # Each experiment pair must retain its own independently observable
    # evidence for a given claim. Without this fence, one row's future-window
    # or rollback receipt can be replayed under a different routing arm.
    evidence_receipts_seen: dict[str, set[str]] = {
        claim: set() for claim in REQUIRED_EVIDENCE
    }
    # Preindex all role-typed identity digests before validating receipts.
    # This catches relabelling in either row order while retaining legitimate
    # repeated target-host/runtime identities in the same identity role.
    identity_roles_seen: dict[str, str] = {}
    for row in results:
        if not isinstance(row, dict):
            continue
        provenance = row.get("provenance")
        if not isinstance(provenance, dict):
            continue
        for role in ("target_host_digest", "runtime_digest"):
            value = provenance.get(role)
            if isinstance(value, str) and _HEX64.fullmatch(value):
                original_role = identity_roles_seen.setdefault(value, role)
                if original_role != role:
                    errors.append(
                        f"provenance.{role} reused as provenance.{original_role} identity"
                    )

    # Within each claim, no two experiment arms can share an observation.
    # Across different claim names, a digest also cannot certify a separate
    # row: a multi-claim attestation would need its own explicit schema.
    receipt_owners: dict[str, tuple[str, int]] = {}
    cohort_fields = ("source_commit", "source_tree", "target_host_digest")
    for index, row in enumerate(results):
        if not isinstance(row, dict):
            errors.append(f"results[{index}] must be an object")
            continue
        errors.extend(f"results[{index}].{error}" for error in validate_result(row))
        evidence_receipts = row.get("evidence_receipts")
        if isinstance(evidence_receipts, dict):
            for claim in REQUIRED_EVIDENCE:
                receipt = evidence_receipts.get(claim)
                if isinstance(receipt, str) and _HEX64.fullmatch(receipt):
                    identity_role = identity_roles_seen.get(receipt)
                    if identity_role is not None:
                        errors.append(
                            f"results[{index}].evidence_receipts.{claim} "
                            f"reused as provenance.{identity_role} identity"
                        )
                    if receipt in metrics_receipts_seen:
                        errors.append(
                            f"results[{index}].evidence_receipts.{claim} "
                            "reused as a metrics receipt"
                        )
                    if receipt in measurement_digests_seen:
                        errors.append(
                            f"results[{index}].evidence_receipts.{claim} "
                            "reused as a provenance measurement digest"
                        )
                    if receipt in evidence_receipts_seen[claim]:
                        errors.append(
                            f"results[{index}].evidence_receipts.{claim} "
                            "reused across matrix pairs"
                        )
                    evidence_receipts_seen[claim].add(receipt)
                    prior_claim, prior_row = receipt_owners.setdefault(
                        receipt, (claim, index)
                    )
                    if prior_claim != claim and prior_row != index:
                        errors.append(
                            f"results[{index}].evidence_receipts.{claim} "
                            "reused for a different evidence claim"
                        )
        metrics_receipt = row.get("metrics_receipt")
        if isinstance(metrics_receipt, str) and _HEX64.fullmatch(metrics_receipt):
            identity_role = identity_roles_seen.get(metrics_receipt)
            if identity_role is not None:
                errors.append(
                    f"results[{index}].metrics_receipt "
                    f"reused as provenance.{identity_role} identity"
                )
            if metrics_receipt in receipt_owners:
                errors.append(
                    f"results[{index}].metrics_receipt "
                    "reused as an evidence claim receipt"
                )
            if metrics_receipt in measurement_digests_seen:
                errors.append(
                    f"results[{index}].metrics_receipt "
                    "reused as a provenance measurement digest"
                )
            if metrics_receipt in metrics_receipts_seen:
                errors.append(
                    f"results[{index}].metrics_receipt reused across matrix pairs"
                )
            metrics_receipts_seen.add(metrics_receipt)
        provenance = row.get("provenance")
        if isinstance(provenance, dict):
            measurement_digest = provenance.get("measurement_digest")
            if (
                isinstance(measurement_digest, str)
                and _HEX64.fullmatch(measurement_digest)
            ):
                identity_role = identity_roles_seen.get(measurement_digest)
                if identity_role is not None:
                    errors.append(
                        f"results[{index}].provenance.measurement_digest "
                        f"reused as provenance.{identity_role} identity"
                    )
                if measurement_digest in measurement_digests_seen:
                    errors.append(
                        f"results[{index}].provenance.measurement_digest "
                        "reused across matrix pairs"
                    )
                if measurement_digest in metrics_receipts_seen:
                    errors.append(
                        f"results[{index}].provenance.measurement_digest "
                        "reused as a metrics receipt"
                    )
                if measurement_digest in receipt_owners:
                    errors.append(
                        f"results[{index}].provenance.measurement_digest "
                        "reused as an evidence claim receipt"
                    )
                measurement_digests_seen.add(measurement_digest)
        size, arm = row.get("size"), row.get("arm")
        if (
            type(size) is not int
            or size not in SIZES
            or not isinstance(arm, str)
            or arm not in ARMS
        ):
            continue
        pair = (size, arm)
        if pair in seen:
            errors.append(f"duplicate matrix pair: {size}/{arm}")
        seen.add(pair)
        provenance = row.get("provenance")
        if isinstance(provenance, dict) and all(
            isinstance(provenance.get(key), str) for key in cohort_fields
        ):
            identity = tuple(provenance[key] for key in cohort_fields)
            if source_host is None:
                source_host = identity
            elif identity != source_host:
                errors.append(
                    f"results[{index}].provenance differs from "
                    "matrix source/host cohort"
                )
    for size, arm in sorted(expected - seen):
        errors.append(f"missing matrix pair: {size}/{arm}")
    return errors


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("plan")
    validate = subparsers.add_parser("validate")
    validate.add_argument("result", type=argparse.FileType("rb"))
    validate_matrix_command = subparsers.add_parser("validate-matrix")
    validate_matrix_command.add_argument("result", type=argparse.FileType("rb"))
    args = parser.parse_args(argv)
    if args.command == "plan":
        json.dump(build_plan(), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    # Bound parsing before json.loads allocates an untrusted nested structure.
    payload = args.result.read(MAX_INPUT_BYTES + 1)
    if len(payload) > MAX_INPUT_BYTES:
        print("qualification input exceeds the 2 MiB limit", file=sys.stderr)
        return 1
    try:
        result = json.loads(
            payload,
            object_pairs_hook=_reject_duplicate_json_members,
            parse_constant=_reject_non_finite_json_constant,
        )
    except (ValueError, UnicodeError, RecursionError) as exc:
        print(f"invalid qualification JSON: {exc}", file=sys.stderr)
        return 1
    errors = (
        validate_matrix(result)
        if args.command == "validate-matrix"
        else validate_result(result)
    )
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    if args.command == "validate-matrix":
        print("valid qualification matrix shape (host authenticity unverified)")
    else:
        print("valid qualification result shape")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
