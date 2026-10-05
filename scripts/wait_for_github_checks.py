#!/usr/bin/env python3
"""Wait for named GitHub check runs and fail closed on any non-success result."""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable


class CheckError(RuntimeError):
    pass


@dataclass(frozen=True)
class CheckState:
    name: str
    status: str
    conclusion: str | None
    check_run_id: int
    details_url: str | None


def evaluate_check_runs(
    payload: dict[str, Any], required_names: Iterable[str]
) -> tuple[dict[str, CheckState], list[str]]:
    runs = payload.get("check_runs")
    if not isinstance(runs, list):
        raise CheckError("GitHub check-runs response omitted check_runs")
    latest: dict[str, dict[str, Any]] = {}
    required = set(required_names)
    for run in runs:
        if not isinstance(run, dict) or run.get("name") not in required:
            continue
        name = run["name"]
        identifier = run.get("id")
        if not isinstance(identifier, int):
            raise CheckError(f"check run {name!r} omitted its numeric id")
        if name not in latest or identifier > latest[name]["id"]:
            latest[name] = run

    states: dict[str, CheckState] = {}
    pending: list[str] = []
    for name in sorted(required):
        run = latest.get(name)
        if run is None:
            pending.append(name)
            continue
        status = run.get("status")
        conclusion = run.get("conclusion")
        if status not in {"queued", "in_progress", "completed", "pending", "waiting"}:
            raise CheckError(f"check run {name!r} has unknown status {status!r}")
        if status != "completed":
            pending.append(name)
        states[name] = CheckState(
            name=name,
            status=status,
            conclusion=conclusion if isinstance(conclusion, str) else None,
            check_run_id=run["id"],
            details_url=run.get("details_url")
            if isinstance(run.get("details_url"), str)
            else None,
        )
    return states, pending


def fetch_check_runs(repository: str, sha: str, token: str) -> dict[str, Any]:
    url = f"https://api.github.com/repos/{repository}/commits/{sha}/check-runs?per_page=100"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "runtime-codex-required-fan-in",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise CheckError(f"failed to read GitHub check runs: {error}") from error


def wait_for_checks(
    repository: str,
    sha: str,
    token: str,
    names: list[str],
    timeout_seconds: int,
    interval_seconds: int,
) -> dict[str, CheckState]:
    deadline = time.monotonic() + timeout_seconds
    last_states: dict[str, CheckState] = {}
    while True:
        payload = fetch_check_runs(repository, sha, token)
        states, pending = evaluate_check_runs(payload, names)
        if states != last_states:
            print(
                json.dumps(
                    {
                        name: {
                            "id": state.check_run_id,
                            "status": state.status,
                            "conclusion": state.conclusion,
                            "detailsUrl": state.details_url,
                        }
                        for name, state in sorted(states.items())
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            last_states = states
        failures = [
            state
            for state in states.values()
            if state.status == "completed" and state.conclusion != "success"
        ]
        if failures:
            details = ", ".join(
                f"{state.name}={state.conclusion}@{state.details_url or state.check_run_id}"
                for state in failures
            )
            raise CheckError(f"required runtime.codex check failed: {details}")
        if not pending and len(states) == len(names):
            return states
        if time.monotonic() >= deadline:
            missing = ", ".join(pending or sorted(set(names) - set(states)))
            raise CheckError(f"timed out waiting for runtime.codex checks: {missing}")
        time.sleep(interval_seconds)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    value.add_argument("--sha", default=os.environ.get("GITHUB_SHA"))
    value.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
    value.add_argument("--timeout-seconds", type=int, default=7200)
    value.add_argument("--interval-seconds", type=int, default=15)
    value.add_argument("checks", nargs="+")
    return value


def main() -> None:
    args = parser().parse_args()
    if not args.repository or "/" not in args.repository:
        raise SystemExit("an owner/repository identity is required")
    if not args.sha or len(args.sha) != 40:
        raise SystemExit("an exact 40-character commit SHA is required")
    if not args.token:
        raise SystemExit("GITHUB_TOKEN is required")
    if not 60 <= args.timeout_seconds <= 10800:
        raise SystemExit("timeout must be in 60..=10800 seconds")
    if not 5 <= args.interval_seconds <= 60:
        raise SystemExit("poll interval must be in 5..=60 seconds")
    wait_for_checks(
        args.repository,
        args.sha,
        args.token,
        args.checks,
        args.timeout_seconds,
        args.interval_seconds,
    )


if __name__ == "__main__":
    main()
