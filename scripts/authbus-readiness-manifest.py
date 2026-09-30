#!/usr/bin/env python3
"""Assemble the sole fail-closed AuthBus readiness manifest.

This program never infers success from source, queued jobs, copied status files,
or receipts from different workflow attempts. It accepts immutable receipts,
validates their common candidate identity, and emits one canonical manifest.
Missing external evidence is represented explicitly and keeps every readiness
decision false.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

EXACT_SCHEMA = "hepta.authbus.exact-head-evidence.v2"
TARGET_SCHEMA = "hepta.authbus.target-host-qualification.v2"
PERFORMANCE_SCHEMA = "hepta.authbus.performance-evidence.v1"
ACCEPTANCE_SCHEMA = "hepta.authbus.production-acceptance.v1"
MANIFEST_SCHEMA = "hepta.authbus.readiness-manifest.v1"
HEX = set("0123456789abcdef")


def load(path: Path | None, label: str) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None

    def unique(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in items:
            if key in value:
                raise ValueError(f"{label}: duplicate JSON key {key!r}")
            value[key] = item
        return value

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError(f"{label}: expected a JSON object")
    return value


def sha256(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def exact_string(value: Any, label: str, *, limit: int = 4096) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ValueError(f"{label}: expected a non-empty bounded string")
    return value


def optional_string(value: Any, label: str, *, limit: int = 4096) -> str | None:
    if value is None:
        return None
    return exact_string(value, label, limit=limit)


def sha1_or_none(value: Any, label: str) -> str | None:
    if value is None:
        return None
    value = exact_string(value, label, limit=40)
    if len(value) != 40 or any(character not in HEX for character in value):
        raise ValueError(f"{label}: expected lowercase 40-character SHA-1")
    return value


def nested(value: dict[str, Any], *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def lane(name: str, required: bool, status: str, receipt: Path | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "required": required,
        "status": status,
        "receiptSha256": sha256(receipt),
    }


def success_exact(receipt: dict[str, Any] | None, kind: str) -> bool:
    return bool(
        receipt
        and receipt.get("schema") == EXACT_SCHEMA
        and nested(receipt, "candidate", "kind") == kind
        and receipt.get("qualificationComplete") is True
        and receipt.get("trackedWorktreeClean") is True
    )


def acceptance_result(value: dict[str, Any] | None) -> str | None:
    if not value:
        return None
    for key in ("activationDecision", "decision", "verifiedOutput", "result"):
        result = value.get(key)
        if isinstance(result, str):
            return result
    return None


def external_lane_status(value: dict[str, Any] | None, schema: str) -> str:
    if value is None:
        return "missing"
    if value.get("schema") != schema:
        return "invalid"
    return "success"


def candidate_from_external(value: dict[str, Any] | None) -> str | None:
    if value is None:
        return None
    candidate = value.get("candidateSha")
    return candidate if isinstance(candidate, str) else None


def aggregate_artifacts(paths: Iterable[tuple[str, Path | None]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for name, path in paths:
        digest = sha256(path)
        if digest is not None:
            result[name] = digest
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-receipt", type=Path)
    parser.add_argument("--merge-receipt", type=Path)
    parser.add_argument("--source-projection", type=Path)
    parser.add_argument("--target-host", type=Path)
    parser.add_argument("--performance", type=Path)
    parser.add_argument("--production-acceptance", type=Path)
    parser.add_argument("--github-merge-sha")
    parser.add_argument("--final-merge-sha")
    parser.add_argument("--require-source-merge", action="store_true")
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()

    try:
        source = load(args.source_receipt, "source receipt")
        merge = load(args.merge_receipt, "merge receipt")
        projection = load(args.source_projection, "source projection")
        target = load(args.target_host, "target-host evidence")
        performance = load(args.performance, "performance evidence")
        acceptance = load(args.production_acceptance, "production acceptance")

        source_kind = nested(source or {}, "candidate", "kind")
        source_ok = bool(
            source
            and source.get("schema") == EXACT_SCHEMA
            and source_kind in {"exact_head", "main_head"}
            and source.get("qualificationComplete") is True
            and source.get("trackedWorktreeClean") is True
        )
        source_sha = sha1_or_none(nested(source or {}, "candidate", "commit"), "source SHA")
        source_tree = sha1_or_none(nested(source or {}, "candidate", "tree"), "source tree")
        merge_parents_candidate = nested(merge or {}, "candidate", "parents")
        fallback_base = (
            merge_parents_candidate[0]
            if isinstance(merge_parents_candidate, list) and merge_parents_candidate
            else None
        )
        base_sha = sha1_or_none(
            nested(source or {}, "pullRequest", "base") or fallback_base,
            "base SHA",
        )

        merge_required = source_kind != "main_head"
        merge_ok = success_exact(merge, "synthetic_merge")
        deterministic_merge_sha = sha1_or_none(
            nested(merge or {}, "candidate", "commit"), "deterministic merge SHA"
        )
        merge_parents = nested(merge or {}, "candidate", "parents")
        if merge is not None and (
            not isinstance(merge_parents, list) or len(merge_parents) != 2
        ):
            raise ValueError("merge receipt must bind exactly two parents")
        if merge_ok and source_sha is not None and merge_parents[1] != source_sha:
            raise ValueError("merge receipt head parent differs from source receipt")
        if merge_ok and base_sha is not None and merge_parents[0] != base_sha:
            raise ValueError("merge receipt base parent differs from source receipt")
        if merge_ok and source is not None:
            for identity_key in ("runId", "runAttempt", "repository", "workflowRef"):
                if nested(source, "workflow", identity_key) != nested(
                    merge, "workflow", identity_key
                ):
                    raise ValueError(
                        f"source and merge receipts differ on workflow.{identity_key}; "
                        "cross-attempt evidence cannot be combined"
                    )

        github_merge_sha = sha1_or_none(args.github_merge_sha, "GitHub merge SHA")
        if github_merge_sha is not None and deterministic_merge_sha != github_merge_sha:
            raise ValueError("GitHub merge SHA differs from verified synthetic merge receipt")
        final_merge_sha = sha1_or_none(args.final_merge_sha, "final merge SHA")

        target_status = external_lane_status(target, TARGET_SCHEMA)
        performance_status = external_lane_status(performance, PERFORMANCE_SCHEMA)
        for label, value in (("target-host", target), ("performance", performance)):
            external_candidate = candidate_from_external(value)
            if external_candidate is not None and source_sha is not None:
                if external_candidate != source_sha and external_candidate != final_merge_sha:
                    raise ValueError(f"{label} evidence names a different candidate")

        target_identity = None
        if target is not None:
            target_identity = optional_string(target.get("targetIdentity"), "target identity")
        if performance is not None:
            performance_identity = optional_string(
                performance.get("targetIdentity"), "performance target identity"
            )
            if target_identity is not None and performance_identity != target_identity:
                raise ValueError("performance and fault evidence name different target identities")
            target_identity = target_identity or performance_identity

        acceptance_status = external_lane_status(acceptance, ACCEPTANCE_SCHEMA)
        decision = acceptance_result(acceptance)
        acceptance_success = bool(
            acceptance_status == "success"
            and decision == "approved_for_canary"
            and nested(acceptance or {}, "securityReview", "verified") is True
            and nested(acceptance or {}, "operatorApproval", "verified") is True
            and (acceptance or {}).get("productionActivated") is False
            and (acceptance or {}).get("release") is False
        )

        source_projection_digest = sha256(args.source_projection)
        source_tree_hash = nested(projection or {}, "sourceDigest") or nested(
            source or {}, "digests", "relevantSource"
        )
        documentation_hash = nested(projection or {}, "documentDigest") or nested(
            source or {}, "digests", "evidenceProjections"
        )
        test_set_hash = nested(source or {}, "digests", "testLogs")
        qualification_profile_hash = canonical_hash(
            {
                "workflowRef": nested(source or {}, "workflow", "workflowRef"),
                "toolchain": (source or {}).get("toolchain"),
                "sourceProjection": source_projection_digest,
                "testSet": test_set_hash,
                "candidateKind": source_kind,
            }
        )

        external_status = "success" if acceptance_success else "missing"
        lanes = {
            "source_head": lane(
                "source_head",
                True,
                "success" if source_ok else ("missing" if source is None else "failed"),
                args.source_receipt,
            ),
            "deterministic_merge": lane(
                "deterministic_merge",
                merge_required,
                (
                    "not_applicable"
                    if not merge_required
                    else "success"
                    if merge_ok
                    else "missing"
                    if merge is None
                    else "failed"
                ),
                args.merge_receipt,
            ),
            "github_merge": lane(
                "github_merge",
                merge_required,
                (
                    "not_applicable"
                    if not merge_required
                    else "success"
                    if github_merge_sha is not None
                    else "missing"
                ),
            ),
            "final_merge": lane(
                "final_merge", True, "success" if final_merge_sha is not None else "missing"
            ),
            "target_host": lane("target_host", True, target_status, args.target_host),
            "performance": lane("performance", True, performance_status, args.performance),
            "kms_hsm": lane("kms_hsm", True, external_status),
            "backup_restore": lane("backup_restore", True, external_status),
            "dual_owner_mount": lane("dual_owner_mount", True, external_status),
            "security_signature": lane("security_signature", True, external_status),
            "operator_signature": lane("operator_signature", True, external_status),
        }
        all_required_success = all(
            (not row["required"]) or row["status"] in {"success", "not_applicable"}
            for row in lanes.values()
        )

        production_qualified = bool(all_required_success and acceptance_success)
        artifacts = aggregate_artifacts(
            (
                ("source_receipt", args.source_receipt),
                ("merge_receipt", args.merge_receipt),
                ("source_projection", args.source_projection),
                ("target_host", args.target_host),
                ("performance", args.performance),
                ("production_acceptance", args.production_acceptance),
            )
        )
        runner_image = {
            "os": nested(source or {}, "runner", "os"),
            "arch": nested(source or {}, "runner", "arch"),
            "name": nested(source or {}, "runner", "name"),
            "environment": nested(source or {}, "runner", "environment"),
            "image": nested(source or {}, "runner", "image"),
        }
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "module": "auth.authbus",
            "source_head_sha": source_sha,
            "source_head_tree_sha": source_tree,
            "base_sha": base_sha,
            "deterministic_merge_sha": deterministic_merge_sha,
            "github_merge_sha": github_merge_sha,
            "final_merge_sha": final_merge_sha,
            "workflow_run_id": nested(source or {}, "workflow", "runId"),
            "attempt_id": nested(source or {}, "workflow", "runAttempt"),
            "runner_image": runner_image,
            "rust_toolchain": nested(source or {}, "toolchain", "rustc"),
            "target_triple": nested(source or {}, "runner", "targetTriple"),
            "Cargo.lock_hash": nested(source or {}, "digests", "cargoLock"),
            "migration_hash": nested(source or {}, "digests", "schema"),
            "source_tree_hash": source_tree_hash,
            "documentation_hash": documentation_hash,
            "test_set_hash": test_set_hash,
            "qualification_profile_hash": qualification_profile_hash,
            "artifact_hashes": artifacts,
            "target_host_identity": target_identity,
            "required_lanes": lanes,
            "sourceCandidateQualified": bool(source_ok and (not merge_required or merge_ok)),
            "productionQualified": production_qualified,
            "mergeReady": production_qualified,
            "approvedForCanary": production_qualified,
            "productionActivated": False,
            "canaryPromotion": False,
            "release": False,
        }
    except (IndexError, KeyError, TypeError, ValueError) as error:
        raise SystemExit(f"AuthBus readiness manifest validation failed: {error}") from error

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if args.require_source_merge and not manifest["sourceCandidateQualified"]:
        raise SystemExit("source-head and deterministic-merge qualification are not both complete")
    if args.require_complete and not manifest["approvedForCanary"]:
        raise SystemExit("required production readiness evidence is incomplete")


if __name__ == "__main__":
    main()
