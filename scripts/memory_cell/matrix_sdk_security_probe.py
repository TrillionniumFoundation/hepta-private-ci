"""Read-only Matrix SDK dependency risk delta; never waive cargo-deny.

This diagnostic compares two Cargo.lock graphs, not runtime exploitability or
migration compatibility. The original blocking cargo-deny remains authoritative.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import tomllib

CRITICAL = (
    "matrix-sdk",
    "matrix-sdk-crypto",
    "matrix-sdk-sqlite",
)
KNOWN = {
    "RUSTSEC-2026-0318": "matrix-sdk-crypto",
    "RUSTSEC-2026-0319": "anymap2",
    "RUSTSEC-2024-0449": "unsafe-libyaml",
}


def _version(value):
    match = (
        re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:[-+][A-Za-z0-9.-]+)?", value)
        if isinstance(value, str)
        else None
    )
    if match is None:
        raise ValueError("noncanonical Cargo package version")
    return tuple(map(int, match.groups()))


def inventory(raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 16 * 1024 * 1024:
        raise ValueError("bounded Cargo.lock bytes required")
    data = tomllib.loads(raw.decode("utf-8", "strict"))
    rows = data.get("package")
    if not isinstance(rows, list) or not rows or len(rows) > 10000:
        raise ValueError("missing bounded lockfile package census")
    keyed = set()
    by_name = {}
    for package in rows:
        if not isinstance(package, dict):
            raise ValueError("invalid lockfile package")
        name, version = package.get("name"), package.get("version")
        if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", name):
            raise ValueError("invalid Cargo package name")
        _version(version)
        key = (name, version, package.get("source"))
        if key in keyed:
            raise ValueError("duplicate exact Cargo package identity")
        keyed.add(key)
        by_name.setdefault(name, set()).add(version)
    for name in CRITICAL:
        if name not in by_name or len(by_name[name]) != 1:
            raise ValueError("critical Matrix SDK component absent or ambiguous")
    sdk = _version(next(iter(by_name["matrix-sdk"])))
    crypto = _version(next(iter(by_name["matrix-sdk-crypto"])))
    sqlite = _version(next(iter(by_name["matrix-sdk-sqlite"])))
    if sdk != crypto or sdk != sqlite:
        raise ValueError("Matrix SDK and crypto/sqlite dependency versions diverged")
    risks = []
    if crypto < (0, 19, 0):
        risks.append("RUSTSEC-2026-0318")
    if "anymap2" in by_name:
        risks.append("RUSTSEC-2026-0319")
    if "unsafe-libyaml" in by_name:
        risks.append("RUSTSEC-2024-0449")
    return dict(
        sha256=hashlib.sha256(raw).hexdigest(),
        packages=len(rows),
        sdk_version=".".join(map(str, sdk)),
        crypto_version=".".join(map(str, crypto)),
        sqlite_version=".".join(map(str, sqlite)),
        known_relevant_advisories=sorted(risks),
        unsupported_zero_risk_claim=False,
    )


def compare(baseline, proposed):
    before, after = inventory(baseline), inventory(proposed)
    if _version(after["sdk_version"]) < _version(before["sdk_version"]):
        raise ValueError("proposed Matrix SDK graph downgrades the baseline")
    return dict(
        schema="hepta.matrix-security-candidate-source-only.v1",
        baseline=before,
        candidate=after,
        original_blocking_cargo_deny_still_required=True,
        proposed_version_not_api_compatibility_evidence=True,
        removed_known_advisories=sorted(
            set(before["known_relevant_advisories"])
            - set(after["known_relevant_advisories"])
        ),
        remaining_known_advisories=after["known_relevant_advisories"],
        candidate_independently_safe=False,
        code_compilation_verified_here=False,
        full_cargo_deny_qualified=False,
        production_accepted=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    for name in ("baseline", "candidate"):
        path = getattr(args, name)
        if path.is_symlink() or not path.is_file():
            raise ValueError("bounded non-symlink lockfile required")
    result = compare(args.baseline.read_bytes(), args.candidate.read_bytes())
    with args.output.open("x", encoding="utf-8") as dest:
        json.dump(result, dest, indent=2, sort_keys=True, allow_nan=False)
        dest.write("\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
