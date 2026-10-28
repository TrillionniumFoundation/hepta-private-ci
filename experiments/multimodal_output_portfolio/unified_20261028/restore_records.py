"""Restore exactly the JSON bytes preserved in a run's compression manifest."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path


def restore(root):
    root = Path(root).resolve()
    manifest = json.loads((root / "COMPRESSED_RECORDS.json").read_text())
    restored = []
    for row in manifest["files"]:
        source, target = root / row["compressed"], root / row["original"]
        if not source.resolve().is_relative_to(root) or not target.resolve().is_relative_to(root):
            raise ValueError("Compression manifest path escaped its run directory")
        compressed = source.read_bytes()
        if hashlib.sha256(compressed).hexdigest() != row["compressed_sha256"]:
            raise ValueError("Compressed evidence changed")
        raw = gzip.decompress(compressed)
        if len(raw) != row["original_bytes"] or hashlib.sha256(raw).hexdigest() != row["original_sha256"]:
            raise ValueError("Original evidence bytes cannot be recovered")
        if target.exists():
            if target.read_bytes() != raw:
                raise FileExistsError("Existing evidence differs; preserve and investigate it")
        else:
            with target.open("xb") as stream:
                stream.write(raw)
        restored.append(str(target))
    return restored


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    print(json.dumps({"restored_exact_original_records": len(restore(args.root))}))
