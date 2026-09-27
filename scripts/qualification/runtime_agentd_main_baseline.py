#!/usr/bin/env python3
"""Generate evidence for consecutive successful blocking-ci main candidates."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable
import urllib.parse
import urllib.request

SCHEMA = 1
SHA = re.compile(r"[0-9a-f]{40}\Z")
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def api_json(url: str, token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "hepta-runtime-agentd-main-baseline",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        require(response.status == 200, f"GitHub API returned HTTP {response.status}")
        data = response.read(MAX_RESPONSE_BYTES + 1)
    require(len(data) <= MAX_RESPONSE_BYTES, "GitHub API response exceeded bound")
    value = json.loads(data)
    require(type(value) is dict, "GitHub API response must be an object")
    return value


def evaluate_runs(
    runs: list[dict[str, Any]],
    job_loader: Callable[[int], list[dict[str, Any]]],
    required_job: str,
    count: int,
    triggering_run_id: int,
    triggering_sha: str,
) -> dict[str, Any]:
    require(2 <= count <= 20, "consecutive run count must be in 2..=20")
    candidates = [
        run
        for run in runs
        if run.get("event") == "push"
        and run.get("head_branch") == "main"
        and run.get("status") == "completed"
    ]
    require(len(candidates) >= count, "not enough completed main push runs")
    candidates.sort(key=lambda run: int(run.get("run_number", 0)), reverse=True)
    selected = candidates[:count]
    first = selected[0]
    require(first.get("id") == triggering_run_id, "latest completed main run is not the triggering run")
    require(first.get("head_sha") == triggering_sha, "triggering main SHA differs from workflow run")

    evidence: list[dict[str, Any]] = []
    seen_runs: set[int] = set()
    seen_shas: set[str] = set()
    previous_number: int | None = None
    for run in selected:
        run_id = run.get("id")
        run_number = run.get("run_number")
        head_sha = run.get("head_sha")
        require(type(run_id) is int and run_id > 0, "invalid workflow run id")
        require(type(run_number) is int and run_number > 0, "invalid workflow run number")
        require(isinstance(head_sha, str) and SHA.fullmatch(head_sha) is not None, "invalid main workflow SHA")
        require(run_id not in seen_runs and head_sha not in seen_shas, "duplicate run or candidate SHA")
        require(run.get("conclusion") == "success", f"main workflow run {run_id} did not succeed")
        if previous_number is not None:
            require(run_number < previous_number, "main workflow runs are not strictly ordered")
        previous_number = run_number
        seen_runs.add(run_id)
        seen_shas.add(head_sha)

        jobs = job_loader(run_id)
        matching = [job for job in jobs if job.get("name") == required_job]
        require(len(matching) == 1, f"run {run_id} has missing or duplicate {required_job!r} jobs")
        job = matching[0]
        require(
            job.get("status") == "completed" and job.get("conclusion") == "success",
            f"run {run_id} required job did not succeed",
        )
        evidence.append(
            {
                "run_id": run_id,
                "run_number": run_number,
                "head_sha": head_sha,
                "workflow_conclusion": run.get("conclusion"),
                "required_job_id": job.get("id"),
                "required_job_conclusion": job.get("conclusion"),
            }
        )

    return {
        "schema": SCHEMA,
        "module": "runtime.agentd",
        "branch": "main",
        "required_job": required_job,
        "consecutive_successes": count,
        "runs": evidence,
        "baseline_result": "success",
        "production_activation": False,
        "unproven": [
            "target-host-qualification",
            "independent-security-acceptance",
            "release",
            "activation",
        ],
    }


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--workflow", default="blocking-ci.yml")
    parser.add_argument("--required-job", default="CI required")
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--triggering-run-id", type=int, required=True)
    parser.add_argument("--triggering-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        require(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repository) is not None, "invalid repository")
        require(SHA.fullmatch(args.triggering_sha) is not None, "triggering SHA must be exact")
        token = os.environ.get("GITHUB_TOKEN", "")
        require(bool(token), "GITHUB_TOKEN is required")
        repository = urllib.parse.quote(args.repository, safe="/")
        workflow = urllib.parse.quote(args.workflow, safe="")
        base = f"https://api.github.com/repos/{repository}"
        runs_value = api_json(
            f"{base}/actions/workflows/{workflow}/runs?branch=main&event=push&status=completed&per_page=50",
            token,
        )
        runs = runs_value.get("workflow_runs")
        require(type(runs) is list, "workflow run response omitted workflow_runs")

        def load_jobs(run_id: int) -> list[dict[str, Any]]:
            value = api_json(f"{base}/actions/runs/{run_id}/jobs?per_page=100", token)
            jobs = value.get("jobs")
            require(type(jobs) is list, f"workflow jobs response omitted jobs for {run_id}")
            return jobs

        result = evaluate_runs(
            runs,
            load_jobs,
            args.required_job,
            args.count,
            args.triggering_run_id,
            args.triggering_sha,
        )
        atomic_json(args.output.resolve(), result)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(f"runtime.agentd main baseline rejected: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
