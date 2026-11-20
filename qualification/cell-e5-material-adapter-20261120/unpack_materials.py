"""Reassemble bounded material payload parts into a new directory; never execute payloads."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile


def unpack(manifest_path, output):
    manifest = json.loads(manifest_path.read_bytes())
    chunks = []
    for part in manifest["parts"]:
        if not re.fullmatch(r"payload/part-\d{3}\.bin", part["path"]):
            raise ValueError("unexpected payload part path")
        data = (manifest_path.parent / part["path"]).read_bytes()
        if len(data) != part["bytes"] or hashlib.sha256(data).hexdigest() != part["sha256"]:
            raise ValueError("payload part changed")
        chunks.append(data)
    archive = b"".join(chunks)
    if len(archive) != manifest["archive_bytes"] or hashlib.sha256(archive).hexdigest() != manifest["archive_sha256"]:
        raise ValueError("archive binding changed")
    output.mkdir(exist_ok=False)
    seen, total = set(), 0
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as source:
        for item in source:
            allowed = re.fullmatch(r"MATERIAL_INDEX\.json|materials/\d{2}\.json|blobs/[0-9a-f]{64}", item.name)
            if not item.isfile() or not allowed or item.name in seen or item.size > manifest["maximum_member_bytes"]:
                raise ValueError("unexpected archive member")
            seen.add(item.name)
            total += item.size
            if total > manifest["raw_bytes"] or len(seen) > manifest["members"]:
                raise ValueError("archive budget exceeded")
            raw = source.extractfile(item).read()
            if len(raw) != item.size:
                raise ValueError("truncated archive member")
            path = output / item.name
            path.parent.mkdir(exist_ok=True)
            with path.open("xb") as target:
                target.write(raw)
    if total != manifest["raw_bytes"] or len(seen) != manifest["members"]:
        raise ValueError("archive cardinality differs")
    result = {"members": len(seen), "raw_bytes": total, "archive_sha256": manifest["archive_sha256"],
              "payload_executed": False, "model_calls": 0, "training_updates": 0, "new_native_children": 0}
    print(json.dumps(result, sort_keys=True))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    unpack(args.manifest, args.output)
