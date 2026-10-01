"""Current-head GitHub approval gate without semantic-acceptance inflation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

_SCHEMA = "hepta.control-engineering-github-approval-gate.v1"
_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
_MAX_REVIEWS = 512


def _review_key(row: Mapping[str, object]) -> tuple[str, int]:
    submitted = row.get("submitted_at")
    review_id = row.get("id")
    if not isinstance(submitted, str) or type(review_id) is not int:
        raise ValueError("github_review_shape")
    return submitted, review_id


def require_independent_approved_review(
    reviews: object,
    *,
    expected_head_sha: str,
    author_user_id: int,
    author_login: str,
    allowed_reviewers: tuple[str, ...] = (),
) -> dict[str, object]:
    if not isinstance(expected_head_sha, str) or _SHA1.fullmatch(expected_head_sha) is None:
        raise ValueError("github_review_head")
    if type(author_user_id) is not int or author_user_id <= 0 or not author_login:
        raise ValueError("github_review_author")
    if not isinstance(reviews, list) or len(reviews) > _MAX_REVIEWS:
        raise ValueError("github_review_shape")
    allowed = {value.casefold() for value in allowed_reviewers}
    latest: dict[int, Mapping[str, object]] = {}
    for row in reviews:
        if not isinstance(row, Mapping):
            raise ValueError("github_review_shape")
        user = row.get("user")
        if not isinstance(user, Mapping):
            raise ValueError("github_review_shape")
        user_id = user.get("id")
        login = user.get("login")
        state = row.get("state")
        commit_id = row.get("commit_id")
        if (
            type(user_id) is not int
            or user_id <= 0
            or not isinstance(login, str)
            or not login
            or state not in {"APPROVED", "CHANGES_REQUESTED", "COMMENTED", "DISMISSED"}
            or not isinstance(commit_id, str)
            or _SHA1.fullmatch(commit_id) is None
        ):
            raise ValueError("github_review_shape")
        current = latest.get(user_id)
        if current is None or _review_key(row) > _review_key(current):
            latest[user_id] = row

    approvals: list[dict[str, object]] = []
    for user_id, row in latest.items():
        user = row["user"]
        login = str(user["login"])
        if (
            user_id == author_user_id
            or login.casefold() == author_login.casefold()
            or login.casefold().endswith("[bot]")
            or row.get("state") != "APPROVED"
            or row.get("commit_id") != expected_head_sha
            or (allowed and login.casefold() not in allowed)
        ):
            continue
        approvals.append(
            {
                "reviewId": int(row["id"]),
                "reviewerUserId": user_id,
                "reviewerLogin": login,
                "commitId": row["commit_id"],
                "submittedAt": row["submitted_at"],
            }
        )
    approvals.sort(key=lambda item: (str(item["submittedAt"]), int(item["reviewId"])))
    if not approvals:
        raise ValueError("independent_current_head_approval_missing")
    value: dict[str, object] = {
        "schema": _SCHEMA,
        "expectedHeadSha": expected_head_sha,
        "authorUserId": author_user_id,
        "authorLogin": author_login,
        "allowedReviewers": sorted(allowed),
        "approvals": approvals,
        "githubApprovalObserved": True,
        "independentSemanticAcceptance": False,
        "mergeAuthority": False,
        "releaseAuthority": False,
    }
    value["gateDigest"] = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviews", required=True, type=Path)
    parser.add_argument("--expected-head-sha", required=True)
    parser.add_argument("--author-user-id", required=True, type=int)
    parser.add_argument("--author-login", required=True)
    parser.add_argument("--allowed-reviewer", action="append", default=[])
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        reviews = json.loads(args.reviews.read_text(encoding="utf-8"))
        value = require_independent_approved_review(
            reviews,
            expected_head_sha=args.expected_head_sha,
            author_user_id=args.author_user_id,
            author_login=args.author_login,
            allowed_reviewers=tuple(args.allowed_reviewer),
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"schema": _SCHEMA, "status": "rejected", "error": str(error)}))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
