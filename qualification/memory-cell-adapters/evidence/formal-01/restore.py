"""Verify and restore the exact fresh-reader evidence, without fitting a model."""

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="new absolute directory")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    output = args.output.absolute()
    if output.exists() or any(path.is_symlink() for path in (output, *output.parents)):
        raise ValueError("new nonsymlink destination required")
    index = json.loads((root / "ARCHIVE.json").read_bytes())
    chunks = []
    for part in index["parts"]:
        relative = PurePosixPath(part["path"])
        if relative.is_absolute() or len(relative.parts) != 1:
            raise ValueError("invalid part path")
        raw = (root / part["path"]).read_bytes()
        if identity(raw) != {key: part[key] for key in ("bytes", "sha256")} or len(raw) >= 512000:
            raise ValueError("part size or digest mismatch")
        chunks.append(raw)
    compressed = b"".join(chunks)
    if identity(compressed) != index["archive"]:
        raise ValueError("archive identity mismatch")
    files = {}
    with tarfile.open(fileobj=io.BytesIO(compressed), mode="r:xz") as archive:
        for member in archive.getmembers():
            relative = PurePosixPath(member.name)
            if (not member.isfile() or relative.is_absolute() or ".." in relative.parts
                    or str(relative) != member.name or member.name not in index["files"]
                    or member.name in files or member.size != index["files"][member.name]["bytes"]):
                raise ValueError("unexpected archive member")
            raw = archive.extractfile(member).read()
            if identity(raw) != index["files"][member.name]:
                raise ValueError("member identity mismatch")
            files[member.name] = raw
    if set(files) != set(index["files"]):
        raise ValueError("incomplete archive")
    output.mkdir(parents=True, exist_ok=False)
    for name, raw in files.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(raw)
    print(json.dumps({"output": str(output), "files": len(files),
                      "restored_bytes": sum(map(len, files.values())), "all_digests_verified": True,
                      "fitting_performed": False}, sort_keys=True))


if __name__ == "__main__":
    main()
