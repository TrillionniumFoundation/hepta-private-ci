#!/usr/bin/env python3
"""Trusted workflow_run bridge for learning.eval PR evidence markers.

This script must be executed from the repository default branch. Evidence from a
candidate workflow is untrusted data: it is never imported or executed. The
bridge accepts exactly one bounded JSON summary, validates its canonical digest
and claim scope, binds it to the producer run and current PR head, then updates
only the machine-owned marker block.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
from types import ModuleType
from typing import Any
import urllib.error

SCRIPT_DIR = Path(__file__).resolve().parent
SHA1 = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
POSITIVE_INTEGER = re.compile(r"[1-9][0-9]*\Z")
MAX_SUMMARY_BYTES = 1024 * 1024
SUMMARY_NAMES = {
    "source": "qualification-summary.json",
    "exact": "exact-summary.json",
}
JOB_RESULTS = {"success", "failure", "cancelled", "skipped"}
MATRIX_RESULTS = JOB_RESULTS


def load_module(name: str, filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load trusted reporter dependency: {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


AGGREGATE = load_module("hepta_learning_eval_aggregate", "hepta-learning-eval-aggregate.py")
EXACT = load_module("hepta_learning_eval_exact_summary", "hepta-learning-eval-exact-summary.py")
PR_STATUS = load_module("hepta_learning_eval_pr_status", "hepta-learning-eval-pr-status.py")


def positive_text(value: str, label: str) -> str:
    if POSITIVE_INTEGER.fullmatch(value) is None:
        raise ValueError(f"{label} must be a positive decimal integer")
    return value


def find_summary(root: Path, expected_name: str) -> Path:
    if expected_name not in SUMMARY_NAMES.values():
        raise ValueError("unapproved evidence summary filename")
    if root.is_symlink() or not root.is_dir():
        raise ValueError("artifact root must be a real directory")
    resolved_root = root.resolve(strict=True)
    candidates = list(root.rglob(expected_name))
    if len(candidates) != 1:
        raise ValueError(
            f"expected exactly one {expected_name}, found {len(candidates)}"
        )
    candidate = candidates[0]
    current = candidate
    while current != root:
        if current.is_symlink():
            raise ValueError("artifact summary path must not contain symlinks")
        current = current.parent
    metadata = candidate.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("artifact summary must be a regular file")
    if not 0 < metadata.st_size <= MAX_SUMMARY_BYTES:
        raise ValueError("artifact summary size is outside the allowed bound")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError("artifact summary escapes its extraction root") from error
    return candidate


def load_summary(root: Path, expected_name: str) -> dict[str, Any]:
    path = find_summary(root, expected_name)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("evidence summary must be a JSON object")
    return value


def validate_bound_summary(
    summary: dict[str, Any],
    marker: str,
    repository: str,
    run_id: str,
    run_attempt: str,
    source_sha: str,
) -> None:
    if marker not in SUMMARY_NAMES:
        raise ValueError("unapproved PR marker")
    if REPOSITORY.fullmatch(repository) is None:
        raise ValueError("invalid repository identity")
    positive_text(run_id, "run ID")
    positive_text(run_attempt, "run attempt")
    if SHA1.fullmatch(source_sha) is None:
        raise ValueError("source SHA must be a full lowercase commit SHA")

    if marker == "source":
        AGGREGATE.validate(summary)
        jobs = summary.get("jobs")
        if not isinstance(jobs, dict) or any(
            not isinstance(result, str) or result not in JOB_RESULTS
            for result in jobs.values()
        ):
            raise ValueError("source summary contains an invalid job result")
    else:
        EXACT.validate(summary)
        if summary.get("eventName") != "pull_request":
            raise ValueError("exact PR marker requires pull_request evidence")
        if summary.get("matrixResult") not in MATRIX_RESULTS:
            raise ValueError("exact summary contains an invalid matrix result")
        for field in ("baseCommit", "syntheticMergeCommit"):
            if SHA1.fullmatch(str(summary.get(field, ""))) is None:
                raise ValueError(f"exact summary has invalid {field}")

    source = summary.get("source")
    if not isinstance(source, dict):
        raise ValueError("summary source identity is missing")
    if source.get("commit") != source_sha:
        raise ValueError("summary source commit does not match producer head SHA")
    if SHA1.fullmatch(str(source.get("tree", ""))) is None:
        raise ValueError("summary source tree is not a full lowercase tree SHA")
    if SHA256.fullmatch(str(summary.get("evidenceSha256", ""))) is None:
        raise ValueError("summary evidence digest is not canonical SHA-256")

    workflow = summary.get("workflow")
    if not isinstance(workflow, dict):
        raise ValueError("summary workflow identity is missing")
    expected = {
        "repository": repository,
        "runId": run_id,
        "runAttempt": run_attempt,
    }
    for key, value in expected.items():
        if workflow.get(key) != value:
            raise ValueError(f"summary workflow {key} does not match producer run")


def update_current_pull_request(
    summary: dict[str, Any],
    marker: str,
    repository: str,
    pull_request: int,
    source_sha: str,
    token: str,
    *,
    dry_run: bool = False,
) -> str:
    if pull_request < 1:
        raise ValueError("pull request number must be positive")
    if not token and not dry_run:
        raise ValueError("missing GitHub token")
    url = f"https://api.github.com/repos/{repository}/pulls/{pull_request}"
    current = PR_STATUS.request_json(url, token or "dry-run-token")
    if current.get("state") != "open":
        raise ValueError("refusing to update a non-open pull request")
    head = current.get("head")
    if not isinstance(head, dict) or head.get("sha") != source_sha:
        raise ValueError("producer run is stale relative to the current PR head")
    head_repo = head.get("repo")
    if not isinstance(head_repo, dict) or head_repo.get("full_name") != repository:
        raise ValueError("pull request head is not owned by the reporting repository")
    body = current.get("body") or ""
    if not isinstance(body, str):
        raise ValueError("pull request body is not text")
    block = PR_STATUS.render(summary, marker)
    next_body = PR_STATUS.replace_marker(body, block, marker)
    if next_body != body and not dry_run:
        PR_STATUS.request_json(url, token, method="PATCH", payload={"body": next_body})
    return next_body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--summary-name", choices=tuple(SUMMARY_NAMES.values()), required=True)
    parser.add_argument("--marker", choices=tuple(SUMMARY_NAMES), required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--pull-request", type=int, required=True)
    parser.add_argument("--token-env", default="GITHUB_TOKEN")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        if SUMMARY_NAMES[args.marker] != args.summary_name:
            raise ValueError("summary filename does not match the selected marker")
        summary = load_summary(args.artifact_root.resolve(), args.summary_name)
        validate_bound_summary(
            summary,
            args.marker,
            args.repository,
            args.run_id,
            args.run_attempt,
            args.source_sha,
        )
        token = os.environ.get(args.token_env, "")
        body = update_current_pull_request(
            summary,
            args.marker,
            args.repository,
            args.pull_request,
            args.source_sha,
            token,
            dry_run=args.dry_run,
        )
        print(body)
        return 0
    except (
        OSError,
        ValueError,
        RuntimeError,
        json.JSONDecodeError,
        urllib.error.URLError,
    ) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
