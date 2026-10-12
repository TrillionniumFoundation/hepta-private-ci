#!/usr/bin/env python3
"""Inspect two REAL pinned Matrix Cargo resolver conflicts; stage only scratch lock bytes.

Not a security remediation, not a Cargo.lock change to the source checkout,
not permission to compile unreviewed SDK code or operate production Matrix.
The scratch lock deliberately omits exactly two stale package blocks so a
separate disposable Cargo resolver can produce newly checksummed records.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tomllib

SOURCE_REV = "b3c07ea6ba6e8e46e30811c0500b04505c4be9f9"
UPSTREAM = "https://github.com/matrix-org/matrix-rust-sdk"
SCHEMA = "hepta.matrix-disposable-dual-lock-unpin.v1"
STALE = {"async-trait": "0.1.89", "bytes": "1.11.1"}
MINIMUM = {"async-trait": "0.1.92", "bytes": "1.12.1"}
MAX_LOCK_BYTES = 4 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_STDERR_CHARS = 100_000


def _hash(value):
    return hashlib.sha256(value).hexdigest()


def _evidence_text(name, value):
    if not isinstance(value, str) or not 0 < len(value) <= MAX_STDERR_CHARS:
        raise ValueError(f"invalid or excessive {name}")
    return value


def inspect_pair(async_log, bytes_log, manifest_bytes, lock_bytes):
    """Only approve EXACT two previously observed stale-lock resolver failures."""
    reasons = []
    try:
        async_log = _evidence_text("async-trait log", async_log)
        bytes_log = _evidence_text("bytes log", bytes_log)
    except ValueError as error:
        reasons.append(str(error))
        async_log = bytes_log = ""
    if (not isinstance(manifest_bytes, bytes) or len(manifest_bytes) > MAX_MANIFEST_BYTES
            or not isinstance(lock_bytes, bytes) or len(lock_bytes) > MAX_LOCK_BYTES):
        reasons.append("invalid or oversized pinned input bytes")
        manifest_bytes = b""
        lock_bytes = b""
    try:
        manifest = tomllib.loads(manifest_bytes.decode("utf-8"))
        pinned = manifest["workspace"]["dependencies"]["matrix-sdk"]
        if pinned != {
            "git": UPSTREAM, "rev": SOURCE_REV, "version": "0.19.1",
            "default-features": False, "features": ["e2e-encryption", "sqlite"],
        }:
            reasons.append("unregistered Matrix source or lost E2EE/SQLite")
    except (KeyError, TypeError, ValueError, UnicodeError, tomllib.TOMLDecodeError):
        reasons.append("unparsable or unpinned disposable manifest")
    try:
        document = tomllib.loads(lock_bytes.decode("utf-8"))
        packages = document.get("package", [])
        if not isinstance(packages, list):
            raise ValueError("malformed package records")
        for name, old in STALE.items():
            selected = [p for p in packages if p.get("name") == name]
            if len(selected) != 1 or selected[0].get("version") != old:
                reasons.append(f"unexpected locked {name} version")
            elif selected[0].get("source") != "registry+https://github.com/rust-lang/crates.io-index":
                reasons.append(f"untrusted locked {name} source")
            elif (not isinstance(selected[0].get("checksum"), str)
                  or len(selected[0]["checksum"]) != 64
                  or any(char not in "0123456789abcdef"
                         for char in selected[0]["checksum"])):
                reasons.append(f"invalid original {name} checksum")
    except (KeyError, TypeError, ValueError, UnicodeError, tomllib.TOMLDecodeError):
        reasons.append("invalid Cargo.lock")

    exact = (
        (async_log, "async-trait", "0.1.89", "0.1.92", "tonic v0.14.3"),
        (bytes_log, "bytes", "1.11.1", "1.12.1", "axum v0.8.8"),
    )
    for log, name, old, required, prior_owner in exact:
        fields = (
            f"error: failed to select a version for `{name}`.",
            "matrix-sdk v0.19.1",
            SOURCE_REV,
            f"requirements `^{required}`",
            f"previously selected package `{name} v{old}`",
            f"(locked to {old})",
            prior_owner,
        )
        if not all(field in log for field in fields) or log.count("error: failed to select a version") != 1:
            reasons.append(f"unverified {name} resolver failure")

    return {
        "schema": SCHEMA,
        "dual_conflict_exactly_verified": not reasons,
        "rejection_reasons": sorted(set(reasons)),
        "candidate_git_sha": SOURCE_REV,
        "stale_versions": dict(STALE),
        "required_versions": dict(MINIMUM),
        "staged_manifest_sha256": _hash(manifest_bytes),
        "original_lock_sha256": _hash(lock_bytes),
        "original_source_modified": False,
        "production_cargo_lock_mutated": False,
        "cargo_resolution_verified": False,
        "cargo_deny_verified": False,
        "matrix_crypto_verified": False,
        "e2ee_verified": False,
        "sqlite_wal_recovery_verified": False,
        "production_authorized": False,
    }


def scratch_unlock_two(lock_bytes):
    """Remove only two exact old package entries; never invent a new checksum."""
    if not isinstance(lock_bytes, bytes) or not 0 < len(lock_bytes) <= MAX_LOCK_BYTES:
        raise ValueError("invalid lock file")
    text = lock_bytes.decode("utf-8")
    # This utility is intentionally callable on its own: reject a corrupted
    # or substituted Cargo registry record even when no CLI evidence planner
    # was run first. A 64-character checksum is not necessarily SHA-256 hex.
    source = tomllib.loads(text)
    packages = source.get("package")
    if type(source.get("version")) is not int or source["version"] != 4 or type(packages) is not list:
        raise ValueError("invalid scratch Cargo lock format")
    for name, old in STALE.items():
        selected = [pkg for pkg in packages
                    if type(pkg) is dict and pkg.get("name") == name]
        if len(selected) != 1 or selected[0].get("version") != old:
            raise ValueError(f"unexpected scratch {name} pin")
        checksum = selected[0].get("checksum")
        if (selected[0].get("source") != "registry+https://github.com/rust-lang/crates.io-index"
                or not isinstance(checksum, str) or len(checksum) != 64
                or any(char not in "0123456789abcdef" for char in checksum)):
            raise ValueError(f"untrusted scratch {name} registry/checksum")
    marker = "\n[[package]]\n"
    blocks = text.split(marker)
    if len(blocks) < 2 or "version = 4" not in blocks[0]:
        raise ValueError("unrecognized lock syntax")
    omitted = set()
    kept = [blocks[0]]
    for block in blocks[1:]:
        first = block.splitlines()[:2]
        if len(first) == 2:
            name = first[0].removeprefix('name = "').removesuffix('"')
            locked = first[1].removeprefix('version = "').removesuffix('"')
        else:
            name, locked = "", ""
        if name in STALE:
            if name in omitted or locked != STALE[name]:
                raise ValueError("wrong or duplicated stale package")
            omitted.add(name)
        else:
            kept.append(block)
    if omitted != set(STALE):
        raise ValueError("not exactly both stale package entries")
    candidate = marker.join(kept).encode("utf-8")
    parsed = tomllib.loads(candidate.decode("utf-8"))
    if any(p.get("name") in STALE for p in parsed.get("package", [])):
        raise ValueError("stale package survived scratch mutation")
    if len(parsed.get("package", [])) != len(tomllib.loads(text).get("package", [])) - 2:
        raise ValueError("unexpected package removal")
    return candidate


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("async-log", "bytes-log", "manifest", "lock", "report", "scratch-lock"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args(argv)
    inputs = {args.async_log.resolve(), args.bytes_log.resolve(), args.manifest.resolve(), args.lock.resolve()}
    outputs = {args.report.resolve(), args.scratch_lock.resolve()}
    if inputs & outputs or len(outputs) != 2:
        parser.error("output paths must be disjoint from all evidence inputs")
    lock = args.lock.read_bytes()
    plan = inspect_pair(
        args.async_log.read_text(encoding="utf-8", errors="replace"),
        args.bytes_log.read_text(encoding="utf-8", errors="replace"),
        args.manifest.read_bytes(), lock,
    )
    if plan["dual_conflict_exactly_verified"]:
        # Scratch file is neither the original nor a valid locked Cargo graph.
        # Rust Cargo must verify and regenerate the exact candidate graph.
        scratch = scratch_unlock_two(lock)
        with args.scratch_lock.open("xb") as f:
            f.write(scratch)
        plan["scratch_lock_sha256"] = _hash(scratch)
        plan["scratch_removed_entries"] = sorted(STALE)
    with args.report.open("x", encoding="utf-8") as f:
        f.write(json.dumps(plan, sort_keys=True, indent=2) + "\n")
    print(json.dumps(plan, sort_keys=True))
    return 0 if plan["dual_conflict_exactly_verified"] else 1


if __name__ == "__main__":
    sys.exit(main())
