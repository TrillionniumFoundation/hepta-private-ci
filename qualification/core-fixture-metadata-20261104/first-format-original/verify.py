#!/usr/bin/env python3
"""Reassemble original failed formatter log bytes; execute no archived source."""
import gzip
import hashlib
import json
from pathlib import Path


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def main():
    root = Path(__file__).resolve().parent
    record = json.loads((root / "PROVENANCE.json").read_bytes())
    chunks = []
    for row in record["parts"]:
        name = row["path"]
        require(Path(name).name == name, "unsafe part path")
        packed = (root / name).read_bytes()
        require(len(packed) == row["gzip"]["bytes"] and hashlib.sha256(packed).hexdigest() == row["gzip"]["sha256"], "packed part bytes differ")
        data = gzip.decompress(packed)
        require(len(data) == row["bytes"] and hashlib.sha256(data).hexdigest() == row["sha256"], "part bytes differ")
        chunks.append(data)
    data = b"".join(chunks)
    expected = record["original_job_log"]
    require(len(data) == expected["bytes"] and hashlib.sha256(data).hexdigest() == expected["sha256"], "original log differs")
    require(record["result"]["status"] == "failed" and not record["result"]["scopes"] and record["native_executions"] == 0, "original outcome changed")
    print(json.dumps({"original_log_bytes_verified": len(data), "sha256": expected["sha256"], "original_status": "failed", "native_executions": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
