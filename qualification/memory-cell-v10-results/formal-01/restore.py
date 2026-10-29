"""Verify every retained formal file, optionally restoring into a new directory."""

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    transport = json.loads((root / "TRANSPORT.json").read_bytes())
    assert transport["schema"] == "hepta.memory.v10.formal-transport.v1"
    manifest_bytes = (root / "RAW_FILES.json").read_bytes()
    assert digest(manifest_bytes) == transport["files_manifest_sha256"]
    manifest = json.loads(manifest_bytes)
    expected = {row["path"]: row for row in manifest["files"]}
    assert len(expected) == len(manifest["files"]) == transport["file_count"]
    chunks = []
    for number, part in enumerate(transport["parts"]):
        assert part["path"] == f"raw.tar.xz.part-{number:03d}"
        path = root / part["path"]
        assert path.is_file() and not path.is_symlink()
        data = path.read_bytes()
        assert len(data) == part["bytes"] and digest(data) == part["sha256"]
        chunks.append(data)
    compressed = b"".join(chunks)
    assert len(compressed) == transport["archive"]["bytes"]
    assert digest(compressed) == transport["archive"]["sha256"]
    if args.output is not None:
        assert not any(path.is_symlink() for path in (args.output, *args.output.parents))
        args.output.mkdir(parents=True, exist_ok=False)
    seen, total = set(), 0
    with tarfile.open(fileobj=io.BytesIO(compressed), mode="r|xz") as archive:
        for member in archive:
            name = PurePosixPath(member.name)
            assert member.isfile() and not name.is_absolute() and ".." not in name.parts
            assert str(name) == member.name and member.name in expected and member.name not in seen
            row = expected[member.name]
            assert member.size == row["bytes"]
            data = archive.extractfile(member).read(member.size + 1)
            assert len(data) == row["bytes"] and digest(data) == row["sha256"]
            if args.output is not None:
                target = args.output / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as handle:
                    handle.write(data)
            seen.add(member.name)
            total += len(data)
    assert seen == set(expected) and total == transport["uncompressed_file_bytes"]
    print(json.dumps({"verified": True, "files": len(seen), "bytes": total,
                      "output": str(args.output) if args.output is not None else None}))


if __name__ == "__main__":
    main()
