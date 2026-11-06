#!/usr/bin/env python3
"""Read only closed r15 inputs; write independent audit outputs beside this script.

Uses Python standard library only. Does not invoke Git, Cargo, Rust, or a test runner.
The archived Git modes, not tar or extracted filesystem permissions, build the tree.
"""
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
import gzip
import hashlib
import io
import json
import re
import tarfile

OUT = Path(__file__).resolve().parent
ROOT = OUT.parent
CHECKPOINT = ROOT / "native-validation-results/checkpoint-r15"
FORMAL_ROOT = ROOT / "hepta-cell/qualification/cell-unification-20261106/native-evidence"
FORMAL = FORMAL_ROOT / "r15-core-mcp-checkpoint"
BASE_COMMIT = "bef6fa7645df9df12b69fda499e97eed25de6c75"
BASE_TREE = "ce997fd958b8073d99b1e5bc302b7a0188fb4c3b"
TARGET_COMMIT = "638997499470f0b7dd33ad18226feacf0198ef3d"
TARGET_TREE = "1646e1656cf6365e74accae19a1225fd2ce6d964"
ARCHIVE_SHA = "4f1943f25c0e2ff0f549fe0463d9b5c9f29c24019d896ddf2418b2e8e431e866"
BASE_INPUT_SHA = "56f7a3076b782105db36509abe860d9872c27bfa41685fb80b31e68b1a5abda1"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git_hash(kind, data):
    return hashlib.sha1(kind.encode() + b" " + str(len(data)).encode() + b"\0" + data).hexdigest()


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def serialized(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def write_json(name, value):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(serialized(value))


def file_pin(path):
    data = path.read_bytes()
    return {"path": str(path.relative_to(ROOT)), "bytes": len(data), "sha256": sha(data)}


def tree_hash(entries):
    data = bytearray()
    for name, entry in sorted(entries.items(), key=lambda item: item[0].encode() + (b"/" if item[1]["type"] == "tree" else b"")):
        mode = "40000" if entry["type"] == "tree" else entry["mode"].lstrip("0")
        data.extend(mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(entry["sha"]))
    return git_hash("tree", bytes(data))


archive_path = FORMAL / "checkpoint-r15-closed.tar.gz"
archive_raw = archive_path.read_bytes()
require(sha(archive_raw) == ARCHIVE_SHA, "closed archive SHA mismatch")
with tarfile.open(fileobj=io.BytesIO(archive_raw), mode="r:gz") as archive:
    members = archive.getmembers()
    require(len(members) == 190, "archive member count")
    require(len({m.name for m in members}) == len(members), "duplicate tar member")
    for member in members:
        path = PurePosixPath(member.name)
        require(member.isfile() and not path.is_absolute() and ".." not in path.parts, "nonregular or unsafe member: " + member.name)
    blobs = {m.name: archive.extractfile(m).read() for m in members}
    tar_modes = {m.name: format(m.mode, "o") for m in members}

index_raw = blobs["INDEX.json"]
require(index_raw == (CHECKPOINT / "INDEX.json").read_bytes() == (FORMAL / "INDEX.json").read_bytes(), "INDEX bytes differ")
index = json.loads(index_raw)
require(index["source_tree"] == TARGET_TREE and index["source_commit"] == TARGET_COMMIT and index["source_base_commit"] == BASE_COMMIT, "INDEX source identity")
listed = {e["path"]: e for e in index["files"]}
require(len(listed) == 189 and set(listed) == set(blobs) - {"INDEX.json"}, "INDEX membership")
member_readback = []
for name, raw in blobs.items():
    require(raw == (CHECKPOINT / name).read_bytes(), "extracted archive bytes differ: " + name)
    if name != "INDEX.json":
        entry = listed[name]
        require((len(raw), sha(raw), tar_modes[name]) == (entry["bytes"], entry["sha256"], entry["mode"]), "member size/hash/tar mode: " + name)
    member_readback.append({"path": name, "bytes": len(raw), "sha256": sha(raw), "archive_mode": tar_modes[name], "extracted_bytes_equal": True})

source_raw = blobs["evidence/native-candidate-r15-source.json"]
source = json.loads(source_raw)
require(source["source_tree"] == TARGET_TREE and source["source_commit"] == TARGET_COMMIT and source["applied_stage"] == 44, "native source identity")
source_entries = {e["path"]: e for e in source["changed_files"]}
require(len(source_entries) == 177, "changed source count")
require({"source/" + p for p in source_entries} == {p for p in blobs if p.startswith("source/")}, "source inventory membership")
require({str(p.relative_to(CHECKPOINT / "source")) for p in (CHECKPOINT / "source").rglob("*") if p.is_file()} == set(source_entries), "extracted source has extra or missing files")
computed_sources = []
for name, entry in source_entries.items():
    data = blobs["source/" + name]
    blob = git_hash("blob", data)
    require((len(data), sha(data), blob) == (entry["bytes"], entry["sha256"], entry["git_blob"]), "source raw/hash/blob mismatch: " + name)
    require(blob == listed["source/" + name]["git_blob"], "archive Git blob differs: " + name)
    require(entry["mode"] in ("100644", "100755"), "unsupported Git source mode")
    computed_sources.append({"path": name, "mode": entry["mode"], "type": "blob", "sha": blob, "bytes": len(data), "sha256": sha(data)})

base_path = FORMAL_ROOT / "r14-core-checkpoint/INDEPENDENT-SOURCE-TREE-INPUT.json"
base_raw = base_path.read_bytes()
require(sha(base_raw) == BASE_INPUT_SHA, "retained original-base input SHA")
base_input = json.loads(base_raw)
require(base_input["source_base_commit"] == BASE_COMMIT and base_input["base_tree"] == BASE_TREE and not base_input["base_listing_truncated"], "original base identity")
base = {e["path"]: dict(e) for e in base_input["base_entries"]}
require(len(base) == len(base_input["base_entries"]), "duplicate base path")
fetch_manifest = json.loads((OUT / "input/base-tree-fetch-manifest.json").read_bytes())
directory_paths = {"codex-mcp": "codex-rs/codex-mcp", "codex-mcp-src": "codex-rs/codex-mcp/src", "session": "codex-rs/core/src/session"}
base_additions = []
for fetch in fetch_manifest["files"]:
    data = (OUT / fetch["path"]).read_bytes()
    require((len(data), sha(data)) == (fetch["bytes"], fetch["sha256"]), "fetch retained bytes")
    tree = json.loads(data)
    directory = directory_paths[fetch["name"]]
    require(directory in base and base[directory]["sha"] == fetch["sha"] == tree["sha"], "base direct tree pin: " + directory)
    require(tree["truncated"] is False, "truncated direct tree")
    children = {}
    for child in tree["tree"]:
        require("/" not in child["path"] and child["path"] not in (".", "..", ""), "nondirect child")
        require(child["path"] not in children, "duplicate direct child")
        children[child["path"]] = {k: child[k] for k in ("mode", "type", "sha")}
        full_path = directory + "/" + child["path"]
        new_entry = {"path": full_path, **children[child["path"]]}
        if full_path in base:
            require(base[full_path] == new_entry, "conflicting base addition")
        base[full_path] = new_entry
    computed = tree_hash(children)
    require(computed == tree["sha"], "GitData direct tree content hash")
    base_additions.append({"path": directory, "direct_children": len(children), "requested_sha": fetch["sha"], "computed_sha": computed, "response_file": fetch["path"], "response_sha256": fetch["sha256"], "url": fetch["url"]})

children = defaultdict(dict)
for path, entry in base.items():
    parent, _, name = path.rpartition("/")
    children[parent][name] = {k: entry[k] for k in ("mode", "type", "sha")}
base_verified = [{"path": "", "sha": tree_hash(children[""])}]
require(base_verified[0]["sha"] == BASE_TREE, "original top-level tree failed independent hash")
for pin in base_input["existing_directory_pins"]:
    computed = tree_hash(children[pin["path"]])
    require(computed == pin["sha"], "original base child tree hash: " + pin["path"])
    base_verified.append({"path": pin["path"], "sha": computed})

ancestors = {""}
for entry in computed_sources:
    parent, _, name = entry["path"].rpartition("/")
    children[parent][name] = {k: entry[k] for k in ("mode", "type", "sha")}
    while parent:
        ancestors.add(parent)
        parent = parent.rpartition("/")[0]
require(len(ancestors) == 61, "r15 dynamic ancestor count")
rebuild = []
for directory in sorted(ancestors, key=lambda p: (p.count("/") + bool(p), p), reverse=True):
    computed = tree_hash(children[directory])
    rebuild.append({"path": directory, "computed_tree": computed, "direct_children": len(children[directory])})
    if directory:
        parent, _, name = directory.rpartition("/")
        children[parent][name] = {"mode": "040000", "type": "tree", "sha": computed}
computed_tree = tree_hash(children[""])
require(computed_tree == TARGET_TREE, "independent r15 tree differs")

formal_readback = []
for name in sorted(p for p in blobs if p.startswith("evidence/")):
    filename = name.split("/", 1)[1]
    path = FORMAL / (filename + ".gz" if filename.endswith(".log") else filename)
    stored = path.read_bytes()
    raw = gzip.decompress(stored) if filename.endswith(".log") else stored
    require(raw == blobs[name], "formal evidence bytes differ: " + filename)
    formal_readback.append({**file_pin(path), "original_bytes": len(raw), "original_sha256": sha(raw), "gzip_decompressed_equal": filename.endswith(".log"), "archive_and_extracted_equal": True})
require(len(formal_readback) == 11, "formal original evidence count")

environment = json.loads(blobs["evidence/native-core-mcp-r15-environment.json"])
require(environment["source_tree"] == TARGET_TREE, "environment tree mismatch")
gate_readback = {}
for phase, expected_exit in (("strict", 0), ("tests", 100)):
    stem = "evidence/native-core-mcp-r15-" + phase
    receipt = json.loads(blobs[stem + "-receipt.json"])
    log = blobs[stem + ".log"]
    resources = blobs[stem + "-resources.txt"]
    expected_command = ["just", "clippy", "--locked", "-p", "codex-core", "-p", "codex-mcp", "--", "-D", "warnings"] if phase == "strict" else ["just", "test", "--locked", "-p", "codex-core", "-p", "codex-mcp", "--retries", "0"]
    require(receipt["command"] == expected_command, "original command mismatch")
    require(receipt["source_tree"] == TARGET_TREE and receipt["source_commit"] == TARGET_COMMIT, "receipt source identity")
    require(receipt["exit_code"] == expected_exit, "receipt exit status")
    require(sha(log) == receipt["log_sha256"] and sha(resources) == receipt["resources_sha256"], "receipt raw log/resources hash")
    require(receipt["source_manifest"] == "native-candidate-r15-source.json" and receipt["environment_manifest"] == "native-core-mcp-r15-environment.json", "receipt referenced evidence")
    require(abs(receipt["end_unix"] - receipt["start_unix"] - receipt["elapsed_seconds"]) < 1e-9, "receipt elapsed arithmetic")
    exit_matches = re.findall(rb"^[ \t]*Exit status: (\d+)\s*$", resources, re.M)
    require(exit_matches == [str(expected_exit).encode()], "resources terminal exit")
    require(('Command being timed: "' + " ".join(expected_command) + '"').encode() in resources, "resources command")
    gate_readback[phase] = {"receipt": phase + "-receipt.json", "command": expected_command, "exit_code": expected_exit, "elapsed_seconds": receipt["elapsed_seconds"], "log_bytes": len(log), "log_sha256": sha(log), "resources_bytes": len(resources), "resources_sha256": sha(resources), "receipt_log_resources_match": True}
strict_receipt = json.loads(blobs["evidence/native-core-mcp-r15-strict-receipt.json"])
test_receipt = json.loads(blobs["evidence/native-core-mcp-r15-tests-receipt.json"])
require(strict_receipt["end_unix"] <= test_receipt["start_unix"], "gate sequence")

raw_log = blobs["evidence/native-core-mcp-r15-tests.log"]
summary_matches = list(re.finditer(rb"^[ \t]*Summary \[([^\]\r\n]+)\] ([^\r\n]+)", raw_log, re.M))
require(len(summary_matches) == 1, "unique nextest Summary")
summary = summary_matches[0]
status_re = rb"^[ \t]*(PASS|FAIL|TIMEOUT|SKIP)[ \t]+\[([^\]\r\n]+)\][ \t]+(\S+)[ \t]+([^\r\n]+)"
matches = list(re.finditer(status_re, raw_log[:summary.start()], re.M))
rows = [{"status": m[1].decode(), "elapsed": m[2].decode().strip(), "binary": m[3].decode(), "name": m[4].decode(), "log_byte_offset": m.start(), "log_line": raw_log.count(b"\n", 0, m.start()) + 1} for m in matches]
row_map = {(r["binary"], r["name"]): r for r in rows}
require(len(rows) == len(row_map) == 4026, "unique executed test IDs")
counts = Counter(r["status"] for r in rows)
require(counts == {"PASS": 4023, "FAIL": 3}, "independent status counts")
per_package = defaultdict(Counter)
per_binary = defaultdict(Counter)
for row in rows:
    per_package[row["binary"].split("::")[0]][row["status"]] += 1
    per_binary[row["binary"]][row["status"]] += 1
require(dict(per_package) == {"codex-core": {"PASS": 3827, "FAIL": 3}, "codex-mcp": {"PASS": 196}}, "package results")
require(summary[2] == b"4026 tests run: 4023 passed, 3 failed, 9 skipped", "summary count agreement")
start_matches = list(re.finditer(rb"^[ \t]*Starting (\d+) tests across (\d+) binaries \((\d+) tests skipped\)", raw_log, re.M))
require(len(start_matches) == 1 and start_matches[0].groups() == (b"4026", b"5", b"9"), "runner starting count agreement")
footer = list(re.finditer(status_re, raw_log[summary.end():], re.M))
require(len(footer) == 3, "footer repeat count")
require({(m[3].decode(), m[4].decode()) for m in footer} == {key for key, row in row_map.items() if row["status"] == "FAIL"}, "footer repeats actual failures only")
native_review = json.loads(blobs["evidence/native-core-mcp-r15-result-review.json"])
require(native_review["source_tree"] == TARGET_TREE and native_review["source_commit"] == TARGET_COMMIT and native_review["log_sha256"] == sha(raw_log) and native_review["log_bytes"] == len(raw_log), "native review binding")
require(native_review["counts_unique"] == dict(counts) and native_review["per_package"] == dict(per_package), "native review counts")
native_blocks = {(b["binary"], b["name"]): b for b in native_review["blocks"]}
failure_blocks = []
for i, match in enumerate(matches):
    if match[1] != b"FAIL":
        continue
    start = match.start()
    bound = matches[i + 1].start() if i + 1 < len(matches) else summary.start()
    # Exclude the blank line separating this finished failure block from the next row.
    excerpt = raw_log[start:bound].rstrip(b"\r\n") + b"\n"
    end = start + len(excerpt)
    row = row_map[(match[3].decode(), match[4].decode())]
    claimed = native_blocks[(row["binary"], row["name"])]
    require(claimed["log_byte_range"] == [start, end] and claimed["excerpt"].encode() == excerpt, "failure exact range/excerpt")
    failure_blocks.append({**row, "log_byte_range_half_open": [start, end], "bytes": len(excerpt), "sha256": sha(excerpt), "excerpt": excerpt.decode(), "native_review_range_and_bytes_equal": True})
require(len(failure_blocks) == len(native_blocks) == 3, "failure block set")

r14_review_path = FORMAL_ROOT / "r14-core-checkpoint/native-core-r14-result-review.json"
r14_review = json.loads(r14_review_path.read_bytes())
require(r14_review["source_tree"] == "d3d2313b838422818bf9448ce5a1b86d89abdf69", "r14 comparison source identity")
old_ids = [(b["binary"], b["name"]) for b in r14_review["blocks"] if b["status"] == "FAIL"]
require(len(old_ids) == len(set(old_ids)) == 24, "original 24 distinct failed IDs")
old_outcomes = [row_map[key] for key in old_ids]
require(Counter(r["status"] for r in old_outcomes) == {"PASS": 22, "FAIL": 2}, "original 24 r15 results")
native_old = {(r["binary"], r["name"]): r for r in native_review["all_original_r14_failed_case_results"]}
require(set(native_old) == set(old_ids), "native old-case set")
for row in old_outcomes:
    require(all(native_old[(row["binary"], row["name"])][k] == row[k] for k in ("status", "elapsed", "binary", "name")), "native old-case result differs")
hook_id = ("codex-mcp", "binding::tests::hook_call_retains_owner_and_rejects_stale_catalog_before_preparation")
hook_row = row_map[hook_id]
require(hook_row["status"] == "PASS", "new hook owner regression")
require(len(native_review["new_hook_owner_regression"]) == 1 and all(native_review["new_hook_owner_regression"][0][k] == hook_row[k] for k in ("status", "elapsed", "binary", "name")), "native hook result differs")

terminal = json.loads(blobs["evidence/native-core-mcp-r15-process-terminal.json"])
require(terminal["job_id"] == "1a1afd6b583-fc05-6c15" and terminal["state"] == "failed" and terminal["exit_code"] == 100, "terminal identity/status")
require(all(terminal[k] is True for k in ("output_complete", "output_durable", "terminal_publication_confirmed")), "terminal closure claims")
require(all(terminal[k] is False for k in ("automatic_retry", "cancelled", "timed_out")), "unexpected native retry/cancel/timeout")
require(not any(terminal["log_truncated"].values()), "native wrapper log truncation")
post = json.loads(blobs["evidence/native-core-mcp-r15-source-post-test-verification.json"])
require(post["source_tree"] == TARGET_TREE and post["changed_files_verified"] == 177 and not post["unstaged_tracked_files"] and not post["untracked_paths"], "post-gate source claims")
require(post["lock_sha256"] == source["lock_sha256"], "lock declared hash agreement")
require("codex-rs/Cargo.lock" not in source_entries, "unexpected lock delta")
require(sha(blobs["source/.github/workflows/hepta-cell-framework-native.yml"]) == source["workflow_sha256"], "actual workflow hash")
require(sha(blobs["input/stage44-r15-input.tar.gz"]) == source["input_archive_sha256"], "stage44 input archive binding")

# Preserve exact original-base input compactly. Its r14 target metadata is ignored.
base_gzip = gzip.compress(base_raw, mtime=0)
(OUT / "input/original-base-direct-map.json.gz").write_bytes(base_gzip)
write_json("ARCHIVE-MEMBER-READBACK.json", {"schema": "hepta.independent-r15-archive-members.v1", "archive_sha256": ARCHIVE_SHA, "members": member_readback})
write_json("TREE-REBUILD.json", {"schema": "hepta.independent-r15-tree-rebuild.v1", "source_base_commit": BASE_COMMIT, "base_tree": BASE_TREE, "base_direct_maps_verified": base_verified, "base_additions": base_additions, "source_entries_computed_from_actual_r15_bytes": computed_sources, "computed_directories": rebuild, "computed_tree": computed_tree})
write_json("FAILURE-BLOCKS.json", {"schema": "hepta.independent-r15-failure-blocks.v1", "log_sha256": sha(raw_log), "offset_unit": "UTF-8 raw bytes, zero-based, half-open", "blocks": failure_blocks})
rows_raw = serialized({"schema": "hepta.independent-r15-test-rows.v1", "source_tree": TARGET_TREE, "raw_log_sha256": sha(raw_log), "rows": rows})
(OUT / "TEST-ROWS.json.gz").write_bytes(gzip.compress(rows_raw, mtime=0))
report = {
    "schema": "hepta.independent-r15-closed-readback.v1",
    "audit_status": "PASS",
    "native_gate_status": "STRICT_PASS_TESTS_FAIL",
    "reviewer": "/root/differentiation_study",
    "scope": "Independent read-only archive/raw-byte/receipt/test-ID/Git-object readback of closed r15; no Rust or native command execution; no r16 input or active log read.",
    "source_base_commit": BASE_COMMIT,
    "source_base_tree": BASE_TREE,
    "source_commit_recorded_in_native_evidence": TARGET_COMMIT,
    "independently_reconstructed_source_tree": computed_tree,
    "source_stage": 44,
    "native_job_id": terminal["job_id"],
    "archive": {**file_pin(archive_path), "members": 190, "all_regular_unique_safe_relative": True, "all_extracted_bytes_equal": True, "all_189_indexed_size_sha_and_archive_modes_equal": True, "index_sha256": sha(index_raw), "source_members": 177, "original_evidence_members": 11, "input_archive_members": 1, "index_members": 1},
    "source": {"computed_blob_count": 177, "git_modes": sorted({e["mode"] for e in computed_sources}), "archive_modes": sorted(set(tar_modes.values())), "mode_boundary": "Tar 0644 and extracted filesystem permissions are not Git mode 100644; only native source manifest Git modes entered object construction.", "source_manifest_sha256": sha(source_raw), "original_base_input": {**file_pin(base_path), "retained_copy": "input/original-base-direct-map.json.gz", "retained_gzip_sha256": sha(base_gzip), "r14_source_tree_and_ancestor_metadata_used_for_target": False}, "base_directories_verified": len(base_verified) + len(base_additions), "additional_original_base_trees": base_additions, "target_ancestors_computed_from_r15_paths": len(ancestors), "computed_tree": computed_tree, "root_gitdata_roundtrip_result_used_as_input": False, "unexpanded_subtrees": "Unchanged opaque child tree and blob IDs are anchored in the verified original base direct maps; their entire descendant contents were not downloaded or rehashed.", "lock": {"changed_in_overlay": False, "base_git_blob": base["codex-rs/Cargo.lock"]["sha"], "native_source_and_post_gate_sha256": source["lock_sha256"], "raw_lock_bytes_independently_rehashed": False}, "workflow_raw_sha256_verified": source["workflow_sha256"]},
    "formal_original_evidence": formal_readback,
    "gates": gate_readback,
    "environment_manifest": {"sha256": sha(blobs["evidence/native-core-mcp-r15-environment.json"]), "source_tree_equal": True},
    "tests": {"unique_executed_ids": 4026, "counts": {"PASS": 4023, "FAIL": 3, "TIMEOUT": 0}, "per_package": dict(per_package), "per_binary": dict(per_binary), "nextest_execution_seconds": float(summary[1].strip().removesuffix(b"s")), "reported_skipped": 9, "skip_identity_boundary": "9 is independently read from Starting and Summary. No original per-ID SKIP rows or list JSON are present in this r15 archive, so this report does not derive or certify the nine identities.", "footer_failure_repetitions_excluded": len(footer), "raw_log_bytes": len(raw_log), "raw_log_sha256": sha(raw_log), "summary_line": summary[0].decode(), "all_actual_rows": "TEST-ROWS.json.gz", "failure_ranges": [{k: v for k, v in b.items() if k != "excerpt"} for b in failure_blocks], "failure_excerpts": "FAILURE-BLOCKS.json"},
    "original_r14_failures": {"input": file_pin(r14_review_path), "only_original_failed_IDs_used": True, "distinct_ids": 24, "r15_counts": {"PASS": 22, "FAIL": 2}, "outcomes_from_r15_raw_log": old_outcomes},
    "new_hook_owner_regression": hook_row,
    "native_terminal_and_post_gate": {"terminal_receipt_sha256": sha(blobs["evidence/native-core-mcp-r15-process-terminal.json"]), "terminal_exit_code": 100, "wrapper_log_truncation_reported": False, "terminal_wrapper_stdout_bytes": terminal["log_bytes"]["stdout"]["stored"], "wrapper_output_is_distinct_from_full_test_log": True, "post_gate_manifest_sha256": sha(blobs["evidence/native-core-mcp-r15-source-post-test-verification.json"]), "source_and_clean_worktree_fields_consistent": True, "boundary": "These are closed native execution receipts; the reviewer checked their exact bytes and consistency but did not independently re-execute or inspect the remote working tree."},
    "discrepancies": [],
    "qualification_boundary": "Readback PASS certifies evidence consistency, not test success. r15 remains FAIL100, 3 actual failures. This report confers no r16, full-workspace, ignored-test, cross-platform, external-service or model-efficacy qualification.",
}
outputs = ["ARCHIVE-MEMBER-READBACK.json", "TREE-REBUILD.json", "FAILURE-BLOCKS.json", "TEST-ROWS.json.gz", "independent_readback.py", "input/base-tree-fetch-manifest.json", "input/original-base-direct-map.json.gz"] + [f["path"] for f in fetch_manifest["files"]]
report["reproducibility_files"] = [file_pin(OUT / name) for name in outputs]
write_json("INDEPENDENT-READBACK.json", report)
print(json.dumps({"audit_status": "PASS", "source_tree": computed_tree, "archive_members": len(members), "source_files": len(computed_sources), "counts": dict(counts), "reported_skips": 9, "original_24": dict(Counter(r["status"] for r in old_outcomes)), "failure_byte_ranges": [b["log_byte_range_half_open"] for b in failure_blocks], "report": file_pin(OUT / "INDEPENDENT-READBACK.json")}))
