#!/usr/bin/env python3
"""Package frozen proposal code and provenance; never run Cargo or publish refs."""
from pathlib import Path
import base64
import gzip
import hashlib
import io
import json
import shutil
import tarfile

ROOT = Path(__file__).resolve().parent
DEST = ROOT / "delivery"


def identity(data):
    return {"bytes": len(data), "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
            "sha256": hashlib.sha256(data).hexdigest()}


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def main():
    DEST.mkdir(exist_ok=False)
    payload = {"root/final-review/" + p.relative_to(ROOT / "final-review").as_posix(): p
               for p in sorted((ROOT / "final-review").rglob("*")) if p.is_file()}
    payload.update({"root/source-registration/" + p.name: p
                    for p in sorted((ROOT / "source-registration").iterdir()) if p.is_file()})
    payload.update({"root/portable-replay-v1/" + name: ROOT / "portable-replay-v1" / name
                    for name in ["execution.json", "stdout.original.txt", "stderr.original.txt"]})
    payload.update({"root/v2/final-review/" + p.relative_to(ROOT / "v2/final-review").as_posix(): p
                    for p in sorted((ROOT / "v2/final-review").rglob("*")) if p.is_file()})
    payload.update({"root/v2/source-registration/" + p.name: p
                    for p in sorted((ROOT / "v2/source-registration").iterdir()) if p.is_file()})
    payload.update({"root/v2/portable-replay-v1/" + name: ROOT / "v2/portable-replay-v1" / name
                    for name in ["execution.json", "stdout.original.txt", "stderr.original.txt"]})
    independent = ROOT.parent / "pin-utils-proposal-independent"
    payload.update({"root/independent-v1-controls/" + p.name: p
                    for p in sorted((independent / "formal-v1").iterdir()) if p.is_file()})
    payload["root/additional-primary/cargo-update-rust195.original.json"] = independent / "cargo-update-rust195.original.json"
    for path in payload.values():
        assert not path.is_symlink()
    manifest = {"schema": "pin-utils-proposal-exact-archive-members-v1", "files": [
        {"path": name, **identity(path.read_bytes())} for name, path in sorted(payload.items())]}
    write(DEST / "manifest.json", manifest)
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, path in sorted(payload.items()):
            data = path.read_bytes()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            info.mtime = 0
            archive.addfile(info, io.BytesIO(data))
    raw = gzip.compress(stream.getvalue(), compresslevel=9, mtime=0)
    (DEST / "snapshot.tar.gz").write_bytes(raw)
    encoded = base64.b64encode(raw)
    parts = []
    for offset in range(0, len(encoded), 240000):
        name = f"snapshot.tar.gz.b64.part{len(parts) + 1:03d}"
        data = encoded[offset:offset + 240000]
        (DEST / name).write_bytes(data)
        parts.append({"path": name, **identity(data)})
    write(DEST / "archive.json", {"schema": "base64-parted-exact-targz-v1", "archive": identity(raw),
        "parts": parts, "payload_manifest": identity((DEST / "manifest.json").read_bytes()),
        "archive_member_count": len(payload), "payload_bytes": sum(p.stat().st_size for p in payload.values())})
    shutil.copyfile(ROOT / "v2/final-review/README.zh-CN.md", DEST / "README.zh-CN.md")
    shutil.copyfile(ROOT / "v2/source-registration/candidate-postimages.actual.json", DEST / "candidate-postimages.actual.json")
    shutil.copyfile(ROOT / "v2/portable-replay-v1/execution.json", DEST / "portable-execution.json")
    shutil.copyfile(__file__, DEST / "build_packet.py")
    print(json.dumps({"archive": identity(raw), "parts": len(parts), "members": len(payload)}, indent=2))


if __name__ == "__main__":
    main()
