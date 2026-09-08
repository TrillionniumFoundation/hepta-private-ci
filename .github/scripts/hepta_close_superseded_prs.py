#!/usr/bin/env python3
"""Close open PRs whose exact head is a strict ancestor of a canonical commit.

The tool deliberately distinguishes "superseded" from "merged". A history-only
ancestor may have been reviewed and retained without its tree being selected.
Only exact Git ancestry is used; titles, labels, branch names and timestamps are
never treated as authority.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

OID_RE = re.compile(r"[0-9a-f]{40}")
API_VERSION = "2022-11-28"
MAX_OPEN_PULLS = 1000


class ApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class PullDisposition:
    number: int
    head_sha: str
    head_ref: str
    action: str
    reason: str


class GitHubApi:
    def __init__(self, repository: str, token: str) -> None:
        if repository.count("/") != 1:
            raise ValueError("repository must be owner/name")
        if not token:
            raise ValueError("GITHUB_TOKEN is required")
        self.repository = repository
        self.base = f"https://api.github.com/repos/{repository}"
        self.headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "hepta-superseded-pr-reconciler/1",
            "X-GitHub-Api-Version": API_VERSION,
        }

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> tuple[Any, dict[str, str]]:
        data = None
        headers = dict(self.headers)
        if body is not None:
            data = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
                value = json.loads(raw) if raw else None
                return value, {key.lower(): value for key, value in response.headers.items()}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:4096]
            raise ApiError(f"{method} {path}: HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ApiError(f"{method} {path}: {exc.reason}") from exc

    def open_pulls(self) -> list[dict[str, Any]]:
        pulls: list[dict[str, Any]] = []
        page = 1
        while True:
            value, _headers = self.request(
                "GET",
                f"/pulls?state=open&sort=created&direction=asc&per_page=100&page={page}",
            )
            if not isinstance(value, list):
                raise ApiError("pull list response is not an array")
            pulls.extend(value)
            if len(pulls) > MAX_OPEN_PULLS:
                raise ApiError(f"open pull count exceeds safety limit {MAX_OPEN_PULLS}")
            if len(value) < 100:
                return pulls
            page += 1

    def compare(self, base_sha: str, head_sha: str) -> dict[str, Any]:
        value, _headers = self.request("GET", f"/compare/{base_sha}...{head_sha}")
        if not isinstance(value, dict):
            raise ApiError("compare response is not an object")
        return value

    def comment(self, number: int, body: str) -> None:
        self.request("POST", f"/issues/{number}/comments", {"body": body})

    def close(self, number: int) -> None:
        self.request("PATCH", f"/pulls/{number}", {"state": "closed"})


def require_oid(value: str, label: str) -> str:
    if OID_RE.fullmatch(value) is None or value == "0" * 40:
        raise ValueError(f"{label} must be a nonzero lowercase full Git OID")
    return value


def reconcile(
    api: GitHubApi,
    canonical_sha: str,
    apply: bool,
    delay_seconds: float,
) -> list[PullDisposition]:
    dispositions: list[PullDisposition] = []
    for pull in api.open_pulls():
        number = pull.get("number")
        head = pull.get("head")
        if not isinstance(number, int) or not isinstance(head, dict):
            raise ApiError("pull response is missing number/head")
        head_sha = require_oid(str(head.get("sha", "")), f"pull {number} head")
        head_ref = str(head.get("ref", ""))
        head_repo = head.get("repo")
        head_full_name = head_repo.get("full_name") if isinstance(head_repo, dict) else None

        if head_sha == canonical_sha:
            dispositions.append(
                PullDisposition(number, head_sha, head_ref, "kept", "canonical_head")
            )
            continue
        if head_full_name != api.repository:
            dispositions.append(
                PullDisposition(number, head_sha, head_ref, "kept", "external_head_repository")
            )
            continue

        comparison = api.compare(head_sha, canonical_sha)
        merge_base = comparison.get("merge_base_commit")
        merge_base_sha = merge_base.get("sha") if isinstance(merge_base, dict) else None
        status = comparison.get("status")
        if merge_base_sha != head_sha or status != "ahead":
            dispositions.append(
                PullDisposition(number, head_sha, head_ref, "kept", "head_not_strict_ancestor")
            )
            continue

        if apply:
            comment = (
                "This PR is being closed as **superseded**, not represented as a GitHub merge. "
                f"Its exact head `{head_sha}` is a strict ancestor of the canonical closure "
                f"candidate `{canonical_sha}`. The final candidate retains the history while "
                "its selected tree, current contracts, tests and qualification receipts are "
                "authoritative. Reopen only with a new non-ancestor head and an explicit delta "
                "against the canonical candidate."
            )
            api.comment(number, comment)
            api.close(number)
            if delay_seconds:
                time.sleep(delay_seconds)
        dispositions.append(
            PullDisposition(number, head_sha, head_ref, "closed" if apply else "would_close", "strict_ancestor")
        )
    return dispositions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--canonical-sha", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--delay-seconds", type=float, default=0.05)
    args = parser.parse_args()

    canonical_sha = require_oid(args.canonical_sha, "canonical SHA")
    token = os.environ.get("GITHUB_TOKEN", "")
    api = GitHubApi(args.repository, token)
    dispositions = reconcile(api, canonical_sha, args.apply, args.delay_seconds)
    report = {
        "schema": "hepta.superseded-pr-reconciliation.v1",
        "repository": args.repository,
        "canonicalSha": canonical_sha,
        "apply": args.apply,
        "counts": {
            "total": len(dispositions),
            "closed": sum(item.action == "closed" for item in dispositions),
            "wouldClose": sum(item.action == "would_close" for item in dispositions),
            "kept": sum(item.action == "kept" for item in dispositions),
        },
        "dispositions": [asdict(item) for item in dispositions],
    }
    encoded = json.dumps(report, sort_keys=True, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(encoded, encoding="utf-8")
    sys.stdout.write(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
