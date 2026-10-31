"""Restore frozen CREMA-D low-level features from hash-checked textual parts."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("transport", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "source_transport.json").read_text())
    start, cpu = time.perf_counter(), time.process_time()
    args.output.mkdir(parents=True, exist_ok=True)
    checks = []
    for row in manifest["files"]:
        values = []
        for part in row["parts"]:
            payload = (args.transport / part["path"]).read_bytes()
            assert len(payload) == part["bytes"]
            assert hashlib.sha256(payload).hexdigest() == part["sha256"]
            decoded = base64.b64decode(payload.strip(), validate=True)
            assert len(decoded) == part["raw_bytes"]
            values.append(decoded)
        data = b"".join(values)
        assert len(data) == row["bytes"]
        assert hashlib.sha256(data).hexdigest() == row["sha256"]
        target = args.output / row["path"]
        if target.exists():
            assert target.read_bytes() == data
        else:
            target.write_bytes(data)
        checks.append({"file": row["path"], "bytes": len(data), "sha256": row["sha256"]})
    receipt = {"source_commit": "dca9febc8143c682077fe27d40dbeaa1137bcaa4",
               "verified_parts": sum(len(row["parts"]) for row in manifest["files"]),
               "files": checks, "restore_wall_seconds": time.perf_counter() - start,
               "restore_cpu_seconds": time.process_time() - cpu,
               "scope": "Hash verification and local restore only; connector transfer cost is not timed here.",
               "test_arrays_opened": False, "new_media_acquisition": False}
    (root / "RESTORE_RECEIPT.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"verified_parts": receipt["verified_parts"], "bytes": sum(x["bytes"] for x in checks)}))


if __name__ == "__main__":
    main()
