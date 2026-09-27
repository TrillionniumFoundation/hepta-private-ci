#!/usr/bin/env python3
"""Enforce exact-blob merge policy and current-head independent approval."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
EXACT_PATHS = (
    "tools/hepta-engineering-control/",
    "docs/modules/control.engineering/",
    "scripts/hepta-implementation-maps.py",
    "scripts/hepta_control_engineering_",
    ".github/workflows/control-engineering-required.yml",
    ".github/workflows/blocking-ci.yml",
)
DECLARATION = "CONTROL_ENGINEERING_MERGE_METHOD=merge_commit"


def git(*args: str, allow_failure: bool = False) -> str:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_TERMINAL_PROMPT="0",
    )
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode and not allow_failure:
        raise SystemExit(result.stderr.strip() or "git command failed")
    return result.stdout.strip()


def _changed(base: str, head: str) -> list[str]:
    return [
        path
        for path in git("diff", "--name-only", base, head, "--").splitlines()
        if path
    ]


def _touches_exact(paths: list[str]) -> bool:
    return any(any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in EXACT_PATHS) for path in paths)


def verify_merge_policy(event_name: str, base: str, head: str, event_path: Path | None) -> dict[str, object]:
    paths = _changed(base, head) if base and git("cat-file", "-e", f"{base}^{{commit}}", allow_failure=True) == "" else []
    applies = _touches_exact(paths)
    result: dict[str, object] = {
        "schema": "hepta.control-engineering-merge-policy.v1",
        "eventName": event_name,
        "base": base,
        "head": head,
        "applies": applies,
        "changedPaths": paths,
        "requiredMergeMethod": "merge_commit" if applies else "not_applicable",
        "passed": True,
    }
    if not applies:
        return result
    if event_name == "pull_request":
        if event_path is None or not event_path.is_file():
            raise SystemExit("pull request event payload is required")
        event = json.loads(event_path.read_text(encoding="utf-8"))
        body = str(event.get("pull_request", {}).get("body") or "")
        if DECLARATION not in body:
            raise SystemExit(
                "exact-blob changes require an explicit merge-commit declaration in the PR body"
            )
        if git("merge-base", "--is-ancestor", base, head, allow_failure=True) != "":
            raise SystemExit("pull request head is not based on the current base")
        result["declaration"] = DECLARATION
        return result
    if event_name == "push":
        parents = git("show", "-s", "--format=%P", head).split()
        if len(parents) < 2:
            raise SystemExit(
                "exact-blob changes on main must arrive through a merge commit; squash/rebase integration is rejected"
            )
        result["parents"] = parents
        return result
    raise SystemExit("unsupported event for exact-blob merge policy")


def verify_review(reviews_path: Path, *, head: str, author: str) -> dict[str, object]:
    reviews = json.loads(reviews_path.read_text(encoding="utf-8"))
    if not isinstance(reviews, list):
        raise SystemExit("review response must be a list")
    latest: dict[str, dict[str, object]] = {}
    for review in reviews:
        if not isinstance(review, dict):
            continue
        user = review.get("user")
        login = user.get("login") if isinstance(user, dict) else None
        if not isinstance(login, str) or not login:
            continue
        submitted = str(review.get("submitted_at") or "")
        current = latest.get(login)
        if current is None or submitted >= str(current.get("submitted_at") or ""):
            latest[login] = review
    approvals = []
    for login, review in latest.items():
        if login == author or login.endswith("[bot]"):
            continue
        if str(review.get("state", "")).upper() != "APPROVED":
            continue
        commit_id = review.get("commit_id")
        if commit_id != head:
            continue
        approvals.append(
            {
                "login": login,
                "reviewId": review.get("id"),
                "submittedAt": review.get("submitted_at"),
                "commitId": commit_id,
            }
        )
    if not approvals:
        raise SystemExit(
            "control.engineering requires a non-author, non-bot APPROVED review bound to the current head SHA"
        )
    body: dict[str, object] = {
        "schema": "hepta.control-engineering-independent-review.v1",
        "head": head,
        "author": author,
        "approvals": sorted(approvals, key=lambda row: str(row["login"])),
        "independentAcceptance": False,
        "mergeAuthority": False,
    }
    body["reviewObservationDigest"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return body


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    merge = sub.add_parser("merge")
    merge.add_argument("--event-name", required=True)
    merge.add_argument("--base", required=True)
    merge.add_argument("--head", required=True)
    merge.add_argument("--event-path", type=Path)
    merge.add_argument("--output", type=Path, required=True)
    review = sub.add_parser("review")
    review.add_argument("--reviews", type=Path, required=True)
    review.add_argument("--head", required=True)
    review.add_argument("--author", required=True)
    review.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "merge":
        value = verify_merge_policy(args.event_name, args.base, args.head, args.event_path)
    else:
        value = verify_review(args.reviews, head=args.head, author=args.author)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
