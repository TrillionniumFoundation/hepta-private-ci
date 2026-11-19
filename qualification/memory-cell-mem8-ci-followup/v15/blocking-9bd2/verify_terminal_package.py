#!/usr/bin/env python3
"""Verify retained blocking CI originals offline; no CI/native/model execution."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile


def identity(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}


def safe(name):
    path = PurePosixPath(name)
    assert name and not path.is_absolute() and ".." not in path.parts and "\\" not in name


root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent
manifest = json.loads((root / "MANIFEST.json").read_bytes())
actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
assert actual == {row["path"] for row in manifest["members"]} | {"MANIFEST.json"}
for row in manifest["members"]:
    safe(row["path"])
    path = root / row["path"]
    assert path.is_file() and not path.is_symlink()
    assert identity(path.read_bytes()) == {key: row[key] for key in ("bytes", "sha256", "git_blob")}
head = "9bd2f589debdba4a93baa363817c3669cb103721"
run = json.loads((root / "RUN_TERMINAL.json").read_bytes())
snapshot = json.loads((root / "JOBS_TERMINAL.json").read_bytes())
jobs = snapshot["payload"]["jobs"]
assert run["id"] == 43021840778 and run["head_sha"] == head
assert run["status"] == "completed" and run["conclusion"] == "failure" and run["run_attempt"] == 1
assert len(jobs) == snapshot["payload"]["total_count"] == 37
assert len({row["id"] for row in jobs}) == 37
counts = {}
for job in jobs:
    assert job["run_id"] == run["id"] and job["head_sha"] == head and job["run_attempt"] == 1
    assert job["status"] == "completed"
    counts[job["conclusion"]] = counts.get(job["conclusion"], 0) + 1
assert counts == {"success": 19, "failure": 9, "cancelled": 5, "skipped": 4}
summary = json.loads((root / "TERMINAL_SUMMARY.json").read_bytes())
assert summary["job_counts"] == counts
mac = next(job for job in jobs if job["id"] == 130526871572)
assert mac["conclusion"] == "failure" and mac["completed_at"] == "2026-11-11T13:58:22Z"
test_step = next(step for step in mac["steps"] if step["name"] == "bazel test //...")
assert test_step["conclusion"] == "failure" and test_step["completed_at"] == "2026-11-11T13:57:09Z"
gap = json.loads((root / "MAC_FULL_RAW_GAP.json").read_bytes())
assert gap["raw_bytes_received"] == 0 and gap["original_job"] == mac["id"]
for name in gap["original_read_failure_files"][:2]:
    error = json.loads((root / name).read_bytes())
    assert error["isError"] is True and "Transport closed" in json.dumps(error)
assert "not an allowed" in (root / gap["original_read_failure_files"][2]).read_text()
assert "Transport closed" in (root / gap["original_read_failure_files"][3]).read_text()

fanin = (root / "CI_REQUIRED_ORIGINAL.log").read_bytes()
fanin_meta = json.loads((root / "CI_REQUIRED_ORIGINAL_META.json").read_bytes())
assert identity(fanin) == {key: fanin_meta[key] for key in ("bytes", "sha256", "git_blob")}
assert fanin_meta["job_id"] == 130567945859
needs_text = fanin.decode().split("  NEEDS: ", 1)[1]
needs, _ = json.JSONDecoder().raw_decode(needs_text)
assert needs["bazel"]["result"] == needs["repo-checks"]["result"] == "abandoned"
assert needs["blob-size-policy"]["result"] == "failure"
assert b"CI gate rejected: invalid or absent CI result: bazel" in fanin

old_info = json.loads((root / "EARLIER_CHECKPOINT_ARCHIVE_INDEX.json").read_bytes())
old_archive = root / old_info["name"]
assert identity(old_archive.read_bytes()) == {
    "bytes": old_info["bytes"], "sha256": old_info["sha256"],
    "git_blob": old_info["git_blob_computed"]}
with tempfile.TemporaryDirectory(prefix="mem9bd2-blocking-original-audit-") as temporary:
    extracted = Path(temporary)
    names = set()
    with tarfile.open(old_archive, "r:xz") as archive:
        for member in archive:
            safe(member.name)
            assert member.isfile() and member.name not in names
            names.add(member.name)
            path = extracted / member.name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.extractfile(member).read())
    assert len(names) == 38
    check = subprocess.run([sys.executable, str(extracted / "verify_blocking_checkpoint.py"), str(extracted)],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    assert check.returncode == 0, check.stderr.decode()
    checkpoint = json.loads((extracted / "CHECKPOINT.json").read_bytes())
    raw_ids = [row["job_id"] for row in checkpoint["complete_raw_logs"]] + [130567945859]
    assert len(raw_ids) == len(set(raw_ids)) == 13
    assert sorted(raw_ids) == sorted(summary["complete_raw_job_ids"])
    for row in checkpoint["complete_raw_logs"]:
        actual_job = next(job for job in jobs if job["id"] == row["job_id"])
        assert actual_job["conclusion"] == row["api_conclusion"]
        assert actual_job["completed_at"] == row["completed_at"]
    assert checkpoint["overall_run_terminal"] is False
    assert checkpoint["source_tree"] == "c77785ecb368c44ea699769001a47402c9f50591"

artifact = json.loads((root / "MAC_ARTIFACT_METADATA.json").read_bytes())
archive_path = root / "MAC_ORIGINAL_EXECUTION_LOGS.zip"
assert artifact["id"] == 13861597870 and artifact["workflow_run"]["id"] == run["id"]
assert artifact["workflow_run"]["head_sha"] == head
binary = archive_path.read_bytes()
assert len(binary) == artifact["size_in_bytes"] == 10562035
assert "sha256:" + hashlib.sha256(binary).hexdigest() == artifact["digest"]
audit = json.loads((root / "MAC_ARTIFACT_DOWNLOAD_AUDIT.json").read_bytes())
with zipfile.ZipFile(archive_path) as archive:
    assert archive.testzip() is None and len(archive.infolist()) == 1
    for member in archive.infolist():
        safe(member.filename)
        assert not member.is_dir() and not stat.S_ISLNK(member.external_attr >> 16)
        row = audit["members"][0]
        assert member.filename == row["path"] and member.CRC == row["crc32"]
        data = archive.read(member)
        assert len(data) == row["bytes"] and hashlib.sha256(data).hexdigest() == row["sha256"]
print(json.dumps({"status": "PASS_ORIGINAL_BLOCKING_TERMINAL_WITH_EXPLICIT_MAC_RAW_GAP",
                  "original_run": run["id"], "source_head": head, "job_counts": counts,
                  "full_decoded_job_logs": 13, "mac_full_job_raw_included": False,
                  "mac_original_execution_artifact_crc_and_bytes_verified": True,
                  "prior_frozen_checkpoint_members": 38,
                  "outer_members": len(actual), "native_commands_executed_by_auditor": 0,
                  "model_calls": 0, "overall_ci_pass": False}, indent=2))
