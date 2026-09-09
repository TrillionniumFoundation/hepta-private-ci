#!/usr/bin/env python3
"""Fail-closed live audit for the Hepta single-main convergence transaction.

The audit is intentionally read-only.  It grants no merge, ref deletion,
release, deployment, external-evidence, or production authority.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPOSITORY = os.environ.get(
    "GITHUB_REPOSITORY", "TrillionniumFoundation/hepta-private-ci"
)
TOKEN = os.environ.get("GITHUB_TOKEN", "")
PR_NUMBER = int(os.environ.get("HEPTA_PR_NUMBER", "480"))
CONTROLLER_BRANCH = os.environ.get(
    "HEPTA_CONTROLLER_BRANCH", "ops/hepta-final-convergence-controller-20260909-r1"
)
OUT = Path(os.environ.get("HEPTA_AUDIT_OUT", "hepta-final-convergence-audit"))
FAIL_CONCLUSIONS = {
    "action_required",
    "cancelled",
    "failure",
    "neutral",
    "skipped",
    "stale",
    "startup_failure",
    "timed_out",
}
AUTHORITY_FALSE_KEYS = re.compile(
    r"(?:all.*(?:closed|passed|ready)|(?:semantic|independent|external|operator|"
    r"production|release|deployment|hardware|device|long.?term|future|product)"
    r".*(?:passed|proved|ready|accepted|closed))$",
    re.IGNORECASE,
)
OPEN_STATUS = re.compile(
    r"(?:^|[-_])(open|pending|blocked|incomplete|unproved|unverified|not[-_])",
    re.IGNORECASE,
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def parse_time(value: str | None) -> dt.datetime:
    if not value:
        return dt.datetime.min.replace(tzinfo=dt.timezone.utc)
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def api(
    path: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    allow_status: set[int] | None = None,
) -> tuple[int, Any, dict[str, str]]:
    if not TOKEN:
        raise SystemExit("GITHUB_TOKEN is required")
    url = path if path.startswith("https://") else f"https://api.github.com{path}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        method=method,
        data=data,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {TOKEN}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "hepta-final-convergence-audit-v1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read()
            payload = json.loads(raw) if raw else None
            return response.status, payload, dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = raw.decode("utf-8", errors="replace")
        if allow_status and exc.code in allow_status:
            return exc.code, payload, dict(exc.headers.items())
        raise RuntimeError(f"GitHub API {method} {url} failed: {exc.code}: {payload}") from exc


def api_pages(path: str, key: str | None = None) -> list[Any]:
    separator = "&" if "?" in path else "?"
    page = 1
    result: list[Any] = []
    while True:
        _, payload, _ = api(f"{path}{separator}per_page=100&page={page}")
        batch = payload[key] if key else payload
        if not isinstance(batch, list):
            raise RuntimeError(f"expected list from {path}, got {type(batch).__name__}")
        result.extend(batch)
        if len(batch) < 100:
            return result
        page += 1
        if page > 100:
            raise RuntimeError(f"pagination exceeded 10,000 records for {path}")


def git(*args: str, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and completed.returncode:
        raise RuntimeError(
            f"git {' '.join(args)} failed ({completed.returncode}): "
            f"{completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def is_ancestor(left: str, right: str) -> bool:
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", left, right],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0


def latest_by(items: list[dict[str, Any]], key_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    selected: dict[tuple[Any, ...], dict[str, Any]] = {}
    for item in items:
        key = tuple(item.get(field) for field in key_fields)
        old = selected.get(key)
        marker = (
            parse_time(item.get("completed_at") or item.get("updated_at") or item.get("created_at")),
            int(item.get("run_attempt") or 0),
            int(item.get("id") or 0),
        )
        old_marker = (
            parse_time(old.get("completed_at") or old.get("updated_at") or old.get("created_at")),
            int(old.get("run_attempt") or 0),
            int(old.get("id") or 0),
        ) if old else None
        if old is None or marker > old_marker:
            selected[key] = item
    return sorted(selected.values(), key=lambda value: tuple(str(value.get(f)) for f in key_fields))


def collect_checks(sha: str) -> dict[str, Any]:
    checks = api_pages(
        f"/repos/{REPOSITORY}/commits/{sha}/check-runs?filter=all",
        key="check_runs",
    )
    statuses = api_pages(f"/repos/{REPOSITORY}/commits/{sha}/statuses")
    workflows = api_pages(f"/repos/{REPOSITORY}/actions/runs?head_sha={sha}", key="workflow_runs")

    latest_checks = latest_by(checks, ("name",))
    latest_statuses = latest_by(statuses, ("context",))
    latest_workflows = latest_by(workflows, ("name", "event"))

    nonterminal: list[dict[str, Any]] = []
    unsuccessful: list[dict[str, Any]] = []
    for item in latest_checks:
        record = {
            "kind": "check_run",
            "name": item.get("name"),
            "status": item.get("status"),
            "conclusion": item.get("conclusion"),
            "id": item.get("id"),
            "app": (item.get("app") or {}).get("slug"),
        }
        if item.get("status") != "completed":
            nonterminal.append(record)
        elif item.get("conclusion") != "success":
            unsuccessful.append(record)
    for item in latest_statuses:
        record = {
            "kind": "commit_status",
            "name": item.get("context"),
            "status": item.get("state"),
            "conclusion": item.get("state"),
            "id": item.get("id"),
            "app": (item.get("creator") or {}).get("login"),
        }
        if item.get("state") == "pending":
            nonterminal.append(record)
        elif item.get("state") != "success":
            unsuccessful.append(record)
    for item in latest_workflows:
        record = {
            "kind": "workflow_run",
            "name": item.get("name"),
            "event": item.get("event"),
            "status": item.get("status"),
            "conclusion": item.get("conclusion"),
            "id": item.get("id"),
        }
        if item.get("status") != "completed":
            nonterminal.append(record)
        elif item.get("conclusion") != "success":
            unsuccessful.append(record)

    return {
        "sha": sha,
        "latestChecks": latest_checks,
        "latestStatuses": latest_statuses,
        "latestWorkflowRuns": latest_workflows,
        "nonterminal": nonterminal,
        "unsuccessful": unsuccessful,
    }


def protection_for(branch: str) -> tuple[dict[str, Any] | None, str | None]:
    quoted = urllib.parse.quote(branch, safe="")
    status, payload, _ = api(
        f"/repos/{REPOSITORY}/branches/{quoted}/protection",
        allow_status={403, 404},
    )
    if status != 200:
        return None, f"branch protection unreadable for {branch}: HTTP {status}: {payload}"
    return payload, None


def required_check_names(protection: dict[str, Any] | None) -> set[str]:
    if not protection:
        return set()
    required = protection.get("required_status_checks") or {}
    names = set(required.get("contexts") or [])
    names.update(
        item.get("context")
        for item in required.get("checks") or []
        if item.get("context")
    )
    return names


def present_success_names(check_packet: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for item in check_packet["latestChecks"]:
        if item.get("status") == "completed" and item.get("conclusion") == "success":
            names.add(str(item.get("name")))
    for item in check_packet["latestStatuses"]:
        if item.get("state") == "success":
            names.add(str(item.get("context")))
    return names


def review_threads() -> tuple[list[dict[str, Any]], str | None]:
    query = """
    query($owner:String!, $name:String!, $number:Int!, $cursor:String) {
      repository(owner:$owner, name:$name) {
        pullRequest(number:$number) {
          reviewThreads(first:100, after:$cursor) {
            nodes { isResolved isOutdated }
            pageInfo { hasNextPage endCursor }
          }
        }
      }
    }
    """
    owner, name = REPOSITORY.split("/", 1)
    cursor: str | None = None
    nodes: list[dict[str, Any]] = []
    while True:
        status, payload, _ = api(
            "https://api.github.com/graphql",
            method="POST",
            body={
                "query": query,
                "variables": {"owner": owner, "name": name, "number": PR_NUMBER, "cursor": cursor},
            },
            allow_status={403},
        )
        if status != 200 or payload.get("errors"):
            return nodes, f"review-thread GraphQL unavailable: HTTP {status}: {payload}"
        connection = payload["data"]["repository"]["pullRequest"]["reviewThreads"]
        nodes.extend(connection["nodes"])
        if not connection["pageInfo"]["hasNextPage"]:
            return nodes, None
        cursor = connection["pageInfo"]["endCursor"]


def evaluate_reviews(
    pr: dict[str, Any], protection: dict[str, Any] | None, head_commit: dict[str, Any]
) -> dict[str, Any]:
    reviews = api_pages(f"/repos/{REPOSITORY}/pulls/{PR_NUMBER}/reviews")
    latest: dict[str, dict[str, Any]] = {}
    for review in reviews:
        login = ((review.get("user") or {}).get("login") or "").lower()
        if not login:
            continue
        old = latest.get(login)
        if old is None or parse_time(review.get("submitted_at")) > parse_time(old.get("submitted_at")):
            latest[login] = review

    author = ((pr.get("user") or {}).get("login") or "").lower()
    head_time = parse_time(((head_commit.get("commit") or {}).get("committer") or {}).get("date"))
    approvals: list[dict[str, Any]] = []
    blocking: list[dict[str, Any]] = []
    for login, review in latest.items():
        state = review.get("state")
        submitted = parse_time(review.get("submitted_at"))
        if state == "CHANGES_REQUESTED":
            blocking.append({"reviewer": login, "submittedAt": review.get("submitted_at")})
        if (
            state == "APPROVED"
            and login != author
            and not login.endswith("[bot]")
            and submitted >= head_time
            and review.get("commit_id") in (None, pr["head"]["sha"])
        ):
            approvals.append({"reviewer": login, "submittedAt": review.get("submitted_at")})

    required = 1
    review_rule = (protection or {}).get("required_pull_request_reviews") or {}
    required = max(required, int(review_rule.get("required_approving_review_count") or 0))
    threads, thread_error = review_threads()
    unresolved = [item for item in threads if not item.get("isResolved") and not item.get("isOutdated")]
    return {
        "requiredApprovalCount": required,
        "eligibleApprovals": approvals,
        "latestBlockingReviews": blocking,
        "reviewThreads": threads,
        "unresolvedThreadCount": len(unresolved),
        "threadReadError": thread_error,
    }


def json_at(commit: str, path: str) -> Any:
    raw = git("show", f"{commit}:{path}")
    return json.loads(raw)


def walk_authority(value: Any, path: str, findings: list[dict[str, Any]]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            if isinstance(child, bool) and child is False and AUTHORITY_FALSE_KEYS.search(key):
                findings.append({"jsonPath": child_path, "value": False, "reason": "authority/readiness flag is false"})
            elif isinstance(child, str) and key.lower().endswith("status") and OPEN_STATUS.search(child):
                findings.append({"jsonPath": child_path, "value": child, "reason": "status remains open/pending/blocked"})
            walk_authority(child, child_path, findings)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            walk_authority(child, f"{path}[{index}]", findings)


def readiness_findings(head: str) -> dict[str, Any]:
    paths = git("ls-tree", "-r", "--name-only", head).splitlines()
    candidates = [
        path for path in paths
        if path.endswith(".json")
        and (
            path.startswith("qualification/")
            or "readiness" in path.lower()
            or "detail_gap" in path.lower()
            or "native_binding" in path.lower()
        )
    ]
    files: list[dict[str, Any]] = []
    for path in sorted(candidates):
        try:
            payload = json_at(head, path)
        except (json.JSONDecodeError, RuntimeError):
            continue
        findings: list[dict[str, Any]] = []
        walk_authority(payload, "", findings)
        if findings:
            files.append({"path": path, "findings": findings[:500], "truncated": len(findings) > 500})
    return {
        "filesInspected": len(candidates),
        "filesWithOpenAuthorityFacts": files,
        "openAuthorityFindingCount": sum(len(item["findings"]) for item in files),
    }


def ephemeral_path(branch: str, path: str) -> bool:
    branch_kind = branch.split("/", 1)[0]
    if branch == CONTROLLER_BRANCH and path in {
        ".github/scripts/hepta_final_convergence_audit.py",
        ".github/workflows/hepta-final-convergence-audit.yml",
    }:
        return True
    if path == "micro_patch.diff" or path.startswith("tmp/"):
        return True
    if branch_kind in {"ops", "backup", "diagnostic", "audit", "qualification"}:
        if path.startswith(".github/workflows/") or path.startswith(".github/scripts/"):
            return True
    return False


def branch_inventory(head: str, head_ref: str) -> dict[str, Any]:
    git("fetch", "--force", "--no-tags", "origin", "+refs/heads/*:refs/remotes/origin/*")
    raw = git("ls-remote", "--heads", "origin")
    refs: list[tuple[str, str]] = []
    for line in raw.splitlines():
        sha, ref = line.split("\t", 1)
        refs.append((ref.removeprefix("refs/heads/"), sha))
    refs.sort()

    records: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    canonical_tree = git("rev-parse", f"{head}^{{tree}}")
    for branch, tip in refs:
        tree = git("rev-parse", f"{tip}^{{tree}}")
        if tip == head:
            disposition = "canonical-head"
            unique_patch_count = 0
            changed: list[str] = []
        elif is_ancestor(tip, head):
            disposition = "history-reachable"
            unique_patch_count = 0
            changed = []
        elif tree == canonical_tree:
            disposition = "canonical-tree-equivalent"
            unique_patch_count = 0
            changed = []
        else:
            cherry = git("rev-list", "--left-right", "--cherry-pick", "--no-merges", f"{head}...{tip}", check=False)
            unique_patch_count = sum(line.startswith(">") for line in cherry.splitlines())
            merge_base = git("merge-base", head, tip, check=False)
            changed = git("diff", "--name-only", "--no-renames", merge_base or tip, tip, check=False).splitlines()
            if unique_patch_count == 0:
                disposition = "patch-equivalent"
            elif changed and all(ephemeral_path(branch, path) for path in changed):
                disposition = "ephemeral-controller-only"
            else:
                disposition = "unresolved-unique-content"
        record = {
            "branch": branch,
            "tip": tip,
            "tree": tree,
            "disposition": disposition,
            "uniquePatchCount": unique_patch_count,
            "changedPathCount": len(changed),
            "changedPathSample": changed[:100],
        }
        records.append(record)
        if disposition == "unresolved-unique-content":
            unresolved.append(record)
    return {
        "branchCount": len(records),
        "canonicalHeadRef": head_ref,
        "records": records,
        "unresolvedBranches": unresolved,
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    blockers: list[dict[str, Any]] = []
    observed_at = utc_now()

    _, repo, _ = api(f"/repos/{REPOSITORY}")
    _, pr, _ = api(f"/repos/{REPOSITORY}/pulls/{PR_NUMBER}")
    if pr.get("state") != "open":
        blockers.append({"class": "pr", "reason": f"PR #{PR_NUMBER} is not open"})
    base_ref = pr["base"]["ref"]
    base_sha = pr["base"]["sha"]
    head_ref = pr["head"]["ref"]
    head_sha = pr["head"]["sha"]
    merge_sha = pr.get("merge_commit_sha")

    git("fetch", "--force", "--no-tags", "origin", f"+refs/heads/{head_ref}:refs/remotes/origin/{head_ref}")
    remote_head = git("rev-parse", f"refs/remotes/origin/{head_ref}")
    if remote_head != head_sha:
        blockers.append({"class": "identity", "reason": "PR head differs from remote branch", "prHead": head_sha, "remoteHead": remote_head})

    _, head_commit, _ = api(f"/repos/{REPOSITORY}/commits/{head_sha}")
    protection, protection_error = protection_for(base_ref)
    if protection_error:
        blockers.append({"class": "administration", "reason": protection_error})

    head_checks = collect_checks(head_sha)
    for item in head_checks["nonterminal"]:
        blockers.append({"class": "head-check", "reason": "nonterminal", "detail": item})
    for item in head_checks["unsuccessful"]:
        blockers.append({"class": "head-check", "reason": "not successful", "detail": item})

    merge_checks = None
    if not merge_sha:
        blockers.append({"class": "identity", "reason": "GitHub prospective merge SHA is absent"})
    else:
        merge_checks = collect_checks(merge_sha)
        for item in merge_checks["nonterminal"]:
            blockers.append({"class": "merge-check", "reason": "nonterminal", "detail": item})
        for item in merge_checks["unsuccessful"]:
            blockers.append({"class": "merge-check", "reason": "not successful", "detail": item})

    required = required_check_names(protection)
    if protection is not None and not required:
        blockers.append({"class": "administration", "reason": "base protection exposes no required checks"})
    missing_required_head = sorted(required - present_success_names(head_checks))
    if missing_required_head:
        blockers.append({"class": "head-check", "reason": "required contexts missing or unsuccessful", "contexts": missing_required_head})
    if merge_checks is not None:
        missing_required_merge = sorted(required - present_success_names(merge_checks))
        if missing_required_merge:
            blockers.append({"class": "merge-check", "reason": "required contexts missing or unsuccessful", "contexts": missing_required_merge})

    reviews = evaluate_reviews(pr, protection, head_commit)
    if reviews["threadReadError"]:
        blockers.append({"class": "review", "reason": reviews["threadReadError"]})
    if reviews["unresolvedThreadCount"]:
        blockers.append({"class": "review", "reason": "unresolved review threads", "count": reviews["unresolvedThreadCount"]})
    if reviews["latestBlockingReviews"]:
        blockers.append({"class": "review", "reason": "current blocking review decisions remain", "reviews": reviews["latestBlockingReviews"]})
    if len(reviews["eligibleApprovals"]) < reviews["requiredApprovalCount"]:
        blockers.append({"class": "review", "reason": "insufficient fresh eligible approvals", "required": reviews["requiredApprovalCount"], "observed": len(reviews["eligibleApprovals"])})

    readiness = readiness_findings(head_sha)
    if readiness["openAuthorityFindingCount"]:
        blockers.append({"class": "readiness", "reason": "authoritative qualification files still contain false/open facts", "count": readiness["openAuthorityFindingCount"]})

    branches = branch_inventory(head_sha, head_ref)
    if branches["unresolvedBranches"]:
        blockers.append({"class": "branches", "reason": "branches with unresolved unique content remain", "count": len(branches["unresolvedBranches"]), "branches": [item["branch"] for item in branches["unresolvedBranches"][:100]]})

    packet = {
        "schema": "hepta-final-convergence-audit-v1",
        "repository": REPOSITORY,
        "observedAt": observed_at,
        "repositoryDefaultBranch": repo.get("default_branch"),
        "pullRequest": {
            "number": PR_NUMBER,
            "state": pr.get("state"),
            "draft": pr.get("draft"),
            "mergeable": pr.get("mergeable"),
            "mergeableState": pr.get("mergeable_state"),
            "baseRef": base_ref,
            "baseSha": base_sha,
            "headRef": head_ref,
            "headSha": head_sha,
            "headTree": git("rev-parse", f"{head_sha}^{{tree}}"),
            "prospectiveMergeSha": merge_sha,
        },
        "protection": protection,
        "headChecks": head_checks,
        "mergeChecks": merge_checks,
        "reviews": reviews,
        "readiness": readiness,
        "branches": branches,
        "blockerCount": len(blockers),
        "blockerCounts": dict(sorted(Counter(item["class"] for item in blockers).items())),
        "blockers": blockers,
        "eligibleForConvergenceStaging": not blockers,
        "mergeAuthorized": False,
        "branchDeletionAuthorized": False,
        "authorityBoundary": (
            "Read-only audit. A successful result permits creation of a separately reviewed "
            "history-convergence candidate only; it does not itself merge or delete refs."
        ),
    }
    (OUT / "audit.json").write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Hepta final convergence audit",
        "",
        f"- Observed: `{observed_at}`",
        f"- Repository: `{REPOSITORY}`",
        f"- PR: `#{PR_NUMBER}`",
        f"- Base: `{base_ref}@{base_sha}`",
        f"- Head: `{head_ref}@{head_sha}`",
        f"- Prospective merge: `{merge_sha}`",
        f"- Branches: `{branches['branchCount']}`",
        f"- Unresolved branches: `{len(branches['unresolvedBranches'])}`",
        f"- Open readiness facts: `{readiness['openAuthorityFindingCount']}`",
        f"- Eligible approvals: `{len(reviews['eligibleApprovals'])}/{reviews['requiredApprovalCount']}`",
        f"- Blockers: `{len(blockers)}`",
        f"- Eligible for convergence staging: `{str(not blockers).lower()}`",
        "",
        "## Blockers",
        "",
    ]
    if blockers:
        for index, blocker in enumerate(blockers, 1):
            lines.append(f"{index}. `{blocker['class']}` — {blocker['reason']}")
    else:
        lines.append("None. A separate reviewed staging transaction may now be created.")
    (OUT / "audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    subprocess.run(
        ["sha256sum", "audit.json", "audit.md"],
        cwd=OUT,
        check=True,
        stdout=(OUT / "SHA256SUMS").open("w", encoding="utf-8"),
    )
    print(json.dumps({
        "head": head_sha,
        "merge": merge_sha,
        "branches": branches["branchCount"],
        "unresolvedBranches": len(branches["unresolvedBranches"]),
        "openReadinessFacts": readiness["openAuthorityFindingCount"],
        "approvals": len(reviews["eligibleApprovals"]),
        "requiredApprovals": reviews["requiredApprovalCount"],
        "blockers": len(blockers),
        "eligibleForConvergenceStaging": not blockers,
    }, sort_keys=True))
    return 0 if not blockers else 1


if __name__ == "__main__":
    sys.exit(main())
