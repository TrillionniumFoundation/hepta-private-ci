"""Small provenance helpers shared by the bounded natural-source studies."""
import hashlib
import json
from pathlib import Path
import urllib.request


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def download(url, path, limit):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(path)
    size = 0
    with urllib.request.urlopen(url, timeout=60) as response, path.open("xb") as stream:
        while block := response.read(1024 * 1024):
            size += len(block)
            if size > limit:
                raise ValueError("Source exceeds declared byte limit")
            stream.write(block)
    return {"path": str(path), "sha256": sha(path), "bytes": size, "source_url": url.split("?Expires=")[0]}


def verify_files(files):
    for row in files:
        if sha(row["path"]) != row["sha256"]:
            raise ValueError("Source identity changed: " + row["path"])


def freeze(source, protocol, assets, output, extra=None):
    files = sorted(Path(source).glob("*.py"))
    files.append(Path(protocol))
    snapshots = output / "executed-source"
    snapshots.mkdir()
    for path in files:
        (snapshots / path.name).write_bytes(path.read_bytes())
    import time
    registration = {"registered_ns": time.time_ns(), "protocol": read(protocol),
        "source_sha256": {p.name: sha(p) for p in files},
        "source_snapshot": str(snapshots), "asset_manifest_sha256": sha(assets),
        "heldout_scoring_not_started": True, **(extra or {})}
    save(output / "FROZEN_REGISTRATION.json", registration)
    return registration
