#!/usr/bin/env python3
"""Reassemble and verify both full original CI archives from immutable Git parts."""
import base64
import datetime
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parent

def sha(b):
    return hashlib.sha256(b).hexdigest()

def blob(b):
    return hashlib.sha1(b"blob " + str(len(b)).encode() + b"\0" + b).hexdigest()

def safe(n):
    return bool(n) and not PurePosixPath(n).is_absolute() and ".." not in PurePosixPath(n).parts and "\\" not in n

def check(b, r):
    assert len(b) == r["bytes"] and sha(b) == r["sha256"] and blob(b) == r["git_blob"]

def untar(raw, count, manifest_name):
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:xz") as t:
        members = t.getmembers()
        assert len(members) == len({m.name for m in members}) == count
        assert all(m.isfile() and safe(m.name) for m in members)
        data = {m.name: t.extractfile(m).read() for m in members}
    manifest = json.loads(data[manifest_name])
    assert set(data) == {r["path"] for r in manifest["members"]} | {manifest_name}
    for r in manifest["members"]:
        check(data[r["path"]], r)
    return data

reports = []
for sub, outer_count, expected_sha in [
    ("source-ci-v5", 21, "b536abac7cba1182f102b3374a55aa83904f89cf9bafbd46bf3d00ab87d6e378"),
    ("bazel-ci-v5", 19, "64c8a448e02fe6011d7f7fca128751aa86e510ac54d7d9f70e3a4a4adfe07b8d"),
]:
    p = ROOT / sub
    publication = json.loads((p / "PUBLICATION.json").read_text())
    chunks = []
    for n, row in enumerate(publication["parts"], 1):
        wrapper = p / f"PART_READBACK_{n}.json"
        if wrapper.exists():
            response = json.loads(wrapper.read_text())
            assert response["encoding"] == "base64" and response["sha"] == row["git_blob"]
            raw = base64.b64decode("".join(response["content"].splitlines()), validate=True)
        else:
            assert safe(row["path"])
            raw = (p / row["path"]).read_bytes()
        check(raw, row)
        assert row["offset"] == sum(map(len, chunks))
        chunks.append(raw)
    raw = b"".join(chunks)
    check(raw, publication["archive"])
    assert sha(raw) == expected_sha
    data = untar(raw, outer_count, "MANIFEST.json")
    assert data["MANIFEST.json"] == (p / "MANIFEST.json").read_bytes()
    zip_reports = []
    if sub == "source-ci-v5":
        expected = [("original/mem8-source-gates-v5-43015979473-1.zip", 337, 335, "mem8-source-gates-v5/mem8-source-gates-v5-records.tar.xz", "6ecc9f1ab22fcaccbf52f0190c9af0e8edef759a0537dbb8f751b227d09b7c80")]
    else:
        expected = [
            ("initial/mem8-bazel-lock-v5-43020198388-1.zip", 36, 29, "mem8-bazel-lock-v5/mem8-bazel-lock-v5-records.tar.xz", None),
            ("revision2/mem8-bazel-lock-v5-43020939762-1.zip", 52, 44, "mem8-bazel-lock-v5/mem8-bazel-lock-v5-records.tar.xz", "8bbc8c00b0c9a25aeac964d8486a065c6557e9aab9d819cbb21f1ddd213fbb95"),
        ]
    assert {n for n in data if n.endswith(".zip")} == {r[0] for r in expected}
    for name, zip_count, tar_count, records_name, expected_zip_sha in expected:
        zraw = data[name]
        if expected_zip_sha:
            assert sha(zraw) == expected_zip_sha
        with zipfile.ZipFile(io.BytesIO(zraw)) as z:
            assert z.testzip() is None
            assert len(z.namelist()) == len(set(z.namelist())) == zip_count
            assert all(safe(n) and not n.endswith("/") for n in z.namelist())
            for entry in z.infolist():
                assert ((entry.external_attr >> 16) & 0o170000) != 0o120000
                z.read(entry)
            inner_raw = z.read(records_name)
        original = untar(inner_raw, tar_count, "FILE_MANIFEST.json")
        result = json.loads(original["RESULT.json"])
        if sub == "source-ci-v5":
            assert sha(inner_raw) == "6718333beb6ea7b6faefc2bd026413e8ab1413f24bf4f377a773fc0264dd288a"
            assert result["status"] == "passed_source_gates_only_review_remaining"
            assert result["initial_commit"] == "c842e995b047eb2ee7d81c073f14fb2fcaa6bff2"
            assert result["candidate_tree"] == "c77785ecb368c44ea699769001a47402c9f50591"
            assert len(json.loads(original["FORMATTED_CAPSULE.json"])["files"]) == 103
        elif name.startswith("initial/"):
            assert result["status"] == "failed" and result["lock_command_phases_started"] == 0
            assert "source_after" not in result and "Bazel version differs" in result["failure"]
            probe = json.loads(original["bazel-version.json"])
            check(original["bazel-version.raw.log"], probe)
            assert probe["exit_code"] == 0 and probe["timed_out"] is False
            assert len(original["bazel-version.raw.log"]) == 115
        else:
            assert sha(inner_raw) == "d8b5413e20d2a316d2038a4a178e8fc79e4285b4059954eddd7159144b19a883"
            assert result["status"] == "passed_exact_source_bazel_lock_only" and result["lock_command_phases_started"] == 1
            assert result["source_before"] == result["source_after"] == {"head": "9bd2f589debdba4a93baa363817c3669cb103721", "tree": "c77785ecb368c44ea699769001a47402c9f50591", "status": ""}
            phase = json.loads(original["lock-generate.json"])
            assert sha(original[phase["log_file"]]) == "dbb76ccdc397772c18d75bb2d744ebf51d1787d386be4f71127248c5a3d50504"
        zip_reports.append({"path": name, "zip_bytes": len(zraw), "zip_sha256": sha(zraw), "zip_members_crc_read": zip_count, "records_tar_bytes": len(inner_raw), "records_tar_sha256": sha(inner_raw), "records_tar_manifest_members_verified": tar_count, "original_result": result["status"]})
    if sub == "source-ci-v5":
        first = json.loads(data["first-zero-job/RUN.json"])
        first_jobs = json.loads(data["first-zero-job/JOBS.json"])
        assert first["id"] == 43015488785 and first["conclusion"] == "failure"
        assert first_jobs["total_count"] == 0 and first_jobs["jobs"] == []
    reports.append({"directory": sub, "full_remote_binary_parts": len(chunks), "archive_bytes": len(raw), "archive_sha256": sha(raw), "whole_archive_git_blob_computed": blob(raw), "whole_archive_blob_actual_create_claimed": False, "outer_regular_members_verified": outer_count, "complete_original_zips": zip_reports})
report = {"schema": "hepta.mem8.v14.root-full-ci-archive-readback.v1", "verified_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "source_carrier_commit": "fe190abfe2c6aef6ef02464dd085b8627386d614", "bazel_carrier_commit": "7a0d5f54f693fb8ca9fd9ad82c4a0ddec0c08999", "archives": reports, "all_18_binary_parts_fully_fetched_and_reassembled": True, "archive_supplied_code_executed": False, "new_native_or_model_calls": 0, "status": "ALL_FULL_ORIGINAL_CI_ARCHIVES_VERIFIED", "qualification_scope": "Only the explicitly verified original source gates and module-lock operation. Historical failures and new native CI remain separate."}
(ROOT / "ROOT_FULL_CI_ARCHIVES_READBACK_AUDIT.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
