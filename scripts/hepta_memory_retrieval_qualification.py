#!/usr/bin/env python3
"""Exact-source and independent-promotion guards for memory.retrieval.

A source observation is not a test result. Historical sourceBase is provenance;
observedAtHead plus immutable objects binds code. The emitted observation binds
that closure to the checkout actually being tested, avoiding a self-referential
commit SHA inside its own tree.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from typing import Any
from urllib.request import Request, urlopen

try:
    from scripts.hepta_memory_retrieval_policy import (
        CLAIMS,
        INPUTS,
        MAP,
        OBJECT_INPUTS,
        REQUIRED_CHECKS,
        ROOT,
        SECURITY_CHECKS,
    )
except ModuleNotFoundError:  # direct script execution from scripts/
    from hepta_memory_retrieval_policy import (  # type: ignore
        CLAIMS,
        INPUTS,
        MAP,
        OBJECT_INPUTS,
        REQUIRED_CHECKS,
        ROOT,
        SECURITY_CHECKS,
    )

SHA = re.compile(r"[0-9a-f]{40}\Z")


class QualificationError(ValueError):
    """Evidence is missing, stale, ambiguous or not independently authorized."""


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise QualificationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if len(data) > 4 * 1024 * 1024:
        raise QualificationError("evidence JSON exceeds 4 MiB")
    value = json.loads(data, object_pairs_hook=unique_object)
    if not isinstance(value, dict):
        raise QualificationError("evidence must be an object")
    return value


def exact_sha(value: str) -> str:
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise QualificationError("an exact lowercase 40-character Git identity is required")
    return value


def git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True,
        check=False, timeout=60,
    )
    if completed.returncode:
        raise QualificationError(f"git {args[0]} failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


def safe_path(value: str) -> str:
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or ".." in path.parts
            or value.startswith(":") or "\\" in value or "\x00" in value):
        raise QualificationError(f"invalid repository path: {value!r}")
    return value


def source_observation(root: Path, head: str) -> dict[str, Any]:
    head = exact_sha(head)
    if git(root, "rev-parse", "HEAD") != head:
        raise QualificationError("checkout is not the requested exact head")
    if git(root, "status", "--porcelain", "--untracked-files=normal"):
        raise QualificationError("source checkout is dirty")
    mapping = load_json(root / MAP)
    if mapping.get("module") != "memory.retrieval":
        raise QualificationError("wrong implementation map")
    observation = mapping.get("observedAtHead", {})
    observed = exact_sha(observation.get("commit", ""))
    if git(root, "rev-parse", f"{observed}^{{tree}}") != observation.get("tree"):
        raise QualificationError("observed commit/tree mismatch")
    git(root, "merge-base", "--is-ancestor", observed, head)
    declared = [safe_path(path) for path in mapping.get("observedSourcePaths", [])]
    if declared != list(INPUTS):
        raise QualificationError("implementation map source inputs differ from canonical policy")
    changed = git(root, "diff", "--name-only", observed, head, "--", *declared)
    if any(path != MAP for path in changed.splitlines()):
        raise QualificationError(f"source closure changed after map observation: {changed}")
    rows = mapping.get("sourceObjects", [])
    if not isinstance(rows, list):
        raise QualificationError("sourceObjects must be a list")
    objects: dict[str, str] = {}
    for row in rows:
        path = safe_path(row["path"])
        if path in objects:
            raise QualificationError(f"duplicate source object: {path}")
        expected = exact_sha(row["object"])
        actual = git(root, "rev-parse", f"{head}:{path}")
        if actual != expected:
            raise QualificationError(f"stale source object: {path}")
        objects[path] = actual
    if tuple(objects) != OBJECT_INPUTS:
        raise QualificationError("source object inventory differs from canonical policy")
    if ROOT not in objects:
        raise QualificationError("full retrieval source tree must be bound")
    inventory = git(root, "ls-tree", "-r", "--full-tree", head, "--", *declared)
    parents = git(root, "show", "-s", "--format=%P", head).split()
    return {
        "schema": "hepta.memory-retrieval.source-observation.v1",
        "testedHead": head,
        "testedTree": git(root, "rev-parse", f"{head}^{{tree}}"),
        "parents": parents,
        "observedAtHead": observation,
        "sourceClosureSha256": hashlib.sha256(inventory.encode()).hexdigest(),
        "sourceObjects": objects,
        "testExecutionProved": False,
        "productionImplementation": False,
        "activation": False,
        "release": False,
    }


def requested_claims(mapping: dict[str, Any]) -> bool:
    result = False
    boundary = mapping.get("claimBoundary", {})
    for claim in CLAIMS:
        for scope in (mapping, boundary):
            value = scope.get(claim, False)
            if not isinstance(value, bool):
                raise QualificationError(f"claim {claim} is not boolean")
            result |= value
    return result


def independent_approval(
    pr: dict[str, Any], reviews: list[dict[str, Any]], checks: list[dict[str, Any]],
    current_head: str, qualified_head: str, authors: set[str],
) -> str:
    current_head, qualified_head = exact_sha(current_head), exact_sha(qualified_head)
    if pr.get("draft") is not False or pr.get("head", {}).get("sha") != current_head:
        raise QualificationError("promotion requires a non-draft exact-head PR")
    author = pr.get("user", {}).get("login")
    if not author:
        raise QualificationError("missing PR author identity")
    authors = authors | {author}
    latest: dict[str, dict[str, Any]] = {}
    for review in sorted(reviews, key=lambda row: row.get("id", 0)):
        if review.get("state") == "PENDING":
            continue
        login = review.get("user", {}).get("login")
        if login:
            latest[login] = review
    approved = [login for login, review in latest.items()
                if login not in authors
                and review.get("user", {}).get("type") == "User"
                and review.get("author_association") in {"OWNER", "MEMBER", "COLLABORATOR"}
                and review.get("state") == "APPROVED"
                and review.get("commit_id") == current_head]
    if not approved:
        raise QualificationError("no current independent human approval")
    if any(review.get("state") == "CHANGES_REQUESTED" for review in latest.values()):
        raise QualificationError("an outstanding change request blocks promotion")
    newest: dict[str, dict[str, Any]] = {}
    for check in sorted(checks, key=lambda row: row.get("id", 0)):
        if check.get("head_sha") == qualified_head:
            newest[check.get("name", "")] = check
    for name in REQUIRED_CHECKS:
        check = newest.get(name, {})
        if check.get("status") != "completed" or check.get("conclusion") != "success":
            raise QualificationError(f"missing successful exact-source check: {name}")
        if check.get("app", {}).get("slug") != "github-actions":
            raise QualificationError(f"unexpected check issuer: {name}")
        if check.get("verified_workflow_path") != REQUIRED_CHECKS[name]:
            raise QualificationError(f"unexpected workflow for check: {name}")
        if check.get("verified_run_head") != qualified_head:
            raise QualificationError(f"workflow/source mismatch: {name}")
    for name, conclusion in SECURITY_CHECKS.items():
        check = newest.get(name, {})
        if check.get("status") != "completed" or check.get("conclusion") != conclusion:
            raise QualificationError(f"missing successful exact-source security check: {name}")
    return sorted(approved)[0]


def api_json(repository: str, suffix: str) -> Any:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise QualificationError("invalid repository identity")
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise QualificationError("live GitHub observations require a read-only token")
    request = Request(
        f"https://api.github.com/repos/{repository}/{suffix}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28"},
    )
    with urlopen(request, timeout=30) as response:
        data = response.read(4 * 1024 * 1024 + 1)
    if len(data) > 4 * 1024 * 1024:
        raise QualificationError("GitHub evidence response exceeds bound")
    return json.loads(data, object_pairs_hook=unique_object)


def promotion_guard(root: Path, head: str) -> dict[str, Any]:
    mapping = load_json(root / MAP)
    if not requested_claims(mapping):
        return {"productionClaimRequested": False, "productionPromotionAuthorized": False}
    for scope in (mapping, mapping.get("claimBoundary", {})):
        if scope.get("activation") or scope.get("release"):
            raise QualificationError("activation/release require the external release authority, not this source gate")
    event = load_json(Path(os.environ.get("GITHUB_EVENT_PATH", "")))
    pr_event = event.get("pull_request", {})
    evidence = mapping.get("qualificationEvidence", {})
    number = pr_event.get("number", evidence.get("promotionPullRequest"))
    if not isinstance(number, int) or number <= 0:
        raise QualificationError("production promotion requires a live reviewable PR identity")
    qualified = exact_sha(evidence.get("qualifiedSourceHead", ""))
    git(root, "merge-base", "--is-ancestor", qualified, head)
    declared = mapping["observedSourcePaths"]
    changed = git(root, "diff", "--name-only", qualified, head, "--", *declared)
    if any(path != MAP for path in changed.splitlines()):
        raise QualificationError("qualified source differs from promotion source")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    pr = api_json(repository, f"pulls/{number}")
    review_head = head
    if not pr_event:
        if pr.get("merged") is not True:
            raise QualificationError("main requires the recorded promotion PR to have merged")
        git(root, "merge-base", "--is-ancestor", exact_sha(pr.get("merge_commit_sha", "")), head)
        review_head = exact_sha(pr.get("head", {}).get("sha", ""))
    reviews, commits = [], []
    for resource, result in (("reviews", reviews), ("commits", commits)):
        for page in range(1, 11):
            batch = api_json(repository, f"pulls/{number}/{resource}?per_page=100&page={page}")
            result.extend(batch)
            if len(batch) < 100:
                break
        else:
            raise QualificationError("review/commit pagination limit exceeded")
    authors = {row.get(kind, {}).get("login") for row in commits
               for kind in ("author", "committer") if row.get(kind)}
    checks = []
    for page in range(1, 21):
        batch = api_json(repository, f"commits/{qualified}/check-runs?per_page=100&page={page}")
        checks.extend(batch.get("check_runs", []))
        if len(checks) >= batch.get("total_count", 0):
            break
    else:
        raise QualificationError("check inventory pagination limit exceeded")
    runs = {}
    for check in checks:
        if check.get("name") not in REQUIRED_CHECKS:
            continue
        pattern = rf"https://github\.com/{re.escape(repository)}/actions/runs/(\d+)/job/\d+"
        match = re.fullmatch(pattern, check.get("details_url", ""))
        if not match:
            raise QualificationError("check does not link to a repository workflow job")
        run_id = match.group(1)
        if run_id not in runs:
            runs[run_id] = api_json(repository, f"actions/runs/{run_id}")
        run = runs[run_id]
        check["verified_workflow_path"] = run.get("path")
        check["verified_run_head"] = run.get("head_sha")
    reviewer = independent_approval(pr, reviews, checks, review_head, qualified, authors)
    # This is a necessary PR/source gate, never a release or deployment grant.
    return {"productionClaimRequested": True, "independentReviewer": reviewer,
            "qualifiedSourceHead": qualified, "releaseAuthority": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("source", "promotion"))
    parser.add_argument("--head", required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = (source_observation(args.root, args.head) if args.command == "source"
                  else promotion_guard(args.root, exact_sha(args.head)))
        encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(encoded)
        else:
            print(encoded, end="")
    except (QualificationError, OSError, ValueError, KeyError, TypeError,
            subprocess.TimeoutExpired) as error:
        print(f"memory.retrieval qualification refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
