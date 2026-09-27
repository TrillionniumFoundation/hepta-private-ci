#!/usr/bin/env python3
"""Require an independent approval bound to the exact platform.types PR head."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA1 = re.compile(r"^[0-9a-f]{40}$")
DECISIVE_STATES = frozenset({"APPROVED", "CHANGES_REQUESTED", "DISMISSED"})
TRUSTED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})


class IndependentReviewError(RuntimeError):
    """The independent-review evidence could not be obtained or interpreted."""


def _login(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    login = value.get("login")
    return login if isinstance(login, str) and login else None


def _review_order(review: dict[str, Any]) -> tuple[str, int]:
    submitted = review.get("submitted_at")
    review_id = review.get("id")
    return (
        submitted if isinstance(submitted, str) else "",
        review_id if isinstance(review_id, int) else 0,
    )


def evaluate_review_gate(
    *,
    repository: str,
    pr_number: int,
    expected_head: str,
    pull_request: dict[str, Any],
    reviews: list[dict[str, Any]],
    commits: list[dict[str, Any]],
) -> dict[str, Any]:
    head = pull_request.get("head")
    observed_head = head.get("sha") if isinstance(head, dict) else None
    author = _login(pull_request.get("user"))
    failures: list[str] = []
    if observed_head != expected_head:
        failures.append("pull_request_head_mismatch")
    if author is None:
        failures.append("pull_request_author_missing")

    excluded: dict[str, str] = {}
    if author is not None:
        excluded[author.casefold()] = "pull_request_author"
    for commit in commits:
        for field in ("author", "committer"):
            actor = _login(commit.get(field))
            if actor is not None:
                excluded.setdefault(actor.casefold(), f"commit_{field}")

    decisive: dict[str, dict[str, Any]] = {}
    for review in reviews:
        reviewer = _login(review.get("user"))
        state = review.get("state")
        if reviewer is None or state not in DECISIVE_STATES:
            continue
        key = reviewer.casefold()
        previous = decisive.get(key)
        if previous is None or _review_order(review) > _review_order(previous):
            decisive[key] = review

    qualifying: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for key, review in sorted(decisive.items()):
        reviewer = _login(review.get("user"))
        assert reviewer is not None
        state = str(review.get("state"))
        commit_id = review.get("commit_id")
        association = review.get("author_association")
        reason: str | None = None
        if state != "APPROVED":
            reason = f"latest_decisive_state_{state.lower()}"
        elif commit_id != expected_head:
            reason = "approval_not_bound_to_current_head"
        elif key in excluded:
            reason = excluded[key]
        elif reviewer.endswith("[bot]"):
            reason = "bot_reviewer"
        elif association not in TRUSTED_ASSOCIATIONS:
            reason = "reviewer_not_repository_member_or_collaborator"

        record = {
            "reviewer": reviewer,
            "reviewId": review.get("id"),
            "state": state,
            "commitId": commit_id,
            "submittedAt": review.get("submitted_at"),
            "authorAssociation": association,
        }
        if reason is None:
            qualifying.append(record)
        else:
            record["rejectionReason"] = reason
            rejected.append(record)

    if not qualifying:
        failures.append("no_independent_current_head_approval")
    return {
        "schema": "hepta.platform-types.independent-review.v1",
        "schemaVersion": 1,
        "repository": repository,
        "pullRequest": pr_number,
        "expectedHeadSha": expected_head,
        "observedHeadSha": observed_head,
        "pullRequestAuthor": author,
        "excludedCandidateActors": [
            {"login": login, "reason": excluded[login]} for login in sorted(excluded)
        ],
        "qualifyingApprovals": qualifying,
        "rejectedDecisiveReviews": rejected,
        "failureReasons": failures,
        "status": "passed" if not failures else "failed",
        "claimBoundary": (
            "current-head independent source review only; not deployment, "
            "operator acceptance, promotion, release, or qualification receipt"
        ),
    }


def _request_json(url: str, token: str) -> tuple[Any, dict[str, str]]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "hepta-platform-types-independent-review",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            headers = {key: value for key, value in response.headers.items()}
            return json.loads(response.read().decode("utf-8")), headers
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise IndependentReviewError(f"GitHub API request failed for {url}: {error}") from error


def _collection(url: str, token: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page = 1
    while True:
        separator = "&" if "?" in url else "?"
        value, _ = _request_json(f"{url}{separator}per_page=100&page={page}", token)
        if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
            raise IndependentReviewError(f"GitHub API collection required for {url}")
        rows.extend(value)
        if len(value) < 100:
            return rows
        page += 1
        if page > 100:
            raise IndependentReviewError(f"GitHub API pagination exceeded for {url}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pr-number", type=int, required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    try:
        if REPOSITORY.fullmatch(args.repository) is None:
            raise IndependentReviewError("repository must be owner/name")
        if args.pr_number <= 0:
            raise IndependentReviewError("pull request number must be positive")
        if SHA1.fullmatch(args.head_sha) is None:
            raise IndependentReviewError("head SHA must be an exact lowercase commit id")
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            raise IndependentReviewError("GITHUB_TOKEN is required")
        root = f"https://api.github.com/repos/{args.repository}"
        pull, _ = _request_json(f"{root}/pulls/{args.pr_number}", token)
        if not isinstance(pull, dict):
            raise IndependentReviewError("pull request object required")
        reviews = _collection(f"{root}/pulls/{args.pr_number}/reviews", token)
        commits = _collection(f"{root}/pulls/{args.pr_number}/commits", token)
        result = evaluate_review_gate(
            repository=args.repository,
            pr_number=args.pr_number,
            expected_head=args.head_sha,
            pull_request=pull,
            reviews=reviews,
            commits=commits,
        )
    except IndependentReviewError as error:
        result = {
            "schema": "hepta.platform-types.independent-review.v1",
            "schemaVersion": 1,
            "repository": args.repository,
            "pullRequest": args.pr_number,
            "expectedHeadSha": args.head_sha,
            "status": "failed",
            "failureReasons": [str(error)],
        }

    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if result.get("status") == "passed":
        reviewers = ", ".join(
            row["reviewer"] for row in result["qualifyingApprovals"]
        )
        print(f"platform.types independent review: passed ({reviewers})")
        return 0
    print(
        "platform.types independent review: failed: "
        + ", ".join(result.get("failureReasons", ["unknown failure"])),
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
