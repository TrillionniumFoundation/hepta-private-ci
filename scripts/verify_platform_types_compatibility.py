#!/usr/bin/env python3
"""Verify the closed platform.types compatibility and mandatory-consumer matrix."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

MATRIX_SCHEMA = "hepta.platform-types.compatibility-matrix.v1"
CATALOG_SCHEMA = "hepta.platform-types.protocol-catalog.v2"
CONSUMER_SCHEMA = "hepta.platform-types.consumer-qualification.v2"
REQUIRED_ASSURANCES = (
    "decoder",
    "validatedBoundary",
    "ownerRevalidation",
    "staleStateRejection",
    "mixedVersionRollback",
)


class CompatibilityError(RuntimeError):
    """The compatibility projection is incomplete or has drifted."""


def read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CompatibilityError(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise CompatibilityError(f"JSON object required: {path}")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CompatibilityError(message)


def strings(value: Any, name: str, *, nonempty: bool = True) -> list[str]:
    require(
        isinstance(value, list)
        and all(isinstance(item, str) and item for item in value),
        f"{name} must be a non-empty string array" if nonempty else f"{name} must be a string array",
    )
    if nonempty:
        require(bool(value), f"{name} must not be empty")
    require(len(value) == len(set(value)), f"{name} contains duplicates")
    return value


def evidence_path(root: Path, relative: str) -> Path:
    require(isinstance(relative, str) and relative, "evidence path required")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as error:
        raise CompatibilityError(f"evidence path escapes repository: {relative}") from error
    require(candidate.is_file(), f"compatibility evidence missing: {relative}")
    return candidate


def _consumer_ids(consumer_matrix: dict[str, Any]) -> list[str]:
    require(
        consumer_matrix.get("schema") == CONSUMER_SCHEMA
        and consumer_matrix.get("module") == "platform.types",
        "consumer matrix header mismatch",
    )
    rows = consumer_matrix.get("consumers")
    require(isinstance(rows, list) and rows, "consumer rows required")
    identifiers = []
    for row in rows:
        require(isinstance(row, dict), "consumer row must be an object")
        identifier = row.get("id")
        require(isinstance(identifier, str) and identifier, "consumer id required")
        require(identifier not in identifiers, f"duplicate consumer id: {identifier}")
        identifiers.append(identifier)
    return identifiers


def verify(
    catalog: dict[str, Any],
    matrix: dict[str, Any],
    consumer_matrix: dict[str, Any],
    root: Path,
) -> dict[str, Any]:
    require(
        catalog.get("schema") == CATALOG_SCHEMA
        and catalog.get("schemaVersion") == 2
        and catalog.get("normativeSource")
        == "codex-rs/hepta-types/src/protocol_catalog_v2.rs",
        "protocol catalog header mismatch",
    )
    catalog_rows = catalog.get("protocols")
    require(
        isinstance(catalog_rows, list)
        and catalog.get("protocolCount") == len(catalog_rows)
        and bool(catalog_rows),
        "protocol catalog rows mismatch",
    )

    require(
        matrix.get("schema") == MATRIX_SCHEMA
        and matrix.get("schemaVersion") == 1
        and matrix.get("module") == "platform.types"
        and matrix.get("normativeCatalog")
        == "codex-rs/hepta-types/src/protocol_catalog_v2.rs"
        and matrix.get("consumerMatrix")
        == "codex-rs/hepta-types/CONSUMER_QUALIFICATION_V1.json",
        "compatibility matrix header mismatch",
    )
    require(
        matrix.get("requiredAssurances") == list(REQUIRED_ASSURANCES),
        "required assurance dimensions drifted",
    )

    consumer_ids = _consumer_ids(consumer_matrix)
    mandatory = strings(matrix.get("mandatoryConsumers"), "mandatoryConsumers")
    optional = strings(matrix.get("optionalConsumers"), "optionalConsumers", nonempty=False)
    require(mandatory == consumer_ids, "mandatory consumer set/order differs from consumer matrix")
    require(optional == [], "optional consumers must be explicitly empty for this qualification")

    rows = matrix.get("protocols")
    require(isinstance(rows, list), "compatibility protocol rows required")
    catalog_ids = [row.get("id") for row in catalog_rows if isinstance(row, dict)]
    matrix_ids = [row.get("id") for row in rows if isinstance(row, dict)]
    require(matrix_ids == catalog_ids, "compatibility protocol set/order differs from Rust catalog")

    covered_consumers: set[str] = set()
    report_rows = []
    for catalog_row, row in zip(catalog_rows, rows, strict=True):
        require(isinstance(catalog_row, dict) and isinstance(row, dict), "protocol row must be an object")
        identifier = catalog_row.get("id")
        require(isinstance(identifier, str) and identifier, "catalog protocol id required")
        for key in ("semanticTypeId", "codecOwner", "compatibility"):
            require(row.get(key) == catalog_row.get(key), f"{identifier}: {key} drift")
        version = catalog_row.get("version")
        require(type(version) is int and version > 0, f"{identifier}: invalid catalog version")
        require(row.get("semanticVersion") == version, f"{identifier}: semantic version drift")
        wire_version = row.get("wireVersion")
        require(type(wire_version) is int and wire_version > 0, f"{identifier}: wire version required")
        for key in ("migration", "rollbackStrategy"):
            value = row.get(key)
            require(isinstance(value, str) and len(value.strip()) >= 24, f"{identifier}: {key} is incomplete")

        consumers = strings(row.get("consumers"), f"{identifier}.consumers")
        require(set(consumers) <= set(mandatory), f"{identifier}: unknown/non-mandatory consumer")
        covered_consumers.update(consumers)

        vectors = strings(row.get("goldenVectors"), f"{identifier}.goldenVectors")
        vector_rows = []
        for relative in vectors:
            path = evidence_path(root, relative)
            raw = path.read_bytes()
            vector_rows.append(
                {
                    "path": relative,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "bytes": len(raw),
                }
            )

        assurances = row.get("assurances")
        require(isinstance(assurances, dict), f"{identifier}: assurances object required")
        require(tuple(assurances) == REQUIRED_ASSURANCES, f"{identifier}: assurance dimensions/order drifted")
        assurance_report = {}
        for dimension in REQUIRED_ASSURANCES:
            assurance = assurances[dimension]
            require(isinstance(assurance, dict), f"{identifier}.{dimension}: object required")
            status = assurance.get("status")
            require(status in ("evidenced", "not_applicable"), f"{identifier}.{dimension}: invalid status")
            if status == "evidenced":
                assurance_consumers = strings(
                    assurance.get("consumers"),
                    f"{identifier}.{dimension}.consumers",
                )
                require(
                    set(assurance_consumers) <= set(consumers),
                    f"{identifier}.{dimension}: assurance consumer outside protocol row",
                )
                assurance_report[dimension] = {
                    "status": status,
                    "consumers": assurance_consumers,
                }
            else:
                reason = assurance.get("reason")
                require(
                    isinstance(reason, str) and len(reason.strip()) >= 24,
                    f"{identifier}.{dimension}: not-applicable reason is incomplete",
                )
                require(
                    "consumers" not in assurance,
                    f"{identifier}.{dimension}: not-applicable assurance cannot cite consumers",
                )
                assurance_report[dimension] = {"status": status, "reason": reason}

        report_rows.append(
            {
                "id": identifier,
                "wireVersion": wire_version,
                "semanticVersion": version,
                "consumers": consumers,
                "goldenVectors": vector_rows,
                "assurances": assurance_report,
                "status": "passed",
            }
        )

    require(
        covered_consumers == set(mandatory),
        "one or more mandatory consumers are not assigned to a protocol",
    )
    return {
        "schema": "hepta.platform-types.compatibility-verification.v1",
        "schemaVersion": 1,
        "normativeSource": catalog["normativeSource"],
        "protocolCount": len(report_rows),
        "mandatoryConsumerCount": len(mandatory),
        "optionalConsumerCount": 0,
        "protocols": report_rows,
        "status": "passed",
        "claimBoundary": (
            "catalog-aligned version, migration, owner, mandatory-consumer, "
            "golden-vector and rollback evidence; not product activation or release"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument(
        "--matrix",
        type=Path,
        default=Path("docs/modules/platform.types/COMPATIBILITY_MATRIX_V1.json"),
    )
    parser.add_argument(
        "--consumer-matrix",
        type=Path,
        default=Path("codex-rs/hepta-types/CONSUMER_QUALIFICATION_V1.json"),
    )
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        report = verify(
            read_object(args.catalog),
            read_object(root / args.matrix if not args.matrix.is_absolute() else args.matrix),
            read_object(
                root / args.consumer_matrix
                if not args.consumer_matrix.is_absolute()
                else args.consumer_matrix
            ),
            root,
        )
    except CompatibilityError as error:
        print(f"platform.types compatibility matrix failed: {error}", file=sys.stderr)
        return 1
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "platform.types compatibility matrix: ok "
        f"({report['protocolCount']} protocols, "
        f"{report['mandatoryConsumerCount']} mandatory consumers)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
