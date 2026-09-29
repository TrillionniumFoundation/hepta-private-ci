#!/usr/bin/env python3
"""Write source-bound learning.operator qualification metadata.

Repository evidence is aggregated without issuing independent scientific,
operator, canary, promotion, activation, or release acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def require_sha(value: str, label: str) -> None:
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ValueError(f"{label} must be a literal SHA-1 identity")


def parse_evidence(values: list[str]) -> list[tuple[str, Path]]:
    result: list[tuple[str, Path]] = []
    names: set[str] = set()
    for value in values:
        if "=" not in value:
            raise ValueError("--evidence requires NAME=PATH")
        name, raw_path = value.split("=", 1)
        if not name or name in names:
            raise ValueError(f"duplicate or empty evidence name: {name!r}")
        path = ROOT / raw_path
        if not path.is_file():
            raise ValueError(f"evidence file absent: {raw_path}")
        names.add(name)
        result.append((name, path))
    return sorted(result, key=lambda item: item[0])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--workflow-blob", required=True)
    parser.add_argument("--main-sha", required=True)
    parser.add_argument("--synthetic-sha", required=True)
    parser.add_argument("--synthetic-tree", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--rustc-file", required=True)
    parser.add_argument("--implementation-map", required=True)
    parser.add_argument("--evidence", action="append", default=[])
    parser.add_argument(
        "--output",
        default="qualification/lane-e/learning-operator-qualification-manifest.json",
    )
    args = parser.parse_args()

    for label, value in (
        ("source SHA", args.source_sha),
        ("source tree", args.source_tree),
        ("workflow blob", args.workflow_blob),
        ("main SHA", args.main_sha),
        ("synthetic SHA", args.synthetic_sha),
        ("synthetic tree", args.synthetic_tree),
    ):
        require_sha(value, label)

    lock = ROOT / "codex-rs/Cargo.lock"
    rustc = ROOT / args.rustc_file
    implementation_map = ROOT / args.implementation_map
    if not lock.is_file() or not rustc.is_file() or not implementation_map.is_file():
        raise ValueError("lock, compiler, or implementation-map evidence is absent")

    map_value = json.loads(implementation_map.read_text(encoding="utf-8"))
    if map_value.get("source") != {
        "sha": args.source_sha,
        "tree": args.source_tree,
    }:
        raise ValueError("implementation map is not bound to the source candidate")

    evidence = []
    for name, path in parse_evidence(args.evidence):
        value = json.loads(path.read_text(encoding="utf-8"))
        if (
            value.get("module") != "learning.operator"
            or value.get("sourceSha") != args.source_sha
            or value.get("sourceTree") != args.source_tree
            or value.get("status") != "pass"
        ):
            raise ValueError(f"{name}: gate receipt is not a passing source-bound result")
        evidence.append(
            {
                "name": name,
                "path": str(path.relative_to(ROOT)),
                "sha256": sha256(path),
            }
        )

    required = {
        "documentation-map",
        "exact-head",
        "lifecycle-state-space",
        "module-tests",
        "payload-replay",
        "performance-profile",
        "synthetic-merge",
        "target-build",
        "workspace-all-targets",
    }
    observed = {entry["name"] for entry in evidence}
    missing = sorted(required - observed)
    if missing:
        raise ValueError("qualification evidence is incomplete: " + ", ".join(missing))

    payload: dict[str, object] = {
        "schema": "hepta.learning-operator-qualification-manifest.v2",
        "schemaVersion": 2,
        "module": "learning.operator",
        "source": {
            "sha": args.source_sha,
            "tree": args.source_tree,
            "authoritativeCandidate": True,
        },
        "currentMain": {"sha": args.main_sha},
        "workflow": {
            "path": ".github/workflows/learning-operator-diagnostics.yml",
            "blobSha": args.workflow_blob,
        },
        "dependencyLock": {
            "path": "codex-rs/Cargo.lock",
            "sha256": sha256(lock),
        },
        "compiler": {
            "target": args.target,
            "rustcEvidencePath": args.rustc_file,
            "rustcEvidenceSha256": sha256(rustc),
        },
        "implementationMap": {
            "path": args.implementation_map,
            "sha256": sha256(implementation_map),
            "sourceSha": args.source_sha,
            "sourceTree": args.source_tree,
        },
        "syntheticMerge": {
            "sha": args.synthetic_sha,
            "tree": args.synthetic_tree,
            "parents": [args.main_sha, args.source_sha],
            "deterministicCommitMetadata": True,
        },
        "evidence": evidence,
        "independentAcceptanceIdentity": None,
        "externalGates": {
            "status": "unissued_external_gate",
            "independentScientificAcceptance": False,
            "targetHostBenchmarkAcceptance": False,
            "futureWindowEfficacy": False,
            "operatorAcceptance": False,
            "canaryAcceptance": False,
            "promotion": False,
            "activation": False,
            "release": False,
        },
        "claimBoundary": {
            "repositoryQualificationEvidence": True,
            "boundedCoordinatorImplemented": True,
            "atomicVerifiedUseImplemented": True,
            "activation": False,
            "release": False,
        },
    }
    payload["aggregateEvidenceSha256"] = hashlib.sha256(
        canonical_bytes(payload)
    ).hexdigest()

    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
