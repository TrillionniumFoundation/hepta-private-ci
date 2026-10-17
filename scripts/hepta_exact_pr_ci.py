#!/usr/bin/env python3
"""Exact-HEAD PR CI truth gate and explicit manual source-lane retry.

A successful workflow_dispatch source lane is NOT a replacement for a
pull_request-triggered merge lane or for blocking-ci. Never treat older
successful runs on a different PR head/base as current evidence.
"""

import argparse
import json
import re
import subprocess
from collections.abc import Sequence
from datetime import datetime

REQUIRED = ("Hepta architecture convergence", "blocking-ci", "v8-canary")
MANUAL = ("hepta-architecture-convergence.yml", "v8-canary.yml")
SHA = re.compile(r"[0-9a-f]{40}\Z")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
# An explicit branch pin can qualify a modern fix/integration PR without
# trusting a broad branch prefix or relaxing any HEAD/base/merge SHA check.
BRANCH_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./-]*\Z")


def gh(*args: str) -> str:
    return subprocess.run(
        ["gh", *args], check=True, capture_output=True, text=True, timeout=45
    ).stdout


def gh_json(endpoint: str) -> dict:
    payload = json.loads(gh("api", endpoint))
    if not isinstance(payload, dict):
        raise ValueError("GitHub response is not a JSON object")
    return payload


def valid_branch_ref(ref: object) -> bool:
    if not isinstance(ref, str) or not BRANCH_REF.fullmatch(ref):
        return False
    if not "/" in ref or ref.endswith(("/", ".", ".lock")) or ".." in ref:
        return False
    return all(part not in ("", ".", "..") for part in ref.split("/"))


def validate_pr(
    pr: dict, repo: str, number: int, sha: str, *, expected_ref: str | None = None
) -> tuple[str, str]:
    if pr.get("number") != number or pr.get("state") != "open" or not pr.get("draft"):
        raise ValueError("expected the same open Draft pull request")
    head, base = pr.get("head", {}), pr.get("base", {})
    if (
        head.get("sha") != sha
        or head.get("repo", {}).get("full_name") != repo
        or not SHA.fullmatch(base.get("sha", ""))
        or not valid_branch_ref(head.get("ref"))
        or not (
            head["ref"] == expected_ref
            if expected_ref is not None
            else head["ref"].startswith("codex/")
        )
    ):
        raise ValueError("PR HEAD, base or repository identity differs from pin")
    return head["ref"], base["sha"]


def exact_pr_run(run: dict, repo: str, number: int, head: str, base: str) -> bool:
    if run.get("event") != "pull_request" or run.get("head_sha") != head:
        return False
    for item in run.get("pull_requests") or []:
        if (
            item.get("number") == number
            and item.get("head", {}).get("sha") == head
            and item.get("base", {}).get("sha") == base
            and item.get("head", {}).get("repo", {}).get("url")
            == f"https://api.github.com/repos/{repo}"
        ):
            return True
    return False


def parse_utc_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.utcoffset().total_seconds() == 0 else None


def prospective_merge_identity(repo: str, number: int, head: str, base: str) -> dict:
    """Check the actual GitHub-generated merge commit, not an old PR URL.

    A successful source-head workflow cannot certify a prospective base
    merge. Missing or stale refs MUST be represented as a blocking result.
    GitHub may leave refs/pull/N/merge pointing at an older candidate.
    """
    try:
        ref = gh_json(f"repos/{repo}/git/ref/pull/{number}/merge")
        merge_sha = ref.get("object", {}).get("sha", "")
        if ref.get("ref") != f"refs/pull/{number}/merge" or not SHA.fullmatch(
            merge_sha
        ):
            raise ValueError("missing or malformed prospective merge ref")
        commit = gh_json(f"repos/{repo}/git/commits/{merge_sha}")
        parents = [item.get("sha") for item in commit.get("parents", [])]
        valid = parents == [base, head]
        created_at = commit.get("committer", {}).get("date", "")
        # Pull request run parent metadata can be a mutable PR snapshot.
        # Use the immutable merge commit's creation time to prevent an old
        # successful run on the same HEAD from qualifying a newer base.
        if valid:
            timestamp = parse_utc_timestamp(created_at)
            if timestamp is None:
                raise ValueError("missing immutable merge commit timestamp")
        return {
            "status": "exact" if valid else "stale_merge_parents",
            "merge_sha": merge_sha,
            "parent_shas": parents,
            "merge_created_at": created_at,
            "qualified": valid,
        }
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError, TypeError):
        return {
            "status": "missing_or_unreadable_merge_ref",
            "qualified": False,
        }


def run_started_after_merge(run: dict, merge_created_at: str | None) -> bool:
    if merge_created_at is None:
        return True
    merge_time = parse_utc_timestamp(merge_created_at)
    run_time = parse_utc_timestamp(run.get("created_at"))
    return merge_time is not None and run_time is not None and run_time >= merge_time


def evaluate(
    pr: dict,
    runs: Sequence[dict],
    repo: str,
    number: int,
    sha: str,
    *,
    merge_created_at: str | None = None,
    expected_ref: str | None = None,
) -> dict:
    _, base = validate_pr(pr, repo, number, sha, expected_ref=expected_ref)
    statuses = {}
    for workflow in REQUIRED:
        candidates = [
            run
            for run in runs
            if run.get("name") == workflow
            and exact_pr_run(run, repo, number, sha, base)
            and run_started_after_merge(run, merge_created_at)
        ]
        # A later failed rerun may not be superseded by an older green run.
        candidates.sort(
            key=lambda run: (run.get("run_number", 0), run.get("run_attempt", 1)),
            reverse=True,
        )
        if not candidates:
            statuses[workflow] = "missing_exact_pull_request_run"
        else:
            run = candidates[0]
            statuses[workflow] = (
                run.get("conclusion") or "pending"
                if run.get("status") == "completed"
                else "pending"
            )
    return {
        "schema": "hepta.ci.exact-pr-head.v1",
        "pull_request": number,
        "head_sha": sha,
        "base_sha": base,
        "required_pull_request_runs": statuses,
        "qualified": all(value == "success" for value in statuses.values()),
    }


def current(
    repo: str, number: int, sha: str, *, expected_ref: str | None = None
) -> tuple[dict, dict]:
    pr = gh_json(f"repos/{repo}/pulls/{number}")
    validate_pr(pr, repo, number, sha, expected_ref=expected_ref)
    response = gh_json(f"repos/{repo}/actions/runs?head_sha={sha}&per_page=100")
    runs = response.get("workflow_runs")
    if not isinstance(runs, list):
        raise ValueError("GitHub Actions did not return the exact-head run list")
    merge = prospective_merge_identity(repo, number, sha, pr["base"]["sha"])
    report = evaluate(
        pr,
        runs,
        repo,
        number,
        sha,
        merge_created_at=(
            merge.get("merge_created_at") if merge["qualified"] else None
        ),
        expected_ref=expected_ref,
    )
    report["prospective_merge_ref"] = merge
    report["qualified"] = report["qualified"] and merge["qualified"]
    return pr, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="TrillionniumFoundation/hepta-private-ci")
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument(
        "--expected-ref",
        help="exact PR head ref; required for non-codex/ branches (does not grant release)",
    )
    parser.add_argument(
        "--dispatch-source",
        action="store_true",
        help="dispatch two manual source workflows; never claim full PR CI green",
    )
    args = parser.parse_args()
    if (
        not REPOSITORY.fullmatch(args.repo)
        or args.pr <= 0
        or not SHA.fullmatch(args.expected_sha)
    ):
        parser.error("invalid repo, PR number or exact 40-digit lowercase SHA")
    if args.expected_ref is not None and not valid_branch_ref(args.expected_ref):
        parser.error("invalid exact Git branch ref")
    pr, report = current(
        args.repo, args.pr, args.expected_sha, expected_ref=args.expected_ref
    )
    if args.dispatch_source:
        branch = pr["head"]["ref"]
        for name in MANUAL:
            gh("workflow", "run", name, "--repo", args.repo, "--ref", branch)
        # A concurrent branch push invalidates any submitted source-only retry.
        current(
            args.repo, args.pr, args.expected_sha, expected_ref=args.expected_ref
        )
        report["source_only_dispatch_submitted"] = True
        report["source_only_is_not_full_pr_ci"] = True
    print(json.dumps(report, sort_keys=True))
    return 0 if report["qualified"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        ValueError,
    ) as error:
        raise SystemExit(f"exact PR CI identity/transport error: {error}") from error
