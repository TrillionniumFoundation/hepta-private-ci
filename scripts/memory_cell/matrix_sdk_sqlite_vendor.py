"""Bounded byte-verified upstream SQLite crate compatibility *research*.

Never use the patched crate in serving without separate maintainer review,
original Cargo tests, SQL semantics, and unchanged cargo-deny qualification.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
import tomllib

CRATE = "matrix-sdk-sqlite"
VERSION = "0.19.0"
ROOT = f"{CRATE}-{VERSION}"
OLD_RUSQLITE = "0.40.2"
EXPERIMENTAL_RUSQLITE = "0.39.0"
MAX_BYTES = 8 * 1024 * 1024
MAX_EXTRACTED = 64 * 1024 * 1024


def candidate(archive: bytes, metadata: bytes, destination: Path):
    """Unpack only verified safe crate members; edit one dependency in a throwaway dir."""
    if not 0 < len(archive) <= MAX_BYTES or not 0 < len(metadata) <= 1024 * 1024:
        raise ValueError("bounded upstream package bytes required")

    def unique(pairs):
        row = {}
        for name, value in pairs:
            if name in row:
                raise ValueError("duplicate registry metadata field")
            row[name] = value
        return row

    data = json.loads(metadata, object_pairs_hook=unique)
    record = data.get("version")
    if not isinstance(record, dict) or record.get("num") != VERSION:
        raise ValueError("mismatched upstream crate version")
    expected = record.get("checksum")
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("missing public registry SHA256")
    if hashlib.sha256(archive).hexdigest() != expected:
        raise ValueError("published crate checksum differs")
    if destination.exists() or destination.is_symlink():
        raise ValueError("existing candidate destination cannot be overwritten")
    found, content, total = set(), {}, 0
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
        members = bundle.getmembers()
        if not 1 <= len(members) <= 4096:
            raise ValueError("oversized crate file census")
        for member in members:
            parts = PurePosixPath(member.name).parts
            if (
                not parts
                or parts[0] != ROOT
                or len(parts) < 2
                or PurePosixPath(member.name).is_absolute()
                or ".." in parts
                or "\\" in member.name
                or not (member.isdir() or member.isfile())
                or member.name in found
                or member.size < 0
            ):
                raise ValueError("unsafe upstream crate member")
            found.add(member.name)
            if member.isfile():
                total += member.size
                if total > MAX_EXTRACTED:
                    raise ValueError("upstream crate decompression budget")
                stream = bundle.extractfile(member)
                if stream is None:
                    raise ValueError("unreadable upstream regular crate file")
                raw = stream.read(member.size + 1)
                if len(raw) != member.size:
                    raise ValueError("short or oversized upstream file")
                content[Path(*parts[1:])] = raw
    manifest_path = Path("Cargo.toml")
    if manifest_path not in content:
        raise ValueError("upstream crate Cargo.toml missing")
    manifest = content[manifest_path].decode("utf-8", "strict")
    original = tomllib.loads(manifest)
    package = original.get("package", {})
    if (
        package.get("name") != CRATE
        or package.get("version") != VERSION
        or original.get("dependencies", {}).get("rusqlite", {}).get("version")
        != OLD_RUSQLITE
    ):
        raise ValueError("upstream exact rusqlite dependency pin changed")
    section = re.search(r"(?ms)^\[dependencies\.rusqlite\]\n.*?(?=^\[|\Z)", manifest)
    if section is None:
        raise ValueError("no isolated rusqlite dependency table")
    old_line = f'version = "{OLD_RUSQLITE}"'
    body = section.group()
    if body.count(old_line) != 1:
        raise ValueError("original rusqlite version not uniquely patchable")
    patched = (
        manifest[: section.start()]
        + body.replace(old_line, f'version = "{EXPERIMENTAL_RUSQLITE}"')
        + manifest[section.end() :]
    )
    parsed = tomllib.loads(patched)
    if parsed["dependencies"]["rusqlite"]["version"] != EXPERIMENTAL_RUSQLITE:
        raise ValueError("dependency edit did not bind expected version")
    content[manifest_path] = patched.encode()
    # All security-sensitive validation occurs before creating any filesystem path.
    for rel, body in content.items():
        path = destination / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(body)
    return dict(
        schema="hepta.matrix-sdk-019-sqlite-compatibility-probe.v1",
        publisher_crate=CRATE,
        publisher_version=VERSION,
        registry_zip_sha256=expected,
        original_manifest_sha256=hashlib.sha256(manifest.encode()).hexdigest(),
        experimental_manifest_sha256=hashlib.sha256(patched.encode()).hexdigest(),
        original_rusqlite=OLD_RUSQLITE,
        experimental_rusqlite=EXPERIMENTAL_RUSQLITE,
        source_member_count=len(content),
        source_uncompressed_bytes=total,
        production_compatible=False,
        upstream_crate_modified_for_research_only=True,
        full_cargo_deny_and_binary_runtime_still_required=True,
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--crate", type=Path, required=True)
    p.add_argument("--metadata", type=Path, required=True)
    p.add_argument("--destination", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    args = p.parse_args()
    for path in (args.crate, args.metadata):
        if not path.is_file() or path.is_symlink():
            raise ValueError("only bounded regular inputs may be admitted")
    out = candidate(
        args.crate.read_bytes(), args.metadata.read_bytes(), args.destination
    )
    with args.report.open("x", encoding="utf-8") as dest:
        json.dump(out, dest, indent=2, sort_keys=True, allow_nan=False)
        dest.write("\n")
    print(json.dumps(out, sort_keys=True))


if __name__ == "__main__":
    main()
