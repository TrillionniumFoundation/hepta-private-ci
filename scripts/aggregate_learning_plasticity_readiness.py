#!/usr/bin/env python3
"""Aggregate learning.plasticity lanes from one workflow run into one readiness fact."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--event", required=True, choices=("pull_request", "push", "workflow_dispatch"))
    parser.add_argument("--source", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--workflow-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--github-merge-sha", default="")
    args = parser.parse_args()

    receipts: list[dict[str, Any]] = []
    receipt_files = sorted(args.input.rglob("execution.json"))
    errors: list[str] = []
    for path in receipt_files:
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except Exception as error:
            errors.append(f"{path}: invalid receipt: {error}")
            continue
        receipts.append(row)

    required = (
        {"source-head", "synthetic-merge"}
        if args.event == "pull_request"
        else {"final-merge"}
    )
    by_lane: dict[str, dict[str, Any]] = {}
    for row in receipts:
        lane = row.get("lane")
        if lane in by_lane:
            errors.append(f"duplicate lane receipt: {lane}")
            continue
        if not isinstance(lane, str):
            errors.append("receipt without lane")
            continue
        by_lane[lane] = row
        checks = {
            "schema": row.get("schema") == "hepta.learning-plasticity-exact-execution.v3",
            "source": row.get("sourceCommit") == args.source,
            "base": row.get("baseCommit") == args.base,
            "run": str(row.get("workflowRunId")) == str(args.run_id),
            "attempt": str(row.get("runAttempt")) == str(args.run_attempt),
            "workflow": row.get("workflowSha") == args.workflow_sha,
            "passed": row.get("repositoryChecksPassed") is True,
            "unchanged": row.get("candidateUnchanged") is True,
        }
        failed = sorted(name for name, passed in checks.items() if not passed)
        if failed:
            errors.append(f"{lane}: invalid or failed fields: {', '.join(failed)}")

    missing = sorted(required.difference(by_lane))
    if missing:
        errors.append("missing required lanes: " + ", ".join(missing))
    unexpected = sorted(set(by_lane).difference(required))
    if unexpected:
        errors.append("unexpected lanes: " + ", ".join(unexpected))

    shared_fields = (
        "cargoLockSha256",
        "implementationMapSha256",
        "exactMappingOverlaySha256",
        "testInventorySha256",
        "documentationSha256",
    )
    shared: dict[str, Any] = {}
    for field in shared_fields:
        values = {row.get(field) for row in by_lane.values()}
        if len(values) != 1 or None in values:
            errors.append(f"lane receipts disagree on {field}")
        else:
            shared[field] = next(iter(values))

    artifacts = []
    for path in sorted(file for file in args.input.rglob("*") if file.is_file()):
        artifacts.append(
            {
                "path": str(path.relative_to(args.input)),
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
            }
        )

    source_receipt = by_lane.get("source-head") or by_lane.get("final-merge")
    synthetic = by_lane.get("synthetic-merge")
    merge_ready = not errors
    readiness = {
        "schema": "hepta.learning-plasticity-readiness-manifest.v1",
        "module": "learning.plasticity",
        "event": args.event,
        "source_head_sha": args.source,
        "source_tree_hash": source_receipt.get("sourceTree") if source_receipt else None,
        "base_sha": args.base,
        "deterministic_merge_sha": synthetic.get("testedCommit") if synthetic else None,
        "deterministic_merge_tree_hash": synthetic.get("testedTree") if synthetic else None,
        "github_merge_sha": args.github_merge_sha or None,
        "workflow_sha": args.workflow_sha,
        "final_merge_sha": args.source if args.event == "push" else None,
        "workflow_run_id": str(args.run_id),
        "attempt_id": str(args.run_attempt),
        "runner_images": sorted(
            {
                f"{row.get('runnerImage') or 'unknown'}@{row.get('runnerImageVersion') or 'unknown'}"
                for row in by_lane.values()
            }
        ),
        "target_triples": sorted(
            {row.get("targetTriple") for row in by_lane.values() if row.get("targetTriple")}
        ),
        "Cargo.lock_hash": shared.get("cargoLockSha256"),
        "implementation_map_hash": shared.get("implementationMapSha256"),
        "exact_mapping_overlay_hash": shared.get("exactMappingOverlaySha256"),
        "documentation_hash": shared.get("documentationSha256"),
        "test_set_hash": shared.get("testInventorySha256"),
        "artifact_hashes": artifacts,
        "required_lanes": sorted(required),
        "observed_lanes": sorted(by_lane),
        "errors": errors,
        "repositoryChecksPassed": merge_ready,
        "mergeReady": merge_ready,
        "productionQualified": False,
        "targetHostEvidence": False,
        "rollbackDomainIndependenceProved": False,
        "independentAcceptance": False,
        "operatorAcceptance": False,
        "activation": False,
        "release": False,
    }
    canonical = json.dumps(readiness, sort_keys=True, separators=(",", ":")).encode("utf-8")
    readiness["manifest_sha256"] = hashlib.sha256(canonical).hexdigest()

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "readiness.json").write_text(
        json.dumps(readiness, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    lines = [
        "# learning.plasticity exact readiness",
        "",
        f"- Source: `{readiness['source_head_sha']}`",
        f"- Base: `{readiness['base_sha']}`",
        f"- Deterministic merge: `{readiness['deterministic_merge_sha']}`",
        f"- Final merge: `{readiness['final_merge_sha']}`",
        f"- Workflow run/attempt: `{readiness['workflow_run_id']}` / `{readiness['attempt_id']}`",
        f"- Repository checks passed: `{str(readiness['repositoryChecksPassed']).lower()}`",
        f"- Merge ready: `{str(readiness['mergeReady']).lower()}`",
        "- Production qualified: `false`",
        "- Target-host evidence: `false`",
        "",
        "## Qualification errors",
        "",
        *(f"- {error}" for error in errors),
        "",
        "## Bound manifest",
        "",
        "```json",
        json.dumps(readiness, indent=2, sort_keys=True),
        "```",
        "",
    ]
    (args.output / "readiness.md").write_text("\n".join(lines), encoding="utf-8")
    return 0 if merge_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
