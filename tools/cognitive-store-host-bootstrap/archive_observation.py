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
import time

import archive
from archive_publication import PinnedDirectory, inode
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
    def final_authorization() -> int:
        require(sha256(reauthorize()) == sha256(operation), "operation changed during observation")
        completed = int(time.time())
        require(completed >= now, "observation clock regressed")
        validate_observation(observation, operation, completed)
        return completed

    destination = archive.path_value(operation["output_path"])
    result = "missing_or_incomplete"
    artifact_digest = None
    segments = None
    # Pin the authenticated scratch root BEFORE calling external verification.
    # Replacing a path during that call must not move later writes or cleanup.
    with PinnedDirectory.open(scratch) as parent:
        require(sha256(reauthorize()) == sha256(operation), "operation changed before observation")
        parent.check_current()
        try:
            destination.stat(follow_symlinks=False)
            if operation["action"] == "archive":
                (destination / "manifest.json").stat(follow_symlinks=False)
            available = True
        except FileNotFoundError:
            available = False
        if available:
            # Use the same descriptor-relative staging owner as publication.
            # Cleanup removes only its created image inode, not replacements,
            # unknown children or recursively discovered historical content.
            with parent.scratch() as stage:
                staged = stage.path / "cognitive_1.sqlite3"
                if operation["action"] == "archive":
                    manifest = archive.decode_archive_image(
                        destination, staged, operation, key, verifier, publication_stage=stage)
                    artifact_digest = sha256(manifest)
                    segments = len(manifest["segments"])
                    result = "valid_archive_observed"
                else:
                    archive.copy_cold_image(destination, staged, operation, publication_stage=stage)
                    archive.native_check(staged, operation["anchor"], verifier, operation["verifier_sha256"])
                    artifact_digest = operation["image_sha256"]
                    result = "valid_restore_observed"
                with stage.reader(staged.name, operation["image_bytes"]) as image:
                    def verify_image() -> None:
                        parent.check_current()
                        stage.check_current()
                        retained = os.fstat(image.fileno())
                        named = os.stat(staged.name, dir_fd=stage.fd, follow_symlinks=False)
                        require(stage.created_files.get(staged.name) == inode(retained) == inode(named) and
                                stat.S_ISREG(retained.st_mode) and retained.st_nlink == 1 and
                                retained.st_uid == os.geteuid() and retained.st_mode & 0o077 == 0,
                                "observed scratch image is not the private created inode")
                        archive.verify_staged_stream(image, operation)
                        after = os.fstat(image.fileno())
                        current = os.stat(staged.name, dir_fd=stage.fd, follow_symlinks=False)
                        require(archive.identity(retained) == archive.identity(after) ==
                                archive.identity(current), "observed image changed during final read")
                    verify_image()
                    completed_at = final_authorization()
                    verify_image()
        else:
            completed_at = final_authorization()
        parent.check_current()
        completed_at = int(time.time())
        require(completed_at >= now, "observation clock regressed")
        validate_observation(observation, operation, completed_at)
        parent.check_current()
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
