#!/usr/bin/env python3
"""Generate and verify secrets.heptabao documentation projections.

The manifest is the semantic source of truth. Exact candidate identities remain
external CI attestations so committed documentation never requires a hash of the
commit that contains itself.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/modules/secrets.heptabao/MODULE_MANIFEST_V1.json"
TRUTH = ROOT / "docs/lane-a-foundation/MODULE_TRUTH_MATRIX.json"
MAP = ROOT / "docs/modules/secrets.heptabao/IMPLEMENTATION_MAP.json"
CAPABILITIES = ROOT / "docs/modules/secrets.heptabao/CAPABILITY_MATRIX.json"
NONCLAIMS = ROOT / "docs/modules/secrets.heptabao/NONCLAIMS.json"
ANCHORS = ROOT / "docs/modules/secrets.heptabao/SOURCE_ANCHORS.json"


def load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=False) + "\n"


def validate(manifest: dict) -> None:
    if manifest.get("schema") != "hepta.module-manifest.v1":
        raise ValueError("unexpected module manifest schema")
    states = manifest.get("recoveryStates")
    if not isinstance(states, list) or not states:
        raise ValueError("recoveryStates must be non-empty")
    names = [row.get("state") for row in states]
    if len(names) != len(set(names)) or any(not name for name in names):
        raise ValueError("recovery state names must be unique and non-empty")
    for row in states:
        if not row.get("meaning") or not row.get("recovery"):
            raise ValueError(f"state {row.get('state')} lacks a recovery action")
    for anchor in manifest.get("sourceAnchors", []):
        path = ROOT / anchor["path"]
        text = path.read_text(encoding="utf-8")
        for needle in anchor.get("mustContain", []):
            if needle not in text:
                raise ValueError(f"missing source anchor {needle!r} in {anchor['path']}")
    provider = manifest["provider"]
    if provider["dynamicLeaseExecutionProved"] or provider["dynamicMutationGate"] != "fail_closed_blocked_provider_contract":
        raise ValueError("unqualified dynamic provider mutation must remain fail closed")


def truth_entry(m: dict) -> dict:
    d = m["documents"]
    return {
        "module": m["module"],
        "profile": m["profile"],
        "formalGuide": d["technicalGuide"],
        "formalGuideRole": "target_architecture",
        "currentSpecification": d["currentImplementation"],
        "currentSpecificationRole": "current_executable_contract",
        "implementationDetail": d["durableSaga"],
        "states": m["states"],
        "currentCapabilities": m["currentCapabilities"],
        "targetOnlyCapabilities": m["targetOnlyCapabilities"],
        "sourceAnchors": m["sourceAnchors"],
        "productCallerState": "registered_host_source_composed_not_activated",
    }


def capability_projection(m: dict) -> dict:
    return {
        "schema": "hepta.module-capability-matrix.v1",
        "module": m["module"],
        "generatedFrom": str(MANIFEST.relative_to(ROOT)),
        "states": m["states"],
        "currentCapabilities": m["currentCapabilities"],
        "targetOnlyCapabilities": m["targetOnlyCapabilities"],
        "provider": m["provider"],
        "recoveryStates": m["recoveryStates"],
    }


def nonclaim_projection(m: dict) -> dict:
    return {
        "schema": "hepta.module-nonclaims.v1",
        "module": m["module"],
        "generatedFrom": str(MANIFEST.relative_to(ROOT)),
        "nonclaims": m["nonclaims"],
        "activation": False,
        "independentAcceptance": False,
        "releaseAuthority": False,
    }


def anchor_projection(m: dict) -> dict:
    return {
        "schema": "hepta.module-source-anchors.v1",
        "module": m["module"],
        "generatedFrom": str(MANIFEST.relative_to(ROOT)),
        "operations": m["operations"],
        "sourceAnchors": m["sourceAnchors"],
    }


def implementation_projection(m: dict, existing: dict) -> dict:
    result = dict(existing)
    result.update(
        {
            "schema": "hepta.module-implementation-map.v4",
            "schemaVersion": 4,
            "module": m["module"],
            "owner": m["owner"],
            "deputy": m["deputy"],
            "technicalGuide": m["documents"]["technicalGuide"],
            "currentImplementationGuide": m["documents"]["durableSaga"],
            "productionImplementation": False,
            "productCallerState": "registered_host_source_composed_not_activated",
            "productionWriterState": "sqlite_owner_pending_json_reference_only",
            "canonicalManifest": str(MANIFEST.relative_to(ROOT)),
            "operations": [
                {
                    "operation": row["operation"],
                    "nativeSymbol": row["symbol"],
                    "sourcePath": row["path"],
                    "state": row["class"],
                    "authority": "kernel.final_use" if "consume" in row["operation"] else "none",
                    "tests": [
                        "codex-rs/hepta-bao-adapter/src/consumption_lifecycle_saga_tests.rs"
                        if "consumption" in row["operation"] or "authbus" in row["operation"]
                        else "codex-rs/hepta-bao-adapter/src/https_consumer_tests.rs"
                    ],
                    "sourcePathExists": True,
                    "designOperation": row["operation"],
                    "mappingClass": "owner_native",
                    "delegatedCallees": [],
                }
                for row in m["operations"]
            ],
            "repositoryControlledGaps": m["targetOnlyCapabilities"],
            "externalEvidenceGates": [
                "exact-candidate native qualification",
                "target-host product execution",
                "independent operator acceptance promotion and release",
            ],
            "claimBoundary": {
                "nativeSourceMappingComplete": True,
                "sourceRootPresent": True,
                "productionImplementation": False,
                "productExecutionProved": False,
                "independentAcceptance": False,
                "activation": False,
                "release": False,
                "implementedOperationMappingComplete": True,
            },
        }
    )
    return result


def projections(m: dict) -> dict[Path, object]:
    truth = load(TRUTH)
    entries = truth.get("modules", [])
    replaced = False
    for index, entry in enumerate(entries):
        if entry.get("module") == m["module"]:
            entries[index] = truth_entry(m)
            replaced = True
            break
    if not replaced:
        raise ValueError("secrets.heptabao truth-matrix entry is missing")
    existing_map = load(MAP)
    return {
        TRUTH: truth,
        MAP: implementation_projection(m, existing_map),
        CAPABILITIES: capability_projection(m),
        NONCLAIMS: nonclaim_projection(m),
        ANCHORS: anchor_projection(m),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    manifest = load(MANIFEST)
    validate(manifest)
    outputs = projections(manifest)
    failures = []
    for path, value in outputs.items():
        expected = dump(value)
        if args.write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected, encoding="utf-8")
        elif not path.is_file() or path.read_text(encoding="utf-8") != expected:
            failures.append(str(path.relative_to(ROOT)))
    if failures:
        raise SystemExit("generated projection drift: " + ", ".join(failures))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
