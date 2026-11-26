#!/usr/bin/env python3
"""Fail-closed check of Cargo's *disposable* Matrix dual-lock resolution.

Compare the scratch Cargo.lock with genuine Cargo metadata. This is a
diagnostic, not a source signature, Cargo-deny verdict, Matrix E2EE test,
WAL recovery receipt, installed production dependency or release permission.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import tomllib

SCHEMA = "hepta.matrix-isolated-dual-lock-verification.v1"
EXPECTED_UPSTREAM = "https://github.com/matrix-org/matrix-rust-sdk"
EXPECTED_REVISION = "b3c07ea6ba6e8e46e30811c0500b04505c4be9f9"
OLD = {"async-trait": (0, 1, 89), "bytes": (1, 11, 1)}
REQUIRED = {"async-trait": (0, 1, 92), "bytes": (1, 12, 1)}
FAMILY = ("matrix-sdk", "matrix-sdk-base", "matrix-sdk-crypto", "matrix-sdk-sqlite")
MAX_LOCK_BYTES = 4 * 1024 * 1024
MAX_META_BYTES = 32 * 1024 * 1024
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
HEX40 = re.compile(r"[0-9a-f]{40}\Z")


def version3(raw):
    if not isinstance(raw, str) or re.fullmatch(r"\d+\.\d+\.\d+", raw) is None:
        raise ValueError("unregistered or prerelease Cargo version")
    return tuple(int(x) for x in raw.split("."))


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def load_lock(payload):
    if type(payload) is not bytes or not 0 < len(payload) <= MAX_LOCK_BYTES:
        raise ValueError("invalid or unbounded Cargo.lock")
    try:
        data = tomllib.loads(payload.decode("utf-8"))
    except (UnicodeError, tomllib.TOMLDecodeError) as error:
        raise ValueError("unparseable Cargo.lock") from error
    if data.get("version") != 4 or type(data.get("package")) is not list:
        raise ValueError("unexpected Cargo.lock schema")
    result = {}
    for item in data["package"]:
        if type(item) is not dict or not isinstance(item.get("name"), str):
            raise ValueError("invalid Cargo package record")
        name, version, source = item["name"], item.get("version"), item.get("source")
        if not isinstance(version, str) or not version:
            raise ValueError("malformed Cargo version")
        key = (name, version, source)
        if key in result:
            raise ValueError("duplicate Cargo package identity")
        checksum = item.get("checksum")
        if source is not None and source.startswith("registry+"):
            if not isinstance(checksum, str) or not HEX64.fullmatch(checksum):
                raise ValueError("missing or malformed registry checksum")
        elif checksum is not None and (
            not isinstance(checksum, str) or not HEX64.fullmatch(checksum)
        ):
            raise ValueError("noncanonical Cargo checksum")
        result[key] = item
    return result


def _one(items, name):
    found = [p for (n, _, _), p in items.items() if n == name]
    if len(found) != 1:
        raise ValueError(f"missing or multiply resolved {name}")
    return found[0]


def inspect(original_lock, resolved_lock, metadata, *, source_sha, pinned_upstream=EXPECTED_REVISION):
    """Check one Cargo-resolved candidate without claiming operational safety."""
    if not isinstance(source_sha, str) or not HEX40.fullmatch(source_sha):
        raise ValueError("invalid Hepta source SHA fence")
    if pinned_upstream != EXPECTED_REVISION:
        raise ValueError("unexpected upstream SDK source revision")
    before, after = load_lock(original_lock), load_lock(resolved_lock)
    if not isinstance(metadata, dict) or type(metadata.get("packages")) is not list:
        raise ValueError("invalid Cargo metadata")
    packages = {}
    for item in metadata["packages"]:
        if type(item) is not dict:
            raise ValueError("invalid Cargo metadata package")
        key = (item.get("name"), item.get("version"), item.get("source"))
        if key in packages:
            raise ValueError("duplicate Cargo metadata package")
        packages[key] = item
    upgrades = {}
    for name in OLD:
        original, selected = _one(before, name), _one(after, name)
        if version3(original["version"]) != OLD[name]:
            raise ValueError(f"unexpected original {name} pin")
        new = version3(selected["version"])
        # async-trait 0.x only accepts the 0.1 family; bytes 1.x accepts
        # later compatible minor releases, never a new major version.
        compatible = new[:2] == (0, 1) if name == "async-trait" else new[0] == 1
        if new < REQUIRED[name] or not compatible:
            raise ValueError(f"required {name} version unresolved")
        if selected.get("source") != "registry+https://github.com/rust-lang/crates.io-index":
            raise ValueError(f"untrusted {name} source")
        upgrades[name] = {"old": original["version"], "resolved": selected["version"]}
    if any(k[0] == "anymap2" for k in after):
        raise ValueError("unmaintained anymap2 still in resolved lock")
    _one(after, "anymap3")
    for component in FAMILY:
        item = _one(after, component)
        if version3(item["version"])[:2] != (0, 19):
            raise ValueError(f"Matrix SDK component {component} still has unsafe family")
    sdk_source = _one(after, "matrix-sdk").get("source", "")
    if (
        not isinstance(sdk_source, str)
        or not sdk_source.startswith("git+" + EXPECTED_UPSTREAM + "?")
        or "rev=" + EXPECTED_REVISION not in sdk_source
        or not sdk_source.endswith("#" + EXPECTED_REVISION)
    ):
        raise ValueError("Matrix SDK does not resolve to exact reviewed Git revision")
    # Compare both identity AND checksum. Synthetic version strings alone must
    # never stand in for Cargo's real chosen source/checksum graph.
    names = set(OLD) | set(FAMILY) | {"anymap3", "anymap2"}
    for name in names:
        locked = [k for k in after if k[0] == name]
        observed = [k for k in packages if k[0] == name]
        if sorted(locked, key=str) != sorted(observed, key=str):
            raise ValueError(f"Cargo metadata disagrees with lock for {name}")
        for key in locked:
            if packages[key].get("checksum") != after[key].get("checksum"):
                raise ValueError(f"Cargo metadata checksum mismatch for {name}")
    return {
        "schema": SCHEMA,
        "staged_hepta_source_sha": source_sha,
        "pinned_matrix_upstream_revision": pinned_upstream,
        "original_lock_sha256": _digest(original_lock),
        "resolved_lock_sha256": _digest(resolved_lock),
        "cargo_lock_metadata_consistent": True,
        "upgraded_locks": upgrades,
        "added_package_identities": sorted(str(k) for k in after.keys() - before.keys()),
        "removed_package_identities": sorted(str(k) for k in before.keys() - after.keys()),
        "matrix_family_minor": "0.19",
        "unmaintained_anymap2_present": False,
        # Path provenance and repository cleanliness are verified by the
        # independent workflow/worktree owner, not by this data-only parser.
        "isolated_worktree_attested": False,
        "original_checkout_modified": None,
        "actual_source_reviewer_approved": False,
        "cargo_deny_verified": False,
        "matrix_e2ee_verified": False,
        "sqlite_wal_recovery_verified": False,
        "production_authorized": False,
    }


def read_bounded(path, limit):
    with Path(path).open("rb") as stream:
        value = stream.read(limit + 1)
    if len(value) > limit:
        raise ValueError("unbounded diagnostic input")
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-lock", type=Path, required=True)
    parser.add_argument("--resolved-lock", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--hepta-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    inputs = (args.original_lock.resolve(), args.resolved_lock.resolve(), args.metadata.resolve())
    if args.output.resolve() in inputs or len(set(inputs)) != len(inputs):
        parser.error("diagnostic output and inputs must be separate files")
    old = read_bounded(args.original_lock, MAX_LOCK_BYTES)
    new = read_bounded(args.resolved_lock, MAX_LOCK_BYTES)
    metadata = json.loads(read_bounded(args.metadata, MAX_META_BYTES))
    result = inspect(old, new, metadata, source_sha=args.hepta_sha)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
