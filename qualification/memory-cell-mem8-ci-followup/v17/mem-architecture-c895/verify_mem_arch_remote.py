"""Reconstruct the complete remote packet and replay its original offline reader."""
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE / "mem-architecture-c895"
SOURCE = WORK / "mem-ci-c895-original"


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def main():
    parts = json.loads((SOURCE / "ARCHIVE_PART_PUBLICATION.json").read_bytes())
    chunks = []
    for part in parts["parts"]:
        raw = base64.b64decode((ROOT / "remote-parts" / (part["path"] + ".b64")).read_text().strip(), validate=True)
        assert identity(raw) == {key: part[key] for key in ("bytes", "sha256", "git_blob")}
        assert part["offset"] == sum(map(len, chunks))
        chunks.append(raw)
    archive = b"".join(chunks)
    assert identity(archive) == {key: parts["archive"][key] for key in ("bytes", "sha256", "git_blob")}
    assert archive == (SOURCE / parts["archive"]["path"]).read_bytes()
    (ROOT / "REMOTE_ORIGINAL_OBSERVATIONS.tar.xz").write_bytes(archive)
    destination = ROOT / "root-extracted"
    destination.mkdir(exist_ok=False)
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:xz") as source:
        members = source.getmembers()
        assert len(members) == len({member.name for member in members}) == 183
        for member in members:
            path = PurePosixPath(member.name)
            assert member.isfile() and not path.is_absolute() and ".." not in path.parts
            target = destination / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.extractfile(member).read())
    manifest = json.loads((destination / "FILE_MANIFEST.json").read_bytes())
    for row in manifest["files"]:
        assert identity((destination / row["path"]).read_bytes()) == {key: row[key] for key in ("bytes", "sha256", "git_blob")}
    result = subprocess.run([sys.executable, "-B", "verify_retained_evidence.py"], cwd=destination, capture_output=True, check=True)
    assert not result.stderr
    replay = json.loads(result.stdout)
    expected = json.loads((SOURCE / "RETAINED_OFFLINE_REPLAY.json").read_bytes())
    assert replay == expected
    (ROOT / "ROOT_OFFLINE_REPLAY.json").write_bytes(result.stdout)
    audit = {
        "schema": "mem8.v17.c895.mem-architecture.root-remote-replay.v1",
        "status": "PASS_COMPLETE_REMOTE_PACKET_AND_ORIGINAL_OFFLINE_REPLAY",
        "immutable_commit": "ef792bef165ce00133cef57b8e3568d959f7a4d5",
        "binary_parts_fully_read": 7, "archive": identity(archive),
        "members_verified": 183, "complete_original_small_ZIPs_replayed": 4,
        "full_original_job_logs_retained": 6,
        "full_original_offline_reader_result_equal": True,
        "source_commit": "c89540598693697577cda8cba31cb07f6ce65317",
        "source_tree": "5a7c897a33e4eef48ea8f4bf52eaf48ea7c866ae",
        "complete_source_index_entries": 14053,
        "large_Architecture_wrapper_present_in_packet": False,
        "MEM_integrity_python_pass": 35,
        "MEM_CPU_or_native_tests_executed": 0,
        "Architecture_python_executions": 288,
        "Architecture_distinct_python_case_ids": 144,
        "Architecture_native_tests_executed": 0,
        "Architecture_required": "failure",
        "both_original_workflows": "failure",
        "new_tests_builds_models_or_network_calls_by_offline_reader": 0,
    }
    (ROOT / "ROOT_REMOTE_ARCHIVE_AUDIT.json").write_text(json.dumps(audit, indent=2) + "\n")
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
