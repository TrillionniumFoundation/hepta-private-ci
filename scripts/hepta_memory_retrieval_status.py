#!/usr/bin/env python3
"""Generate the exact-head memory.retrieval qualification manifest.

The manifest is an observation, not an approval. Required GitHub Actions checks
are accepted only from one exact workflow run and one exact run attempt per
workflow definition. Repository evidence is never assembled from independent
reruns or from jobs emitted by a different workflow path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any
from urllib.request import Request, urlopen

try:
    from scripts.hepta_memory_retrieval_policy import (
        CLAIMS,
        MAP,
        POLICY,
        REQUIRED_CHECKS,
        SECURITY_CHECKS,
    )
except ModuleNotFoundError:  # direct script execution from scripts/
    from hepta_memory_retrieval_policy import (  # type: ignore
        CLAIMS,
        MAP,
        POLICY,
        REQUIRED_CHECKS,
        SECURITY_CHECKS,
    )

SHA = re.compile(r"[0-9a-f]{40}\Z")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
MAX_RESPONSE = 8 * 1024 * 1024
CARGO_LOCK = "codex-rs/Cargo.lock"
DOCUMENTATION_ROOT = "docs/modules/memory.retrieval"
QUALIFICATION_ROOT = "qualification/memory-retrieval"
POLICY_PATH = "qualification/memory-retrieval/qualification-policy.json"
PRODUCT_COMPOSITION = "qualification/memory-retrieval/product-composition.json"
PRODUCTION_QUALIFICATION = "qualification/memory-retrieval/production-qualification.json"


class StatusError(ValueError):
    pass


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StatusError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def exact_sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise StatusError(f"{field} must be an exact lowercase Git commit")
    return value


def positive_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise StatusError(f"{field} must be a positive integer")
    return value


def nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StatusError(f"{field} must be a non-empty string")
    return value


def exact_repository(value: Any) -> str:
    if not isinstance(value, str) or not REPOSITORY.fullmatch(value):
        raise StatusError("invalid GitHub repository identity")
    return value


def git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if completed.returncode:
        raise StatusError(f"git {args[0]} failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


def commit_exists(root: Path, value: str) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", f"{value}^{{commit}}"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return completed.returncode == 0 and completed.stdout.strip() == value


def fetch_event_merge(root: Path, value: str, event_ref: str | None) -> None:
    if commit_exists(root, value):
        return
    if not isinstance(event_ref, str) or not re.fullmatch(
        r"refs/pull/[1-9][0-9]*/merge", event_ref
    ):
        raise StatusError("GitHub merge object is absent and event ref is unsafe")
    completed = subprocess.run(
        ["git", "-C", str(root), "fetch", "--no-tags", "--force", "origin", event_ref],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if completed.returncode or not commit_exists(root, value):
        raise StatusError(
            "failed to materialize the exact GitHub merge object: "
            + completed.stderr.strip()
        )


def environment_workflow_path(repository: str) -> str:
    value = os.environ.get("GITHUB_WORKFLOW_REF", "")
    prefix = repository + "/"
    if not value.startswith(prefix) or "@" not in value:
        raise StatusError("GITHUB_WORKFLOW_REF does not bind this repository")
    path = value[len(prefix):].split("@", 1)[0]
    if not re.fullmatch(r"\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml", path):
        raise StatusError("GITHUB_WORKFLOW_REF has an unsafe workflow path")
    return path


def environment_target_triple() -> str:
    completed = subprocess.run(
        ["rustc", "-vV"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode:
        raise StatusError("rustc -vV failed while binding target triple")
    for line in completed.stdout.splitlines():
        if line.startswith("host: "):
            return nonempty_string(line.removeprefix("host: "), "target_triple")
    raise StatusError("rustc -vV did not report a host target")


def load_json(path: Path) -> Any:
    data = path.read_bytes()
    if len(data) > MAX_RESPONSE:
        raise StatusError(f"JSON input exceeds {MAX_RESPONSE} bytes")
    return json.loads(data, object_pairs_hook=unique_object)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def api_json(url: str, token: str) -> Any:
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urlopen(request, timeout=30) as response:
        data = response.read(MAX_RESPONSE + 1)
    if len(data) > MAX_RESPONSE:
        raise StatusError("GitHub API response exceeds bound")
    return json.loads(data, object_pairs_hook=unique_object)


def api_check_runs(repository: str, source: str) -> list[dict[str, Any]]:
    repository = exact_repository(repository)
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise StatusError("GITHUB_TOKEN is required for live check observation")
    result: list[dict[str, Any]] = []
    for page in range(1, 21):
        value = api_json(
            f"https://api.github.com/repos/{repository}/commits/{source}/check-runs"
            f"?per_page=100&page={page}",
            token,
        )
        batch = value.get("check_runs", [])
        if not isinstance(batch, list):
            raise StatusError("GitHub check response is malformed")
        result.extend(batch)
        if len(result) >= value.get("total_count", 0) or len(batch) < 100:
            return result
    raise StatusError("GitHub check inventory pagination limit exceeded")


def action_details(
    check: dict[str, Any], repository: str
) -> tuple[int, int] | None:
    details = check.get("details_url")
    if not isinstance(details, str):
        return None
    matched = re.fullmatch(
        rf"https://github\.com/{re.escape(repository)}"
        r"/actions/runs/([0-9]+)/job/([0-9]+)",
        details,
    )
    if not matched:
        return None
    return int(matched.group(1)), int(matched.group(2))


def api_action_inventory(
    repository: str, checks: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    repository = exact_repository(repository)
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise StatusError("GITHUB_TOKEN is required for live action observation")
    required_names = set(REQUIRED_CHECKS)
    run_ids = {
        parsed[0]
        for check in checks
        if check.get("name") in required_names
        if (parsed := action_details(check, repository)) is not None
    }
    runs: list[dict[str, Any]] = []
    jobs: list[dict[str, Any]] = []
    for run_id in sorted(run_ids):
        run = api_json(
            f"https://api.github.com/repos/{repository}/actions/runs/{run_id}",
            token,
        )
        if not isinstance(run, dict):
            raise StatusError("GitHub workflow run response is malformed")
        runs.append(run)
        for page in range(1, 21):
            value = api_json(
                f"https://api.github.com/repos/{repository}/actions/runs/{run_id}/jobs"
                f"?filter=all&per_page=100&page={page}",
                token,
            )
            batch = value.get("jobs", [])
            if not isinstance(batch, list):
                raise StatusError("GitHub workflow jobs response is malformed")
            jobs.extend(batch)
            if len(batch) < 100:
                break
        else:
            raise StatusError("GitHub workflow jobs pagination limit exceeded")
    return runs, jobs


def latest_checks(checks: list[dict[str, Any]], source: str) -> dict[str, dict[str, Any]]:
    newest: dict[str, dict[str, Any]] = {}
    for check in sorted(checks, key=lambda row: row.get("id", 0)):
        if check.get("head_sha") != source:
            continue
        name = check.get("name")
        if isinstance(name, str) and name:
            newest[name] = check
    return newest


def check_observation(
    check: dict[str, Any] | None,
    expected: str,
    expected_issuer: str | None = None,
) -> dict[str, Any]:
    if not check:
        return {
            "status": "not_observed",
            "conclusion": None,
            "expected_conclusion": expected,
            "satisfied": False,
        }
    status = check.get("status")
    conclusion = check.get("conclusion")
    issuer = check.get("app", {}).get("slug")
    issuer_satisfied = expected_issuer is None or issuer == expected_issuer
    return {
        "status": status,
        "conclusion": conclusion,
        "expected_conclusion": expected,
        "satisfied": (
            status == "completed"
            and conclusion == expected
            and issuer_satisfied
        ),
        "check_id": check.get("id"),
        "details_url": check.get("details_url"),
        "issuer": issuer,
        "expected_issuer": expected_issuer,
    }


def index_runs(runs: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    indexed: dict[int, dict[str, Any]] = {}
    for run in runs:
        run_id = run.get("id")
        if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0:
            raise StatusError("workflow run id must be a positive integer")
        if run_id in indexed:
            raise StatusError(f"duplicate workflow run metadata: {run_id}")
        indexed[run_id] = run
    return indexed


def job_check_id(job: dict[str, Any], repository: str) -> int:
    url = job.get("check_run_url")
    if not isinstance(url, str):
        raise StatusError("workflow job lacks check_run_url")
    matched = re.fullmatch(
        rf"https://api\.github\.com/repos/{re.escape(repository)}"
        r"/check-runs/([0-9]+)",
        url,
    )
    if not matched:
        raise StatusError("workflow job has an invalid check_run_url")
    return int(matched.group(1))


def index_jobs(
    jobs: list[dict[str, Any]], repository: str
) -> dict[int, dict[str, Any]]:
    indexed: dict[int, dict[str, Any]] = {}
    for job in jobs:
        check_id = job_check_id(job, repository)
        if check_id in indexed:
            raise StatusError(f"duplicate workflow job for check: {check_id}")
        indexed[check_id] = job
    return indexed


def coherent_required_checks(
    checks: list[dict[str, Any]],
    source: str,
    repository: str,
    runs: list[dict[str, Any]],
    jobs: list[dict[str, Any]],
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    list[dict[str, Any]],
]:
    runs_by_id = index_runs(runs)
    jobs_by_check = index_jobs(jobs, repository)
    expected_by_workflow: dict[str, list[str]] = {}
    for name, workflow in REQUIRED_CHECKS.items():
        expected_by_workflow.setdefault(workflow, []).append(name)

    candidates: dict[str, list[dict[str, Any]]] = {
        workflow: [] for workflow in expected_by_workflow
    }
    errors: list[dict[str, Any]] = []
    required_names = set(REQUIRED_CHECKS)

    for check in checks:
        name = check.get("name")
        if name not in required_names or check.get("head_sha") != source:
            continue
        check_id = check.get("id")
        if isinstance(check_id, bool) or not isinstance(check_id, int) or check_id <= 0:
            errors.append({"check": name, "reason": "invalid_check_id"})
            continue
        parsed = action_details(check, repository)
        if parsed is None:
            errors.append(
                {"check": name, "check_id": check_id, "reason": "invalid_details_url"}
            )
            continue
        run_id, job_id = parsed
        run = runs_by_id.get(run_id)
        job = jobs_by_check.get(check_id)
        if run is None or job is None:
            errors.append(
                {
                    "check": name,
                    "check_id": check_id,
                    "run_id": run_id,
                    "reason": "missing_action_metadata",
                }
            )
            continue
        if job.get("id") != job_id or job.get("run_id") != run_id:
            errors.append(
                {
                    "check": name,
                    "check_id": check_id,
                    "run_id": run_id,
                    "reason": "job_identity_mismatch",
                }
            )
            continue
        if job.get("head_sha") != source or run.get("head_sha") != source:
            errors.append(
                {
                    "check": name,
                    "check_id": check_id,
                    "run_id": run_id,
                    "reason": "action_head_mismatch",
                }
            )
            continue
        attempt = job.get("run_attempt")
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt <= 0:
            errors.append(
                {
                    "check": name,
                    "check_id": check_id,
                    "run_id": run_id,
                    "reason": "invalid_run_attempt",
                }
            )
            continue
        expected_workflow = REQUIRED_CHECKS[name]
        candidates[expected_workflow].append(
            {
                "check": check,
                "run": run,
                "job": job,
                "run_id": run_id,
                "run_attempt": attempt,
            }
        )

    observations: dict[str, dict[str, Any]] = {}
    cohorts: dict[str, dict[str, Any]] = {}
    for workflow, expected_names in expected_by_workflow.items():
        rows = candidates[workflow]
        run_candidates = {
            row["run_id"]: row["run"] for row in rows
        }
        if not run_candidates:
            cohorts[workflow] = {
                "workflow": workflow,
                "run_id": None,
                "run_attempt": None,
                "head_sha": source,
                "complete": False,
                "satisfied": False,
            }
            for name in expected_names:
                observations[name] = {
                    "workflow": workflow,
                    **check_observation(None, "success", "github-actions"),
                }
            continue

        selected_run_id = max(run_candidates)
        selected_run = run_candidates[selected_run_id]
        selected_attempt = selected_run.get("run_attempt")
        valid_attempt = (
            not isinstance(selected_attempt, bool)
            and isinstance(selected_attempt, int)
            and selected_attempt > 0
        )
        path_matches = selected_run.get("path") == workflow
        head_matches = selected_run.get("head_sha") == source

        selected: dict[str, dict[str, Any]] = {}
        if valid_attempt:
            for row in rows:
                check = row["check"]
                name = check.get("name")
                if (
                    row["run_id"] == selected_run_id
                    and row["run_attempt"] == selected_attempt
                    and name in expected_names
                ):
                    previous = selected.get(name)
                    if previous is None or check.get("id", 0) > previous["check"].get("id", 0):
                        selected[name] = row

        for name in expected_names:
            row = selected.get(name)
            observation = check_observation(
                row["check"] if row else None,
                "success",
                "github-actions",
            )
            observation.update(
                {
                    "workflow": workflow,
                    "workflow_run_id": selected_run_id,
                    "run_attempt": selected_attempt if valid_attempt else None,
                    "job_id": row["job"].get("id") if row else None,
                }
            )
            observations[name] = observation

        complete = (
            valid_attempt
            and path_matches
            and head_matches
            and all(name in selected for name in expected_names)
        )
        satisfied = complete and all(
            observations[name]["satisfied"] for name in expected_names
        )
        cohorts[workflow] = {
            "workflow": workflow,
            "workflow_name": selected_run.get("name"),
            "run_id": selected_run_id,
            "run_attempt": selected_attempt if valid_attempt else None,
            "head_sha": selected_run.get("head_sha"),
            "event": selected_run.get("event"),
            "status": selected_run.get("status"),
            "conclusion": selected_run.get("conclusion"),
            "path_matches_policy": path_matches,
            "head_matches_candidate": head_matches,
            "required_checks": sorted(expected_names),
            "complete": complete,
            "satisfied": satisfied,
        }

    return observations, cohorts, errors


def build_hash_identity(root: Path, source: str) -> dict[str, Any]:
    workflow_paths = sorted(set(REQUIRED_CHECKS.values()))
    workflows: dict[str, dict[str, str]] = {}
    for path in workflow_paths:
        workflows[path] = {
            "git_blob_sha": git(root, "rev-parse", f"{source}:{path}"),
            "sha256": sha256_file(root / path),
        }
    test_set = {
        "required_checks": REQUIRED_CHECKS,
        "security_checks": SECURITY_CHECKS,
    }
    return {
        "cargo_lock_hash": sha256_file(root / CARGO_LOCK),
        "qualification_policy_hash": sha256_file(root / POLICY_PATH),
        "qualification_profile_hash": canonical_sha256(POLICY),
        "implementation_map_hash": sha256_file(root / MAP),
        "product_composition_hash": sha256_file(root / PRODUCT_COMPOSITION),
        "production_qualification_hash": sha256_file(
            root / PRODUCTION_QUALIFICATION
        ),
        "test_set_hash": canonical_sha256(test_set),
        "documentation_hash": git(
            root, "rev-parse", f"{source}:{DOCUMENTATION_ROOT}"
        ),
        "qualification_tree_hash": git(
            root, "rev-parse", f"{source}:{QUALIFICATION_ROOT}"
        ),
        "workflow_definitions": workflows,
    }


def build_manifest(
    root: Path,
    source: str,
    base: str,
    main: str,
    synthetic: str,
    checks: list[dict[str, Any]],
    *,
    repository: str,
    workflow_runs: list[dict[str, Any]],
    jobs: list[dict[str, Any]],
    github_merge: str,
    final_merge: str | None,
    producer_run_id: int,
    producer_run_attempt: int,
    producer_workflow: str,
    producer_job: str,
    event_name: str,
    runner_image: str,
    target_triple: str,
) -> dict[str, Any]:
    repository = exact_repository(repository)
    source = exact_sha(source, "source_head_sha")
    base = exact_sha(base, "base_sha")
    main = exact_sha(main, "main_sha")
    synthetic = exact_sha(synthetic, "deterministic_merge_sha")
    github_merge = exact_sha(github_merge, "github_merge_sha")
    if final_merge is not None:
        final_merge = exact_sha(final_merge, "final_merge_sha")
    producer_run_id = positive_integer(producer_run_id, "producer_run_id")
    producer_run_attempt = positive_integer(
        producer_run_attempt, "producer_run_attempt"
    )
    producer_workflow = nonempty_string(producer_workflow, "producer_workflow")
    producer_job = nonempty_string(producer_job, "producer_job")
    event_name = nonempty_string(event_name, "event_name")
    runner_image = nonempty_string(runner_image, "runner_image")
    target_triple = nonempty_string(target_triple, "target_triple")

    if git(root, "rev-parse", "HEAD") != source:
        raise StatusError("checkout is not the requested exact source")
    if git(root, "status", "--porcelain", "--untracked-files=normal"):
        raise StatusError("source checkout is dirty")
    for value in (source, base, main, synthetic, github_merge):
        if git(root, "rev-parse", "--verify", f"{value}^{{commit}}") != value:
            raise StatusError("manifest identity is not a commit")
    if final_merge is not None:
        if git(root, "rev-parse", "--verify", f"{final_merge}^{{commit}}") != final_merge:
            raise StatusError("final merge identity is not a commit")
        if final_merge != source:
            raise StatusError("post-merge evidence must execute on the final merge SHA")

    parents = git(root, "show", "-s", "--format=%P", synthetic).split()
    if parents != [base, source]:
        raise StatusError("deterministic merge does not have declared ordered parents")
    synthetic_tree = git(root, "rev-parse", f"{synthetic}^{{tree}}")
    if github_merge != source:
        github_parents = git(
            root, "show", "-s", "--format=%P", github_merge
        ).split()
        if github_parents != [base, source]:
            raise StatusError("GitHub merge does not have declared ordered parents")
        if git(root, "rev-parse", f"{github_merge}^{{tree}}") != synthetic_tree:
            raise StatusError("GitHub merge tree differs from deterministic merge tree")

    mapping = load_json(root / MAP)
    if not isinstance(mapping, dict) or mapping.get("module") != "memory.retrieval":
        raise StatusError("wrong implementation map")
    boundary = mapping.get("claimBoundary", {})
    if not isinstance(boundary, dict):
        raise StatusError("implementation map claimBoundary must be an object")
    for claim in CLAIMS:
        for scope in (mapping, boundary):
            value = scope.get(claim, False)
            if value is not False:
                raise StatusError(f"status generation refuses promoted claim: {claim}")

    required, cohorts, identity_errors = coherent_required_checks(
        checks,
        source,
        repository,
        workflow_runs,
        jobs,
    )
    newest = latest_checks(checks, source)
    security = {
        name: check_observation(newest.get(name), conclusion)
        for name, conclusion in SECURITY_CHECKS.items()
    }
    repository_ready = (
        not identity_errors
        and all(row["satisfied"] for row in cohorts.values())
        and all(row["satisfied"] for row in required.values())
    )
    security_ready = all(row["satisfied"] for row in security.values())
    external = [dict(row) for row in POLICY["externalGates"]]
    external_ready = all(row.get("state") == "satisfied_external" for row in external)
    hash_identity = build_hash_identity(root, source)

    if event_name not in {"pull_request", "push"}:
        raise StatusError("qualification manifest must come from pull_request or push")
    if event_name == "pull_request":
        if final_merge is not None or github_merge == source:
            raise StatusError("pull-request evidence must bind a distinct GitHub merge")
    else:
        if final_merge != source or github_merge != source or main != source:
            raise StatusError("push evidence must bind the exact final main merge SHA")

    producer_identity = {
        "workflow_run_id": producer_run_id,
        "attempt_id": producer_run_attempt,
        "workflow": producer_workflow,
        "job": producer_job,
        "event": event_name,
        "runner_image": runner_image,
        "target_triple": target_triple,
    }
    producer_cohort = cohorts.get(producer_workflow, {})
    candidate_identity_satisfied = (
        producer_workflow
        == ".github/workflows/hepta-memory-retrieval-convergence.yml"
        and producer_cohort.get("run_id") == producer_run_id
        and producer_cohort.get("run_attempt") == producer_run_attempt
        and producer_cohort.get("head_sha") == source
        and not identity_errors
    )
    merge_ready = (
        candidate_identity_satisfied
        and repository_ready
        and security_ready
    )
    production_qualified = merge_ready and external_ready

    artifact_hashes = {
        "source_tree_git_sha": git(root, "rev-parse", f"{source}^{{tree}}"),
        "deterministic_merge_tree_git_sha": synthetic_tree,
        "github_merge_tree_git_sha": git(
            root, "rev-parse", f"{github_merge}^{{tree}}"
        ),
        "implementation_map_sha256": hash_identity["implementation_map_hash"],
        "qualification_policy_sha256": hash_identity["qualification_policy_hash"],
    }
    return {
        "schema": "hepta.memory-retrieval.qualification-manifest.v2",
        "module": "memory.retrieval",
        "repository": repository,
        "source_head_sha": source,
        "frozen_source_sha": source,
        "source_sha": source,
        "tree_sha": artifact_hashes["source_tree_git_sha"],
        "main_sha": main,
        "base_sha": base,
        "synthetic_base_sha": base,
        "deterministic_merge_sha": synthetic,
        "synthetic_merge_sha": synthetic,
        "synthetic_merge_tree_sha": synthetic_tree,
        "github_merge_sha": github_merge,
        "final_merge_sha": final_merge,
        "producer": producer_identity,
        "workflow_run_id": producer_run_id,
        "attempt_id": producer_run_attempt,
        "runner_image": runner_image,
        "target_triple": target_triple,
        **hash_identity,
        "artifact_hashes": artifact_hashes,
        "workflow_cohorts": cohorts,
        "check_identity_errors": identity_errors,
        "required_checks": required,
        "security_checks": security,
        "e2e_evidence": dict(POLICY["e2eEvidence"]),
        "calibration_evidence": dict(POLICY["calibrationEvidence"]),
        "external_gates": external,
        "independent_acceptance": False,
        "activation_mode": POLICY["activationMode"],
        "claim_boundary": dict(POLICY["claimBoundary"]),
        "candidate_identity_satisfied": candidate_identity_satisfied,
        "repository_checks_satisfied": repository_ready,
        "security_checks_satisfied": security_ready,
        "external_gates_satisfied": external_ready,
        "mergeReady": merge_ready,
        "productionQualified": production_qualified,
        "merge_ready": merge_ready,
        "production_ready": production_qualified,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--source", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--main", required=True)
    parser.add_argument("--synthetic-merge", required=True)
    parser.add_argument("--github-merge")
    parser.add_argument("--final-merge")
    parser.add_argument("--checks-json", type=Path)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--producer-run-id", type=int)
    parser.add_argument("--producer-run-attempt", type=int)
    parser.add_argument("--producer-workflow")
    parser.add_argument("--producer-job")
    parser.add_argument("--event-name")
    parser.add_argument("--runner-image")
    parser.add_argument("--target-triple")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        repository = exact_repository(args.repository)
        event_name = args.event_name or os.environ.get("GITHUB_EVENT_NAME")
        event_name = nonempty_string(event_name, "event_name")
        github_merge = args.github_merge or os.environ.get("GITHUB_SHA")
        github_merge = exact_sha(github_merge, "github_merge_sha")
        if event_name == "pull_request":
            fetch_event_merge(
                args.root,
                github_merge,
                os.environ.get("GITHUB_REF"),
            )
        final_merge = args.final_merge
        if final_merge is None and event_name == "push":
            final_merge = exact_sha(args.source, "source_head_sha")
        producer_run_id = (
            args.producer_run_id
            if args.producer_run_id is not None
            else int(os.environ.get("GITHUB_RUN_ID", "0"))
        )
        producer_run_attempt = (
            args.producer_run_attempt
            if args.producer_run_attempt is not None
            else int(os.environ.get("GITHUB_RUN_ATTEMPT", "0"))
        )
        producer_workflow = (
            args.producer_workflow
            or environment_workflow_path(repository)
        )
        producer_job = (
            args.producer_job or os.environ.get("GITHUB_JOB")
        )
        runner_image = args.runner_image or "/".join(
            filter(
                None,
                (
                    os.environ.get("ImageOS") or os.environ.get("RUNNER_OS"),
                    os.environ.get("ImageVersion")
                    or os.environ.get("RUNNER_ARCH"),
                ),
            )
        )
        target_triple = args.target_triple or environment_target_triple()

        if args.checks_json:
            payload = load_json(args.checks_json)
            if not isinstance(payload, dict):
                raise StatusError("offline inventory must be an object")
            checks = payload.get("check_runs", [])
            workflow_runs = payload.get("workflow_runs", [])
            jobs = payload.get("jobs", [])
            if not all(isinstance(value, list) for value in (
                checks, workflow_runs, jobs
            )):
                raise StatusError("offline action inventory is malformed")
        else:
            checks = api_check_runs(
                repository, exact_sha(args.source, "source_head_sha")
            )
            workflow_runs, jobs = api_action_inventory(
                repository, checks
            )
        manifest = build_manifest(
            args.root,
            args.source,
            args.base,
            args.main,
            args.synthetic_merge,
            checks,
            repository=repository,
            workflow_runs=workflow_runs,
            jobs=jobs,
            github_merge=github_merge,
            final_merge=final_merge,
            producer_run_id=producer_run_id,
            producer_run_attempt=producer_run_attempt,
            producer_workflow=producer_workflow,
            producer_job=producer_job,
            event_name=event_name,
            runner_image=runner_image,
            target_triple=target_triple,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        )
        print(args.output)
    except (
        StatusError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.TimeoutExpired,
    ) as error:
        print(f"memory.retrieval status refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
