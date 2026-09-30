#!/usr/bin/env python3
"""Generate and verify the current machine-readable platform.types truth matrix."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DOC_ROOT = ROOT / "docs" / "modules" / "platform.types"
OUTPUT_PATH = DOC_ROOT / "TRUTH_MATRIX_V2.json"
PUBLIC_API_PATH = DOC_ROOT / "PUBLIC_API_INVENTORY_V1.json"
COMPATIBILITY_PATH = DOC_ROOT / "COMPATIBILITY_MATRIX_V1.json"
IMPLEMENTATION_MAP_PATH = DOC_ROOT / "IMPLEMENTATION_MAP.json"
STATUS_SOURCE_PATH = DOC_ROOT / "implementation_status_source.json"
ARCHIVE_MANIFEST_PATH = DOC_ROOT / "archive" / "MANIFEST.json"
LEGACY_TRUTH_MATRIX = "docs/lane-a-foundation/platform.types/TRUTH_MATRIX_V1.json"
AUTHORITATIVE_ENTRIES = {
    "specification": "docs/modules/platform.types/SPEC_V2.md",
    "implementationStatus": "docs/modules/platform.types/IMPLEMENTATION_STATUS.md",
    "migration": "docs/modules/platform.types/MIGRATION_V1_TO_V2.md",
}


class TruthMatrixError(RuntimeError):
    """The generated truth projection is missing, malformed, or stale."""


def read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TruthMatrixError(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise TruthMatrixError(f"JSON object required: {path}")
    return value


def require_file(root: Path, relative: str) -> None:
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise TruthMatrixError(f"repository path escapes root: {relative}") from error
    if not path.is_file():
        raise TruthMatrixError(f"required repository path is missing: {relative}")


def positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise TruthMatrixError(f"{label} must be a non-negative integer")
    return value


def expected_truth(root: Path = ROOT) -> dict[str, Any]:
    doc_root = root / "docs" / "modules" / "platform.types"
    public_api = read_object(doc_root / "PUBLIC_API_INVENTORY_V1.json")
    compatibility = read_object(doc_root / "COMPATIBILITY_MATRIX_V1.json")
    implementation_map = read_object(doc_root / "IMPLEMENTATION_MAP.json")
    status = read_object(doc_root / "implementation_status_source.json")
    archive = read_object(doc_root / "archive" / "MANIFEST.json")

    for label, value, schema in (
        (
            "public API inventory",
            public_api,
            "hepta.platform-types.public-api-inventory.v1",
        ),
        (
            "compatibility matrix",
            compatibility,
            "hepta.platform-types.compatibility-matrix.v1",
        ),
        (
            "archive manifest",
            archive,
            "hepta.platform-types.documentation-archive.v1",
        ),
    ):
        if value.get("schema") != schema or value.get("module") != "platform.types":
            raise TruthMatrixError(f"{label} schema or module mismatch")

    if implementation_map.get("schema") != "hepta.module-implementation-map.v3":
        raise TruthMatrixError("implementation map schema mismatch")
    if implementation_map.get("module") != "platform.types":
        raise TruthMatrixError("implementation map module mismatch")
    map_inventory = implementation_map.get("publicApiInventory")
    if not isinstance(map_inventory, dict):
        raise TruthMatrixError("implementation map publicApiInventory is missing")

    export_count = positive_int(public_api.get("exportCount"), "publicApi.exportCount")
    operation_count = positive_int(
        public_api.get("operationCount"),
        "publicApi.operationCount",
    )
    source_module_count = positive_int(
        public_api.get("sourceModuleCount"),
        "publicApi.sourceModuleCount",
    )
    if map_inventory.get("exportCount") != export_count:
        raise TruthMatrixError("implementation map export count is stale")
    if map_inventory.get("operationCount") != operation_count:
        raise TruthMatrixError("implementation map operation count is stale")

    protocols = compatibility.get("protocols")
    mandatory_consumers = compatibility.get("mandatoryConsumers")
    records = archive.get("records")
    if not isinstance(protocols, list) or not protocols:
        raise TruthMatrixError("compatibility matrix has no protocol rows")
    if not isinstance(mandatory_consumers, list) or not mandatory_consumers:
        raise TruthMatrixError("compatibility matrix has no mandatory consumers")
    if not isinstance(records, list) or not records:
        raise TruthMatrixError("archive manifest has no records")

    expected_status_header = {
        "schema": "platform.types/implementation-status-source/v1",
        "spec_version": "platform.types/v2",
    }
    for key, expected in expected_status_header.items():
        if status.get(key) != expected:
            raise TruthMatrixError(
                f"implementation status source {key} mismatch: expected {expected!r}"
            )
    owner_migration = status.get("owner_migration")
    if not isinstance(owner_migration, str) or not owner_migration:
        raise TruthMatrixError("owner_migration must be a non-empty string")

    # Committed source may describe implementation facts, but it cannot self-certify
    # workflow success, reviewer approval, or activation.
    if status.get("qualification") != "unqualified":
        raise TruthMatrixError(
            "committed status source must remain unqualified; exact-head evidence is runtime-only"
        )
    if status.get("approval_sha") is not None:
        raise TruthMatrixError(
            "committed status source must not self-assert an approval SHA"
        )
    if status.get("activation") is not False:
        raise TruthMatrixError(
            "committed status source must not self-assert activation"
        )

    for relative in AUTHORITATIVE_ENTRIES.values():
        require_file(root, relative)
    for relative in (
        "docs/modules/platform.types/PUBLIC_API_INVENTORY_V1.json",
        "docs/modules/platform.types/COMPATIBILITY_MATRIX_V1.json",
        "docs/modules/platform.types/IMPLEMENTATION_MAP.json",
        "docs/modules/platform.types/archive/MANIFEST.json",
        LEGACY_TRUTH_MATRIX,
    ):
        require_file(root, relative)

    return {
        "schema": "hepta.platform-types.truth-matrix.v2",
        "schemaVersion": 2,
        "module": "platform.types",
        "generationCommand": "python3 scripts/platform_types_truth_matrix.py --write",
        "generatedFrom": [
            "docs/modules/platform.types/PUBLIC_API_INVENTORY_V1.json",
            "docs/modules/platform.types/COMPATIBILITY_MATRIX_V1.json",
            "docs/modules/platform.types/IMPLEMENTATION_MAP.json",
            "docs/modules/platform.types/implementation_status_source.json",
            "docs/modules/platform.types/archive/MANIFEST.json",
        ],
        "authorityModel": {
            "humanReadableEntries": AUTHORITATIVE_ENTRIES,
            "machineReadableDerivatives": {
                "publicApiInventory": "docs/modules/platform.types/PUBLIC_API_INVENTORY_V1.json",
                "compatibilityMatrix": "docs/modules/platform.types/COMPATIBILITY_MATRIX_V1.json",
                "implementationMap": "docs/modules/platform.types/IMPLEMENTATION_MAP.json",
                "archiveManifest": "docs/modules/platform.types/archive/MANIFEST.json",
            },
            "legacyTruthMatrix": LEGACY_TRUTH_MATRIX,
        },
        "sourceFacts": {
            "specVersion": status["spec_version"],
            "ownerMigration": owner_migration,
            "publicApiExportCount": export_count,
            "publicApiOperationCount": operation_count,
            "publicApiSourceModuleCount": source_module_count,
            "protocolCount": len(protocols),
            "mandatoryConsumerCount": len(mandatory_consumers),
            "archivedRecordCount": len(records),
        },
        "qualificationState": {
            "qualification": status["qualification"],
            "approvalSha": status["approval_sha"],
            "activation": status["activation"],
            "sourceIdentity": "injected-only-into-exact-head-runtime-evidence",
            "requiredOrdering": [
                "exact-source qualification",
                "fixed synthetic-merge qualification",
                "independent same-head approval",
                "merge to main",
                "post-merge qualification",
                "explicit activation",
            ],
        },
        "claimBoundary": (
            "source-derived implementation and migration facts only; qualification, "
            "approval, merge, activation, promotion, and release require external "
            "exact-SHA evidence and are never inferred from this committed projection"
        ),
    }


def write_truth(root: Path = ROOT) -> dict[str, Any]:
    value = expected_truth(root)
    path = root / "docs" / "modules" / "platform.types" / "TRUTH_MATRIX_V2.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return value


def verify_truth(root: Path = ROOT) -> dict[str, Any]:
    expected = expected_truth(root)
    path = root / "docs" / "modules" / "platform.types" / "TRUTH_MATRIX_V2.json"
    actual = read_object(path)
    if actual != expected:
        raise TruthMatrixError(
            "TRUTH_MATRIX_V2.json drift; run "
            "`python3 scripts/platform_types_truth_matrix.py --write`"
        )
    canonical = json.dumps(actual, indent=2, ensure_ascii=False) + "\n"
    if path.read_text(encoding="utf-8") != canonical:
        raise TruthMatrixError(
            "TRUTH_MATRIX_V2.json is not canonical JSON"
        )
    return expected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.write and args.check:
        parser.error("--write and --check are mutually exclusive")
    try:
        value = write_truth() if args.write else verify_truth()
    except TruthMatrixError as error:
        print(f"platform.types truth matrix failed: {error}", file=sys.stderr)
        return 1
    facts = value["sourceFacts"]
    action = "generated" if args.write else "verified"
    print(
        f"platform.types truth matrix: {action} "
        f"({facts['publicApiExportCount']} exports, "
        f"{facts['protocolCount']} protocols, "
        f"{facts['mandatoryConsumerCount']} mandatory consumers)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
