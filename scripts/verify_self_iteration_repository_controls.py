#!/usr/bin/env python3
"""Verify repository administration before any source self-iteration activation.

This is intentionally an activation-only check. Ordinary source development does
not require repository-administration receipts. Autonomous source candidate
promotion does: a protected canonical branch, independent approval, required
status checks, and force-push/deletion denial must be observable from GitHub.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

REPO = os.environ.get("GITHUB_REPOSITORY", "TrillionniumFoundation/hepta-private-ci")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
BRANCH = os.environ.get("HEPTA_CANONICAL_BRANCH", "main")
API = f"https://api.github.com/repos/{REPO}"


def fail(message: str) -> None:
    raise SystemExit("FAIL_SELF_ITERATION_REPOSITORY_CONTROLS: " + message)


def get(path: str):
    request = urllib.request.Request(
        API + path,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            **({"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        body = error.read(512).decode("utf-8", errors="replace")
        fail(f"cannot verify {path}: HTTP {error.code}: {body}")
    except Exception as error:
        fail(f"cannot verify {path}: {error}")


def main() -> int:
    repo = get("")
    if repo.get("default_branch") != BRANCH:
        fail(f"default branch is {repo.get('default_branch')!r}, expected {BRANCH!r}")

    branch = get(f"/branches/{BRANCH}")
    if branch.get("protected") is not True:
        fail(f"canonical branch {BRANCH!r} is not protected")

    # The protection endpoint requires repository administration visibility.
    # If the activation identity cannot observe it, activation is denied rather
    # than guessing that a UI/ruleset is sufficient.
    protection = get(f"/branches/{BRANCH}/protection")
    reviews = protection.get("required_pull_request_reviews") or {}
    if int(reviews.get("required_approving_review_count") or 0) < 1:
        fail("at least one independent approving review is required")

    checks = protection.get("required_status_checks") or {}
    contexts = checks.get("contexts") or []
    app_checks = checks.get("checks") or []
    if not contexts and not app_checks:
        fail("canonical branch has no required status checks")

    if protection.get("allow_force_pushes", {}).get("enabled") is True:
        fail("force pushes are enabled on the canonical branch")
    if protection.get("allow_deletions", {}).get("enabled") is True:
        fail("canonical branch deletion is enabled")

    restrictions = protection.get("restrictions")
    if restrictions is None:
        # Admin bypass policy may instead be provided by an organization
        # ruleset. Require that to be observable; do not infer it.
        rulesets = get("/rulesets?includes_parents=true")
        active = [row for row in rulesets if row.get("enforcement") == "active"]
        if not active:
            fail("no active repository/organization ruleset is observable for bypass control")

    print(json.dumps({
        "status": "PASS_SELF_ITERATION_REPOSITORY_CONTROLS",
        "repository": REPO,
        "canonicalBranch": BRANCH,
        "protected": True,
        "requiredApprovingReviews": reviews.get("required_approving_review_count"),
        "requiredChecks": sorted(
            set(contexts)
            | {row.get("context") for row in app_checks if row.get("context")}
        ),
        "forcePush": False,
        "deletion": False,
        "activationAuthorityGranted": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
