#!/usr/bin/env python3
"""Check current-head independent review; this script never changes authority.

The PR/review/permission input must come from authenticated GitHub API reads in
CI. A caller-supplied JSON document is not, by itself, proof of a review.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from verify_memory_retrieval_slo import loads

CLAIMS = ("productionImplementation", "productExecutionProved", "independentAcceptance", "activation", "release")
DECISIONS = {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}


def is_promoted(mapping: dict[str, Any]) -> bool:
    promoted = False
    for node in (mapping, mapping.get("claimBoundary", {})):
        if not isinstance(node, dict):
            raise ValueError("invalid implementation-map claims")
        for key in CLAIMS:
            if key in node:
                if type(node[key]) is not bool:
                    raise ValueError(f"{key}: claim must be an explicit Boolean")
                promoted |= node[key]
    return promoted


def check_promotion(mapping: dict[str, Any], envelope: dict[str, Any], source: str) -> list[str]:
    if not is_promoted(mapping):
        return []
    pr = envelope.get("pull_request")
    if not isinstance(pr, dict) or pr.get("draft") is not False:
        raise ValueError("promotion requires a non-draft pull request")
    if pr.get("head", {}).get("sha") != source:
        raise ValueError("pull request head differs from qualification source")
    author = pr.get("user", {}).get("login")
    if not isinstance(author, str) or not author:
        raise ValueError("missing author identity")
    permissions = envelope.get("permissions")
    reviews = envelope.get("reviews")
    if not isinstance(permissions, dict) or not isinstance(reviews, list):
        raise ValueError("missing authenticated review/permission inventory")
    latest: dict[str, dict[str, Any]] = {}
    ids: set[int] = set()
    for review in reviews:
        identity = review.get("id")
        if type(identity) is not int or identity <= 0 or identity in ids:
            raise ValueError("invalid or duplicate review identity")
        ids.add(identity)
        user = review.get("user", {})
        login = user.get("login")
        if not isinstance(login, str) or not login:
            raise ValueError("missing reviewer identity")
        state = review.get("state")
        # Comments do not replace formal review decisions. Dismissals do.
        if state not in DECISIONS:
            continue
        if login not in latest or identity > latest[login]["id"]:
            latest[login] = review
    eligible = []
    for login, review in latest.items():
        if login == author or review.get("user", {}).get("type") != "User":
            continue
        if permissions.get(login) not in ("write", "maintain", "admin"):
            continue
        if review["state"] == "CHANGES_REQUESTED":
            raise ValueError("an authorized independent reviewer requested changes")
        if review["state"] == "APPROVED" and review.get("commit_id") == source:
            eligible.append(login)
    if not eligible:
        raise ValueError("no independent authorized approval of this exact head")
    return sorted(eligible)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", required=True, type=Path)
    parser.add_argument("--github-observation", required=True, type=Path)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    try:
        mapping = loads(args.map.read_text())
        reviewers = check_promotion(mapping, loads(args.github_observation.read_text()), args.source_sha)
        print("current-head review gate:", ", ".join(reviewers) if reviewers else "no production promotion requested")
        return 0
    except (ValueError, OSError, TypeError, AttributeError) as error:
        print(f"FAIL: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
