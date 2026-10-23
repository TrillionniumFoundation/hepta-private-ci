"""Observe canonical control.engineering workflow jobs for one exact commit.

This gate never reinterprets a workflow conclusion. It waits for the existing
`hepta-consolidated-source.yml` run at the exact head SHA, requires the named
source/base product and strong-sandbox jobs, and emits a digest-only observation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

_SCHEMA = "hepta.control-engineering-workflow-observation.v1"
_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
_REQUIRED_SOURCE = (
    "Engineering strong sandbox (source-head)",
    "control.engineering product caller (source-head)",
)
_REQUIRED_PULL_REQUEST = _REQUIRED_SOURCE + (
    "Engineering strong sandbox (base-merge)",
    "control.engineering product caller (base-merge)",
    "control.engineering dual-lane product evidence",
)


def select_exact_run(runs: object, *, head_sha: str, expected_event: str) -> dict[str, object] | None:
    if not isinstance(runs, list):
        raise ValueError("workflow_runs_shape")
    candidates = []
    for row in runs:
        if not isinstance(row, dict):
            raise ValueError("workflow_runs_shape")
        if row.get("head_sha") == head_sha and row.get("event") == expected_event:
            run_id = row.get("id")
            attempt = row.get("run_attempt", 1)
            created = row.get("created_at", "")
            if type(run_id) is not int or type(attempt) is not int or not isinstance(created, str):
                raise ValueError("workflow_runs_shape")
            candidates.append((created, attempt, run_id, row))
    return None if not candidates else max(candidates)[-1]


def verify_required_jobs(jobs: object, *, pull_request: bool) -> dict[str, object]:
    if not isinstance(jobs, list):
        raise ValueError("workflow_jobs_shape")
    required = _REQUIRED_PULL_REQUEST if pull_request else _REQUIRED_SOURCE
    by_name: dict[str, dict[str, object]] = {}
    for row in jobs:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str):
            raise ValueError("workflow_jobs_shape")
        by_name[str(row["name"])] = row
    missing = [name for name in required if name not in by_name]
    if missing:
        raise ValueError("workflow_required_jobs_missing:" + ",".join(missing))
    observed = []
    for name in required:
        row = by_name[name]
        if row.get("status") != "completed" or row.get("conclusion") != "success":
            raise ValueError(
                "workflow_required_job_not_success:"
                + name
                + ":"
                + str(row.get("status"))
                + ":"
                + str(row.get("conclusion"))
            )
        observed.append(
            {
                "jobId": row.get("id"),
                "name": name,
                "status": row.get("status"),
                "conclusion": row.get("conclusion"),
            }
        )
    return {"requiredJobs": observed}


class GitHubActionsReader:
    def __init__(self, repository: str, token: str):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("github_repository")
        if not token or "\n" in token or "\r" in token:
            raise ValueError("github_token")
        self.repository = repository
        self.token = token

    def _json(self, path: str) -> dict[str, object]:
        request = Request(
            "https://api.github.com" + path,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": "Bearer " + self.token,
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "hepta-control-engineering-workflow-gate/1",
            },
        )
        with urlopen(request, timeout=20) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError("github_response_limit")
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("github_response_shape")
        return value

    def runs(self, head_sha: str, expected_event: str) -> list[dict[str, object]]:
        query = urlencode({"head_sha": head_sha, "event": expected_event, "per_page": 100})
        value = self._json(
            f"/repos/{self.repository}/actions/workflows/hepta-consolidated-source.yml/runs?{query}"
        )
        runs = value.get("workflow_runs")
        if not isinstance(runs, list):
            raise ValueError("workflow_runs_shape")
        return runs

    def jobs(self, run_id: int) -> list[dict[str, object]]:
        value = self._json(
            f"/repos/{self.repository}/actions/runs/{run_id}/jobs?filter=latest&per_page=100"
        )
        jobs = value.get("jobs")
        if not isinstance(jobs, list):
            raise ValueError("workflow_jobs_shape")
        return jobs


def observe_workflow(
    reader: GitHubActionsReader,
    *,
    head_sha: str,
    pull_request: bool,
    timeout_seconds: int = 2_700,
    poll_seconds: int = 15,
) -> dict[str, object]:
    if _SHA1.fullmatch(head_sha) is None:
        raise ValueError("workflow_head_sha")
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 3_600:
        raise ValueError("workflow_timeout")
    if type(poll_seconds) is not int or not 1 <= poll_seconds <= 60:
        raise ValueError("workflow_poll")
    event = "pull_request" if pull_request else "push"
    deadline = time.monotonic() + timeout_seconds
    last_error = "workflow_run_pending"
    while time.monotonic() < deadline:
        run = select_exact_run(reader.runs(head_sha, event), head_sha=head_sha, expected_event=event)
        if run is not None:
            run_id = int(run["id"])
            jobs = reader.jobs(run_id)
            try:
                verified = verify_required_jobs(jobs, pull_request=pull_request)
            except ValueError as error:
                last_error = str(error)
                if run.get("status") == "completed":
                    raise
            else:
                value: dict[str, object] = {
                    "schema": _SCHEMA,
                    "repository": reader.repository,
                    "headSha": head_sha,
                    "event": event,
                    "runId": run_id,
                    "runAttempt": run.get("run_attempt", 1),
                    **verified,
                    "githubApprovalObserved": False,
                    "independentSemanticAcceptance": False,
                    "mergeAuthority": False,
                    "releaseAuthority": False,
                }
                value["observationDigest"] = hashlib.sha256(
                    json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                return value
        time.sleep(poll_seconds)
    raise ValueError("workflow_observation_timeout:" + last_error)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--pull-request", action="store_true")
    parser.add_argument("--token-env", default="GITHUB_TOKEN")
    parser.add_argument("--timeout-seconds", type=int, default=2700)
    parser.add_argument("--poll-seconds", type=int, default=15)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        token = os.environ.get(args.token_env, "")
        value = observe_workflow(
            GitHubActionsReader(args.repository, token),
            head_sha=args.head_sha,
            pull_request=args.pull_request,
            timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"schema": _SCHEMA, "status": "rejected", "error": str(error)}))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
