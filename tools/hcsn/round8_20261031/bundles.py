"""Lossless evidence volumes with per-file checksums and safe restoration.

Sources and concise reports remain ordinary Git files. Large raw records and
checkpoints are in bounded gzip/tar volumes, preserving their original bytes.
"""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile

HERE = Path(__file__).resolve().parent
PART_BYTES = 4 * 1024 * 1024


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


class Volumes(io.RawIOBase):
    def __init__(self, name):
        self.name, self.parts, self.current, self.size = name, [], None, 0
        self.whole_hash = hashlib.sha256()

    def writable(self):
        return True

    def write(self, data):
        size = len(data)
        self.whole_hash.update(data)
        while data:
            if self.current is None or self.size == PART_BYTES:
                if self.current is not None:
                    self.current.close()
                path = HERE / "bundles" / f"{self.name}.tar.gz.part{len(self.parts):03d}"
                self.current = path.open("xb")
                self.parts.append(path)
                self.size = 0
            amount = min(len(data), PART_BYTES - self.size)
            self.current.write(data[:amount])
            data = data[amount:]
            self.size += amount
        return size

    def close(self):
        if self.current is not None:
            self.current.close()
        super().close()


def pack(component):
    directory = HERE / component / "evidence"
    destination = HERE / "bundles"
    destination.mkdir(exist_ok=True)
    index_path = destination / (component + ".json")
    if index_path.exists():
        raise FileExistsError(index_path)
    files = sorted(p for p in directory.rglob("*") if p.is_file()
        and "__pycache__" not in p.parts and p.name != "RAW_NATIVE_EVIDENCE.tar.gz")
    members = {}
    writer = Volumes(component)
    with writer, gzip.GzipFile(fileobj=writer, mode="wb", filename="", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w|") as archive:
            for path in files:
                if path.is_symlink():
                    raise ValueError("evidence symlinks are not archived")
                relative = path.relative_to(HERE).as_posix()
                size, sha = path.stat().st_size, digest(path)
                members[relative] = {"bytes": size, "sha256": sha}
                info = tarfile.TarInfo(relative)
                info.size, info.mode, info.mtime = size, 0o644, 0
                with path.open("rb") as stream:
                    archive.addfile(info, stream)
                if digest(path) != sha:
                    raise RuntimeError("evidence changed while being archived: " + relative)
    manifest = {"schema": "hepta.r8.evidence-volumes.v1", "component": component,
        "archive_sha256": writer.whole_hash.hexdigest(), "files": members,
        "parts": [{"path": p.relative_to(HERE).as_posix(), "bytes": p.stat().st_size,
            "sha256": digest(p)} for p in writer.parts]}
    index_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"manifest": str(index_path), "files": len(files),
        "parts": len(writer.parts), "bytes": sum(p.stat().st_size for p in writer.parts)}))


class Concatenated(io.RawIOBase):
    def __init__(self, paths):
        self.paths, self.index, self.stream = paths, 0, None

    def readable(self):
        return True

    def read(self, size=-1):
        if size < 0:
            raise ValueError("bounded streaming reads required")
        result = bytearray()
        while len(result) < size and self.index < len(self.paths):
            if self.stream is None:
                self.stream = self.paths[self.index].open("rb")
            chunk = self.stream.read(size - len(result))
            if chunk:
                result.extend(chunk)
            else:
                self.stream.close()
                self.stream = None
                self.index += 1
        return bytes(result)

    def close(self):
        if self.stream is not None:
            self.stream.close()
        super().close()


def restore(component, verify_only=False):
    manifest = json.loads((HERE / "bundles" / (component + ".json")).read_text())
    paths, total = [], hashlib.sha256()
    for part in manifest["parts"]:
        relative = PurePosixPath(part["path"])
        if relative.is_absolute() or ".." in relative.parts or relative.parts[:1] != ("bundles",):
            raise ValueError("invalid evidence volume path")
        path = HERE.joinpath(*relative.parts)
        if path.stat().st_size != part["bytes"] or digest(path) != part["sha256"]:
            raise ValueError("volume checksum mismatch: " + str(path))
        paths.append(path)
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                total.update(block)
    if total.hexdigest() != manifest["archive_sha256"]:
        raise ValueError("whole archive checksum mismatch")
    seen = set()
    with Concatenated(paths) as source, tarfile.open(fileobj=source, mode="r|gz") as archive:
        for entry in archive:
            relative = PurePosixPath(entry.name)
            if not entry.isfile() or relative.is_absolute() or ".." in relative.parts or entry.name in seen:
                raise ValueError("invalid or duplicate archive member")
            if relative.parts[:2] != (component, "evidence"):
                raise ValueError("archive member is outside its evidence directory")
            expected = manifest["files"].get(entry.name)
            if expected is None or expected["bytes"] != entry.size:
                raise ValueError("unregistered archive member")
            data = archive.extractfile(entry).read()
            if hashlib.sha256(data).hexdigest() != expected["sha256"]:
                raise ValueError("archive member checksum mismatch")
            path = HERE.joinpath(*relative.parts)
            if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent.is_relative_to(HERE)):
                raise ValueError("symlink in evidence destination")
            if path.exists():
                if digest(path) != expected["sha256"]:
                    raise ValueError("refusing to replace changed evidence: " + str(path))
            elif not verify_only:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("xb") as stream:
                    stream.write(data)
            seen.add(entry.name)
    if seen != set(manifest["files"]):
        raise ValueError("incomplete evidence archive")
    print(json.dumps({"component": component, "verified_files": len(seen), "verify_only": verify_only}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("pack", "restore", "verify"))
    parser.add_argument("component", choices=("state_task", "value_calibration", "native_owner"))
    args = parser.parse_args()
    if args.operation == "pack":
        pack(args.component)
    else:
        restore(args.component, verify_only=args.operation == "verify")
