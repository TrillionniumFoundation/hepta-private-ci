from pathlib import Path
import collections, hashlib, json, re, tarfile

ROOT = Path("/workspace/scratch/08f5efd48967")
ARCHIVE = ROOT / "native-validation-results/checkpoint-r23-closed.tar.gz"
OUT = ROOT / "native-validation-results/checkpoint-r23"
REVIEW = ROOT / "r23-root-review"
TREE = "be34ab1afe622ad3b8f030c8c5018f4f54fbc304"
COMMIT = "50dd4bedefcd1b8e2e8cd5cf5023c60a86d38d0a"
LOCK = "4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c"

def sha(b):
    return hashlib.sha256(b).hexdigest()

def blob(b):
    return hashlib.sha1(b"blob " + str(len(b)).encode() + b"\0" + b).hexdigest()

def write(path, value):
    raw = (json.dumps(value, indent=2) + "\n").encode()
    with path.open("xb") as f:
        f.write(raw)

raw = ARCHIVE.read_bytes()
assert len(raw) == 2165685 and sha(raw) == "0e7f39f14a68e20bdaefa9646177bc5879098285e45ca42c6d13b81180fa7ee6"
assert blob(raw) == "e4ab664e6c29222b2a3a23d29a46c9d7d1066c5f"
assert not OUT.exists()
OUT.mkdir()
with tarfile.open(ARCHIVE, "r:gz") as tar:
    members = tar.getmembers()
    assert len(members) == 211 and all(m.isfile() for m in members)
    assert len({m.name for m in members}) == 211
    values = {}
    for member in members:
        path = Path(member.name)
        assert not path.is_absolute() and ".." not in path.parts
        values[member.name] = tar.extractfile(member).read()
    index = json.loads(values["INDEX.json"])
    assert len(index) == 210
    assert {r["path"] for r in index} == set(values) - {"INDEX.json"}
    member_map = {m.name: m for m in members}
    for row in index:
        b = values[row["path"]]
        assert len(b) == row["bytes"] and sha(b) == row["sha256"]
        assert f'{member_map[row["path"]].mode:04o}' == row["mode"]
    for member in members:
        path = OUT / member.name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(values[member.name])
        path.chmod(member.mode)

def read(name):
    return json.loads(values["evidence/" + name])

source = read("native-candidate-r22-source.json")
assert sha(values["evidence/native-candidate-r22-source.json"]) == "8cd1ec59c95d6c777d887f3302b257dc5230a7bfa5570fe9df0f0b2ef361aba5"
assert source["source_tree"] == TREE and source["source_commit"] == COMMIT
assert len(source["changed_files"]) == 188
assert sum(p.startswith("source/") for p in values) == 188
for row in source["changed_files"]:
    path = "source/" + row["path"]
    b = values[path]
    assert len(b) == row["bytes"] and sha(b) == row["sha256"] and blob(b) == row["git_blob"]
    assert int(row["mode"], 8) & 0o777 == member_map[path].mode
    previous = ROOT / "native-validation-results/checkpoint-r22/source" / row["path"]
    assert previous.read_bytes() == b
assert sha(values["input/Cargo.lock"]) == LOCK

receipt = read("native-workspace-r23-tests-receipt.json")
rawrc = read("native-workspace-r23-tests-raw-process-result.json")
terminal = read("native-workspace-r23-terminal-process-status.json")
for r in (receipt, rawrc):
    assert r["source_tree"] == TREE and r["source_commit"] == COMMIT
    assert r["command"] == ["just", "test", "--locked", "--retries", "0"]
    assert r["cwd"] == "/home/alex/work/hepta-cell-unified-20261106-a/source/codex-rs"
    assert r["exit_code"] == 100
assert receipt["start_unix"] == rawrc["start_unix"] and receipt["end_unix"] == rawrc["end_unix"]
assert terminal["job_id"] == "1a1b0f18be6-fc05-7441" and terminal["state"] == "failed" and terminal["exit_code"] == 100
assert terminal["output_complete"] and terminal["output_durable"] and terminal["terminal_publication_confirmed"]
assert not terminal["timed_out"] and not terminal["cancelled"] and not terminal["automatic_retry"]
for stream in ("stdout", "stderr"):
    b = values["evidence/native-workspace-r23-process." + stream + ".txt"]
    assert len(b) == terminal["log_bytes"][stream]["stored"] == terminal["log_bytes"][stream]["seen"]
    assert not terminal["log_truncated"][stream]
resources = values["evidence/native-workspace-r23-tests-resources.txt"]
assert sha(resources) == receipt["resources_sha256"] == "0cbaa54be8b81bb184ffcf9d3c7ff38657f571ed7352f51be438d4be72781785"
assert re.search(rb"Exit status:\s*100\s*$", resources, re.M)
for suffix in ("source-pre-verification", "source-post-test-verification"):
    guard = read("native-workspace-r23-" + suffix + ".json")
    assert guard["pass"] and guard["actual_tree"] == TREE and guard["changed_file_count"] == 188
    assert guard["lock_sha256"] == LOCK
    assert not guard["file_mismatches"] and not guard["unstaged_paths"] and not guard["untracked_paths"]
metadata = read("native-workspace-r23-metadata.json")
scope = read("native-workspace-r23-scope.json")
assert len(metadata["workspace_members"]) == len(metadata["workspace_default_members"]) == 193
assert metadata["workspace_members"] == [r["id"] for r in scope["workspace_members"]]
assert metadata["workspace_default_members"] == [r["id"] for r in scope["workspace_default_members"]]
assert set(metadata["workspace_members"]) == set(metadata["workspace_default_members"])
assert scope["metadata_sha256"] == sha(values["evidence/native-workspace-r23-metadata.json"])

log = values["evidence/native-workspace-r23-tests.log"]
assert len(log) == 2503794
assert sha(log) == receipt["log_sha256"] == "eb06c476d928ec2a6ebc95d3b3b84aa219ddd3a533d5a04d11aa4a217164d78e"
lines = log.splitlines(keepends=True)
summary_indices = [i for i, line in enumerate(lines) if re.match(rb"^[ \t]*Summary[ \t]+\[", line)]
assert len(summary_indices) == 1
summary_index = summary_indices[0]
summary = lines[summary_index].decode().strip()
assert summary == "Summary [1671.481s] 20228 tests run: 20220 passed (4 slow), 7 failed, 1 timed out, 130 skipped"
pattern = re.compile(rb"^[ \t]*(PASS|FAIL|TIMEOUT|CRASH|LEAK|EXECFAIL|XFAIL|XPASS)[ \t]+\[[ \t]*([0-9.]+)s\][ \t]+(\S+)[ \t]+(.+?)[ \t\r\n]*$")
rows = []
offset = 0
for index, line in enumerate(lines):
    match = pattern.match(line) if index < summary_index else None
    if match:
        rows.append({"status": match[1].decode(), "seconds": float(match[2]), "binary": match[3].decode(), "name": match[4].decode(), "line": index + 1, "byte_offset": offset})
    offset += len(line)
assert len(rows) == 20228 and len({(r["binary"], r["name"]) for r in rows}) == 20228
counts = dict(collections.Counter(r["status"] for r in rows))
assert counts == {"PASS": 20220, "FAIL": 7, "TIMEOUT": 1}
assert rows == read("native-workspace-r23-closed-test-results.json")
blocks = read("native-workspace-r23-closed-failure-blocks.json")
assert len(blocks) == 8
for block in blocks:
    b = log[block["start_byte"]:block["end_byte"]]
    assert sha(b) == block["sha256"] and b.decode() == block["text"]
    assert any((r["binary"], r["name"], r["status"]) == (block["binary"], block["name"], block["status"]) for r in rows)
derived = read("native-workspace-r23-closed-result-review.json")
assert derived["readback_pass"] and not derived["readback_errors"]
assert derived["counts"] == counts and derived["unique_execution_id_count"] == 20228
assert derived["reported_skips"] == [130]
report = {
    "schema": "hepta.root-r23-complete-archive-and-results-readback.v1",
    "source_commit": COMMIT, "source_tree": TREE, "source_changed_paths": 188,
    "archive": {"bytes": len(raw), "sha256": sha(raw), "git_blob": blob(raw), "regular_members": 211, "index_entries": 210},
    "all_index_path_byte_sha_mode_pins_verified": True,
    "all_188_raw_source_sha_git_blob_modes_verified": True,
    "all_188_source_bytes_equal_closed_r22_source49": True,
    "independent_full_tree_reconstruction": "Pending separate reviewer; root verified original archived sources and exact same-source equality, not a new complete-tree reconstruction.",
    "default_workspace_members": 193, "default_member_set_equal_full_workspace": True,
    "original_command": receipt["command"], "raw_exit_code": 100,
    "natural_outer_state": terminal["state"], "natural_outer_exit_code": 100,
    "original_elapsed_seconds_including_build": receipt["elapsed_seconds"],
    "nextest_execution_seconds": 1671.481,
    "log_bytes": len(log), "log_sha256": sha(log),
    "unique_executed_tests": 20228, "passed": 20220, "failed": 7, "timed_out": 1, "reported_skipped": 130,
    "all_exported_execution_rows_and_offsets_equal_root_full_log_parse": True,
    "failure_blocks_verified": 8,
    "failed_test_ids": [{"binary": r["binary"], "name": r["name"], "status": r["status"], "seconds": r["seconds"]} for r in rows if r["status"] != "PASS"],
    "source_and_lock_postguards_pass": True,
    "gate_pass": False, "evidence_readback_pass": True,
    "fix_fmt_executed": False, "scientific_disposition": "HOLD", "authority": "DENY_ALL",
    "no_Rust_or_source_mutation_by_readback": True,
}
REVIEW.mkdir(exist_ok=True)
write(REVIEW / "ROOT-RESULT-READBACK.json", report)
print(json.dumps({"report": str(REVIEW / "ROOT-RESULT-READBACK.json"), "report_sha256": sha((REVIEW / "ROOT-RESULT-READBACK.json").read_bytes()), "regular_members": 211, "indexed_members": 210, "source_files": 188, "tests": counts, "unique_tests": 20228, "skipped": 130, "gate_exit_code": 100}, indent=2))
