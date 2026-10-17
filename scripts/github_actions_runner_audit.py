#!/usr/bin/env python3
"""Bounded GitHub Actions audit: workflows != jobs != org runner entitlement.

Reports observed GitHub-hosted/self-hosted jobs and the sampling boundary.
Never cancels/retries runs, never asserts subscription or runner quota.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import statistics
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


def _time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def request_json(path: str, params: dict, *, token: str) -> dict:
    if not token:
        raise ValueError(
            "GITHUB_TOKEN or GH_TOKEN is required for authenticated capacity audit"
        )
    url = "https://api.github.com" + path + "?" + urlencode(params)
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "hepta-gh-actions-fleet-capacity-audit/1",
        },
    )
    with urlopen(request, timeout=20) as stream:
        result = json.load(stream)
    if not isinstance(result, dict):
        raise ValueError("unexpected API result shape")
    return result


def summarize(
    repo: str,
    query,
    *,
    max_active_runs: int = 60,
    max_queued_runs: int = 8,
    old_days: int = 7,
    now: datetime | None = None,
) -> dict:
    """Return exact observed lower bounds, never extrapolate to organization capacity."""
    if "/" not in repo or repo.count("/") != 1:
        raise ValueError("repo must be OWNER/REPO")
    if not (
        1 <= max_active_runs <= 100
        and 0 <= max_queued_runs <= 20
        and 1 <= old_days <= 30
    ):
        raise ValueError("sample limits out of bounds")
    now = now or datetime.now(timezone.utc)
    prefix = f"/repos/{quote(repo, safe='/')}/actions/runs"
    counts: dict[str, int] = {}
    pages: dict[str, list] = {}
    for status in ("in_progress", "queued", "pending", "waiting", "completed"):
        response = query(prefix, {"status": status, "per_page": 100, "page": 1})
        counts[status] = int(response["total_count"])
        pages[status] = response["workflow_runs"]
    cancellations = Counter(
        run.get("conclusion") or "unknown" for run in pages["completed"]
    )
    oldest_date = (now - timedelta(days=old_days)).date().isoformat()
    oldest = query(
        prefix, {"status": "queued", "created": f"<{oldest_date}", "per_page": 5}
    )
    jobs_summary = Counter()
    labels = Counter()
    queue_seconds = []
    inspected_runs: list[dict] = []
    sample = (
        pages["in_progress"][:max_active_runs]
        + pages["queued"][:max_queued_runs]
        + oldest["workflow_runs"][:5]
    )
    seen: set[int] = set()
    job_results_complete = True
    for run in sample:
        run_id = int(run["id"])
        if run_id in seen:
            continue
        seen.add(run_id)
        path = f"{prefix}/{run_id}/jobs"
        response = query(path, {"per_page": 100, "page": 1})
        declared = int(response["total_count"])
        jobs = response["jobs"]
        if declared > len(jobs):
            job_results_complete = False
        for job in jobs:
            state = job.get("status", "unknown")
            jobs_summary[state] += 1
            if state == "in_progress":
                tag = job.get("labels") or []
                labels["self-hosted" if "self-hosted" in tag else "github-hosted"] += 1
                labels[f"label:{','.join(sorted(tag)) or '(none)'}"] += 1
            started = _time(job.get("started_at"))
            created = _time(job.get("created_at"))
            # GitHub can populate started_at on queued/unassigned jobs.
            # A timestamp alone is not proof a runner actually started work.
            if (
                state in {"in_progress", "completed"}
                and (job.get("runner_name") or job.get("runner_id"))
                and started
                and created
            ):
                queue_seconds.append(max(0, (started - created).total_seconds()))
        inspected_runs.append(
            {
                "run_id": run_id,
                "run_status": run.get("status"),
                "run_created_at": run.get("created_at"),
                "observed_job_count": len(jobs),
                "provider_reported_job_count": declared,
                "jobs_page_complete": declared <= len(jobs),
                "url": run.get("html_url"),
            }
        )
    observed = len(pages["in_progress"][:max_active_runs])
    complete_active = counts["in_progress"] == observed and job_results_complete
    return {
        "captured_at": now.isoformat(),
        "repo": repo,
        "organization_plan_known": False,
        "organization_job_concurrency_limit_known": False,
        "note": "Workflow-run counts are NOT job or available-runner counts.",
        "workflow_run_counts": counts,
        "completed_run_sample": {
            "size": len(pages["completed"]),
            "conclusions": dict(cancellations),
        },
        "old_queued_runs": {
            "older_than_days": old_days,
            "provider_reported_count": int(oldest["total_count"]),
            "examined_old_count": sum(
                _time(x["run_created_at"]) < now - timedelta(days=old_days)
                for x in inspected_runs
                if _time(x["run_created_at"])
            ),
            "old_without_jobs_in_sample": sum(
                _time(x["run_created_at"]) < now - timedelta(days=old_days)
                and x["provider_reported_job_count"] == 0
                for x in inspected_runs
                if _time(x["run_created_at"])
            ),
        },
        "job_observation": {
            "sampled_workflow_runs": len(inspected_runs),
            "sampled_all_in_progress_runs": complete_active,
            "job_pagination_complete": job_results_complete,
            "job_status_counts_lower_bound": dict(jobs_summary),
            "currently_running_jobs_lower_bound": jobs_summary["in_progress"],
            "running_job_runner_types_lower_bound": dict(labels),
            "median_started_job_queue_seconds": statistics.median(queue_seconds)
            if queue_seconds
            else None,
            "observed_started_jobs": len(queue_seconds),
        },
        "inspected_runs": inspected_runs,
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    p.add_argument("--active-runs", type=int, default=60)
    p.add_argument("--queued-runs", type=int, default=8)
    p.add_argument("--old-days", type=int, default=7)
    p.add_argument("--output", type=Path, default=Path("github-actions-capacity.json"))
    args = p.parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""

    def query(path, params):
        return request_json(path, params, token=token)

    try:
        result = summarize(
            args.repo,
            query,
            max_active_runs=args.active_runs,
            max_queued_runs=args.queued_runs,
            old_days=args.old_days,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(
            json.dumps(
                {
                    "repo": result["repo"],
                    "workflow_run_counts": result["workflow_run_counts"],
                    "running_jobs_lower_bound": result["job_observation"][
                        "currently_running_jobs_lower_bound"
                    ],
                    "complete_active_sample": result["job_observation"][
                        "sampled_all_in_progress_runs"
                    ],
                    "output": str(args.output),
                },
                sort_keys=True,
            )
        )
        return 0
    except (HTTPError, URLError, ValueError, KeyError, OSError) as exc:
        print(
            f"fleet-capacity: audit failed (no success receipt): {exc}", file=sys.stderr
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
