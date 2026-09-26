#!/usr/bin/env python3
"""Generate and verify the closed-world platform.types public API inventory."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LIB_PATH = ROOT / "codex-rs/hepta-types/src/lib.rs"
INVENTORY_PATH = ROOT / "docs/modules/platform.types/PUBLIC_API_INVENTORY_V1.json"
IMPLEMENTATION_MAP_PATH = ROOT / "docs/modules/platform.types/IMPLEMENTATION_MAP.json"
TRUTH_MATRIX_PATH = ROOT / "docs/lane-a-foundation/platform.types/TRUTH_MATRIX_V1.json"
CURRENT_IMPLEMENTATION_PATH = (
    ROOT / "docs/lane-a-foundation/platform.types/CURRENT_IMPLEMENTATION.md"
)
DOSSIER_PATH = ROOT / "qualification/module-execution-dossiers/detail/platform.types.md"
PUB_USE = re.compile(
    r"^pub use (?P<module>[a-z_][a-z0-9_]*)::"
    r"(?P<symbol>[A-Za-z_][A-Za-z0-9_]*);$"
)
SYMBOL_OWNERS: dict[str, tuple[str, str]] = {
    "AuthorityFlagsV1": ("identity", "raw_authority_ingress"),
    "AuthorityPosture": ("identity", "raw_authority_ingress"),
    "AuthorityPostureError": ("identity", "raw_authority_ingress"),
    "BoundedBytes": ("bounded", "bounded_values"),
    "BoundedText": ("bounded", "bounded_values"),
    "BoundedValueError": ("bounded", "bounded_values"),
    "CanonicalDigestError": ("canonical_digest", "canonical_digest_v1"),
    "CanonicalFieldV1": ("canonical_digest", "canonical_digest_v1"),
    "CanonicalMapEntryV1": ("canonical_digest", "canonical_digest_v1"),
    "CanonicalValueV1": ("canonical_digest", "canonical_digest_v1"),
    "ContractRegistryV1": ("registry", "contract_registry_v1"),
    "Digest32": ("digest", "digest32"),
    "DigestParseError": ("digest", "digest32"),
    "ExternalSystemClassV1": ("manifests", "external_system_manifest_v1"),
    "ExternalSystemManifestV1": ("manifests", "external_system_manifest_v1"),
    "FIXED_Q32_ARITHMETIC_PROFILE_V1": ("fixed", "fixed_q32"),
    "FixedQ32": ("fixed", "fixed_q32"),
    "FixedQ32Error": ("fixed", "fixed_q32"),
    "Generation": ("identity", "validate_id"),
    "IdNamespaceV1": ("identity", "validate_id"),
    "IdProfileV1": ("identity", "validate_id"),
    "IdentityError": ("identity", "validate_id"),
    "LogicalSequence": ("identity", "validate_id"),
    "MAX_CANONICAL_BYTES_V1": ("canonical_digest", "canonical_digest_v1"),
    "MAX_CANONICAL_CONTAINER_ITEMS_V1": ("canonical_digest", "canonical_digest_v1"),
    "MAX_CANONICAL_DEPTH_V1": ("canonical_digest", "canonical_digest_v1"),
    "MAX_CLOCK_DOMAIN_BYTES_V1": ("manifests", "manifest_contract_primitives_v1"),
    "MAX_CONFIDENCE_PPM_V1": ("manifests", "manifest_contract_primitives_v1"),
    "MAX_MANIFEST_ENUM_BYTES_V1": ("manifests", "manifest_contract_primitives_v1"),
    "MAX_MANIFEST_TIMESTAMP_BYTES_V1": ("manifests", "manifest_contract_primitives_v1"),
    "MAX_MANIFEST_VERSION_BYTES_V1": ("manifests", "manifest_contract_primitives_v1"),
    "MAX_OPERATING_UNIT_BYTES_V1": ("manifests", "manifest_contract_primitives_v1"),
    "MAX_PROMPT_REJECTION_REASON_BYTES_V1": ("prompt_delivery", "prompt_delivery_observation_v1"),
    "MAX_PROMPT_TOKEN_POSITIONS_V1": ("prompt_delivery", "prompt_delivery_observation_v1"),
    "MAX_REGISTRY_AGGREGATE_DEFINITION_BYTES_V1": ("registry", "contract_registry_v1"),
    "MAX_REGISTRY_DEFINITION_BYTES_V1": ("registry", "contract_registry_v1"),
    "MAX_REGISTRY_ENTRIES_V1": ("registry", "contract_registry_v1"),
    "ManifestContractErrorV1": ("manifests", "manifest_contract_primitives_v1"),
    "NUMERIC_PROFILE_DEFINITION_VERSION_V1": ("numeric_profile", "numeric_profile_definition_v1"),
    "NonAuthorizingPosture": ("identity", "raw_authority_ingress"),
    "NumericConversionError": ("numeric_profile", "numeric_profile_definition_v1"),
    "NumericConversionReceiptV1": ("numeric_conversion", "rescale_signal"),
    "NumericErrorBoundV1": ("numeric_conversion", "rescale_signal"),
    "NumericProfileDefinitionError": ("numeric_profile", "numeric_profile_definition_v1"),
    "NumericProfileDefinitionV1": ("numeric_profile", "numeric_profile_definition_v1"),
    "NumericProfileV1": ("numeric_profile", "numeric_profile_definition_v1"),
    "NumericRoundingV1": ("numeric_profile", "numeric_profile_definition_v1"),
    "NumericSignalSchemaV1": ("numeric_profile", "numeric_profile_definition_v1"),
    "NumericSignalV1": ("numeric_conversion", "rescale_signal"),
    "ProbabilityQ32": ("fixed", "fixed_q32"),
    "PromptDeliveryErrorV1": ("prompt_delivery", "prompt_delivery_observation_v1"),
    "PromptDeliveryObservationV1": ("prompt_delivery", "prompt_delivery_observation_v1"),
    "PromptDeliveryRejectReasonV1": ("prompt_delivery", "prompt_delivery_observation_v1"),
    "RandomStreamManifestV1": ("manifests", "random_stream_manifest_v1"),
    "RegisteredNumericConversionReceiptV1": ("numeric_conversion", "rescale_signal_registered"),
    "RegistryDefinitionV1": ("registry", "contract_registry_v1"),
    "RegistryError": ("registry", "contract_registry_v1"),
    "RegistryKindV1": ("registry", "contract_registry_v1"),
    "Revision": ("identity", "validate_id"),
    "RuntimeTopologyCandidateV1": ("topology", "runtime_topology_candidate_v1"),
    "RuntimeTopologyContractErrorV1": ("topology", "runtime_topology_candidate_v1"),
    "RuntimeTopologyDeltaV1": ("topology", "runtime_topology_candidate_v1"),
    "RuntimeTopologyOperationV1": ("topology", "runtime_topology_candidate_v1"),
    "SensorCalibrationManifestV1": ("manifests", "sensor_calibration_manifest_v1"),
    "SensorClassV1": ("manifests", "sensor_calibration_manifest_v1"),
    "SensorFailurePolicyV1": ("manifests", "sensor_calibration_manifest_v1"),
    "SensorOperatingRangeV1": ("manifests", "sensor_calibration_manifest_v1"),
    "SensorUncertaintyProfileV1": ("manifests", "sensor_calibration_manifest_v1"),
    "SignalUnitV1": ("numeric_profile", "numeric_profile_definition_v1"),
    "StableId": ("identity", "validate_id"),
    "UncertaintyDistributionV1": ("manifests", "sensor_calibration_manifest_v1"),
    "UtcTimestampV1": ("manifests", "external_system_manifest_v1"),
    "canonical_digest_v1": ("canonical_digest", "canonical_digest_v1"),
    "canonical_encode_v1": ("canonical_digest", "canonical_digest_v1"),
    "canonical_validate_v1": ("canonical_digest", "canonical_validate_v1"),
    "rescale_signal": ("numeric_conversion", "rescale_signal"),
    "rescale_signal_registered": ("numeric_conversion", "rescale_signal_registered"),
    "validate_id": ("identity", "validate_id"),
}
INVENTORY_RELATIVE = "docs/modules/platform.types/PUBLIC_API_INVENTORY_V1.json"
TRUTH_MATRIX_RELATIVE = "docs/lane-a-foundation/platform.types/TRUTH_MATRIX_V1.json"
COVERAGE_POLICY = "closed_world_exact_pub_use_exports"


class PublicApiInventoryError(RuntimeError):
    """The public Rust surface and its committed ownership inventory diverged."""


def _exports() -> list[dict[str, str]]:
    try:
        lines = LIB_PATH.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise PublicApiInventoryError(f"cannot read {LIB_PATH}: {error}") from error
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for line_number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line.startswith("pub use "):
            continue
        match = PUB_USE.fullmatch(line)
        if match is None:
            raise PublicApiInventoryError(
                f"unsupported public export syntax at lib.rs:{line_number}: {line}"
            )
        module = match.group("module")
        symbol = match.group("symbol")
        if symbol in seen:
            raise PublicApiInventoryError(f"duplicate public symbol: {symbol}")
        seen.add(symbol)
        owner = SYMBOL_OWNERS.get(symbol)
        if owner is None:
            raise PublicApiInventoryError(
                f"unregistered public symbol {symbol} from {module}; "
                "assign an explicit operation owner before exporting it"
            )
        expected_module, operation = owner
        if module != expected_module:
            raise PublicApiInventoryError(
                f"{symbol} moved from {expected_module} to {module} without "
                "an inventory ownership update"
            )
        rows.append(
            {
                "symbol": symbol,
                "sourceModule": module,
                "sourcePath": f"codex-rs/hepta-types/src/{module}.rs",
                "operation": operation,
            }
        )
    orphaned = sorted(set(SYMBOL_OWNERS) - seen)
    if orphaned:
        raise PublicApiInventoryError(
            "registered public symbols no longer exported: " + ", ".join(orphaned)
        )
    if not rows:
        raise PublicApiInventoryError("no public exports found")
    return rows


def expected_inventory() -> dict[str, Any]:
    exports = _exports()
    module_order: list[str] = []
    for row in exports:
        if row["sourceModule"] not in module_order:
            module_order.append(row["sourceModule"])
    modules = []
    for module in module_order:
        owned = [row for row in exports if row["sourceModule"] == module]
        modules.append(
            {
                "sourceModule": module,
                "sourcePath": f"codex-rs/hepta-types/src/{module}.rs",
                "exportCount": len(owned),
                "exports": {
                    row["symbol"]: row["operation"]
                    for row in owned
                },
            }
        )
    return {
        "schema": "hepta.platform-types.public-api-inventory.v1",
        "schemaVersion": 1,
        "module": "platform.types",
        "generatedFrom": "codex-rs/hepta-types/src/lib.rs",
        "generationCommand": "python3 scripts/platform_types_public_api.py --write",
        "coveragePolicy": COVERAGE_POLICY,
        "provenancePolicy": (
            "committed inventory is content-derived; exact candidate SHA and tree "
            "are injected into Lane A qualification artifacts"
        ),
        "exportCount": len(exports),
        "sourceModuleCount": len(modules),
        "operationCount": len({row["operation"] for row in exports}),
        "sourceModules": modules,
    }


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PublicApiInventoryError(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise PublicApiInventoryError(f"JSON object required: {path}")
    return value


def _validate_implementation_map(inventory: dict[str, Any]) -> None:
    value = _read_object(IMPLEMENTATION_MAP_PATH)
    reference = value.get("publicApiInventory")
    expected_reference = {
        "path": INVENTORY_RELATIVE,
        "coveragePolicy": COVERAGE_POLICY,
        "exportCount": inventory["exportCount"],
        "operationCount": inventory["operationCount"],
    }
    if reference != expected_reference:
        raise PublicApiInventoryError(
            "implementation map publicApiInventory reference is missing or stale"
        )
    operations = value.get("operations")
    present = {
        row.get("operation")
        for row in operations
        if isinstance(row, dict) and isinstance(row.get("operation"), str)
    } if isinstance(operations, list) else set()
    required = {
        operation
        for module in inventory["sourceModules"]
        for operation in module["exports"].values()
    }
    missing = sorted(required - present)
    if missing:
        raise PublicApiInventoryError(
            "implementation map is missing public API operation owners: "
            + ", ".join(missing)
        )
    claim = value.get("claimBoundary")
    if not isinstance(claim, dict) or claim.get("publicApiInventoryComplete") is not True:
        raise PublicApiInventoryError(
            "implementation map must machine-claim publicApiInventoryComplete=true"
        )


def _validate_truth_matrix(inventory: dict[str, Any]) -> None:
    value = _read_object(TRUTH_MATRIX_PATH)
    expected_header = {
        "schema": "hepta.platform-types.truth-matrix.v1",
        "schemaVersion": 1,
        "module": "platform.types",
        "publicApiInventory": INVENTORY_RELATIVE,
        "publicApiExportCount": inventory["exportCount"],
        "publicApiOperationCount": inventory["operationCount"],
    }
    for key, expected in expected_header.items():
        if value.get(key) != expected:
            raise PublicApiInventoryError(
                f"platform.types truth matrix {key} is missing or stale"
            )
    if value.get("qualificationState") not in {
        "exact_candidate_pending",
        "source_head_qualified",
        "synthetic_merge_qualified",
        "source_and_synthetic_merge_qualified",
    }:
        raise PublicApiInventoryError("invalid platform.types qualification state")
    anchors = value.get("evidenceAnchors")
    if not isinstance(anchors, list) or not anchors:
        raise PublicApiInventoryError("platform.types truth matrix needs evidence anchors")
    for path in anchors:
        if not isinstance(path, str) or not (ROOT / path).is_file():
            raise PublicApiInventoryError(f"missing truth-matrix evidence anchor: {path}")


def _validate_prose_references() -> None:
    for path in (CURRENT_IMPLEMENTATION_PATH, DOSSIER_PATH):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as error:
            raise PublicApiInventoryError(f"cannot read {path}: {error}") from error
        for needle in (
            INVENTORY_RELATIVE,
            TRUTH_MATRIX_RELATIVE,
            "strictly increasing `StableId` order",
            "JSON transport",
            "HPTC semantic commitment",
        ):
            if needle not in text:
                raise PublicApiInventoryError(
                    f"{path.relative_to(ROOT)} missing {needle!r}"
                )


def verify_repository() -> dict[str, Any]:
    expected = expected_inventory()
    actual = _read_object(INVENTORY_PATH)
    if actual != expected:
        raise PublicApiInventoryError(
            "public API inventory drift; run "
            "`python3 scripts/platform_types_public_api.py --write`"
        )
    _validate_implementation_map(expected)
    _validate_truth_matrix(expected)
    _validate_prose_references()
    return expected


def write_inventory() -> None:
    INVENTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    INVENTORY_PATH.write_text(
        json.dumps(expected_inventory(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    try:
        if args.write:
            write_inventory()
        inventory = verify_repository()
    except PublicApiInventoryError as error:
        print(f"platform.types public API verification failed: {error}", file=sys.stderr)
        return 1
    print(
        "platform.types public API inventory: "
        f"{inventory['exportCount']} exports, "
        f"{inventory['operationCount']} operation owners verified"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
