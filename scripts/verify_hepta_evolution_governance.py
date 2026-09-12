#!/usr/bin/env python3
"""Read-only, fail-closed observation of classic main-branch protection.

This is configuration evidence, not approval, ownership validation, a durable
attestation, or permission to activate self-evolution. Ruleset-only protection
requires separate equivalent-policy evidence; it is never silently accepted.
No administration credential should be exposed to an untrusted PR workflow.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

REQUIRED_CHECKS = ("qualification (source-head)", "qualification (base-merge)")
GITHUB_ACTIONS_APP_ID = 15368
MAX_RESPONSE_BYTES = 1024 * 1024


def mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def protection_gaps(branch: Any, protection: Any) -> list[str]:
    """Check API observations without treating missing/unknown fields as safe."""
    branch = mapping(branch)
    protection = mapping(protection)
    gaps = []
    if branch.get("name") != "main" or branch.get("protected") is not True:
        gaps.append("main_not_protected")
    for field, expected in (
        ("enforce_admins", True),
        ("required_conversation_resolution", True),
        ("allow_force_pushes", False),
        ("allow_deletions", False),
    ):
        if mapping(protection.get(field)).get("enabled") is not expected:
            gaps.append(f"invalid_{field}")
    reviews = mapping(protection.get("required_pull_request_reviews"))
    count = reviews.get("required_approving_review_count")
    if type(count) is not int or count < 1:
        gaps.append("independent_review_not_required")
    for field in (
        "dismiss_stale_reviews",
        "require_code_owner_reviews",
        "require_last_push_approval",
    ):
        if reviews.get(field) is not True:
            gaps.append(f"invalid_{field}")
    bypass = reviews.get("bypass_pull_request_allowances")
    if not isinstance(bypass, dict) or any(
        bypass.get(kind) != [] for kind in ("users", "teams", "apps")
    ):
        gaps.append("review_bypass_not_proven_disabled")
    status = mapping(protection.get("required_status_checks"))
    if status.get("strict") is not True:
        gaps.append("up_to_date_checks_not_required")
    checks = status.get("checks")
    if not isinstance(checks, list):
        checks = []
    for context in REQUIRED_CHECKS:
        matching = [mapping(check) for check in checks if mapping(check).get("context") == context]
        if len(matching) != 1 or matching[0].get("app_id") != GITHUB_ACTIONS_APP_ID:
            gaps.append(f"required_check_missing_or_unpinned:{context}")
    return gaps


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward an Authorization header to a redirect destination.
        return None


def read_json(url: str, token: str | None) -> dict[str, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2026-03-10",
        "User-Agent": "hepta-governance-observer",
        "Cache-Control": "no-cache",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    opener = urllib.request.build_opener(NoRedirect())
    with opener.open(request, timeout=15) as response:
        data = response.read(MAX_RESPONSE_BYTES + 1)
    if len(data) > MAX_RESPONSE_BYTES:
        raise ValueError("API response exceeds the observation limit")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("API observation is not an object")
    return value


def observe(repository: str, token: str | None) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", repository):
        raise ValueError("invalid repository identity")
    url = f"https://api.github.com/repos/{repository}/branches/main"
    branch = read_json(url, token)
    if branch.get("protected") is not True:
        gaps = ["main_not_protected"]
    else:
        gaps = protection_gaps(branch, read_json(f"{url}/protection", token))
    return {
        "schema": "hepta.branch-protection-observation.v1",
        "repository": repository,
        "branch": "main",
        "observedAt": datetime.now(timezone.utc).isoformat(),
        "status": "BLOCKED" if gaps else "CONFIGURATION_VERIFIED",
        "gaps": gaps,
        "scope": "classic_branch_protection_configuration_only",
        "productionAuthorized": False,
        "independentAcceptance": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default="TrillionniumFoundation/hepta-private-ci")
    args = parser.parse_args()
    try:
        result = observe(args.repository, os.environ.get("GITHUB_TOKEN"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        # HTTP status/type is sufficient. Do not log request headers or raw API
        # responses, which can expose credentials or unrelated administrative data.
        code = error.code if isinstance(error, urllib.error.HTTPError) else type(error).__name__
        result = {
            "schema": "hepta.branch-protection-observation.v1",
            "repository": args.repository,
            "status": "BLOCKED",
            "gaps": [f"configuration_unverifiable:{code}"],
            "productionAuthorized": False,
            "independentAcceptance": False,
        }
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "CONFIGURATION_VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
