"""Restore exact, source-bound research ELF artifacts; never executes them."""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re


def sha(data):
    return hashlib.sha256(data).hexdigest()


def safe_path(value):
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or value != path.as_posix()
            or any(x in (".", "..") for x in path.parts) or "\\" in value or ":" in value):
        raise ValueError("unsafe relative path")
    return Path(*path.parts)


def write_exact(path, content, boundary):
    for parent in [path, *path.parents]:
        if parent == boundary.parent:
            break
        if parent.is_symlink():
            raise ValueError("symlink binary destination")
    if path.exists():
        if not path.is_file() or path.read_bytes() != content:
            raise ValueError("existing different binary")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o755)
    with os.fdopen(descriptor, "wb") as output:
        output.write(content)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--restore-evidence-aliases", action="store_true")
    args = parser.parse_args()
    component = Path(__file__).resolve().parent
    destination = args.destination or component / "restored_binaries"
    manifest = json.loads((component / "BINARY_ARTIFACTS.json").read_text())
    if manifest["schema"] != "hcsn-fixed-binary-artifacts-v1":
        raise ValueError("binary artifact schema")
    results = []
    for item in manifest["binaries"]:
        if not re.fullmatch("[0-9a-f]{64}", item["sha256"]) or not 0 < item["bytes"] <= 64 * 1024**2:
            raise ValueError("binary profile")
        compressed = bytearray()
        for part in item["parts"]:
            path = component / safe_path(part["path"])
            if not part["path"].startswith("binary_transport/") or not 0 < part["bytes"] <= 450000:
                raise ValueError("binary part profile")
            for parent in [path, *path.parents]:
                if parent == component.parent:
                    break
                if parent.is_symlink():
                    raise ValueError("symlink binary part")
            data = path.read_bytes()
            if len(data) != part["bytes"] or sha(data) != part["sha256"]:
                raise ValueError("binary part identity")
            compressed.extend(data)
            if len(compressed) > item["gzip_bytes"] or len(compressed) > 64 * 1024**2:
                raise ValueError("binary archive capacity")
        if len(compressed) != item["gzip_bytes"] or sha(compressed) != item["gzip_sha256"]:
            raise ValueError("binary gzip identity")
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as zipped:
            data = zipped.read(item["bytes"] + 1)
        if len(data) != item["bytes"] or sha(data) != item["sha256"] or not data.startswith(b"\x7fELF"):
            raise ValueError("binary identity")
        write_exact(destination / item["sha256"], data, destination)
        if args.restore_evidence_aliases:
            for alias in item["evidence_aliases"]:
                write_exact(component / safe_path(alias), data, component)
        results.append(dict(sha256=item["sha256"], bytes=len(data)))
    print(json.dumps(dict(restored=results, executable_path=str(destination / manifest["formal_binary_sha256"])), sort_keys=True))


if __name__ == "__main__":
    main()
