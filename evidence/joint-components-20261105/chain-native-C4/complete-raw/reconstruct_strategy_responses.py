#!/usr/bin/env python3
"""Reconstruct exact retained transport-response bytes from deduplicated payloads.

This performs no remote calls, native executions, or verifier replays.
The original response lengths and SHA256 values are mandatory checks.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="new destination directory")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    delivery = json.loads((root / "C4-strategy-delivery.json").read_text())
    transfer = json.loads((root / "C4-strategy-transfer-index.json").read_text())
    archive = bytearray()
    for index, item in enumerate(delivery["parts"]):
        relative = Path(item["path"])
        assert not relative.is_absolute() and ".." not in relative.parts
        part = (root / relative).read_bytes()
        assert item["index"] == index and item["offset"] == len(archive)
        assert len(part) == item["bytes"] and digest(part) == item["sha256"]
        archive.extend(part)
    assert len(archive) == delivery["bytes"]
    assert digest(archive) == delivery["sha256"]
    args.output.mkdir(parents=True, exist_ok=False)
    offset = 0
    for record in transfer["chunks"]:
        metadata = record["all_response_metadata_except_payload"]
        location = record["payload_location"]
        assert metadata["offset"] == location["offset"] == offset
        payload = archive[offset : offset + location["bytes"]]
        assert len(payload) == location["bytes"]
        assert digest(payload) == metadata["chunk_sha256"]
        offset += len(payload)
        assert metadata["next_offset"] == offset
        assert metadata["eof"] == (offset == len(archive))
        value = dict(metadata, data_base64=base64.b64encode(payload).decode())
        body = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        trailing = record["persisted_response_bytes"] - len(body)
        assert trailing in (1, 2)
        original = body + b"\n" * trailing
        assert digest(original) == record["persisted_response_sha256"]
        name = Path(record["original_persisted_response_path"]).name
        with (args.output / name).open("xb") as stream:
            stream.write(original)
    assert offset == len(archive) and len(transfer["chunks"]) == 495
    print(json.dumps({"responses": 495, "archive_bytes": len(archive),
                      "all_original_response_hashes_match": True,
                      "remote_calls": 0, "native_executions": 0}))


if __name__ == "__main__":
    main()
