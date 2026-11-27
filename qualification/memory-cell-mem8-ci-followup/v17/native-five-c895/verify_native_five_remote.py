"""Reconstruct original remote bytes and run only the reviewed offline auditor."""
from pathlib import Path, PurePosixPath
import base64
import hashlib
import io
import json
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parent
WORK = ROOT.parent
rows = json.loads((ROOT / "NATIVE_FIVE_STAGE_OBJECTS.json").read_text())
prefix = "qualification/memory-cell-mem8-ci-followup/v17/"
for row in rows:
    p = ROOT / "native-five-remote" / row["path"][len(prefix):]
    data = base64.b64decode(Path(str(p) + ".b64").read_text().strip(), validate=True) if row["binary"] else p.read_bytes()
    assert data == Path(row["local"]).read_bytes()
    assert len(data) == row["bytes"] and hashlib.sha256(data).hexdigest() == row["sha256"]
    assert hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == row["git_blob"]
    if row["binary"]:
        p.write_bytes(data)

packet = ROOT / "native-five-remote/native-five-c895"
archive = packet / "FIVE_NATIVE_ORIGINAL_COMPLETE.tar.xz"
manifest = json.loads((packet / "MEMBER_MANIFEST.json").read_text())
extracted = packet / "root-extracted"
assert not extracted.exists()
with tarfile.open(archive, "r:xz") as t:
    members = t.getmembers()
    assert len(members) == len({m.name for m in members}) == len(manifest) == 17
    assert {m.name for m in members} == {r["path"] for r in manifest}
    indexed = {r["path"]: r for r in manifest}
    for m in members:
        name = PurePosixPath(m.name)
        assert m.isfile() and not name.is_absolute() and ".." not in name.parts and "\\" not in m.name
        data = t.extractfile(m).read()
        r = indexed[m.name]
        assert len(data) == r["bytes"] and hashlib.sha256(data).hexdigest() == r["sha256"]
        assert hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == r["git_blob"]
        p = extracted / m.name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

prior = WORK / "mem8-ci-followup-v16/native-five-preparation/NATIVE_FIVE_PREPARATION_V2_REMOTE.tar.xz"
raw = prior.read_bytes()
assert len(raw) == 815008 and hashlib.sha256(raw).hexdigest() == "41e4fd36bd7d1af83d5e9cc3a4dea389bb37dd5871c8b3f6bf9290017e4c5d58"
bindings = []
with tarfile.open(fileobj=io.BytesIO(raw), mode="r:xz") as t:
    for tail in [".github/fixtures/mem-native-five-plan.json", ".github/scripts/mem_native_five.py", ".github/scripts/mem_native_five_support.py", ".github/workflows/hepta-mem-native-five.yml"]:
        name = "mem-five-native-harness-preparation/rendered-c895405/" + tail
        m = t.getmember(name)
        assert m.isfile()
        data = t.extractfile(m).read()
        p = packet / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        bindings.append({"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})

out = packet / "root-auditor-output"
command = [sys.executable, str(extracted / "audit_original.py"), "--zip", str(extracted / "ORIGINAL_ARTIFACT.zip"), "--output", str(out)]
result = subprocess.run(command, capture_output=True, check=True)
assert result.stderr == b""
actual = json.loads((out / "INDEPENDENT_AUDIT.json").read_bytes())
expected = json.loads((extracted / "readback/INDEPENDENT_AUDIT.json").read_bytes())
actual_time = actual.pop("observed_at")
expected_time = expected.pop("observed_at")
assert actual == expected
assert actual["observed_status_counts"] == {"PASS": 5}
assert len(actual["independently_qualified_native_cases"]) == 5
assert actual["clean_scoped_fix_packages"] == ["core_test_support"]
assert actual["qualification"] == "NOT_QUALIFIED_RETAIN_ORIGINAL_FAILURE_OR_UNKNOWN"
assert (out / "ZIP_MEMBER_AUDIT.json").read_bytes() == (extracted / "readback/ZIP_MEMBER_AUDIT.json").read_bytes()
proof = {"schema": "mem8.v17.native-five-root-remote-replay.v1", "ref": "6fdb3191bbba93b2211d3b4f2d2bc1b5b4719a44", "full_remote_objects_equal": len(rows), "outer_archive_members_verified": 17, "original_zip_members_verified": 353, "original_manifest_members": 352, "unchanged_original_auditor_exit": 0, "whole_result_equal_except_observer_time": True, "observed_at_original": expected_time, "observed_at_root": actual_time, "prior_v16_full_remote_archive_reused": {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "exact_four_bindings": bindings}, "named_native_cases_passed": 5, "native_failures": 0, "native_leaks": 0, "clean_scoped_fix_packages": actual["clean_scoped_fix_packages"], "whole_qualification": actual["qualification"], "unsettled_core_fix_exit": "UNKNOWN", "windows_sandbox_fix": "NOT_RUN", "new_native_or_model_executions": 0}
(ROOT / "ROOT_NATIVE_FIVE_REMOTE_REPLAY.json").write_text(json.dumps(proof, indent=2) + "\n")
print(json.dumps(proof, indent=2))
