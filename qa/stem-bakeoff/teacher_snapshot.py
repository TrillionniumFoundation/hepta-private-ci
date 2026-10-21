#!/usr/bin/env python3
"""Offline, fail-closed byte inventory for candidate teacher checkpoints.

A matching digest proves ONLY that local files match an operator-pinned
inventory. It does not prove publisher identity, training, license grant,
independent model attestation, benchmark quality or production readiness.
No downloads, credentials, executable remote code or runtime mutation.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
from typing import Any

MODEL_TYPES = {
    "embeddinggemma2_740m": "embedding_gemma2",
    "t5gemma2_encoder_270m": "t5gemma2",
}
SHA256_RE = re.compile(r"[a-f0-9]{64}\Z")
SHA40_RE = re.compile(r"[a-f0-9]{40}\Z")
MAX_FILES = 10_000
MAX_BYTES = 32 * 1024 ** 3
CHUNK_SIZE = 1024 * 1024


class TeacherSnapshotError(ValueError):
    pass


def _is_sha(value: object, *, length: int) -> bool:
    return isinstance(value, str) and (
        SHA256_RE.fullmatch(value) if length == 64 else SHA40_RE.fullmatch(value)
    ) is not None


def inventory(snapshot: str | Path) -> dict[str, Any]:
    """Read regular, local files and hash full bytes; reject symlink escape."""
    root = Path(snapshot).absolute()
    if not root.is_dir() or root.is_symlink():
        raise TeacherSnapshotError("snapshot must be a real local directory")
    entries: list[dict[str, Any]] = []
    total = 0
    for parent, dirs, files in os.walk(root, followlinks=False):
        dirs.sort()
        files.sort()
        base = Path(parent)
        for name in dirs:
            child = base / name
            if child.is_symlink() or not child.is_dir():
                raise TeacherSnapshotError("snapshot may not contain symlink directories")
        for name in files:
            target = base / name
            metadata = target.lstat()
            if not stat.S_ISREG(metadata.st_mode):
                raise TeacherSnapshotError("snapshot may contain only regular files")
            if metadata.st_nlink != 1:
                raise TeacherSnapshotError("snapshot may not contain hardlink aliases")
            total += metadata.st_size
            if len(entries) >= MAX_FILES or total > MAX_BYTES:
                raise TeacherSnapshotError("checkpoint file/byte budget exceeded")
            digest = hashlib.sha256()
            with target.open("rb") as stream:
                while chunk := stream.read(CHUNK_SIZE):
                    digest.update(chunk)
            # Do not silently accept modified files during hashing.
            after = target.lstat()
            if (metadata.st_dev, metadata.st_ino, metadata.st_size,
                    metadata.st_mtime_ns, metadata.st_ctime_ns, metadata.st_nlink) != (
                    after.st_dev, after.st_ino, after.st_size,
                    after.st_mtime_ns, after.st_ctime_ns, after.st_nlink
            ):
                raise TeacherSnapshotError("snapshot changed while hashing")
            relative = target.relative_to(root).as_posix()
            entries.append({"path": relative, "bytes": metadata.st_size,
                            "sha256": digest.hexdigest()})
    entries.sort(key=lambda item: item["path"])
    canonical = json.dumps(entries, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return {
        "entries": entries,
        "inventory_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "total_bytes": total,
        "file_count": len(entries),
    }


def verify_snapshot(snapshot: str | Path, *, candidate: str,
                    revision: str, expected_inventory_sha256: str,
                    operator_accepted_terms: bool) -> dict[str, Any]:
    """Validate an explicitly pinned offline checkpoint; never select a model."""
    if candidate not in MODEL_TYPES:
        raise TeacherSnapshotError("unregistered teacher candidate")
    if not _is_sha(revision, length=40):
        raise TeacherSnapshotError("immutable upstream revision SHA40 required")
    if not _is_sha(expected_inventory_sha256, length=64):
        raise TeacherSnapshotError("external expected inventory SHA256 required")
    if operator_accepted_terms is not True:
        raise TeacherSnapshotError("explicit operator license acceptance required")

    contents = inventory(snapshot)
    if not hmac.compare_digest(contents["inventory_sha256"], expected_inventory_sha256):
        raise TeacherSnapshotError("checkpoint inventory does not match pinned digest")
    names = {row["path"] for row in contents["entries"]}
    if "config.json" not in names:
        raise TeacherSnapshotError("model config.json missing")
    if not any(name.endswith(".safetensors") for name in names):
        raise TeacherSnapshotError("safetensors checkpoint missing")
    try:
        config_item = next(row for row in contents["entries"]
                           if row["path"] == "config.json")
        if config_item["bytes"] > 1024 * 1024:
            raise TeacherSnapshotError("checkpoint config.json exceeds 1 MiB")
        config_path = Path(snapshot) / "config.json"
        if config_path.is_symlink():
            raise TeacherSnapshotError("checkpoint config.json became a symlink")
        # Re-read only bounded config bytes and confirm they match the pinned
        # inventory. A mutation between inventory and parse must not silently
        # change the model_type that was actually checked.
        config_bytes = config_path.read_bytes()
        if hashlib.sha256(config_bytes).hexdigest() != config_item["sha256"]:
            raise TeacherSnapshotError("checkpoint config.json changed after hashing")
        config = json.loads(config_bytes.decode("utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        if isinstance(error, TeacherSnapshotError):
            raise
        raise TeacherSnapshotError("invalid checkpoint config.json") from error
    if not isinstance(config, dict) or config.get("model_type") != MODEL_TYPES[candidate]:
        raise TeacherSnapshotError("checkpoint model_type not registered for candidate")

    return {
        "schema": "hepta.teacher-local-snapshot.v1",
        "candidate": candidate,
        "revision": revision,
        "inventory_sha256": contents["inventory_sha256"],
        "file_count": contents["file_count"],
        "total_bytes": contents["total_bytes"],
        "bytes_match_operator_pin": True,
        "publisher_identity_independently_verified": False,
        "pretrained_capability_verified": False,
        "license_verified_by_hepta": False,
        "operator_attests_terms_accepted": True,
        "authority": "DENY_ALL",
        "mode": "SHADOW_ONLY",
        "production_activation_allowed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--candidate", choices=sorted(MODEL_TYPES), required=True)
    parser.add_argument("--revision", required=True, help="immutable upstream SHA40")
    parser.add_argument("--expected-inventory-sha256", required=True)
    parser.add_argument("--operator-accepted-terms", action="store_true")
    args = parser.parse_args()
    try:
        receipt = verify_snapshot(
            args.snapshot, candidate=args.candidate, revision=args.revision,
            expected_inventory_sha256=args.expected_inventory_sha256,
            operator_accepted_terms=args.operator_accepted_terms,
        )
    except TeacherSnapshotError as error:
        print(json.dumps({"state": "REJECTED", "reason": str(error),
                          "authority": "DENY_ALL"}))
        return 2
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
