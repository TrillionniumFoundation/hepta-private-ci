#!/usr/bin/env python3
"""Observe the strict classic-branch-protection profile for self-iteration.

This is NOT an activation token or proof of credential separation. The evaluator
App must be independently operated; its ID comes from administration-owned
configuration, never a value supplied by candidate code. No write API is used.
Ruleset-only protection is deliberately unsupported by this profile: it fails
closed rather than treating unrelated rulesets as effective branch protection.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from typing import Any

REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")
EVALUATION_CONTEXT = "hepta-independent-evaluation"


class ControlError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ControlError(message)


def positive_integer(value: Any) -> bool:
    return type(value) is int and value > 0


def required_checks(protection: dict[str, Any], evaluator_app: int) -> dict[str, int | None]:
    require(positive_integer(evaluator_app), "An independently provisioned evaluator App ID is required")
    require(protection.get("enforce_admins", {}).get("enabled") is True,
            "Branch protection does not enforce administrators")
    for key in ("allow_force_pushes", "allow_deletions"):
        require(protection.get(key, {}).get("enabled") is False, f"{key} is enabled or unknown")
    reviews = protection.get("required_pull_request_reviews")
    require(isinstance(reviews, dict), "Required independent review is missing")
    require(positive_integer(reviews.get("required_approving_review_count")), "No approving review is required")
    require(reviews.get("dismiss_stale_reviews") is True, "Stale reviews are not dismissed")
    require(reviews.get("require_last_push_approval") is True, "Last push need not have independent approval")
    bypass = reviews.get("bypass_pull_request_allowances", {})
    require(isinstance(bypass, dict), "Malformed review bypass allowances")
    for kind in ("users", "teams", "apps"):
        require(bypass.get(kind, []) == [], f"Review bypass {kind} are permitted")
    status = protection.get("required_status_checks")
    require(isinstance(status, dict) and status.get("strict") is True,
            "Required status checks are missing or permit a stale base")
    checks = status.get("checks", [])
    contexts = status.get("contexts", [])
    require(isinstance(checks, list) and isinstance(contexts, list), "Malformed required check registry")
    result: dict[str, int | None] = {}
    for check in checks:
        require(isinstance(check, dict), "Malformed required check")
        name, app_id = check.get("context"), check.get("app_id")
        require(isinstance(name, str) and bool(name), "Required check has no context")
        require(name not in result, "Duplicate required check context")
        require(app_id is None or app_id == -1 or positive_integer(app_id), "Invalid required check App ID")
        result[name] = app_id if positive_integer(app_id) else None
    for name in contexts:
        require(isinstance(name, str) and bool(name), "Malformed legacy check context")
        result.setdefault(name, None)
    require("blocking-ci" in result, "blocking-ci is not required by live protection")
    require(result.get(EVALUATION_CONTEXT) == evaluator_app,
            "Independent evaluation is not required from the exact trusted App")
    return result


def validate_observation(branch: dict[str, Any], protection: dict[str, Any],
                         checks: list[dict[str, Any]], *, expected_sha: str,
                         evaluator_app: int) -> list[int]:
    require(bool(SHA.fullmatch(expected_sha)), "Invalid expected main SHA")
    require(branch.get("name") == "main" and branch.get("protected") is True,
            "main is not protected")
    require(branch.get("commit", {}).get("sha") == expected_sha, "main changed or differs from this workflow")
    required = required_checks(protection, evaluator_app)
    accepted: list[int] = []
    for context, app_id in required.items():
        matching = []
        for check in checks:
            require(isinstance(check, dict), "Malformed check run")
            if check.get("name") != context or check.get("head_sha") != expected_sha:
                continue
            observed_app = check.get("app", {})
            require(isinstance(observed_app, dict), "Check source App is unknown")
            if app_id is not None and observed_app.get("id") != app_id:
                continue
            require(positive_integer(check.get("id")), "Check identity is missing")
            matching.append(check)
        require(bool(matching), f"No exact-head check from the required source: {context}")
        # A newer pending, cancelled, skipped or failed run invalidates an older
        # success. Never select a successful historical run just to turn green.
        latest = max(matching, key=lambda value: value["id"])
        require(latest.get("status") == "completed" and latest.get("conclusion") == "success",
                f"Required check did not complete successfully: {context}")
        if context == EVALUATION_CONTEXT:
            require(latest["app"].get("slug") not in (None, "", "github-actions"),
                    "Repository Actions is not an independent evaluator identity")
        accepted.append(latest["id"])
    return accepted


def api(path: str) -> Any:
    result = subprocess.run(["gh", "api", "--method", "GET", path], check=True,
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return json.loads(result.stdout)


def collect_checks(repository: str, sha: str) -> list[dict[str, Any]]:
    result = []
    for page in range(1, 101):
        response = api(f"repos/{repository}/commits/{sha}/check-runs?filter=all&per_page=100&page={page}")
        require(isinstance(response, dict) and isinstance(response.get("check_runs"), list),
                "Cannot observe check runs")
        items = response["check_runs"]
        result.extend(items)
        if len(items) < 100:
            return result
    raise ControlError("Check pagination exceeded the observation bound; no truncated success is allowed")


def observe(repository: str, expected_sha: str, evaluator_app: int) -> dict[str, Any]:
    require(bool(REPOSITORY.fullmatch(repository))
            and all(part not in (".", "..") for part in repository.split("/")), "Invalid repository")
    require(bool(SHA.fullmatch(expected_sha)), "Invalid expected SHA")
    require(positive_integer(evaluator_app), "Missing indepently provisioned evaluator App ID")
    branch_path = f"repos/{repository}/branches/main"
    protection_path = branch_path + "/protection"
    before = api(branch_path)
    protection = api(protection_path)  # 403/404 is an error, never a default policy.
    require(isinstance(before, dict) and isinstance(protection, dict), "Incomplete repository observation")
    # Validate policy before asking for potentially many check records.
    required_checks(protection, evaluator_app)
    accepted = validate_observation(before, protection, collect_checks(repository, expected_sha),
                                    expected_sha=expected_sha, evaluator_app=evaluator_app)
    after, current_protection = api(branch_path), api(protection_path)
    require(isinstance(after, dict) and after.get("commit", {}).get("sha") == expected_sha
            and after.get("protected") is True, "main moved during the observation")
    require(protection == current_protection, "Protection changed during the observation")
    return {"repository": repository, "source_sha": expected_sha,
            "check_run_ids": accepted, "repository_control_profile_passed": True,
            "activation_authorized": False,
            "scope": "read-only observation; independent credential isolation is not established here"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args()
    try:
        app_id = int(os.environ.get("HEPTA_EVALUATOR_APP_ID", "0"))
        print(json.dumps(observe(args.repo, args.expected_sha, app_id), sort_keys=True))
        return 0
    except (ControlError, TypeError, AttributeError, ValueError, KeyError, OSError,
            subprocess.CalledProcessError) as error:
        print(f"FAIL_HEPTA_REPOSITORY_CONTROLS: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
