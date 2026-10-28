"""Export complete native qualification diagnostics separately from large inputs."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tarfile


SUFFIXES = {".json", ".jsonl", ".stdout", ".stderr", ".log", ".xml", ".txt"}
PART_BYTES = 128 * 1024 * 1024
MAX_PARTS = 8
MAX_FILES = 5000
MAX_PATH_BYTES = 1024


def identity(path):
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(f"Diagnostic is not a regular file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError(f"Diagnostic changed while opening: {path}")
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
        after = os.fstat(stream.fileno())
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f"Diagnostic changed while reading: {path}")
    return {"bytes": before.st_size, "sha256": digest.hexdigest()}


def inventory(source):
    if source.is_symlink() or not source.is_dir():
        raise ValueError("Diagnostic source must be an existing physical directory")
    selected = {}
    for directory, folders, files in os.walk(source, followlinks=False):
        folders.sort()
        for name in folders:
            if (Path(directory) / name).is_symlink():
                raise ValueError("Diagnostic traversal encountered a directory link")
        for name in sorted(files):
            path = Path(directory) / name
            if path.suffix not in SUFFIXES:
                continue
            relative = path.relative_to(source).as_posix()
            if len(relative.encode()) > MAX_PATH_BYTES or len(selected) >= MAX_FILES:
                raise ValueError("Diagnostic inventory exceeds its explicit bound")
            selected[relative] = identity(path)
    return dict(sorted(selected.items()))


class Parts:
    """A bounded, ordered byte stream; concatenating all parts restores the tar."""

    def __init__(self, directory, part_bytes, max_parts):
        if part_bytes <= 0 or max_parts <= 0:
            raise ValueError("Diagnostic part bounds must be positive")
        self.directory = directory
        self.part_bytes = part_bytes
        self.max_parts = max_parts
        self.parts = []
        self.stream = None
        self.part_digest = None
        self.digest = hashlib.sha256()
        self.part_size = 0

    def close(self):
        if self.stream is not None:
            self.stream.close()
            self.parts[-1].update(
                bytes=self.part_size, sha256=self.part_digest.hexdigest()
            )
            self.stream = None

    def write(self, data):
        total = len(data)
        view = memoryview(data)
        while view:
            if self.stream is None:
                if len(self.parts) >= self.max_parts:
                    raise ValueError(
                        "Complete diagnostics exceed the export part bound"
                    )
                name = f"part-{len(self.parts) + 1:02d}.tar.part"
                self.stream = (self.directory / name).open("xb")
                self.parts.append({"file": name})
                self.part_digest = hashlib.sha256()
                self.part_size = 0
            chunk = view[: self.part_bytes - self.part_size]
            self.stream.write(chunk)
            self.part_digest.update(chunk)
            self.digest.update(chunk)
            self.part_size += len(chunk)
            view = view[len(chunk) :]
            if self.part_size == self.part_bytes:
                self.close()
        return total


class HashedReader:
    def __init__(self, stream):
        self.stream = stream
        self.digest = hashlib.sha256()

    def read(self, size):
        data = self.stream.read(size)
        self.digest.update(data)
        return data


def pack(source, files, parts):
    with tarfile.open(fileobj=parts, mode="w|", format=tarfile.PAX_FORMAT) as archive:
        for relative, expected in files.items():
            path = source / relative
            if path.is_symlink():
                raise ValueError(f"Diagnostic became a link: {relative}")
            with path.open("rb") as stream:
                opened = os.fstat(stream.fileno())
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or opened.st_size != expected["bytes"]
                ):
                    raise ValueError(f"Diagnostic size or type changed: {relative}")
                reader = HashedReader(stream)
                member = tarfile.TarInfo(relative)
                member.size = expected["bytes"]
                member.mode = 0o600
                archive.addfile(member, reader)
                if reader.digest.hexdigest() != expected["sha256"] or stream.read(1):
                    raise ValueError(f"Diagnostic bytes changed: {relative}")


def probe_records(files):
    records = []
    for relative in files:
        match = re.fullmatch(
            r"(preparation/controller-commands/)([0-9]+)-start-native-tool-probe\.stdout",
            relative,
        )
        if match:
            prefix, number = match.groups()
            paths = {
                "stdout": relative,
                "stderr": relative.removesuffix(".stdout") + ".stderr",
                "start": f"{prefix}{number}-START.json",
                "end": f"{prefix}{number}-END.json",
            }
            records.append(
                {
                    key: {"path": path, "identity": files.get(path)}
                    for key, path in paths.items()
                }
            )
    return records


def collect(source, output, *, part_bytes=PART_BYTES, max_parts=MAX_PARTS):
    source, output = Path(source).absolute(), Path(output).absolute()
    if output.resolve().is_relative_to(source.resolve()):
        raise ValueError("Diagnostic exports must be outside the original evidence")
    output.mkdir(parents=True, exist_ok=False)
    parts = Parts(output, part_bytes, max_parts)
    result = {
        "schema": "hepta.synapse.diagnostic-export.v1",
        "complete": False,
        "source_directory": str(source),
        "selection": {"recursive_suffixes": sorted(SUFFIXES)},
        "bounds": {
            "part_bytes": part_bytes,
            "max_parts": max_parts,
            "max_files": MAX_FILES,
            "max_path_bytes": MAX_PATH_BYTES,
        },
        "files": {},
        "parts": [],
        "reconstruction": "Verify part hashes, concatenate parts in listed order, open as tar, then verify every member against files. An incomplete export is not a complete diagnostic record.",
        "original_artifact_unchanged": True,
        "qualification_or_promotion": False,
        "workflow": {
            name: os.environ.get(name)
            for name in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_SHA")
        },
    }
    try:
        result["files"] = inventory(source)
        if not result["files"]:
            raise ValueError("No actual diagnostic files were found")
        pack(source, result["files"], parts)
        parts.close()
        for part in parts.parts:
            expected = {key: part[key] for key in ("bytes", "sha256")}
            if identity(output / part["file"]) != expected:
                raise ValueError("Diagnostic part failed complete readback")
        result["complete"] = True
    except (OSError, ValueError, tarfile.TarError) as error:
        result["error"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        parts.close()
        result["parts"] = parts.parts
        result["tar_sha256"] = parts.digest.hexdigest()
        result["native_tool_probe"] = probe_records(result["files"])
        result["file_count"] = len(result["files"])
        result["selected_bytes"] = sum(
            item["bytes"] for item in result["files"].values()
        )
        (output / "DIAGNOSTICS.json").write_text(json.dumps(result, indent=2) + "\n")
        if github_output := os.environ.get("GITHUB_OUTPUT"):
            with Path(github_output).open("a") as stream:
                stream.write(f"part_count={len(parts.parts)}\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = collect(args.source, args.output)
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "complete",
                    "file_count",
                    "selected_bytes",
                    "parts",
                    "native_tool_probe",
                )
            }
        )
    )
    return 0 if result["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
