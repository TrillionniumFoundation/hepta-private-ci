#!/usr/bin/env python3
"""Fail-closed checks for the platform.types documentation authority model."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_ROOT = REPO_ROOT / "docs" / "modules" / "platform.types"
AUTHORITATIVE = (
    "SPEC_V2.md",
    "IMPLEMENTATION_STATUS.md",
    "MIGRATION_V1_TO_V2.md",
)
AUTHORITATIVE_PATHS = tuple(
    f"docs/modules/platform.types/{name}" for name in AUTHORITATIVE
)
DERIVED = (
    "PUBLIC_API_INVENTORY_V1.json",
    "COMPATIBILITY_MATRIX_V1.json",
    "IMPLEMENTATION_MAP.json",
    "TRUTH_MATRIX_V2.json",
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
ARCHIVE_MANIFEST = DOC_ROOT / "archive" / "MANIFEST.json"
SHA40 = re.compile(r"^[0-9a-f]{40}$")


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def read_object(path: Path, errors: list[str]) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        errors.append(f"cannot read JSON {path.relative_to(REPO_ROOT)}: {error}")
        return None
    if not isinstance(value, dict):
        errors.append(f"JSON object required: {path.relative_to(REPO_ROOT)}")
        return None
    return value


def git_output(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def validate_technical_authority(text: str, errors: list[str]) -> None:
    introduction = text.split("\n## ", 1)[0]
    current_links = re.findall(r"\]\(\./([^)]+)\)", introduction)
    require(
        tuple(current_links) == AUTHORITATIVE,
        "TECHNICAL introduction must direct readers to exactly the three current entries",
        errors,
    )
    for name in HISTORICAL:
        require(
            name not in introduction,
            f"TECHNICAL introduction must not direct current interpretation to archived {name}",
            errors,
        )


def validate_archive_manifest(readme: str, errors: list[str]) -> None:
    require(
        "archive/MANIFEST.json" in readme,
        "README must link archive/MANIFEST.json",
        errors,
    )
    require(
        ARCHIVE_MANIFEST.is_file(),
        "missing archive/MANIFEST.json",
        errors,
    )
    if not ARCHIVE_MANIFEST.is_file():
        return

    manifest = read_object(ARCHIVE_MANIFEST, errors)
    if manifest is None:
        return

    require(
        manifest.get("schema") == "hepta.platform-types.documentation-archive.v1",
        "archive manifest schema mismatch",
        errors,
    )
    require(
        manifest.get("schemaVersion") == 1, "archive schemaVersion mismatch", errors
    )
    require(
        manifest.get("module") == "platform.types", "archive module mismatch", errors
    )
    require(
        manifest.get("authoritativeEntries") == list(AUTHORITATIVE_PATHS),
        "archive authoritativeEntries must name exactly the three current entries",
        errors,
    )
    claim = manifest.get("claimBoundary")
    require(
        isinstance(claim, str) and "does not qualify" in claim,
        "archive manifest needs a non-qualification claim boundary",
        errors,
    )

    relocation = manifest.get("relocationPolicy")
    require(
        isinstance(relocation, dict),
        "archive relocationPolicy must be an object",
        errors,
    )
    if isinstance(relocation, dict):
        require(
            relocation.get("status") == "retained_in_place",
            "archive relocationPolicy.status must be retained_in_place",
            errors,
        )
        require(
            isinstance(relocation.get("moveCondition"), str)
            and "manifest" in relocation["moveCondition"],
            "archive relocationPolicy must define a manifest-based move condition",
            errors,
        )

    records = manifest.get("records")
    require(isinstance(records, list), "archive records must be a list", errors)
    if not isinstance(records, list):
        return

    expected_paths = {f"docs/modules/platform.types/{name}" for name in HISTORICAL}
    observed_paths = {
        row.get("path")
        for row in records
        if isinstance(row, dict) and isinstance(row.get("path"), str)
    }
    require(
        observed_paths == expected_paths,
        "archive record set must exactly cover retained historical documents",
        errors,
    )
    require(
        len(records) == len(expected_paths),
        "archive records contain duplicate or malformed entries",
        errors,
    )

    for row in records:
        if not isinstance(row, dict):
            errors.append("archive record must be an object")
            continue
        relative = row.get("path")
        if not isinstance(relative, str):
            errors.append("archive record path must be a string")
            continue
        path = REPO_ROOT / relative
        require(path.is_file(), f"missing archived-in-place record: {relative}", errors)
        require(
            row.get("status") == "superseded",
            f"{relative}: status must be superseded",
            errors,
        )

        superseded_by = row.get("supersededBy")
        require(
            isinstance(superseded_by, list)
            and bool(superseded_by)
            and all(item in AUTHORITATIVE_PATHS for item in superseded_by),
            f"{relative}: supersededBy must point only to current authoritative entries",
            errors,
        )

        source_sha = row.get("sourceSha")
        source_blob = row.get("sourceGitBlob")
        require(
            isinstance(source_sha, str) and SHA40.fullmatch(source_sha) is not None,
            f"{relative}: sourceSha must be a lowercase 40-hex commit",
            errors,
        )
        require(
            isinstance(source_blob, str) and SHA40.fullmatch(source_blob) is not None,
            f"{relative}: sourceGitBlob must be a lowercase 40-hex blob",
            errors,
        )
        require(
            row.get("validUntil") == "path-bound-evidence-retirement",
            f"{relative}: validUntil must be path-bound-evidence-retirement",
            errors,
        )
        record_claim = row.get("claimBoundary")
        require(
            isinstance(record_claim, str) and "not a current" in record_claim,
            f"{relative}: claimBoundary must reject current-authority use",
            errors,
        )

        if (
            path.is_file()
            and isinstance(source_sha, str)
            and SHA40.fullmatch(source_sha)
            and isinstance(source_blob, str)
            and SHA40.fullmatch(source_blob)
        ):
            try:
                git_output("cat-file", "-e", f"{source_sha}^{{commit}}")
                tree_row = git_output("ls-tree", source_sha, "--", relative)
                parts = tree_row.split(None, 3)
                observed_source_blob = parts[2] if len(parts) >= 3 else ""
                current_blob = git_output("hash-object", "--", relative)
            except (OSError, subprocess.CalledProcessError) as error:
                errors.append(
                    f"{relative}: cannot verify immutable archive identity: {error}"
                )
            else:
                require(
                    observed_source_blob == source_blob,
                    f"{relative}: sourceSha does not contain sourceGitBlob",
                    errors,
                )
                require(
                    current_blob == source_blob,
                    f"{relative}: historical content changed without a new archive record",
                    errors,
                )


def main() -> int:
    errors: list[str] = []
    readme_path = DOC_ROOT / "README.md"
    require(
        readme_path.is_file(), f"missing {readme_path.relative_to(REPO_ROOT)}", errors
    )
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

    current_section_match = re.search(
        r"## Current authoritative entry points\n(?P<body>.*?)(?=\n## )",
        readme,
        flags=re.DOTALL,
    )
    require(
        current_section_match is not None,
        "README current-authority section is missing",
        errors,
    )
    if current_section_match is not None:
        current_links = re.findall(
            r"\]\(\./([^)]+)\)", current_section_match.group("body")
        )
        require(
            tuple(current_links) == AUTHORITATIVE,
            "README current-authority section must link exactly the three authoritative entries",
            errors,
        )

    for name in AUTHORITATIVE:
        path = DOC_ROOT / name
        require(path.is_file(), f"missing authoritative entry {name}", errors)
        require(f"](./{name})" in readme, f"README does not link {name}", errors)

    for name in DERIVED:
        require((DOC_ROOT / name).is_file(), f"missing derived artifact {name}", errors)
        require(
            name in readme, f"README does not classify derived artifact {name}", errors
        )

    for name in HISTORICAL:
        require(
            (DOC_ROOT / name).is_file(),
            f"missing retained historical record {name}",
            errors,
        )
        require(
            name in readme, f"README does not classify historical record {name}", errors
        )

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
        require(
            marker in status,
            f"IMPLEMENTATION_STATUS.md missing fail-closed marker: {marker}",
            errors,
        )

    migration = (DOC_ROOT / "MIGRATION_V1_TO_V2.md").read_text(encoding="utf-8")
    for marker in (
        "Digest32::as_bytes()",
        "Digest32::as_array()",
        "Digest32::into_array()",
        "Mandatory consumer ledger",
        "Wire compatibility scope",
    ):
        require(
            marker in migration,
            f"MIGRATION_V1_TO_V2.md missing migration marker: {marker}",
            errors,
        )

    require(
        "check_platform_types_generated_artifacts.py" in readme,
        "README must name the generated-artifact verification entrypoint",
        errors,
    )
    technical_path = DOC_ROOT / "TECHNICAL.md"
    require(technical_path.is_file(), "missing supporting TECHNICAL.md", errors)
    if technical_path.is_file():
        validate_technical_authority(technical_path.read_text(encoding="utf-8"), errors)
    validate_archive_manifest(readme, errors)

    if errors:
        for error in errors:
            print(f"platform.types documentation contract: {error}", file=sys.stderr)
        return 1

    print("platform.types documentation contract: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
