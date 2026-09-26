#!/usr/bin/env python3
"""Fail closed when memory.retrieval production claims are promoted without review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

PROTECTED_CLAIMS: tuple[tuple[str, ...], ...] = (
    ("productionImplementation",),
    ("claimBoundary", "productionImplementation"),
    ("claimBoundary", "productExecutionProved"),
    ("claimBoundary", "independentAcceptance"),
    ("claimBoundary", "activation"),
    ("claimBoundary", "release"),
)
ALLOWED_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}


def _value(document: dict[str, Any], path: tuple[str, ...]) -> bool:
    current: Any = document
    for part in path:
        if not isinstance(current, dict):
            return False
        current = current.get(part)
    return current is True


def promoted_claims(base: dict[str, Any], head: dict[str, Any]) -> list[str]:
    return [".".join(path) for path in PROTECTED_CLAIMS if not _value(base, path) and _value(head, path)]


def _flatten_reviews(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, list):
            rows.extend(_flatten_reviews(item))
        elif isinstance(item, dict):
            rows.append(item)
    return rows


def current_independent_approvals(
    reviews: Any,
    *,
    author_login: str,
    head_sha: str,
) -> list[str]:
    latest: dict[str, dict[str, Any]] = {}
    for review in _flatten_reviews(reviews):
        user = review.get("user") or {}
        login = str(user.get("login") or "")
        if not login:
            continue
        previous = latest.get(login)
        order = (str(review.get("submitted_at") or ""), int(review.get("id") or 0))
        previous_order = (
            str((previous or {}).get("submitted_at") or ""),
            int((previous or {}).get("id") or 0),
        )
        if previous is None or order >= previous_order:
            latest[login] = review

    approved: list[str] = []
    for login, review in latest.items():
        user = review.get("user") or {}
        if login == author_login or str(user.get("type") or "").lower() == "bot":
            continue
        if str(review.get("state") or "").upper() != "APPROVED":
            continue
        if str(review.get("commit_id") or "") != head_sha:
            continue
        if str(review.get("author_association") or "").upper() not in ALLOWED_ASSOCIATIONS:
            continue
        approved.append(login)
    return sorted(approved)


def verify(
    base: dict[str, Any],
    head: dict[str, Any],
    event: dict[str, Any],
    reviews: Any,
    *,
    head_sha: str,
) -> dict[str, Any]:
    promotions = promoted_claims(base, head)
    result: dict[str, Any] = {
        "schema": "hepta.memory-retrieval.review-gate.v1",
        "head": head_sha,
        "promotions": promotions,
        "approvedBy": [],
    }
    if not promotions:
        result["decision"] = "not_required"
        return result

    pull = event.get("pull_request")
    if not isinstance(pull, dict):
        raise ValueError("memory.retrieval production claims may only be promoted through a pull request")
    if bool(pull.get("draft")):
        raise ValueError("a draft pull request cannot promote memory.retrieval production claims")
    author = str(((pull.get("user") or {}).get("login")) or "")
    event_head = str((((pull.get("head") or {}).get("sha")) or ""))
    if not author or event_head != head_sha:
        raise ValueError("pull-request author/head identity is missing or stale")
    approvals = current_independent_approvals(reviews, author_login=author, head_sha=head_sha)
    if not approvals:
        raise ValueError(
            "production-claim promotion requires a current-head approval from an independent repository owner/member/collaborator"
        )
    result["decision"] = "approved"
    result["approvedBy"] = approvals
    return result


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-map", type=Path, required=True)
    parser.add_argument("--head-map", type=Path, required=True)
    parser.add_argument("--event-json", type=Path, required=True)
    parser.add_argument("--reviews-json", type=Path, required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify(
        _load(args.base_map),
        _load(args.head_map),
        _load(args.event_json),
        _load(args.reviews_json),
        head_sha=args.head_sha,
    )
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
