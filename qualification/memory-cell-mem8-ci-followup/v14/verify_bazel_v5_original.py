#!/usr/bin/env python3
"""Audit the actual V5 module-lock operation and its original complete artifact."""
import datetime
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parent
P = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT.parent / "mem8-bazel-ci-v5-revision2-original-run"
SOURCE = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else ROOT.parent / "mem8-source-ci-v5-original-run/records"
assert len(sys.argv) <= 3

def sha(b):
    return hashlib.sha256(b).hexdigest()

def blob(b):
    return hashlib.sha1(b"blob " + str(len(b)).encode() + b"\0" + b).hexdigest()

def safe(n):
    return bool(n) and not PurePosixPath(n).is_absolute() and ".." not in PurePosixPath(n).parts and "\\" not in n

def check(b, r):
    assert len(b) == r["bytes"] and sha(b) == r["sha256"] and blob(b) == r["git_blob"]

zraw = (P / "mem8-bazel-lock-v5-43020939762-1.zip").read_bytes()
assert len(zraw) == 2278345 and sha(zraw) == "8bbc8c00b0c9a25aeac964d8486a065c6557e9aab9d819cbb21f1ddd213fbb95"
with zipfile.ZipFile(io.BytesIO(zraw)) as z:
    assert z.testzip() is None and len(z.namelist()) == len(set(z.namelist())) == 52
    assert all(safe(n) and not n.endswith("/") for n in z.namelist())
    for n in z.namelist():
        assert z.read(n) == (P / "artifact" / n).read_bytes()
    archive_name = "mem8-bazel-lock-v5/mem8-bazel-lock-v5-records.tar.xz"
    raw = z.read(archive_name)
assert len(raw) == 659176 and sha(raw) == "d8b5413e20d2a316d2038a4a178e8fc79e4285b4059954eddd7159144b19a883"
with tarfile.open(fileobj=io.BytesIO(raw), mode="r:xz") as t:
    members = t.getmembers()
    assert len(members) == len({m.name for m in members}) == 44
    assert all(m.isfile() and safe(m.name) for m in members)
    data = {m.name: t.extractfile(m).read() for m in members}
manifest = json.loads(data["FILE_MANIFEST.json"])["members"]
assert len(manifest) == 43
assert set(data) == {r["path"] for r in manifest} | {"FILE_MANIFEST.json"}
archive_only = []
for row in manifest:
    check(data[row["path"]], row)
    scattered = P / "artifact/mem8-bazel-lock-v5/records" / row["path"]
    if scattered.exists():
        assert data[row["path"]] == scattered.read_bytes()
    else:
        archive_only.append(row["path"])
assert set(archive_only) == {"source-config/.bazelrc", "source-config/.bazelversion"}
assert sha(data["DRIVER.py"]) == "08da7b6f91f57932359f2c6937abc24f6f5f21bfc14a321c4053d7af200ed323"
assert blob(data["hepta_ci_exec.py"]) == "c9434b3a4afb31f80e323d543936386a2fa738de"
assert data["SOURCE_TREE.ls-tree"] == (SOURCE / "CANDIDATE_TREE.ls-tree").read_bytes()
assert data["BASE_TREE.ls-tree"] == (SOURCE / "BASE_TREE.ls-tree").read_bytes()
source_blobs = {}
for row in data["SOURCE_TREE.ls-tree"].split(b"\0"):
    if row:
        attrs, path = row.split(b"\t", 1)
        source_blobs[path.decode()] = attrs.decode().split()[2]
for name in [".bazelrc", ".bazelversion", "justfile", "MODULE.bazel"]:
    assert blob(data["source-config/" + name]) == source_blobs[name]
result = json.loads(data["RESULT.json"])
receipt = json.loads(data["lock-generate.json"])
assert result["phase_receipt"] == receipt
assert result["status"] == "passed_exact_source_bazel_lock_only" and result["failure"] is None
identity = {"head": "9bd2f589debdba4a93baa363817c3669cb103721", "tree": "c77785ecb368c44ea699769001a47402c9f50591", "status": ""}
assert result["source_before"] == result["source_after"] == identity
assert receipt["before"] == receipt["after"] and not receipt["after"]["dirty"]
assert receipt["source_sha"] == receipt["tested_sha"] == receipt["after"]["commit"] == identity["head"]
assert receipt["after"]["tree"] == identity["tree"] and receipt["lane"] == "source-head"
assert result["lock_command_phases_started"] == result["maximum_lock_command_phases"] == 1
assert result["lock_command_budget_seconds"] == 1200 and result["automatic_retries"] == 0
assert receipt["command"] == ["/home/runner/.cargo/bin/just", "bazel-lock-update"]
assert receipt["run_id"] == "43020939762" and receipt["run_attempt"] == "1"
assert receipt["returncode"] == receipt["command_exit_code"] == receipt["exit_code"] == 0
assert receipt["status"] == "passed" and not receipt["timed_out"] and not receipt["output_limit_exceeded"]
assert receipt["observed_passed_tests"] == receipt["observed_failed_tests"] == 0
assert 0 < receipt["elapsed_seconds"] < 1200
log = data[receipt["log_file"]]
assert len(log) == receipt["log_bytes"] == 3211 and sha(log) == receipt["log_sha256"] == "dbb76ccdc397772c18d75bb2d744ebf51d1787d386be4f71127248c5a3d50504"
assert b"bazel mod deps --lockfile_mode=update" in log and b"06adadd2-2e89-495f-b534-007c92f53108" in log
assert data["source-after.patch"] == data["source-after-status.txt"] == b""
assert not result["changed_paths"] and not result["lock_changed"]
locks_before, locks_after = [json.loads(data[n]) for n in ["locks-before.json", "locks-after.json"]]
assert locks_before == locks_after and len(locks_before) == 2
for r in locks_before:
    assert data["locks-before/" + r["path"]] == data["locks-after/" + r["path"]]
    check(data["locks-before/" + r["path"]], r)
assert json.loads(data["TOOLS_BEFORE.json"]) == json.loads(data["TOOLS_AFTER.json"])
inventory = json.loads(data["OWNED_BAZELISK_BINARY_INVENTORY.json"])["files"]
assert inventory == json.loads(data["OWNED_BAZELISK_BINARY_INVENTORY_AFTER.json"])["files"] and len(inventory) == 1
assert inventory[0]["sha256"] == "d302d22ed77ee5658b87857249baa579db84300ecebe0a1e9a357b5b20f80eb8"
version = json.loads(data["bazel-version.json"])
assert data["bazel-version.raw.log"].strip() == b"bazel 9.3.0"
check(data["bazel-version.raw.log"], version)
check(data[version["stderr"]["file"]], version["stderr"])
assert version["exit_code"] == 0 and version["timed_out"] is False
assert result["model_requests_executed"] == result["native_project_tests_executed"] == 0
raw_job = (P / "job-130523679401-decoded.log").read_bytes()
assert len(raw_job) == 93173 and sha(raw_job) == "895f14d3e81a7a85d9e82dd622c48032d03915c63d2d6a534b9713ce262f1eef"
report = {"schema": "hepta.mem8.bazel-v5.root-original-audit.v1", "verified_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "run_id": 43020939762, "job_id": 130523679401, "attempt": 1, "workflow_head": "d03aa4c87d4f9fe9c1f99fbe319f829d9eef6158", "source_head": identity["head"], "source_tree": identity["tree"], "source_before_after_clean_and_equal": True, "all_source_tree_entries_equal_prior_root_verified_formatter_tree": True, "zip_bytes": len(zraw), "zip_sha256": sha(zraw), "all_zip_members_verified": 52, "records_archive_bytes": len(raw), "records_archive_sha256": sha(raw), "all_archive_members_verified": 44, "actual_lock_command_phases": 1, "original_budget_seconds": 1200, "command_elapsed_seconds": receipt["elapsed_seconds"], "command_started_at": receipt["started_at"], "command_finished_at": receipt["finished_at"], "actual_invocation": "06adadd2-2e89-495f-b534-007c92f53108", "raw_command_log_sha256": sha(log), "both_lock_files_byte_identical_before_after": locks_before, "tool_before_after_recorded_identities_equal": True, "actual_bazel_binary_recorded_sha256": inventory[0]["sha256"], "version_stdout_and_download_stderr_retained_separately": True, "warnings_retained": "Original module direct-dependency and crate-annotation warnings are preserved; no check_direct_dependencies or annotation change was made.", "native_project_tests": 0, "model_requests": 0, "status": "PASS_EXACT_SOURCE_BAZEL_MODULE_LOCK", "limits": ["Module resolution and lock consistency do not compile Rust or qualify native runtime behavior.", "The first run's version-probe failure with zero lock-command phases remains an original failure."]}
(ROOT / "ROOT_BAZEL_V5_AUDIT.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
