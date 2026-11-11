"""Verify full immutable remote bytes and reconstruct the two original packets."""
from pathlib import Path, PurePosixPath
import base64
import hashlib
import io
import json
import subprocess
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parent
rows = json.loads((ROOT / "COMPLETED_GATE_STAGE_OBJECTS.json").read_text())
prefix = "qualification/memory-cell-mem8-ci-followup/v17/"
proof = []
for row in rows:
    p = ROOT / "completed-gate-remote" / row["path"][len(prefix):]
    data = base64.b64decode(Path(str(p) + ".b64").read_text().strip(), validate=True) if row["binary"] else p.read_bytes()
    if row["binary"]:
        p.write_bytes(data)
    assert data == Path(row["local"]).read_bytes(), row["path"]
    assert len(data) == row["bytes"] and hashlib.sha256(data).hexdigest() == row["sha256"]
    assert hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == row["git_blob"]
    proof.append({k: row[k] for k in ["path", "bytes", "sha256", "git_blob"]})
archives = []
for folder, index_name in [("source-v9", "PART_PUBLICATION.json"), ("fence013-original", "ARCHIVE_INFO.json")]:
    p = ROOT / "completed-gate-remote" / folder
    index = json.loads((p / index_name).read_text())
    data = b"".join((p / r["path"]).read_bytes() for r in index["parts"])
    assert len(data) == index["archive"]["bytes"] and hashlib.sha256(data).hexdigest() == index["archive"]["sha256"]
    archive = p / "ROOT_RECONSTRUCTED.tar.xz"
    archive.write_bytes(data)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:xz") as t:
        members = t.getmembers()
        assert len({m.name for m in members}) == len(members) and all(m.isfile() for m in members)
        for m in members:
            name = PurePosixPath(m.name)
            assert not name.is_absolute() and ".." not in name.parts and "\\" not in m.name
        archive_rows = {m.name: t.extractfile(m).read() for m in members}
    for manifest_name in ["MEMBER_MANIFEST.json", "MANIFEST.json"]:
        if (p / manifest_name).exists():
            manifest = json.loads((p / manifest_name).read_text())
            expected = manifest.get("members", manifest.get("files"))
            assert len({r["path"] for r in expected}) == len(expected)
            names = {r["path"] for r in expected}
            assert names | ({"MANIFEST.json"} if folder == "fence013-original" else set()) == set(archive_rows)
            for row in expected:
                value = archive_rows[row["path"]]
                assert len(value) == row["bytes"] and hashlib.sha256(value).hexdigest() == row["sha256"]
                assert hashlib.sha1(b"blob " + str(len(value)).encode() + b"\0" + value).hexdigest() == row["git_blob"]
    extracted = p / "root-extracted-v3"
    assert not extracted.exists(), "create-only independent reconstruction"
    for name, value in archive_rows.items():
        target = extracted / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(value)
    if folder == "fence013-original":
        command = [sys.executable, str(extracted / "verify_fence013.py"), str(extracted), "--compare-audit"]
        result = subprocess.run(command, capture_output=True, check=True)
        assert result.stderr == b"" and result.stdout == archive_rows["AUDIT.json"]
        (p / "ROOT_REMOTE_OFFLINE_REPLAY.json").write_bytes(result.stdout)
    else:
        canonical = extracted / "readback/canonical-original"
        expected_verification = (canonical / "OFFLINE_VERIFICATION.json").read_bytes()
        expected_patch = (canonical / "FORMAT_ONLY.patch").read_bytes()
        info = json.loads((canonical / "ARCHIVE_INFO.json").read_bytes())
        original_zip = archive_rows["ORIGINAL_ARTIFACT.zip"]
        assert len(original_zip) == 7236232 and hashlib.sha256(original_zip).hexdigest() == "39e1db90fb6b470da5c61e18e7ea7a9f5169f17f0fd0f00522ec385435fd94bd"
        with zipfile.ZipFile(io.BytesIO(original_zip)) as z:
            assert z.testzip() is None and len(z.namelist()) == len(set(z.namelist())) == 386
            assert [n for n in z.namelist() if n.endswith(".tar.xz")] == ["mem8-source-gates-v9/" + info["path"]]
            inner = z.read("mem8-source-gates-v9/" + info["path"])
        assert len(inner) == info["bytes"] and hashlib.sha256(inner).hexdigest() == info["sha256"]
        (canonical / info["path"]).write_bytes(inner)
        with tarfile.open(fileobj=io.BytesIO(inner), mode="r:xz") as t:
            members = t.getmembers()
            assert len(members) == len({m.name for m in members}) == 384 and all(m.isfile() for m in members)
            for member in members:
                name = PurePosixPath(member.name)
                assert not name.is_absolute() and ".." not in name.parts and "\\" not in member.name
                target = canonical / "records" / member.name
                target.parent.mkdir(parents=True, exist_ok=True)
                assert not target.exists()
                target.write_bytes(t.extractfile(member).read())
        result = subprocess.run([sys.executable, str(extracted / "verify_source_records_v9.py"), str(canonical)], capture_output=True, check=True)
        assert result.stderr == b""
        assert (canonical / "OFFLINE_VERIFICATION.json").read_bytes() == expected_verification
        assert (canonical / "FORMAT_ONLY.patch").read_bytes() == expected_patch == b""
        (p / "ROOT_REMOTE_OFFLINE_REPLAY.json").write_bytes(expected_verification)
    assert result.returncode == 0
    archives.append({"folder": folder, "members": list(archive_rows), "archive": index["archive"]})
(ROOT / "COMPLETED_GATE_REMOTE_BYTE_AUDIT.json").write_text(json.dumps({"schema": "mem8.v17.completed-gate-remote-byte-audit.v1", "ref": "f033cb0136a6eaf5ab66cdf81ff2b9ea5bc1fde7", "full_content_equal_count": len(proof), "objects": proof, "archives": archives}, indent=2) + "\n")
print(json.dumps({"full_remote_equal": len(proof), "archives": archives}, indent=2))
