"""Restore the unchanged published Linux research host after all hash checks."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path


VENDOR = Path(__file__).with_name("native_vendor")


def restore(destination):
    manifest = json.loads((VENDOR / "MANIFEST.json").read_text())
    parts = []
    for item in manifest["parts"]:
        data = (VENDOR / item["file"]).read_bytes()
        if len(data) != item["bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise ValueError("Native archive part identity mismatch")
        parts.append(data)
    compressed = b"".join(parts)
    if (len(compressed) != manifest["compressed_bytes"] or
            hashlib.sha256(compressed).hexdigest() != manifest["compressed_sha256"]):
        raise ValueError("Native compressed archive identity mismatch")
    binary = gzip.decompress(compressed)
    if (len(binary) != manifest["binary_bytes"] or
            hashlib.sha256(binary).hexdigest() != manifest["binary_sha256"]):
        raise ValueError("Native executable identity mismatch")
    destination = Path(destination).absolute()
    if destination.is_symlink():
        raise ValueError("Native destination must not be a symbolic link")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.read_bytes() != binary:
            raise ValueError("Refusing to overwrite a different native executable")
    else:
        with destination.open("xb") as stream:
            stream.write(binary)
    destination.chmod(0o755)
    return destination, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    path, manifest = restore(args.destination)
    print(json.dumps({"path": str(path), "sha256": manifest["binary_sha256"],
                      "rebuilt": False, "production_authority": False}))


if __name__ == "__main__":
    main()
