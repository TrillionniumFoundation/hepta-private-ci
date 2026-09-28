#!/usr/bin/env python3
"""Build an exact-source AuthBus receipt without changing the checkout.

A receipt describes this workflow, not deployment approval. Actual GitHub job
conclusions remain authoritative. Missing, skipped, failed or cancelled inputs
cannot become a successful receipt just because an artifact was uploaded.
"""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

REQUIRED_STEPS = (
    "format", "receipt_tests", "authbus", "clippy", "latency",
    "evidence", "bao", "agentd", "clean",
)
REQUIRED_FILES = (
    "source-sha.txt", "source-tree.txt", "toolchain.txt", "format.log",
    "receipt-tests.log", "authbus-tests.log", "authbus-clippy.log",
    "owner-latency.json", "owner-peak-rss.txt", "evidence-tests.log",
    "bao-tests.log", "agentd-tests.log", "unchanged-source.log",
)
MAX_EVIDENCE_BYTES = 256 * 1024 * 1024


def sha256_file(path):
    """Hash one bounded regular artifact, rejecting symlinks and missing files."""
    if path.is_symlink() or not path.is_file():
        return None
    size = path.stat().st_size
    if size == 0 or size > MAX_EVIDENCE_BYTES:
        return None
    digest = hashlib.sha256()
    observed = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            observed += len(chunk)
            if observed > MAX_EVIDENCE_BYTES:
                return None
    if observed != size:
        return None
    return {"bytes": size, "sha256": digest.hexdigest()}


def build_receipt(source_sha, source_tree, recorded_sha, recorded_tree, steps, artifacts):
    """Pure fail-closed classification; the caller supplies observed identities."""
    blockers = []
    identity_matches = (
        re.fullmatch(r"[0-9a-f]{40}", source_sha or "") is not None
        and re.fullmatch(r"[0-9a-f]{40}", source_tree or "") is not None
        and source_sha == recorded_sha
        and source_tree == recorded_tree
    )
    if not identity_matches:
        blockers.append("source_identity_mismatch_or_missing")
    outcomes = {}
    for name in REQUIRED_STEPS:
        observed = steps.get(name, {})
        outcome = observed.get("outcome", "not_recorded")
        conclusion = observed.get("conclusion", "not_recorded")
        outcomes[name] = {"outcome": outcome, "conclusion": conclusion}
        # Check the raw outcome as well as conclusion: continue-on-error must
        # never turn a failed check into an accepted source receipt.
        if outcome != "success" or conclusion != "success":
            blockers.append("step_not_successful:" + name)
    for name in REQUIRED_FILES:
        if not artifacts.get(name):
            blockers.append("evidence_missing_or_invalid:" + name)
    return {
        "schema_version": 1,
        "scope": "AuthBus immutable macOS candidate verification",
        "source": {"sha": source_sha, "tree": source_tree},
        "recorded_source": {"sha": recorded_sha, "tree": recorded_tree},
        "identity_matches": identity_matches,
        "steps": outcomes,
        "artifacts": artifacts,
        "candidate_verified": not blockers,
        "blockers": blockers,
        "production_approval": "not assessed by this workflow",
    }


def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def read_identity(directory, name):
    path = directory / name
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 128:
        return None
    return path.read_text(encoding="utf-8").strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    args = parser.parse_args()
    root = Path(git("rev-parse", "--show-toplevel")).resolve()
    directory = args.directory.resolve(strict=True)
    if directory == root or root in directory.parents:
        parser.error("evidence must be outside the checkout")
    steps = json.loads(os.environ.get("AUTHBUS_STEPS_JSON", "{}"))
    if not isinstance(steps, dict):
        parser.error("AUTHBUS_STEPS_JSON must contain the GitHub steps object")
    artifacts = {name: sha256_file(directory / name) for name in REQUIRED_FILES}
    receipt = build_receipt(
        git("rev-parse", "HEAD"),
        git("rev-parse", "HEAD^{tree}"),
        read_identity(directory, "source-sha.txt"),
        read_identity(directory, "source-tree.txt"),
        steps,
        artifacts,
    )
    github_sha = os.environ.get("GITHUB_SHA")
    if github_sha != receipt["source"]["sha"]:
        receipt["blockers"].append("github_sha_mismatch_or_missing")
        receipt["candidate_verified"] = False
    receipt["run"] = {
        "repository": os.environ.get("GITHUB_REPOSITORY"),
        "id": os.environ.get("GITHUB_RUN_ID"),
        "attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "runner_os": os.environ.get("RUNNER_OS"),
        "runner_arch": os.environ.get("RUNNER_ARCH"),
    }
    receipt["recorded_at_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    target = directory / "verification-manifest.json"
    target.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["candidate_verified"] else 1


if __name__ == "__main__":
    sys.exit(main())
