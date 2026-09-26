#!/usr/bin/env python3
"""Deterministic mutation/property checks for platform.types public protocols."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
import sys
from pathlib import Path
from typing import Any

from platform_types_property_support import (
    ORACLE_PATH,
    VECTOR_PATH,
    PropertyCheckError,
    delete_path,
    digest,
    expect_reject,
    leaf_paths,
    load_oracle,
    mutations,
    read_object,
    reverse_objects,
    set_path,
    sha256,
)

try:
    from platform_types_implementation_map import verify_repository as verify_map
    from platform_types_public_api import verify_repository as verify_inventory
except ImportError as error:  # pragma: no cover - executable location invariant
    raise SystemExit(f"cannot import platform.types generators: {error}") from error


def run_checks() -> dict[str, Any]:
    inventory = verify_inventory()
    generated_map = verify_map()
    oracle = load_oracle()
    vectors = read_object(VECTOR_PATH)
    valid_vectors = vectors.get("validVectors")
    invalid_vectors = vectors.get("invalidVectors")
    if not isinstance(valid_vectors, list) or not isinstance(invalid_vectors, list):
        raise PropertyCheckError("manifest conformance vectors are incomplete")

    mutation_count = 0
    missing_field_count = 0
    order_count = 0
    discriminator_rejection_count = 0
    unknown_field_count = 0
    bounded_fuzz_count = 0

    mutation_table = mutations()
    valid_by_kind: dict[str, dict[str, Any]] = {}
    for vector in valid_vectors:
        if not isinstance(vector, dict) or not isinstance(vector.get("json"), dict):
            raise PropertyCheckError("invalid valid-vector structure")
        value = vector["json"]
        kind = vector.get("kind")
        if not isinstance(kind, str) or value.get("kind") != kind:
            raise PropertyCheckError("vector kind mismatch")
        if kind not in mutation_table:
            raise PropertyCheckError(f"missing mutation table: {kind}")
        baseline = oracle.semantic_digest(value)
        if baseline != vector.get("expectedHptcSha256"):
            raise PropertyCheckError(f"golden digest mismatch: {vector.get('id')}")
        valid_by_kind[kind] = value

        if oracle.semantic_digest(reverse_objects(value)) != baseline:
            raise PropertyCheckError(f"JSON object order changed HPTC: {kind}")
        order_count += 1

        unknown = copy.deepcopy(value)
        unknown["__unknown_property_check"] = True
        expect_reject(oracle, unknown, f"{kind}: unknown top-level field")
        unknown_field_count += 1

        wrong_kind = copy.deepcopy(value)
        wrong_kind["kind"] = "unsupported_manifest_v1"
        expect_reject(oracle, wrong_kind, f"{kind}: discriminator")
        discriminator_rejection_count += 1

        for path in leaf_paths(value):
            if path == ("kind",):
                continue
            missing = copy.deepcopy(value)
            delete_path(missing, path)
            expect_reject(oracle, missing, f"{kind}: missing {'.'.join(path)}")
            missing_field_count += 1

        for path, replacement in mutation_table[kind]:
            candidate = copy.deepcopy(value)
            set_path(candidate, path, replacement)
            if oracle.semantic_digest(candidate) == baseline:
                raise PropertyCheckError(
                    f"semantic field did not change HPTC: {kind}:{'.'.join(path)}"
                )
            mutation_count += 1

    for vector in invalid_vectors:
        if not isinstance(vector, dict) or not isinstance(vector.get("json"), dict):
            raise PropertyCheckError("invalid rejection-vector structure")
        expect_reject(oracle, vector["json"], f"rejection vector {vector.get('id')}")

    rng = random.Random(0x48505443)
    kinds = sorted(valid_by_kind)
    for index in range(384):
        kind = rng.choice(kinds)
        baseline_value = valid_by_kind[kind]
        baseline_digest = oracle.semantic_digest(baseline_value)
        path, replacement = rng.choice(mutation_table[kind])
        candidate = copy.deepcopy(baseline_value)
        if isinstance(replacement, str) and len(path) == 1 and path[0].endswith("_digest"):
            replacement = digest(f"{kind}:{'.'.join(path)}:{index}")
        elif isinstance(replacement, str) and path in {
            ("manifest_id",), ("episode_id",), ("decision_id",), ("stream_id",),
            ("system_id",), ("sensor_id",),
        }:
            replacement = f"{replacement}.f{index}"
        set_path(candidate, path, replacement)
        if oracle.semantic_digest(candidate) == baseline_digest:
            raise PropertyCheckError(
                f"bounded mutation fuzz retained digest: {kind}:{'.'.join(path)}:{index}"
            )
        bounded_fuzz_count += 1

    generated_map_hash = hashlib.sha256(
        json.dumps(
            generated_map,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "schema": "hepta.platform-types.property-report.v1",
        "schemaVersion": 1,
        "module": "platform.types",
        "inventoryExportCount": inventory["exportCount"],
        "inventoryOperationCount": inventory["operationCount"],
        "generatedMapExportCount": generated_map["exportCount"],
        "generatedMapOperationCount": generated_map["operationCount"],
        "validVectorCount": len(valid_vectors),
        "invalidVectorCount": len(invalid_vectors),
        "semanticMutationCount": mutation_count,
        "missingFieldRejectionCount": missing_field_count,
        "unknownFieldRejectionCount": unknown_field_count,
        "discriminatorRejectionCount": discriminator_rejection_count,
        "jsonOrderInvarianceCount": order_count,
        "boundedMutationFuzzCount": bounded_fuzz_count,
        "manifestConformanceSha256": sha256(VECTOR_PATH),
        "manifestOracleSha256": sha256(ORACLE_PATH),
        "generatedImplementationMapSha256": generated_map_hash,
        "status": "passed",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        report = run_checks()
    except (PropertyCheckError, OSError, ValueError) as error:
        print(f"platform.types property checks failed: {error}", file=sys.stderr)
        return 1
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(
        "platform.types property checks: ok "
        f"({report['semanticMutationCount']} semantic mutations, "
        f"{report['boundedMutationFuzzCount']} bounded fuzz cases)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
