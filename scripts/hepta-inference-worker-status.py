#!/usr/bin/env python3
"""Generate the exact inference.worker qualification status artifact.

The tracked repository contains this generator, not a self-referential commit
SHA. CI runs it after all qualification jobs complete and uploads the JSON
artifact bound to the exact source head/tree and mapped blob objects.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_TOP_LEVEL = {
    "schema",
    "module",
    "source_head",
    "source_tree",
    "source_blob_digests",
    "last_exact_head_run",
    "last_merge_candidate_run",
    "linux_result",
    "macos_result",
    "lib_test_result",
    "binary_test_result",
    "clippy_result",
    "real_hardware_result",
    "composition_result",
    "independent_acceptance_result",
    "profiles",
    "reconciliation",
}


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def source_blobs() -> dict[str, str]:
    paths = git(
        "ls-files",
        "codex-rs/hepta-infer-worker-host",
        "codex-rs/hepta-infer-core/src/native_control.rs",
        "docs/modules/inference.worker",
        "qualification/module-execution-dossiers/detail/inference.worker.md",
        "scripts/hepta-inference-worker-status.py",
        ".github/workflows/inference-worker-qualification.yml",
    ).splitlines()
    return {
        path: git("rev-parse", f"HEAD:{path}")
        for path in sorted(path for path in paths if path)
    }


def github_jobs(repository: str, run_id: str, token: str) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    page = 1
    while True:
        url = (
            f"https://api.github.com/repos/{repository}/actions/runs/{run_id}/jobs"
            f"?per_page=100&page={page}"
        )
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "hepta-inference-worker-status",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
        batch = payload.get("jobs", [])
        if not isinstance(batch, list):
            raise ValueError("GitHub jobs response is not a list")
        jobs.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return jobs


def normalized_result(values: list[str | None]) -> str:
    concrete = [value for value in values if value]
    if not concrete:
        return "not_run"
    for terminal in ("failure", "cancelled", "timed_out", "action_required"):
        if terminal in concrete:
            return terminal
    if any(value in {"queued", "in_progress", "waiting", "pending"} for value in concrete):
        return "in_progress"
    if all(value in {"success", "skipped", "neutral"} for value in concrete):
        return "success" if "success" in concrete else concrete[0]
    return ",".join(sorted(set(concrete)))


def job_result(jobs: list[dict[str, Any]], name: str) -> str:
    matches = [job.get("conclusion") or job.get("status") for job in jobs if job.get("name") == name]
    return normalized_result(matches)


def platform_result(jobs: list[dict[str, Any]], platform: str) -> str:
    matches = [
        job.get("conclusion") or job.get("status")
        for job in jobs
        if f"({platform})" in str(job.get("name", ""))
    ]
    return normalized_result(matches)


def step_result(jobs: list[dict[str, Any]], step_name: str) -> str:
    values: list[str | None] = []
    for job in jobs:
        for step in job.get("steps", []):
            if step.get("name") == step_name:
                values.append(step.get("conclusion") or step.get("status"))
    return normalized_result(values)


def build_status(jobs: list[dict[str, Any]], run_id: str, run_attempt: str) -> dict[str, Any]:
    exact = job_result(jobs, "Exact source and derived truth")
    merge = job_result(jobs, "Deterministic synthetic merge")
    return {
        "schema": "hepta.inference-worker-current-status.v1",
        "module": "inference.worker",
        "source_head": git("rev-parse", "HEAD"),
        "source_tree": git("rev-parse", "HEAD^{tree}"),
        "source_blob_digests": source_blobs(),
        "last_exact_head_run": {
            "run_id": run_id,
            "run_attempt": run_attempt,
            "result": exact,
        },
        "last_merge_candidate_run": {
            "run_id": run_id,
            "run_attempt": run_attempt,
            "result": merge,
        },
        "linux_result": platform_result(jobs, "ubuntu-24.04"),
        "macos_result": platform_result(jobs, "macos-15"),
        "lib_test_result": step_result(jobs, "Run focused library tests"),
        "binary_test_result": step_result(jobs, "Compile explicit binary where present"),
        "clippy_result": step_result(jobs, "Strict owner lint"),
        "real_hardware_result": "not_proved_by_repository_ci",
        "composition_result": "not_proved_by_inference_worker_qualification",
        "independent_acceptance_result": "not_proved",
        "profiles": {
            "HostedAppServerWorker": "production-candidate",
            "LocalModelWorker": "experimental-non-production",
            "LegacyReceiptBoundary": "validation-only",
        },
        "reconciliation": {
            "exact_app_server_thread_history": "implemented",
            "missing_history_resolution": "verified-external-receipt-port-implemented; deployed-authority-not-proved",
            "trusted_token_usage_reconciliation": "verified-external-receipt-port-implemented; provider-evidence-not-proved",
            "real_provider_target_host_qualification": "not_proved",
        },
    }


def validate_status(status: dict[str, Any]) -> None:
    missing = REQUIRED_TOP_LEVEL.difference(status)
    if missing:
        raise ValueError(f"status is missing fields: {sorted(missing)}")
    for field in ("source_head", "source_tree"):
        value = status[field]
        if not isinstance(value, str) or len(value) != 40:
            raise ValueError(f"{field} must be a Git SHA-1")
    blobs = status["source_blob_digests"]
    if not isinstance(blobs, dict) or not blobs:
        raise ValueError("source_blob_digests must be a nonempty object")
    if status["profiles"] != {
        "HostedAppServerWorker": "production-candidate",
        "LocalModelWorker": "experimental-non-production",
        "LegacyReceiptBoundary": "validation-only",
    }:
        raise ValueError("profile claim ceilings drifted")
    if status["real_hardware_result"] == "success" or status["independent_acceptance_result"] == "success":
        raise ValueError("repository CI cannot self-assert external evidence")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check-schema", action="store_true")
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", "local"))
    parser.add_argument("--run-attempt", default=os.environ.get("GITHUB_RUN_ATTEMPT", "1"))
    args = parser.parse_args()

    if args.check_schema:
        sample = build_status([], "schema-check", "1")
        validate_status(sample)
        return 0

    repository = os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GITHUB_TOKEN")
    jobs = github_jobs(repository, args.run_id, token) if repository and token else []
    status = build_status(jobs, args.run_id, args.run_attempt)
    validate_status(status)
    rendered = json.dumps(status, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
