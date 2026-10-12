#!/usr/bin/env python3
"""Read-only, strictly non-authorizing Matrix SDK dependency qualification.

This reports, but does not suppress, two RustSec advisories. A successful
execution of this reporting script is NOT an accepted security qualification.
"""
from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path

SECURITY_ADVISORIES = ("RUSTSEC-2026-0318", "RUSTSEC-2026-0319")


def _read_toml(path: Path) -> dict:
    try:
        with path.open("rb") as stream:
            return tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"unable to read {path}: {exc}") from exc


def _version_tuple(value: str) -> tuple[int, int, int] | None:
    value = value.removeprefix("=").removeprefix("v").strip()
    try:
        parts = value.split(".")
        if len(parts) != 3 or any(not x.isdecimal() for x in parts):
            return None
        return tuple(map(int, parts))  # type: ignore[return-value]
    except ValueError:
        return None


def evaluate(*, manifest: dict, lock: dict, deny: dict, cargo_update: str,
             cargo_check: str, cargo_test: str) -> dict:
    sdk = manifest.get("workspace", {}).get("dependencies", {}).get("matrix-sdk", {})
    requirement = sdk.get("version") if isinstance(sdk, dict) else None
    packages = lock.get("package", [])
    if not isinstance(packages, list):
        packages = []
    observed: dict[str, list[str]] = {}
    for entry in packages:
        if isinstance(entry, dict) and isinstance(entry.get("name"), str):
            observed.setdefault(entry["name"], []).append(str(entry.get("version", "")))
    for values in observed.values():
        values.sort()
    crypto_versions = observed.get("matrix-sdk-crypto", [])
    outdated_crypto = not crypto_versions or any(
        version is None or version < (0, 19, 0)
        for version in (_version_tuple(v) for v in crypto_versions)
    )
    unmaintained_anymap = bool(observed.get("anymap2"))
    ignored = deny.get("advisories", {}).get("ignore", [])
    ignored_ids = {
        item.get("id") if isinstance(item, dict) else item
        for item in ignored if isinstance(item, (str, dict))
    }
    tampered_policy = sorted(set(SECURITY_ADVISORIES) & ignored_ids)
    complete_execution = all(
        item == "success" for item in (cargo_update, cargo_check, cargo_test)
    )
    result = {
        "schema": "hepta.matrix.security-preflight.v1",
        "authority": "none",
        "profile": "research-only-no-release",
        "matrix_sdk_requirement": requirement,
        "resolved_matrix_sdk": observed.get("matrix-sdk", []),
        "resolved_crypto": crypto_versions,
        "resolved_anymap2": observed.get("anymap2", []),
        "rustsec": {
            "RUSTSEC-2026-0318": "blocked" if outdated_crypto else "no-affected-crypto-version-in-lock",
            "RUSTSEC-2026-0319": "blocked" if unmaintained_anymap else "no-anymap2-in-lock",
        },
        "ignored_security_advisories": tampered_policy,
        "execution": {
            "cargo_update": cargo_update,
            "cargo_check": cargo_check,
            "cargo_test": cargo_test,
        },
        "security_ready": (
            not outdated_crypto and not unmaintained_anymap
            and not tampered_policy and complete_execution
        ),
    }
    result["disposition"] = "evidence-only" if result["security_ready"] else "BLOCKED"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--lock", required=True, type=Path)
    parser.add_argument("--deny", required=True, type=Path)
    parser.add_argument("--update-status", choices=("success", "failed", "not-run"), default="not-run")
    parser.add_argument("--check-status", choices=("success", "failed", "not-run"), default="not-run")
    parser.add_argument("--test-status", choices=("success", "failed", "not-run"), default="not-run")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = evaluate(
        manifest=_read_toml(args.manifest),
        lock=_read_toml(args.lock),
        deny=_read_toml(args.deny),
        cargo_update=args.update_status,
        cargo_check=args.check_status,
        cargo_test=args.test_status,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "disposition": result["disposition"],
        "matrix_sdk": result["resolved_matrix_sdk"],
        "crypto": result["resolved_crypto"],
        "anymap2": result["resolved_anymap2"],
        "policy_ignored": result["ignored_security_advisories"],
    }, ensure_ascii=False))
    return 0  # Evidence generation is separate from release admission.


if __name__ == "__main__":
    raise SystemExit(main())
