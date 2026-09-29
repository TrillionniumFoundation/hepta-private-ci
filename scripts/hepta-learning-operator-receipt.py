#!/usr/bin/env python3
"""Write immutable learning.operator qualification metadata without self-acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    parser.add_argument("--test-artifact", required=True)
    parser.add_argument(
        "--output",
        default="qualification/lane-e/learning-operator-qualification-manifest.json",
    )
    args = parser.parse_args()

    lock = ROOT / "codex-rs/Cargo.lock"
    rustc = ROOT / args.rustc_file
    test_artifact = ROOT / args.test_artifact
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "schema": "hepta.learning-operator-qualification-manifest.v1",
        "schemaVersion": 1,
        "module": "learning.operator",
        "source": {
            "sha": args.source_sha,
            "tree": args.source_tree,
            "authoritativeCandidate": True,
        },
        "currentMain": {"sha": args.main_sha},
        "workflow": {
            "path": ".github/workflows/learning-operator-remaining-convergence.yml",
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
        "syntheticMerge": {
            "sha": args.synthetic_sha,
            "tree": args.synthetic_tree,
            "parents": [args.main_sha, args.source_sha],
            "deterministicCommitMetadata": True,
        },
        "testArtifact": {
            "path": args.test_artifact,
            "sha256": sha256(test_artifact),
        },
        "independentAcceptanceIdentity": None,
        "externalGates": {
            "status": "unissued_external_gate",
            "independentScientificAcceptance": False,
            "targetHostBenchmark": False,
            "futureWindowEfficacy": False,
            "operatorAcceptance": False,
            "canary": False,
            "promotion": False,
            "release": False,
        },
        "claimBoundary": {
            "repositoryQualificationEvidence": True,
            "activation": False,
            "release": False,
        },
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
