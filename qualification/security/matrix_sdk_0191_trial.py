#!/usr/bin/env python3
"""Unprivileged Matrix SDK security migration probe, never a production upgrade.

Operates on CI's disposable checkout; no signing, model changes, advisory
ignores, or direct updates to the protected branch/lockfile.
"""
import argparse
import json
from pathlib import Path
import re
import tomllib

PINNED_OLD = 'matrix-sdk = { version = "0.18.0", default-features = false, features = ["e2e-encryption", "sqlite"] }'
CANDIDATE = 'matrix-sdk = { version = "=0.19.1", default-features = false, features = ["e2e-encryption", "sqlite"] }'
SHA = re.compile(r"^[0-9a-f]{40}$")


def prepare(manifest_path: Path) -> None:
    content = manifest_path.read_text(encoding="utf-8")
    if content.count(PINNED_OLD) != 1 or CANDIDATE in content:
        raise ValueError("Matrix 0.18 exact source manifest no longer matches approved trial baseline")
    manifest_path.write_text(content.replace(PINNED_OLD, CANDIDATE), encoding="utf-8")


def _version_at_least(version: str, floor: tuple[int, ...]) -> bool:
    parts = version.split(".")
    if len(parts) != 3 or not all(p.isascii() and p.isdecimal() for p in parts):
        return False
    return tuple(int(x) for x in parts) >= floor


def assess_lock(lock: dict, source_sha: str, rust_toolchain: str) -> dict:
    if not isinstance(source_sha, str) or not SHA.fullmatch(source_sha):
        raise ValueError("source must be pinned to immutable 40-character SHA")
    if rust_toolchain != "1.96.0":
        raise ValueError("Matrix SDK 0.19.1 trial requires reviewed Rust 1.96.0 toolchain")
    if not isinstance(lock, dict) or not isinstance(lock.get("package"), list):
        raise ValueError("Cargo.lock has no canonical packages")
    packages = {}
    for row in lock["package"]:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str):
            raise ValueError("malformed lockfile package")
        name, version = row["name"], row.get("version")
        if not isinstance(version, str):
            raise ValueError("lockfile package without string version")
        packages.setdefault(name, []).append(version)
    families = ("matrix-sdk", "matrix-sdk-base", "matrix-sdk-crypto", "matrix-sdk-sqlite")
    exact = {}
    for name in families:
        versions = packages.get(name, [])
        if len(versions) != 1:
            raise ValueError(f"expected one version of {name}, found {versions}")
        exact[name] = versions[0]
    crypto_fix_present = all(_version_at_least(exact[name], (0, 19, 0))
                             for name in families)
    legacy = {
        "RUSTSEC-2026-0318": not crypto_fix_present,
        "RUSTSEC-2026-0319": "anymap2" in packages,
        "RUSTSEC-2024-0449": "unsafe-libyaml" in packages,
    }
    return {
        "schema": "hepta.matrix-rustsec-migration-probe.v1",
        "source_sha": source_sha,
        "trial_toolchain": rust_toolchain,
        "candidate_matrix_sdk": "0.19.1",
        "matrix_family_versions": exact,
        "candidate_0318_crypto_fix_resolved": crypto_fix_present,
        "unresolved_advisories": [key for key, blocked in legacy.items() if blocked],
        "status": "BLOCKED" if any(legacy.values()) else "dependency_lock_candidate_only",
        "no_advisory_ignored": True,
        "production_promotion_permitted": False,
        "package_upgrade_committed": False,
        "non_matrix_advisories_still_require_independent_cargo_deny": True,
        "target_host_performance_or_ndu_qualified": False,
        "limitations": [
            "Generated from an untrusted scratch lockfile, not an accepted Cargo build receipt",
            "Matrix SDK 0.19.1 has MSRV Rust 1.96 and still depends on anymap2",
            "Any remaining advisory or cargo-deny failure is release-blocking",
        ],
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    command = p.add_subparsers(dest="command", required=True)
    pre = command.add_parser("prepare", help="rewrite CI scratch workspace manifest only")
    pre.add_argument("--manifest", type=Path, required=True)
    chk = command.add_parser("inspect", help="fail closed on unresolved locked advisories")
    chk.add_argument("--lock", type=Path, required=True)
    chk.add_argument("--sha", required=True)
    chk.add_argument("--rust", default="1.96.0")
    chk.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    if args.command == "prepare":
        prepare(args.manifest)
        return
    if args.out.exists():
        raise SystemExit("refusing to overwrite recorded security trial")
    lock = tomllib.loads(args.lock.read_text(encoding="utf-8"))
    report = assess_lock(lock, args.sha, args.rust)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    if report["status"] == "BLOCKED":
        raise SystemExit("BLOCKED: " + ", ".join(report["unresolved_advisories"]))


if __name__ == "__main__":
    main()
