#!/usr/bin/env python3
"""Validate the proposed lossless Neuron V3 segment manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

SCHEMA = "hepta.neuron.runtime.segment-manifest.v3"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SEGMENT_KINDS = {
    "operation_history",
    "full_receipt_payloads",
    "checkpoint_payloads",
    "failure_tombstones",
    "dispatch_history",
    "runtime_index",
    "witness_lineage",
}
CRASH_CUTS = {
    "segment_create",
    "segment_write",
    "segment_sync",
    "segment_path_identity_check",
    "manifest_temp_write",
    "manifest_temp_sync",
    "manifest_replace",
    "manifest_parent_sync",
    "manifest_readback",
    "selection_pointer_publish",
}
RETENTION_FLAGS = {
    "successHistoryRetained",
    "failureTombstonesRetained",
    "reservationHistoryRetained",
    "dispatchHistoryRetained",
    "fullReceiptBytesPreserved",
    "checkpointBytesPreserved",
    "witnessLineageRetained",
    "historicalQueriesPassed",
    "deletionNonResurrectionPassed",
}


class ManifestError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ManifestError(message)


def mapping(value: Any, name: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{name} must be an object")
    return value


def text(value: Any, name: str) -> str:
    require(isinstance(value, str) and bool(value), f"{name} must be non-empty")
    return value


def sha256(value: Any, name: str) -> str:
    value = text(value, name)
    require(HEX64.fullmatch(value) is not None, f"{name} must be lowercase sha256")
    return value


def canonical_without_digest(manifest: dict[str, Any]) -> bytes:
    value = dict(manifest)
    value.pop("manifestDigest", None)
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def expected_digest(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_without_digest(manifest)).hexdigest()


def validate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    require(manifest.get("schema") == SCHEMA, "unexpected manifest schema")
    require(manifest.get("productionActivation") is False, "manifest activated production")
    require(manifest.get("release") is False, "manifest authorized release")
    require(manifest.get("sourceFormats") == ["HPTNGS02", "HPTNGI02", "HPTNGW02"], "source format mismatch")
    require(manifest.get("targetFormats") == ["HPTNGM03", "HPTNGS03", "HPTNGI03", "HPTNGW03"], "target format mismatch")
    require(isinstance(manifest.get("generation"), int) and manifest["generation"] > 0, "invalid generation")
    predecessor = manifest.get("predecessorManifestDigest")
    require(predecessor is None or HEX64.fullmatch(predecessor) is not None, "invalid predecessor digest")

    identities = mapping(manifest.get("identities"), "identities")
    for key in (
        "subjectScopeDigest",
        "objectiveScopeDigest",
        "bodyBundleDigest",
        "modelSemanticDigest",
        "configurationDigest",
    ):
        sha256(identities.get(key), f"identities.{key}")

    segments = manifest.get("segments")
    require(isinstance(segments, list) and segments, "segments must be non-empty")
    ids: set[str] = set()
    kinds: set[str] = set()
    intervals: dict[str, list[tuple[int, int]]] = {}
    for index, raw in enumerate(segments):
        segment = mapping(raw, f"segments[{index}]")
        segment_id = text(segment.get("segmentId"), f"segments[{index}].segmentId")
        require(segment_id not in ids, "duplicate segmentId")
        ids.add(segment_id)
        kind = text(segment.get("segmentKind"), f"segments[{index}].segmentKind")
        require(kind in SEGMENT_KINDS, f"unknown segment kind {kind}")
        kinds.add(kind)
        first = segment.get("firstSequence")
        last = segment.get("lastSequence")
        require(isinstance(first, int) and first >= 0, "invalid firstSequence")
        require(isinstance(last, int) and last >= first, "invalid lastSequence")
        require(isinstance(segment.get("recordCount"), int) and segment["recordCount"] > 0, "invalid recordCount")
        require(isinstance(segment.get("logicalBytes"), int) and segment["logicalBytes"] > 0, "invalid logicalBytes")
        require(isinstance(segment.get("physicalBytes"), int) and segment["physicalBytes"] > 0, "invalid physicalBytes")
        require(segment.get("immutable") is True, "segment must be immutable")
        require(segment.get("formatVersion") == 3, "segment formatVersion must be 3")
        sha256(segment.get("contentSha256"), f"segments[{index}].contentSha256")
        intervals.setdefault(kind, []).append((first, last))
    require(kinds == SEGMENT_KINDS, "required segment kind set mismatch")
    for kind, values in intervals.items():
        values.sort()
        for previous, current in zip(values, values[1:]):
            require(previous[1] < current[0], f"overlapping {kind} segments")

    frontiers = mapping(manifest.get("frontiers"), "frontiers")
    for key in (
        "operationCount",
        "successCount",
        "failureCount",
        "reservationCount",
        "dispatchCount",
        "witnessPendingCount",
    ):
        require(isinstance(frontiers.get(key), int) and frontiers[key] >= 0, f"invalid frontiers.{key}")
    require(
        frontiers["successCount"] + frontiers["failureCount"] <= frontiers["operationCount"],
        "terminal counts exceed operation count",
    )
    sha256(frontiers.get("checkpointAnchorDigest"), "frontiers.checkpointAnchorDigest")
    sha256(frontiers.get("witnessFrontierDigest"), "frontiers.witnessFrontierDigest")

    retention = mapping(manifest.get("retention"), "retention")
    require(set(retention) == RETENTION_FLAGS, "retention flag set mismatch")
    for flag in RETENTION_FLAGS:
        require(retention.get(flag) is True, f"retention.{flag} did not pass")

    migration = mapping(manifest.get("migration"), "migration")
    for key in (
        "sourceGenerationStoreSha256",
        "sourceRuntimeIndexSha256",
        "sourceWitnessSha256",
        "migrationBinarySha256",
        "sourceBinarySha256",
    ):
        sha256(migration.get(key), f"migration.{key}")
    require(migration.get("sourceV2ReadOnly") is True, "V2 source was not retained read-only")
    require(migration.get("deterministicReplayPassed") is True, "deterministic replay did not pass")
    require(migration.get("historicalQueryParityPassed") is True, "historical query parity did not pass")
    cuts = mapping(migration.get("crashCuts"), "migration.crashCuts")
    require(set(cuts) == CRASH_CUTS, "crash cut set mismatch")
    for cut in CRASH_CUTS:
        result = mapping(cuts[cut], f"migration.crashCuts.{cut}")
        require(result.get("status") == "passed", f"crash cut {cut} did not pass")
        sha256(result.get("logSha256"), f"migration.crashCuts.{cut}.logSha256")

    manifest_digest = sha256(manifest.get("manifestDigest"), "manifestDigest")
    require(manifest_digest == expected_digest(manifest), "manifest digest mismatch")

    return {
        "schema": "hepta.neuron.runtime.segment-manifest-validation.v1",
        "generation": manifest["generation"],
        "manifestDigest": manifest_digest,
        "segmentCount": len(segments),
        "segmentKinds": sorted(kinds),
        "operationCount": frontiers["operationCount"],
        "migrationQualified": True,
        "productionActivation": False,
        "release": False,
    }


def command_validate(args: argparse.Namespace) -> None:
    source = Path(args.manifest)
    value = json.loads(source.read_text(encoding="utf-8"))
    mapping(value, "manifest")
    result = validate_manifest(value)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    subcommands = result.add_subparsers(dest="command", required=True)
    validate = subcommands.add_parser("validate")
    validate.add_argument("--manifest", required=True)
    validate.add_argument("--output", required=True)
    validate.set_defaults(handler=command_validate)
    return result


def main() -> None:
    args = parser().parse_args()
    try:
        args.handler(args)
    except (ManifestError, json.JSONDecodeError, OSError) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
