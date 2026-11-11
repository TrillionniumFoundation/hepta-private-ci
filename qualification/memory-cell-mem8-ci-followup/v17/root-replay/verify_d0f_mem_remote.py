"""Reconstruct and audit the complete original d0f MEM packet from remote bytes."""
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parent
REMOTE = ROOT / "d0f-mem-remote"


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def main():
    rows = json.loads((ROOT / "D0F_MEM_STAGE_OBJECTS.json").read_bytes())
    checked = []
    for row in rows:
        relative = row["path"].split("/v17/", 1)[1]
        file = REMOTE / relative
        raw = base64.b64decode(Path(str(file) + ".b64").read_text().strip(), validate=True) if row["binary"] else file.read_bytes()
        assert pin(raw) == {k: row[k] for k in ("bytes", "sha256", "git_blob")}
        assert raw == Path(row["local"]).read_bytes()
        if row["binary"]:
            file.write_bytes(raw)
        checked.append({"path": row["path"], **pin(raw), "full_remote_bytes_equal": True})
    p = REMOTE / "mem-d0f"
    publication = json.loads((p / "ACTUAL_PUBLICATION.json").read_bytes())
    data = b""
    for part in publication["parts"]:
        assert part["offset"] == len(data)
        raw = (p / part["path"]).read_bytes()
        assert pin(raw) == {k: part[k] for k in ("bytes", "sha256", "git_blob")}
        data += raw
    assert pin(data) == {k: publication["archive"][k] for k in ("bytes", "sha256", "git_blob")}
    archive = p / "ROOT_RECONSTRUCTED.tar.xz"
    assert not archive.exists()
    archive.write_bytes(data)
    objects = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:xz") as packed:
        members = packed.getmembers()
        assert len(members) == len({m.name for m in members}) == 31
        for member in members:
            name = PurePosixPath(member.name)
            assert member.isfile() and not name.is_absolute() and ".." not in name.parts
            assert "\\" not in member.name and str(name) == member.name
            objects[member.name] = packed.extractfile(member).read()
    manifest = json.loads((p / "PACKAGE_MANIFEST.json").read_bytes())
    assert objects["PACKAGE_MANIFEST.json"] == (p / "PACKAGE_MANIFEST.json").read_bytes()
    assert len(manifest["files"]) == 30
    assert {r["path"] for r in manifest["files"]} | {"PACKAGE_MANIFEST.json"} == set(objects)
    for row in manifest["files"]:
        assert pin(objects[row["path"]]) == {k: row[k] for k in ("bytes", "sha256", "git_blob")}
    out = p / "root-extracted"
    assert not out.exists()
    for name, raw in objects.items():
        file = out / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(raw)
    original_api = json.loads((p / "ROOT_ORIGINAL_API.json").read_bytes())
    original_jobs = json.loads(json.loads(objects["MEM_JOBS_TERMINAL.json"])["structuredContent"]["content"])["jobs"]
    actual_jobs = {j["id"]: j for j in original_api["jobs"]["jobs"]}
    assert {j["id"] for j in original_jobs} == set(actual_jobs)
    for job in original_jobs:
        for key in ("id", "name", "run_id", "run_attempt", "head_sha", "status", "conclusion", "started_at", "completed_at", "steps"):
            assert job[key] == actual_jobs[job["id"]][key], (job["id"], key)
    actual_artifacts = {a["id"]: a for a in original_api["artifacts"]["artifacts"]}
    assert set(actual_artifacts) == {13874211716, 13873374531, 13874919829}
    for aid, actual in actual_artifacts.items():
        original = json.loads(objects[f"artifacts/{aid}/MANIFEST.json"])["artifact"]
        for key in ("id", "name", "size_in_bytes", "digest", "workflow_run"):
            assert original[key] == actual[key], (aid, key)
    replay = subprocess.run([sys.executable, str(p / "verify_mem_package.py"), str(archive)], capture_output=True)
    assert replay.returncode == 0 and replay.stderr == b"", (replay.returncode, replay.stderr)
    assert replay.stdout == (p / "OFFLINE_PACKAGE_REPLAY.json").read_bytes()
    (p / "ROOT_REMOTE_OFFLINE_REPLAY.json").write_bytes(replay.stdout)
    junit = subprocess.run([sys.executable, str(p / "audit_mem_junit_crossbinding.py"), str(out / "artifacts/13874919829/original.zip")], capture_output=True)
    assert junit.returncode == 0 and junit.stderr == b"", (junit.returncode, junit.stderr)
    assert junit.stdout == (p / "MEM_JUNIT_CROSSBINDING_ADDENDUM.json").read_bytes()
    (p / "ROOT_JUNIT_OFFLINE_REPLAY.json").write_bytes(junit.stdout)
    proof = {"schema": "mem8.v17.d0f-mem-root-remote-replay.v1", "immutable_commit": "1eee8836f06b53e185c7dbb1f135ea64001144ba", "objects": checked, "archive": pin(data), "complete_package_members": 31, "unchanged_reader_exit": 0, "full_original_result_bytes_equal": True, "root_actual_API_jobs_steps_and_artifacts_equal": True, "result": json.loads(replay.stdout), "junit_addendum_result_bytes_equal": True, "new_native_or_model_executions": 0}
    (ROOT / "ROOT_D0F_MEM_REMOTE_REPLAY.json").write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps({"status": "PASS_COMPLETE_REMOTE_MEM_ORIGINAL_AND_JUNIT_BINDINGS", "objects": len(checked), "archive_members": 31, "python": proof["result"]["python"], "native": proof["result"]["native"]}, indent=2))


if __name__ == "__main__":
    main()
