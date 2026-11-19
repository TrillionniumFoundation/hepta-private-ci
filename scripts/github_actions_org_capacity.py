#!/usr/bin/env python3
"""Read-only organization GitHub Actions concurrency evidence.

A workflow run != a job, and a queued job's started_at is not runner admission.
This tool observes concurrency from assigned-runner job intervals and verifies
the target only with completed jobs. It does not create, rerun, cancel or
dispatch jobs.
"""

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

    For in-progress jobs, use request start instead of response completion as
    the observed right endpoint. Stale API status can still overstate these
    intervals, so only completed job intervals support final verification.
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
            # A job starting after the request began has no observed interval
            # before this request's right endpoint.
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


def merge_job_observations(previous: dict, current: dict) -> dict | None:
    """Accept pagination refreshes, but never combine contradictory executions."""
    for field in ("run_id", "run_attempt"):
        if previous.get(field) is not None and current.get(field) is not None:
            if previous[field] != current[field]:
                return None

    def executing(job):
        return job.get("status") in {"in_progress", "completed"} and (
            job.get("runner_id") or job.get("runner_name")
        )

    if executing(previous) and executing(current):
        if previous.get("runner_id") and current.get("runner_id"):
            if previous["runner_id"] != current["runner_id"]:
                return None
        elif previous.get("runner_name") != current.get("runner_name"):
            return None
        if parse_time(previous.get("started_at")) != parse_time(
            current.get("started_at")
        ):
            return None
    if previous.get("status") == current.get("status") == "completed":
        for field in ("completed_at", "conclusion"):
            if previous.get(field) != current.get(field):
                return None

    # A queued started_at is not an execution timestamp. A later terminal
    # observation supersedes it; a stale queued/in-progress page must not
    # overwrite a terminal observation of the same immutable job ID.
    order = {"queued": 0, "waiting": 0, "in_progress": 1, "completed": 2}
    if order.get(previous.get("status"), -1) > order.get(current.get("status"), -1):
        return previous
    return current


def runner_intervals(
    observations: list[tuple[dict, datetime]], window_start: datetime
) -> tuple[list[tuple[datetime, datetime]], list[dict]]:
    """A reused runner contributes at most one job at any instant."""
    by_runner: dict[tuple, list[tuple[datetime, datetime]]] = {}
    for job, requested_at in observations:
        runner_id = job.get("runner_id")
        runner = ("id", runner_id) if runner_id else ("name", job.get("runner_name"))
        by_runner.setdefault(runner, []).extend(
            job_intervals([job], requested_at, window_start)
        )
    intervals = []
    overlaps = []
    for runner, periods in by_runner.items():
        merged = []
        overlap = False
        for started, ended in sorted(periods):
            if merged and started < merged[-1][1]:
                overlap = True
                merged[-1] = (merged[-1][0], max(merged[-1][1], ended))
            else:
                merged.append((started, ended))
        intervals.extend(merged)
        if overlap:
            overlaps.append({"runner_identity_type": runner[0], "runner": runner[1]})
    return intervals, overlaps


def collect(
    org: str,
    query,
    *,
    clock=None,
    workers: int = 7,
    max_runs: int = 200,
    max_repo_pages: int = 3,
    max_job_pages: int = 8,
    max_run_pages: int = 8,
    include_queued: bool = False,
) -> dict:
    """Gather a bounded, explicitly incomplete-on-error org-wide lower bound."""
    if not VALID_ORG.fullmatch(org):
        raise ValueError("invalid organization name")
    if not (
        1 <= workers <= 12
        and 1 <= max_runs <= 1000
        and 1 <= max_repo_pages <= 10
        and 1 <= max_job_pages <= 10
        and 1 <= max_run_pages <= 10
        and type(include_queued) is bool
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
    run_statuses = ("in_progress", "queued") if include_queued else ("in_progress",)
    run_counts: dict[str, dict[str, int | None]] = {
        status: {} for status in run_statuses
    }
    candidates: dict[int, tuple[int, str, int]] = {}

    def repo_runs(repo: str, status: str):
        path = f"/repos/{quote(org)}/{quote(repo)}/actions/runs"
        runs: set[int] = set()
        total = None
        highest_total = 0
        truncated = False
        try:
            for page in range(1, max_run_pages + 1):
                answer = query(path, {"status": status, "per_page": 100, "page": page})
                total = int(answer["total_count"])
                highest_total = max(highest_total, total)
                records = answer["workflow_runs"]
                runs.update(int(run["id"]) for run in records)
                if len(runs) >= highest_total or len(records) < 100:
                    break
            if len(runs) < highest_total:
                truncated = True
            return repo, status, runs, total, truncated, None
        except Exception as exc:
            return repo, status, runs, total, True, type(exc).__name__

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(repo_runs, repo, status)
            for repo in repos
            for status in run_statuses
        ]
        for future in as_completed(futures):
            repo, status, runs, count, truncated, failure = future.result()
            if failure or truncated:
                error.append(
                    {
                        "stage": "active_runs",
                        "repo": repo,
                        "status": status,
                        "reason": failure or "truncated",
                    }
                )
            run_counts[status][repo] = count
            for run_id in runs:
                # A parent can appear in both status queries while transitioning.
                # Read its jobs once, prioritizing in-progress parents under the cap.
                candidate = (run_statuses.index(status), repo, run_id)
                candidates[run_id] = min(candidate, candidates.get(run_id, candidate))
    discovered_runs = len(candidates)
    selected = sorted(candidates.values())
    if discovered_runs > max_runs:
        error.append(
            {
                "stage": "active_runs",
                "reason": "max_runs_exceeded",
                "available": discovered_runs,
                "limit": max_runs,
            }
        )
        selected = selected[:max_runs]
    active_runs = [(repo, run_id) for _, repo, run_id in selected]
    sampled_parent_statuses = Counter(
        run_statuses[priority] for priority, _, _ in selected
    )

    states: Counter[str] = Counter()
    labels: Counter[str] = Counter()
    observations: dict[int, tuple[dict, datetime]] = {}
    conflicting_ids: set[int] = set()
    collected_jobs = 0
    duplicate_jobs = 0
    sampled_runs = 0

    def run_jobs(task: tuple[str, int]):
        repo, run_id = task
        path = f"/repos/{quote(org)}/{quote(repo)}/actions/runs/{run_id}/jobs"
        started_request = clock()
        jobs: dict[int, dict] = {}
        seen_ids: set[int] = set()
        conflicts: set[int] = set()
        problems: list[dict] = []
        raw_count = duplicate_count = total = 0
        exhausted = False
        try:
            for page in range(1, max_job_pages + 1):
                answer = query(path, {"per_page": 100, "page": page})
                records = answer["jobs"]
                total = max(total, int(answer["total_count"]))
                raw_count += len(records)
                for job in records:
                    job_id = job.get("id")
                    if type(job_id) is not int or job_id <= 0:
                        problems.append({"reason": "invalid_job_id", "page": page})
                        continue
                    if job_id in seen_ids:
                        duplicate_count += 1
                    seen_ids.add(job_id)
                    if job_id in conflicts:
                        continue
                    reported_run_id = job.get("run_id")
                    if reported_run_id is not None and (
                        type(reported_run_id) is not int or reported_run_id != run_id
                    ):
                        conflicts.add(job_id)
                        jobs.pop(job_id, None)
                        problems.append(
                            {"reason": "job_parent_mismatch", "job_id": job_id}
                        )
                        continue
                    if job_id in jobs:
                        merged = merge_job_observations(jobs[job_id], job)
                        if merged is None:
                            conflicts.add(job_id)
                            del jobs[job_id]
                            problems.append(
                                {
                                    "reason": "conflicting_job_observations",
                                    "job_id": job_id,
                                }
                            )
                            continue
                        job = merged
                    jobs[job_id] = job
                # Raw record count can reach total_count while repeated IDs
                # hide a missing page. Use distinct IDs against every total
                # observed in this read, without requiring an extra empty page.
                if len(seen_ids) >= total:
                    exhausted = True
                    break
                if len(records) < 100:
                    break
            if not exhausted or len(seen_ids) < total:
                problems.append({"reason": "truncated"})
        except Exception as exc:
            problems.append({"reason": type(exc).__name__})
        return (
            task,
            jobs,
            conflicts,
            started_request,
            raw_count,
            duplicate_count,
            problems,
        )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run_jobs, task) for task in active_runs]
        for future in as_completed(futures):
            task, jobs, conflicts, request_start, raw_count, duplicates, problems = (
                future.result()
            )
            if problems:
                error.extend(
                    {
                        "stage": "run_jobs",
                        "repo": task[0],
                        "run_id": task[1],
                        **problem,
                    }
                    for problem in problems
                )
            else:
                sampled_runs += 1
            collected_jobs += raw_count
            duplicate_jobs += duplicates
            # A locally excluded ID remains excluded across all parents,
            # regardless of which future's observations arrive first.
            conflicting_ids.update(conflicts)
            for job_id in conflicts:
                observations.pop(job_id, None)
            for job_id, job in jobs.items():
                # Parent IDs were already deduplicated. The same job appearing
                # under distinct parents is inconsistent, not extra capacity.
                if job_id in observations or job_id in conflicting_ids:
                    duplicate_jobs += 1
                    if job_id not in conflicting_ids:
                        error.append(
                            {
                                "stage": "run_jobs",
                                "reason": "job_in_multiple_runs",
                                "job_id": job_id,
                            }
                        )
                    conflicting_ids.add(job_id)
                    observations.pop(job_id, None)
                else:
                    observations[job_id] = (job, request_start)

    for job, _ in observations.values():
        states[job.get("status", "unknown")] += 1
        if job.get("status") == "in_progress" and (
            job.get("runner_name") or job.get("runner_id")
        ):
            labels[",".join(job.get("labels") or []) or "unknown"] += 1
    intervals, overlaps = runner_intervals(list(observations.values()), began)
    error.extend(
        {"stage": "job_intervals", "reason": "overlapping_runner_jobs", **overlap}
        for overlap in overlaps
    )

    maximum, at = provable_peak(intervals)
    terminal_intervals, _ = runner_intervals(
        [
            observation
            for observation in observations.values()
            if observation[0].get("status") == "completed"
            and type(observation[0].get("runner_id")) is int
            and observation[0]["runner_id"] > 0
        ],
        began,
    )
    terminal_maximum, terminal_at = provable_peak(terminal_intervals)
    finished = clock()
    return {
        "org": org,
        "observation_start": began.isoformat(),
        "observation_end": finished.isoformat(),
        "repositories_visible": len(repos),
        "repository_listing_complete": listing_complete,
        "provider_active_workflow_runs_by_repository": run_counts["in_progress"],
        "provider_workflow_run_counts_by_status_and_repository": run_counts,
        "parent_run_statuses_requested": list(run_statuses),
        "unique_parent_runs_discovered": discovered_runs,
        "parent_runs_omitted_by_max_runs": max(0, discovered_runs - max_runs),
        "sampled_parent_run_query_statuses": dict(sampled_parent_statuses),
        "sampling_limits": {
            "max_runs": max_runs,
            "max_run_pages_per_repository_status": max_run_pages,
            "max_repository_pages": max_repo_pages,
            "max_job_pages_per_run": max_job_pages,
        },
        "workflow_runs_sampled": len(active_runs),
        "complete_job_pages": sampled_runs,
        "sampled_job_records": collected_jobs,
        "unique_sampled_job_records": len(observations),
        "duplicate_job_records": duplicate_jobs,
        "job_states_seen_nonatomic": dict(states),
        "in_progress_runner_labels_nonatomic": dict(labels),
        "peak_provable_concurrent_jobs_lower_bound": maximum,
        "peak_proof_timestamp": at.isoformat() if at else None,
        "peak_terminal_concurrent_jobs_lower_bound": terminal_maximum,
        "peak_terminal_proof_timestamp": terminal_at.isoformat()
        if terminal_at
        else None,
        "target": 500,
        "verified_500_running": terminal_maximum >= 500,
        "all_read_paths_complete": listing_complete and not error,
        "limitations": (
            "Parent status filters: "
            + ", ".join(run_statuses)
            + ". "
            + (
                ""
                if include_queued
                else "Queued parents can have executing children; use --include-queued to sample them. "
            )
            + "Parent queries and job reads are bounded by sampling_limits. "
            "Provider status totals come from separate reads and may overlap; "
            "job reads are deduplicated by parent run ID and job ID. "
            "Conflicting jobs and parent mismatches are excluded across all "
            "parents; overlapping intervals "
            "on one runner count once and are reported. The legacy "
            "peak_provable_concurrent_jobs_lower_bound and peak_proof_timestamp "
            "fields are observed estimates: in-progress status may be stale "
            "even when its interval ends at request start. Only the terminal "
            "peak, from completed jobs with positive integer runner IDs, "
            "determines verified_500_running. Name-only runner identities "
            "contribute only to the observed estimate. Jobs from completed parents are not "
            "comprehensively enumerated; the terminal peak is a lower bound, "
            "not organization entitlement or a complete global peak."
        ),
        "errors": error,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=7)
    parser.add_argument("--max-runs", type=int, default=200)
    parser.add_argument("--max-run-pages", type=int, default=8)
    parser.add_argument(
        "--include-queued",
        action="store_true",
        help="Also inspect queued parents, which can already have executing jobs; sampling limits still apply",
    )
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
            max_run_pages=args.max_run_pages,
            include_queued=args.include_queued,
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
                    "observed_peak": result[
                        "peak_provable_concurrent_jobs_lower_bound"
                    ],
                    "terminal_peak_lower_bound": result[
                        "peak_terminal_concurrent_jobs_lower_bound"
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
