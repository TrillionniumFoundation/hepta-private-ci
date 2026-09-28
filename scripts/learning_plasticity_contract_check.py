#!/usr/bin/env python3
"""Cross-module contract check for control.engineering -> learning.plasticity.

The check is deliberately read-only. It proves that the canonical
MutationGrammarManifestV1 registry entry has exactly one owner, declares
learning.plasticity as a consumer, and that the native projection binds the exact
non-zero grammar digest into policy, generator, coverage, and self-iteration
context digests. It does not claim wire round-trip support or runtime activation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
PROTOCOLS = ROOT / "docs/readiness/PROTOCOLS.json"
POLICY = ROOT / "codex-rs/hepta-plasticity/src/parameter_mutation_policy_v1.rs"
GENERATOR = ROOT / "codex-rs/hepta-plasticity/src/generator_v3.rs"
COVERAGE = ROOT / "codex-rs/hepta-plasticity/src/coverage_v1.rs"
COORDINATOR = ROOT / "codex-rs/hepta-agentd/src/plasticity_iteration_coordinator.rs"
IMPLEMENTATION_MAP = ROOT / "docs/modules/learning.plasticity/IMPLEMENTATION_MAP.json"


class ContractError(RuntimeError):
    pass


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_json(path: pathlib.Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read canonical JSON {path}: {exc}") from exc


def read_text(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractError(f"cannot read source {path}: {exc}") from exc


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def unique_protocol(registry: dict[str, Any], protocol_id: str) -> dict[str, Any]:
    values = [
        value
        for value in registry.get("protocols", [])
        if value.get("id") == protocol_id
    ]
    require(len(values) == 1, f"{protocol_id} must have exactly one registry entry")
    return values[0]


def validate_protocol(protocol: dict[str, Any]) -> list[str]:
    require(protocol.get("owner") == "control.engineering", "grammar owner drift")
    require(
        "learning.plasticity" in protocol.get("consumers", []),
        "learning.plasticity is not a declared grammar consumer",
    )
    require(
        protocol.get("canonicalEncoding") == "canonical_json_utf8",
        "grammar canonical encoding drift",
    )
    require(
        protocol.get("denyUnknownCriticalFields") is True,
        "grammar must reject unknown critical fields",
    )
    require(protocol.get("authorityDelta") == "none", "grammar grants authority")
    maximum = protocol.get("maximumEncodedBytes")
    require(isinstance(maximum, int) and 0 < maximum <= 262_144, "invalid grammar bound")

    fields = protocol.get("fields")
    require(isinstance(fields, list) and fields, "grammar fields are missing")
    names = [field.get("name") for field in fields]
    require(all(isinstance(name, str) and name for name in names), "invalid field name")
    require(len(names) == len(set(names)), "duplicate grammar field")
    require(
        any(
            field.get("type") == "sha256"
            and "digest" in str(field.get("name", "")).lower()
            and field.get("required") is True
            for field in fields
        ),
        "grammar has no required semantic digest field",
    )
    return names


def require_source_contract() -> dict[str, str]:
    policy = read_text(POLICY)
    generator = read_text(GENERATOR)
    coverage = read_text(COVERAGE)
    coordinator = read_text(COORDINATOR)

    required_policy_fragments = [
        "MutationGrammarManifestV1",
        "pub mutation_grammar_digest: Digest32",
        "EmptyMutationGrammar",
        "policy.mutation_grammar_digest.is_zero()",
        "bytes.extend_from_slice(policy.mutation_grammar_digest.as_array())",
        "ParameterMutationSurfaceV1::LearnableParameter",
        "ParameterMutationSurfaceV1::Authority",
        "ParameterMutationSurfaceV1::Evaluator",
        "ParameterMutationSurfaceV1::Deletion",
        "ParameterMutationSurfaceV1::RuntimeTopology",
        "ParameterMutationSurfaceV1::Credential",
    ]
    for fragment in required_policy_fragments:
        require(fragment in policy, f"policy projection missing: {fragment}")

    for fragment in [
        "verify_parameter_mutation_policy_v1(&profile.mutation_policy)?",
        "authorize_parameter_mutation_v1(",
        "profile.mutation_policy.policy_digest.as_array()",
    ]:
        require(fragment in generator, f"generator binding missing: {fragment}")

    for fragment in [
        "pub mutation_grammar_digest: Digest32",
        "profile.mutation_policy.mutation_grammar_digest",
        "receipt.mutation_grammar_digest",
        "owner_frontier_digest",
        "scale_policy_digest",
    ]:
        require(fragment in coverage, f"coverage binding missing: {fragment}")

    for fragment in [
        "context.envelope.grammar_digest != context.mutation_grammar_digest",
        "request.generator_profile.mutation_policy.mutation_grammar_digest",
        "coverage.mutation_grammar_digest != context.mutation_grammar_digest",
    ]:
        require(fragment in coordinator, f"coordinator binding missing: {fragment}")

    return {
        "parameterMutationPolicySha256": sha256_bytes(policy.encode("utf-8")),
        "parameterGeneratorSha256": sha256_bytes(generator.encode("utf-8")),
        "generatorCoverageSha256": sha256_bytes(coverage.encode("utf-8")),
        "selfIterationCoordinatorSha256": sha256_bytes(coordinator.encode("utf-8")),
    }


def validate_implementation_map() -> str:
    value = read_json(IMPLEMENTATION_MAP)
    operations = value.get("operations", [])
    matches = [
        operation
        for operation in operations
        if operation.get("operation") == "parameter_mutation_policy"
    ]
    require(len(matches) == 1, "parameter_mutation_policy map entry must be unique")
    operation = matches[0]
    require(
        operation.get("sourcePath")
        == "codex-rs/hepta-plasticity/src/parameter_mutation_policy_v1.rs",
        "parameter mutation policy map path drift",
    )
    require(operation.get("authority") == "none", "policy map grants authority")
    return sha256_bytes(canonical_json(value))


def build_receipt() -> dict[str, Any]:
    registry = read_json(PROTOCOLS)
    protocol = unique_protocol(registry, "MutationGrammarManifestV1")
    field_names = validate_protocol(protocol)
    source_digests = require_source_contract()
    map_digest = validate_implementation_map()
    return {
        "schema": "hepta.learning-plasticity-grammar-contract-check.v1",
        "protocolId": "MutationGrammarManifestV1",
        "owner": "control.engineering",
        "consumer": "learning.plasticity",
        "protocolDigest": sha256_bytes(canonical_json(protocol)),
        "protocolFieldNames": field_names,
        "implementationMapDigest": map_digest,
        "sourceDigests": source_digests,
        "authorityDelta": "none",
        "decision": "passed",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args()
    try:
        receipt = build_receipt()
    except ContractError as exc:
        print(f"learning.plasticity grammar contract check failed: {exc}", file=sys.stderr)
        return 1
    encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    sys.stdout.write(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
