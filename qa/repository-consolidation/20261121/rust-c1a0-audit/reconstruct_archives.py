#!/usr/bin/env python3
"""Reconstruct the recorded archives without extracting or executing their contents."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile


PART_BYTES = 491520


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def verify_bytes(data: bytes, record: dict, label: str) -> None:
    require(len(data) == record["bytes"], f"Size check failed: {label}")
    require(
        hashlib.sha256(data).hexdigest() == record["sha256"],
        f"SHA256 check failed: {label}",
    )
    digest = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data)
    require(digest.hexdigest() == record["git_blob"], f"Git blob check failed: {label}")


def verify_record(record: dict, label: str) -> None:
    require(
        type(record["bytes"]) is int and record["bytes"] > 0, f"Invalid size: {label}"
    )
    for field, length in (("sha256", 64), ("git_blob", 40)):
        value = record[field]
        require(
            isinstance(value, str)
            and re.fullmatch(r"[0-9a-f]+", value) is not None
            and len(value) == length,
            f"Invalid digest: {label}",
        )


def read_expected(path: Path, record: dict, label: str) -> bytes:
    require(
        path.is_file() and not path.is_symlink(), f"Expected a regular file: {label}"
    )
    with path.open("rb") as stream:
        data = stream.read(record["bytes"] + 1)
    verify_bytes(data, record, label)
    return data


def load_archives(package: Path) -> list[tuple[dict, bytes]]:
    manifest = json.loads((package / "ARCHIVE-PARTS.json").read_text(encoding="utf-8"))
    require(manifest["schema_version"] == 1, "Unsupported archive manifest version")
    require(manifest["maximum_part_bytes"] == PART_BYTES, "Unexpected part size limit")
    require(
        isinstance(manifest["archives"], list) and manifest["archives"],
        "No archives recorded",
    )
    names = set()
    assembled = []
    for archive in manifest["archives"]:
        name = archive["name"]
        require(
            isinstance(name, str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name) is not None
            and name not in names,
            "Invalid or duplicate archive name",
        )
        names.add(name)
        verify_record(archive, name)
        parts = archive["parts"]
        require(isinstance(parts, list), f"Invalid part list: {name}")
        require(
            len(parts) == (archive["bytes"] + PART_BYTES - 1) // PART_BYTES,
            f"Wrong part count: {name}",
        )
        blocks = []
        offset = 0
        for number, part in enumerate(parts, 1):
            relative = f"archive-parts/{name}/part-{number:03}.bin"
            require(
                part["path"] == relative
                and part["index"] == number
                and part["offset"] == offset,
                f"Unexpected part order: {name}",
            )
            verify_record(part, relative)
            require(
                part["bytes"] == min(PART_BYTES, archive["bytes"] - offset),
                f"Unexpected part size: {relative}",
            )
            path = package / relative
            require(
                path.resolve(strict=True) == path,
                f"Part path must not use a symbolic link: {relative}",
            )
            blocks.append(read_expected(path, part, relative))
            offset += part["bytes"]
        data = b"".join(blocks)
        verify_bytes(data, archive, name)
        assembled.append((archive, data))
    return assembled


def check_existing(path: Path, archive: dict) -> bool:
    if not path.exists() and not path.is_symlink():
        return False
    try:
        read_expected(path, archive, archive["name"])
    except (OSError, ValueError) as error:
        raise ValueError(
            f"Existing output differs; refusing to overwrite: {path}"
        ) from error
    return True


def publish_archive(output: Path, archive: dict, data: bytes) -> str:
    destination = output / archive["name"]
    if check_existing(destination, archive):
        return "existing_file_verified"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="archive-reconstruction-", suffix=".tmp", dir=output, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            # A hard link publishes the checked file without replacing an entry
            # created by another process after the earlier existence check.
            os.link(temporary, destination)
        except FileExistsError:
            require(
                check_existing(destination, archive),
                "Existing output disappeared during publication",
            )
            return "existing_file_verified"
        return "archive_reconstructed"
    finally:
        if temporary is not None:
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="explicit output directory; existing different files are never replaced",
    )
    args = parser.parse_args()
    try:
        package = Path(__file__).resolve().parent
        assembled = load_archives(package)
        output = args.output_dir.expanduser().resolve()
        require(
            not output.exists() or output.is_dir(), "Output path is not a directory"
        )
        # Validate every part and both complete archives before creating output.
        for archive, _ in assembled:
            check_existing(output / archive["name"], archive)
        output.mkdir(parents=True, exist_ok=True)
        results = []
        for archive, data in assembled:
            state = publish_archive(output, archive, data)
            results.append(
                {
                    "name": archive["name"],
                    "status": state,
                    "bytes": archive["bytes"],
                    "sha256": archive["sha256"],
                    "git_blob": archive["git_blob"],
                    "output": str(output / archive["name"]),
                }
            )
        print(json.dumps({"status": "verified", "archives": results}, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Cannot reconstruct archives: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
