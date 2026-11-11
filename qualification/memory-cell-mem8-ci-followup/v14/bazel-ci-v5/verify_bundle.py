#!/usr/bin/env python3
"""Verify two original Bazel CI attempts offline without executing Bazel or tests."""
from pathlib import Path, PurePosixPath
import hashlib
import io
import json
import sys
import tarfile
import zipfile

root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).parent.resolve()
HEAD = "9bd2f589debdba4a93baa363817c3669cb103721"
TREE = "c77785ecb368c44ea699769001a47402c9f50591"

def info(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}

def safe(name):
    path = PurePosixPath(name)
    assert path.parts and not path.is_absolute() and ".." not in path.parts
    return path

def merkle(raw):
    root = {}
    for row in raw.split(b"\0"):
        if not row:
            continue
        meta, path = row.split(b"\t", 1)
        mode, kind, digest = meta.decode().split()
        assert kind in ("blob", "commit")
        current = root
        parts = safe(path.decode()).parts
        for part in parts[:-1]:
            current = current.setdefault(part, {})
        assert parts[-1] not in current
        current[parts[-1]] = mode, digest
    def tree(node):
        body = b""
        for name, value in sorted(node.items(), key=lambda item: item[0].encode() + (b"/" if isinstance(item[1], dict) else b"")):
            mode, digest = ("40000", tree(value)) if isinstance(value, dict) else value
            body += mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(digest)
        return hashlib.sha1(b"tree " + str(len(body)).encode() + b"\0" + body).hexdigest()
    return tree(root)

manifest = json.loads((root / "MANIFEST.json").read_bytes())
for row in manifest["members"]:
    data = (root / safe(row["path"])).read_bytes()
    assert info(data) == {key: row[key] for key in ("bytes", "sha256", "git_blob")}

attempts = (
    ("initial", 43020198388, 130521184483, "8ead9735ecd78721f306f03e49dbd57894a474d0",
     1940015, "a06ec21789566209edfd3c798efd3f35a16be2990a3c5e2ad1bde2067013faee", 36, 29),
    ("revision2", 43020939762, 130523679401, "d03aa4c87d4f9fe9c1f99fbe319f829d9eef6158",
     2278345, "8bbc8c00b0c9a25aeac964d8486a065c6557e9aab9d819cbb21f1ddd213fbb95", 52, 44),
)
all_records = {}
for label, run_id, job_id, harness, length, digest, zip_count, tar_count in attempts:
    folder = root / label
    raw = (folder / f"job-{job_id}-decoded.log").read_bytes()
    run = json.loads((folder / "RUN_FINAL.json").read_bytes())
    jobs = json.loads((folder / "JOBS_FINAL.json").read_bytes())
    assert (run["id"], run["head_sha"], run["run_attempt"]) == (run_id, harness, 1)
    assert len(jobs["jobs"]) == 1 and jobs["jobs"][0]["id"] == job_id
    assert run["conclusion"] == jobs["jobs"][0]["conclusion"] == ("failure" if label == "initial" else "success")
    blob = (folder / f"mem8-bazel-lock-v5-{run_id}-1.zip").read_bytes()
    assert len(blob) == length and hashlib.sha256(blob).hexdigest() == digest
    expected = {row["path"]: row for row in json.loads((folder / "ZIP_MEMBERS.json").read_bytes())}
    with zipfile.ZipFile(io.BytesIO(blob)) as bundle:
        members = bundle.infolist()
        assert len(members) == len({m.filename for m in members}) == zip_count
        for member in members:
            safe(member.filename)
            assert not member.is_dir()
            data = bundle.read(member)
            row = expected[member.filename]
            assert len(data) == row["bytes"] and hashlib.sha256(data).hexdigest() == row["sha256"]
        tar_bytes = bundle.read("mem8-bazel-lock-v5/mem8-bazel-lock-v5-records.tar.xz")
        tar_info = json.loads(bundle.read("mem8-bazel-lock-v5/ARCHIVE_INFO.json"))
    assert info(tar_bytes) == {key: tar_info[key] for key in ("bytes", "sha256", "git_blob")}
    records = {}
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:xz") as bundle:
        members = bundle.getmembers()
        assert len(members) == len({m.name for m in members}) == tar_count
        for member in members:
            safe(member.name)
            assert member.isfile()
            records[member.name] = bundle.extractfile(member).read()
    member_manifest = json.loads(records["FILE_MANIFEST.json"])
    assert len(member_manifest["members"]) + 1 == tar_count
    for row in member_manifest["members"]:
        assert info(records[row["path"]]) == {key: row[key] for key in ("bytes", "sha256", "git_blob")}
    result = json.loads(records["RESULT.json"])
    echoed = [json.loads(line.split("Z ", 1)[1]) for line in raw.decode().splitlines()
              if 'Z {"schema": "hepta.mem8.bazel-lock-ci.v5"' in line]
    assert echoed == [result]
    assert result["source_before"] == {"head": HEAD, "tree": TREE, "status": ""}
    assert result["native_project_tests_executed"] == result["model_requests_executed"] == result["automatic_retries"] == 0
    assert result["lock_command_budget_seconds"] == 1200 and result["maximum_lock_command_phases"] == 1
    assert merkle(records["SOURCE_TREE.ls-tree"]) == TREE
    assert merkle(records["BASE_TREE.ls-tree"]) == "12159640adcf073b51f3837e75575e11f5c20233"
    assert info(records["hepta_ci_exec.py"])["git_blob"] == "c9434b3a4afb31f80e323d543936386a2fa738de"
    all_records[label] = records

first = all_records["initial"]
failed = json.loads(first["RESULT.json"])
assert failed["status"] == "failed" and failed["lock_command_phases_started"] == 0
assert "source_after" not in failed and "lock-generate.json" not in first
version = json.loads(first["bazel-version.json"])
assert version["exit_code"] == 0 and version["timed_out"] is False
assert info(first["bazel-version.raw.log"])["sha256"] == "70b6e531ac335269d7bedf2b85c21a1328ad74eac8e7a53af047221d983ee276"
assert first["bazel-version.raw.log"].strip() != b"bazel 9.3.0"
assert first["bazel-version.raw.log"].endswith(b"bazel 9.3.0\n")
assert "Bazel version differs" in failed["failure"]

second = all_records["revision2"]
passed = json.loads(second["RESULT.json"])
receipt = json.loads(second["lock-generate.json"])
assert passed["status"] == "passed_exact_source_bazel_lock_only" and passed["failure"] is None
assert passed["lock_command_phases_started"] == 1
assert passed["source_before"] == passed["source_after"]
assert passed["changed_paths"] == [] and passed["lock_changed"] is False
assert passed["phase_receipt"] == receipt
assert receipt["before"] == receipt["after"] and receipt["before"]["dirty"] is False
assert receipt["source_sha"] == receipt["tested_sha"] == HEAD and receipt["lane"] == "source-head"
assert receipt["status"] == "passed" and receipt["command_exit_code"] == receipt["exit_code"] == passed["wrapper_exit_code"] == 0
assert receipt["command"] == ["/home/runner/.cargo/bin/just", "bazel-lock-update"]
assert receipt["run_id"] == "43020939762" and receipt["run_attempt"] == "1"
assert receipt["minimum_tests"] == receipt["observed_passed_tests"] == receipt["observed_failed_tests"] == 0
assert not receipt["timed_out"] and not receipt["output_limit_exceeded"] and receipt["elapsed_seconds"] < 1200
raw = second[receipt["log_file"]]
assert len(raw) == receipt["log_bytes"] == 3211
assert hashlib.sha256(raw).hexdigest() == receipt["log_sha256"] == "dbb76ccdc397772c18d75bb2d744ebf51d1787d386be4f71127248c5a3d50504"
assert b"bazel mod deps --lockfile_mode=update" in raw
assert second["source-after.patch"] == second["source-after-status.txt"] == b""
assert json.loads(second["TOOLS_BEFORE.json"]) == json.loads(second["TOOLS_AFTER.json"])
assert json.loads(second["OWNED_BAZELISK_BINARY_INVENTORY.json"])["files"] == json.loads(second["OWNED_BAZELISK_BINARY_INVENTORY_AFTER.json"])["files"]
locks = json.loads(second["locks-before.json"])
assert locks == json.loads(second["locks-after.json"])
for row in locks:
    assert second["locks-before/" + row["path"]] == second["locks-after/" + row["path"]]
    assert info(second["locks-after/" + row["path"]]) == {key: row[key] for key in ("bytes", "sha256", "git_blob")}
assert second["bazel-version.raw.log"].strip() == b"bazel 9.3.0"
version = json.loads(second["bazel-version.json"])
assert info(second[version["stderr"]["file"]]) == {key: version["stderr"][key] for key in ("bytes", "sha256", "git_blob")}
assert info(second["DRIVER.py"])["sha256"] == "08da7b6f91f57932359f2c6937abc24f6f5f21bfc14a321c4053d7af200ed323"
print(json.dumps({
    "status": "PASS_ORIGINAL_BAZEL_FAILURE_AND_REVISION2_LOCK_EVIDENCE",
    "initial_run": 43020198388, "initial_lock_phases": 0,
    "revision2_run": 43020939762, "revision2_lock_phases": 1,
    "source_head": HEAD, "source_tree": TREE, "source_before_after_clean": True,
    "two_locks_unchanged": True, "all_tools_and_actual_bazel_bytes_unchanged": True,
    "original_zip_members": [36, 52], "original_tar_members": [29, 44],
    "native_tests_or_model_calls_by_original_gates_or_this_verifier": 0,
}, indent=2))
