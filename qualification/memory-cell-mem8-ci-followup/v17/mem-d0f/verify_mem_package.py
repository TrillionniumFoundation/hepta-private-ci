#!/usr/bin/env python3
"""Replay this evidence package using only its offline readers; no repository command runs."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import tempfile
import zipfile


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def safe_name(name):
    path = PurePosixPath(name)
    assert not path.is_absolute() and all(p not in ("", ".", "..") for p in path.parts)
    return path


def main(archive_path):
    with tempfile.TemporaryDirectory(prefix="mem-d0f-offline-") as directory:
        root = Path(directory)
        with tarfile.open(archive_path, "r:xz") as archive:
            members = archive.getmembers()
            assert len(members) == len({m.name for m in members})
            payload = {}
            for member in members:
                safe_name(member.name)
                assert member.isfile()
                data = archive.extractfile(member).read()
                assert len(data) == member.size
                payload[member.name] = data
            manifest = json.loads(payload["PACKAGE_MANIFEST.json"])
            assert set(payload) == {"PACKAGE_MANIFEST.json"} | {r["path"] for r in manifest["files"]}
            for row in manifest["files"]:
                assert identity(payload[row["path"]]) == {k: row[k] for k in ("bytes", "sha256", "git_blob")}
            for name, data in payload.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        artifact_counts = {}
        for artifact_id in (13874211716, 13873374531, 13874919829):
            folder = root / "artifacts" / str(artifact_id)
            original_manifest = json.loads((folder / "MANIFEST.json").read_bytes())
            raw = (folder / "original.zip").read_bytes()
            assert len(raw) == original_manifest["artifact"]["size_in_bytes"]
            assert "sha256:" + hashlib.sha256(raw).hexdigest() == original_manifest["artifact"]["digest"]
            with zipfile.ZipFile(folder / "original.zip") as archive:
                assert archive.testzip() is None
                infos = archive.infolist()
                names = [item.filename for item in infos if not item.is_dir()]
                assert len(names) == len(set(names))
                assert set(names) == {r["name"] for r in original_manifest["members"]}
                for info in infos:
                    safe_name(info.filename)
                    assert (info.external_attr >> 16) & 0o170000 != 0o120000
                    if not info.is_dir():
                        data = archive.read(info.filename)
                        path = folder / "files" / info.filename
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(data)
            artifact_counts[str(artifact_id)] = len(names)
        expected_names = ["MEM_COMPLETE_ORIGINAL_AUDIT.json", "MEM_NATIVE_ORIGINAL_AUDIT.json",
                          "NATIVE_SOURCE_ARCHIVE_AUDIT.json", "CPU_ORIGINAL_AUDIT_V2.json"]
        expected = {name: (root / name).read_bytes() for name in expected_names}
        command = [sys.executable, "-B", str(root / "audit_mem_complete_original.py")]
        result = subprocess.run(command, cwd=root, capture_output=True, timeout=60)
        assert result.returncode == 0, result.stderr.decode()
        for name, old in expected.items():
            assert (root / name).read_bytes() == old, name
        audited = json.loads((root / "MEM_COMPLETE_ORIGINAL_AUDIT.json").read_bytes())
        return {"status": "PASS_FULL_ORIGINAL_MEM_PACKAGE_REPLAY", "archive": identity(archive_path.read_bytes()),
                "package_members": len(members), "all_member_hashes_verified": True,
                "original_zip_member_counts": artifact_counts, "reader_regenerated_audits_byte_identical": expected_names,
                "source_head": audited["head"], "source_tree": audited["tree"],
                "python": audited["python_totals"], "native": audited["native_totals"],
                "archived_native_or_repository_commands_executed": 0,
                "scope": "Original MEM software/fixture workflow only, not overall required CI or memory benefit."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    print(json.dumps(main(args.archive), indent=2, sort_keys=True))
