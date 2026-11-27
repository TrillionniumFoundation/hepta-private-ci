#!/usr/bin/env python3
"""Verify or restore historical Memory assets from reachable local Git objects.

No branch name, network fetch, extraction, or execution of archive contents is
needed. A shallow/partial clone must already contain the specified history and
blobs; the tool refuses missing objects instead of downloading them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess

SCHEMA = "hepta.historical-git-assets.v1"
MAX_ASSET_BYTES = 100 * 1024 * 1024
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def git(repo: Path, *arguments: str) -> bytes:
    environment = dict(os.environ)
    environment.update(GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0")
    # Protocol denials also prevent implicit promisor fetch on Git versions
    # predating GIT_NO_LAZY_FETCH. These are command overrides, not config edits.
    command = ["git", "--no-replace-objects", "-C", str(repo), "-c", "protocol.allow=never"]
    for protocol in ("file", "git", "http", "https", "ssh", "ext"):
        command.extend(["-c", f"protocol.{protocol}.allow=never"])
    result = subprocess.run(
        [*command, *arguments], env=environment, capture_output=True, check=False
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(
            f"Local Git verification failed ({' '.join(arguments)}): {detail}; "
            "the required ancestor history and blobs must already be available locally"
        )
    return result.stdout


def read_manifest(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema") != SCHEMA or value.get("git_object_format") != "sha1":
        raise ValueError("unsupported historical asset manifest")
    source = value.get("source_commit", "")
    if not isinstance(source, str) or not HEX40.fullmatch(source):
        raise ValueError("full source commit identity required")
    rows = value.get("files")
    if not isinstance(rows, list) or not rows or value.get("file_count") != len(rows):
        raise ValueError("complete nonempty asset inventory required")
    seen = set()
    total = 0
    for row in rows:
        raw = row.get("original_path", "")
        if not isinstance(raw, str):
            raise ValueError("asset path must be text")
        relative = PurePosixPath(raw)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or relative.as_posix() != raw
            or not raw.startswith("qa/")
            or "\\" in raw
            or any(ord(char) < 32 or ord(char) == 127 for char in raw)
            or raw in seen
        ):
            raise ValueError(f"unsafe or duplicate historical asset path: {raw!r}")
        seen.add(raw)
        if (
            row.get("source_commit") != source
            or row.get("mode") != "100644"
            or not isinstance(row.get("blob_oid"), str)
            or not HEX40.fullmatch(row["blob_oid"])
            or not isinstance(row.get("sha256"), str)
            or not HEX64.fullmatch(row["sha256"])
            or type(row.get("bytes")) is not int
            or not 0 < row["bytes"] <= MAX_ASSET_BYTES
        ):
            raise ValueError(f"incomplete historical asset identity: {raw}")
        total += row["bytes"]
    if value.get("total_bytes") != total:
        raise ValueError("historical asset byte total differs from inventory")
    return value


def verified_blob(repo: Path, row: dict) -> bytes:
    path = row["original_path"]
    oid = row["blob_oid"]
    tree_entry = git(repo, "ls-tree", "-z", row["source_commit"], "--", path)
    expected = f"100644 blob {oid}\t{path}\0".encode("utf-8")
    if tree_entry != expected:
        raise ValueError(f"asset is not the recorded path/blob in its source tree: {path}")
    if git(repo, "cat-file", "-t", oid).strip() != b"blob":
        raise ValueError(f"historical object is not a blob: {path}")
    if int(git(repo, "cat-file", "-s", oid)) != row["bytes"]:
        raise ValueError(f"historical blob size mismatch: {path}")
    data = git(repo, "cat-file", "blob", oid)
    canonical = b"blob " + str(len(data)).encode("ascii") + b"\0" + data
    if (
        len(data) != row["bytes"]
        or hashlib.sha256(data).hexdigest() != row["sha256"]
        or hashlib.sha1(canonical).hexdigest() != oid
    ):
        raise ValueError(f"historical blob hash mismatch: {path}")
    return data


def restore(repo: Path, manifest: Path, output: Path | None = None) -> dict:
    repo = repo.resolve(strict=True)
    data = read_manifest(manifest)
    if git(repo, "rev-parse", "--show-object-format").strip() != b"sha1":
        raise ValueError("manifest requires a SHA-1 Git object repository")
    source = data["source_commit"]
    if git(repo, "cat-file", "-t", source).strip() != b"commit":
        raise ValueError("source identity is not a commit")
    git(repo, "merge-base", "--is-ancestor", source, "HEAD")
    if output is not None:
        if output.exists() or output.is_symlink():
            raise ValueError("restore destination must be a new external directory")
        output = output.resolve()
        if output == repo or repo in output.parents:
            raise ValueError("restore destination must be outside the repository")
        output.mkdir(mode=0o700)
    checked = []
    for row in data["files"]:
        blob = verified_blob(repo, row)
        if output is not None:
            target = output.joinpath(*PurePosixPath(row["original_path"]).parts)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with target.open("xb") as stream:
                stream.write(blob)
            if hashlib.sha256(target.read_bytes()).hexdigest() != row["sha256"]:
                raise ValueError(f"restored byte check failed: {row['original_path']}")
        checked.append(row["original_path"])
    return {
        "schema": "hepta.historical-git-assets.receipt.v1",
        "source_commit": source,
        "head": git(repo, "rev-parse", "HEAD").decode("ascii").strip(),
        "files": len(checked),
        "bytes": data["total_bytes"],
        "sha256_and_git_blob_identity_verified": True,
        "source_is_head_ancestor": True,
        "output": str(output) if output is not None else None,
        "network_fetch_performed": False,
        "archive_extraction_or_execution_performed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[4])
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("HISTORICAL_ASSETS.json"))
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument("--verify-only", action="store_true")
    destination.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        receipt = restore(args.repo, args.manifest, args.output)
    except (ValueError, OSError) as error:
        parser.exit(1, f"FAIL_HISTORICAL_GIT_ASSETS: {error}\n")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
