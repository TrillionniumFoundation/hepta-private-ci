#!/usr/bin/env python3
"""Read-only, fail-closed, exact-SHA CI evidence check for Hepta shadow work.

Run GitHub API collection *after* checks finish. This never authenticates a
model artifact, issues Final-use permission, or approves a Cell for production.
Do not infer status from a different commit's checks or a workflow display URL.
"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
from typing import Any

SHA = re.compile(r"^[0-9a-f]{40}$")
REQUIRED_WORKFLOWS = (
    "Hepta Neuron Stem Shadow Qualification",
    "Hepta Stem-Head Worker Bridge Shadow Qualification",
    "Hepta architecture convergence",
    "v8-canary",
    "blocking-ci",
)
SECURITY_JOB = "cargo-deny / cargo-deny"


def sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False,
                   separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _records(value: Any, key: str) -> list[dict]:
    if not isinstance(value, dict) or not isinstance(value.get(key), list):
        raise ValueError(f"GitHub API payload must contain list {key!r}")
    records = value[key]
    if any(not isinstance(row, dict) for row in records):
        raise ValueError(f"malformed GitHub API {key!r} entries")
    return records


def _best_attempts(head_sha: str, records: list[dict]) -> dict[str, dict]:
    buckets = defaultdict(list)
    for entry in records:
        if entry.get("name") not in REQUIRED_WORKFLOWS:
            continue
        if entry.get("head_sha") != head_sha or entry.get("event") != "pull_request":
            # A success on a base-merge, branch push or previous SHA cannot
            # authorize the exact source tree under consideration.
            continue
        if type(entry.get("id")) is not int or entry["id"] <= 0:
            raise ValueError("workflow run lacks a stable positive GitHub run id")
        if type(entry.get("run_attempt", 1)) is not int or entry.get("run_attempt", 1) <= 0:
            raise ValueError("malformed workflow attempt")
        if type(entry.get("run_number", 0)) is not int:
            raise ValueError("malformed workflow run number")
        buckets[entry["name"]].append(entry)
    selected = {}
    for name, attempts in buckets.items():
        # The latest run/attempt wins, not an earlier convenient success.
        key = lambda row: (row.get("run_number", 0), row.get("run_attempt", 1), row["id"])
        selected[name] = max(attempts, key=key)
    return selected


def qualify(head_sha: str, runs: Any, jobs: Any) -> dict:
    """Check real GitHub run+job envelopes. No source or owner attestation."""
    if not isinstance(head_sha, str) or not SHA.fullmatch(head_sha):
        raise ValueError("expected exact lowercase 40-hex commit SHA")
    records = _records(runs, "workflow_runs")
    if (type(runs.get("total_count")) is int
            and runs["total_count"] > len(records)):
        raise ValueError("GitHub workflow_runs pagination incomplete")
    if not isinstance(jobs, dict):
        raise ValueError("jobs must be a run-id -> GitHub jobs payload map")
    selected = _best_attempts(head_sha, records)
    blockers = []
    evidence = []
    for name in REQUIRED_WORKFLOWS:
        run = selected.get(name)
        if run is None:
            blockers.append(f"missing exact-head pull_request workflow: {name}")
            continue
        run_id = run["id"]
        if run.get("status") != "completed" or run.get("conclusion") != "success":
            blockers.append(f"workflow {name} not successful on exact head: "
                            f"{run.get('status')}/{run.get('conclusion')}")
        packet = jobs.get(str(run_id))
        if packet is None:
            blockers.append(f"missing authoritative jobs for workflow {name} (run {run_id})")
            continue
        run_jobs = _records(packet, "jobs")
        if (type(packet.get("total_count")) is int
                and packet["total_count"] > len(run_jobs)):
            blockers.append(f"GitHub jobs pagination incomplete for {name}")
        if not run_jobs:
            blockers.append(f"workflow {name} returned zero jobs")
        seen_jobs = set()
        completed_success = 0
        for job in run_jobs:
            job_name = job.get("name")
            if not isinstance(job_name, str) or not job_name:
                blockers.append(f"unnamed job in {name}")
                continue
            if job_name in seen_jobs:
                blockers.append(f"duplicate job name in {name}: {job_name}")
            seen_jobs.add(job_name)
            if job.get("status") != "completed":
                blockers.append(f"unfinished job in {name}: {job_name}")
            conclusion = job.get("conclusion")
            if conclusion in ("failure", "cancelled", "timed_out", "action_required", None):
                blockers.append(f"failed/cancelled/incomplete job in {name}: "
                                f"{job_name} [{conclusion}]")
            elif conclusion == "success":
                completed_success += 1
            elif conclusion not in ("skipped", "neutral"):
                blockers.append(f"unrecognized job status in {name}: {job_name} [{conclusion}]")
        if completed_success == 0:
            blockers.append(f"no genuinely successful job in {name}")
        if name == "blocking-ci":
            matches = [j for j in run_jobs if j.get("name") == SECURITY_JOB]
            if len(matches) != 1 or matches[0].get("status") != "completed" or matches[0].get("conclusion") != "success":
                blockers.append("cargo-deny must have one completed successful security Job")
        evidence.append({
            "workflow": name,
            "run_id": run_id,
            "run_attempt": run.get("run_attempt", 1),
            "status": run.get("status"),
            "conclusion": run.get("conclusion"),
            "jobs_digest": sha256(run_jobs),
        })
    passed = not blockers
    return {
        "schema": "hepta.neuron.exact-sha-shadow-ci-evidence.v1",
        "source_head_sha": head_sha,
        "status": "all_required_ci_passed_shadow_only" if passed else "blocked",
        "exact_sha_ci_gate_passed": passed,
        "production_promotion_permitted": False,
        "independent_signed_final_use_verified": False,
        "real_jina_weights_executed": False,
        "target_host_4096_cell_qualified": False,
        "source_artifact_CAS_recovery_verified": False,
        "required_workflows": list(REQUIRED_WORKFLOWS),
        "workflow_evidence": evidence,
        "blocking_reasons": sorted(set(blockers)),
        "runs_input_sha256": sha256(runs),
        "job_inputs_sha256": sha256(jobs),
        "limitations": [
            "Unsigned GitHub API JSON is not a cryptographic CI/build attestation",
            "This does not prove a protected runner, reproducible build or merge-result SHA",
            "Green CI is not NDU, checkpoint CAS, model-load or production Final-use proof",
            "Any changed final composition must be checked on a new exact SHA",
        ],
    }


def _json(path):
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream, parse_constant=lambda value:
                         (_ for _ in ()).throw(ValueError("invalid JSON constant: " + value)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--runs-json", required=True)
    parser.add_argument("--jobs-json", required=True,
                        help="JSON map {GitHub-run-id: {jobs: [...]}}")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    target = Path(args.output)
    if target.exists():
        raise SystemExit("refusing to overwrite prior exact-SHA CI evidence")
    result = qualify(args.head_sha, _json(args.runs_json), _json(args.jobs_json))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    if not result["exact_sha_ci_gate_passed"]:
        raise SystemExit("BLOCKED: " + "; ".join(result["blocking_reasons"]))


if __name__ == "__main__":
    main()
