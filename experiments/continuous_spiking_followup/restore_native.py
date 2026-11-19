"""Restore the exact archived Linux native research host without recompilation."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import zlib


def restore(source, destination):
    source, destination = Path(source), Path(destination)
    manifest = json.loads((source / "MANIFEST.json").read_text())
    if manifest["schema"] != "hcsn-pinned-native-binary-v1":
        raise ValueError("unsupported binary archive")
    if not 0 < manifest["binary_bytes"] <= 8 * 1024 * 1024:
        raise ValueError("native binary size is outside the bounded archive contract")
    parts = []
    for index, entry in enumerate(manifest["parts"]):
        if entry["file"] != f"host.part-{index:03d}.gzpart" or not re.fullmatch(
            r"[0-9a-f]{64}", entry["sha256"]
        ):
            raise ValueError("invalid binary part identity")
        path = source / entry["file"]
        if path.is_symlink() or not 0 < path.stat().st_size <= 400000:
            raise ValueError("invalid binary part path or size")
        raw = path.read_bytes()
        if (
            len(raw) != entry["bytes"]
            or hashlib.sha256(raw).hexdigest() != entry["sha256"]
        ):
            raise ValueError("native binary part hash/size mismatch")
        parts.append(raw)
    if not parts or len(parts) > 32:
        raise ValueError("native binary part count out of range")
    compressed = b"".join(parts)
    if hashlib.sha256(compressed).hexdigest() != manifest["compressed_sha256"]:
        raise ValueError("compressed native binary hash mismatch")
    decoder = zlib.decompressobj(wbits=31)
    raw = decoder.decompress(compressed, manifest["binary_bytes"] + 1)
    if (
        not decoder.eof
        or decoder.unused_data
        or decoder.unconsumed_tail
        or len(raw) != manifest["binary_bytes"]
        or hashlib.sha256(raw).hexdigest() != manifest["binary_sha256"]
    ):
        raise ValueError("restored native binary hash/size mismatch")
    if destination.is_symlink():
        raise ValueError("refusing to restore over a symlink")
    if destination.exists():
        if (
            not destination.is_file()
            or hashlib.sha256(destination.read_bytes()).hexdigest()
            != manifest["binary_sha256"]
        ):
            raise FileExistsError("refusing to overwrite a differing native binary")
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    destination.chmod(0o755)
    return {
        "binary": str(destination),
        "sha256": manifest["binary_sha256"],
        "bytes": len(raw),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    arguments = parser.parse_args()
    print(json.dumps(restore(arguments.source, arguments.destination)))
