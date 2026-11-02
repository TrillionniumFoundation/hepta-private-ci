"""Restore content-addressed evidence without extracting untrusted tar paths."""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import tarfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def relative(value):
    path = PurePosixPath(value)
    if (not isinstance(value, str) or not value or value != path.as_posix()
            or path.is_absolute() or any(x in ("", ".", "..") for x in path.parts)
            or "\\" in value or ":" in value or "\0" in value):
        raise ValueError("unsafe relative path")
    return Path(*path.parts)


def unpack(component, record, prefix, raw_cap, gzip_cap):
    if not (0 <= record["gzip_bytes"] <= gzip_cap and 0 <= record["raw_bytes"] <= raw_cap):
        raise ValueError("archive capacity")
    compressed = bytearray()
    for part in record["parts"]:
        path = relative(part["path"])
        if path.parts[0] != prefix or not 0 <= part["size"] <= 450000:
            raise ValueError("part profile")
        source = component / path
        for parent in [source, *source.parents]:
            if parent == component.parent:
                break
            if parent.is_symlink():
                raise ValueError("symlink part path")
        data = source.read_bytes()
        if len(data) != part["size"] or digest(data) != part["sha256"]:
            raise ValueError("part identity")
        compressed.extend(data)
        if len(compressed) > record["gzip_bytes"]:
            raise ValueError("archive capacity")
    if len(compressed) != record["gzip_bytes"] or digest(compressed) != record["gzip_sha256"]:
        raise ValueError("archive identity")
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as zipped:
        data = zipped.read(record["raw_bytes"] + 1)
    if len(data) != record["raw_bytes"] or digest(data) != record["raw_sha256"]:
        raise ValueError("raw identity")
    return data


def restore(component, destination):
    manifest = json.loads((component / "EVIDENCE_TRANSPORT.json").read_text())
    if manifest["schema"] != "hcsn-evidence-transport-v2":
        raise ValueError("unsupported transport")
    maximum = manifest["file_count_cap"]
    if type(maximum) is not int or not 0 <= maximum <= 65536:
        raise ValueError("file capacity")
    mapping = unpack(component, manifest["file_map"], "map_transport", 64 * 1024**2, 64 * 1024**2)
    entries = json.loads(mapping)["files"]
    if len(entries) > maximum:
        raise ValueError("file capacity")
    data = unpack(component, manifest["archive"], "transport", 512 * 1024**2, 256 * 1024**2)
    if manifest["logical_bytes_cap"] > 512 * 1024**2 or sum(item["size"] for item in entries) > manifest["logical_bytes_cap"]:
        raise ValueError("logical restore capacity")
    expected, paths = {}, set()
    for entry in entries:
        relative(entry["path"])
        if (entry["path"] in paths or not re.fullmatch("[0-9a-f]{64}", entry["sha256"])
                or not 0 <= entry["size"] <= 512 * 1024**2 or entry["mode"] not in (0o600, 0o644, 0o700, 0o755)):
            raise ValueError("invalid file manifest")
        paths.add(entry["path"])
        name = "objects/" + entry["sha256"]
        if name in expected and expected[name] != entry["size"]:
            raise ValueError("object size conflict")
        expected[name] = entry["size"]
    objects = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as tar:
        for member in tar:
            relative(member.name)
            if not member.isfile() or member.name not in expected or member.name in objects:
                raise ValueError("unexpected or linked archive member")
            if member.size != expected[member.name]:
                raise ValueError("member size")
            stream = tar.extractfile(member)
            if stream is None:
                raise ValueError("missing member")
            payload = stream.read(member.size + 1)
            if len(payload) != member.size or digest(payload) != member.name.removeprefix("objects/"):
                raise ValueError("member identity")
            objects[member.name] = payload
    if set(objects) != set(expected):
        raise ValueError("missing objects")
    if destination.is_symlink():
        raise ValueError("symlink destination")
    destination.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        path = destination / relative(entry["path"])
        for parent in [path, *path.parents]:
            if parent == destination.parent:
                break
            if parent.is_symlink():
                raise ValueError("symlink restore path")
        if path.exists() and (not path.is_file() or path.read_bytes() != objects["objects/" + entry["sha256"]]):
            raise ValueError("existing different file")
    for entry in entries:
        path = destination / relative(entry["path"])
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, entry["mode"])
        with os.fdopen(descriptor, "wb") as output:
            output.write(objects["objects/" + entry["sha256"]])
    return dict(restored_files=len(entries), unique_objects=len(objects), archive_sha256=manifest["archive"]["gzip_sha256"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    base = Path(__file__).resolve().parent
    print(json.dumps(restore(base, args.destination or base), sort_keys=True))
