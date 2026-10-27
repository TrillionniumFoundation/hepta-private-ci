"""Verify or reconstruct the complete archived V7 language evidence.

No model is loaded. Every byte, archive member and destination is checked before
any output is created. --output must be a new directory; existing files are never
overwritten. Selected model bytes are reused from the indexed repository assets.
"""

import argparse
import hashlib
import io
import json
import lzma
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import tarfile


PROJECT = Path(__file__).resolve().parent
MAX_BYTES = 128_000_000


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def safe_root(value):
    path = Path(os.path.abspath(value))
    require(not any(item.is_symlink() for item in (path, *path.parents)), "symlinked archive path")
    return path


def below(root, name):
    require(isinstance(name, str) and name and not any(c in name for c in ("\\", "\0", "\r", "\n", ":")), "invalid archive path")
    relative = PurePosixPath(name)
    require(not relative.is_absolute() and all(part not in ("", ".", "..") for part in name.split("/")), "unsafe archive path")
    require(all(relative.parts), "empty archive path")
    return safe_root(root.joinpath(*relative.parts))


def checked(root, entry, maximum=MAX_BYTES):
    count, expected = entry["bytes"], entry["sha256"]
    require(type(count) is int and 0 <= count <= maximum, "invalid byte bound")
    require(isinstance(expected, str) and re.fullmatch("[0-9a-f]{64}", expected) is not None, "invalid digest")
    path = below(root, entry["path"])
    require(path.is_file() and path.stat().st_size == count, "missing or wrong-sized file: " + entry["path"])
    with path.open("rb") as stream:
        raw = stream.read(count + 1)
    require(len(raw) == count and sha(raw) == expected, "file hash differs: " + entry["path"])
    return raw


def unique_object(pairs):
    result = {}
    for name, value in pairs:
        require(name not in result, "duplicate JSON key")
        result[name] = value
    return result


def reject_constant(value):
    raise ValueError("nonfinite JSON number: " + value)


def verify(index_directory, repository):
    root, repo = safe_root(index_directory), safe_root(repository)
    digest_path = below(root, "INDEX.sha256")
    require(digest_path.is_file() and digest_path.stat().st_size == 65, "invalid index digest file")
    index_sha = digest_path.read_text().strip()
    path = below(root, "INDEX.json")
    index_raw = checked(root, {"path": "INDEX.json", "bytes": path.stat().st_size, "sha256": index_sha}, maximum=512000)
    index = json.loads(index_raw, object_pairs_hook=unique_object, parse_constant=reject_constant)
    require(index["schema"] == "hepta.memory.v7.addressing-evidence-index.v1", "unknown evidence index")
    for artifact in index["artifacts"]:
        checked(root, artifact, maximum=512000)
    for tool in index["tools"]:
        checked(repo, tool, maximum=512000)
    archive = index["archive"]
    require(0 <= archive["bytes"] <= MAX_BYTES and 0 <= archive["tar_bytes"] <= MAX_BYTES, "archive exceeds bounds")
    require(sum(part["bytes"] for part in archive["parts"]) == archive["bytes"], "archive part lengths differ")
    packed = b"".join(checked(root, part, maximum=400000) for part in archive["parts"])
    require(sha(packed) == archive["sha256"], "whole archive hash differs")
    decompressor = lzma.LZMADecompressor(memlimit=MAX_BYTES)
    expanded = decompressor.decompress(packed, max_length=archive["tar_bytes"] + 1)
    require(decompressor.eof and not decompressor.unused_data and len(expanded) == archive["tar_bytes"], "expanded archive bounds differ")
    require(sha(expanded) == archive["tar_sha256"], "expanded archive hash differs")
    objects = {}
    expected = index["objects"]
    with tarfile.open(fileobj=io.BytesIO(expanded), mode="r:") as stream:
        members = stream.getmembers()
        require(len(members) == len(expected), "archive object count differs")
        for member in members:
            require(member.isfile() and re.fullmatch("objects/[0-9a-f]{64}", member.name) is not None, "non-regular or unsafe archive object")
            identifier = member.name.split("/")[1]
            require(identifier in expected and identifier not in objects and member.size == expected[identifier]["bytes"], "unknown, repeated or wrong-sized object")
            source = stream.extractfile(member)
            require(source is not None, "missing regular object")
            raw = source.read(member.size + 1)
            require(len(raw) == member.size and sha(raw) == identifier, "archive object bytes differ")
            objects[identifier] = raw
    external = {}
    for identifier, asset in index["external_assets"].items():
        raw = b"".join(checked(repo, part, maximum=512000) for part in asset["parts"])
        require(len(raw) == asset["bytes"] and sha(raw) == asset["sha256"], "external asset identity differs")
        external[identifier] = raw
    restored = {}
    for entry in index["original_files"]:
        logical = entry["path"]
        below(Path("/"), logical)
        require(logical not in restored, "duplicate original path")
        storage = entry["storage"]
        if storage["kind"] == "direct":
            raw = checked(root, {**entry, "path": storage["path"]}, maximum=512000)
        elif storage["kind"] == "object":
            raw = objects[storage["sha256"]]
        elif storage["kind"] == "external":
            raw = external[storage["asset"]]
        else:
            raise ValueError("unknown storage kind")
        require(len(raw) == entry["bytes"] and sha(raw) == entry["sha256"], "original bytes differ: " + logical)
        restored[logical] = raw
    require(len(restored) == index["original_file_count"] and sum(map(len, restored.values())) == index["original_bytes"], "restored inventory differs")
    return index_sha, restored


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-directory", type=Path, default=PROJECT / "evidence/addressing")
    parser.add_argument("--repo", type=Path, default=PROJECT.parents[1])
    parser.add_argument("--output", type=Path, help="new output directory; omit for a byte-only verification")
    args = parser.parse_args()
    output = safe_root(args.output) if args.output else None
    require(output is None or not output.exists(), "reconstruction output must not exist")
    index_sha, files = verify(args.index_directory, args.repo)
    if output is not None:
        output.mkdir(parents=True, exist_ok=False)
        for name, raw in files.items():
            path = below(output, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(raw)
    print(json.dumps({"verified": True, "index_sha256": index_sha, "files": len(files),
                      "original_bytes": sum(map(len, files.values())), "output": str(output) if output else None,
                      "model_executions": 0}))


if __name__ == "__main__":
    main()
