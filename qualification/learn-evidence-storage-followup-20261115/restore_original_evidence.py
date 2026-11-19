"""Verify and restore archived evidence without replacing existing files."""
from pathlib import Path
import hashlib
import json
import sys

root = Path(__file__).resolve().parents[2]
report = json.loads(Path(__file__).with_name("VERIFICATION.json").read_text())
destination = Path(sys.argv[1]) if len(sys.argv) == 2 else Path.cwd()
outputs = []
for entry in report["artifacts"]:
    manifest_path = root / entry["manifest"]
    manifest = json.loads(manifest_path.read_text())
    data = bytearray()
    for part in manifest["ordered_parts"]:
        chunk = (manifest_path.parent / part["path"]).read_bytes()
        if part["offset"] != len(data) or len(chunk) != part["bytes"]:
            raise ValueError("part length or offset mismatch: " + part["path"])
        if hashlib.sha256(chunk).hexdigest() != part["sha256"]:
            raise ValueError("part checksum mismatch: " + part["path"])
        data.extend(chunk)
    if len(data) != manifest["archive_bytes"]:
        raise ValueError("original length mismatch: " + str(manifest_path))
    if hashlib.sha256(data).hexdigest() != manifest["archive_sha256"]:
        raise ValueError("original checksum mismatch: " + str(manifest_path))
    output = destination / manifest["original_repository_path"]
    if output.exists():
        raise FileExistsError(output)
    outputs.append((output, data))
for output, data in outputs:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(data)
    print("Verified and restored " + str(output))
