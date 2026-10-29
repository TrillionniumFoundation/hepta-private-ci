#!/usr/bin/env python3
"""Verify retained upstream sources and the exact security compatibility patches."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re


ROOT = Path(__file__).resolve().parents[1]
INDEX = "codex-rs/third_party/SECURITY_PATCHES.json"
PATCH_MANIFEST = "HEPTA_PATCH_PROVENANCE.json"
UPSTREAM_MANIFEST = "HEPTA_UPSTREAM_PROVENANCE.json"
PATCH = "HEPTA_COMPATIBILITY.patch"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate manifest key: {key}")
        result[key] = value
    return result


def document(path):
    return json.loads(path.read_text(), object_pairs_hook=unique_object)


def safe_path(root, relative):
    path = PurePosixPath(relative)
    if (
        not isinstance(relative, str)
        or not relative
        or path.is_absolute()
        or any(part in {".", ".."} for part in path.parts)
        or path.as_posix() != relative
        or "\\" in relative
        or ":" in relative
    ):
        raise ValueError(f"invalid vendor path: {relative!r}")
    target = root.joinpath(*path.parts)
    for parent in (target, *target.parents):
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError(f"vendor symlink is forbidden: {relative}")
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"vendor path escapes root: {relative}")
    return target


def original_from_patch(current, patch):
    """Reverse an exact unified diff, checking both content and hunk coordinates."""
    lines = patch.splitlines(keepends=True)
    offset = 0
    reconstructed = {}
    while offset < len(lines):
        if not lines[offset].startswith("--- a/"):
            raise ValueError("invalid original patch header")
        name = lines[offset][6:].rstrip("\n")
        if offset + 1 >= len(lines) or lines[offset + 1] != f"+++ b/{name}\n":
            raise ValueError("patch paths do not match")
        if name in reconstructed or name not in current:
            raise ValueError("duplicate or undeclared patched file")
        actual = current[name].decode("utf-8").splitlines(keepends=True)
        before = []
        cursor = 0
        hunks = 0
        offset += 2
        while offset < len(lines) and not lines[offset].startswith("--- a/"):
            match = re.fullmatch(
                r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:.*)\n",
                lines[offset],
            )
            if not match:
                raise ValueError("invalid patch hunk header")
            old_start, old_count, new_start, new_count = (
                int(value) if value is not None else 1 for value in match.groups()
            )
            start = max(0, new_start - 1)
            if start < cursor or start > len(actual):
                raise ValueError("patch hunk is out of order")
            before.extend(actual[cursor:start])
            if len(before) != max(0, old_start - 1):
                raise ValueError("original patch coordinate mismatch")
            cursor = start
            consumed = produced = 0
            offset += 1
            while offset < len(lines) and lines[offset][:1] in {" ", "+", "-"}:
                if lines[offset].startswith("--- a/"):
                    break
                operation, content = lines[offset][0], lines[offset][1:]
                if operation in {" ", "+"}:
                    if cursor >= len(actual) or actual[cursor] != content:
                        raise ValueError("patch does not match retained source")
                    cursor += 1
                    consumed += 1
                if operation in {" ", "-"}:
                    before.append(content)
                    produced += 1
                offset += 1
            if consumed != new_count or produced != old_count:
                raise ValueError("patch hunk length mismatch")
            hunks += 1
        if not hunks:
            raise ValueError("patch has no hunks")
        before.extend(actual[cursor:])
        reconstructed[name] = "".join(before).encode("utf-8")
    return reconstructed


def verify_package(root, entry):
    relative = entry["directory"]
    if not relative.startswith("codex-rs/third_party/"):
        raise ValueError("vendor package is outside the third-party boundary")
    directory = safe_path(root, relative)
    manifest_path = safe_path(directory, PATCH_MANIFEST)
    if digest(manifest_path.read_bytes()) != entry["manifest_sha256"]:
        raise ValueError(f"patch manifest changed: {relative}")
    manifest = document(manifest_path)
    if manifest["schema"] != "hepta.security-vendor-patch.v1":
        raise ValueError("unsupported vendor patch manifest")
    upstream_path = safe_path(directory, UPSTREAM_MANIFEST)
    if digest(upstream_path.read_bytes()) != manifest["upstream_manifest_sha256"]:
        raise ValueError("upstream manifest changed")
    upstream = document(upstream_path)
    if upstream["sha256"] != manifest["upstream_archive_sha256"]:
        raise ValueError("upstream archive identity mismatch")
    expected = manifest["files"]
    actual = set()
    for file in directory.rglob("*"):
        name = file.relative_to(directory).as_posix()
        safe_path(directory, name)
        if file.is_file() and name != PATCH_MANIFEST:
            actual.add(name)
    if actual != set(expected):
        raise ValueError(f"vendor file set differs: {relative}")
    contents = {}
    for name, identity in expected.items():
        data = safe_path(directory, name).read_bytes()
        if len(data) != identity["bytes"] or digest(data) != identity["sha256"]:
            raise ValueError(f"vendor file changed: {relative}/{name}")
        contents[name] = data
    restored = original_from_patch(contents, contents[PATCH].decode("utf-8"))
    if set(restored) != set(manifest["modified_upstream_files"]):
        raise ValueError("declared compatibility edits do not match the patch")
    for name, identity in upstream["upstream_files"].items():
        safe_path(directory, name)
        data = restored.get(name, contents.get(name))
        if data is None or digest(data) != identity:
            raise ValueError(f"upstream identity mismatch: {relative}/{name}")
    return {
        "name": upstream["name"],
        "version": upstream["version"],
        "upstream_archive_sha256": upstream["sha256"],
        "files": len(contents),
        "modified_upstream_files": sorted(restored),
        "bytes": sum(len(data) for data in contents.values()),
    }


def verify(root=ROOT):
    root = Path(root)
    index = document(safe_path(root, INDEX))
    if index["schema"] != "hepta.security-vendor-index.v1":
        raise ValueError("unsupported security vendor index")
    directories = [entry["directory"] for entry in index["packages"]]
    if not directories or len(directories) != len(set(directories)):
        raise ValueError("empty or duplicate vendor package registration")
    packages = [verify_package(root, entry) for entry in index["packages"]]
    return {"status": "verified", "packages": packages}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.root), indent=2, sort_keys=True))
    except (KeyError, TypeError, ValueError, OSError) as error:
        parser.exit(1, f"Security vendor verification failed: {error}\n")


if __name__ == "__main__":
    main()
