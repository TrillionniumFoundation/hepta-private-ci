"""Freeze all cloud-prepared originals and outputs into lossless small parts."""
import base64
import gzip
import hashlib
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "delivery"


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def put(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == raw, "frozen file changed: " + str(path)
    else:
        path.write_bytes(raw)


def put_json(path, value):
    put(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def main():
    # This is the offline evidence verifier, never the operational runner.
    checked = subprocess.run([sys.executable, str(HERE / "verify_rebound_packet.py")], cwd=HERE, capture_output=True, timeout=30)
    put(HERE / "offline-verifier.stdout", checked.stdout)
    put(HERE / "offline-verifier.stderr", checked.stderr)
    put_json(HERE / "offline-verifier-receipt.json", {"argv": ["python", "verify_rebound_packet.py"], "exit_code": checked.returncode, "stdout": identity(checked.stdout), "stderr": identity(checked.stderr), "native_execution": False})
    assert checked.returncode == 0
    paths = sorted(p for p in HERE.rglob("*") if p.is_file() and OUT not in p.parents and "__pycache__" not in p.parts)
    members = []
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for path in paths:
            name = path.relative_to(HERE).as_posix()
            raw = path.read_bytes()
            members.append({"name": name, **identity(raw)})
            entry = tarfile.TarInfo(name)
            entry.size, entry.mode, entry.mtime, entry.uid, entry.gid = len(raw), 0o644, 0, 0, 0
            entry.uname = entry.gname = ""
            archive.addfile(entry, io.BytesIO(raw))
    packed = gzip.compress(stream.getvalue(), mtime=0)
    chunks = []
    for number, start in enumerate(range(0, len(packed), 350000)):
        raw = base64.b64encode(packed[start:start + 350000]) + b"\n"
        name = "archive-base64-part-%03d.txt" % number
        assert len(raw) < 480000
        put(OUT / name, raw)
        chunks.append({"name": name, "decoded_bytes": min(350000, len(packed) - start), **identity(raw)})
    replay = b"".join(base64.b64decode((OUT / row["name"]).read_bytes(), validate=False) for row in chunks)
    assert replay == packed
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(replay)), mode="r:") as archive:
        assert [m.name for m in archive.getmembers()] == [m["name"] for m in members]
        for row in members:
            assert identity(archive.extractfile(row["name"]).read()) == {k: row[k] for k in ("bytes", "sha256", "git_blob")}
    put_json(OUT / "member-manifest.json", {"schema": "linux-full-67cc-prepared-members-v1", "members": members, "member_count": len(members), "original_member_bytes": sum(m["bytes"] for m in members)})
    put_json(OUT / "transport-manifest.json", {"schema": "linux-full-67cc-prepared-transport-v1", "compression": "deterministic gzip of USTAR; each part separately base64", "archive": identity(packed), "parts": chunks, "member_manifest": identity((OUT / "member-manifest.json").read_bytes()), "members_verified_full_bytes_after_roundtrip": len(members), "native_execution": False, "ref_modified": False, "actual_registration": "Each computed identity requires its separate create_blob and full GET registry; this manifest is not itself such a receipt."})
    print(json.dumps({"members": len(members), "archive": identity(packed), "parts": len(chunks), "max_part_bytes": max(r["bytes"] for r in chunks), "offline_verifier_exit": checked.returncode, "delivery": str(OUT)}))


if __name__ == "__main__":
    main()
