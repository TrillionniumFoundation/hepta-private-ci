#!/usr/bin/env python3
"""Fail-closed checks for the platform.types documentation authority model."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_ROOT = REPO_ROOT / "docs" / "modules" / "platform.types"
AUTHORITATIVE = (
    "SPEC_V2.md",
    "IMPLEMENTATION_STATUS.md",
    "MIGRATION_V1_TO_V2.md",
)
DERIVED = (
    "PUBLIC_API_INVENTORY_V1.json",
    "COMPATIBILITY_MATRIX_V1.json",
    "IMPLEMENTATION_MAP.json",
)
HISTORICAL = (
    "CURRENT_IMPLEMENTATION.md",
    "TECHNICAL_CURRENT_AMENDMENT_V2.md",
    "DEEP_QUALIFICATION_V1.md",
    "QUALIFICATION_HARDENING_20260928.md",
    "QUALIFICATION_INTEGRITY_20260929.md",
    "NDU_SNAPSHOT_INTEGRATION_20260929.md",
    "REMAINING_GAPS_CLOSURE_20260929.md",
    "OPTIMIZATION_CLOSURE_20260929.md",
)


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main() -> int:
    errors: list[str] = []
    readme_path = DOC_ROOT / "README.md"
    require(readme_path.is_file(), f"missing {readme_path.relative_to(REPO_ROOT)}", errors)
    if errors:
        for error in errors:
            print(f"platform.types documentation contract: {error}", file=sys.stderr)
        return 1

    readme = readme_path.read_text(encoding="utf-8")
    require(
        "exactly three current human-readable entry points" in readme,
        "README must declare exactly three current human-readable entry points",
        errors,
    )

    for name in AUTHORITATIVE:
        path = DOC_ROOT / name
        require(path.is_file(), f"missing authoritative entry {name}", errors)
        require(f"({f'./{name}'})" in readme, f"README does not link {name}", errors)

    for name in DERIVED:
        require((DOC_ROOT / name).is_file(), f"missing derived artifact {name}", errors)
        require(name in readme, f"README does not classify derived artifact {name}", errors)

    for name in HISTORICAL:
        require((DOC_ROOT / name).is_file(), f"missing retained historical record {name}", errors)
        require(name in readme, f"README does not classify historical record {name}", errors)

    spec = (DOC_ROOT / "SPEC_V2.md").read_text(encoding="utf-8")
    require(
        re.search(r"\b[0-9a-f]{40}\b", spec, flags=re.IGNORECASE) is None,
        "SPEC_V2.md must be branch-independent and contain no commit SHA",
        errors,
    )
    for heading in (
        "Type invariants",
        "Canonical bytes",
        "Digest domains",
        "Wire schema",
        "Bounds",
        "Protocol catalog",
        "Compatibility rules",
        "Error contract",
    ):
        require(heading in spec, f"SPEC_V2.md missing section: {heading}", errors)

    status = (DOC_ROOT / "IMPLEMENTATION_STATUS.md").read_text(encoding="utf-8")
    for marker in (
        "qualification: unqualified",
        "approval_sha: null",
        "activation: false",
        "source_sha: generated-by-ci",
    ):
        require(marker in status, f"IMPLEMENTATION_STATUS.md missing fail-closed marker: {marker}", errors)

    migration = (DOC_ROOT / "MIGRATION_V1_TO_V2.md").read_text(encoding="utf-8")
    for marker in (
        "Digest32::as_bytes()",
        "Digest32::as_array()",
        "Digest32::into_array()",
        "Mandatory consumer ledger",
        "Wire compatibility scope",
    ):
        require(marker in migration, f"MIGRATION_V1_TO_V2.md missing migration marker: {marker}", errors)

    if errors:
        for error in errors:
            print(f"platform.types documentation contract: {error}", file=sys.stderr)
        return 1

    print("platform.types documentation contract: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
