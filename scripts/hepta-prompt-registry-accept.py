#!/usr/bin/env python3
"""Produce an independent, identity-bound prompt.registry acceptance record."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def canonical_digest(value: dict) -> str:
    payload = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--acceptor", required=True)
    parser.add_argument("--acceptance-run", required=True)
    parser.add_argument("--acceptance-workflow-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = json.loads(args.summary.read_text())
    if summary.get("schema") != "hepta.prompt-registry.qualification-summary.v2":
        raise SystemExit("unsupported qualification summary")
    if summary.get("sourceQualified") is not True or summary.get("accepted") is not False:
        raise SystemExit("qualification summary is not an unaccepted four-lane pass")
    requester = summary.get("requester")
    if not requester or args.acceptor == requester:
        raise SystemExit("acceptor must be a non-requesting identity")
    digests = summary.get("laneEvidenceSha256", {})
    if set(digests) != {
        "core/exact-head", "core/base-merge", "product/exact-head", "product/base-merge"
    }:
        raise SystemExit("all four lane artifact digests are mandatory")
    record = {
        "schema": "hepta.prompt-registry.independent-acceptance.v1",
        "accepted": True,
        "independent": True,
        "acceptor": args.acceptor,
        "requester": requester,
        "acceptanceRunId": args.acceptance_run,
        "acceptanceWorkflowSha": args.acceptance_workflow_sha,
        "sourceSha": summary["sourceSha"],
        "sourceTree": summary["tested"]["exact-head"]["tree"],
        "baseSha": summary["baseSha"],
        "syntheticMergeSha": summary["tested"]["base-merge"]["sha"],
        "syntheticMergeTree": summary["tested"]["base-merge"]["tree"],
        "qualificationWorkflowBlobSha": summary["qualificationWorkflowBlobSha"],
        "cargoLockSha256": summary["cargoLockSha256"],
        "targetTriples": summary["targetTriples"],
        "runnerIdentities": summary["runnerIdentities"],
        "laneEvidenceSha256": digests,
        "qualificationRunId": summary["runId"],
        "qualificationRunAttempt": summary["runAttempt"],
    }
    record["acceptanceDigest"] = canonical_digest(record)
    args.output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(json.dumps(record, sort_keys=True))


if __name__ == "__main__":
    main()
