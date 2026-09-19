#!/usr/bin/env python3
"""Install a no-bypass, independently reviewed main ruleset after a real green gate.

Adapted from #912 for #774's existing always-reporting blocking-ci workflow.
Uses the operator's authenticated gh CLI. Default mode is read-only; no policy
is inferred from a local test, a PR's historical result, or a generated receipt.
Existing rules are never replaced or weakened. Administrator credentials must
never be supplied to a candidate workflow to run this operator-only command.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
RULESET_NAME = "Hepta owner-operated main baseline"
GATE = "CI required"
WORKFLOW = "blocking-ci.yml"


class ProtectionError(RuntimeError):
    pass


class API:
    def call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        command = ["gh", "api", "--method", method,
                   "-H", "Accept: application/vnd.github+json",
                   "-H", "X-GitHub-Api-Version: 2022-11-28",
                   f"repos/{REPOSITORY}/{path}"]
        if body is not None:
            command.extend(["--input", "-"])
        environment = dict(os.environ, GH_PROMPT_DISABLED="1")
        environment.pop("GH_DEBUG", None)
        try:
            result = subprocess.run(
                command, input=None if body is None else json.dumps(body),
                text=True, capture_output=True, check=False, env=environment, timeout=60,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProtectionError(
                f"GitHub {method} timed out; a write may have applied: inspect live policy before retry"
            ) from exc
        if result.returncode:
            raise ProtectionError(f"GitHub {method} {path} failed: {result.stderr.strip()}")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ProtectionError("GitHub returned invalid JSON") from exc

    def pages(self, path: str, key: str | None = None) -> list[dict[str, Any]]:
        output = []
        separator = "&" if "?" in path else "?"
        for page in range(1, 101):
            value = self.call("GET", f"{path}{separator}per_page=100&page={page}")
            rows = value[key] if key else value
            if not isinstance(rows, list):
                raise ProtectionError("unexpected paginated response")
            output.extend(rows)
            if len(rows) < 100:
                return output
        raise ProtectionError("pagination limit reached; no incomplete policy read accepted")


def desired_ruleset(app_id: int) -> dict[str, Any]:
    if type(app_id) is not int or app_id <= 0:
        raise ProtectionError("a verified GitHub Actions integration ID is required")
    return {
        "name": RULESET_NAME, "target": "branch", "enforcement": "active",
        "bypass_actors": [],
        "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
        "rules": [
            {"type": "deletion"}, {"type": "non_fast_forward"},
            {"type": "pull_request", "parameters": {
                "dismiss_stale_reviews_on_push": True,
                "require_code_owner_review": True,
                "require_last_push_approval": True,
                "required_approving_review_count": 1,
                "required_review_thread_resolution": True,
            }},
            {"type": "required_status_checks", "parameters": {
                "required_status_checks": [{"context": GATE, "integration_id": app_id}],
                "strict_required_status_checks_policy": True,
                "do_not_enforce_on_create": False,
            }},
        ],
    }


def verify_ruleset(value: dict[str, Any], app_id: int) -> None:
    if value.get("target") != "branch" or value.get("enforcement") != "active":
        raise ProtectionError("ruleset is not an active branch policy")
    if value.get("bypass_actors") != []:
        raise ProtectionError("ruleset has bypass actors or bypass visibility is unavailable")
    if value.get("conditions") != desired_ruleset(app_id)["conditions"]:
        raise ProtectionError("ruleset does not exactly target main")
    rows = value.get("rules", [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ProtectionError("malformed rules")
    rules = {row.get("type"): row for row in rows}
    if len(rules) != len(rows):
        raise ProtectionError("duplicate rule types are ambiguous")
    if not {"deletion", "non_fast_forward", "pull_request", "required_status_checks"} <= rules.keys():
        raise ProtectionError("missing required protection")
    review = rules["pull_request"].get("parameters", {})
    count = review.get("required_approving_review_count")
    if type(count) is not int or count < 1:
        raise ProtectionError("at least one independent approval is required")
    for field in ("dismiss_stale_reviews_on_push", "require_code_owner_review",
                  "require_last_push_approval", "required_review_thread_resolution"):
        if review.get(field) is not True:
            raise ProtectionError(f"missing independent-review control: {field}")
    checks = rules["required_status_checks"].get("parameters", {})
    if checks.get("strict_required_status_checks_policy") is not True:
        raise ProtectionError("checks do not require an up-to-date base")
    if checks.get("do_not_enforce_on_create", False) is not False:
        raise ProtectionError("creation bypasses required checks")
    if {"context": GATE, "integration_id": app_id} not in checks.get("required_status_checks", []):
        raise ProtectionError("required check is not bound to the verified Actions app")


def verified_gate_app(checks: list[dict[str, Any]], runs: list[dict[str, Any]], head: str) -> int:
    matches = [row for row in checks if row.get("name") == GATE and row.get("head_sha") == head
               and row.get("app", {}).get("slug") == "github-actions"]
    if not matches:
        raise ProtectionError("no real Actions blocking gate exists on the exact main head")
    latest = max(matches, key=lambda row: row.get("id", 0))
    if latest.get("status") != "completed" or latest.get("conclusion") != "success":
        raise ProtectionError("latest exact-head gate is not completed successfully")
    suite = latest.get("check_suite", {}).get("id")
    if type(suite) is not int or suite <= 0:
        raise ProtectionError("gate has no verifiable check-suite identity")
    trusted_runs = [run for run in runs if run.get("head_sha") == head
                    and run.get("check_suite_id") == suite
                    and run.get("status") == "completed" and run.get("conclusion") == "success"
                    and run.get("path", "").split("@")[0] == ".github/workflows/" + WORKFLOW]
    if not trusted_runs:
        raise ProtectionError("gate is not backed by this workflow's successful exact-head run")
    app_id = latest["app"].get("id")
    desired_ruleset(app_id)
    return app_id


def snapshot(api: API) -> dict[str, Any]:
    branch = api.call("GET", "branches/main")
    rulesets = api.pages("rulesets?includes_parents=true")
    named = [row for row in rulesets if row.get("name") == RULESET_NAME]
    if len(named) > 1:
        raise ProtectionError("multiple named baseline rulesets; refusing to guess")
    detail = api.call("GET", f"rulesets/{named[0]['id']}") if named else None
    return {"main_head": branch["commit"]["sha"], "rulesets": rulesets, "named_ruleset": detail}


def write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def execute(api: API, expected_head: str, audit: Path, apply: bool) -> dict[str, Any]:
    before = snapshot(api)
    write_json(audit / "before.json", before)
    if before["main_head"] != expected_head:
        raise ProtectionError("main moved: no policy mutation performed")
    checks = api.pages(f"commits/{expected_head}/check-runs?filter=latest", "check_runs")
    runs = api.pages(f"actions/workflows/{WORKFLOW}/runs?head_sha={expected_head}", "workflow_runs")
    app_id = verified_gate_app(checks, runs, expected_head)
    desired = desired_ruleset(app_id)
    write_json(audit / "proposed.json", desired)
    # Dry-run must also reject an existing weaker named policy, not imply that
    # apply would succeed when it will deliberately refuse to replace it.
    if before["named_ruleset"] is not None:
        verify_ruleset(before["named_ruleset"], app_id)
    if not apply:
        return {"mode": "read-only", "main_head": expected_head,
                "would_create": before["named_ruleset"] is None}
    if snapshot(api) != before:
        raise ProtectionError("repository state changed during preflight; no mutation performed")
    if before["named_ruleset"] is None:
        created = api.call("POST", "rulesets", desired)
        write_json(audit / "write-response.json", created)
    after = snapshot(api)
    write_json(audit / "after.json", after)
    if after["named_ruleset"] is None:
        raise ProtectionError("write has no readable matching ruleset; do not claim enforcement")
    verify_ruleset(after["named_ruleset"], app_id)
    if after["main_head"] != expected_head:
        raise ProtectionError("policy may have been installed, but main changed during mutation; inspect after.json")
    return {"mode": "applied-and-read-back", "main_head": expected_head,
            "ruleset_id": after["named_ruleset"]["id"], "gate": GATE, "integration_id": app_id}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--audit-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.expected_head):
        parser.error("expected-head must be an exact GitHub commit SHA")
    args.audit_dir.mkdir(parents=True, exist_ok=False)
    try:
        result = execute(API(), args.expected_head, args.audit_dir, args.apply)
        result["observed_at"] = datetime.now(timezone.utc).isoformat()
        write_json(args.audit_dir / "result.json", result)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, KeyError, ProtectionError) as exc:
        write_json(args.audit_dir / "failure.json", {"error": str(exc), "applied_successfully": False})
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
