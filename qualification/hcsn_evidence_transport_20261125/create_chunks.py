"""Create bounded raw-byte parts from an explicitly pinned original inventory."""

import argparse
import json
from pathlib import Path

from reassemble import FORMAT, MAX_PART_BYTES, PART_FORMAT, contained_file, digest, git_blob_digest

INDEX_PATH = "qualification/hcsn_evidence_transport_20261125/INDEX.json"


def write_new(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(raw)


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def pack(inventory, source_root, output_root):
    source_root, output_root = Path(source_root), Path(output_root)
    sources = []
    for obj in inventory["objects"]:
        raw = contained_file(source_root, obj["logical_path"]).read_bytes()
        if (len(raw) != obj["bytes"] or digest(raw) != obj["sha256"]
                or git_blob_digest(raw) != obj["source_git_blob_sha1"]):
            raise ValueError("source differs from immutable inventory: " + obj["logical_path"])
        sources.append((obj, raw))
    index = {"format": FORMAT, "repository": inventory["repository"],
             "source_commit": inventory["source_commit"], "part_limit_bytes": MAX_PART_BYTES,
             "object_count": len(sources), "objects": []}
    for original, raw in sources:
        obj = {**original, "format": PART_FORMAT, "source_commit": inventory["source_commit"],
               "repository": inventory["repository"], "parts": []}
        logical = obj["logical_path"]
        for number, offset in enumerate(range(0, len(raw), MAX_PART_BYTES)):
            part = raw[offset:offset + MAX_PART_BYTES]
            name = logical + f".parts/{number:05d}.bin"
            write_new(output_root / name, part)
            obj["parts"].append({"index": number, "offset": offset, "path": name,
                                 "bytes": len(part), "sha256": digest(part),
                                 "git_blob_sha1": git_blob_digest(part)})
        name = logical + ".parts.json"
        manifest = json_bytes(obj)
        write_new(output_root / name, manifest)
        index["objects"].append({"logical_path": logical, "manifest": name,
                                 "manifest_bytes": len(manifest), "manifest_sha256": digest(manifest)})
    write_new(output_root / INDEX_PATH, json_bytes(index))
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(pack(json.loads(args.inventory.read_text()), args.source_root, args.output_root)))
