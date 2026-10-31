"""Verify and restore raw scientific evidence from exact registered archives."""
import hashlib
import json
from pathlib import Path
import tarfile


def restore():
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "BUNDLES.json").read_text())
    total = 0
    for item in manifest["bundles"]:
        path = root / item["path"]
        raw = path.read_bytes()
        if len(raw) != item["bytes"] or hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError((str(path), "archive identity mismatch"))
        destination = (root / item["extract_to"]).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        expected = {f["path"]: f for f in item["files"]}
        with tarfile.open(path) as archive:
            names = {m.name for m in archive.getmembers() if m.isfile()}
            if names != set(expected):
                raise ValueError("archive member inventory mismatch")
            for member in archive.getmembers():
                target = (destination / member.name).resolve()
                if not target.is_relative_to(destination) or not (member.isfile() or member.isdir()):
                    raise ValueError("unsafe archive member")
                if member.isdir():
                    continue
                data = archive.extractfile(member).read()
                record = expected[member.name]
                if len(data) != record["bytes"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
                    raise ValueError((member.name, "member identity mismatch"))
                if target.exists() and target.read_bytes() != data:
                    raise ValueError((str(target), "refusing to replace different evidence"))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                total += 1
    print(json.dumps({"verified_archives": len(manifest["bundles"]), "verified_files": total}))


if __name__ == "__main__":
    restore()
