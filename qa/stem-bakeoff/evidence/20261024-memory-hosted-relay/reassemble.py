"""Reassemble verified immutable relay evidence parts without executing them."""

import argparse
import hashlib
import json
from pathlib import Path


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
directory = Path(__file__).resolve().parent
manifest = json.loads((directory / "parts.json").read_text())
if args.output.exists():
    raise SystemExit("Refusing to overwrite an existing output")
verified = []
for item in manifest["parts"]:
    name = item["filename"]
    if Path(name).name != name:
        raise ValueError("Unsafe part path")
    payload = (directory / name).read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest()
    if (len(payload), hashlib.sha256(payload).hexdigest(), blob) != (item["bytes"], item["sha256"], item["git_blob_sha"]):
        raise ValueError(f"Part integrity failure: {name}")
    verified.append(payload)
payload = b"".join(verified)
if (len(payload), hashlib.sha256(payload).hexdigest()) != (manifest["archive_bytes"], manifest["archive_sha256"]):
    raise ValueError("Complete archive integrity failure")
with args.output.open("xb") as stream:
    stream.write(payload)
print(manifest["archive_sha256"])
