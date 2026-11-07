"""Read-only, fail-closed Matrix SDK dependency preflight for Hepta P0.

This is NOT cargo-deny, code-signing, source review, or release authority.
Input is the actual Cargo.lock and the repository's pinned rust-toolchain.toml.
Tests compare graph semantics, never supply fake vulnerabilities as evidence.
"""

import argparse
from collections import deque
import json
from pathlib import Path
import re
import sys
import tomllib

SCHEMA = "hepta.matrix-sdk-p0-lock-preflight.v1"
ROOTS = ("codex-hepta-matrix-sdk", "codex-hepta-matrixd")
# Verified published crate minimums (docs.rs 0.19.0/0.19.1 Cargo.toml).
KNOWN_MATRIX_SDK_MSRV = {"0.19.0": (1, 96), "0.19.1": (1, 96)}


def parse_version(value):
    if not isinstance(value, str):
        raise ValueError("version is not a string")
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:[-+][A-Za-z0-9.\-]+)?", value)
    if not match:
        raise ValueError(f"unrecognized version: {value!r}")
    return tuple(int(match.group(i)) for i in (1, 2, 3))


def pinned_rust_version(toolchain_text):
    doc = tomllib.loads(toolchain_text)
    channel = doc["toolchain"]["channel"]
    return parse_version(channel)


def packages(lock_text):
    parsed = tomllib.loads(lock_text)
    raw = parsed.get("package")
    if not isinstance(raw, list) or not raw:
        raise ValueError("Cargo.lock lacks packages")
    result = {}
    for package in raw:
        name, version, deps = package.get("name"), package.get("version"), package.get("dependencies", [])
        if not isinstance(name, str) or not name or not isinstance(deps, list):
            raise ValueError("malformed Cargo package")
        parse_version(version)
        if any(not isinstance(x, str) for x in deps):
            raise ValueError("malformed Cargo dependency list")
        # Multiple versions are preserved. Do not silently overwrite a variant.
        result.setdefault(name, []).append({"version": version, "dependencies": deps})
    return result


def dep_name(spec):
    return spec.partition(" ")[0]


def dependency_path(locked, target):
    """Deterministic minimum-hop dependency-name path from Hepta Matrix roots.

    Cargo.lock names are intentionally sufficient for Matrix's single-version
    path here. Version-qualified duplicate edges need separate cargo tree proof.
    """
    queue = deque((root, (root,)) for root in ROOTS if root in locked)
    visited = set()
    while queue:
        name, path = queue.popleft()
        if name == target:
            return list(path)
        if name in visited:
            continue
        visited.add(name)
        for variant in locked.get(name, []):
            for spec in sorted(variant["dependencies"]):
                next_name = dep_name(spec)
                if next_name not in visited:
                    queue.append((next_name, (*path, next_name)))
    return None


def audit(lock_text, toolchain_text):
    locked = packages(lock_text)
    compiler = pinned_rust_version(toolchain_text)
    found = {name: sorted({p["version"] for p in locked.get(name, [])}) for name in
             ("matrix-sdk", "matrix-sdk-base", "matrix-sdk-crypto", "matrix-sdk-sqlite",
              "anymap2", "chacha20", "spin")}
    blockers = []
    def block(code, message):
        blockers.append({"code": code, "reason": message})
    if not all(root in locked for root in ROOTS):
        block("matrix_owner_missing", "Hepta Matrix service dependency root missing; cannot claim secure replacement")
    if not found["matrix-sdk"]:
        block("matrix_sdk_missing", "No SDK version or verified replacement in locked graph")
    if not found["matrix-sdk-crypto"]:
        block("e2ee_crypto_missing", "Missing E2EE crate is NOT a way to pass security admission")
    if found["anymap2"]:
        block("RUSTSEC-2026-0319", "Unmaintained anymap2 remains in resolved lock; direct SDK bump is insufficient")
    for version in found["matrix-sdk-crypto"]:
        if parse_version(version) < (0, 19, 0) or "-" in version:
            block("RUSTSEC-2026-0318", f"matrix-sdk-crypto {version} predates fixed >=0.19.0")
    for version in found["matrix-sdk"]:
        if "-" in version:
            block("matrix_sdk_prerelease_unverified", f"SDK candidate {version} requires explicit upstream source/version review")
        if version not in KNOWN_MATRIX_SDK_MSRV and not version.startswith("0.18."):
            block("matrix_sdk_msrv_unknown", f"SDK {version} has no pinned independently reviewed Rust MSRV")
        if version in KNOWN_MATRIX_SDK_MSRV and compiler[:2] < KNOWN_MATRIX_SDK_MSRV[version]:
            block("matrix_sdk_msrv", f"matrix-sdk {version} requires Rust {KNOWN_MATRIX_SDK_MSRV[version][0]}.{KNOWN_MATRIX_SDK_MSRV[version][1]} but toolchain pins {compiler[0]}.{compiler[1]}.{compiler[2]}")
    if found["matrix-sdk"] and found["matrix-sdk-crypto"]:
        if set(found["matrix-sdk"]) != set(found["matrix-sdk-crypto"]):
            block("matrix_sdk_family_alignment_unverified", "SDK/crypto component versions differ; prove compatible family via full native test suite")
    return {
        "schema": SCHEMA,
        "input_classification": "untrusted_read_only_lockfile_snapshot",
        "pinned_rust": ".".join(str(x) for x in compiler),
        "package_count": sum(map(len, locked.values())),
        "resolved": found,
        "provenance_paths_unverified_until_cargo_tree": {
            name: dependency_path(locked, name)
            for name in ("anymap2", "matrix-sdk-crypto")
        },
        "blocked": bool(blockers),
        "blockers": blockers,
        "other_yanked_versions_to_check_with_cargo_deny": [
            key for key, version in (("chacha20", "0.10.0"), ("spin", "0.9.8"))
            if version in found[key]
        ],
        "cargo_deny_passed": False,
        "source_provenance_verified": False,
        "matrix_e2ee_and_sqlite_recovery_tested": False,
        "production_authorized": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Hepta P0 read-only Matrix lock advisory and MSRV diagnostic")
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--toolchain", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--enforce", action="store_true", help="exit nonzero on known blockers (never a complete security PASS)")
    args = parser.parse_args(argv)
    report = audit(args.lock.read_text(encoding="utf-8"), args.toolchain.read_text(encoding="utf-8"))
    # Create-only: no old report may be overwritten to erase failed gate evidence.
    with args.output.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"Matrix P0 preflight: {'BLOCKED' if report['blocked'] else 'NO KNOWN LOCK BLOCKER'}; cargo-deny/production not attested")
    return 2 if args.enforce and report["blocked"] else 0


if __name__ == "__main__":
    sys.exit(main())
