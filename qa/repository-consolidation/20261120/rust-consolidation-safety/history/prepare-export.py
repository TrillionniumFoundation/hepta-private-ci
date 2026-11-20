import collections
import gzip
import hashlib
import io
import json
import os
import pathlib
import stat
import subprocess
import sys
import zlib

AUDIT_ROOT = pathlib.Path("/home/qian-qi/hepta-rust-protection-20261120-0cee")
EVIDENCE = AUDIT_ROOT / "history-audit-evidence"
EXPORT = pathlib.Path(os.environ.get("HEPTA_AUDIT_EXPORT_DIRECTORY", str(EVIDENCE / "export")))
MAX_GZIP_BYTES = 256 * 1024
INITIAL_RAW_PART_BYTES = 512 * 1024
SOURCE_EXPECTED = "d5d4047be9282be9760af63a9a0aa1e3e33e4cd85775025fbdf18b91e0aad5f7"
MANIFEST_EXPECTED = "262d189d478d0a072e5b2c6ae278b2fe084ca0cedba92df7960cc0d05546791f"
RESULT_EXPECTED = "1a94c299150ebad0feb080d7aa666c8624d16fcd1325c0f9c5b6cb2f3c7fd8ca"
PROVENANCE = json.loads("{\"preflight_v2_request\":{\"host\":\"rog\",\"executable\":\"/usr/bin/python3\",\"args\":[\"-\"],\"cwd\":\"/home/qian-qi/hepta-rust-protection-20261120-0cee\",\"stdin\":\"import datetime, hashlib, json, os, pathlib, shutil, subprocess, sys\\nroot = pathlib.Path(\\\"/home/qian-qi/hepta-rust-protection-20261120-0cee\\\")\\nhistory = root / \\\"history.git\\\"\\nevidence = root / \\\"history-audit-evidence\\\"\\nif not root.is_dir() or root.is_symlink() or root.resolve() != root:\\n    raise RuntimeError(\\\"Authorized isolated root is absent or indirect\\\")\\nfor target in (history, evidence):\\n    if os.path.lexists(target):\\n        raise RuntimeError(\\\"Refuse existing target: \\\" + str(target))\\ngit = shutil.which(\\\"git\\\")\\nif not git:\\n    raise RuntimeError(\\\"Git unavailable\\\")\\nversion = subprocess.run([git, \\\"--version\\\"], text=True, capture_output=True, timeout=15)\\nif version.returncode:\\n    raise RuntimeError(\\\"Git version failed\\\")\\nhelp_run = subprocess.run([git, \\\"fetch\\\", \\\"-h\\\"], cwd=root, text=True, capture_output=True, timeout=15)\\nhelp_text = help_run.stdout + help_run.stderr\\nexpected = {\\n    \\\"hepta_branch_consolidation.py\\\": \\\"d5d4047be9282be9760af63a9a0aa1e3e33e4cd85775025fbdf18b91e0aad5f7\\\",\\n    \\\"protected-branches.json\\\": \\\"262d189d478d0a072e5b2c6ae278b2fe084ca0cedba92df7960cc0d05546791f\\\",\\n}\\ninputs = []\\nfor name, sha in expected.items():\\n    path = root / \\\"candidate\\\" / \\\"tools\\\" / \\\"branch-consolidation\\\" / name\\n    if path.is_symlink() or not path.is_file():\\n        raise RuntimeError(\\\"Candidate input not regular\\\")\\n    raw = path.read_bytes()\\n    got = hashlib.sha256(raw).hexdigest()\\n    if got != sha:\\n        raise RuntimeError(\\\"Candidate changed: \\\" + name)\\n    inputs.append({\\\"path\\\": str(path), \\\"bytes\\\": len(raw), \\\"sha256\\\": got})\\nspace = shutil.disk_usage(root)\\nif space.free < 4 * 1024**3:\\n    raise RuntimeError(\\\"Insufficient isolated fetch disk headroom\\\")\\nevidence.mkdir(mode=0o700)\\nrecord = {\\n    \\\"schema\\\": \\\"hepta.commit-only-history-audit-preflight.v1\\\",\\n    \\\"observed_at_utc\\\": datetime.datetime.now(datetime.timezone.utc).isoformat(),\\n    \\\"root\\\": str(root), \\\"new_bare_repository\\\": str(history),\\n    \\\"git_executable\\\": git, \\\"git_version\\\": version.stdout.strip(),\\n    \\\"git_fetch_help_exit\\\": help_run.returncode,\\n    \\\"git_fetch_filter_in_short_help\\\": \\\"--filter\\\" in help_text,\\n    \\\"server_filter_capability_verified\\\": False,\\n    \\\"predecessor_job\\\": \\\"1a1f6a7093b-ffbe-1523\\\",\\n    \\\"predecessor_outcome\\\": \\\"FAILED1: short-help text did not prove filter support; no fetch attempted\\\",\\n    \\\"disk_free_bytes\\\": space.free, \\\"inputs\\\": inputs,\\n    \\\"remote_mutations_authorized\\\": False,\\n    \\\"fetch_filter_required\\\": \\\"tree:0\\\",\\n    \\\"classification_no_lazy_fetch_required\\\": True,\\n    \\\"history_existed\\\": False, \\\"classification_performed\\\": False,\\n}\\n(evidence / \\\"preflight.json\\\").write_text(json.dumps(record, indent=2) + \\\"\\\\n\\\")\\n(evidence / \\\"git-fetch-help.txt\\\").write_text(help_text)\\nprint(json.dumps(record, indent=2))\\n\",\"cpu_quota_percent\":100,\"memory_max_bytes\":2147483648,\"nice\":10,\"timeout_seconds\":60,\"idempotency_key\":\"hepta-rust-protection-0cee-history-preflight-20261120-v2\"},\"native_job\":{\"host\":\"rog\",\"job_id\":\"1a1f6b645e3-ffbe-1534\",\"start\":{\"audit_recorded\":true,\"job\":{\"args\":[\"/home/qian-qi/hepta-rust-protection-20261120-0cee/history-audit-evidence/full-history-audit.py\"],\"created_unix_ms\":1795140503011,\"cwd\":\"/home/qian-qi/hepta-rust-protection-20261120-0cee\",\"env_keys\":[\"HEPTA_HISTORY_AUDIT_SCRIPT_SHA256\"],\"executable\":\"/usr/bin/python3\",\"execution_mode\":\"operator\",\"host\":\"rog\",\"id\":\"1a1f6b645e3-ffbe-1534\",\"idempotency_key\":\"hepta-rust-protection-0cee-full-history-audit-20261120-v1\",\"launch_error\":null,\"launch_state\":\"launched\",\"remote_job_dir\":\"/home/qian-qi/.local/state/hepta-runtime-mac-worker/jobs/1a1f6b645e3-ffbe-1534\",\"request_digest\":\"56bc1a2882c91b1fb9448402632a29cc57f00753d70e68f81ecbb882b1f809ed\",\"request_fingerprint\":6249899144178638000,\"ssh_target\":\"rog-ts\",\"system_jobctl\":false,\"unit\":\"hepta-runtime-job-1a1f6b645e3-ffbe-1534\"},\"launch\":{\"backend\":\"systemd\",\"launcher_pid\":null,\"ok\":true,\"unit\":\"hepta-runtime-job-1a1f6b645e3-ffbe-1534\"},\"local_record_pending\":false,\"reused\":false},\"terminal_status\":{\"at_unix_ms\":1795140559847,\"audit_recorded\":true,\"automatic_retry\":false,\"cancelled\":false,\"exit_code\":0,\"job_id\":\"1a1f6b645e3-ffbe-1534\",\"launch_nonce\":\"d2a0e9d74b9b874115b317f2f0e94248\",\"log_bytes\":{\"stderr\":{\"seen\":0,\"stored\":0},\"stdout\":{\"seen\":8632,\"stored\":8632}},\"log_errors\":{\"stderr\":null,\"stdout\":null},\"log_synced\":{\"stderr\":true,\"stdout\":true},\"log_truncated\":{\"stderr\":false,\"stdout\":false},\"output_complete\":true,\"output_durable\":true,\"state\":\"succeeded\",\"terminal_publication_confirmed\":true,\"terminal_publication_protocol\":1,\"timed_out\":false}},\"preflight_v1_preserved_record\":{\"path\":\"/home/qian-qi/hepta-rust-protection-20261120-0cee/history-preflight-unknown.json\",\"sha256\":\"cbaa201c48d376a7f0a4682a5ddbb60d88dd9331420058b84d24307c9d27cc1b\",\"recovered_job_id\":\"1a1f6a7093b-ffbe-1523\",\"recovered_exit_code\":1,\"reason\":\"Installed Git help uses --[no-]filter, so original parser rejected it before fetch; corrected preflight succeeded.\"}}")
VERIFY_SOURCE = "import base64\nimport gzip\nimport hashlib\nimport json\nimport pathlib\nimport sys\n\nROOT = pathlib.Path(__file__).resolve().parent\nmanifest = json.loads((ROOT / \"export-manifest.json\").read_bytes())\n\ndef require(ok, message):\n    if not ok:\n        raise RuntimeError(message)\n\ndef sha(raw):\n    return hashlib.sha256(raw).hexdigest()\n\ndef blob(raw):\n    return hashlib.sha1(b\"blob \" + str(len(raw)).encode() + b\"\\0\" + raw).hexdigest()\n\ndef serialized(value):\n    return (json.dumps(value, indent=2, sort_keys=True) + \"\\n\").encode()\n\nfor entry in manifest[\"exported_files\"]:\n    path = ROOT / entry[\"path\"]\n    require(not path.is_symlink() and path.is_file(), \"Missing regular export file: \" + entry[\"path\"])\n    raw = path.read_bytes()\n    require(len(raw) == entry[\"bytes\"], \"Export size mismatch: \" + entry[\"path\"])\n    require(sha(raw) == entry[\"sha256\"], \"Export SHA256 mismatch: \" + entry[\"path\"])\n    require(blob(raw) == entry[\"git_blob_sha1\"], \"Export Git blob mismatch: \" + entry[\"path\"])\n\nreconstructed = {}\nfor artifact in manifest[\"artifacts\"]:\n    chunks = []\n    offset = 0\n    line_offset = 0\n    for part in artifact[\"parts\"]:\n        compressed = (ROOT / part[\"path\"]).read_bytes()\n        require(len(compressed) <= manifest[\"gzip\"][\"maximum_part_bytes\"], \"Oversized gzip part\")\n        require(compressed[:3] == b\"\\x1f\\x8b\\x08\" and compressed[3] == 0, \"Unexpected gzip header\")\n        require(compressed[4:8] == b\"\\0\\0\\0\\0\", \"Nonzero gzip timestamp\")\n        raw = gzip.decompress(compressed)\n        require(part[\"raw_start_offset\"] == offset, \"Noncontiguous raw offsets\")\n        require(part[\"raw_end_offset\"] == offset + len(raw), \"Incorrect raw end offset\")\n        require(part[\"raw_sha256\"] == sha(raw), \"Incorrect part raw hash\")\n        require(part[\"raw_line_start\"] == line_offset, \"Noncontiguous line offsets\")\n        require(part[\"raw_line_count\"] == len(raw.splitlines()), \"Incorrect raw line count\")\n        offset += len(raw)\n        line_offset += len(raw.splitlines())\n        chunks.append(raw)\n    whole = b\"\".join(chunks)\n    require(len(whole) == artifact[\"raw_bytes\"], \"Reconstructed artifact size mismatch\")\n    require(sha(whole) == artifact[\"raw_sha256\"], \"Reconstructed artifact SHA256 mismatch\")\n    require(blob(whole) == artifact[\"raw_git_blob_sha1\"], \"Reconstructed artifact Git blob mismatch\")\n    reconstructed[artifact[\"id\"]] = whole\n\nrefs = json.loads(reconstructed[\"captured-refs\"])\nnames = sorted(refs)\nmemberships = json.loads(reconstructed[\"coverage-membership\"])\nrequire(memberships[\"captured_refs_sha256\"] == sha(reconstructed[\"captured-refs\"]), \"Wrong coverage name index\")\nfor item in memberships[\"maps\"]:\n    indices = item[\"name_indices\"]\n    require(indices == sorted(set(indices)), \"Duplicate or unordered membership indices\")\n    require(all(type(i) is int and 0 <= i < len(names) for i in indices), \"Invalid membership index\")\n    value = {names[i]: refs[names[i]] for i in indices}\n    raw = serialized(value)\n    require(len(value) == item[\"name_count\"], \"Coverage membership count mismatch\")\n    require(len(raw) == item[\"original_bytes\"], \"Coverage original byte-size mismatch\")\n    require(sha(raw) == item[\"original_sha256\"], \"Coverage original SHA256 mismatch\")\n    require(blob(raw) == item[\"original_git_blob_sha1\"], \"Coverage original Git blob mismatch\")\n\nrequire(len(refs) == manifest[\"snapshot\"][\"captured_ref_count\"], \"Ref count mismatch\")\nprotected = json.loads(reconstructed[\"protected-classification\"])\nrequire(len(protected) == manifest[\"snapshot\"][\"protected_name_count\"], \"Protected classification count mismatch\")\nrequire(len(reconstructed[\"complete-parent-graph\"].splitlines()) == manifest[\"snapshot\"][\"parent_graph_nodes\"], \"Graph line count mismatch\")\nprint(json.dumps({\n    \"outcome\": \"PASS_OFFLINE_BYTE_ROUNDTRIP\",\n    \"exported_files_verified\": len(manifest[\"exported_files\"]),\n    \"exact_raw_artifacts\": len(reconstructed),\n    \"exact_original_coverage_maps_reconstructed\": len(memberships[\"maps\"]),\n    \"coverage_source_paths_including_aliases\": sum(len(x[\"source_paths\"]) for x in memberships[\"maps\"]),\n    \"classification_or_git_executed\": False,\n    \"network_used\": False\n}, indent=2, sort_keys=True))\n"
EXPORTER_SOURCE = globals().get("EXPORTER_SOURCE") or pathlib.Path(__file__).read_text()
sys.dont_write_bytecode = True
os.umask(0o077)
files = []
artifacts = []
inputs = {}

def require(ok, message):
    if not ok:
        raise RuntimeError(message)

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()

def serialized(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()

def raw_metadata(raw):
    return {"bytes": len(raw), "sha256": sha(raw), "git_blob_sha1": blob(raw)}

def read_original(path, expected=None):
    path = pathlib.Path(path)
    require(path.is_absolute() and path.resolve() == path, "Source path resolution changed")
    before = path.stat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, "Source must be a single-link regular file")
    raw = path.read_bytes()
    after = path.stat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
            "Source file changed while read")
    if expected:
        require(sha(raw) == expected, "Source SHA256 mismatch: " + str(path))
    if str(path) in inputs:
        require(inputs[str(path)]["sha256"] == sha(raw), "Source changed between reads")
    inputs[str(path)] = {"path": str(path), **raw_metadata(raw)}
    return raw

def write(relative, raw, role):
    rel = pathlib.PurePosixPath(relative)
    require(not rel.is_absolute() and ".." not in rel.parts, "Unsafe export path")
    destination = EXPORT.joinpath(*rel.parts)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    entry = {"path": relative, **raw_metadata(raw), "role": role}
    files.append(entry)
    return entry

def deterministic_gzip(raw):
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", fileobj=buffer, mode="wb", compresslevel=9, mtime=0) as stream:
        stream.write(raw)
    return buffer.getvalue()

def bounded_chunks(raw):
    lines = raw.splitlines(keepends=True)
    require(b"".join(lines) == raw, "Raw line split changed bytes")
    result = []
    current, size = [], 0
    for line in lines:
        if current and size + len(line) > INITIAL_RAW_PART_BYTES:
            result.append(b"".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line)
    if current:
        result.append(b"".join(current))
    if not result:
        result = [b""]
    def fit(piece):
        compressed = deterministic_gzip(piece)
        if len(compressed) <= MAX_GZIP_BYTES:
            return [(piece, compressed)]
        part_lines = piece.splitlines(keepends=True)
        require(len(part_lines) > 1, "One line exceeds maximum compressed-part size")
        midpoint = len(part_lines) // 2
        return fit(b"".join(part_lines[:midpoint])) + fit(b"".join(part_lines[midpoint:]))
    return [pair for chunk in result for pair in fit(chunk)]

def compress_artifact(identifier, raw, source_paths, role):
    entries = []
    offset, line_offset = 0, 0
    roundtrip = []
    for index, (piece, compressed) in enumerate(bounded_chunks(raw), 1):
        require(compressed == deterministic_gzip(piece), "Gzip output is not deterministic")
        require(gzip.decompress(compressed) == piece, "Independent gzip part did not roundtrip")
        require(compressed[:3] == b"\x1f\x8b\x08" and compressed[3] == 0, "Unexpected gzip metadata")
        require(compressed[4:8] == b"\0\0\0\0", "Gzip timestamp is not zero")
        relative = "parts/" + identifier + ".part-" + str(index).zfill(3) + ".gz"
        meta = write(relative, compressed, role)
        line_count = len(piece.splitlines())
        entries.append({
            **meta,
            "raw_start_offset": offset,
            "raw_end_offset": offset + len(piece),
            "raw_line_start": line_offset,
            "raw_line_count": line_count,
            "raw_bytes": len(piece),
            "raw_sha256": sha(piece),
            "independently_decompressible": True,
        })
        offset += len(piece)
        line_offset += line_count
        roundtrip.append(gzip.decompress((EXPORT / relative).read_bytes()))
    joined = b"".join(roundtrip)
    require(joined == raw, "Joined independent parts differ from the original artifact")
    artifact = {
        "id": identifier,
        "source_paths": source_paths,
        "raw_bytes": len(raw),
        "raw_sha256": sha(raw),
        "raw_git_blob_sha1": blob(raw),
        "raw_line_count": len(raw.splitlines()),
        "parts": entries,
        "roundtrip_proof": {
            "independent_parts_all_decompressed": True,
            "raw_offsets_contiguous": True,
            "joined_bytes_equal_original": True,
            "joined_bytes": len(joined),
            "joined_sha256": sha(joined),
            "gzip_recompression_byte_equal": True,
        },
    }
    artifacts.append(artifact)
    return artifact

require(AUDIT_ROOT.resolve() == AUDIT_ROOT and EVIDENCE.resolve() == EVIDENCE, "Audit root identity changed")
require(EXPORT.parent == EVIDENCE and EXPORT.name not in ("", ".", ".."), "Export must be a new child of the evidence directory")
require(not os.path.lexists(EXPORT), "Refuse to reuse an existing export namespace")
result_raw = read_original(EVIDENCE / "full-history-result.json", RESULT_EXPECTED)
result = json.loads(result_raw)
require(result["completed"] and result["outcome"] == "PASS_CAPTURED_FULL_DAG", "Original audit is not complete")
require(result["fresh_matches_captured"], "Original captured/fresh refs differ")
EXPORT.mkdir(mode=0o700)

write("full-history-result.json", result_raw, "exact native audit result")
write("native/full-history-audit.py", read_original(EVIDENCE / "full-history-audit.py", result["script_sha256"]), "exact executed native audit source; archived, not executed by export")
write("native/full-history-process-request.json", read_original(EVIDENCE / "full-history-process-request.json", "9cff4a397bd233d63bde46c5b32fe0ec0d85cf73a4dd724cfe1b2203b5aa4b90"), "exact recorded native process request")
write("native/preflight.json", read_original(EVIDENCE / "preflight.json", "9b53254d77a3d1f0662e7fedf75056e6fd6d685a743725b84605d51e99deebbe"), "exact successful native preflight result")
write("native/git-fetch-help.txt", read_original(EVIDENCE / "git-fetch-help.txt", "530d9283cffb6001ea68e02ddbd45c26bd44b31308085973b46e450a3ea583a8"), "exact Git filtering capability help")
write("native/preflight-v2-process-request.json", serialized(PROVENANCE["preflight_v2_request"]), "exact submitted successful preflight request values")
write("native/runtime-provenance.json", serialized({key: value for key, value in PROVENANCE.items() if key != "preflight_v2_request"}), "native launch and terminal receipt plus preserved prior failure identity")
write("native/hepta_branch_consolidation.py", read_original(AUDIT_ROOT / "candidate/tools/branch-consolidation/hepta_branch_consolidation.py", SOURCE_EXPECTED), "exact reviewed protection implementation; archived only")

refs_raw = read_original(result["captured_refs_artifact"]["path"], result["captured_refs_artifact"]["sha256"])
refs = json.loads(refs_raw)
ref_alias_paths = [result["captured_refs_artifact"]["path"]]
for name in ("refs-before-fetch.json", "fresh-remote-refs.json"):
    path = EVIDENCE / name
    require(read_original(path) == refs_raw, "Reference alias is not byte-identical")
    ref_alias_paths.append(str(path))
compress_artifact("captured-refs", refs_raw, ref_alias_paths, "exact captured refs; identical before/fresh snapshots are aliases")
graph_meta = result["commit_parent_graph_artifact"]
compress_artifact("complete-parent-graph", read_original(graph_meta["path"], graph_meta["sha256"]), [graph_meta["path"]], "exact complete parent graph, split only on line boundaries")
protected_meta = result["protected_classification_artifact"]
compress_artifact("protected-classification", read_original(protected_meta["path"], protected_meta["sha256"]), [protected_meta["path"]], "exact native classification output")
original_manifest = AUDIT_ROOT / "candidate/tools/branch-consolidation/protected-branches.json"
compress_artifact("input-protection-manifest", read_original(original_manifest, MANIFEST_EXPECTED), [str(original_manifest)], "exact reviewed protection input")
observed_meta = result["observed_protection_artifact"]
compress_artifact("observed-protection", read_original(observed_meta["path"], observed_meta["sha256"]), [observed_meta["path"]], "exact frozen protection output")

name_indices = {name: index for index, name in enumerate(sorted(refs))}
coverage_maps = {}
coverage = {}
aliases = []
for label, entry in result["coverage"].items():
    target = {key: value for key, value in entry.items() if not key.endswith("_artifact")}
    target["maps"] = {}
    for kind in ("covered", "pending", "frontier"):
        original = entry[kind + "_artifact"]
        raw = read_original(original["path"], original["sha256"])
        require(len(raw) == original["bytes"], "Coverage artifact source size mismatch")
        value = json.loads(raw)
        require(all(name in refs and refs[name] == tip for name, tip in value.items()), "Coverage map contains a noncaptured ref")
        indices = sorted(name_indices[name] for name in value)
        selected = set(indices)
        rebuilt = serialized({name: refs[name] for name in sorted(refs) if name_indices[name] in selected})
        require(rebuilt == raw, "Coverage membership reconstruction is not byte-exact")
        identifier = original["sha256"]
        if identifier not in coverage_maps:
            coverage_maps[identifier] = {
                "id": identifier,
                "source_paths": [],
                "original_bytes": len(raw),
                "original_sha256": sha(raw),
                "original_git_blob_sha1": blob(raw),
                "name_count": len(value),
                "name_indices": indices,
                "roundtrip_bytes_equal_original": True,
            }
        else:
            require(coverage_maps[identifier]["name_indices"] == indices, "Coverage hash collision")
        coverage_maps[identifier]["source_paths"].append(original["path"])
        target["maps"][kind] = identifier
    coverage[label] = target
    if label == "live_integration":
        require({key: value for key, value in target.items()} == coverage["integration_0cee"], "Live integration alias differs from fixed integration")
        aliases.append({"target": "live_integration", "canonical_target": "integration_0cee", "all_counts_and_map_hashes_equal": True})

membership = {
    "schema": "hepta.coverage-name-membership.v1",
    "captured_refs_sha256": sha(refs_raw),
    "name_order": "Python sorted(captured_refs.keys()); Unicode code point order",
    "original_json_encoding": "UTF-8 json.dumps(value, indent=2, sort_keys=True) plus newline",
    "maps": [coverage_maps[key] for key in sorted(coverage_maps)],
}
membership_raw = (json.dumps(membership, sort_keys=True, separators=(",", ":")) + "\n").encode()
compress_artifact("coverage-membership", membership_raw, [], "lossless compact representation of original coverage maps; no classification rerun")
coverage_summary = {
    "schema": "hepta.full-commit-coverage-summary.v1",
    "source_result_sha256": sha(result_raw),
    "captured_refs_sha256": sha(refs_raw),
    "finished_at_utc": result["finished_at_utc"],
    "targets": coverage,
    "target_aliases": aliases,
    "unique_coverage_maps": len(coverage_maps),
    "original_source_map_count": sum(len(entry["source_paths"]) for entry in coverage_maps.values()),
    "all_original_maps_reconstructed_byte_exactly": True,
    "classification_rerun": False,
}
write("coverage-summary.json", serialized(coverage_summary), "compact coverage, pending and frontier summary with original-map hashes")
write("verify_export.py", VERIFY_SOURCE.encode(), "offline file, independent gzip and original-map roundtrip verifier")
write("prepare-export.py", EXPORTER_SOURCE.encode(), "exact deterministic export generator, including provenance constants")

readme = """# Full commit ancestry audit: reproducible evidence

This export preserves the 2026-11-20 native audit of TrillionniumFoundation/hepta-private-ci.
The original result is full-history-result.json. It captured 7,654 refs and a complete
78,730-commit parent graph, classified 483 protected names with 504 retained pins,
and compared the captured refs with the remote again after classification.

Run the standard-library-only offline integrity check from this directory:

    python3 verify_export.py

The check performs no Git command, network call, classification, merge, or deletion.
It verifies all exported-file SHA256 and Git blob SHA1 values, independently decompresses
every gzip part, checks contiguous byte and line offsets, and reconstructs exact original
coverage maps. A passing result confirms byte preservation of the recorded evidence;
it does not constitute a fresh remote audit, a build result, or permission to retire refs.

## Exact raw inputs

export-manifest.json identifies each raw artifact and its ordered gzip parts.
Each part is a standalone gzip stream, at most 262,144 compressed bytes, with
compression level 9, timestamp zero, no original filename, and line-boundary splits.
Concatenate each artifact's independently decompressed parts in manifest order to recover
the exact original bytes. The original whole-file byte size and SHA256 are in the manifest.

The captured, prefetch and fresh-ref JSON files were byte-identical and share one payload.
The live-integration target was identical to integration_0cee and is an explicit alias.

## Coverage maps without repeated name/SHA strings

coverage-summary.json records counts and original map hashes for covered, pending and
frontier names. The coverage-membership artifact stores each distinct map as indices into
sorted(captured-refs.keys()). Rebuild a dictionary using those names and captured SHAs,
then serialize with json.dumps(value, indent=2, sort_keys=True) plus one newline.
The verifier proves this reproduces all 12 original map files byte-for-byte through
8 unique map payloads. Repeated frontier and live-integration maps are explicit aliases.

## Native provenance

native/full-history-audit.py is the exact script executed on ROG.
native/full-history-process-request.json records its exact runtime request.
native/hepta_branch_consolidation.py and the input-protection-manifest artifact preserve
the exact reviewed implementation and policy used by that job. They are archived inputs;
the export and offline verifier do not execute them. The native script records absolute
paths and is not intended to be executed unchanged in this publication directory.

The successful preflight result, Git help, submitted preflight request, native launch
receipt and terminal status are retained under native/. The previous preflight's false
negative and preserved unknown-outcome record are identified in runtime-provenance.json.

prepare-export.py records the packaging algorithm. It only reads existing evidence,
requires a new output namespace, and writes export files. It never invokes Git or reruns
classification. Gzip generation is byte-deterministic with the recorded Python/zlib
versions and normalized headers. No native Git pack files are included.
"""
write("README.md", readme.encode(), "reconstruction and scope instructions")

for path, entry in list(inputs.items()):
    require(sha(pathlib.Path(path).read_bytes()) == entry["sha256"], "Original evidence changed during packaging")

manifest = {
    "schema": "hepta.full-commit-ancestry-export.v1",
    "repository": result["repository"],
    "source_audit_result": {"path": "full-history-result.json", **raw_metadata(result_raw)},
    "snapshot": {
        "finished_at_utc": result["finished_at_utc"],
        "captured_ref_count": result["captured_ref_count"],
        "parent_graph_nodes": result["parent_graph_nodes"],
        "missing_parent_count": result["missing_parent_count"],
        "protected_name_count": result["protected_name_count"],
        "protected_pin_count": result["protected_pin_count_input"],
        "ordinary_name_count": result["ordinary_name_count"],
        "ordinary_distinct_head_count": result["ordinary_distinct_head_count"],
        "fresh_matches_captured": result["fresh_matches_captured"],
        "no_protected_intersection_all_targets": result["no_protected_intersection_all_targets"],
    },
    "gzip": {
        "compression_level": 9,
        "mtime": 0,
        "filename": "",
        "maximum_part_bytes": MAX_GZIP_BYTES,
        "initial_raw_part_bytes": INITIAL_RAW_PART_BYTES,
        "split_boundaries": "complete lines; raw byte offsets are zero-based and end-exclusive",
        "all_streams_independently_decompressible": True,
        "python_version": sys.version.split()[0],
        "zlib_runtime_version": zlib.ZLIB_RUNTIME_VERSION,
    },
    "artifacts": artifacts,
    "coverage": {
        "summary": "coverage-summary.json",
        "membership_artifact": "coverage-membership",
        "unique_maps": len(coverage_maps),
        "original_source_maps": sum(len(entry["source_paths"]) for entry in coverage_maps.values()),
        "target_aliases": aliases,
        "roundtrip_all_original_maps_byte_equal": True,
    },
    "original_inputs_verified_unchanged": [inputs[key] for key in sorted(inputs)],
    "exported_files": sorted(files, key=lambda entry: entry["path"]),
    "exported_files_excluding_manifest_bytes": sum(entry["bytes"] for entry in files),
    "publication_notes": [
        "All file and gzip part hashes include SHA256 and Git blob SHA1.",
        "The manifest is intentionally not self-hashed; its hash is returned by the native export job.",
        "The exact audit script is native/full-history-audit.py.",
        "No native Git pack, Git reference mutation or classification rerun is part of this export.",
    ],
}
manifest_entry = write("export-manifest.json", serialized(manifest), "export manifest; external self-hash is in native process output")
verified = subprocess.run([sys.executable, str(EXPORT / "verify_export.py")], capture_output=True, text=True, timeout=60)
require(verified.returncode == 0, "Offline verifier failed:\n" + verified.stderr)
verification = json.loads(verified.stdout)
require(verification["outcome"] == "PASS_OFFLINE_BYTE_ROUNDTRIP", "Unexpected offline verifier result")
graph_export = next(entry for entry in artifacts if entry["id"] == "complete-parent-graph")
summary = {
    "outcome": "PASS_DETERMINISTIC_EXPORT",
    "export_directory": str(EXPORT),
    "manifest": manifest_entry,
    "exported_file_count_including_manifest": len(files),
    "exported_total_bytes": sum(entry["bytes"] for entry in files),
    "gzip_part_count": sum(len(entry["parts"]) for entry in artifacts),
    "gzip_total_bytes": sum(part["bytes"] for entry in artifacts for part in entry["parts"]),
    "graph_part_count": len(graph_export["parts"]),
    "graph_gzip_bytes": sum(part["bytes"] for part in graph_export["parts"]),
    "largest_gzip_part_bytes": max(part["bytes"] for entry in artifacts for part in entry["parts"]),
    "original_evidence_unchanged": True,
    "classification_rerun": False,
    "git_or_network_used": False,
    "native_audit_script": str(EXPORT / "native/full-history-audit.py"),
    "original_native_audit_script": str(EVIDENCE / "full-history-audit.py"),
    "offline_verification": verification,
}
print(json.dumps(summary, indent=2, sort_keys=True), flush=True)
