"""Verify full remote bytes and replay existing offline evidence validators."""
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parent

def pin(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}

def load(path):
    return json.loads(path.read_bytes())

def safe(name):
    p = PurePosixPath(name)
    assert name and not p.is_absolute() and ".." not in p.parts and "\\" not in name
    return p

verified = []
for name, manifest_name in (("source-v7-original", "FILE_MANIFEST.json"),
                             ("source-v8-preparation", "FILE_MANIFEST.json"),
                             ("windows-scoped-fix-original/records", "PACKAGE_MEMBERS.json")):
    directory = ROOT / name
    manifest = load(directory / manifest_name)
    rows = manifest["members"]
    for row in rows:
        path = directory / safe(row["path"])
        assert path.is_file() and not path.is_symlink()
        assert pin(path.read_bytes()) == {k: row[k] for k in ("bytes", "sha256", "git_blob")}
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}
    assert actual == {row["path"] for row in rows} | {manifest_name}
    verified.append({"archive": name, "verified_members": len(actual)})

original = ROOT / "source-v7-original"
zip_path = original / "ORIGINAL_ARTIFACT.zip"
artifact = load(original / "ARTIFACT_METADATA.json")["structuredContent"]["artifacts"][0]
zip_identity = pin(zip_path.read_bytes())
assert zip_identity["bytes"] == artifact["size_in_bytes"] == 7028444
assert zip_identity["sha256"] == artifact["digest"].removeprefix("sha256:")
canonical = ROOT / "v7-root-canonical-replay"
canonical.mkdir(exist_ok=True)
with zipfile.ZipFile(zip_path) as bundle:
    assert bundle.testzip() is None
    members = bundle.infolist()
    assert len(members) == len({m.filename for m in members}) == 377
    for member in members:
        safe(member.filename)
        assert not member.is_dir()
    archive_info = bundle.read("mem8-source-gates-v7/ARCHIVE_INFO.json")
    info = json.loads(archive_info)
    archived = bundle.read("mem8-source-gates-v7/" + info["path"])
    assert pin(archived) == {k: info[k] for k in ("bytes", "sha256", "git_blob")}
    (canonical / "ARCHIVE_INFO.json").write_bytes(archive_info)
    (canonical / info["path"]).write_bytes(archived)
    missing_hidden = []
    direct_equal = 0
    with tarfile.open(fileobj=io.BytesIO(archived), mode="r:xz") as tar:
        inner = tar.getmembers()
        assert len(inner) == len({m.name for m in inner}) == info["members"] == 375
        for member in inner:
            safe(member.name)
            assert member.isfile()
            data = tar.extractfile(member).read()
            path = canonical / "records" / member.name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            direct = "mem8-source-gates-v7/records/" + member.name
            if direct in bundle.namelist():
                assert bundle.read(direct) == data
                direct_equal += 1
            else:
                missing_hidden.append(member.name)
    correction = load(original / "CANONICAL_ARCHIVE_MATERIALIZATION.json")
    assert sorted(missing_hidden) == sorted(correction["direct_zip_omitted_paths"])
    assert direct_equal == correction["direct_zip_equal_members"] == 369

verifier = original / "verify_source_records_v7.py"
assert pin(verifier.read_bytes())["git_blob"] == "13ec3f70870757d26a348fb07a095ae84e2e58e6"
run = subprocess.run([sys.executable, "-B", str(verifier), str(canonical)], capture_output=True, timeout=40)
(ROOT / "ROOT_V7_REPLAY.stdout").write_bytes(run.stdout)
(ROOT / "ROOT_V7_REPLAY.stderr").write_bytes(run.stderr)
assert run.returncode == 0, run.stderr.decode(errors="replace")
actual_v7 = load(canonical / "OFFLINE_VERIFICATION.json")
assert actual_v7 == load(original / "canonical-original/OFFLINE_VERIFICATION.json")
assert (canonical / "FORMAT_ONLY.patch").read_bytes() == (original / "canonical-original/FORMAT_ONLY.patch").read_bytes()

scoped = ROOT / "windows-scoped-fix-original/records"
verifier = scoped / "verify_scoped_fix_original.py"
assert pin(verifier.read_bytes())["git_blob"] == "6f44caae26a64ac69e160267f7267f8b42e8507b"
run = subprocess.run([sys.executable, "-B", str(verifier)], capture_output=True, timeout=40)
(ROOT / "ROOT_SCOPED_FIX_REPLAY.stdout").write_bytes(run.stdout)
(ROOT / "ROOT_SCOPED_FIX_REPLAY.stderr").write_bytes(run.stderr)
assert run.returncode == 0, run.stderr.decode(errors="replace")
actual_scoped = json.loads(run.stdout)
assert actual_scoped == load(scoped / "OFFLINE_AUDIT.json")

report = {"schema": "mem8.v16.root-full-remote-and-offline-replay.v1",
          "status": "PASS_FULL_REMOTE_ARCHIVES_AND_ORIGINAL_OFFLINE_REPLAY",
          "immutable_commit": "4aaa14c3ed75d95de38f8987a7f17fed0237942a",
          "archives": verified, "v7_original_zip": zip_identity,
          "v7_zip_members": 377, "v7_inner_tar_members": 375,
          "v7_exact_zip_hidden_omissions_retained_in_original_tar": missing_hidden,
          "v7_full_original_verifier_result_equal": True,
          "v7_formatter_patch_byte_equal": True,
          "v7_source_gate_run": 43042186271, "v7_actual_python_pass": 18,
          "v7_gate_elapsed_seconds": actual_v7["elapsed_seconds"],
          "scoped_fix_original_run": 43038376307,
          "scoped_fix_full_original_verifier_result_equal": True,
          "scoped_fix_original_qualification": "FAIL: third command rewrote two source files",
          "scoped_fix_command_exit_codes": [p["command_exit_code"] for p in actual_scoped["phases"]],
          "v8_preparation_only_archive": True, "native_or_model_execution": 0}
(ROOT / "ROOT_COMPLETE_REPLAY_AUDIT.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
