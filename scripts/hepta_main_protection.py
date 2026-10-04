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
        command = [
            "gh",
            "api",
            "--hostname",
            "github.com",
            "--method",
            method,
            "-H",
            "Accept: application/vnd.github+json",
            "-H",
            "X-GitHub-Api-Version: 2022-11-28",
            f"repos/{REPOSITORY}/{path}",
        ]
        if body is not None:
            command.extend(["--input", "-"])
        environment = dict(os.environ, GH_PROMPT_DISABLED="1")
        environment.pop("GH_DEBUG", None)
        try:
            result = subprocess.run(
                command,
                input=None if body is None else json.dumps(body),
                text=True,
                capture_output=True,
                check=False,
                env=environment,
                timeout=60,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProtectionError(
                f"GitHub {method} timed out; a write may have applied: inspect live policy before retry"
            ) from exc
        if result.returncode:
            raise ProtectionError(
                f"GitHub {method} {path} failed: {result.stderr.strip()}"
            )
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
        raise ProtectionError(
            "pagination limit reached; no incomplete policy read accepted"
        )


def desired_ruleset(app_id: int) -> dict[str, Any]:
    if type(app_id) is not int or app_id <= 0:
        raise ProtectionError("a verified GitHub Actions integration ID is required")
    return {
        "name": RULESET_NAME,
        "target": "branch",
        "enforcement": "active",
        "bypass_actors": [],
        "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
                "type": "pull_request",
                "parameters": {
                    "dismiss_stale_reviews_on_push": True,
                    "require_code_owner_review": True,
                    "require_last_push_approval": True,
                    "required_approving_review_count": 1,
                    "required_review_thread_resolution": True,
                },
            },
            {
                "type": "required_status_checks",
                "parameters": {
                    "required_status_checks": [
                        {"context": GATE, "integration_id": app_id}
                    ],
                    "strict_required_status_checks_policy": True,
                    "do_not_enforce_on_create": False,
                },
            },
        ],
    }


def verify_ruleset(value: dict[str, Any], app_id: int) -> None:
    if value.get("target") != "branch" or value.get("enforcement") != "active":
        raise ProtectionError("ruleset is not an active branch policy")
    if value.get("bypass_actors") != []:
        raise ProtectionError(
            "ruleset has bypass actors or bypass visibility is unavailable"
        )
    if value.get("conditions") != desired_ruleset(app_id)["conditions"]:
        raise ProtectionError("ruleset does not exactly target main")
    rows = value.get("rules", [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ProtectionError("malformed rules")
    rules = {row.get("type"): row for row in rows}
    if len(rules) != len(rows):
        raise ProtectionError("duplicate rule types are ambiguous")
    if (
        not {"deletion", "non_fast_forward", "pull_request", "required_status_checks"}
        <= rules.keys()
    ):
        raise ProtectionError("missing required protection")
    review = rules["pull_request"].get("parameters", {})
    count = review.get("required_approving_review_count")
    if type(count) is not int or count < 1:
        raise ProtectionError("at least one independent approval is required")
    for field in (
        "dismiss_stale_reviews_on_push",
        "require_code_owner_review",
        "require_last_push_approval",
        "required_review_thread_resolution",
    ):
        if review.get(field) is not True:
            raise ProtectionError(f"missing independent-review control: {field}")
    checks = rules["required_status_checks"].get("parameters", {})
    if checks.get("strict_required_status_checks_policy") is not True:
        raise ProtectionError("checks do not require an up-to-date base")
    if checks.get("do_not_enforce_on_create", False) is not False:
        raise ProtectionError("creation bypasses required checks")
    if {"context": GATE, "integration_id": app_id} not in checks.get(
        "required_status_checks", []
    ):
        raise ProtectionError("required check is not bound to the verified Actions app")


def verified_gate_evidence(
    checks: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    head: str,
) -> dict[str, int]:
    """Bind the newest main workflow attempt before looking for its green gate.

    An old successful suite must not fill in a gate that a newer workflow has
    not produced yet. These identities are observations, not authorization to
    execute candidate code or mutate the candidate branch.
    """
    if not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ProtectionError("gate head must be an exact GitHub commit SHA")
    if not isinstance(checks, list) or not isinstance(runs, list):
        raise ProtectionError("malformed gate evidence")
    if any(not isinstance(row, dict) for row in [*checks, *runs]):
        raise ProtectionError("malformed gate evidence row")
    trusted = []
    for run in runs:
        if run.get("head_sha") != head:
            continue
        path = run.get("path")
        if not isinstance(path, str):
            raise ProtectionError("workflow path is unavailable")
        if path.split("@")[0] != ".github/workflows/" + WORKFLOW:
            continue
        repository = run.get("repository")
        if (
            run.get("head_branch") != "main"
            or run.get("event") not in {"push", "workflow_dispatch"}
            or not isinstance(repository, dict)
            or repository.get("full_name") != REPOSITORY
        ):
            continue
        for field in ("id", "run_attempt", "check_suite_id"):
            if type(run.get(field)) is not int or run[field] <= 0:
                raise ProtectionError(f"workflow has no valid {field}")
        trusted.append(run)
    if not trusted:
        raise ProtectionError("no exact-main run of the required workflow")
    run = max(trusted, key=lambda row: (row["id"], row["run_attempt"]))
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        raise ProtectionError("latest exact-main workflow attempt is not successful")

    matches = []
    for check in checks:
        if check.get("name") != GATE or check.get("head_sha") != head:
            continue
        app, suite = check.get("app"), check.get("check_suite")
        if (
            not isinstance(app, dict)
            or app.get("slug") != "github-actions"
            or not isinstance(suite, dict)
            or type(suite.get("id")) is not int
            or suite["id"] != run["check_suite_id"]
        ):
            continue
        if type(check.get("id")) is not int or check["id"] <= 0:
            raise ProtectionError("gate has no valid check identity")
        matches.append(check)
    if not matches:
        raise ProtectionError("latest workflow has no matching Actions blocking gate")
    latest = max(matches, key=lambda row: row["id"])
    if latest.get("status") != "completed" or latest.get("conclusion") != "success":
        raise ProtectionError("latest exact-head gate is not completed successfully")
    app_id = latest["app"].get("id")
    desired_ruleset(app_id)
    return {
        "integration_id": app_id,
        "check_id": latest["id"],
        "suite_id": run["check_suite_id"],
        "run_id": run["id"],
        "run_attempt": run["run_attempt"],
    }


def verified_gate_app(
    checks: list[dict[str, Any]], runs: list[dict[str, Any]], head: str
) -> int:
    return verified_gate_evidence(checks, runs, head)["integration_id"]


def read_gate_evidence(api: API, head: str) -> dict[str, int]:
    checks = api.pages(f"commits/{head}/check-runs?filter=latest", "check_runs")
    runs = api.pages(
        f"actions/workflows/{WORKFLOW}/runs?head_sha={head}", "workflow_runs"
    )
    gate = verified_gate_evidence(checks, runs, head)
    # Reruns can retain a suite ID. Check-suite membership alone therefore does
    # not prove that the required job belongs to this particular run attempt.
    jobs = api.pages(
        f"actions/runs/{gate['run_id']}/attempts/{gate['run_attempt']}/jobs",
        "jobs",
    )
    expected_url = (
        f"https://api.github.com/repos/{REPOSITORY}/check-runs/{gate['check_id']}"
    )
    if any(not isinstance(job, dict) for job in jobs):
        raise ProtectionError("malformed workflow-attempt job evidence")
    matches = [job for job in jobs if job.get("check_run_url") == expected_url]
    if len(matches) != 1:
        raise ProtectionError("gate is not a unique job in the latest workflow attempt")
    job = matches[0]
    if (
        type(job.get("id")) is not int
        or job["id"] <= 0
        or type(job.get("run_id")) is not int
        or job["run_id"] != gate["run_id"]
        or job.get("head_sha") != head
        or job.get("name") != GATE
        or job.get("status") != "completed"
        or job.get("conclusion") != "success"
    ):
        raise ProtectionError("latest workflow-attempt job binding is not successful")
    if "run_attempt" in job and (
        type(job["run_attempt"]) is not int or job["run_attempt"] != gate["run_attempt"]
    ):
        raise ProtectionError("job is from a different workflow attempt")
    return {**gate, "job_id": job["id"]}


def snapshot(api: API) -> dict[str, Any]:
    branch = api.call("GET", "branches/main")
    rulesets = api.pages("rulesets?includes_parents=true")
    named = [row for row in rulesets if row.get("name") == RULESET_NAME]
    if len(named) > 1:
        raise ProtectionError("multiple named baseline rulesets; refusing to guess")
    detail = api.call("GET", f"rulesets/{named[0]['id']}") if named else None
    return {
        "main_head": branch["commit"]["sha"],
        "rulesets": rulesets,
        "named_ruleset": detail,
    }


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
    gate = read_gate_evidence(api, expected_head)
    write_json(audit / "gate-before.json", gate)
    app_id = gate["integration_id"]
    desired = desired_ruleset(app_id)
    write_json(audit / "proposed.json", desired)
    # Dry-run must also reject an existing weaker named policy, not imply that
    # apply would succeed when it will deliberately refuse to replace it.
    if before["named_ruleset"] is not None:
        verify_ruleset(before["named_ruleset"], app_id)
    if not apply:
        return {
            "mode": "read-only",
            "main_head": expected_head,
            "would_create": before["named_ruleset"] is None,
        }
    prewrite_gate = read_gate_evidence(api, expected_head)
    write_json(audit / "gate-prewrite.json", prewrite_gate)
    if prewrite_gate != gate:
        raise ProtectionError(
            "gate identity changed during preflight; no mutation performed"
        )
    if snapshot(api) != before:
        raise ProtectionError(
            "repository state changed during preflight; no mutation performed"
        )
    if before["named_ruleset"] is None:
        created = api.call("POST", "rulesets", desired)
        write_json(audit / "write-response.json", created)
    after = snapshot(api)
    write_json(audit / "after.json", after)
    if after["named_ruleset"] is None:
        raise ProtectionError(
            "write has no readable matching ruleset; do not claim enforcement"
        )
    verify_ruleset(after["named_ruleset"], app_id)
    if after["main_head"] != expected_head:
        raise ProtectionError(
            "policy may have been installed, but main changed during mutation; inspect after.json"
        )
    # GitHub reads and writes are not one transaction. Preserve the installed
    # protection on a post-write race; never delete it to undo a failed audit.
    after_gate = read_gate_evidence(api, expected_head)
    write_json(audit / "gate-after.json", after_gate)
    if after_gate != gate:
        raise ProtectionError(
            "policy may be installed, but gate identity changed; inspect audit"
        )
    return {
        "mode": "applied-and-read-back",
        "main_head": expected_head,
        "ruleset_id": after["named_ruleset"]["id"],
        "gate": GATE,
        "integration_id": app_id,
    }


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
        write_json(
            args.audit_dir / "failure.json",
            {"error": str(exc), "applied_successfully": False},
        )
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
