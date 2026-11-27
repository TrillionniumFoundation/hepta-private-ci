#!/usr/bin/env python3
"""Verify the frozen V6 package and replay its offline evidence audit only."""
import hashlib
import io
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
    return path


root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent
manifest = json.loads((root / "MANIFEST.json").read_bytes())
assert manifest["original_run"] == 43032289667 and manifest["original_job"] == 130562136934
for row in manifest["members"]:
    safe(row["path"])
    path = root / row["path"]
    assert path.is_file() and not path.is_symlink()
    assert identity(path.read_bytes()) == {key: row[key] for key in ("bytes", "sha256", "git_blob")}
artifact = json.loads((root / "ARTIFACTS.json").read_bytes())["artifacts"]
assert len(artifact) == 1 and artifact[0]["id"] == 13861297427
zip_bytes = (root / "ORIGINAL_ARTIFACT.zip").read_bytes()
assert len(zip_bytes) == artifact[0]["size_in_bytes"] == 6686095
assert "sha256:" + hashlib.sha256(zip_bytes).hexdigest() == artifact[0]["digest"]
raw = (root / "ORIGINAL_JOB.log").read_bytes()
raw_meta = json.loads((root / "ORIGINAL_JOB_LOG_META.json").read_bytes())
assert identity(raw) == {key: raw_meta[key] for key in ("bytes", "sha256", "git_blob")}
run = json.loads((root / "RUN_TERMINAL.json").read_bytes())
job = json.loads((root / "JOBS_TERMINAL.json").read_bytes())["payload"]["jobs"][0]
assert run["id"] == 43032289667 and job["id"] == 130562136934
assert run["head_sha"] == job["head_sha"] == "268539ff9272c8c1950ad630416f66774ce2f890"
assert run["status"] == job["status"] == "completed" and run["conclusion"] == job["conclusion"] == "success"
assert run["run_attempt"] == 1
with tempfile.TemporaryDirectory(prefix="mem-v6-evidence-audit-") as temporary:
    destination = Path(temporary)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        assert archive.testzip() is None
        names = [member.filename for member in archive.infolist()]
        assert len(names) == len(set(names)) == 365
        for member in archive.infolist():
            safe(member.filename)
            assert not member.is_dir() and not stat.S_ISLNK(member.external_attr >> 16)
            content = archive.read(member)
            target = destination / "zip" / member.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
    prefix = destination / "zip" / "mem8-source-gates-v6"
    tar_name = "mem8-source-gates-v6-records.tar.xz"
    (destination / tar_name).write_bytes((prefix / tar_name).read_bytes())
    (destination / "ARCHIVE_INFO.json").write_bytes((prefix / "ARCHIVE_INFO.json").read_bytes())
    with tarfile.open(destination / tar_name, "r:xz") as archive:
        names = set()
        for member in archive:
            safe(member.name)
            assert member.isfile() and member.name not in names
            names.add(member.name)
            target = destination / "records" / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.extractfile(member).read())
        assert len(names) == 363
    for path in (prefix / "records").rglob("*"):
        if path.is_file():
            relative = path.relative_to(prefix / "records")
            assert path.read_bytes() == (destination / "records" / relative).read_bytes()
    invocation = json.loads((destination / "zip/mem8-source-gates-v6-launcher/WORKFLOW_INVOCATION.json").read_bytes())
    assert invocation["GITHUB_SHA"] == run["head_sha"] and invocation["GITHUB_RUN_ID"] == str(run["id"])
    assert invocation["MEM_SOURCE_COMMIT"] == "421d15080b3cb942be8ac51bbe443e268d124a9e"
    assert invocation["MEM_SOURCE_TREE"] == "df293c7709860ecfc3889e4cabb1f970fb649d8e"
    assert invocation["deadline_seconds"] == 600
    completed = subprocess.run([sys.executable, str(root / "verify_source_records.py"), str(destination)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    assert completed.returncode == 0, completed.stderr.decode()
    regenerated = json.loads((destination / "OFFLINE_VERIFICATION.json").read_bytes())
    assert regenerated == json.loads((root / "OFFLINE_VERIFICATION.json").read_bytes())
    assert (destination / "FORMAT_ONLY.patch").read_bytes() == (root / "FORMAT_ONLY.patch").read_bytes()
print(json.dumps({"status": "PASS_OFFLINE_V6_PACKAGE", "archive_members": len(manifest["members"]) + 1,
                  "zip_members": 365, "tar_members": 363, "source_paths": 109,
                  "source_python_actual_pass": 18, "rust_files": 6201,
                  "full_golden_comparison": "only derived rustFilesScanned differs by +1",
                  "native_execution": 0, "model_calls": 0}, indent=2))
