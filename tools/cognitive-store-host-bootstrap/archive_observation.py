#!/usr/bin/env python3
"""Read-only publication reconciliation through the existing cold-image oracle.

Called by archive.py --reconcile-plan. A fresh independently signed observation
plan permits inspection of a possibly expired original operation. Neither a
matching output nor an absent one permits replay, retirement, erasure or a live
writer. Only disposable private scratch bytes are created and removed here.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat
import tempfile
import time

import archive
from lifecycle import digest, exact, identifier, integer, require, sha256

SCHEMA = "hepta.cognitive.archive-observation-plan.v1"
REPORT_SCHEMA = "hepta.cognitive.archive-publication-observation.v1"


def validate_observation(observation: dict, operation: dict, now: int) -> Path:
    exact(observation, {"schema", "request_id", "operation_plan_sha256", "purpose",
                        "created_at", "expires_at", "scratch_parent"})
    require(observation["schema"] == SCHEMA and
            observation["purpose"] == "reconcile_publication",
            "observation cannot grant archive, restore or erasure authority")
    identifier(observation["request_id"])
    digest(observation["operation_plan_sha256"])
    require(observation["operation_plan_sha256"] == sha256(operation),
            "observation names another original operation")
    integer(now)
    integer(observation["created_at"])
    integer(observation["expires_at"])
    require(observation["created_at"] <= now < observation["expires_at"],
            "observation authority is expired or future")
    scratch = archive.path_value(observation["scratch_parent"])
    require(scratch.resolve(strict=True) == scratch, "scratch path is redirected")
    metadata = scratch.stat(follow_symlinks=False)
    require(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == os.geteuid() and
            metadata.st_mode & 0o077 == 0, "scratch must be an owned private directory")
    for field in ("input_path", "output_path", "live_fleet_root"):
        protected = archive.path_value(operation[field])
        require(not scratch.is_relative_to(protected) and not protected.is_relative_to(scratch),
                "observation scratch overlaps the live fleet or original operation")
    return scratch


def observe_publication(operation: dict, observation: dict, key: bytes,
                        verifier: Path, reauthorize) -> dict:
    """Observe exact output bytes without mutating or adopting that output.

    Missing paths and missing manifests are unresolved, never NotApplied. A
    readable valid artifact does not prove an earlier fsync/acknowledgement.
    The trusted host must separately establish publication durability and the
    current cut before retirement or writable recovery.
    """
    now = int(time.time())
    scratch = validate_observation(observation, operation, now)
    archive.validate_plan(operation, now, require_live=False)
    require(sha256(reauthorize()) == sha256(operation), "operation changed before observation")
    destination = archive.path_value(operation["output_path"])
    result = "missing_or_incomplete"
    artifact_digest = None
    segments = None
    try:
        destination.stat(follow_symlinks=False)
        if operation["action"] == "archive":
            (destination / "manifest.json").stat(follow_symlinks=False)
        available = True
    except FileNotFoundError:
        available = False
    if available:
        # No source-side or destination-side checkpoint, chmod, rename, fsync,
        # unlink or mkdir occurs here. Native admission sees a scratch copy.
        # Missing verifier/dependencies or disappearance after preflight must
        # propagate, not be misclassified as an absent original output.
        with tempfile.TemporaryDirectory(prefix=".cognitive-observe-", dir=scratch) as temporary:
            staged = Path(temporary) / "cognitive_1.sqlite3"
            if operation["action"] == "archive":
                manifest = archive.decode_archive_image(destination, staged, operation, key, verifier)
                artifact_digest = sha256(manifest)
                segments = len(manifest["segments"])
                result = "valid_archive_observed"
            else:
                archive.copy_cold_image(destination, staged, operation)
                archive.native_check(staged, operation["anchor"], verifier, operation["verifier_sha256"])
                artifact_digest = operation["image_sha256"]
                result = "valid_restore_observed"
    require(sha256(reauthorize()) == sha256(operation), "operation changed during observation")
    completed_at = int(time.time())
    validate_observation(observation, operation, completed_at)
    report = {"schema": REPORT_SCHEMA, "operation_plan_sha256": sha256(operation),
              "observation_plan_sha256": sha256(observation), "observed_at": completed_at,
              "owner_agent_id": operation["owner_agent_id"], "writer_generation": operation["writer_generation"],
              "anchor": operation["anchor"], "image_sha256": operation["image_sha256"],
              "artifact_sha256": artifact_digest, "segments": segments, "result": result,
              "artifact_verified": artifact_digest is not None,
              "publication_durability_proved": False, "replay_authorized": False,
              "grants_authority": False, "source_preserved": True,
              "production_activated": False, "physical_erasure_proved": False,
              "hot_history_pruned": False, "target_host_qualified": False}
    report["report_sha256"] = sha256(report)
    return report
