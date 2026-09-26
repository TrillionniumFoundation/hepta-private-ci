"""Canonical control.engineering -> learning.plasticity grammar projection.

The bridge owns no proposal registry, learning signal, evaluator, selector or
activation authority. It freezes a typed mutation grammar, derives its semantic
digest, and projects an unambiguous parameter-policy payload for the Rust
learning.plasticity boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import struct
from typing import Any, Mapping, Sequence

_SCHEMA = "hepta.control-engineering.mutation-grammar.v1"
_DOMAIN = b"hepta.control-engineering.mutation-grammar-manifest.v1\0"
_POLICY_DOMAIN = b"hepta.plasticity.parameter-mutation-policy.v1\0"
_MAX_RULES = 4096
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,254}$")
_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SURFACE_TAGS = {
    "learnable_parameter": 0,
    "authority": 1,
    "evaluator": 2,
    "deletion": 3,
    "runtime_topology": 4,
    "credential": 5,
}


class PlasticityBridgeError(ValueError):
    """Fail-closed grammar or projection validation error."""


@dataclass(frozen=True, order=True)
class MutationGrammarRuleV1:
    parameter_id: str
    layer_id: str
    surface: str
    minimum_delta_raw_q32: int
    maximum_delta_raw_q32: int

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "MutationGrammarRuleV1":
        _require_exact_keys(
            value,
            {
                "parameterId",
                "layerId",
                "surface",
                "minimumDeltaRawQ32",
                "maximumDeltaRawQ32",
            },
            "mutation rule",
        )
        parameter_id = _stable_id(value["parameterId"], "parameterId")
        layer_id = _stable_id(value["layerId"], "layerId")
        surface = value["surface"]
        if surface not in _SURFACE_TAGS:
            raise PlasticityBridgeError(f"unsupported mutation surface: {surface!r}")
        minimum = _i64(value["minimumDeltaRawQ32"], "minimumDeltaRawQ32")
        maximum = _i64(value["maximumDeltaRawQ32"], "maximumDeltaRawQ32")
        if minimum > maximum:
            raise PlasticityBridgeError(
                f"inverted mutation bounds for {parameter_id}: {minimum}>{maximum}"
            )
        return cls(parameter_id, layer_id, surface, minimum, maximum)

    def canonical_mapping(self) -> dict[str, Any]:
        return {
            "parameterId": self.parameter_id,
            "layerId": self.layer_id,
            "surface": self.surface,
            "minimumDeltaRawQ32": self.minimum_delta_raw_q32,
            "maximumDeltaRawQ32": self.maximum_delta_raw_q32,
        }


@dataclass(frozen=True)
class MutationGrammarManifestV1:
    manifest_id: str
    selected_artifact_digest: str
    window_id: str
    window_digest: str
    rules: tuple[MutationGrammarRuleV1, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "MutationGrammarManifestV1":
        allowed = {
            "schema",
            "manifestId",
            "selectedArtifactDigest",
            "window",
            "rules",
            # Golden-vector metadata is not part of semantic content.
            "semanticDigest",
            "expectedPlasticityPolicyId",
            "expectedPlasticityPolicyDigest",
        }
        unknown = set(value) - allowed
        if unknown:
            raise PlasticityBridgeError(
                f"mutation grammar contains unknown fields: {sorted(unknown)}"
            )
        if value.get("schema") != _SCHEMA:
            raise PlasticityBridgeError("mutation grammar schema mismatch")
        manifest_id = _stable_id(value.get("manifestId"), "manifestId")
        selected_artifact_digest = _digest(
            value.get("selectedArtifactDigest"), "selectedArtifactDigest"
        )
        window = value.get("window")
        if not isinstance(window, Mapping):
            raise PlasticityBridgeError("window must be an object")
        _require_exact_keys(window, {"windowId", "windowDigest"}, "window")
        window_id = _stable_id(window["windowId"], "windowId")
        window_digest = _digest(window["windowDigest"], "windowDigest")
        raw_rules = value.get("rules")
        if not isinstance(raw_rules, Sequence) or isinstance(raw_rules, (str, bytes)):
            raise PlasticityBridgeError("rules must be an array")
        if not 1 <= len(raw_rules) <= _MAX_RULES:
            raise PlasticityBridgeError(
                f"rule count must be within 1..={_MAX_RULES}"
            )
        rules = tuple(
            sorted(MutationGrammarRuleV1.from_mapping(rule) for rule in raw_rules)
        )
        parameters = [rule.parameter_id for rule in rules]
        if len(parameters) != len(set(parameters)):
            raise PlasticityBridgeError("duplicate parameterId in mutation grammar")
        return cls(
            manifest_id=manifest_id,
            selected_artifact_digest=selected_artifact_digest,
            window_id=window_id,
            window_digest=window_digest,
            rules=rules,
        )

    def canonical_mapping(self) -> dict[str, Any]:
        return {
            "schema": _SCHEMA,
            "manifestId": self.manifest_id,
            "selectedArtifactDigest": self.selected_artifact_digest,
            "window": {
                "windowId": self.window_id,
                "windowDigest": self.window_digest,
            },
            "rules": [rule.canonical_mapping() for rule in self.rules],
        }

    def semantic_bytes(self) -> bytes:
        return json.dumps(
            self.canonical_mapping(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    def semantic_digest(self) -> str:
        return hashlib.sha256(_DOMAIN + self.semantic_bytes()).hexdigest()


@dataclass(frozen=True)
class PlasticityMutationProjectionV1:
    policy_id: str
    mutation_grammar_digest: str
    selected_artifact_digest: str
    window_id: str
    window_digest: str
    rules: tuple[MutationGrammarRuleV1, ...]
    policy_digest: str

    def as_mapping(self) -> dict[str, Any]:
        return {
            "policyId": self.policy_id,
            "mutationGrammarDigest": self.mutation_grammar_digest,
            "selectedArtifactDigest": self.selected_artifact_digest,
            "window": {
                "windowId": self.window_id,
                "windowDigest": self.window_digest,
            },
            "rules": [rule.canonical_mapping() for rule in self.rules],
            "policyDigest": self.policy_digest,
        }


def load_mutation_grammar_manifest_v1(
    path: str | Path,
) -> MutationGrammarManifestV1:
    source = Path(path)
    with source.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, Mapping):
        raise PlasticityBridgeError("mutation grammar root must be an object")
    return MutationGrammarManifestV1.from_mapping(value)


def project_parameter_mutation_policy_v1(
    manifest: MutationGrammarManifestV1,
    *,
    policy_id: str,
) -> PlasticityMutationProjectionV1:
    policy_id = _stable_id(policy_id, "policyId")
    grammar_digest = manifest.semantic_digest()
    material = bytearray(_POLICY_DOMAIN)
    _push_id(material, policy_id)
    material.extend(bytes.fromhex(grammar_digest))
    material.extend(bytes.fromhex(manifest.selected_artifact_digest))
    _push_id(material, manifest.window_id)
    material.extend(bytes.fromhex(manifest.window_digest))
    material.extend(struct.pack(">I", len(manifest.rules)))
    for rule in manifest.rules:
        _push_id(material, rule.parameter_id)
        _push_id(material, rule.layer_id)
        material.append(_SURFACE_TAGS[rule.surface])
        material.extend(struct.pack(">q", rule.minimum_delta_raw_q32))
        material.extend(struct.pack(">q", rule.maximum_delta_raw_q32))
    return PlasticityMutationProjectionV1(
        policy_id=policy_id,
        mutation_grammar_digest=grammar_digest,
        selected_artifact_digest=manifest.selected_artifact_digest,
        window_id=manifest.window_id,
        window_digest=manifest.window_digest,
        rules=manifest.rules,
        policy_digest=hashlib.sha256(material).hexdigest(),
    )


def _push_id(material: bytearray, value: str) -> None:
    encoded = value.encode("utf-8")
    material.extend(struct.pack(">I", len(encoded)))
    material.extend(encoded)


def _require_exact_keys(
    value: Mapping[str, Any], expected: set[str], label: str
) -> None:
    actual = set(value)
    if actual != expected:
        raise PlasticityBridgeError(
            f"{label} fields mismatch: missing={sorted(expected-actual)} "
            f"unknown={sorted(actual-expected)}"
        )


def _stable_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or _ID_PATTERN.fullmatch(value) is None:
        raise PlasticityBridgeError(f"invalid {label}")
    return value


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or _HEX_PATTERN.fullmatch(value) is None:
        raise PlasticityBridgeError(f"invalid {label}")
    if value == "0" * 64:
        raise PlasticityBridgeError(f"zero {label}")
    return value


def _i64(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PlasticityBridgeError(f"{label} must be an integer")
    if value < -(1 << 63) or value > (1 << 63) - 1:
        raise PlasticityBridgeError(f"{label} is outside signed 64-bit range")
    return value
