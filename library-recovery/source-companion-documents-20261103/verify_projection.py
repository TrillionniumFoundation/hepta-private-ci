#!/usr/bin/env python3
"""Verify document and affected peer bytes; never execute preserved source."""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from verify_source_custody_container import (
    FOLLOWUP,
    MAX_CONTROL,
    MAX_TAR,
    identity,
    read_regular,
    require,
    resolve_original_paths,
    unique_object,
)

if sys.flags.optimize:
    raise SystemExit("optimized Python is refused")

root = Path(__file__).resolve().parent
original_manifest = read_regular(root, "SOURCE_MANIFEST.json", MAX_CONTROL)
require(
    identity(original_manifest)["oid"] == "db63cae4f1609c02bd95cd9971304b697787a1b1",
    "original companion manifest drift",
)
manifest = json.loads(original_manifest, object_pairs_hook=unique_object)
seen = set()
for row in manifest["candidates"] + manifest["notices"]:
    path = root / row["relative_path"]
    require(path.resolve().is_relative_to(root), "projection path escaped root")
    raw = read_regular(root, row["relative_path"], MAX_TAR)
    actual = identity(raw)
    require(actual["bytes"] == row["bytes"], row["relative_path"] + ": size")
    require(actual["sha256"] == row["sha256"], row["relative_path"] + ": SHA256")
    require(actual["oid"] == row["git_blob_sha"], row["relative_path"] + ": Git blob")
    require(row["git_blob_sha"] not in seen, "duplicate object")
    seen.add(row["git_blob_sha"])
require(len(manifest["candidates"]) == manifest["candidate_count"], "candidate count")

affected = []
for candidate in manifest["candidates"]:
    for peer in candidate.get("same_original_package_verified_source_peers", []):
        reference = peer.get("verified_peer_reference", {})
        path = reference.get("path")
        if isinstance(path, str) and path.startswith(FOLLOWUP + "/"):
            affected.append((path, peer["git_blob_sha"], reference["git_blob_sha"]))
paths = sorted({path for path, _, _ in affected})
require(
    len(affected) == 30 and len(paths) == 25, "affected peer reference count changed"
)
resolved = resolve_original_paths(root.parents[1], paths)
for path, peer_oid, reference_oid in affected:
    require(
        identity(resolved[path])["oid"] == peer_oid == reference_oid,
        "preserved peer identity differs: " + path,
    )
print(
    json.dumps(
        {
            "candidate_count": len(manifest["candidates"]),
            "notice_count": len(manifest["notices"]),
            "all_bytes_match_manifest": True,
            "affected_peer_occurrences_verified": len(affected),
            "affected_peer_paths_verified": len(paths),
            "archived_source_executed": False,
            "research_or_runtime_qualification": False,
        }
    )
)
