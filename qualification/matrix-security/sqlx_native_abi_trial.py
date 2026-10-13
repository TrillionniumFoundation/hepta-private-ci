#!/usr/bin/env python3
"""Scratch-only SQLx 0.9.0 native SQLite upper-bound compatibility experiment.

This does NOT patch the production SQLx crate, Hepta workspace, Cargo.lock,
Matrix E2EE code, or a running SQLite database. The original crates.io package
must match its independently pinned Cargo.lock SHA-256 before any change.
An expanded manifest version range is an unverified ABI hypothesis; only
subsequent real Cargo resolution, compilation and crash/recovery can evaluate it.
"""

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile
import tomllib

SCHEMA = "hepta.sqlx-sqlite-abi-038-disposable-trial.v1"
PACKAGE = "sqlx-sqlite"
VERSION = "0.9.0"
EXPECTED_OLD = ">=0.30.1, <0.38.0"
CANDIDATE = ">=0.30.1, <0.39.0"
REGISTRY = "registry+https://github.com/rust-lang/crates.io-index"
MAX_ARCHIVE_BYTES = 3 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 12 * 1024 * 1024
MAX_MEMBERS = 2500


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical_lock(lock_bytes):
    if type(lock_bytes) is not bytes or not 0 < len(lock_bytes) < 4 * 1024 * 1024:
        raise ValueError("missing or oversized trusted Cargo.lock")
    try:
        lock = tomllib.loads(lock_bytes.decode("utf-8"))
    except (UnicodeError, tomllib.TOMLDecodeError) as e:
        raise ValueError("invalid Cargo.lock") from e
    packages = lock.get("package")
    if type(packages) is not list:
        raise ValueError("Cargo lock has no packages")
    selected = [p for p in packages if p.get("name") == PACKAGE]
    if len(selected) != 1 or selected[0].get("version") != VERSION:
        raise ValueError("not exactly the pinned sqlx-sqlite 0.9.0")
    source = selected[0].get("source")
    checksum = selected[0].get("checksum")
    if (source != REGISTRY or type(checksum) is not str or
            len(checksum) != 64 or any(c not in "0123456789abcdef" for c in checksum)):
        raise ValueError("SQLx archive source/checksum not independently pinned")
    for name, version in (("libsqlite3-sys", "0.37.0"), ("sqlx", "0.9.0")):
        matched = [p for p in packages if p.get("name") == name]
        if len(matched) != 1 or matched[0].get("version") != version:
            raise ValueError("unrecognized production SQLite/SQLx dependency baseline")
    return checksum


def _read_source_archive(archive_bytes, checksum):
    if (type(archive_bytes) is not bytes or
            not 0 < len(archive_bytes) <= MAX_ARCHIVE_BYTES or
            sha(archive_bytes) != checksum):
        raise ValueError("crates.io SQLx archive checksum/size mismatch")
    prefix = f"{PACKAGE}-{VERSION}"
    found = {}
    size = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
            members = archive.getmembers()
            if not members or len(members) > MAX_MEMBERS:
                raise ValueError("unbounded SQLx source archive")
            for member in members:
                path = PurePosixPath(member.name)
                if (path.is_absolute() or len(path.parts) < 1 or
                        path.parts[0] != prefix or
                        any(part in ("..", ".", "") for part in path.parts) or
                        member.issym() or member.islnk() or
                        not (member.isfile() or member.isdir())):
                    raise ValueError("SQLx archive contains untrusted entry")
                if member.name in found:
                    raise ValueError("duplicate SQLx archive path")
                if member.isdir():
                    found[member.name] = None
                    continue
                size += member.size
                if member.size < 0 or size > MAX_UNCOMPRESSED_BYTES:
                    raise ValueError("unbounded expanded SQLx source")
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError("missing SQLx member content")
                data = stream.read(member.size + 1)
                if len(data) != member.size:
                    raise ValueError("truncated SQLx member content")
                found[member.name] = data
    except (tarfile.TarError, OSError) as e:
        raise ValueError("invalid SQLx source archive") from e
    key = f"{prefix}/Cargo.toml"
    if not isinstance(found.get(key), bytes):
        raise ValueError("original normalized SQLx Cargo.toml missing")
    return found, key


def trial(archive_bytes, lock_bytes):
    """Pure source audit. Returns exact candidate files and a nonpromoting report."""
    checksum = canonical_lock(lock_bytes)
    files, key = _read_source_archive(archive_bytes, checksum)
    raw = files[key]
    try:
        doc = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeError, tomllib.TOMLDecodeError) as e:
        raise ValueError("unparseable signed SQLx manifest") from e
    if (doc.get("package", {}).get("name") != PACKAGE or
            doc.get("package", {}).get("version") != VERSION):
        raise ValueError("wrong signed SQLx crate source")
    dep = doc.get("dependencies", {}).get("libsqlite3-sys")
    if type(dep) is not dict or dep.get("version") != EXPECTED_OLD:
        raise ValueError("SQLx native SQLite bound has drifted; do not patch unknown manifest")
    old_line = ('version = "' + EXPECTED_OLD + '"').encode()
    if raw.count(old_line) != 1:
        raise ValueError("SQLx native SQLite upper-bound patch is not unique")
    changed = raw.replace(old_line, ('version = "' + CANDIDATE + '"').encode())
    revised = tomllib.loads(changed.decode("utf-8"))
    revised["dependencies"]["libsqlite3-sys"]["version"] = EXPECTED_OLD
    if revised != doc or changed == raw:
        raise ValueError("unexpected SQLx manifest delta")
    files[key] = changed
    return files, {
        "schema": SCHEMA,
        "crate": f"{PACKAGE} {VERSION}",
        "original_crates_io_sha256": checksum,
        "source_manifest_sha256": sha(raw),
        "candidate_manifest_sha256": sha(changed),
        "only_change": "sqlx-sqlite libsqlite3-sys upper bound <0.38.0 -> <0.39.0",
        "candidate_dependency_range": CANDIDATE,
        "production_sources_changed": False,
        "hepta_cargo_lock_changed": False,
        "sdk_e2ee_sqlite_enabled": "not_observed_by_source_trial",
        "cargo_metadata_verified": False,
        "native_compile_verified": False,
        "sqlite_wal_recovery_verified": False,
        "cross_platform_verified": False,
        "cargo_deny_verified": False,
        "production_authorized": False,
    }


def stage(archive, lock, output_dir, report_file):
    archive, lock = Path(archive), Path(lock)
    output_dir, report_file = Path(output_dir), Path(report_file)
    if (archive.is_symlink() or lock.is_symlink() or
            not archive.is_file() or not lock.is_file() or
            output_dir.exists() or report_file.exists() or
            report_file.resolve().is_relative_to(output_dir.resolve())):
        raise ValueError("trial paths must be existing trusted sources and new detached outputs")
    files, report = trial(archive.read_bytes(), lock.read_bytes())
    output_dir.mkdir(parents=True, exist_ok=False)
    for name, data in files.items():
        if data is None:
            continue
        destination = output_dir / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    report_file.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_dir / f"{PACKAGE}-{VERSION}", report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--lock", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    args = p.parse_args(argv)
    source, report = stage(args.archive, args.lock, args.output_dir, args.report)
    print(json.dumps({"local_patch_path": str(source), **report}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
