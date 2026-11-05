"""Deterministic bounded text records; no model inference or scoring."""
import gzip
import hashlib
import json
from pathlib import Path


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def save(path, value):
    path = Path(path)
    raw = (canonical(value)+"\n").encode()
    if path.name.endswith(".gz"):
        raw = gzip.compress(raw, mtime=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    if len(raw) >= 480000:
        parts = []
        for i, offset in enumerate(range(0, len(raw), 479000)):
            name = path.name+f".part{i:04d}"
            chunk = raw[offset:offset+479000]
            with (path.parent/name).open("xb") as stream:
                stream.write(chunk)
            parts.append({"name": name, "bytes": len(chunk), "sha256": sha(chunk)})
        save(path.with_name(path.name+".parts.json"), {"bytes": len(raw), "sha256": sha(raw), "parts": parts})
    else:
        with path.open("xb") as stream:
            stream.write(raw)
    return {"bytes": len(raw), "sha256": sha(raw)}


def raw_bytes(path):
    path = Path(path)
    if path.exists():
        return path.read_bytes()
    record = json.loads(path.with_name(path.name+".parts.json").read_text())
    chunks = []
    for item in record["parts"]:
        chunk = (path.parent/item["name"]).read_bytes()
        assert len(chunk) == item["bytes"] and sha(chunk) == item["sha256"]
        chunks.append(chunk)
    data = b"".join(chunks)
    assert len(data) == record["bytes"] and sha(data) == record["sha256"]
    return data


def read(path):
    path = Path(path)
    data = raw_bytes(path)
    return json.loads(gzip.decompress(data) if path.name.endswith(".gz") else data)
