import base64
import gzip
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
manifest = json.loads((ROOT / "export-manifest.json").read_bytes())

def require(ok, message):
    if not ok:
        raise RuntimeError(message)

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()

def serialized(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()

for entry in manifest["exported_files"]:
    path = ROOT / entry["path"]
    require(not path.is_symlink() and path.is_file(), "Missing regular export file: " + entry["path"])
    raw = path.read_bytes()
    require(len(raw) == entry["bytes"], "Export size mismatch: " + entry["path"])
    require(sha(raw) == entry["sha256"], "Export SHA256 mismatch: " + entry["path"])
    require(blob(raw) == entry["git_blob_sha1"], "Export Git blob mismatch: " + entry["path"])

reconstructed = {}
for artifact in manifest["artifacts"]:
    chunks = []
    offset = 0
    line_offset = 0
    for part in artifact["parts"]:
        compressed = (ROOT / part["path"]).read_bytes()
        require(len(compressed) <= manifest["gzip"]["maximum_part_bytes"], "Oversized gzip part")
        require(compressed[:3] == b"\x1f\x8b\x08" and compressed[3] == 0, "Unexpected gzip header")
        require(compressed[4:8] == b"\0\0\0\0", "Nonzero gzip timestamp")
        raw = gzip.decompress(compressed)
        require(part["raw_start_offset"] == offset, "Noncontiguous raw offsets")
        require(part["raw_end_offset"] == offset + len(raw), "Incorrect raw end offset")
        require(part["raw_sha256"] == sha(raw), "Incorrect part raw hash")
        require(part["raw_line_start"] == line_offset, "Noncontiguous line offsets")
        require(part["raw_line_count"] == len(raw.splitlines()), "Incorrect raw line count")
        offset += len(raw)
        line_offset += len(raw.splitlines())
        chunks.append(raw)
    whole = b"".join(chunks)
    require(len(whole) == artifact["raw_bytes"], "Reconstructed artifact size mismatch")
    require(sha(whole) == artifact["raw_sha256"], "Reconstructed artifact SHA256 mismatch")
    require(blob(whole) == artifact["raw_git_blob_sha1"], "Reconstructed artifact Git blob mismatch")
    reconstructed[artifact["id"]] = whole

refs = json.loads(reconstructed["captured-refs"])
names = sorted(refs)
memberships = json.loads(reconstructed["coverage-membership"])
require(memberships["captured_refs_sha256"] == sha(reconstructed["captured-refs"]), "Wrong coverage name index")
for item in memberships["maps"]:
    indices = item["name_indices"]
    require(indices == sorted(set(indices)), "Duplicate or unordered membership indices")
    require(all(type(i) is int and 0 <= i < len(names) for i in indices), "Invalid membership index")
    value = {names[i]: refs[names[i]] for i in indices}
    raw = serialized(value)
    require(len(value) == item["name_count"], "Coverage membership count mismatch")
    require(len(raw) == item["original_bytes"], "Coverage original byte-size mismatch")
    require(sha(raw) == item["original_sha256"], "Coverage original SHA256 mismatch")
    require(blob(raw) == item["original_git_blob_sha1"], "Coverage original Git blob mismatch")

require(len(refs) == manifest["snapshot"]["captured_ref_count"], "Ref count mismatch")
protected = json.loads(reconstructed["protected-classification"])
require(len(protected) == manifest["snapshot"]["protected_name_count"], "Protected classification count mismatch")
require(len(reconstructed["complete-parent-graph"].splitlines()) == manifest["snapshot"]["parent_graph_nodes"], "Graph line count mismatch")
print(json.dumps({
    "outcome": "PASS_OFFLINE_BYTE_ROUNDTRIP",
    "exported_files_verified": len(manifest["exported_files"]),
    "exact_raw_artifacts": len(reconstructed),
    "exact_original_coverage_maps_reconstructed": len(memberships["maps"]),
    "coverage_source_paths_including_aliases": sum(len(x["source_paths"]) for x in memberships["maps"]),
    "classification_or_git_executed": False,
    "network_used": False
}, indent=2, sort_keys=True))
