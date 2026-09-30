#!/usr/bin/env python3
"""Retain and verify bounded historical retrieval microbenchmark archives.

This binds observed bytes and source identity, not product SLOs or authority.
A checked-in receipt remains independently reviewable after Actions retention.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
import zipfile

MEMBERS = {"host.txt", "sqlite-owner.log", "hnmf-512.log", "hnmf-structural.log"}
PHASES = {"sqlite-owner.log": "sqlite-owner", "hnmf-512.log": "hnmf",
          "hnmf-structural.log": "hnmf-full-ceiling"}
MAX_ARCHIVE = 4 * 1024 * 1024
MAX_EXPANDED = 8 * 1024 * 1024
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
GIT_SHA = re.compile(r"[0-9a-f]{40}\Z")


class ArchiveError(ValueError):
    """Archive, source identity, or retained receipt failed validation."""


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ArchiveError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_json(data):
    def invalid_constant(value):
        raise ArchiveError(f"invalid JSON number: {value}")
    return json.loads(data, object_pairs_hook=unique_object, parse_constant=invalid_constant)


def bounded_read(path, maximum):
    with Path(path).open("rb") as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise ArchiveError("input exceeds byte budget")
    return data


def positive_integer(value, name):
    if type(value) is not int or not 1 <= value <= (1 << 63) - 1:
        raise ArchiveError(f"{name} must be a positive bounded integer")
    return value


def inspect_archive(data, expected_sha, source, run_id, artifact_id):
    if not isinstance(expected_sha, str) or not SHA256.fullmatch(expected_sha):
        raise ArchiveError("invalid archive SHA-256")
    if not isinstance(source, str) or not GIT_SHA.fullmatch(source):
        raise ArchiveError("source must be an exact Git commit")
    positive_integer(run_id, "run_id")
    positive_integer(artifact_id, "artifact_id")
    if len(data) > MAX_ARCHIVE or hashlib.sha256(data).hexdigest() != expected_sha:
        raise ArchiveError("archive size/hash mismatch")
    files = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(names) != len(MEMBERS) or set(names) != MEMBERS:
            raise ArchiveError("unexpected, duplicate or missing archive member")
        if sum(entry.file_size for entry in entries) > MAX_EXPANDED:
            raise ArchiveError("archive expansion exceeds budget")
        for entry in entries:
            if entry.flag_bits & 1 or stat.S_ISLNK(entry.external_attr >> 16):
                raise ArchiveError("encrypted and symlink members are forbidden")
            with archive.open(entry) as stream:
                content = stream.read(MAX_EXPANDED + 1)
            if len(content) != entry.file_size or len(content) > MAX_EXPANDED:
                raise ArchiveError("member size mismatch")
            files[entry.filename] = content
    host = files["host.txt"].decode("utf-8")
    commits = re.findall(r"^source_commit=([0-9a-f]{40})$", host, re.MULTILINE)
    trees = re.findall(r"^source_tree=([0-9a-f]{40})$", host, re.MULTILINE)
    if commits != [source] or len(trees) != 1:
        raise ArchiveError("host receipt does not bind exactly one source commit/tree")
    measurements = []
    for filename, phase in PHASES.items():
        rows = []
        for line in files[filename].decode("utf-8").splitlines():
            if '"hepta.memory-retrieval.target-host.v1"' not in line:
                continue
            row = parse_json(line[line.index("{"):])
            if not isinstance(row, dict) or row.get("phase") != phase:
                raise ArchiveError("measurement phase mismatch")
            positive_integer(row.get("iterations"), "iterations")
            prefixes = ("retrieval_", "revalidation_") if phase == "sqlite-owner" else ("",)
            for prefix in prefixes:
                values = [row.get(f"{prefix}p{p}_us") for p in (50, 95, 99)]
                if any(type(value) is not int or not 0 <= value < (1 << 63) for value in values):
                    raise ArchiveError("invalid measured percentile")
                if values != sorted(values):
                    raise ArchiveError("percentiles are not ordered")
            rows.append(row)
        if len(rows) != 1:
            raise ArchiveError("each phase requires exactly one measured summary")
        measurements.extend(rows)
    return {
        "schema": "hepta.memory-retrieval.historical-archive.v1",
        "repository": "TrillionniumFoundation/hepta-private-ci",
        "run_id": run_id, "artifact_id": artifact_id,
        "source_head": source, "source_tree": trees[0],
        "archive_file": "archive.zip", "archive_sha256": expected_sha,
        "archive_bytes": len(data),
        "members": {name: {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
                    for name, content in sorted(files.items())},
        "measurements": measurements,
        "evidence_class": "historical-github-hosted-microbenchmark",
        "currentSourceQualified": False, "productExecutionProved": False,
        "independentAcceptance": False, "productionImplementation": False,
        "activation": False, "release": False,
    }


def exclusive_write(path, data):
    try:
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        if bounded_read(path, max(MAX_ARCHIVE, len(data))) != data:
            raise ArchiveError("existing content-addressed evidence differs") from None


def retain(archive, expected_sha, source, run_id, artifact_id, output):
    data = bounded_read(archive, MAX_ARCHIVE)
    receipt = inspect_archive(data, expected_sha, source, run_id, artifact_id)
    destination = Path(output) / expected_sha
    destination.mkdir(parents=True, exist_ok=True)
    exclusive_write(destination / "archive.zip", data)
    exclusive_write(destination / "receipt.json", canonical(receipt))
    descriptor = os.open(destination, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return destination / "receipt.json"


def verify(path):
    path = Path(path)
    encoded = bounded_read(path, MAX_ARCHIVE)
    receipt = parse_json(encoded)
    if not isinstance(receipt, dict) or receipt.get("archive_file") != "archive.zip":
        raise ArchiveError("receipt must reference its local archive.zip")
    if path.parent.name != receipt.get("archive_sha256"):
        raise ArchiveError("receipt directory is not content addressed")
    data = bounded_read(path.parent / "archive.zip", MAX_ARCHIVE)
    expected = inspect_archive(data, receipt["archive_sha256"], receipt["source_head"],
                               receipt["run_id"], receipt["artifact_id"])
    if encoded != canonical(expected):
        raise ArchiveError("receipt is not the canonical observation of its archive")
    return expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("verify")
    check.add_argument("receipt", type=Path)
    add = commands.add_parser("retain")
    add.add_argument("--archive", type=Path, required=True)
    add.add_argument("--sha256", required=True)
    add.add_argument("--source", required=True)
    add.add_argument("--run-id", type=int, required=True)
    add.add_argument("--artifact-id", type=int, required=True)
    add.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "verify":
            result = verify(args.receipt)
            print(f"verified historical microbenchmark: {result['archive_sha256']}")
        else:
            print(retain(args.archive, args.sha256, args.source, args.run_id,
                         args.artifact_id, args.output))
    except (ArchiveError, OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as error:
        print(f"retrieval archive refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
