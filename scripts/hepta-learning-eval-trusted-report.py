#!/usr/bin/env python3
"""Trusted workflow_run bridge for learning.eval PR evidence markers.

This script must be executed from the repository default branch. Evidence from a
candidate workflow is untrusted data: it is never imported or executed. The
bridge accepts exactly one bounded JSON summary, validates its canonical digest
and claim scope, verifies the actual producer run and job conclusions through
the GitHub API, requires the candidate workflow to be byte-for-byte identical to
the trusted default-branch workflow, binds source/tree/base/merge identities to
GitHub objects and the current PR, then updates only the machine-owned marker.
"""
from __future__ import annotations

import argparse
import base64
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
from urllib.parse import quote

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
SHA1 = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
POSITIVE_INTEGER = re.compile(r"[1-9][0-9]*\Z")
MAX_SUMMARY_BYTES = 1024 * 1024
SUMMARY_NAMES = {
    "source": "qualification-summary.json",
    "exact": "exact-summary.json",
}
WORKFLOWS: dict[str, dict[str, Any]] = {
    "source": {
        "name": "Hepta learning.eval convergence",
        "path": ".github/workflows/hepta-learning-eval-convergence.yml",
        "required_jobs": {
            "identityRecorder": "identity-recorder",
            "compileDefault": "compile-default",
            "compileCompatibility": "compile-compatibility",
            "consumerTests": "consumer-tests",
            "faultRecoveryTests": "fault-recovery-tests",
            "formatLint": "format-lint",
            "coverage": "coverage",
        },
        "summary_job": "immutable-qualification-summary",
        "attestation_job": "attest-source-summary",
    },
    "exact": {
        "name": "Hepta learning.eval exact trees",
        "path": ".github/workflows/hepta-learning-eval-exact.yml",
        "matrix_jobs": ("exact-head", "exact-merge"),
        "summary_job": "exact-matrix-summary",
        "attestation_job": "attest-exact-summary",
    },
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
        claims = summary.get("claims", {})
        if claims.get("sourceInventoryVerified") != (
            jobs.get("identityRecorder") == "success"
        ):
            raise ValueError("source inventory claim does not match identity job")
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


def request_json(url: str, token: str) -> dict[str, Any]:
    return PR_STATUS.request_json(url, token)


def fetch_candidate_workflow(
    repository: str, path: str, source_sha: str, token: str
) -> str:
    encoded_path = quote(path, safe="/")
    value = request_json(
        f"https://api.github.com/repos/{repository}/contents/{encoded_path}?ref={source_sha}",
        token,
    )
    if value.get("type") != "file" or value.get("encoding") != "base64":
        raise ValueError("candidate workflow content response is not a base64 file")
    encoded = value.get("content")
    if not isinstance(encoded, str):
        raise ValueError("candidate workflow content is missing")
    try:
        decoded = base64.b64decode(encoded, validate=False).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as error:
        raise ValueError("candidate workflow content is not valid UTF-8 base64") from error
    if not decoded or len(decoded.encode("utf-8")) > MAX_SUMMARY_BYTES:
        raise ValueError("candidate workflow size is outside the allowed bound")
    return decoded


def trusted_workflow_text(marker: str) -> str:
    if marker not in WORKFLOWS:
        raise ValueError("unapproved producer workflow")
    path = ROOT / WORKFLOWS[marker]["path"]
    if path.is_symlink() or not path.is_file():
        raise ValueError("trusted default-branch workflow is not a regular file")
    value = path.read_text(encoding="utf-8")
    if not value or len(value.encode("utf-8")) > MAX_SUMMARY_BYTES:
        raise ValueError("trusted workflow size is outside the allowed bound")
    return value


def validate_candidate_workflow_text(text: str, marker: str) -> None:
    if marker not in WORKFLOWS:
        raise ValueError("unapproved producer workflow")
    if "\njobs:" not in text:
        raise ValueError("candidate workflow has no jobs mapping")
    header = text.split("\njobs:", 1)[0]
    if re.search(r"(?m)^permissions:\s*$", header) is None:
        raise ValueError("candidate workflow lacks explicit top-level permissions")
    if re.search(r"(?m)^  contents:\s*read\s*$", header) is None:
        raise ValueError("candidate workflow is not explicitly contents-read-only")
    if "pull_request_target:" in text:
        raise ValueError("candidate workflow must not use pull_request_target")
    if "needs.identity-recorder.outputs.tested_sha" in text:
        raise ValueError("candidate workflow checks out a job-output-derived ref")
    if "hepta-learning-eval-pr-status.py" in text:
        raise ValueError("candidate workflow performs direct privileged PR reporting")
    for forbidden in ("secrets.", "secrets[", "secrets:", "GITHUB_TOKEN", "github.token"):
        if forbidden in text:
            raise ValueError(f"candidate workflow references forbidden credential surface: {forbidden}")

    yaml_lines = []
    for raw in text.splitlines():
        content = raw.split("#", 1)[0].rstrip()
        if content.strip():
            yaml_lines.append(content.strip())
    write_lines = []
    for line in yaml_lines:
        if re.fullmatch(r"[A-Za-z0-9_-]+:\s*write(?:-all)?", line):
            write_lines.append(line)
        elif line.startswith("permissions:") and re.search(r"\bwrite(?:-all)?\b", line):
            write_lines.append(line)
    if sorted(write_lines) != ["attestations: write", "id-token: write"]:
        raise ValueError(f"candidate workflow has an unapproved write permission: {write_lines}")

    attestation_job = WORKFLOWS[marker]["attestation_job"]
    marker_text = f"\n  {attestation_job}:"
    offset = text.find(marker_text)
    if offset < 0:
        raise ValueError("candidate workflow lacks its isolated attestation job")
    prefix, attestation = text[:offset], text[offset:]
    if "id-token: write" in prefix or "attestations: write" in prefix:
        raise ValueError("candidate execution receives attestation authority")
    if "github.event_name == 'push'" not in attestation or "github.ref == 'refs/heads/main'" not in attestation:
        raise ValueError("attestation job is not restricted to main push")
    if "actions/checkout@" in attestation or re.search(r"(?m)^\s+-?\s*run:\s*", attestation):
        raise ValueError("attestation job must not checkout or execute candidate code")
    allowed_actions = (
        "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
        "actions/attest-build-provenance@4d101475d8b20a2381f78447822ac1eab6504dd8",
    )
    for line in attestation.splitlines():
        stripped = line.strip()
        if stripped.startswith("uses:") or stripped.startswith("- uses:"):
            action = stripped.split("uses:", 1)[1].strip()
            if action not in allowed_actions:
                raise ValueError(f"attestation job uses an unapproved action: {action}")


def validate_trusted_workflow_identity(candidate: str, marker: str) -> None:
    trusted = trusted_workflow_text(marker)
    if candidate.encode("utf-8") != trusted.encode("utf-8"):
        raise ValueError(
            "candidate producer workflow differs from the trusted default-branch workflow"
        )
    validate_candidate_workflow_text(candidate, marker)


def job_conclusions(value: dict[str, Any], run_attempt: str) -> dict[str, str]:
    jobs = value.get("jobs")
    total = value.get("total_count")
    if not isinstance(jobs, list) or not isinstance(total, int) or total != len(jobs):
        raise ValueError("producer job inventory is incomplete or malformed")
    conclusions: dict[str, str] = {}
    for job in jobs:
        if not isinstance(job, dict):
            raise ValueError("producer job entry is malformed")
        name = job.get("name")
        conclusion = job.get("conclusion")
        if not isinstance(name, str) or not isinstance(conclusion, str):
            raise ValueError("producer job lacks a terminal name/conclusion")
        if name in conclusions:
            raise ValueError(f"duplicate producer job name: {name}")
        if str(job.get("run_attempt", run_attempt)) != run_attempt:
            raise ValueError(f"producer job belongs to another run attempt: {name}")
        conclusions[name] = conclusion
    return conclusions


def validate_actual_job_results(
    summary: dict[str, Any], marker: str, conclusions: dict[str, str]
) -> None:
    config = WORKFLOWS[marker]
    allowed = {config["summary_job"], config["attestation_job"]}
    if marker == "source":
        required = config["required_jobs"]
        allowed.update(required.values())
        unexpected = sorted(set(conclusions) - allowed)
        if unexpected:
            raise ValueError(f"producer run contains unapproved jobs: {unexpected}")
        for summary_key, job_name in required.items():
            actual = conclusions.get(job_name)
            expected = summary["jobs"][summary_key]
            if actual != expected:
                raise ValueError(
                    f"summary result for {summary_key} does not match actual job {job_name}: {expected} != {actual}"
                )
        qualified = bool(summary["claims"]["sourceQualifiedByThisRun"])
        if (conclusions.get(config["summary_job"]) == "success") is not qualified:
            raise ValueError("source summary job conclusion does not match qualification claim")
    else:
        matrix_jobs = set(config["matrix_jobs"])
        allowed.update(matrix_jobs)
        unexpected = sorted(set(conclusions) - allowed)
        if unexpected:
            raise ValueError(f"producer run contains unapproved jobs: {unexpected}")
        if not matrix_jobs.issubset(conclusions):
            raise ValueError("exact producer run lacks head or ordered-parent merge job")
        matrix_success = all(conclusions[name] == "success" for name in matrix_jobs)
        if (summary.get("matrixResult") == "success") is not matrix_success:
            raise ValueError("exact matrix summary does not match actual matrix jobs")
        if (conclusions.get(config["summary_job"]) == "success") is not matrix_success:
            raise ValueError("exact summary job conclusion does not match matrix result")


def validate_current_pull_request(
    current: dict[str, Any],
    repository: str,
    pull_request: int,
    source_sha: str,
) -> None:
    if current.get("number", pull_request) != pull_request:
        raise ValueError("pull request identity mismatch")
    if current.get("state") != "open":
        raise ValueError("refusing to update a non-open pull request")
    head = current.get("head")
    if not isinstance(head, dict) or head.get("sha") != source_sha:
        raise ValueError("producer run is stale relative to the current PR head")
    head_repo = head.get("repo")
    if not isinstance(head_repo, dict) or head_repo.get("full_name") != repository:
        raise ValueError("pull request head is not owned by the reporting repository")


def validate_producer_run(
    summary: dict[str, Any],
    marker: str,
    repository: str,
    run_id: str,
    run_attempt: str,
    source_sha: str,
    pull_request: int,
    token: str,
) -> None:
    config = WORKFLOWS[marker]
    run = request_json(
        f"https://api.github.com/repos/{repository}/actions/runs/{run_id}", token
    )
    expected_scalars = {
        "name": config["name"],
        "path": config["path"],
        "event": "pull_request",
        "status": "completed",
        "head_sha": source_sha,
    }
    for key, expected in expected_scalars.items():
        if run.get(key) != expected:
            raise ValueError(f"producer run {key} mismatch: {run.get(key)!r} != {expected!r}")
    if str(run.get("run_attempt")) != run_attempt:
        raise ValueError("producer run attempt mismatch")
    head_repository = run.get("head_repository")
    if not isinstance(head_repository, dict) or head_repository.get("full_name") != repository:
        raise ValueError("producer run head repository mismatch")
    pulls = run.get("pull_requests")
    if (
        not isinstance(pulls, list)
        or len(pulls) != 1
        or not isinstance(pulls[0], dict)
        or pulls[0].get("number") != pull_request
    ):
        raise ValueError("producer run is not bound to the expected single pull request")
    run_pull = pulls[0]
    run_head = run_pull.get("head")
    run_base = run_pull.get("base")
    if not isinstance(run_head, dict) or run_head.get("sha") != source_sha:
        raise ValueError("producer run pull-request head mismatch")
    if not isinstance(run_base, dict) or SHA1.fullmatch(str(run_base.get("sha", ""))) is None:
        raise ValueError("producer run pull-request base identity is missing")

    commit = request_json(
        f"https://api.github.com/repos/{repository}/git/commits/{source_sha}", token
    )
    tree = commit.get("tree")
    if not isinstance(tree, dict) or tree.get("sha") != summary["source"]["tree"]:
        raise ValueError("summary source tree does not match the GitHub commit object")

    current = request_json(
        f"https://api.github.com/repos/{repository}/pulls/{pull_request}", token
    )
    validate_current_pull_request(current, repository, pull_request, source_sha)
    current_base = current.get("base")
    if not isinstance(current_base, dict) or current_base.get("sha") != run_base.get("sha"):
        raise ValueError("producer run is stale relative to the current PR base")
    if marker == "exact":
        if summary.get("baseCommit") != current_base.get("sha"):
            raise ValueError("exact summary base commit does not match the current PR base")
        if summary.get("syntheticMergeCommit") != current.get("merge_commit_sha"):
            raise ValueError("exact summary merge commit does not match the current PR merge object")

    jobs = request_json(
        f"https://api.github.com/repos/{repository}/actions/runs/{run_id}/jobs?filter=latest&per_page=100",
        token,
    )
    conclusions = job_conclusions(jobs, run_attempt)
    validate_actual_job_results(summary, marker, conclusions)

    workflow_text = fetch_candidate_workflow(
        repository, config["path"], source_sha, token
    )
    validate_trusted_workflow_identity(workflow_text, marker)


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
    validate_current_pull_request(current, repository, pull_request, source_sha)
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
        if not token:
            raise ValueError(f"missing token environment variable: {args.token_env}")
        validate_producer_run(
            summary,
            args.marker,
            args.repository,
            args.run_id,
            args.run_attempt,
            args.source_sha,
            args.pull_request,
            token,
        )
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
