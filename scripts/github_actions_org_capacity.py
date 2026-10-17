#!/usr/bin/env python3
"""Read-only organization GitHub Actions concurrency evidence.

A workflow run != a job, and a queued job's started_at is not runner admission.
This tool reconstructs a conservative *provable* concurrency peak from real
job execution intervals. It does not create, rerun, cancel or dispatch jobs.
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

VALID_ORG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")


def parse_time(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def api_get(path: str, params: dict, token: str):
    if not token:
        raise ValueError("GITHUB_TOKEN or GH_TOKEN is required")
    query = urlencode(params)
    url = "https://api.github.com" + path + ("?" + query if query else "")
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + token,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "hepta-org-actions-concurrency/1",
        },
    )
    with urlopen(request, timeout=25) as response:
        return json.load(response)


def job_intervals(
    jobs: list[dict], requested_at: datetime, window_start: datetime
) -> list[tuple[datetime, datetime]]:
    """Only intervals backed by actual runner assignment and job timestamps.

    In-progress jobs are proven running at response time. Use the request
    *start* as a conservative right endpoint rather than network response
    completion, which could be later than the job's actual completion.
    """
    results: list[tuple[datetime, datetime]] = []
    for job in jobs:
        if not (job.get("runner_name") or job.get("runner_id")):
            continue
        started = parse_time(job.get("started_at"))
        if started is None:
            continue
        status = job.get("status")
        if status == "in_progress":
            # If it started after the HTTP request began, no safe pre-request
            # execution interval can be established.
            if started > requested_at:
                continue
            ended = requested_at
        elif status == "completed":
            ended = parse_time(job.get("completed_at"))
            if ended is None:
                continue
        else:
            # GitHub sometimes sets started_at on queued/unassigned jobs.
            continue
        beginning = max(started, window_start)
        if ended > beginning:
            results.append((beginning, ended))
    return results


def provable_peak(
    intervals: list[tuple[datetime, datetime]],
) -> tuple[int, datetime | None]:
    """Maximum overlapping half-open execution intervals [started, ended)."""
    events: list[tuple[datetime, int]] = []
    for started, ended in intervals:
        if ended <= started:
            continue
        events.extend(((started, 1), (ended, -1)))
    # On identical timestamps, release a finished job before allocating a new
    # one, so the boundary does not overstate simultaneous job count.
    events.sort(key=lambda event: (event[0], event[1]))
    peak = active = 0
    at = None
    for point, delta in events:
        active += delta
        if active > peak:
            peak, at = active, point
    return peak, at


def collect(
    org: str,
    query,
    *,
    clock=None,
    workers: int = 7,
    max_runs: int = 200,
    max_repo_pages: int = 3,
    max_job_pages: int = 8,
) -> dict:
    """Gather a bounded, explicitly incomplete-on-error org-wide lower bound."""
    if not VALID_ORG.fullmatch(org):
        raise ValueError("invalid organization name")
    if not (
        1 <= workers <= 12
        and 1 <= max_runs <= 1000
        and 1 <= max_repo_pages <= 10
        and 1 <= max_job_pages <= 10
    ):
        raise ValueError("invalid observation limits")
    clock = clock or (lambda: datetime.now(timezone.utc))
    began = clock()
    error: list[dict] = []
    all_repos: list[dict] = []
    listing_complete = False
    for page in range(1, max_repo_pages + 1):
        try:
            records = query(
                f"/orgs/{org}/repos", {"type": "all", "per_page": 100, "page": page}
            )
            if not isinstance(records, list):
                raise ValueError("repository list is not an array")
            all_repos.extend(records)
            if len(records) < 100:
                listing_complete = True
                break
        except Exception as exc:
            error.append(
                {"stage": "repositories", "page": page, "reason": type(exc).__name__}
            )
            break
    repos = sorted(
        {r["name"] for r in all_repos if not r.get("archived") and r.get("name")}
    )
    run_counts: Counter[str] = Counter()
    active_runs: list[tuple[str, int]] = []

    def repo_runs(repo: str):
        path = f"/repos/{quote(org)}/{quote(repo)}/actions/runs"
        runs: list[dict] = []
        total = None
        truncated = False
        try:
            for page in range(1, 9):
                answer = query(
                    path, {"status": "in_progress", "per_page": 100, "page": page}
                )
                total = int(answer["total_count"])
                records = answer["workflow_runs"]
                runs.extend(records)
                if len(runs) >= total or len(records) < 100:
                    break
            if total is not None and len(runs) < total:
                truncated = True
            return repo, runs, total, truncated, None
        except Exception as exc:
            return repo, runs, total, True, type(exc).__name__

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(repo_runs, repo) for repo in repos]
        for future in as_completed(futures):
            repo, runs, count, truncated, failure = future.result()
            if failure or truncated:
                error.append(
                    {
                        "stage": "active_runs",
                        "repo": repo,
                        "reason": failure or "truncated",
                    }
                )
            run_counts[repo] = count if count is not None else 0
            active_runs.extend((repo, int(run["id"])) for run in runs)
    active_runs = sorted(set(active_runs))
    if len(active_runs) > max_runs:
        error.append(
            {
                "stage": "active_runs",
                "reason": "max_runs_exceeded",
                "available": len(active_runs),
                "limit": max_runs,
            }
        )
        active_runs = active_runs[:max_runs]

    states: Counter[str] = Counter()
    labels: Counter[str] = Counter()
    intervals: list[tuple[datetime, datetime]] = []
    collected_jobs = 0
    sampled_runs = 0

    def run_jobs(task: tuple[str, int]):
        repo, run_id = task
        path = f"/repos/{quote(org)}/{quote(repo)}/actions/runs/{run_id}/jobs"
        started_request = clock()
        jobs: list[dict] = []
        try:
            for page in range(1, max_job_pages + 1):
                answer = query(path, {"per_page": 100, "page": page})
                jobs.extend(answer["jobs"])
                if len(jobs) >= int(answer["total_count"]):
                    return task, jobs, started_request, False, None
            return task, jobs, started_request, True, None
        except Exception as exc:
            return task, jobs, started_request, True, type(exc).__name__

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run_jobs, task) for task in active_runs]
        for future in as_completed(futures):
            task, jobs, request_start, truncated, failure = future.result()
            if truncated or failure:
                error.append(
                    {
                        "stage": "run_jobs",
                        "repo": task[0],
                        "run_id": task[1],
                        "reason": failure or "truncated",
                    }
                )
            else:
                sampled_runs += 1
            collected_jobs += len(jobs)
            states.update(job.get("status", "unknown") for job in jobs)
            for job in jobs:
                if job.get("status") == "in_progress" and (
                    job.get("runner_name") or job.get("runner_id")
                ):
                    labels[",".join(job.get("labels") or []) or "unknown"] += 1
            intervals.extend(job_intervals(jobs, request_start, began))

    maximum, at = provable_peak(intervals)
    finished = clock()
    return {
        "org": org,
        "observation_start": began.isoformat(),
        "observation_end": finished.isoformat(),
        "repositories_visible": len(repos),
        "repository_listing_complete": listing_complete,
        "provider_active_workflow_runs_by_repository": dict(run_counts),
        "workflow_runs_sampled": len(active_runs),
        "complete_job_pages": sampled_runs,
        "sampled_job_records": collected_jobs,
        "job_states_seen_nonatomic": dict(states),
        "in_progress_runner_labels_nonatomic": dict(labels),
        "peak_provable_concurrent_jobs_lower_bound": maximum,
        "peak_proof_timestamp": at.isoformat() if at else None,
        "target": 500,
        "verified_500_running": maximum >= 500,
        "all_read_paths_complete": listing_complete and not error,
        "limitations": (
            "Only in-progress workflow runs sampled. Jobs from completed "
            "runs are not comprehensively enumerated; the peak is a proven "
            "lower bound from intersecting assigned-runner intervals, not "
            "organization entitlement or a complete global peak."
        ),
        "errors": error,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=7)
    parser.add_argument("--max-runs", type=int, default=200)
    args = parser.parse_args(argv)
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or ""
    try:
        if not token:
            raise ValueError("GITHUB_TOKEN or GH_TOKEN must be set")
        result = collect(
            args.org,
            lambda path, params: api_get(path, params, token),
            workers=args.workers,
            max_runs=args.max_runs,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(
            json.dumps(
                {
                    "org": result["org"],
                    "running_job_records_nonatomic": result[
                        "job_states_seen_nonatomic"
                    ].get("in_progress", 0),
                    "proven_peak_lower_bound": result[
                        "peak_provable_concurrent_jobs_lower_bound"
                    ],
                    "verified_500": result["verified_500_running"],
                    "all_read_paths_complete": result["all_read_paths_complete"],
                    "output": str(args.output),
                },
                sort_keys=True,
            )
        )
        return 0 if not result["errors"] else 2
    except (HTTPError, URLError, OSError, ValueError, KeyError) as exc:
        print(
            f"organization capacity audit failed: {type(exc).__name__}", file=sys.stderr
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
