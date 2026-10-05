#!/usr/bin/env python3
"""Project the Rust platform.types catalog into central registries and guides."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_REGISTRY = ROOT / "docs/contracts/PROTOCOL_SCHEMAS.json"
CONTRACT_REGISTRY = ROOT / "docs/contracts/CONTRACTS.json"
TECHNICAL = ROOT / "docs/modules/platform.types/TECHNICAL.md"
GLOBAL_TRUTH = ROOT / "docs/lane-a-foundation/MODULE_TRUTH_MATRIX.json"
NORMATIVE_SOURCE = "codex-rs/hepta-types/src/protocol_catalog_v2.rs"
MARKER_START = "<!-- BEGIN GENERATED PLATFORM.TYPES V2 TRUTH -->"
MARKER_END = "<!-- END GENERATED PLATFORM.TYPES V2 TRUTH -->"


class SyncError(RuntimeError):
    """The generated catalog cannot be projected safely."""


def read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SyncError(f"cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise SyncError(f"JSON object required: {path}")
    return value


def write_object(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def require_catalog(path: Path) -> dict[str, Any]:
    value = read_object(path)
    protocols = value.get("protocols")
    if (
        value.get("schema") != "hepta.platform-types.protocol-catalog.v2"
        or value.get("schemaVersion") != 2
        or value.get("normativeSource") != NORMATIVE_SOURCE
        or not isinstance(protocols, list)
        or value.get("protocolCount") != len(protocols)
        or len(protocols) < 7
    ):
        raise SyncError("generated Rust protocol catalog header mismatch")
    identifiers = [row.get("id") for row in protocols if isinstance(row, dict)]
    if len(identifiers) != len(protocols) or len(set(identifiers)) != len(identifiers):
        raise SyncError("generated Rust protocol catalog IDs are invalid")
    return value


def central_type(wire_type: str) -> str:
    if "stable_id" in wire_type:
        return "id128"
    if "digest32" in wire_type:
        return "sha256"
    if wire_type in {"positive_u64", "u64"}:
        return "u64"
    if wire_type == "bool":
        return "bool"
    if "array" in wire_type:
        return "bounded_array"
    if wire_type in {"closed_enum", "enum_token"}:
        return "enum"
    if wire_type in {"bounded_object", "numeric_conversion_receipt_v1"}:
        return "bounded_object"
    return "utf8"


def central_fields(protocol: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    fields = protocol.get("fields")
    if not isinstance(fields, list):
        raise SyncError(f"{protocol.get('id')}: fields missing")
    for field in fields:
        if not isinstance(field, dict) or not isinstance(field.get("name"), str):
            raise SyncError(f"{protocol.get('id')}: invalid field")
        wire_type = str(field.get("wireType"))
        row: dict[str, Any] = {
            "name": field["name"],
            "type": central_type(wire_type),
            "required": bool(field.get("required")),
            "nativeWireType": wire_type,
        }
        if wire_type.startswith("required_nullable_"):
            row["nullable"] = True
        maximum = field.get("maximumEncodedBytes")
        if isinstance(maximum, int):
            row["maxBytes"] = maximum
        result.append(row)
    return result


def protocol_projection(protocol: dict[str, Any]) -> dict[str, Any]:
    return {
        "normativeSource": NORMATIVE_SOURCE,
        "semanticTypeId": protocol.get("semanticTypeId"),
        "semanticEncoding": protocol.get("semanticEncoding"),
        "transportSchema": protocol.get("transportSchema"),
        "codecOwner": protocol.get("codecOwner"),
        "compatibility": protocol.get("compatibility"),
        "fields": protocol.get("fields"),
    }


def sync_protocol_registry(catalog: dict[str, Any]) -> None:
    registry = read_object(PROTOCOL_REGISTRY)
    rows = registry.get("protocols")
    if not isinstance(rows, list):
        raise SyncError("central protocol registry has no protocols")
    by_id = {
        row.get("id"): row
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    for protocol in catalog["protocols"]:
        identifier = protocol["id"]
        row = by_id.get(identifier)
        if row is None:
            row = {
                "id": identifier,
                "contractId": identifier,
                "canonicalEncoding": protocol["semanticEncoding"],
                "denyUnknownCriticalFields": True,
                "maximumEncodedBytes": 262_144,
                "digestScope": "all_versioned_semantic_fields",
                "fields": central_fields(protocol),
                "invariants": [
                    "bounded_lengths",
                    "versioned_semantic_identity",
                    "digest_before_authority_use",
                    "unknown_critical_fields_rejected",
                ],
            }
            rows.append(row)
            by_id[identifier] = row
        row["canonicalEncoding"] = protocol["semanticEncoding"]
        row["digestScope"] = (
            "legacy_candidate_id_changed_and_ordered_deltas_only"
            if identifier == "RuntimeTopologyCandidateV1"
            else "all_versioned_semantic_fields"
        )
        row["platformTypesNormativeProjection"] = protocol_projection(protocol)
        if identifier == "PromptDeliveryObservationV1":
            row["transportStatus"] = "legacy_shape_only_no_product_json_codec"
            row["compatibility"] = "frozen_v1_custom_digest_no_reinterpretation"
        elif protocol.get("transportSchema") is not None:
            row["transportStatus"] = "strict_product_codec_owned_by_platform.wire"
    registry["platformTypesNormativeSource"] = NORMATIVE_SOURCE
    registry["platformTypesProjectionPolicy"] = (
        "central rows are generated compatibility projections; the typed Rust "
        "catalog and frozen native implementations define semantic identity"
    )
    write_object(PROTOCOL_REGISTRY, registry)


def sync_contract_registry(catalog: dict[str, Any]) -> None:
    registry = read_object(CONTRACT_REGISTRY)
    rows = registry.get("contracts")
    if not isinstance(rows, list):
        raise SyncError("central contract registry has no contracts")
    by_id = {
        row.get("id"): row
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    v1 = by_id.get("PromptDeliveryObservationV1")
    if v1 is None:
        raise SyncError("PromptDeliveryObservationV1 missing from contract registry")
    v1["semanticEncoding"] = "frozen_custom_length_framed_sha256_v1"
    v1["compatibility"] = "frozen_v1_custom_digest_no_reinterpretation"
    v1["normativeSource"] = NORMATIVE_SOURCE
    if "PromptDeliveryObservationV2" not in by_id:
        v2 = copy.deepcopy(v1)
        v2["id"] = "PromptDeliveryObservationV2"
        if "contractId" in v2:
            v2["contractId"] = "PromptDeliveryObservationV2"
        v2["version"] = 2
        v2["semanticEncoding"] = "HPTC_V1_schema_2"
        v2["compatibility"] = "additive_v2_with_explicit_v1_migration_witness"
        v2["schema"] = "schemas/prompt-delivery-observation-v2.schema.json"
        v2["normativeSource"] = NORMATIVE_SOURCE
        rows.append(v2)
    registry["platformTypesNormativeSource"] = NORMATIVE_SOURCE
    write_object(CONTRACT_REGISTRY, registry)


def generated_block(catalog: dict[str, Any]) -> str:
    protocols = ", ".join(
        f"`{row['id']}` V{row['version']}" for row in catalog["protocols"]
    )
    return f"""{MARKER_START}

## Current versioned protocol truth

The normative field/version/identity source is
`{NORMATIVE_SOURCE}`. Exact-candidate JSON and Markdown projections are compiled
from that Rust catalog; this guide is explanatory and cannot override it.

Registered catalog surface: {protocols}.

`PromptDeliveryObservationV1` remains frozen under its historical custom
length-framed SHA-256 commitment and is never relabeled as HPTC.
`PromptDeliveryObservationV2` is a distinct HPTC schema-2 identity with an
explicit exact-V1-digest migration witness. Generation-sensitive numeric
admission uses private-field V2 receipts that bind registry generation/digest,
profile-definition digests, normalization-definition digest and the base
conversion receipt, and are fully recomputed by the verifier.

Strict Prompt V2 and separate historical Topology V1/current V2 JSON transport belongs to `platform.wire`,
which preserves V1 historical verification without effect admission, and rejects
raw oversize/depth, duplicate or unknown fields and non-canonical
integers before native revalidation. NDU owns random-stream manifest admission;
Runtime Supervisor owns external-system and sensor-calibration admission. All
owner receipts remain deny-only and grant no activation authority.

The exact top-level `pub use` inventory is a narrow ownership projection. Full
candidate API and semver evidence comes from normalized rustdoc JSON, while Git
provenance binds exact source, schema, owner, consumer, document, verifier and
workflow blobs to the candidate tree.

{MARKER_END}"""


def sync_technical(catalog: dict[str, Any]) -> None:
    text = TECHNICAL.read_text(encoding="utf-8")
    block = generated_block(catalog)
    if MARKER_START in text:
        start = text.index(MARKER_START)
        end = text.index(MARKER_END, start) + len(MARKER_END)
        text = text[:start] + block + text[end:]
    else:
        anchors = (
            "Documentation readiness is not source qualification, activation, "
            "operator acceptance, promotion or release.",
            "Documentation readiness is not source implementation, activation, "
            "operator acceptance, promotion or release.",
        )
        anchor = next((value for value in anchors if value in text), None)
        if anchor is None:
            raise SyncError("TECHNICAL.md insertion anchor missing")
        text = text.replace(anchor, anchor + "\n\n" + block, 1)
    old = (
        "Rust owns the semantic primitives and the five shared native contracts above; "
        "HPTC V1 owns their structured semantic commitments; "
        "`PLATFORM_TYPES_BINDINGS_V1.json` owns the intentionally smaller generated "
        "Python/JavaScript/TypeScript foundational binding surface."
    )
    replacement = (
        "Rust owns the semantic primitives and versioned native contracts. Prompt V1 "
        "retains its frozen historical custom commitment; historical Topology V1 retains "
        "legacy V3 framing and is read/audit-only. Prompt V2, Topology V2 and the "
        "three manifest families use their registered HPTC commitments. "
        "`PLATFORM_TYPES_BINDINGS_V1.json` owns the intentionally smaller generated "
        "Python/JavaScript/TypeScript foundational binding surface."
    )
    if old in text:
        text = text.replace(old, replacement, 1)
    TECHNICAL.write_text(text, encoding="utf-8")


def sync_topology_lane_projection(catalog: dict[str, Any]) -> None:
    protocols = {row["id"]: row for row in catalog["protocols"]}
    legacy = protocols["RuntimeTopologyCandidateV1"]
    current = protocols["RuntimeTopologyCandidateV2"]
    registry_path = ROOT / "docs/lane-a-foundation/PROTOCOL_REGISTRY_V1.json"
    registry = read_object(registry_path)
    row = next(
        item
        for item in registry["protocols"]
        if item["protocolId"] == "hepta.platform.types.primitives.v1"
    )
    source = "codex-rs/hepta-types/src/topology_v2.rs"
    if source not in row["source"]:
        row["source"].append(source)
    row["invariants"] = [
        item
        for item in row["invariants"]
        if not item.startswith(
            "PromptDeliveryObservationV1 and RuntimeTopologyCandidateV1"
        )
        and not item.startswith("Topology version boundary:")
    ]
    row["invariants"].append(
        f"Topology version boundary: {legacy['id']} retains {legacy['semanticTypeId']} historical read/audit only; "
        f"{current['id']} uses {current['semanticTypeId']} schema {current['version']} and requires fresh independent selection"
    )
    write_object(registry_path, registry)
    capability_path = ROOT / "docs/lane-a-foundation/CAPABILITY_EVIDENCE_MAP.json"
    capabilities = read_object(capability_path)
    rows = capabilities["entries"]
    old = next(
        item
        for item in rows
        if item["capabilityId"] == "platform.types.runtime-topology-candidate.v1"
    )
    old["summary"] = (
        "frozen legacy V3 RuntimeTopologyCandidateV1 historical verification; current effect admission always refused"
    )
    old["sourceEvidence"] = [
        item
        for item in old["sourceEvidence"]
        if item["path"] != "codex-rs/hepta-supervisor/src/module_runtime.rs"
    ]
    if not any(
        item["capabilityId"] == "platform.types.runtime-topology-candidate.v2"
        for item in rows
    ):
        new = copy.deepcopy(old)
        new["capabilityId"] = "platform.types.runtime-topology-candidate.v2"
        new["summary"] = (
            "distinct HPTC schema-2 RuntimeTopologyCandidateV2 with fresh-selection Supervisor admission; authenticated execution unqualified"
        )
        new["publicSymbols"] = [
            "RuntimeTopologyCandidateV2",
            "RuntimeTopologyDeltaV2",
            "RuntimeTopologyOperationV2",
        ]
        for group in ("sourceEvidence", "positiveTests", "negativeTests"):
            for entry in new[group]:
                entry["path"] = entry["path"].replace("/topology.rs", "/topology_v2.rs")
                entry["mustContain"] = [
                    needle.replace("CandidateV1", "CandidateV2").replace(
                        "selected_digest_cannot_hide_substituted_delta_content",
                        "selected_digest_cannot_hide_substituted_candidate_content",
                    )
                    for needle in entry["mustContain"]
                ]
        new["sourceEvidence"].append(
            {
                "path": "codex-rs/hepta-supervisor/src/module_runtime.rs",
                "mustContain": [
                    "register_selected_topology_candidate_v2",
                    "candidate.validate()?",
                    "TopologyBaselineMismatch",
                    "reject_legacy_topology_candidate",
                ],
            }
        )
        rows.insert(rows.index(old) + 1, new)
    capabilities["entryCount"] = len(rows)
    write_object(capability_path, capabilities)


def sync_global_truth() -> None:
    value = read_object(GLOBAL_TRUTH)
    rows = value.get("modules")
    if not isinstance(rows, list):
        raise SyncError("global truth matrix has no modules")
    module = next(
        (
            row
            for row in rows
            if isinstance(row, dict) and row.get("module") == "platform.types"
        ),
        None,
    )
    if module is None:
        raise SyncError("platform.types missing from global truth matrix")
    module_json = json.dumps(module)
    module_json = module_json.replace(
        "digest-bound RuntimeTopologyCandidateV1 with current supervisor admission callsite",
        "distinct RuntimeTopologyCandidateV2 with fresh-selection Supervisor admission; V1 historical read only",
    )
    module.clear()
    module.update(json.loads(module_json))
    states = module.get("states")
    if not isinstance(states, dict):
        raise SyncError("platform.types global states missing")
    states["implementation"] = (
        "native_contracts_v1_compatibility_v2_hptc_strict_wire_product_owners"
    )
    module["targetOnlyCapabilities"] = [
        "authenticated_registry_snapshot_publication_and_anti_rollback",
        "complete_historical_prompt_v1_to_v2_product_migration",
        "authenticated_topology_v2_upgrade_and_rollback_native_qualification",
        "deployed_random_stream_host_inventory_and_sensor_drivers",
        "target_host_performance_canary_operator_acceptance_and_release",
    ]
    module["normativeProtocolSource"] = NORMATIVE_SOURCE
    write_object(GLOBAL_TRUTH, value)


def sync_topology_only(catalog: dict[str, Any]) -> None:
    """Refresh only this version boundary, without importing unrelated projection drift."""
    subset = dict(catalog)
    subset["protocols"] = [
        row
        for row in catalog["protocols"]
        if row["id"] in {"RuntimeTopologyCandidateV1", "RuntimeTopologyCandidateV2"}
    ]
    subset["protocolCount"] = len(subset["protocols"])
    if subset["protocolCount"] != 2:
        raise SyncError("topology projection requires both exact Rust descriptors")
    sync_protocol_registry(subset)
    sync_topology_lane_projection(catalog)
    sync_technical(catalog)
    value = read_object(GLOBAL_TRUTH)
    module = next(
        row for row in value["modules"] if row.get("module") == "platform.types"
    )
    for key, entry in module.items():
        if isinstance(entry, list):
            module[key] = [
                item.replace(
                    "digest-bound RuntimeTopologyCandidateV1 with current supervisor admission callsite",
                    "distinct RuntimeTopologyCandidateV2 with fresh-selection Supervisor admission; V1 historical read only",
                )
                if isinstance(item, str)
                else item
                for item in entry
            ]
    gap = "authenticated_topology_v2_upgrade_and_rollback_native_qualification"
    if gap not in module["targetOnlyCapabilities"]:
        module["targetOnlyCapabilities"].append(gap)
    write_object(GLOBAL_TRUTH, value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--topology-only", action="store_true")
    args = parser.parse_args()
    catalog = require_catalog(args.catalog)
    if args.topology_only:
        sync_topology_only(catalog)
        print("platform.types topology-only generated truth synchronized")
        return 0
    sync_protocol_registry(catalog)
    sync_contract_registry(catalog)
    sync_technical(catalog)
    sync_topology_lane_projection(catalog)
    sync_global_truth()
    print(
        "platform.types generated truth synchronized: "
        f"{catalog['protocolCount']} protocol descriptors"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SyncError as error:
        raise SystemExit(
            f"platform.types generated truth sync failed: {error}"
        ) from error
