#!/usr/bin/env python3
"""Fail closed unless an exact self-iteration PR has real repository controls."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request


def fail(message: str) -> None:
    raise SystemExit("FAIL_HEPTA_SELF_ITERATION_GOVERNANCE: " + message)


def api(path: str, token: str) -> object:
    request = urllib.request.Request(
        "https://api.github.com" + path,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "hepta-self-iteration-governance",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)
    except (urllib.error.URLError, json.JSONDecodeError) as error:
        fail(f"GitHub observation failed: {error}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        fail("GITHUB_TOKEN missing")
    event = json.loads(pathlib.Path(args.event).read_text(encoding="utf-8"))
    pr = event.get("pull_request")
    if not isinstance(pr, dict):
        fail("pull_request event required")

    head = pr.get("head", {}).get("sha")
    base_ref = pr.get("base", {}).get("ref")
    number = pr.get("number")
    author = pr.get("user", {}).get("login")
    if head != args.expected_head:
        fail("event head differs from checked candidate")
    if base_ref != "main":
        fail("self-iteration governance requires canonical main base")
    if not isinstance(number, int) or not author:
        fail("pull request identity missing")

    branch = api(f"/repos/{args.repository}/branches/main", token)
    if not isinstance(branch, dict) or branch.get("protected") is not True:
        fail("canonical main branch is not protected")

    reviews = api(f"/repos/{args.repository}/pulls/{number}/reviews?per_page=100", token)
    if not isinstance(reviews, list):
        fail("review observation malformed")

    latest: dict[str, dict] = {}
    for review in reviews:
        if not isinstance(review, dict):
            continue
        user = review.get("user", {}).get("login")
        if user:
            latest[user] = review

    approved = []
    for reviewer, review in latest.items():
        if reviewer == author:
            continue
        if review.get("state") != "APPROVED":
            continue
        if review.get("commit_id") != head:
            continue
        if review.get("author_association") not in {"MEMBER", "COLLABORATOR", "OWNER"}:
            continue
        approved.append(reviewer)
    if not approved:
        fail("no independent repository member approved this exact head")

    receipt = {
        "schema": "hepta.self-iteration-governance.v1",
        "repository": args.repository,
        "pullRequest": number,
        "head": head,
        "base": base_ref,
        "branchProtected": True,
        "author": author,
        "independentExactHeadApprovers": sorted(approved),
        "authorityGranted": False,
        "status": "PASS_HEPTA_SELF_ITERATION_GOVERNANCE",
    }
    target = pathlib.Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
