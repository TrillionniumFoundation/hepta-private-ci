#!/usr/bin/env python3
"""Read-only, exact-SHA CI status diagnostic for Hepta Neuron Draft PRs.

Inputs are caller-supplied GitHub Actions API snapshots. The caller MUST acquire
and authenticate those JSON bytes independently; this program does not provide
or mint provenance, model selection, NDU approval, or production authority.
"""

import argparse
import json
import re
import sys
from pathlib import Path

SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
REQUIRED_WORKFLOWS = (
    "Hepta Neuron model trial protocol",
    "Hepta Neuron native Ledger source (diagnostic)",
    "Hepta Neuron native local baseline (diagnostic)",
    "Hepta Neuron native Replay source bridge (diagnostic)",
    "Hepta Neuron real Worker/ModelPort seam (diagnostic)",
    "Hepta Neuron Supervisor active candidate diagnostic",
    "Hepta architecture convergence",
    "v8-canary",
    "blocking-ci",
)
NON_ACCEPTING_PROBES = (
    "Hepta Matrix advisory upgrade probe (non-accepting)",
)


class InvalidSnapshot(ValueError):
    pass


def _require(predicate, error):
    if not predicate:
        raise InvalidSnapshot(error)


def evaluate(snapshot, expected_sha, required=REQUIRED_WORKFLOWS):
    _require(isinstance(snapshot, dict), "snapshot must be an object")
    _require(isinstance(expected_sha, str) and SHA_RE.fullmatch(expected_sha), "invalid expected SHA")
    _require(snapshot.get("branch_sha") == expected_sha, "branch/expected SHA mismatch")
    runs = snapshot.get("workflow_runs")
    _require(isinstance(runs, list) and len(runs) <= 200, "invalid or oversized workflow runs")
    observed = {}
    seen_attempt_ids = {}
    for run in runs:
        _require(isinstance(run, dict), "run must be an object")
        name, sha = run.get("name"), run.get("head_sha")
        _require(isinstance(name, str) and bool(name), "run is missing name")
        _require(isinstance(sha, str) and SHA_RE.fullmatch(sha), "run has invalid head SHA")
        _require(type(run.get("id")) is int and run["id"] > 0, "invalid run id")
        _require(type(run.get("run_attempt")) is int and run["run_attempt"] > 0, "missing or invalid attempt")
        _require(run.get("status") in {"queued", "pending", "in_progress", "waiting", "requested", "completed"}, "invalid run status")
        _require(run.get("conclusion") in {None, "success", "failure", "cancelled", "timed_out", "action_required", "neutral", "skipped", "stale", "startup_failure"}, "invalid conclusion")
        # Historical SHA runs cannot satisfy the expected SHA's gate. Keep them
        # for diagnostic display but never substitute an old green result.
        _require(run.get("event") in {"pull_request", "workflow_dispatch", "push", "schedule", "dynamic"}, "missing or invalid event")
        if sha != expected_sha or run["event"] != "pull_request":
            continue
        identity = (run["id"], run["run_attempt"])
        if identity in seen_attempt_ids and seen_attempt_ids[identity] != name:
            raise InvalidSnapshot("workflow run identity reused across names")
        seen_attempt_ids[identity] = name
        key = (name, run["id"], run["run_attempt"])
        if key in observed and observed[key] != run:
            raise InvalidSnapshot("conflicting copies of a workflow attempt")
        observed[key] = run

    details, blockers = {}, []
    for name in required:
        candidates = [r for (n, _, _), r in observed.items() if n == name]
        if not candidates:
            details[name] = {"state": "missing", "run_id": None}
            blockers.append(name)
            continue
        # A later workflow run supersedes an older run, while reruns on the
        # same run id are distinguished by run_attempt.
        newest = max(candidates, key=lambda r: (r["id"], r["run_attempt"]))
        passed = newest["status"] == "completed" and newest.get("conclusion") == "success"
        details[name] = {
            "state": "success" if passed else "not_accepted",
            "run_id": newest["id"],
            "attempt": newest["run_attempt"],
            "status": newest["status"],
            "conclusion": newest.get("conclusion"),
        }
        if not passed:
            blockers.append(name)
    probes = {}
    for name in NON_ACCEPTING_PROBES:
        candidates = [r for (n, _, _), r in observed.items() if n == name]
        if candidates:
            newest = max(candidates, key=lambda r: (r["id"], r["run_attempt"]))
            probes[name] = {"run_id": newest["id"], "status": newest["status"], "conclusion": newest.get("conclusion")}
    return {
        "schema": "hepta.neuron.exact-sha-ci.diagnostic.v1",
        "expected_head_sha": expected_sha,
        "required_count": len(required),
        "successful_count": len(required) - len(blockers),
        "ci_all_required_success": not blockers,
        "blocking_workflows": blockers,
        "workflow_details": details,
        "non_accepting_probes": probes,
        "signed_owner_evidence_verified": False,
        "production_route_verified": False,
        "real_future_ndu_verified": False,
        "promotion_authorized": False,
        "note": "Caller-provided API data is not independently authenticated; only an exact-SHA read-only diagnostic.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = evaluate(json.loads(args.snapshot.read_text(encoding="utf-8")), args.expected_sha)
    except (OSError, json.JSONDecodeError, InvalidSnapshot) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    result = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.write_text(result, encoding="utf-8")
    print(result, end="")
    return 0 if report["ci_all_required_success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
