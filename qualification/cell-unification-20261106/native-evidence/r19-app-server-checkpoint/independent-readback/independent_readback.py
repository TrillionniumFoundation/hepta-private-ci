#!/usr/bin/env python3
"""Independently read closed r19 archive/source/results using Python stdlib only.

Reads only pinned local inputs. Writes audit outputs beside this script.
Does not invoke Git, Cargo, Rust, native tools, network, or any test runner.
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
CHECKPOINT = ROOT / "native-validation-results/checkpoint-r19"
FORMAL = ROOT / "hepta-cell/qualification/cell-unification-20261106/native-evidence/r19-app-server-checkpoint"
BASE_COMMIT = "bef6fa7645df9df12b69fda499e97eed25de6c75"
BASE_TREE = "ce997fd958b8073d99b1e5bc302b7a0188fb4c3b"
TARGET_COMMIT = "0c78b43424ced27d37892a7744de065c1497d5e8"
TARGET_TREE = "cc2b01c2f69f43d63f8f5c561abd5e941d645769"
BASE_RAW_SHA = "56f7a3076b782105db36509abe860d9872c27bfa41685fb80b31e68b1a5abda1"
LOCK_SHA = "4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c"
LOG_SHA = "917632f553e67bb4787e160da977f3d97440c4d9e50bfcc09d733ad752c7e73e"
JOB = "1a1b03cadff-fc05-6f44"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def git_hash(kind, raw):
    return hashlib.sha1(kind.encode() + b" " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def require(value, message):
    if not value:
        raise AssertionError(message)


def serial(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def emit(name, value):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(serial(value))


def pin(path):
    raw = path.read_bytes()
    return {"path": str(path.relative_to(ROOT)), "bytes": len(raw), "sha256": sha(raw)}


def tree_hash(children):
    raw = bytearray()
    for name, entry in sorted(children.items(), key=lambda x: x[0].encode() + (b"/" if x[1]["type"] == "tree" else b"")):
        mode = "40000" if entry["type"] == "tree" else entry["mode"].lstrip("0")
        raw.extend(mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(entry["sha"]))
    return git_hash("tree", bytes(raw))


def read_tar(raw, expected_count=None):
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        members = archive.getmembers()
        if expected_count is not None:
            require(len(members) == expected_count, "archive regular member count")
        require(len({m.name for m in members}) == len(members), "duplicate archive member")
        for m in members:
            p = PurePosixPath(m.name)
            require(m.isfile() and not p.is_absolute() and ".." not in p.parts and str(p) == m.name, "unsafe/nonregular member: " + m.name)
        return {m.name: archive.extractfile(m).read() for m in members}, {m.name: m.mode for m in members}


archive_pin = json.loads((OUT / "input/ARCHIVE-PIN.json").read_bytes())
archive_path = ROOT / archive_pin["path"]
archive_raw = archive_path.read_bytes()
require((len(archive_raw), sha(archive_raw)) == (1127067, "5001f43d00ca61b2da70cedc1ba073f2cc17c7a5c5c30eaf1c0a78df4f1d4908"), "archive raw identity")
blobs, archive_modes = read_tar(archive_raw, 203)
require(sum(p.startswith("source/") for p in blobs) == 181, "181 source archive members")
require(sum(p.startswith("evidence/") for p in blobs) == 20, "20 evidence archive members")
require({p for p in blobs if p.startswith("input/")} == {"input/stage47-input.tar.gz"}, "stage47 archive member")
index = json.loads(blobs["INDEX.json"])
require(index["source_tree"] == TARGET_TREE and index["source_commit"] == TARGET_COMMIT, "INDEX source")
require(index["source_file_count"] == 181 and index["evidence_file_count"] == 20 and index["test_execution_started"] is True and index["outcome"] == "STRICT_PASS_TESTS_FAILED", "INDEX source/result scope")
require(index["counts"] == {"PASS": 1338, "FAIL": 7, "TIMEOUT": 0} and index["reported_skipped"] == 2, "INDEX result counts")
listed = {e["path"]: e for e in index["files"]}
require(len(listed) == 202 and set(listed) == set(blobs) - {"INDEX.json"}, "INDEX membership")
member_readback = []
for name, raw in blobs.items():
    disk = CHECKPOINT / name
    require(not disk.is_symlink() and disk.is_file() and disk.read_bytes() == raw, "exact extracted member: " + name)
    if name in listed:
        entry = listed[name]
        require((len(raw), sha(raw)) == (entry["bytes"], entry["sha256"]), "INDEX raw pin: " + name)
        if "mode" in entry:
            require((int(entry["mode"], 8) & 0o777) == (archive_modes[name] & 0o777), "INDEX/archive permission bits: " + name)
    member_readback.append({"path": name, "bytes": len(raw), "sha256": sha(raw), "archive_mode": format(archive_modes[name], "o"), "extracted_exact": True})

source_raw = blobs["evidence/native-candidate-r19-source.json"]
source = json.loads(source_raw)
require(sha(source_raw) == "64e26c5c3340b27d6b64b7342fac8561300224f9f1e96c22f2aa23b184eafee3", "actual native source manifest hash")
require(source["source_tree"] == TARGET_TREE and source["source_commit"] == TARGET_COMMIT and source["applied_stage"] == 47, "source stage identity")
require(BASE_COMMIT in source["parent_identities"], "original framework parent")
source_entries = {e["path"]: e for e in source["changed_files"]}
require(len(source_entries) == len(source["changed_files"]) == 181, "source path count")
require({"source/" + p for p in source_entries} == {p for p in blobs if p.startswith("source/")}, "source membership")
require({str(p.relative_to(CHECKPOINT / "source")) for p in (CHECKPOINT / "source").rglob("*") if p.is_file()} == set(source_entries), "extracted source extra/missing files")
computed_sources = []
for path, e in source_entries.items():
    raw = blobs["source/" + path]
    blob = git_hash("blob", raw)
    require((len(raw), sha(raw), blob) == (e["bytes"], e["sha256"], e["git_blob"]), "source raw/blob: " + path)
    require(e["mode"] in ("100644", "100755") and listed["source/" + path]["mode"] == e["mode"], "source Git mode")
    require(blob == listed["source/" + path]["git_blob"], "archive source Git blob")
    computed_sources.append({"path": path, "mode": e["mode"], "type": "blob", "sha": blob, "bytes": len(raw), "sha256": sha(raw)})
require(source["lock_sha256"] == LOCK_SHA and "codex-rs/Cargo.lock" not in source_entries, "unchanged declared Cargo.lock")
require(sha(blobs["source/.github/workflows/hepta-cell-framework-native.yml"]) == source["workflow_sha256"], "workflow raw identity")

# Independently reconstruct from original base children; ignore earlier target-tree metadata.
base_pins = json.loads((OUT / "input/BASE-INPUT-PINS.json").read_bytes())
for e in base_pins["retained_original_inputs"]:
    raw = (OUT / e["path"]).read_bytes()
    require((len(raw), sha(raw)) == (e["bytes"], e["sha256"]), "retained base input bytes")
base_raw = gzip.decompress((OUT / "input/original-base-direct-map.json.gz").read_bytes())
require(sha(base_raw) == BASE_RAW_SHA, "original raw base JSON hash")
base_input = json.loads(base_raw)
require(base_input["source_base_commit"] == BASE_COMMIT and base_input["base_tree"] == BASE_TREE and base_input["base_listing_truncated"] is False, "base source identity")
base = {e["path"]: dict(e) for e in base_input["base_entries"]}
require(len(base) == len(base_input["base_entries"]), "duplicate original base entries")
fetch_manifest = json.loads((OUT / "input/base-tree-fetch-manifest.json").read_bytes())
directory_paths = {"codex-mcp": "codex-rs/codex-mcp", "codex-mcp-src": "codex-rs/codex-mcp/src", "session": "codex-rs/core/src/session", "tools": "codex-rs/core/src/tools", "runtimes": "codex-rs/core/src/tools/runtimes", "zsh-fork": "codex-rs/core/src/tools/runtimes/zsh_fork", "common": "codex-rs/core/tests/common"}
maps = [{**e, "directory": directory_paths[e["name"]], "source": "retained immutable original-base direct GitHub tree response"} for e in fetch_manifest["files"]]
maps += [{**e, "source": "direct children selected from retained complete original-base recursive GitHub tree response"} for e in base_pins["additional_base_direct_maps"]]
base_additions = []
for m in maps:
    raw = (OUT / m["path"]).read_bytes()
    require((len(raw), sha(raw)) == (m["bytes"], m["sha256"]), "additional base input bytes")
    tree = json.loads(raw)
    directory = m["directory"]
    require(directory in base and base[directory]["sha"] == m["sha"] == tree["sha"] and tree["truncated"] is False, "parent-anchored base tree: " + directory)
    children = {}
    for e in tree["tree"]:
        name = e["path"]
        require("/" not in name and name not in ("", ".", "..") and name not in children, "direct base child")
        children[name] = {k: e[k] for k in ("mode", "type", "sha")}
        full = directory + "/" + name
        added = {"path": full, **children[name]}
        if full in base:
            require(base[full] == added, "conflicting base entry")
        base[full] = added
    require(tree_hash(children) == tree["sha"], "base direct content hash")
    base_additions.append({"directory": directory, "computed_tree": tree["sha"], "children": len(children), "input": m["path"], "input_sha256": sha(raw), "source": m["source"]})
children = defaultdict(dict)
for path, e in base.items():
    parent, _, name = path.rpartition("/")
    children[parent][name] = {k: e[k] for k in ("mode", "type", "sha")}
require(tree_hash(children[""]) == BASE_TREE, "original framework root content hash")
base_verified = [{"path": "", "sha": BASE_TREE}]
for e in base_input["existing_directory_pins"]:
    require(tree_hash(children[e["path"]]) == e["sha"], "original expanded directory content hash")
    base_verified.append({"path": e["path"], "sha": e["sha"]})
ancestors = {""}
for e in computed_sources:
    parent = e["path"].rpartition("/")[0]
    while parent:
        ancestors.add(parent)
        parent = parent.rpartition("/")[0]
for directory in ancestors:
    if directory in base and base[directory]["type"] == "tree":
        require(tree_hash(children[directory]) == base[directory]["sha"], "all original siblings retained: " + directory)
for e in computed_sources:
    parent, _, name = e["path"].rpartition("/")
    children[parent][name] = {k: e[k] for k in ("mode", "type", "sha")}
rebuild = []
for directory in sorted(ancestors, key=lambda p: (p.count("/") + bool(p), p), reverse=True):
    computed = tree_hash(children[directory])
    rebuild.append({"path": directory, "computed_tree": computed, "direct_children": len(children[directory])})
    if directory:
        parent, _, name = directory.rpartition("/")
        children[parent][name] = {"mode": "040000", "type": "tree", "sha": computed}
computed_tree = tree_hash(children[""])
require(computed_tree == TARGET_TREE, "independent source47 tree")

# Bind stage input bytes without using root target-roundtrip output for reconstruction.
input_raw = blobs["input/stage47-input.tar.gz"]
require(sha(input_raw) == source["input_archive_sha256"], "stage input archive hash")
stage_members, _ = read_tar(input_raw, 6)
stage = json.loads(stage_members["manifest.json"])
require(stage["source_commit"] == TARGET_COMMIT and stage["expected_after_tree"] == computed_tree and stage["expected_changed_file_count"] == 181, "stage input identity")
require(sha(stage_members["combined.patch"]) == stage["combined_patch"]["sha256"] == source["input_combined_patch_sha256"], "stage patch pin")
for filename, key in (("root-publish-manifest.json", "root_publish_manifest_sha256"), ("root-published-source.json", "root_published_source_sha256")):
    require(sha(stage_members[filename]) == stage[key], "stage metadata raw pin")
for f in stage["files"]:
    e = source_entries[f["path"]]
    require(all(e[k] == f["after"][k] for k in ("bytes", "sha256", "git_blob", "mode")), "stage after bytes in actual archive")
input_readback = {"archive_bytes": len(input_raw), "archive_sha256": sha(input_raw), "members": [{"path": k, "bytes": len(v), "sha256": sha(v)} for k, v in stage_members.items()], "stage_file_count": len(stage["files"]), "target_tree_reconstructed_without_root_publish_proof": True}

environment = json.loads(blobs["evidence/native-app-server-r19-environment.json"])
require(environment["source_tree"] == TARGET_TREE and environment["source_environment_immutable_during_gates"] is True and environment["test_deadlines_features_filters_retries_unchanged"] is True, "gate environment/source declarations")
gates = {}
receipts = {}
phase_posts = []
resource_fields = {"user_seconds": rb"User time \(seconds\): ([^\r\n]+)", "system_seconds": rb"System time \(seconds\): ([^\r\n]+)", "max_resident_kbytes": rb"Maximum resident set size \(kbytes\): ([^\r\n]+)", "wall_time_text": rb"Elapsed \(wall clock\) time \(h:mm:ss or m:ss\): ([^\r\n]+)"}
for phase, expected_exit in (("strict", 0), ("tests", 100)):
    stem = "evidence/native-app-server-r19-" + phase
    receipt = json.loads(blobs[stem + "-receipt.json"])
    receipts[phase] = receipt
    log = blobs[stem + ".log"]
    resources = blobs[stem + "-resources.txt"]
    command = ["just", "clippy", "--locked", "-p", "codex-app-server", "--", "-D", "warnings"] if phase == "strict" else ["just", "test", "--locked", "-p", "codex-app-server", "--retries", "0"]
    require(receipt["phase"] == phase and receipt["command"] == command and receipt["packages"] == ["codex-app-server"], "original selected gate command")
    require(receipt["source_tree"] == TARGET_TREE and receipt["source_commit"] == TARGET_COMMIT and receipt["exit_code"] == expected_exit, "gate source/result")
    require(receipt["source_manifest"] == "native-candidate-r19-source.json" and receipt["environment_manifest"] == "native-app-server-r19-environment.json", "gate manifest references")
    require(sha(log) == receipt["log_sha256"] and sha(resources) == receipt["resources_sha256"], "receipt log/resources hash")
    require(abs(receipt["end_unix"] - receipt["start_unix"] - receipt["elapsed_seconds"]) < 1e-9, "elapsed arithmetic")
    require(re.findall(rb"^[ \t]*Exit status: (\d+)\s*$", resources, re.M) == [str(expected_exit).encode()], "resource exit")
    require(('Command being timed: "' + " ".join(command) + '"').encode() in resources, "resource command")
    post_raw = blobs[stem + "-source-post-verification.json"]
    post = json.loads(post_raw)
    require(post["source_tree"] == post["actual_tree_after_phase"] == TARGET_TREE and post["phase"] == phase and post["gate_exit_code"] == expected_exit, "phase post source/result")
    require(post["all_changed_source_hashes_match"] is True and post["changed_file_count"] == 181 and post["unstaged_empty"] is True and post["untracked_source"] == [] and post["lock_sha256"] == LOCK_SHA, "phase post source/lock cleanliness")
    phase_posts.append({"path": stem + "-source-post-verification.json", "sha256": sha(post_raw), "phase": phase, "source_and_lock_consistent": True})
    parsed_resources = {}
    for field, pattern in resource_fields.items():
        match = re.search(pattern, resources)
        require(match is not None, "resource field: " + field)
        parsed_resources[field] = match[1].decode()
    gates[phase] = {"command": command, "exit_code": expected_exit, "elapsed_seconds": receipt["elapsed_seconds"], "receipt_sha256": sha(blobs[stem + "-receipt.json"]), "log_bytes": len(log), "log_sha256": sha(log), "resources_sha256": sha(resources), "resource_values": parsed_resources, "receipt_log_resources_exact": True}
require(receipts["strict"]["end_unix"] <= receipts["tests"]["start_unix"], "strict before tests")
require(receipts["tests"]["retries"] == 0 and receipts["strict"]["retries"] is None, "original retry flags")

raw_log = blobs["evidence/native-app-server-r19-tests.log"]
require((len(raw_log), sha(raw_log)) == (225301, LOG_SHA), "full test log pin")
summaries = list(re.finditer(rb"^[ \t]*Summary \[([^\]\r\n]+)\] ([^\r\n]+)", raw_log, re.M))
require(len(summaries) == 1, "single original nextest Summary")
summary = summaries[0]
require(summary[2] == b"1345 tests run: 1338 passed, 7 failed, 2 skipped", "Summary counts")
starts = list(re.finditer(rb"^[ \t]*Starting (\d+) tests across (\d+) binaries \((\d+) tests skipped\)", raw_log, re.M))
require(len(starts) == 1 and starts[0].groups() == (b"1345", b"6", b"2"), "Starting counts")
status_pattern = rb"^[ \t]*(PASS|FAIL|TIMEOUT|SKIP)[ \t]+\[([^\]\r\n]+)\][ \t]+(\S+)[ \t]+([^\r\n]+)"
matches = list(re.finditer(status_pattern, raw_log[:summary.start()], re.M))
rows = [{"status": m[1].decode(), "elapsed": m[2].decode().strip(), "binary": m[3].decode(), "name": m[4].decode(), "log_byte_offset": m.start(), "log_line": raw_log.count(b"\n", 0, m.start()) + 1, "line": m[0].decode().strip()} for m in matches]
by_id = {(x["binary"], x["name"]): x for x in rows}
counts = Counter(x["status"] for x in rows)
require(len(rows) == len(by_id) == 1345 and counts == {"PASS": 1338, "FAIL": 7}, "unique original executed test rows")
footer = list(re.finditer(status_pattern, raw_log[summary.end():], re.M))
failed_ids = {key for key, value in by_id.items() if value["status"] == "FAIL"}
require(len(footer) == 7 and all(m[1] == b"FAIL" for m in footer), "seven footer repetitions")
require({(m[3].decode(), m[4].decode()) for m in footer} == failed_ids, "footer actual failed-ID set")
native_rows = json.loads(blobs["evidence/native-app-server-r19-test-results.json"])
require(len(native_rows) == 1345 and len({(x["binary"], x["name"]) for x in native_rows}) == 1345, "native row inventory")
native_by_id = {(x["binary"], x["name"]): x for x in native_rows}
require(set(native_by_id) == set(by_id), "native row IDs equal raw log")
for key, row in by_id.items():
    require(all(native_by_id[key][field] == row[field] for field in ("status", "binary", "name", "line")), "native row exact line")

native_blocks = json.loads(blobs["evidence/native-app-server-r19-failure-blocks.json"])
blocks_by_id = {(x["binary"], x["name"]): x for x in native_blocks}
require(len(native_blocks) == len(blocks_by_id) == 7 and set(blocks_by_id) == failed_ids, "seven original failure block IDs")
failure_blocks = []
for i, m in enumerate(matches):
    if m[1] != b"FAIL":
        continue
    start = m.start()
    end = matches[i + 1].start() if i + 1 < len(matches) else summary.start()
    excerpt = raw_log[start:end]
    row = by_id[(m[3].decode(), m[4].decode())]
    nb = blocks_by_id[(row["binary"], row["name"])]
    require(excerpt == nb["block"].encode() and sha(excerpt) == nb["block_sha256"], "exact full failure block")
    require(raw_log.count(excerpt) == 1, "unique full failure block occurrence")
    failure_blocks.append({**row, "log_byte_range_half_open": [start, end], "bytes": len(excerpt), "sha256": sha(excerpt), "excerpt": excerpt.decode(), "original_block_bytes_exact": True})

review = json.loads(blobs["evidence/native-app-server-r19-result-review.json"])
require(review["source_tree"] == TARGET_TREE and review["source_commit"] == TARGET_COMMIT and review["job_id"] == JOB, "native review identity")
require(review["counts"] == {"PASS": 1338, "FAIL": 7, "TIMEOUT": 0} and review["unique_test_count"] == 1345 and review["reported_skipped"] == 2, "native review count agreement")
require(review["log_sha256"] == LOG_SHA and review["log_bytes"] == len(raw_log) and review["footer_duplicates_not_counted"] == 7, "review log/footer binding")
require(review["exit_code"] == receipts["tests"]["exit_code"] == 100 and review["elapsed_seconds"] == receipts["tests"]["elapsed_seconds"], "review terminal receipt agreement")
require(review["command"] == receipts["tests"]["command"] and review["test_execution_started"] is True, "review executed command")
require(review["no_workspace_r20_started"] is True and review["no_fix_fmt_executed"] is True, "historical no-follow-up record")
require(review["summary"] == summary[0].decode().strip(), "native exact Summary")
require(len(review["failed_tests"]) == 7 and {(x["binary"], x["name"]) for x in review["failed_tests"]} == failed_ids, "native review failed-ID set")
for item in review["failed_tests"]:
    require(item["status"] == "FAIL" and item["block_sha256"] == blocks_by_id[(item["binary"], item["name"])]["block_sha256"], "native review failure-block pin")
process_ids = [
    "suite::v2::process_exec::process_kill_terminates_running_process",
    "suite::v2::process_exec::process_spawn_reports_buffered_output_cap_reached",
    "suite::v2::process_exec::process_spawn_returns_before_exit_and_emits_exit_notification",
    "suite::v2::process_exec::process_spawn_returns_error_when_local_environment_is_disabled",
    "suite::v2::process_exec::capability_tests::process_spawn_refuses_legacy_or_terminal_opt_out_before_creating_a_process",
]
process_rows = [by_id[("codex-app-server::all", name)] for name in process_ids]
require(all(x["status"] == "PASS" for x in process_rows), "four process_exec plus one capability originals PASS")
require({x["name"] for x in review["original_process_exec_cases"]} == set(process_ids), "native original process case set")
for e in review["original_process_exec_cases"]:
    row = by_id[(e["binary"], e["name"])]
    require(all(e[k] == row[k] for k in ("status", "line")), "native original process row")
process_source = blobs["source/codex-rs/app-server/tests/suite/v2/process_exec.rs"]
for name in process_ids[:4]:
    require(("async fn " + name.split("::")[-1] + "(").encode() in process_source, "archived original process fixture definition")

terminal_raw = blobs["evidence/native-app-server-r19-terminal-process-status.json"]
terminal = json.loads(terminal_raw)
require(terminal["job_id"] == JOB and terminal["state"] == "failed" and terminal["exit_code"] == 100, "actual process terminal")
require(all(terminal[k] is True for k in ("output_complete", "output_durable", "terminal_publication_confirmed")), "terminal output closure")
require(all(terminal[k] is False for k in ("automatic_retry", "cancelled", "timed_out")) and not any(terminal["log_truncated"].values()), "no native timeout/cancel/retry/truncation")
require(terminal["at_unix_ms"] / 1000 >= receipts["tests"]["end_unix"], "terminal publication after test receipt")
control_raw = blobs["evidence/native-app-server-r19-control-status-timeout.txt"]
require(b"heptaruntime_mac_controller.process_status" in control_raw and b"MCP request timed out" in control_raw, "separate controller status read timeout")
post_raw = blobs["evidence/native-app-server-r19-source-post-test-verification.json"]
post = json.loads(post_raw)
require(post["source_tree"] == TARGET_TREE and post["source_commit"] == TARGET_COMMIT and post["changed_source_count"] == 181 and post["lock_sha256"] == LOCK_SHA, "archive post source/lock")
require(post["unstaged_changed_paths"] == [] and post["untracked_paths"] == [] and post["sampled_unix"] >= receipts["tests"]["end_unix"], "archive post source cleanliness/time")

# The exact small blocker export is retained inside the full archive too.
blocker = json.loads(blobs["evidence/native-app-server-r19-blocker-input.json"])
require(blocker["source_tree"] == TARGET_TREE and blocker["source_commit"] == TARGET_COMMIT, "nested blocker source")
nested, _ = read_tar(blobs["evidence/native-app-server-r19-blocker-input.tar.gz"])
for nested_name, original_name in (("source-manifest.json", "native-app-server-r19-blocker-input.json"), ("failure-blocks.json", "native-app-server-r19-failure-blocks.json"), ("result-review.json", "native-app-server-r19-result-review.json")):
    require(nested[nested_name] == blobs["evidence/" + original_name], "nested small export exact evidence")
for f in blocker["files"]:
    raw = nested["source/" + f["path"]]
    require((len(raw), sha(raw), git_hash("blob", raw)) == (f["bytes"], f["sha256"], f["git_blob"]), "nested blocker original raw/blob")
    require(f["unchanged_from_bef"] is True and f["git_blob"] == f["base_blob"] == base[f["path"]]["sha"], "nested blocker original-base identity")
owner = json.loads(blobs["evidence/native-app-server-r19-disconnect-owner-map.json"])
require(owner["source_tree"] == TARGET_TREE and owner["source_commit"] == TARGET_COMMIT and owner["source_written"] is False and owner["rust_command_executed"] is False, "retained read-only owner map declarations")

formal_readback = []
for name in sorted(p for p in blobs if p.startswith("evidence/")):
    basename = name.split("/", 1)[1]
    candidates = [FORMAL / basename, FORMAL / (basename + ".gz")]
    found = next((p for p in candidates if p.is_file()), None)
    if found is None:
        formal_readback.append({"original_member": name, "original_bytes": len(blobs[name]), "original_sha256": sha(blobs[name]), "formal_present": False, "formal_copy_owner": "/root"})
        continue
    stored = found.read_bytes()
    lossless = found.name == basename + ".gz"
    raw = gzip.decompress(stored) if lossless else stored
    require(raw == blobs[name], "formal evidence exact: " + basename)
    formal_readback.append({**pin(found), "original_member": name, "original_bytes": len(raw), "original_sha256": sha(raw), "lossless_gzip": lossless, "formal_present": True, "exact": True})
per_binary = defaultdict(Counter)
for row in rows:
    per_binary[row["binary"]][row["status"]] += 1
emit("ARCHIVE-MEMBER-READBACK.json", {"schema": "hepta.r19-independent-archive-members.v1", "archive_sha256": sha(archive_raw), "members": member_readback})
emit("TREE-REBUILD.json", {"schema": "hepta.r19-independent-tree-rebuild.v1", "base_commit": BASE_COMMIT, "base_tree": BASE_TREE, "original_base_directories": base_verified, "additional_original_base_maps": base_additions, "source_entries_computed_from_archived_bytes": computed_sources, "computed_directories": rebuild, "computed_tree": computed_tree, "root_target_proof_used_as_input": False})
emit("FAILURE-BLOCKS.json", {"schema": "hepta.r19-independent-failure-blocks.v1", "raw_log_sha256": LOG_SHA, "offset_unit": "zero-based UTF-8 raw bytes, half-open", "blocks": failure_blocks})
rows_raw = serial({"schema": "hepta.r19-independent-test-rows.v1", "source_tree": TARGET_TREE, "raw_log_sha256": LOG_SHA, "rows": rows})
(OUT / "TEST-ROWS.json.gz").write_bytes(gzip.compress(rows_raw, mtime=0))
emit("STAGE-INPUT-READBACK.json", input_readback)
emit("CONTROL-VS-TERMINAL.json", {
    "schema": "hepta.r19-control-vs-native-terminal.v1",
    "control_read_error": {"path": "evidence/native-app-server-r19-control-status-timeout.txt", "bytes": len(control_raw), "sha256": sha(control_raw), "text": control_raw.decode(), "timestamp_present": False},
    "actual_native_terminal": {"path": "evidence/native-app-server-r19-terminal-process-status.json", "sha256": sha(terminal_raw), "job_id": JOB, "state": "failed", "exit_code": 100, "timed_out": False, "cancelled": False, "automatic_retry": False},
    "conclusion": "A process_status MCP request timed out; this is not a process timeout or test result. The independent complete log, test/resource receipts and durable process terminal agree on natural test failure100.",
    "ordering_boundary": "The retained controller error has no timestamp. This readback does not infer when that status-read failure occurred relative to process completion.",
    "wrapper_output_boundary": "The24666-byte durable controller stdout is a wrapper output containing tails. It is not the225301-byte complete original test log.",
})
artifacts = ["ARCHIVE-MEMBER-READBACK.json", "TREE-REBUILD.json", "FAILURE-BLOCKS.json", "TEST-ROWS.json.gz", "STAGE-INPUT-READBACK.json", "CONTROL-VS-TERMINAL.json", "independent_readback.py"]
report = {
    "schema": "hepta.r19-independent-closed-readback.v1",
    "status": "READBACK_COMPLETE_STRICT_PASS_TESTS_FAIL",
    "source_commit": TARGET_COMMIT, "source_tree": computed_tree, "source_stage": 47,
    "reviewer": "/root/historical_assets",
    "archive": {**pin(archive_path), "regular_unique_safe_members": 203, "INDEX_entries": 202, "source_files": 181, "evidence_files": 20, "stage_input_archives": 1, "all_member_raw_hashes_and_extracted_bytes_exact": True},
    "source_reconstruction": {"method": "Original framework base direct maps, seven retained immutable base responses and four app-server direct maps derived from a retained complete original-base listing; all affected original sibling sets rehashed before applying181 archived file blobs.", "base_commit": BASE_COMMIT, "base_tree": BASE_TREE, "computed_tree": computed_tree, "root_target_proof_used": False, "root_publish_metadata_used_to_construct_tree": False, "source_manifest_sha256": sha(source_raw), "original_base_raw_json_sha256": BASE_RAW_SHA, "base_directories_verified": len(base_verified), "additional_base_maps": len(base_additions), "target_ancestors": len(ancestors), "archived_source_Git_modes_used": True, "unexpanded_subtrees": "Unchanged opaque subtree/blob IDs remain anchored in independently verified original base tree objects; their complete descendant bytes were not re-downloaded.", "Cargo_lock": {"changed_in_overlay": False, "original_base_blob": base["codex-rs/Cargo.lock"]["sha"], "declared_native_pre_post_sha256": LOCK_SHA, "raw_lock_bytes_rehashed_by_this_auditor": False}},
    "gates": gates,
    "phase_source_posts": phase_posts,
    "environment": {"original_sha256": sha(blobs["evidence/native-app-server-r19-environment.json"]), "selection": environment["selection"], "recorded_selection_is_not_a_new_execution": True},
    "tests": {"unique_executed_IDs": 1345, "counts": {"PASS": 1338, "FAIL": 7, "TIMEOUT": 0}, "reported_skipped": 2, "skip_identity_boundary": "Two skipped is independently present in Starting and Summary. No per-ID SKIP row/list is retained, so identities are not independently certified.", "nextest_execution_seconds": 396.597, "whole_gate_elapsed_seconds": receipts["tests"]["elapsed_seconds"], "footer_duplicates_excluded": 7, "per_binary": {k: dict(v) for k, v in per_binary.items()}, "log_bytes": len(raw_log), "log_sha256": LOG_SHA, "summary_line": summary[0].decode().strip(), "native_row_inventory_exact": True, "all_seven_failure_blocks_exact": True, "failure_ranges": [{k: v for k, v in b.items() if k != "excerpt"} for b in failure_blocks]},
    "original_process_exec_four_and_capability_one": process_rows,
    "terminal": {"job_id": JOB, "state": "failed", "exit_code": 100, "timed_out": False, "cancelled": False, "automatic_retry": False, "durable_closed": True, "terminal_receipt_sha256": sha(terminal_raw), "controller_status_read_timeout_not_test_timeout": True},
    "archive_post_verification": {"sha256": sha(post_raw), "source_tree_and_lock_match": True, "changed_files": 181, "unstaged_and_untracked_empty": True},
    "resource_boundary": {"shared_free_before": environment["free_bytes_before"], "shared_free_at_archive_packaging": post["free_bytes_at_archive_verification"], "sampled_at_different_times": True, "exclusive_task_disk_cost_inferred": False},
    "stage_input": input_readback,
    "nested_blocker_input": {"source_files_verified": len(blocker["files"]), "all_equal_original_base_blobs": True, "complete_archive_member_hash_verified": True},
    "formal_attachment_snapshot": {"present_exact": sum(x["formal_present"] for x in formal_readback), "not_yet_present": sum(not x["formal_present"] for x in formal_readback), "files": formal_readback, "formal_owner": "/root"},
    "boundaries": [
        "Only Python stdlib offline file/hash/JSON/tar/log analysis was executed; no Rust, Cargo, Git command, native controller, shell/network probe or test runner.",
        "No source, fixture, test budget, permission, assertion, retry, skip or filter was changed.",
        "This independent readback validates evidence, not a new test execution or a passing overall app-server gate.",
        "The observed scoped strict exit0 is not a zero-warning entire-workspace claim.",
        "source47 r20-workspace was not started after the failed r19 prerequisite. Later round identifiers are separate and are not inferred here.",
        "No full-workspace, final fix/fmt, final published SHA, remote CI, cross-platform or model-efficacy qualification follows from these scoped results.",
        "Native source/lock and process terminal declarations are checked for exact bytes and consistency; the reviewer did not inspect or rerun the remote working tree."
    ],
    "reproducibility_files": [pin(OUT / name) for name in artifacts] + [pin(p) for p in sorted((OUT / "input").glob("*")) if p.is_file()],
    "discrepancies": [],
}
emit("INDEPENDENT-READBACK.json", report)
print(json.dumps({"report": pin(OUT / "INDEPENDENT-READBACK.json"), "source_tree": computed_tree, "archive_members": len(blobs), "source_files": len(source_entries), "strict_exit": 0, "tests_exit": 100, "unique_tests": len(rows), "counts": dict(counts), "reported_skipped": 2, "footer_duplicates": len(footer), "process_exec_originals_PASS": len(process_rows), "failure_ranges": [x["log_byte_range_half_open"] for x in failure_blocks]}, indent=2))
