#!/usr/bin/env python3
"""Plan and validate fail-closed runtime.codex target-host qualification evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

PLAN_SCHEMA = "hepta.runtime-codex.target-plan.v1"
OBS_SCHEMA = "hepta.runtime-codex.target-observation.v1"
RECEIPT_SCHEMA = "hepta.runtime-codex.target-receipt.v1"
CASES = (
    "success",
    "provider_ack_loss",
    "provider_event_lag",
    "worker_kill_before_effect_entry",
    "worker_kill_after_effect_entry",
    "agentd_restart",
    "app_server_restart",
    "issuer_restart",
    "revocation_frontier_race",
)
TIMINGS = (
    "authorityClaimMs",
    "durablePrepareMs",
    "ownerDispatchMs",
    "firstTokenMs",
    "terminalMs",
    "reconcileMs",
)


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def percentile(values: list[float], percentile_value: float) -> float:
    require(bool(values), "cannot compute a percentile over an empty sample")
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile_value * len(ordered)))
    return ordered[rank - 1]


def command_plan(args: argparse.Namespace) -> None:
    require(args.iterations >= 3, "fault-matrix iterations must be at least three")
    candidate_sha = git("rev-parse", args.candidate)
    candidate_tree = git("rev-parse", f"{candidate_sha}^{{tree}}")
    plan = {
        "schema": PLAN_SCHEMA,
        "candidateSha": candidate_sha,
        "candidateTree": candidate_tree,
        "profileId": args.profile_id,
        "iterations": args.iterations,
        "cases": [
            {"case": case, "iteration": iteration}
            for case in CASES
            for iteration in range(1, args.iterations + 1)
        ],
        "requirements": {
            "realProvider": True,
            "independentIssuer": True,
            "processInstanceIdentity": True,
            "trustedClock": True,
            "antiRollbackRecovery": True,
            "blindReplayAttempts": 0,
        },
    }
    Path(args.output).write_bytes(canonical(plan))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise SystemExit(f"invalid JSONL at line {line_number}: {error}") from error
        require(isinstance(value, dict), f"observation line {line_number} is not an object")
        observations.append(value)
    require(bool(observations), "target qualification evidence is empty")
    return observations


def validate_common(observation: dict[str, Any], plan: dict[str, Any]) -> None:
    require(observation.get("schema") == OBS_SCHEMA, "unexpected target observation schema")
    require(observation.get("candidateSha") == plan["candidateSha"], "candidate SHA mismatch")
    require(observation.get("candidateTree") == plan["candidateTree"], "candidate tree mismatch")
    require(observation.get("profileId") == plan["profileId"], "target profile mismatch")
    for field in (
        "operationId",
        "targetHostId",
        "hostBootId",
        "appServerSessionId",
        "issuerSignerId",
        "providerEvidenceSha256",
        "processEvidenceSha256",
    ):
        require(isinstance(observation.get(field), str) and observation[field], f"missing {field}")
    for field in ("providerEvidenceSha256", "processEvidenceSha256"):
        require(len(observation[field]) == 64, f"{field} is not a SHA-256 digest")
        require(all(char in "0123456789abcdef" for char in observation[field]), f"{field} is not lowercase hex")
    for field in ("agentGeneration", "issuerEpoch", "revocationRevision"):
        require(isinstance(observation.get(field), int) and observation[field] > 0, f"invalid {field}")
    for field in (
        "realProvider",
        "independentIssuer",
        "processInstanceIdentityVerified",
        "trustedClockAttested",
        "antiRollbackRecoveryAttested",
    ):
        require(observation.get(field) is True, f"target evidence did not establish {field}")
    require(observation.get("blindReplayAttempts") == 0, "blind replay was observed")
    require(
        isinstance(observation.get("physicalProviderRequests"), int)
        and observation["physicalProviderRequests"] >= 0,
        "invalid physicalProviderRequests",
    )
    require(isinstance(observation.get("timings"), dict), "missing timings")
    for timing in TIMINGS:
        value = observation["timings"].get(timing)
        require(isinstance(value, (int, float)) and value >= 0, f"invalid timing {timing}")
    for field in ("peakRssBytes", "cpuMillis"):
        require(isinstance(observation.get(field), (int, float)) and observation[field] >= 0, f"invalid {field}")


def validate_case(observation: dict[str, Any]) -> None:
    case = observation["case"]
    requests = observation["physicalProviderRequests"]
    outcome = observation.get("outcome")
    terminal = observation.get("terminalObserved") is True
    if case == "success":
        require(requests == 1 and terminal and outcome == "succeeded", "success case did not complete exactly once")
    elif case == "worker_kill_before_effect_entry":
        require(requests == 0 and outcome == "definitely_unsent", "pre-entry kill crossed the effect boundary")
    elif case == "revocation_frontier_race":
        require(requests == 0 and outcome == "revoked_before_effect", "revoked request reached provider")
    elif case in {
        "provider_ack_loss",
        "worker_kill_after_effect_entry",
        "agentd_restart",
        "app_server_restart",
        "issuer_restart",
    }:
        require(requests <= 1, f"{case} duplicated the provider request")
        require(outcome in {"terminal", "held_indeterminate", "quarantined"}, f"invalid {case} outcome")
    elif case == "provider_event_lag":
        require(requests <= 1 and outcome in {"terminal", "quarantined"}, "event lag was misclassified")
    else:
        raise SystemExit(f"unknown target qualification case: {case}")


def command_verify(args: argparse.Namespace) -> None:
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    require(plan.get("schema") == PLAN_SCHEMA, "unexpected target plan schema")
    require(plan.get("candidateSha") == git("rev-parse", "HEAD"), "checkout does not match target plan")
    require(plan.get("candidateTree") == git("rev-parse", "HEAD^{tree}"), "checkout tree does not match target plan")
    thresholds = json.loads(Path(args.thresholds).read_text(encoding="utf-8"))
    require(thresholds.get("schema") == "hepta.runtime-codex.target-thresholds.v1", "unexpected threshold schema")
    observations = load_jsonl(Path(args.evidence))
    expected = {(item["case"], item["iteration"]) for item in plan["cases"]}
    seen: set[tuple[str, int]] = set()
    operation_ids: set[str] = set()
    timing_samples: dict[str, list[float]] = defaultdict(list)
    peak_rss: list[float] = []
    cpu: list[float] = []
    issuer_heads: dict[tuple[str, str], tuple[int, int]] = {}
    for observation in observations:
        validate_common(observation, plan)
        key = (observation.get("case"), observation.get("iteration"))
        require(key in expected, f"unexpected case/iteration: {key}")
        require(key not in seen, f"duplicate case/iteration: {key}")
        seen.add(key)
        operation_id = observation["operationId"]
        require(operation_id not in operation_ids, f"operation identity reused across fault cases: {operation_id}")
        operation_ids.add(operation_id)
        validate_case(observation)
        for timing in TIMINGS:
            timing_samples[timing].append(float(observation["timings"][timing]))
        peak_rss.append(float(observation["peakRssBytes"]))
        cpu.append(float(observation["cpuMillis"]))
        head_key = (observation["targetHostId"], observation["issuerSignerId"])
        candidate = (observation["issuerEpoch"], observation["revocationRevision"])
        prior = issuer_heads.get(head_key)
        if prior is not None:
            require(candidate >= prior, "issuer/revocation frontier rolled backward")
        issuer_heads[head_key] = candidate
    require(seen == expected, f"missing target cases: {sorted(expected - seen)}")

    metrics: dict[str, dict[str, float]] = {}
    for name, samples in timing_samples.items():
        metrics[name] = {
            "p50": percentile(samples, 0.50),
            "p95": percentile(samples, 0.95),
            "p99": percentile(samples, 0.99),
            "max": max(samples),
        }
    metrics["peakRssBytes"] = {
        "p95": percentile(peak_rss, 0.95),
        "p99": percentile(peak_rss, 0.99),
        "max": max(peak_rss),
    }
    metrics["cpuMillis"] = {
        "p95": percentile(cpu, 0.95),
        "p99": percentile(cpu, 0.99),
        "max": max(cpu),
    }
    for metric_name, limits in thresholds.get("metrics", {}).items():
        require(metric_name in metrics, f"threshold references unknown metric {metric_name}")
        for percentile_name, ceiling in limits.items():
            require(
                metrics[metric_name][percentile_name] <= ceiling,
                f"{metric_name}.{percentile_name} exceeded {ceiling}",
            )

    evidence_path = Path(args.evidence)
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "candidateSha": plan["candidateSha"],
        "candidateTree": plan["candidateTree"],
        "profileId": plan["profileId"],
        "planSha256": sha256_bytes(Path(args.plan).read_bytes()),
        "evidenceSha256": sha256_bytes(evidence_path.read_bytes()),
        "thresholdsSha256": sha256_bytes(Path(args.thresholds).read_bytes()),
        "observations": len(observations),
        "metrics": metrics,
        "claims": {
            "realProviderFaultMatrixValidated": True,
            "targetHostEvidenceValidated": True,
            "independentAcceptance": False,
            "activation": False,
            "promotion": False,
            "release": False,
        },
    }
    Path(args.output).write_bytes(canonical(receipt))


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--candidate", required=True)
    plan.add_argument("--profile-id", required=True)
    plan.add_argument("--iterations", type=int, default=5)
    plan.add_argument("--output", required=True)
    plan.set_defaults(func=command_plan)
    verify = commands.add_parser("verify")
    verify.add_argument("--plan", required=True)
    verify.add_argument("--evidence", required=True)
    verify.add_argument("--thresholds", required=True)
    verify.add_argument("--output", required=True)
    verify.set_defaults(func=command_verify)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
