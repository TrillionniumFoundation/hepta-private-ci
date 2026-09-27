#!/usr/bin/env python3
"""Fail closed when the Rust platform.types catalog and JSON Schemas diverge."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "codex-rs/hepta-types"
CATALOG_SCHEMA = "hepta.platform-types.protocol-catalog.v2"
JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"


class SchemaCatalogError(RuntimeError):
    """A generated protocol descriptor and its executable schema diverged."""


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SchemaCatalogError(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise SchemaCatalogError(f"JSON object required: {path}")
    return value


def _transport_kind(protocol_id: str) -> str:
    first = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", protocol_id)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", first).lower()


def _unique_strings(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise SchemaCatalogError(f"{name} must be a string array")
    if len(value) != len(set(value)):
        raise SchemaCatalogError(f"{name} contains duplicates")
    return value


def _validate_closed_objects(value: Any, location: str) -> None:
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_closed_objects(item, f"{location}[{index}]")
        return
    if not isinstance(value, dict):
        return
    if value.get("type") == "object" and isinstance(value.get("properties"), dict):
        if value.get("additionalProperties") is not False:
            raise SchemaCatalogError(f"{location}: object must deny additional properties")
        properties = set(value["properties"])
        required = set(_unique_strings(value.get("required", []), f"{location}.required"))
        if not required <= properties:
            missing = sorted(required - properties)
            raise SchemaCatalogError(
                f"{location}: required names absent from properties: {missing}"
            )
    for key, item in value.items():
        _validate_closed_objects(item, f"{location}.{key}")


def _schema_path(relative: str) -> Path:
    root = SCHEMA_ROOT.resolve()
    candidate = (SCHEMA_ROOT / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise SchemaCatalogError(f"schema path escapes crate root: {relative}") from error
    if not candidate.is_file():
        raise SchemaCatalogError(f"schema file missing: {relative}")
    return candidate


def _validate_protocol(protocol: dict[str, Any]) -> dict[str, Any] | None:
    identifier = protocol.get("id")
    relative = protocol.get("transportSchema")
    fields = protocol.get("fields")
    if not isinstance(identifier, str) or not identifier:
        raise SchemaCatalogError("protocol id required")
    if relative is None:
        return None
    if not isinstance(relative, str) or not relative:
        raise SchemaCatalogError(f"{identifier}: invalid transport schema path")
    if not isinstance(fields, list) or not fields:
        raise SchemaCatalogError(f"{identifier}: descriptor fields required")

    field_names: list[str] = []
    required_fields: set[str] = set()
    for field in fields:
        if not isinstance(field, dict) or not isinstance(field.get("name"), str):
            raise SchemaCatalogError(f"{identifier}: invalid field descriptor")
        name = field["name"]
        if not name or name in field_names:
            raise SchemaCatalogError(f"{identifier}: duplicate/empty field {name!r}")
        if not isinstance(field.get("required"), bool):
            raise SchemaCatalogError(f"{identifier}.{name}: required must be boolean")
        field_names.append(name)
        if field["required"]:
            required_fields.add(name)

    path = _schema_path(relative)
    schema = _read_object(path)
    if schema.get("$schema") != JSON_SCHEMA_DIALECT:
        raise SchemaCatalogError(f"{identifier}: JSON Schema dialect mismatch")
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        raise SchemaCatalogError(f"{identifier}: top-level schema must be a closed object")
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        raise SchemaCatalogError(f"{identifier}: properties object required")

    expected_properties = {"kind", *field_names}
    actual_properties = set(properties)
    if actual_properties != expected_properties:
        raise SchemaCatalogError(
            f"{identifier}: property drift; missing={sorted(expected_properties - actual_properties)} "
            f"extra={sorted(actual_properties - expected_properties)}"
        )
    actual_required = set(
        _unique_strings(schema.get("required"), f"{identifier}.required")
    )
    expected_required = {"kind", *required_fields}
    if actual_required != expected_required:
        raise SchemaCatalogError(
            f"{identifier}: required drift; missing={sorted(expected_required - actual_required)} "
            f"extra={sorted(actual_required - expected_required)}"
        )

    expected_kind = _transport_kind(identifier)
    kind = properties.get("kind")
    if not isinstance(kind, dict) or kind.get("const") != expected_kind:
        raise SchemaCatalogError(
            f"{identifier}: kind discriminator must be {expected_kind!r}"
        )
    _validate_closed_objects(schema, identifier)
    raw = path.read_bytes()
    return {
        "protocol": identifier,
        "transportKind": expected_kind,
        "schemaPath": str(path.relative_to(ROOT)),
        "schemaSha256": hashlib.sha256(raw).hexdigest(),
        "fieldCount": len(field_names),
        "requiredFieldCount": len(required_fields),
        "status": "passed",
    }


def verify_catalog(catalog: dict[str, Any]) -> dict[str, Any]:
    protocols = catalog.get("protocols")
    if (
        catalog.get("schema") != CATALOG_SCHEMA
        or catalog.get("schemaVersion") != 2
        or catalog.get("normativeSource")
        != "codex-rs/hepta-types/src/protocol_catalog_v2.rs"
        or not isinstance(protocols, list)
        or catalog.get("protocolCount") != len(protocols)
    ):
        raise SchemaCatalogError("generated protocol catalog header mismatch")
    identifiers: set[str] = set()
    rows: list[dict[str, Any]] = []
    for protocol in protocols:
        if not isinstance(protocol, dict):
            raise SchemaCatalogError("protocol rows must be objects")
        identifier = protocol.get("id")
        if not isinstance(identifier, str) or identifier in identifiers:
            raise SchemaCatalogError(f"duplicate/invalid protocol id: {identifier!r}")
        identifiers.add(identifier)
        row = _validate_protocol(protocol)
        if row is not None:
            rows.append(row)
    if not rows:
        raise SchemaCatalogError("catalog has no executable transport schemas")
    return {
        "schema": "hepta.platform-types.schema-catalog-verification.v1",
        "schemaVersion": 1,
        "normativeSource": catalog["normativeSource"],
        "catalogProtocolCount": len(protocols),
        "executableSchemaCount": len(rows),
        "schemas": rows,
        "status": "passed",
        "claimBoundary": (
            "exact descriptor/property/required/discriminator and closed-object parity; "
            "native constructors and codec tests remain the semantic validators"
        ),
    }


def self_test() -> None:
    protocol = {
        "id": "ExampleContractV1",
        "transportSchema": "schemas/example-contract-v1.schema.json",
        "fields": [
            {"name": "value", "required": True},
            {"name": "note", "required": False},
        ],
    }
    schema = {
        "$schema": JSON_SCHEMA_DIALECT,
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "value"],
        "properties": {
            "kind": {"const": "example_contract_v1"},
            "value": {"type": "string"},
            "note": {"type": "string"},
        },
    }

    def validate_fixture(candidate: dict[str, Any]) -> None:
        fields = protocol["fields"]
        expected_properties = {"kind", *(item["name"] for item in fields)}
        actual_properties = set(candidate["properties"])
        if actual_properties != expected_properties:
            raise SchemaCatalogError("self-test property drift")
        expected_required = {
            "kind",
            *(item["name"] for item in fields if item["required"]),
        }
        if set(candidate["required"]) != expected_required:
            raise SchemaCatalogError("self-test required drift")
        if candidate["properties"]["kind"].get("const") != _transport_kind(protocol["id"]):
            raise SchemaCatalogError("self-test kind drift")
        _validate_closed_objects(candidate, "self-test")

    validate_fixture(schema)
    for mutation in (
        lambda value: value["properties"].__setitem__("extra", {"type": "string"}),
        lambda value: value["required"].remove("value"),
        lambda value: value["properties"]["kind"].__setitem__("const", "wrong"),
        lambda value: value.__setitem__("additionalProperties", True),
    ):
        invalid = deepcopy(schema)
        mutation(invalid)
        try:
            validate_fixture(invalid)
        except SchemaCatalogError:
            pass
        else:
            raise SchemaCatalogError("schema verifier self-test accepted drift")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        self_test()
        report = verify_catalog(_read_object(args.catalog))
    except SchemaCatalogError as error:
        print(f"platform.types schema catalog failed: {error}", file=sys.stderr)
        return 1
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        "platform.types schema catalog: ok "
        f"({report['executableSchemaCount']} executable schemas)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
