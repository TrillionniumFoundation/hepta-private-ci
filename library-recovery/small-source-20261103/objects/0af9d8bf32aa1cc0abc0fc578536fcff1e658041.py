#!/usr/bin/env python3
"""Read-only GitHub Actions backlog audit for exact-source Hepta research.

Never issues GitHub write requests. Output is a review plan, NOT cancellation
approval, CI acceptance or production authority. Bounded GitHub REST scans may
be incomplete when GitHub reports more queue entries than API pages expose.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

CURRENT_REPO = "TrillionniumFoundation/hepta-private-ci"
CURRENT_PR = 2366
CURRENT_SHA = "f019280f1c1fe77b13b847901ad69098b1e1a2ba"
HEX40 = re.compile(r"[a-f0-9]{40}\Z")
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
# The ONLY workflow names eligible for a MANUAL review of cancellation. Never
# cancel Architecture, security, owner, signed evidence or release checks.
REVIEWABLE_RESEARCH = frozenset({
    "Hepta Cell Meta pinned Granite retrospective physical study (DENY_ALL)",
    "Hepta Cell Meta physical Router CPU research",
})
SCHEMA = "hepta.actions-queue-read-only-screen.v1"


class InvalidQueue(ValueError):
    """Incomplete, malformed or potentially misleading queue observation."""


def require(valid: bool, message: str) -> None:
    if not valid:
        raise InvalidQueue(message)


def read_json(path: Path, *, maximum: int = 8_000_000) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), "unsafe input fixture")
    stat = path.stat()
    require(0 < stat.st_size <= maximum, "input too large")
    with path.open("rb") as f:
        raw = f.read(maximum + 1)
    require(len(raw) == stat.st_size, "input changed while reading")
    try:
        doc = json.loads(raw, object_pairs_hook=reject_duplicate_keys,
                         parse_constant=lambda x: (_ for _ in ()).throw(
                             InvalidQueue("nonfinite input")))
    except (ValueError, RecursionError, UnicodeDecodeError) as e:
        raise InvalidQueue("invalid JSON input") from e
    require(type(doc) is dict, "expected object fixture")
    return doc


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        require(name not in result, "duplicate JSON key")
        result[name] = value
    return result


def gh_get(repo: str, status: str, page: int, token: str | None) -> dict[str, Any]:
    require(REPO.fullmatch(repo) is not None, "malformed repository")
    require(status in ("queued", "in_progress"), "unsupported run status")
    url = f"https://api.github.com/repos/{repo}/actions/runs?" + urlencode(
        {"status": status, "per_page": 100, "page": page})
    headers = {"Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": "hepta-read-only-queue-screen"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = Request(url, headers=headers, method="GET")
    try:
        with urlopen(req, timeout=25) as response:
            raw = response.read(2_000_001)
    except (HTTPError, URLError, TimeoutError) as e:
        # Do not print tokens, URLs, error bodies, or confidential response data.
        raise InvalidQueue("GitHub Actions inventory unavailable") from e
    require(len(raw) < 2_000_001, "API response too large")
    try:
        doc = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as e:
        raise InvalidQueue("invalid API response") from e
    require(type(doc) is dict, "invalid API structure")
    return doc


def get_inventory(repo: str, status: str, pages: int, token: str | None) -> dict[str, Any]:
    require(type(pages) is int and 1 <= pages <= 10, "bounded 1..10 page scan")
    runs: list[Any] = []
    total = None
    for page in range(1, pages + 1):
        doc = gh_get(repo, status, page, token)
        reported = doc.get("total_count")
        candidates = doc.get("workflow_runs")
        require(type(reported) is int and reported >= 0 and type(candidates) is list,
                "incomplete GitHub inventory response")
        if total is None:
            total = reported
        else:
            # The total can change between page fetches; do not assert
            # exhaustive coverage, but retain the highest reported count.
            total = max(total, reported)
        runs.extend(candidates)
        if len(candidates) < 100:
            break
    return {"total_count": total, "workflow_runs": runs}


def pr_number(run: dict[str, Any]) -> int | None:
    # Do not infer PR identity from branch names, title strings or author names.
    prs = run.get("pull_requests")
    if type(prs) is not list or len(prs) != 1:
        return None
    item = prs[0]
    value = item.get("number") if type(item) is dict else None
    return value if type(value) is int and value > 0 else None


def summary(run: dict[str, Any]) -> dict[str, Any]:
    ident, title, status, sha = (run.get(k) for k in
                                 ("id", "name", "status", "head_sha"))
    require(type(ident) is int and ident > 0, "invalid run ID")
    require(type(title) is str and 0 < len(title) <= 200, "invalid workflow name")
    require(status in ("queued", "in_progress"), "invalid run state")
    require(type(sha) is str and HEX40.fullmatch(sha) is not None,
            "invalid source SHA")
    return {"id": ident, "name": title, "status": status, "head_sha": sha,
            "pr": pr_number(run), "event": run.get("event"),
            "attempt": run.get("run_attempt"),
            "created_at": run.get("created_at"),
            "url": run.get("html_url")}


def screen(fixture: dict[str, Any], *, repo: str=CURRENT_REPO,
           current_pr: int=CURRENT_PR, current_sha: str=CURRENT_SHA) -> dict[str, Any]:
    require(REPO.fullmatch(repo) is not None and
            type(current_pr) is int and current_pr > 0 and
            type(current_sha) is str and HEX40.fullmatch(current_sha) is not None,
            "invalid exact source selector")
    require(type(fixture) is dict, "invalid fixture")
    collected: list[dict[str, Any]] = []
    totals: dict[str, int] = {}
    seen: set[int] = set()
    for status in ("queued", "in_progress"):
        payload = fixture.get(status)
        require(type(payload) is dict, "missing status inventory")
        total, runs = payload.get("total_count"), payload.get("workflow_runs")
        require(type(total) is int and total >= 0 and type(runs) is list,
                "invalid inventory field")
        totals[status] = total
        for raw in runs:
            require(type(raw) is dict, "invalid raw run")
            normalized = summary(raw)
            require(normalized["status"] == status, "run in wrong status bucket")
            require(normalized["id"] not in seen, "duplicated queued run ID")
            seen.add(normalized["id"])
            collected.append(normalized)
    all_current = [r for r in collected if r["pr"] == current_pr and
                   r["head_sha"] == current_sha]
    by_name = Counter(r["name"] for r in collected)
    review: list[dict[str, Any]] = []
    for old in collected:
        if (old["pr"] != current_pr or old["head_sha"] == current_sha or
            old["status"] != "queued" or old["name"] not in REVIEWABLE_RESEARCH or
            old["event"] != "pull_request" or old["attempt"] != 1):
            continue
        newest = [x for x in all_current if x["name"] == old["name"]]
        if not newest:
            continue
        # Only recommend a human inspect. The script has no GitHub POST/DELETE
        # and never emits a cancel URL or an executable cancellation command.
        review.append({"run_id": old["id"], "name": old["name"],
                       "old_sha": old["head_sha"],
                       "replacement_sha": current_sha,
                       "reason": "same_PR_same_research_workflow_older_source",
                       "disposition": "MANUAL_OWNERSHIP_AND_RECEIPT_REVIEW_REQUIRED"})
    review.sort(key=lambda x: x["run_id"])
    have = {k: sum(r["status"] == k for r in collected) for k in totals}
    incomplete = any(have[k] < totals[k] for k in totals)
    return {
        "schema": SCHEMA,
        "repository": repo,
        "current_candidate": {"pr": current_pr, "head_sha": current_sha},
        "source_inventory": {"reported_count": totals, "observed_count": have,
                             "partial_inventory": incomplete,
                             "page_limited_or_concurrent_mutations_possible": True},
        "top_observed_queued_workflows": sorted(
            ({"name": k, "sampled_runs": v} for k, v in by_name.items()),
            key=lambda x: (-x["sampled_runs"], x["name"]))[:20],
        "latest_head_observed": bool(all_current),
        "latest_head_running": any(x["status"] == "in_progress" for x in all_current),
        "review_only_possible_supersessions": review,
        "cancelled_runs": [], "any_mutation_performed": False,
        "independent_runner_capacity_verified": False,
        "github_wide_outage_established": False,
        "production_admission": "BLOCKED", "authority_posture": "DENY_ALL",
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fixture", type=Path, help="Offline JSON containing queued and in_progress inventories")
    p.add_argument("--repo", default=CURRENT_REPO)
    p.add_argument("--pr", type=int, default=CURRENT_PR)
    p.add_argument("--head-sha", default=CURRENT_SHA)
    p.add_argument("--pages", type=int, default=10)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args(argv)
    try:
        if a.fixture is not None:
            inventory = read_json(a.fixture)
        else:
            token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
            inventory = {
                status: get_inventory(a.repo, status, a.pages, token)
                for status in ("queued", "in_progress")
            }
        outcome = screen(inventory, repo=a.repo, current_pr=a.pr,
                         current_sha=a.head_sha)
        destination = a.output
        require(destination.parent.is_dir() and not destination.parent.is_symlink()
                and not destination.exists() and not destination.is_symlink(),
                "unsafe or existing output")
        payload = json.dumps(outcome, sort_keys=True, ensure_ascii=True,
                             separators=(",", ":"), allow_nan=False).encode() + b"\n"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os,"O_NOFOLLOW", 0)
        fd = os.open(destination, flags, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        print(json.dumps({"output":str(destination),
                          "queued":outcome["source_inventory"]["reported_count"]["queued"],
                          "in_progress":outcome["source_inventory"]["reported_count"]["in_progress"],
                          "partial":outcome["source_inventory"]["partial_inventory"],
                          "mutation_performed":False},sort_keys=True))
        return 0
    except (InvalidQueue, OSError, ValueError) as exc:
        print("ACTIONS QUEUE READ-ONLY AUDIT DENIED: "+str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
