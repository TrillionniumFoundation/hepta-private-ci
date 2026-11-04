#!/usr/bin/env python3
"""Fail-closed read-only latest-PR-SHA GitHub CI convergence classifier.

Only accepts captured GitHub REST JSON as observations. No JWT/signature/route
trust can be inferred from these self-contained files; never use as production
promotion or NDU authority. CI success means the observed workflow run reached
GitHub's success state for the currently observed PR head, not that it is safe.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any

SHA = re.compile(r"[0-9a-f]{40}\Z")
REQUIRED = (
    "Hepta Neuron model trial protocol",
    "Hepta Neuron native Ledger source (diagnostic)",
    "Hepta Neuron native local baseline (diagnostic)",
    "Hepta Neuron native Replay source bridge (diagnostic)",
    "Hepta Neuron Supervisor active candidate diagnostic",
    "Hepta Neuron real Worker/ModelPort seam (diagnostic)",
    "Hepta architecture convergence",
    "v8-canary",
    "blocking-ci",
)
MATRIX = "Hepta Matrix advisory upgrade probe (non-accepting)"
SCHEMA = "hepta.neuron.ci-convergence.observation.v1"


class EvidenceError(ValueError):
    """Malformed evidence, ambiguous head, or unsupported capture."""


def _json_file(path: str | Path) -> dict[str, Any]:
    try:
        raw = Path(path).read_bytes()
        if len(raw) > 16_000_000:
            raise EvidenceError("oversize evidence snapshot")
        result = json.loads(raw)
    except (OSError, UnicodeError, ValueError) as error:
        raise EvidenceError(f"cannot read evidence: {error}") from error
    if not isinstance(result, dict):
        raise EvidenceError("GitHub REST result must be an object")
    return result


def _sha(value: Any) -> str:
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise EvidenceError("invalid 40-char SHA")
    return value


def _datetime(s: Any) -> datetime:
    if not isinstance(s, str) or not s.endswith("Z"):
        raise EvidenceError("workflow creation time must be UTC RFC3339")
    try:
        dt = datetime.fromisoformat(s[:-1] + "+00:00")
    except ValueError as e:
        raise EvidenceError("invalid workflow timestamp") from e
    if dt.tzinfo is None:
        raise EvidenceError("naive workflow timestamp")
    return dt


def _pr_id(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise EvidenceError("invalid PR number")
    return value


def _url(repo: str, run_id: int) -> str:
    return f"https://github.com/{repo}/actions/runs/{run_id}"


def classify(
    pr: dict[str, Any],
    branch_ref: dict[str, Any],
    runs: dict[str, Any],
    *,
    repo: str,
    pr_number: int,
    expected_sha: str,
    expected_branch: str,
) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise EvidenceError("invalid repository")
    pr_number = _pr_id(pr_number)
    expected_sha = _sha(expected_sha)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", expected_branch):
        raise EvidenceError("invalid expected branch")
    if branch_ref.get("ref") != "refs/heads/" + expected_branch:
        raise EvidenceError("wrong branch ref")
    if _pr_id(pr.get("number")) != pr_number:
        raise EvidenceError("PR number mismatch")
    if pr.get("state") != "open" or pr.get("draft") is not True:
        raise EvidenceError("experimental PR must be open and Draft")
    target_repo = pr.get("base", {}).get("repo", {}).get("full_name")
    if target_repo is not None and target_repo != repo:
        raise EvidenceError("PR belongs to another repository")
    pr_sha = _sha(pr.get("head", {}).get("sha"))
    branch_sha = _sha(branch_ref.get("object", {}).get("sha"))
    if pr_sha != expected_sha or branch_sha != expected_sha:
        # HEAD drift is not a malformed observation; it is a safety blocker.
        head_consistent = False
    else:
        head_consistent = True
    arr = runs.get("workflow_runs")
    if not isinstance(arr, list) or len(arr) > 1000:
        raise EvidenceError("missing or oversized workflow_runs array")
    by_name: dict[str, list[dict[str, Any]]] = {}
    for row in arr:
        if not isinstance(row, dict):
            raise EvidenceError("malformed workflow run")
        name = row.get("name")
        if name not in (*REQUIRED, MATRIX):
            continue
        sha = _sha(row.get("head_sha"))
        if sha != expected_sha:
            continue
        if row.get("event") not in ("pull_request", "workflow_dispatch"):
            raise EvidenceError("unsupported workflow event in evidence")
        if not isinstance(row.get("id"), int) or isinstance(row["id"], bool) or row["id"] <= 0:
            raise EvidenceError("invalid workflow run id")
        if row.get("status") not in ("queued", "pending", "in_progress", "completed", "requested", "waiting"):
            raise EvidenceError("unknown workflow run state")
        # An explicitly triggered diagnostic can be described, but is not
        # evidence of the mandatory PR head check.
        by_name.setdefault(name, []).append(row)
    findings: dict[str, dict[str, Any]] = {}
    for name in (*REQUIRED, MATRIX):
        rows = by_name.get(name, [])
        pr_rows = [r for r in rows if r.get("event") == "pull_request"]
        if not pr_rows:
            findings[name] = {"state": "missing", "run_id": None, "url": None, "conclusion": None}
            continue
        # Current/latest attempt controls the verdict; a prior success on the
        # same SHA cannot hide a later failed/queued rerun.
        latest = max(pr_rows, key=lambda r: (_datetime(r.get("created_at")), r.get("run_attempt", 1), r["id"]))
        status = latest["status"]
        conclusion = latest.get("conclusion")
        if status == "completed":
            if conclusion not in ("success", "failure", "cancelled", "timed_out", "action_required", "neutral", "skipped", "stale", "startup_failure"):
                raise EvidenceError("invalid completed conclusion")
            state = "success" if conclusion == "success" else "failed"
        else:
            if conclusion is not None:
                raise EvidenceError("pending run cannot have conclusion")
            state = "incomplete"
        findings[name] = {
            "state": state,
            "run_id": latest["id"],
            "url": _url(repo, latest["id"]),
            "conclusion": conclusion,
            "status": status,
        }
    succeeded = all(findings[name]["state"] == "success" for name in REQUIRED)
    # Matrix probe is explicitly non-accepting. Even a successful probe does
    # NOT prove deployment: only actual patched/upgraded production dependencies
    # and a clean cargo-deny would. Preserve uncertainty instead of guessing.
    matrix = findings[MATRIX]["state"]
    return {
        "schema": SCHEMA,
        "repository": repo,
        "pr": pr_number,
        "expected_head_sha": expected_sha,
        "expected_branch": expected_branch,
        "observed_pr_head_sha": pr_sha,
        "observed_branch_head_sha": branch_sha,
        "head_consistent": head_consistent,
        "all_required_workflows_success_at_observed_head": head_consistent and succeeded,
        "matrix_upgrade_probe": matrix,
        "matrix_production_upgrade_verified": False,
        "production_no_change_selection_verified": False,
        "real_future_window_ndu_verified": False,
        "promotion_authorized": False,
        "source_is_unsigned_api_capture": True,
        "checks": findings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr", type=Path, required=True)
    parser.add_argument("--ref", type=Path, required=True)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--number", type=int, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = classify(
            _json_file(args.pr), _json_file(args.ref), _json_file(args.runs),
            repo=args.repo, pr_number=args.number, expected_sha=args.expected_sha,
            expected_branch=args.branch,
        )
    except EvidenceError as error:
        print(f"FAIL-CLOSED: {error}", file=sys.stderr)
        return 2
    # New, private local output; never overwrite any existing evidence.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, sort_keys=True, indent=2)
            stream.write("\n")
    except (OSError, FileExistsError) as error:
        print(f"FAIL-CLOSED: cannot create output: {error}", file=sys.stderr)
        return 2
    print(f"HEAD={args.expected_sha} convergence={'YES' if report['all_required_workflows_success_at_observed_head'] else 'NO'} promotion=DENIED")
    return 0 if report["all_required_workflows_success_at_observed_head"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
