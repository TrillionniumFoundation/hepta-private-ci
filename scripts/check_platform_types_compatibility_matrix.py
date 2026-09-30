#!/usr/bin/env python3
"""Validate the platform.types compatibility matrix against source consumers."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MATRIX_RELATIVE = "docs/modules/platform.types/COMPATIBILITY_MATRIX_V1.json"
CONSUMER_RELATIVE = "codex-rs/hepta-types/CONSUMER_QUALIFICATION_V1.json"
MATRIX_PATH = ROOT / MATRIX_RELATIVE
EXPECTED_ASSURANCES = (
    "decoder",
    "validatedBoundary",
    "ownerRevalidation",
    "staleStateRejection",
    "mixedVersionRollback",
)


class CompatibilityMatrixError(RuntimeError):
    """The compatibility matrix is malformed or diverges from source evidence."""


def read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CompatibilityMatrixError(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise CompatibilityMatrixError(f"JSON object required: {path}")
    return value


def repo_file(root: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise CompatibilityMatrixError(f"{label} must be a non-empty repository path")
    root_resolved = root.resolve()
    candidate = (root / value).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as error:
        raise CompatibilityMatrixError(f"{label} escapes the repository: {value}") from error
    if not candidate.is_file():
        raise CompatibilityMatrixError(f"{label} is missing: {value}")
    return candidate


def string_list(value: Any, label: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list):
        raise CompatibilityMatrixError(f"{label} must be a list")
    if not allow_empty and not value:
        raise CompatibilityMatrixError(f"{label} must not be empty")
    if not all(isinstance(item, str) and item for item in value):
        raise CompatibilityMatrixError(f"{label} must contain non-empty strings")
    if len(value) != len(set(value)):
        raise CompatibilityMatrixError(f"{label} contains duplicates")
    return value


def nonempty_text(row: dict[str, Any], key: str, label: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CompatibilityMatrixError(f"{label}.{key} must be non-empty text")
    return value


def validate_consumer_matrix(
    root: Path,
    consumer_matrix: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    if consumer_matrix.get("schema") != "hepta.platform-types.consumer-qualification.v2":
        raise CompatibilityMatrixError("consumer matrix schema mismatch")
    if consumer_matrix.get("module") != "platform.types":
        raise CompatibilityMatrixError("consumer matrix module mismatch")
    rows = consumer_matrix.get("consumers")
    if not isinstance(rows, list) or not rows:
        raise CompatibilityMatrixError("consumer matrix needs consumer rows")

    result: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        label = f"consumer[{index}]"
        if not isinstance(row, dict):
            raise CompatibilityMatrixError(f"{label} must be an object")
        consumer_id = nonempty_text(row, "id", label)
        if consumer_id in result:
            raise CompatibilityMatrixError(f"duplicate consumer id: {consumer_id}")
        nonempty_text(row, "kind", label)
        path_value = nonempty_text(row, "path", label)
        path = repo_file(root, path_value, f"{label}.path")
        needles = string_list(row.get("mustContain"), f"{label}.mustContain")
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise CompatibilityMatrixError(
                f"cannot inspect consumer {consumer_id}: {error}"
            ) from error
        missing = [needle for needle in needles if needle not in content]
        if missing:
            raise CompatibilityMatrixError(
                f"consumer {consumer_id} is missing required source markers: "
                + ", ".join(repr(item) for item in missing)
            )
        result[consumer_id] = row
    return result


def validate_assurance(
    protocol_id: str,
    assurance_name: str,
    value: Any,
    protocol_consumers: set[str],
) -> None:
    label = f"{protocol_id}.assurances.{assurance_name}"
    if not isinstance(value, dict):
        raise CompatibilityMatrixError(f"{label} must be an object")
    status = value.get("status")
    if status == "evidenced":
        consumers = set(string_list(value.get("consumers"), f"{label}.consumers"))
        if not consumers.issubset(protocol_consumers):
            unknown = sorted(consumers - protocol_consumers)
            raise CompatibilityMatrixError(
                f"{label} cites consumers outside the protocol row: {unknown}"
            )
        if value.get("reason") not in (None, ""):
            raise CompatibilityMatrixError(
                f"{label} must not mix evidenced consumers with a not-applicable reason"
            )
        return
    if status == "not_applicable":
        reason = value.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise CompatibilityMatrixError(
                f"{label} requires a non-empty not-applicable reason"
            )
        if value.get("consumers") not in (None, []):
            raise CompatibilityMatrixError(
                f"{label} must not cite consumers when not_applicable"
            )
        return
    raise CompatibilityMatrixError(
        f"{label}.status must be evidenced or not_applicable"
    )


def validate_values(
    root: Path,
    matrix: dict[str, Any],
    consumer_matrix: dict[str, Any],
) -> dict[str, Any]:
    expected_header = {
        "schema": "hepta.platform-types.compatibility-matrix.v1",
        "schemaVersion": 1,
        "module": "platform.types",
        "normativeCatalog": "codex-rs/hepta-types/src/protocol_catalog_v2.rs",
        "consumerMatrix": CONSUMER_RELATIVE,
    }
    for key, expected in expected_header.items():
        if matrix.get(key) != expected:
            raise CompatibilityMatrixError(
                f"compatibility matrix {key} mismatch: expected {expected!r}"
            )

    claim = matrix.get("claimBoundary")
    if not isinstance(claim, str) or "not activation" not in claim:
        raise CompatibilityMatrixError(
            "compatibility matrix needs a non-activation claim boundary"
        )

    catalog_path = repo_file(root, matrix["normativeCatalog"], "normativeCatalog")
    consumer_path = repo_file(root, matrix["consumerMatrix"], "consumerMatrix")
    if read_object(consumer_path) != consumer_matrix:
        raise CompatibilityMatrixError(
            "provided consumer matrix does not match the declared consumerMatrix path"
        )

    consumers = validate_consumer_matrix(root, consumer_matrix)
    consumer_ids = set(consumers)
    mandatory = string_list(matrix.get("mandatoryConsumers"), "mandatoryConsumers")
    optional = string_list(
        matrix.get("optionalConsumers"),
        "optionalConsumers",
        allow_empty=True,
    )
    mandatory_set = set(mandatory)
    optional_set = set(optional)
    if mandatory_set & optional_set:
        raise CompatibilityMatrixError(
            "mandatoryConsumers and optionalConsumers must be disjoint"
        )
    if mandatory_set | optional_set != consumer_ids:
        missing = sorted(consumer_ids - mandatory_set - optional_set)
        unknown = sorted((mandatory_set | optional_set) - consumer_ids)
        raise CompatibilityMatrixError(
            f"consumer classification mismatch; missing={missing}, unknown={unknown}"
        )

    required_assurances = string_list(
        matrix.get("requiredAssurances"),
        "requiredAssurances",
    )
    if tuple(required_assurances) != EXPECTED_ASSURANCES:
        raise CompatibilityMatrixError(
            "requiredAssurances must use the complete stable assurance order"
        )

    protocols = matrix.get("protocols")
    if not isinstance(protocols, list) or not protocols:
        raise CompatibilityMatrixError("compatibility matrix needs protocol rows")

    source_corpus = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((root / "codex-rs/hepta-types/src").rglob("*.rs"))
    )
    protocol_ids: set[str] = set()
    semantic_ids: set[str] = set()
    covered_consumers: set[str] = set()

    for index, row in enumerate(protocols):
        label = f"protocol[{index}]"
        if not isinstance(row, dict):
            raise CompatibilityMatrixError(f"{label} must be an object")
        protocol_id = nonempty_text(row, "id", label)
        if protocol_id in protocol_ids:
            raise CompatibilityMatrixError(f"duplicate protocol id: {protocol_id}")
        protocol_ids.add(protocol_id)
        if protocol_id not in source_corpus:
            raise CompatibilityMatrixError(
                f"protocol id has no platform.types source symbol: {protocol_id}"
            )

        semantic_id = nonempty_text(row, "semanticTypeId", label)
        if semantic_id in semantic_ids:
            raise CompatibilityMatrixError(
                f"duplicate semanticTypeId: {semantic_id}"
            )
        semantic_ids.add(semantic_id)

        for version_key in ("wireVersion", "semanticVersion"):
            version = row.get(version_key)
            if not isinstance(version, int) or isinstance(version, bool) or version < 1:
                raise CompatibilityMatrixError(
                    f"{label}.{version_key} must be a positive integer"
                )

        for text_key in (
            "codecOwner",
            "compatibility",
            "migration",
            "rollbackStrategy",
        ):
            nonempty_text(row, text_key, label)

        protocol_consumers = set(
            string_list(row.get("consumers"), f"{label}.consumers")
        )
        unknown_consumers = protocol_consumers - consumer_ids
        if unknown_consumers:
            raise CompatibilityMatrixError(
                f"{protocol_id} cites unknown consumers: {sorted(unknown_consumers)}"
            )
        covered_consumers.update(protocol_consumers)

        vectors = string_list(row.get("goldenVectors"), f"{label}.goldenVectors")
        for vector in vectors:
            repo_file(root, vector, f"{protocol_id}.goldenVectors")

        assurances = row.get("assurances")
        if not isinstance(assurances, dict):
            raise CompatibilityMatrixError(
                f"{protocol_id}.assurances must be an object"
            )
        if set(assurances) != set(EXPECTED_ASSURANCES):
            missing = sorted(set(EXPECTED_ASSURANCES) - set(assurances))
            extra = sorted(set(assurances) - set(EXPECTED_ASSURANCES))
            raise CompatibilityMatrixError(
                f"{protocol_id} assurance set mismatch; missing={missing}, extra={extra}"
            )
        for assurance_name in EXPECTED_ASSURANCES:
            validate_assurance(
                protocol_id,
                assurance_name,
                assurances[assurance_name],
                protocol_consumers,
            )

    uncovered = sorted(mandatory_set - covered_consumers)
    if uncovered:
        raise CompatibilityMatrixError(
            "mandatory consumers not bound to a protocol row: " + ", ".join(uncovered)
        )

    if not catalog_path.read_text(encoding="utf-8").strip():
        raise CompatibilityMatrixError("normative protocol catalog is empty")
    return matrix


def validate(root: Path = ROOT) -> dict[str, Any]:
    matrix_path = root / MATRIX_RELATIVE
    consumer_path = root / CONSUMER_RELATIVE
    matrix = read_object(matrix_path)
    consumer_matrix = read_object(consumer_path)
    canonical = json.dumps(matrix, indent=2, ensure_ascii=False) + "\n"
    try:
        observed = matrix_path.read_text(encoding="utf-8")
    except OSError as error:
        raise CompatibilityMatrixError(
            f"cannot read compatibility matrix bytes: {error}"
        ) from error
    if observed != canonical:
        raise CompatibilityMatrixError(
            "compatibility matrix is not canonical JSON (indent=2, UTF-8, final newline)"
        )
    return validate_values(root, matrix, consumer_matrix)


def main() -> int:
    try:
        matrix = validate()
    except CompatibilityMatrixError as error:
        print(f"platform.types compatibility matrix failed: {error}", file=sys.stderr)
        return 1
    print(
        "platform.types compatibility matrix: ok "
        f"({len(matrix['protocols'])} protocols, "
        f"{len(matrix['mandatoryConsumers'])} mandatory consumers)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
