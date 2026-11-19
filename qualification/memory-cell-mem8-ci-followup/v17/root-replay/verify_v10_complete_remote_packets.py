"""Replay reviewed offline readers against four complete remote reconstructions."""
from pathlib import Path, PurePosixPath
import hashlib
import io
import json
import subprocess
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parent
BASE = ROOT / "v10-completed-remote"
def pin(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}

def extract_regular(raw, destination, count):
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:xz") as archive:
        members = archive.getmembers()
        assert len(members) == len({m.name for m in members}) == count
        objects = {}
        for m in members:
            p = PurePosixPath(m.name)
            assert m.isfile() and not p.is_absolute() and ".." not in p.parts and "\\" not in m.name
            assert str(p) == m.name
            objects[m.name] = archive.extractfile(m).read()
    assert not destination.exists()
    for name, data in objects.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return objects

specs = [
    ("source-v10", "MEMBER_MANIFEST.json", 32, "", False),
    ("native-two-preparation", "MEMBER_MANIFEST.json", 90, "", True),
    ("windows-fix-preparation", "FILE_MANIFEST.json", 27, "", True),
    ("mac-memory-code-c895", "FILE_MANIFEST.json", 28, "packet/", True),
]
proofs = []
for folder, manifest_name, count, prefix, self_excluded in specs:
    p = BASE / folder
    archive = p / "ROOT_RECONSTRUCTED.tar.xz"
    out = p / "root-extracted-v3"
    objects = extract_regular(archive.read_bytes(), out, count)
    manifest = json.loads((p / manifest_name).read_bytes())
    rows = manifest if isinstance(manifest, list) else manifest.get("files", manifest.get("members"))
    names = {prefix + row["path"] for row in rows}
    assert len(names) == len(rows)
    if self_excluded:
        names.add(prefix + "FILE_MANIFEST.json")
    assert names == set(objects)
    for row in rows:
        assert pin(objects[prefix + row["path"]]) == {k: row[k] for k in ("bytes", "sha256", "git_blob")}
    if folder == "source-v10":
        expected = objects["readback/canonical-original/OFFLINE_VERIFICATION.json"]
        materialized = p / "root-materialized-v3"
        result = subprocess.run([sys.executable, str(out / "materialize_original.py"), "--zip", str(out / "ORIGINAL_ARTIFACT.zip"), "--output", str(materialized)], capture_output=True)
        assert result.returncode == 0 and result.stderr == b"", result.stderr.decode()
        canonical = materialized / "canonical-original"
        info = json.loads((canonical / "ARCHIVE_INFO.json").read_bytes())
        raw_zip = objects["ORIGINAL_ARTIFACT.zip"]
        assert len(raw_zip) == 7243400 and hashlib.sha256(raw_zip).hexdigest() == "bb1cca9742144cc0c1bfe7bf3d5f7081ab651ea8fedd6a51041f2fe5fc8361ff"
        with zipfile.ZipFile(io.BytesIO(raw_zip)) as z:
            assert z.testzip() is None and len(z.namelist()) == len(set(z.namelist())) == 386
            expected_tar = "mem8-source-gates-v10/" + info["path"]
            assert [name for name in z.namelist() if name.endswith(".tar.xz")] == [expected_tar]
            inner = z.read(expected_tar)
        assert pin(inner) == {k: info[k] for k in ("bytes", "sha256", "git_blob")}
        assert (canonical / info["path"]).read_bytes() == inner
        result = subprocess.run([sys.executable, str(out / "verify_source_records_v10.py"), str(canonical)], capture_output=True)
        assert result.returncode == 0 and result.stderr == b"", result.stderr.decode()
        assert (canonical / "OFFLINE_VERIFICATION.json").read_bytes() == expected
        assert (canonical / "FORMAT_ONLY.patch").read_bytes() == b""
        replay = expected
        audit = json.loads(replay)
        assert audit["formatter_changed_paths"] == [] and audit["source_after_status"] == ""
        scope = {"source_gate_run": 43060276203, "source_gate_job": 130660630288, "original_ZIP_members": 386, "canonical_members": 387, "original_manifest_members": 386, "formatter_changes": 0, "source_after_clean": True, "python_pass": 18, "overlay_paths": 118, "rust_files": 6204, "old_name_hits": 0, "elapsed_seconds": audit["elapsed_seconds"], "native_results": False}
    elif folder == "native-two-preparation":
        result = subprocess.run([sys.executable, str(out / "verify_preparation.py"), str(archive)], capture_output=True)
        assert result.returncode == 0 and result.stderr == b"", result.stderr.decode()
        expected = (p / "LOCAL_ARCHIVE_AUDIT.json").read_bytes()
        observed = json.loads(result.stdout)
        captured = json.loads(expected)
        # The original record is an execution wrapper, not raw reader stdout.
        # Compare every captured result field, and authenticate its reader.
        mapping = {
            "result": "status", "archive": "archive", "members": "members",
            "references": "reference_sources",
            "source_dependencies": "final_source_dependencies",
            "full_tree_leaves": "full_source_tree_leaves",
            "offline_parser_controls": "offline_parser_controls",
            "native_results_included": "native_results_included",
        }
        metadata = {"actual_exit_code", "actual_reader_command", "actual_tool_chunk_id", "observed_tool_wall_time_seconds", "reader", "schema", "source_or_native_model_execution"}
        assert set(captured) == set(mapping) | metadata
        for old_key, new_key in mapping.items():
            assert captured[old_key] == observed[new_key], old_key
        assert captured["actual_exit_code"] == result.returncode == 0
        assert captured["reader"] == pin(objects["verify_preparation.py"])
        assert captured["source_or_native_model_execution"] is False
        assert observed["source_or_native_tests_or_models_executed_by_reader"] == 0
        assert observed["source_head"] == "d0f6507e08f7f5c5855f5164d07c049a34d1a6d9"
        assert observed["source_tree"] == "658fa040046285116b1fd81b94ff8c96444072ad"
        assert observed["active_cases"] == 2
        assert observed["scoped_fix_packages"] == ["codex-core"]
        assert observed["job_budget_minutes"] == 65
        assert observed["actual_admission_preserved"] is True
        replay = result.stdout
        scope = json.loads(replay)
    elif folder == "windows-fix-preparation":
        result = subprocess.run([sys.executable, str(out / "verify_preparation.py"), str(out)], capture_output=True)
        assert result.returncode == 0 and result.stderr == b"", result.stderr.decode()
        assert result.stdout == (p / "OFFLINE_REPLAY.json").read_bytes()
        replay = result.stdout
        scope = json.loads(replay)
        scope["full_twenty_source_byte_recovery"] = "Separate frozen dependency input addendum required; the 27-member package carries the complete tree and twenty pins, not all twenty loose source files."
    else:
        original = ROOT / "blocking-remote/blocking-c895/root-extracted/records"
        result = subprocess.run([sys.executable, str(out / "packet/verify_packet.py"), str(out / "packet"), "--full-raw", str(original / "job-130619380498.log"), "--full-tree", str(original / "SOURCE_TREE.ls-tree")], capture_output=True)
        assert result.returncode == 0 and result.stderr == b"", result.stderr.decode()
        audit = json.loads(result.stdout)
        assert audit == json.loads((p / "ARCHIVE_INFO.json").read_bytes())["offline_full_originals"]
        replay = result.stdout
        scope = audit
    (p / "ROOT_REMOTE_OFFLINE_REPLAY.json").write_bytes(replay)
    proofs.append({"folder": folder, "archive": pin(archive.read_bytes()), "outer_members": count, "unchanged_offline_verifier_exit": 0, "full_original_result_equal": True, "comparison": "every original result field from execution wrapper; reader bytes and additional bound source/plan fields verified" if folder == "native-two-preparation" else "complete original reader result", "scope": scope})

proof = {"schema": "mem8.v17.v10-complete-packets-root-replay.v1", "ref": "d761b425e971caf067509886d8f7fbb069899a73", "previous_full_remote_object_byte_checks": 60, "packets": proofs, "new_native_or_model_executions": 0}
(ROOT / "ROOT_V10_COMPLETE_PACKETS_REPLAY.json").write_text(json.dumps(proof, indent=2) + "\n")
print(json.dumps({"status": "PASS_FOUR_COMPLETE_REMOTE_PACKETS_AND_UNCHANGED_OFFLINE_READERS", "ref": proof["ref"], "packet_members": {p["folder"]: p["outer_members"] for p in proofs}}, indent=2))
