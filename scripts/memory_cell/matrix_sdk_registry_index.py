"""Convert pinned crates.io sparse-index metadata into a crate checksum envelope.

This is only a transport alternative for an isolated dependency compatibility
trial. The archive is still verified independently against the published SHA256
by matrix_sdk_sqlite_vendor; this never waives cargo-deny or vendor checks.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re

CRATE = "matrix-sdk-sqlite"
VERSION = "0.19.0"
MAX_INDEX_BYTES = 2 * 1024 * 1024
MAX_RELEASES = 512
MAX_RECORD_BYTES = 64 * 1024


def _unique(pairs):
    value = {}
    for key, field in pairs:
        if key in value:
            raise ValueError("duplicate sparse-index JSON field")
        value[key] = field
    return value


def _nonfinite(_):
    raise ValueError("nonfinite sparse-index metadata")


def envelope(raw: bytes) -> tuple[bytes, dict]:
    """Select the exact non-yanked release; do not substitute a nearby version."""
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_INDEX_BYTES:
        raise ValueError("bounded sparse-index response bytes required")
    lines = raw.splitlines()
    if not 1 <= len(lines) <= MAX_RELEASES:
        raise ValueError("bounded sparse-index release census required")
    found = []
    for line in lines:
        if not 0 < len(line) <= MAX_RECORD_BYTES:
            raise ValueError("invalid sparse-index record length")
        record = json.loads(
            line.decode("utf-8", "strict"),
            object_pairs_hook=_unique,
            parse_constant=_nonfinite,
        )
        if (
            not isinstance(record, dict)
            or record.get("name") != CRATE
            or not isinstance(record.get("vers"), str)
            or not isinstance(record.get("cksum"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", record["cksum"])
            or type(record.get("yanked")) is not bool
        ):
            raise ValueError("invalid exact-publisher sparse-index entry")
        if record["vers"] == VERSION:
            if record["yanked"]:
                raise ValueError("published target is yanked")
            found.append(record)
    if len(found) != 1:
        raise ValueError("exact unique published target version required")
    result = found[0]
    body = json.dumps(
        {"version": {"num": VERSION, "checksum": result["cksum"]}},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    receipt = {
        "schema": "hepta.matrix-sdk-sqlite-sparse-index.v1",
        "registry_record_sha256": hashlib.sha256(raw).hexdigest(),
        "publisher_package": CRATE,
        "publisher_version": VERSION,
        "release_checksum_sha256": result["cksum"],
        "publisher_record_count": len(lines),
        "not_yanked": True,
        "archive_bytes_verified_here": False,
        "cargo_deny_qualified": False,
        "production_accepted": False,
    }
    return body, receipt


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--index", type=Path, required=True)
    p.add_argument("--metadata", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    args = p.parse_args()
    if (
        any(part.is_symlink() for part in (args.index, *args.index.parents))
        or not args.index.is_file()
    ):
        raise ValueError("regular sparse-index input required")
    metadata, report = envelope(args.index.read_bytes())
    outputs = (
        (args.metadata, metadata),
        (args.report, json.dumps(report, sort_keys=True, indent=2).encode() + b"\n"),
    )
    if args.metadata == args.report or any(
        path.exists()
        or path.is_symlink()
        or any(parent.is_symlink() for parent in path.parents)
        for path, _ in outputs
    ):
        raise ValueError("candidate outputs must be new regular paths")
    created = []
    try:
        for name, body in outputs:
            with name.open("xb") as stream:
                created.append(name)
                stream.write(body)
    except Exception:
        for name in created:
            name.unlink(missing_ok=True)
        raise
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
