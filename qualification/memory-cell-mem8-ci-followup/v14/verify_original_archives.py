#!/usr/bin/env python3
"""Verify immutable Git readbacks without executing any archive-supplied code."""
import base64
import collections
import datetime
import hashlib
import io
import json
import lzma
from pathlib import Path, PurePosixPath
import re
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parent
READ = ROOT / "root-readback"
ARCHIVE_NAMES = [
    "mem8-fence189-pinned-review-v1",
    "mem8-fourcell189-diagnostic-candidate-v1",
    "mem8-integrated189-terminal-addendum-v1",
    "mem8-windows-current189-original-v2",
]
PINS = [
    ("011065e84a2b2445091a737586ddee2f96a4a288", 117756, "b03d7a0f09260996d531dc30f434db0d1a24e5e95abfd31aa50878462c72cbd7", "a97b205237fd96f11a95cafbda2ce27d65f7712d"),
    ("71aa28f1d53f93cf51659fc8d85eaf89b6b30dbc", 46460, "7d534c36b9adf1769860e77cace991c61183b78249cb361f4c21976b3e61a7ab", "a98b1357e8d0fc4bddbdb0324a62d826c47ba7b9"),
    ("376d21c2cc451042c74b9a3dad2c634e9810373a", 393468, "0dd01818941749570916d787488428aa3fc8bb8400674b2f388577638c1f5390", "7836ab21bcaa1df614e2e0baca89b0df9d45efef"),
    ("3b8b74cc2ee0fd2810718d2005b7a12f66bc72fd", 235016, "266fd121e2aca469e4ba9343a7db5594d58afffaae6f0c20af54f35ec6781c1d", "f281fb48116cbd976e19035f8aed5a804a7729d5"),
]

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def git_blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()

def check_row(raw, row):
    assert len(raw) == row["bytes"], row
    assert sha(raw) == row["sha256"], row
    if "git_blob" in row:
        assert git_blob(raw) == row["git_blob"], row

def safe_name(name):
    p = PurePosixPath(name)
    return bool(name) and not p.is_absolute() and ".." not in p.parts and "\\" not in name

def read_archive(i):
    expected_blob, expected_size, expected_sha, expected_manifest = PINS[i]
    wrapper_path = READ / f"original-archive-{i}.json"
    if wrapper_path.exists():
        a = json.loads(wrapper_path.read_text())["structuredContent"]
        m = json.loads((READ / f"original-manifest-{i}.json").read_text())["structuredContent"]
        assert a["encoding"] == "base64" and m["encoding"] == "utf-8"
        raw = base64.b64decode("".join(a["content"].splitlines()), validate=True)
        manifest_bytes = m["content"].encode()
        assert a["sha"] == expected_blob and m["sha"] == expected_manifest
    else:
        # The committed, immutable files make the verifier usable from a checkout.
        raw = (ROOT / "original-ci" / (ARCHIVE_NAMES[i] + ".tar.xz")).read_bytes()
        manifest_bytes = (ROOT / "original-ci" / (ARCHIVE_NAMES[i] + ".MANIFEST.json")).read_bytes()
    assert git_blob(raw) == expected_blob
    assert len(raw) == expected_size and sha(raw) == expected_sha
    assert git_blob(manifest_bytes) == expected_manifest
    manifest = json.loads(manifest_bytes)
    assert manifest["source_head"] == "189711e3563ea13a5328d52e99a286f082045b98"
    assert manifest["source_tree"] == "e253b99e0a5c3b3a680569da0d224fabff0781ba"
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:xz") as tar:
        members = tar.getmembers()
        names = [x.name for x in members]
        assert len(names) == len(set(names))
        assert all(x.isfile() and safe_name(x.name) for x in members)
        data = {x.name: tar.extractfile(x).read() for x in members}
    rows = manifest["members"]
    assert len(rows) == len({r["path"] for r in rows})
    assert set(data) == {r["path"] for r in rows} | {"MANIFEST.json"}
    assert data["MANIFEST.json"] == manifest_bytes
    for r in rows:
        check_row(data[r["path"]], r)
    return data, {"git_blob": expected_blob, "bytes": len(raw), "sha256": sha(raw), "manifest_git_blob": expected_manifest, "members_verified": len(data)}

archives = []
reports = []
for i in range(4):
    data, report = read_archive(i)
    archives.append(data)
    reports.append(report)

fence = archives[0]
source_index = json.loads(fence["VERIFIED_SOURCE_INDEX.json"])
assert len(source_index) == 13
for r in source_index:
    rec = json.loads(fence["inputs/" + r["record"]])
    assert rec["encoding"] == "utf-8"
    content = rec["content"].encode()
    check_row(content, r)
    assert rec["sha"] == r["git_blob"]
fence_review = json.loads(fence["READ_ONLY_REVIEW.json"])
for name, row in zip(["original-job-attempt1.log", "original-job-attempt2.log"], fence_review["raw_logs"]):
    check_row(fence[name], {"bytes": row["bytes"], "sha256": row["sha256"]})
    assert b"local_control_inventory_unavailable" in fence[name]
bundle = json.loads(fence["BUNDLE_SOURCE_COMPARISON.json"])
assert len(bundle["files"]) == 5
assert all(r["action_pin_blob"] == r["declared_binary_source_blob"] for r in bundle["files"])
assert bundle["binary_artifact_downloaded_or_independently_attested_in_this_review"] is False
reports[0].update({"full_primary_files_verified": 13, "raw_logs_verified": 2, "runtime_qualification": False, "binary_independent_attestation": False})

diag = archives[1]
candidate = json.loads(diag["CANDIDATE_MANIFEST.json"])
capsule = json.loads(diag["SOURCE_CAPSULE.json"])
assert len(candidate["paths"]) == len(capsule["files"]) == 3
assert len(diag["CANDIDATE.patch"]) == candidate["patch_bytes"]
assert sha(diag["CANDIDATE.patch"]) == candidate["patch_sha256"]
capsule_rows = {r["path"]: r for r in capsule["files"]}
for r in candidate["paths"]:
    pre = diag["preimages/" + r["path"]]
    post = diag["source/" + r["path"]]
    assert git_blob(pre) == r["preimage_git_blob"]
    assert git_blob(post) == r["postimage_git_blob"]
    check_row(post, r)
    assert base64.b64decode(capsule_rows[r["path"]]["content_base64"], validate=True) == post
assert candidate["native_tests"] == 0 and candidate["formatted"] is False
reports[1].update({"exact_pre_post_and_capsule_paths": 3, "status": "diagnostic_only_unqualified_candidate"})

terminal = archives[2]
raw_index = json.loads(terminal["RAW_LOG_INDEX.json"])
assert len(raw_index) == 7
raw_logs = {}
for r in raw_index:
    raw = lzma.decompress(terminal[r["archive_path"]])
    assert len(raw) == r["raw_bytes"] and sha(raw) == r["raw_sha256"]
    raw_logs[r["job_id"]] = raw
original = json.loads(terminal["ORIGINAL_ATTEMPT1_SNAPSHOT.json"])["blocking"]
attempt2 = json.loads(terminal["ATTEMPT2_JOBS.json"])
mapping = json.loads(terminal["ATTEMPT2_JOB_MAPPING.json"])
assert original["total_count"] == len(original["jobs"]) == 37
assert attempt2["total_count"] == len(attempt2["jobs"]) == len(mapping) == 37
counts = dict(collections.Counter(j["conclusion"] for j in original["jobs"]))
assert counts == {"success": 23, "failure": 10, "skipped": 4}
original_by_id = {j["id"]: j for j in original["jobs"]}
second_by_id = {j["id"]: j for j in attempt2["jobs"]}
executions = []
for r in mapping:
    before = original_by_id[r["original_attempt1_id"]]
    after = second_by_id[r["attempt2_representative_id"]]
    for field in ["started_at", "completed_at"]:
        assert r["original_" + field] == before[field]
        assert r[field] == after[field]
    assert before["head_sha"] == after["head_sha"] == "189711e3563ea13a5328d52e99a286f082045b98"
    same_times = (before["started_at"], before["completed_at"]) == (after["started_at"], after["completed_at"])
    assert r["same_execution_times"] == same_times
    assert r["skipped"] == (after["conclusion"] == "skipped")
    if not same_times and not r["skipped"]:
        executions.append(after["id"])
assert sorted(executions) == [130483156553, 130483324196]
target_reports = []
for job, failures in [(130461514723, 10), (130461514761, 4)]:
    target = json.loads(terminal[f"job-{job}-FINAL_TARGETS.json"])
    lines = raw_logs[job].decode().splitlines()
    assert len(target["failed_targets"]) == failures
    assert len({r["target"] for r in target["targets"]}) == len(target["targets"])
    for r in target["targets"]:
        line = lines[r["line"] - 1]
        assert r["target"] in line and r["status"] in line and r["tail"] in line
    assert [r for r in target["targets"] if r["status"] != "PASSED"] == target["failed_targets"]
    target_reports.append({"job": job, "final_targets": len(target["targets"]), "nonpassing_targets": failures})
reports[2].update({"raw_logs_verified": 7, "attempt1_jobs": counts, "second_attempt_actual_new_execution_job_ids": executions, "mac_final_target_counts": target_reports})

windows = archives[3]
audit = json.loads(windows["ORIGINAL_AUDIT.json"])
zip_raw = windows["windows-current-13851265558.zip"]
assert len(zip_raw) == 113306 and sha(zip_raw) == "c3518e59dc841accae8380cd13128d30684a4d3b7e368d095051bfb26f4868d5"
with zipfile.ZipFile(io.BytesIO(zip_raw)) as z:
    assert z.testzip() is None
    assert len(z.infolist()) == len(set(z.namelist())) == 22
    assert all(safe_name(n) for n in z.namelist())
    for r in audit["original_artifact"]["members"]:
        raw = z.read(r["name"])
        check_row(raw, r)
        assert raw == windows["artifact/" + r["name"]]
assert lzma.decompress(windows["job-130461336393-decoded.log.xz"]) == windows["job-130461336393-decoded.log"]
check_row(windows["job-130461336393-decoded.log"], {"bytes": 168226, "sha256": "b3d404246a9b5bea5f92504dc9cbad5e79e26a3a751a400b06d559f5afbb11b4"})
for n in ["EXACT_DRIVER_SOURCE.json", "EXACT_SCOPE_SOURCE.json", "EXACT_WORKFLOW_SOURCE.json"]:
    r = json.loads(windows[n])
    assert r["encoding"] == "utf-8" and git_blob(r["content"].encode()) == r["sha"]
groups = json.loads(windows["artifact/groups.json"])
assert len(groups) == 15
observed = []
uuids = []
for g in groups:
    log = windows["artifact/" + g["id"] + ".log"].decode()
    assert len(re.findall(r"^\s*Summary \[", log, re.M)) == 1
    uuid = re.findall(r"Nextest run ID ([0-9a-f-]{36})", log)
    assert len(uuid) == 1
    uuids.extend(uuid)
    before_summary = re.split(r"^\s*Summary \[", log, maxsplit=1, flags=re.M)[0]
    cases = re.findall(r"^\s*(PASS|FAIL|LEAK)\s+\[[^\]]+\]\s+(\S+)\s+(\S+)\s*$", before_summary, re.M)
    assert len(cases) == g["expectedTestCount"] == g["selectedTestCount"]
    assert sorted(c[2] for c in cases) == sorted(g["observedTests"])
    assert all(c[1] == g["package"] for c in cases)
    assert (all(c[0] == "PASS" for c in cases) and g["exitCode"] == 0) == g["passed"]
    observed.extend(cases)
assert len(uuids) == len(set(uuids)) == 15
assert len(observed) == len({(c[1], c[2]) for c in observed}) == 139
statuses = dict(collections.Counter(c[0] for c in observed))
assert statuses == {"PASS": 137, "LEAK": 1, "FAIL": 1} == audit["statuses"]
assert sum(g["passed"] for g in groups) == 13
source_before = json.loads(windows["artifact/source-before.json"])
assert source_before["head"] == "189711e3563ea13a5328d52e99a286f082045b98" and not source_before["trackedChanges"]
assert not any("source-after" in n or "final-aggregate" in n for n in windows)
reports[3].update({"original_zip_members_verified": 22, "full_exact_sources_verified": 3, "completed_groups": 15, "strict_passed_groups": 13, "fresh_run_uuids": 15, "distinct_package_case_terminals": 139, "case_statuses_rederived_from_pre_summary_raw": statuses, "terminal": "cancelled", "source_after": "ABSENT", "failure_classification": "ordinary host four-cell passed; elevated outside deletion and separate output LEAK remain failures"})

report = {"schema": "hepta.mem8.v14.root-original-archive-readback-audit.v1", "verified_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "root_reviewer": "root", "source_of_bytes": "full original Git connector readbacks retained in functions store across local environment reset", "staged_evidence_commit": "7690b8bb148e0923cf808d2e0148f62ec91b054b", "archive_supplied_code_executed": False, "new_native_or_model_executions": 0, "archives": reports, "result": "ALL_FOUR_IMMUTABLE_ARCHIVES_AND_SCOPED_ORIGINAL_COUNTS_VERIFIED", "limits": ["Byte and count verification does not convert original failures, cancellations, missing terminal records, or candidate source changes into passes.", "Fence unavailable observation remains an external runtime dependency; no specific missing input or successful runtime qualification was inferred.", "Diagnostic candidate has no native qualification here.", "Windows current has no source-after or final aggregate; no all-167-case pass is claimed."]}
(ROOT / "ROOT_ORIGINAL_ARCHIVES_READBACK_AUDIT.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
