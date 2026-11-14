#!/usr/bin/env python3
"""Fail-closed validation of an *isolated* Matrix Cargo dual-lock resolution.

This inspects genuine Cargo.lock and cargo metadata output after Cargo itself
re-resolves exactly pinned async-trait / bytes conflicts in a disposable
worktree. It does not compile code, validate source signatures, attest E2EE,
prove SQLite recovery, change the production lock, or authorize release.
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


def hash_bytes(content):
    return hashlib.sha256(content).hexdigest()


def load_lock(payload):
    if type(payload) is not bytes or not 0 < len(payload) <= MAX_LOCK_BYTES:
        raise ValueError("invalid or unbounded Cargo.lock")
    try:
        document = tomllib.loads(payload.decode("utf-8"))
    except (UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ValueError("unparseable Cargo.lock") from exc
    if document.get("version") != 4 or type(document.get("package")) is not list:
        raise ValueError("unexpected Cargo.lock schema")
    items = {}
    for item in document["package"]:
        if type(item) is not dict or not isinstance(item.get("name"), str):
            raise ValueError("invalid Cargo package record")
        name = item["name"]
        ver = item.get("version")
        if not isinstance(ver, str) or not ver:
            raise ValueError("malformed Cargo version")
        source = item.get("source")
        key = (name, ver, source)
        if key in items:
            raise ValueError("duplicate Cargo package identity")
        checksum = item.get("checksum")
        if source is not None and source.startswith("registry+"):
            if not isinstance(checksum, str) or not HEX64.fullmatch(checksum):
                raise ValueError("missing or malformed registry checksum")
        elif checksum is not None and (not isinstance(checksum, str) or not HEX64.fullmatch(checksum)):
            raise ValueError("noncanonical Cargo checksum")
        items[key] = item
    return items


def exactly_one(items, name):
    matches = [item for (n, _, _), item in items.items() if n == name]
    if len(matches) != 1:
        raise ValueError(f"missing or multiply resolved {name}")
    return matches[0]


def inspect(original_lock, resolved_lock, metadata, *, source_sha, pinned_upstream=EXPECTED_REVISION):
    """Verify resolved lock *against* real Cargo metadata, without granting authority."""
    if not isinstance(source_sha, str) or not HEX40.fullmatch(source_sha):
        raise ValueError("invalid Hepta source SHA fence")
    if pinned_upstream != EXPECTED_REVISION:
        raise ValueError("unexpected upstream SDK source revision")
    previous = load_lock(original_lock)
    after = load_lock(resolved_lock)
    if not isinstance(metadata, dict) or type(metadata.get("packages")) is not list:
        raise ValueError("invalid Cargo metadata")
    packages = {}
    for pkg in metadata["packages"]:
        if type(pkg) is not dict:
            raise ValueError("invalid Cargo metadata package")
        key = (pkg.get("name"), pkg.get("version"), pkg.get("source"))
        if key in packages:
            raise ValueError("duplicate Cargo metadata package")
        packages[key] = pkg

    upgrades = {}
    for name in OLD:
        old = exactly_one(previous, name)
        new = exactly_one(after, name)
        if version3(old["version"]) != OLD[name]:
            raise ValueError(f"unexpected original {name} pin")
        v = version3(new["version"])
        if v < REQUIRED[name] or v[:2] != REQUIRED[name][:2]:
            raise ValueError(f"required {name} version unresolved")
        if new.get("source") != "registry+https://github.com/rust-lang/crates.io-index":
            raise ValueError(f"untrusted {name} source")
        upgrades[name] = {"old": old["version"], "resolved": new["version"]}

    if any(key[0] == "anymap2" for key in after):
        raise ValueError("unmaintained anymap2 still in resolved lock")
    exactly_one(after, "anymap3")
    for name in FAMILY:
        item = exactly_one(after, name)
        if version3(item["version"])[:2] != (0, 19):
            raise ValueError(f"Matrix SDK component {name} still has unsafe family")
    matrix_sdk = exactly_one(after, "matrix-sdk")
    sdk_source = matrix_sdk.get("source", "")
    if (not isinstance(sdk_source, str)
            or not sdk_source.startswith("git+" + EXPECTED_UPSTREAM + "?")
            or "rev=" + EXPECTED_REVISION not in sdk_source
            or not sdk_source.endswith("#" + EXPECTED_REVISION)):
        raise ValueError("Matrix SDK does not resolve to exact reviewed Git revision")

    # Cargo metadata and Cargo.lock must agree on every security-critical
    # package identity and checksum. A synthetic amended manifest or stale
    # metadata output cannot be used to manufacture a green diagnostic.
    names = set(OLD) | set(FAMILY) | {"anymap3", "anymap2"}
    for name in names:
        selected = [key for key in after if key[0] == name]
        observed = [key for key in packages if key[0] == name]
        if sorted(selected, key=str) != sorted(observed, key=str):
            raise ValueError(f"Cargo metadata disagrees with lock for {name}")
        for key in selected:
            pkg = packages[key]
            lock_sum = after[key].get("checksum")
            if pkg.get("checksum") != lock_sum:
                raise ValueError(f"Cargo metadata checksum mismatch for {name}")

    new_identities = sorted((str(key) for key in after.keys() - previous.keys()))
    removed_identities = sorted((str(key) for key in previous.keys() - after.keys()))
    return {
        "schema": SCHEMA,
        "staged_hepta_source_sha": source_sha,
        "pinned_matrix_upstream_revision": pinned_upstream,
        "original_lock_sha256": hash_bytes(original_lock),
        "resolved_lock_sha256": hash_bytes(resolved_lock),
        "cargo_lock_metadata_consistent": True,
        "upgraded_locks": upgrades,
        "added_package_identities": new_identities,
        "removed_package_identities": removed_identities,
        "matrix_family_minor": "0.19",
        "unmaintained_anymap2_present": False,
        "only_disposable_lock_examined": True,
        "original_checkout_modified": False,
        "actual_source_reviewer_approved": False,
        "cargo_deny_verified": False,
        "matrix_e2ee_verified": False,
        "sqlite_wal_recovery_verified": False,
        "production_authorized": False,
    }


def read_bounded(path, limit):
    with Path(path).open("rb") as handle:
        value = handle.read(limit + 1)
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
    paths = [args.original_lock.resolve(), args.resolved_lock.resolve(), args.metadata.resolve()]
    if args.output.resolve() in paths or len(set(paths)) != len(paths):
        parser.error("diagnostic output and inputs must be separate files")
    original = read_bounded(args.original_lock, MAX_LOCK_BYTES)
    resolved = read_bounded(args.resolved_lock, MAX_LOCK_BYTES)
    metadata = json.loads(read_bounded(args.metadata, MAX_META_BYTES))
    report = inspect(original, resolved, metadata, source_sha=args.hepta_sha)
    with args.output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
