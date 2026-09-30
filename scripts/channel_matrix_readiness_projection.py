#!/usr/bin/env python3
"""Project one readiness manifest into an atomic, non-mixable status bundle.

The generated files are evidence artifacts. They are never written back into the
checkout, so the exact source SHA cannot be made self-referential and a failed
run cannot partially update one status surface while leaving another stale.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

SHA1 = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
MAX_MANIFEST_BYTES = 64 * 1024 * 1024
OUTPUT_NAMES = (
    "MODULE_STATUS.json",
    "CURRENT_STATUS.md",
    "EXACT_CANDIDATE_EVIDENCE.json",
    "ARTIFACT_PROVENANCE.json",
)


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_manifest(path: Path) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError("readiness manifest must be one bounded regular file")
    data = path.read_bytes()
    row = json.loads(data)
    if not isinstance(row, dict):
        raise ValueError("readiness manifest must be a JSON object")
    return row, data


def exact_sha(row: dict[str, Any], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not SHA1.fullmatch(value):
        raise ValueError(f"readiness manifest lacks exact Git identity: {field}")
    return value


def exact_sha256(row: dict[str, Any], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise ValueError(f"readiness manifest lacks exact SHA-256 identity: {field}")
    return value


def validate(row: dict[str, Any]) -> None:
    if row.get("schema") != "hepta.channel-matrix-readiness.v1":
        raise ValueError("unsupported readiness manifest schema")
    for field in (
        "source_head_sha",
        "base_sha",
        "deterministic_merge_sha",
        "github_merge_sha",
        "workflow_sha",
    ):
        exact_sha(row, field)
    exact_sha256(row, "candidate_key")
    for field in (
        "Cargo.lock_hash",
        "test_set_hash",
        "migration_hash",
        "implementation_map_hash",
        "documentation_hash",
    ):
        exact_sha256(row, field)
    for field in ("workflow_run_id", "attempt_id"):
        value = row.get(field)
        if not isinstance(value, str) or not value:
            raise ValueError(f"readiness manifest lacks execution identity: {field}")
    artifact_hashes = row.get("artifact_hashes")
    if not isinstance(artifact_hashes, dict) or not artifact_hashes:
        raise ValueError("readiness manifest lacks immutable artifact hashes")
    for name, value in artifact_hashes.items():
        if not isinstance(name, str) or not name or not isinstance(value, str) or not SHA256.fullmatch(value):
            raise ValueError("readiness manifest has invalid artifact identity")
    lane_status = row.get("lane_status")
    if not isinstance(lane_status, dict):
        raise ValueError("readiness manifest lacks lane status")
    for field in ("activation", "promotion", "release", "authorityGranted"):
        if row.get(field) is not False:
            raise ValueError(f"repository readiness may not grant {field}")


def projections(row: dict[str, Any], manifest_sha256: str) -> dict[str, bytes]:
    candidate = {
        "candidateKey": row["candidate_key"],
        "sourceHeadSha": row["source_head_sha"],
        "baseSha": row["base_sha"],
        "deterministicMergeSha": row["deterministic_merge_sha"],
        "githubMergeSha": row["github_merge_sha"],
        "finalMergeSha": row.get("final_merge_sha"),
        "workflowSha": row["workflow_sha"],
        "workflowRunId": row["workflow_run_id"],
        "attemptId": row["attempt_id"],
        "readinessManifestSha256": manifest_sha256,
    }
    lane_status = row["lane_status"]
    module_status = {
        "schema": "hepta.channel-matrix-module-status-artifact.v1",
        "module": "channel.matrix",
        "candidate": candidate,
        "repositoryQualified": row.get("repositoryQualified") is True,
        "mergeReady": row.get("mergeReady") is True,
        "productionQualified": row.get("productionQualified") is True,
        "targetQualification": lane_status.get("target_qualification", "not_proved"),
        "independentAcceptance": lane_status.get("independent_acceptance", "not_proved"),
        "activation": False,
        "promotion": False,
        "release": False,
        "authorityGranted": False,
    }
    exact_evidence = {
        "schema": "hepta.channel-matrix-exact-candidate-evidence.v1",
        "candidate": candidate,
        "runnerImage": row.get("runner_image"),
        "targetTriple": row.get("target_triple"),
        "laneStatus": lane_status,
        "requiredLanes": row.get("required_lanes"),
        "repositoryQualified": row.get("repositoryQualified") is True,
        "mergeReady": row.get("mergeReady") is True,
        "productionQualified": row.get("productionQualified") is True,
        "activation": False,
        "promotion": False,
        "release": False,
        "authorityGranted": False,
    }
    artifact_provenance = {
        "schema": "hepta.channel-matrix-artifact-provenance.v1",
        "candidate": candidate,
        "sourceHashes": {
            "Cargo.lock": row["Cargo.lock_hash"],
            "testSet": row["test_set_hash"],
            "migrations": row["migration_hash"],
            "implementationMap": row["implementation_map_hash"],
            "documentation": row["documentation_hash"],
        },
        "artifactHashes": row["artifact_hashes"],
        "crossCandidateMixingAllowed": False,
        "crossWorkflowRunMixingAllowed": False,
        "crossAttemptMixingAllowed": False,
        "authorityGranted": False,
    }
    status_lines = [
        "# channel.matrix exact-candidate status",
        "",
        f"- Candidate key: `{row['candidate_key']}`",
        f"- Source head: `{row['source_head_sha']}`",
        f"- Base: `{row['base_sha']}`",
        f"- Deterministic merge: `{row['deterministic_merge_sha']}`",
        f"- GitHub merge: `{row['github_merge_sha']}`",
        f"- Workflow/run/attempt: `{row['workflow_sha']}` / `{row['workflow_run_id']}` / `{row['attempt_id']}`",
        f"- Repository qualified: `{str(row.get('repositoryQualified') is True).lower()}`",
        f"- Merge ready: `{str(row.get('mergeReady') is True).lower()}`",
        f"- Target qualification: `{lane_status.get('target_qualification', 'not_proved')}`",
        f"- Independent acceptance: `{lane_status.get('independent_acceptance', 'not_proved')}`",
        f"- Production qualified: `{str(row.get('productionQualified') is True).lower()}`",
        "- Activation/promotion/release/authority: `false / false / false / false`",
        "",
        "This file and the three JSON projections were generated atomically from the",
        "same immutable readiness manifest. They do not grant deployment or external",
        "effect authority.",
        "",
    ]
    return {
        "MODULE_STATUS.json": canonical_bytes(module_status),
        "CURRENT_STATUS.md": "\n".join(status_lines).encode("utf-8"),
        "EXACT_CANDIDATE_EVIDENCE.json": canonical_bytes(exact_evidence),
        "ARTIFACT_PROVENANCE.json": canonical_bytes(artifact_provenance),
    }


def write_bundle(output: Path, files: dict[str, bytes], manifest_sha256: str) -> None:
    output = output.absolute()
    parent = output.parent.resolve(strict=True)
    if output.exists() or output.is_symlink():
        raise ValueError("status bundle output must not already exist")
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=parent))
    try:
        inventory: dict[str, dict[str, object]] = {}
        for name in OUTPUT_NAMES:
            data = files[name]
            path = staging / name
            with path.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            inventory[name] = {"sha256": digest_bytes(data), "bytes": len(data)}
        bundle = canonical_bytes(
            {
                "schema": "hepta.channel-matrix-status-bundle.v1",
                "readinessManifestSha256": manifest_sha256,
                "files": inventory,
                "atomicProjection": True,
                "authorityGranted": False,
            }
        )
        with (staging / "STATUS_BUNDLE.json").open("xb") as stream:
            stream.write(bundle)
            stream.flush()
            os.fsync(stream.fileno())
        directory_fd = os.open(staging, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        os.replace(staging, output)
        parent_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        row, raw = read_manifest(args.manifest)
        validate(row)
        manifest_sha256 = digest_bytes(raw)
        write_bundle(args.output_dir, projections(row, manifest_sha256), manifest_sha256)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(1, f"FAIL_CHANNEL_MATRIX_READINESS_PROJECTION: {exc}\n")
    print("PASS_CHANNEL_MATRIX_READINESS_PROJECTION")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
