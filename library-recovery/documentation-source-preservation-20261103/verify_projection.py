#!/usr/bin/env python3
"""Verify the original manifest through gzip carriers; never execute source."""

import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from verify_frozen_gzip import read_original
from verify_source_custody_container import (
    MAX_CONTROL,
    identity,
    read_regular,
    require,
    unique_object,
)

MANIFEST_OID = "cbd3806d33c0350c47959c32cad4a0293e2a4c7a"
CARRIER_MANIFEST_SHA256 = (
    "cd0c9e761e5c9a4b7382032128b3ada9f35b5de2db90a91b559db14a9356e7d7"
)


def verify(root):
    require(not sys.flags.optimize, "optimized Python is refused")
    raw_manifest = read_regular(root, "SOURCE_MANIFEST.json", MAX_CONTROL)
    require(identity(raw_manifest)["oid"] == MANIFEST_OID, "original manifest drift")
    manifest = json.loads(raw_manifest, object_pairs_hook=unique_object)
    raw_carriers = read_regular(root, "GZIP_MANIFEST.json", MAX_CONTROL)
    require(
        hashlib.sha256(raw_carriers).hexdigest() == CARRIER_MANIFEST_SHA256,
        "registered carrier manifest drift",
    )
    carriers = json.loads(raw_carriers, object_pairs_hook=unique_object)
    require(
        carriers["schema"] == "hepta.frozen-gzip-projection.v1"
        and carriers["original_manifest"]
        == {"path": "SOURCE_MANIFEST.json", **identity(raw_manifest)}
        and carriers["source_executed"] is False
        and carriers["scientific_or_runtime_qualification"] is False,
        "carrier identity or qualification boundary drift",
    )
    entries = {entry["path"]: entry for entry in carriers["members"]}
    require(len(entries) == len(carriers["members"]), "duplicate carrier member")
    rows = manifest["candidates"] + manifest["notices"]
    require(
        set(entries)
        == {row["relative_path"] for row in rows}
        | {"README.md", "verify_projection.py"},
        "carrier membership mismatch",
    )
    seen = set()
    for row in rows:
        entry = entries[row["relative_path"]]
        require(
            entry["role"] == "candidate"
            and entry["original"]
            == {
                "bytes": row["bytes"],
                "sha256": row["sha256"],
                "oid": row["git_blob_sha"],
            },
            "carrier does not bind the original manifest row",
        )
        read_original(root, entry)
        require(row["git_blob_sha"] not in seen, "duplicate object")
        seen.add(row["git_blob_sha"])
    for name in ("README.md", "verify_projection.py"):
        entry = entries[name]
        require(entry["role"] == "prior_control", "original control role mismatch")
        read_original(root, entry)
    require(
        len(manifest["candidates"]) == manifest["candidate_count"], "candidate count"
    )
    require(
        sum(row["bytes"] for row in manifest["candidates"])
        == manifest["candidate_bytes"],
        "candidate byte count",
    )
    return {
        "candidate_count": len(manifest["candidates"]),
        "notice_count": len(manifest["notices"]),
        "all_bytes_match_manifest": True,
        "archived_source_executed": False,
        "research_or_runtime_qualification": False,
    }


if __name__ == "__main__":
    print(json.dumps(verify(Path(__file__).resolve().parent)))
