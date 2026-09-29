#!/usr/bin/env python3
"""Create a source-bound independent acceptance statement from a qualified summary."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

LANES = {f"{profile}/{lane}" for profile in ("core", "product") for lane in ("exact-head", "base-merge")}


def exact_keys(value: object, name: str) -> dict:
    if not isinstance(value, dict) or set(value) != LANES:
        raise ValueError(name + " must bind exactly four lanes")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--qualification-run", required=True)
    parser.add_argument("--qualification-attempt", required=True)
    parser.add_argument("--pull-request", type=int, required=True)
    parser.add_argument("--pull-request-author", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--acceptance-workflow-sha", required=True)
    parser.add_argument("--acceptance-run", required=True)
    parser.add_argument("--acceptance-attempt", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    raw = args.summary.read_bytes()
    summary = json.loads(raw)
    if summary.get("schema") != "hepta.prompt-registry.qualification-summary.v2":
        raise ValueError("unsupported qualification summary")
    if summary.get("sourceQualified") is not True:
        raise ValueError("source was not qualified")
    if any(summary.get(name) is not False for name in ("accepted", "productActivated", "released")):
        raise ValueError("qualification summary crossed its claim boundary")
    if summary.get("sourceSha") != args.source:
        raise ValueError("source identity mismatch")
    if str(summary.get("runId")) != args.qualification_run or str(summary.get("runAttempt")) != args.qualification_attempt:
        raise ValueError("qualification run identity mismatch")
    if args.actor.casefold() == args.pull_request_author.casefold():
        raise ValueError("implementation author cannot independently accept the candidate")
    for name in ("sourceSha", "sourceTree", "baseSha"):
        if not re.fullmatch(r"[a-f0-9]{40}", summary.get(name, "")):
            raise ValueError("invalid summary identity: " + name)
    workflow = summary.get("qualificationWorkflow")
    merge = summary.get("syntheticMerge")
    if not isinstance(workflow, dict) or not re.fullmatch(r"[a-f0-9]{40}", workflow.get("sha", "")) or not workflow.get("ref"):
        raise ValueError("invalid qualification workflow identity")
    if not isinstance(merge, dict) or any(not re.fullmatch(r"[a-f0-9]{40}", merge.get(name, "")) for name in ("sha", "tree")):
        raise ValueError("invalid synthetic merge identity")
    if not re.fullmatch(r"[a-f0-9]{64}", summary.get("dependencyLockSha256", "")):
        raise ValueError("invalid dependency lock identity")
    receipts = exact_keys(summary.get("receiptSha256"), "receipt digests")
    artifacts = exact_keys(summary.get("laneArtifactContentSha256"), "artifact digests")
    runners = exact_keys(summary.get("runnerTargets"), "runner targets")
    for collection in (receipts, artifacts):
        if any(not re.fullmatch(r"[a-f0-9]{64}", value) for value in collection.values()):
            raise ValueError("invalid lane digest")
    if not re.fullmatch(r"[a-f0-9]{40}", args.acceptance_workflow_sha):
        raise ValueError("invalid acceptance workflow SHA")

    statement = {
        "schema": "hepta.prompt-registry.independent-acceptance.v1",
        "accepted": True,
        "acceptedAt": datetime.now(timezone.utc).isoformat(),
        "acceptorId": args.actor,
        "pullRequest": args.pull_request,
        "pullRequestAuthor": args.pull_request_author,
        "sourceSha": summary["sourceSha"],
        "sourceTree": summary["sourceTree"],
        "baseSha": summary["baseSha"],
        "syntheticMerge": merge,
        "qualificationWorkflow": workflow,
        "qualificationRun": {"id": args.qualification_run, "attempt": args.qualification_attempt},
        "dependencyLockSha256": summary["dependencyLockSha256"],
        "runnerTargets": runners,
        "receiptSha256": receipts,
        "laneArtifactContentSha256": artifacts,
        "qualificationSummarySha256": hashlib.sha256(raw).hexdigest(),
        "acceptanceWorkflow": {
            "sha": args.acceptance_workflow_sha,
            "runId": args.acceptance_run,
            "runAttempt": args.acceptance_attempt,
            "protectedEnvironment": "prompt-registry-independent-acceptance",
        },
        "productActivated": False,
        "released": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(statement, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(statement, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise SystemExit(f"prompt.registry acceptance rejected: {error}") from error
