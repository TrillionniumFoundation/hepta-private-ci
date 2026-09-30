#!/usr/bin/env python3
"""Emit and verify one non-mixable learning.operator readiness fact."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_STAGES = (
    "source_identity",
    "documentation_schema",
    "default_api_surface",
    "compile",
    "unit_tests",
    "product_integration",
    "mutation",
    "coverage",
    "resource_performance",
    "static_quality",
    "deterministic_merge",
    "exact_source_receipt",
)
SHA_FIELDS = (
    "source_head_sha",
    "frozen_source_sha",
    "observation_head_sha",
    "base_sha",
    "deterministic_merge_sha",
    "github_merge_sha",
    "workflow_sha",
    "source_tree_hash",
)


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_file(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def exact_sha(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None


def canonical_digest(paths: list[Path]) -> str:
    payload = bytearray()
    for path in sorted(paths, key=lambda value: value.as_posix()):
        relative = path.relative_to(ROOT).as_posix().encode("utf-8")
        raw = path.read_bytes()
        payload.extend(len(relative).to_bytes(4, "big"))
        payload.extend(relative)
        payload.extend(len(raw).to_bytes(8, "big"))
        payload.extend(raw)
    return digest_bytes(bytes(payload))


def load_stages(directory: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for stage in REQUIRED_STAGES:
        path = directory / f"{stage}.json"
        if not path.is_file():
            result[stage] = {
                "stage": stage,
                "status": "not_run",
                "reason": "stage receipt missing",
            }
            continue
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("schema") != "hepta.learning-operator-stage.v1":
            raise ValueError(f"invalid stage schema: {stage}")
        if value.get("stage") != stage:
            raise ValueError(f"stage identity mismatch: {stage}")
        if value.get("status") not in {"passed", "failed", "not_run"}:
            raise ValueError(f"invalid stage status: {stage}")
        result[stage] = value
    return result


def artifact_hashes(evidence: Path, output: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    if not evidence.is_dir():
        return hashes
    for path in sorted(evidence.rglob("*")):
        if path.is_file() and path.resolve() != output.resolve():
            hashes[path.relative_to(ROOT).as_posix()] = digest_file(path)
    return hashes


def emit(args: argparse.Namespace) -> None:
    output = ROOT / args.output
    stage_directory = ROOT / args.stage_directory
    stages = load_stages(stage_directory)
    all_passed = all(value.get("status") == "passed" for value in stages.values())

    documents = [
        ROOT / "docs/modules/learning.operator/STATUS.json",
        ROOT / "docs/modules/learning.operator/TECHNICAL.md",
        ROOT / "docs/modules/learning.operator/ADMISSION_CONTRACT.md",
        ROOT / "docs/modules/learning.operator/SCHEMA_COMPATIBILITY.json",
        ROOT / "docs/modules/learning.operator/IMPLEMENTATION_MAP.json",
        ROOT / "qualification/module-execution-dossiers/detail/learning.operator.md",
    ]
    for path in documents:
        if not path.is_file():
            raise ValueError(f"documentation input absent: {path.relative_to(ROOT)}")

    evidence = output.parent
    payload: dict[str, Any] = {
        "schema": "hepta.learning-operator-readiness.v1",
        "schemaVersion": 1,
        "module": "learning.operator",
        "source_head_sha": args.source_head_sha,
        "frozen_source_sha": args.frozen_source_sha,
        "observation_head_sha": args.observation_head_sha,
        "base_sha": args.base_sha,
        "deterministic_merge_sha": args.deterministic_merge_sha,
        "github_merge_sha": args.github_merge_sha,
        "workflow_sha": args.workflow_sha,
        "workflow_run_id": args.workflow_run_id,
        "attempt_id": args.attempt_id,
        "runner_image": args.runner_image,
        "target_triple": args.target_triple,
        "Cargo.lock_hash": digest_file(ROOT / "codex-rs/Cargo.lock"),
        "toolchain_hash": digest_file(ROOT / args.toolchain_file),
        "test_set_hash": digest_file(ROOT / args.test_set_file),
        "implementation_map_hash": digest_file(ROOT / args.implementation_map),
        "documentation_hash": canonical_digest(documents),
        "source_tree_hash": args.source_tree_hash,
        "stage_statuses": {
            name: {
                "status": value.get("status"),
                "reason": value.get("reason", ""),
                "receipt_sha256": digest_file(stage_directory / f"{name}.json")
                if (stage_directory / f"{name}.json").is_file()
                else None,
            }
            for name, value in stages.items()
        },
        "artifact_hashes": {},
        "engineeringQualified": all_passed,
        "mergeReady": all_passed,
        "productionQualified": False,
        "externalGates": {
            "independentScientificAcceptance": False,
            "targetHostCapacityAccepted": False,
            "operatorAcceptance": False,
            "canaryAccepted": False,
            "promotionAuthorized": False,
            "activation": False,
            "release": False,
        },
    }
    for field in SHA_FIELDS:
        if not exact_sha(payload[field]):
            raise ValueError(f"{field} must be an exact 40-character SHA")
    output.parent.mkdir(parents=True, exist_ok=True)
    payload["artifact_hashes"] = artifact_hashes(evidence, output)
    payload["manifest_sha256"] = digest_bytes(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    verify_path(output)


def verify_path(path: Path) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema") != "hepta.learning-operator-readiness.v1":
        raise ValueError("readiness schema mismatch")
    if value.get("module") != "learning.operator":
        raise ValueError("readiness module mismatch")
    for field in SHA_FIELDS:
        if not exact_sha(value.get(field)):
            raise ValueError(f"readiness exact identity missing: {field}")
    stages = value.get("stage_statuses")
    if not isinstance(stages, dict) or sorted(stages) != sorted(REQUIRED_STAGES):
        raise ValueError("readiness stage set is not exact")
    all_passed = all(
        isinstance(stages[name], dict) and stages[name].get("status") == "passed"
        for name in REQUIRED_STAGES
    )
    if value.get("engineeringQualified") is not all_passed:
        raise ValueError("engineeringQualified disagrees with stage evidence")
    if value.get("mergeReady") is not all_passed:
        raise ValueError("mergeReady disagrees with stage evidence")
    if value.get("productionQualified") is not False:
        raise ValueError("repository readiness cannot self-issue production qualification")
    external = value.get("externalGates")
    if not isinstance(external, dict) or any(item is not False for item in external.values()):
        raise ValueError("external acceptance/activation gates must remain false")
    manifest_digest = value.pop("manifest_sha256", None)
    expected = digest_bytes(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    if manifest_digest != expected:
        raise ValueError("readiness manifest digest mismatch")
    value["manifest_sha256"] = manifest_digest


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action", required=True)
    write = subparsers.add_parser("emit")
    for name in (
        "source_head_sha",
        "frozen_source_sha",
        "observation_head_sha",
        "source_tree_hash",
        "base_sha",
        "deterministic_merge_sha",
        "github_merge_sha",
        "workflow_sha",
        "workflow_run_id",
        "attempt_id",
        "runner_image",
        "target_triple",
        "toolchain_file",
        "test_set_file",
        "implementation_map",
        "stage_directory",
        "output",
    ):
        write.add_argument("--" + name.replace("_", "-"), required=True)
    check = subparsers.add_parser("verify")
    check.add_argument("--path", required=True)
    args = parser.parse_args()
    if args.action == "emit":
        emit(args)
    else:
        verify_path(ROOT / args.path)


if __name__ == "__main__":
    main()
