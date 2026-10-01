#!/usr/bin/env python3
"""Generate/check the canonical control.engineering status projection."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "docs/modules/control.engineering/IMPLEMENTATION_MAP.json"
STATUS = ROOT / "docs/modules/control.engineering/STATUS.json"


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def source_projection() -> dict[str, object]:
    row = json.loads(MAP.read_text(encoding="utf-8"))
    boundary = row["claimBoundary"]
    return {
        "schema": "hepta.control-engineering-status.v1",
        "schemaVersion": 1,
        "module": "control.engineering",
        "generatedFrom": "docs/modules/control.engineering/IMPLEMENTATION_MAP.json",
        "source": {
            "sourceRootPresent": bool(row["sourceRootPresent"]),
            "mappingMode": row["mappingSourceIdentityMode"],
            "identityPolicy": row["sourceIdentityPolicy"],
            "namedProductCaller": bool(row.get("productCallers")),
        },
        "claims": {
            "productionImplementation": bool(
                boundary["productionImplementation"]
            ),
            "productExecutionProved": bool(boundary["productExecutionProved"]),
            "independentAcceptance": bool(boundary["independentAcceptance"]),
            "activation": bool(boundary["activation"]),
            "release": bool(boundary["release"]),
        },
        "requiredEvidence": {
            "pullRequestDualLane": "external_ci_artifact",
            "postMergeExactMain": "external_ci_artifact",
            "independentSemanticReview": "missing",
            "liveDistributedFence": "missing",
            "externalImmutableAudit": "missing",
            "hardwareKeyCustody": "missing",
            "targetDeployment": "missing",
            "rollbackRehearsal": "missing",
            "operatorAcceptance": "missing",
        },
        "authority": {
            "runtime": False,
            "merge": False,
            "release": False,
            "deployment": False,
        },
    }


def exact_runtime_projection(source: dict[str, object]) -> dict[str, object]:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()

    result = dict(source)
    result["exactCandidate"] = {
        "commit": git("rev-parse", "HEAD"),
        "tree": git("rev-parse", "HEAD^{tree}"),
        "parents": git("show", "-s", "--format=%P", "HEAD").split(),
    }
    result["projectionDigest"] = hashlib.sha256(canonical(result)).hexdigest()
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--runtime-output", type=Path)
    args = parser.parse_args()
    source = source_projection()
    rendered = json.dumps(source, indent=2, sort_keys=True) + "\n"
    if args.write:
        STATUS.write_text(rendered, encoding="utf-8")
    if args.check and (
        not STATUS.is_file() or STATUS.read_text(encoding="utf-8") != rendered
    ):
        raise SystemExit("control.engineering STATUS.json is stale")
    if args.runtime_output:
        args.runtime_output.parent.mkdir(parents=True, exist_ok=True)
        args.runtime_output.write_text(
            json.dumps(exact_runtime_projection(source), indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
    if not (args.write or args.check or args.runtime_output):
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
