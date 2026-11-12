#!/usr/bin/env python3
"""Read-only exact-source identity audit. This is not a product or native test."""
from pathlib import Path
import hashlib
import json
import tomllib

ROOT = Path(__file__).resolve().parent
manifest = json.loads((ROOT / "SOURCE_MANIFEST.json").read_text())
if manifest["base_commit"] != "094958b83a8fd19e3bc6d01a092793c0f420bb75":
    raise SystemExit("unexpected audit baseline")
mismatches = []
for record in manifest["files"]:
    path = ROOT / "source" / record["path"]
    raw = path.read_bytes()
    actual_sha = hashlib.sha256(raw).hexdigest()
    actual_git = hashlib.sha1(b"blob " + str(len(raw)).encode() + bytes([0]) + raw).hexdigest()
    if actual_sha != record["sha256"] or actual_git != record["git_blob"]:
        mismatches.append(record["path"])
callers = tomllib.loads((ROOT / "source" / "CALLERS.toml").read_text())
boundaries = {row["id"]: row for row in callers["boundary"]}
boundary_mismatches = []
for expected in manifest["evidence_boundaries"]:
    actual = boundaries.get(expected["id"])
    if actual is None or any(actual.get(key) != expected[key] for key in ("symbol", "product_callers")):
        boundary_mismatches.append(expected["id"])
result = {
    "kind": "exact-source identity readback, not product behavior verification",
    "base_commit": manifest["base_commit"],
    "source_files_verified": len(manifest["files"]),
    "source_mismatches": mismatches,
    "boundary_rows_verified": len(manifest["evidence_boundaries"]),
    "boundary_mismatches": boundary_mismatches,
    "production_changes": 0,
    "native": "UNRUN",
    "ordinary_qualification_added": 0,
}
print(json.dumps(result, indent=2))
raise SystemExit(bool(mismatches or boundary_mismatches))
