#!/usr/bin/env python3
"""Plan and diagnose supplied runtime.codex observations without qualifying a target.

Exit zero means only that the supplied data passed local consistency checks.
Provider/process evidence, issuer independence, trusted time and anti-rollback
claims are not authenticated here. Every diagnostic receipt retains HOLD.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

PLAN_SCHEMA = "hepta.runtime-codex.target-plan.v1"
OBS_SCHEMA = "hepta.runtime-codex.target-observation.v1"
RECEIPT_SCHEMA = "hepta.runtime-codex.target-diagnostic.v1"
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
    return subprocess.check_output(["git", "--no-replace-objects", *args], text=True).strip()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)



def parse_json(raw: bytes | str, label: str) -> Any:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate key {key}")
            value[key] = item
        return value

    def reject_constant(value: str) -> Any:
        raise ValueError(f"non-finite JSON number {value}")

    try:
        return json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)
    except (ValueError, UnicodeError) as error:
        raise SystemExit(f"invalid {label}: {error}") from error


def finite_nonnegative(value: Any) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def validate_plan(plan: Any) -> set[tuple[str, int]]:
    require(isinstance(plan, dict), "target plan must be an object")
    require(plan.get("schema") == PLAN_SCHEMA, "unexpected target plan schema")
    for name in ("candidateSha", "candidateTree"):
        require(isinstance(plan.get(name), str) and re.fullmatch(r"[0-9a-f]{40}", plan[name]) is not None,
                f"invalid plan {name}")
    profile = plan.get("profileId")
    require(isinstance(profile, str) and bool(profile) and profile.strip() == profile,
            "invalid target profile")
    iterations = plan.get("iterations")
    require(type(iterations) is int and iterations >= 3,
            "fault-matrix iterations must be at least three")
    cases = plan.get("cases")
    require(isinstance(cases, list) and len(cases) == len(CASES) * iterations,
            "plan must contain every required case and iteration exactly once")
    expected = {(case, iteration) for case in CASES for iteration in range(1, iterations + 1)}
    actual: set[tuple[str, int]] = set()
    for item in cases:
        require(isinstance(item, dict) and set(item) == {"case", "iteration"},
                "invalid plan case entry")
        require(isinstance(item["case"], str) and type(item["iteration"]) is int,
                "invalid plan case/iteration type")
        key = (item["case"], item["iteration"])
        require(key in expected and key not in actual, "unexpected or duplicate plan case/iteration")
        actual.add(key)
    require(actual == expected, "incomplete target plan")
    requirements = plan.get("requirements")
    required = {
        "realProvider": True,
        "independentIssuer": True,
        "processInstanceIdentity": True,
        "trustedClock": True,
        "antiRollbackRecovery": True,
        "blindReplayAttempts": 0,
    }
    require(isinstance(requirements, dict) and set(requirements) == set(required),
            "invalid plan requirements")
    for name, expected_value in required.items():
        require(type(requirements[name]) is type(expected_value) and requirements[name] == expected_value,
                f"invalid plan requirement {name}")
    return expected


def validate_thresholds(thresholds: Any) -> None:
    require(isinstance(thresholds, dict), "thresholds must be an object")
    require(thresholds.get("schema") == "hepta.runtime-codex.target-thresholds.v1",
            "unexpected threshold schema")
    metrics = thresholds.get("metrics")
    require(isinstance(metrics, dict) and set(metrics) == set(TIMINGS) | {"peakRssBytes", "cpuMillis"},
            "thresholds must cover every timing and resource metric")
    for name, limits in metrics.items():
        required = {"p95", "p99"} if name in TIMINGS else {"p99"}
        available = {"p50", "p95", "p99", "max"} if name in TIMINGS else {"p95", "p99", "max"}
        require(isinstance(limits, dict) and required <= set(limits) <= available,
                f"invalid threshold percentiles for {name}")
        for percentile_name, ceiling in limits.items():
            require(finite_nonnegative(ceiling), f"invalid threshold {name}.{percentile_name}")


def percentile(values: list[float], percentile_value: float) -> float:
    require(bool(values), "cannot compute a percentile over an empty sample")
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile_value * len(ordered)))
    return ordered[rank - 1]


def command_plan(args: argparse.Namespace) -> None:
    require(type(args.iterations) is int and args.iterations >= 3, "fault-matrix iterations must be at least three")
    candidate_sha = git("rev-parse", "--verify", "--end-of-options", f"{args.candidate}^{{commit}}")
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
    validate_plan(plan)
    Path(args.output).write_bytes(canonical(plan))


def load_jsonl(path: Path, raw: bytes | None = None) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    try:
        text = (path.read_bytes() if raw is None else raw).decode("utf-8")
    except UnicodeError as error:
        raise SystemExit(f"invalid observation UTF-8: {error}") from error
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        value = parse_json(line, f"observation JSONL line {line_number}")
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
        require(type(observation.get(field)) is int and observation[field] > 0, f"invalid {field}")
    for field in (
        "realProvider",
        "independentIssuer",
        "processInstanceIdentityVerified",
        "trustedClockAttested",
        "antiRollbackRecoveryAttested",
    ):
        require(observation.get(field) is True, f"target evidence did not establish {field}")
    require(type(observation.get("blindReplayAttempts")) is int and observation["blindReplayAttempts"] == 0,
            "invalid or nonzero blindReplayAttempts")
    require(type(observation.get("iteration")) is int and observation["iteration"] > 0, "invalid iteration")
    require(isinstance(observation.get("case"), str), "invalid case")
    require(type(observation.get("terminalObserved")) is bool, "invalid terminalObserved")
    require(
        type(observation.get("physicalProviderRequests")) is int
        and observation["physicalProviderRequests"] >= 0,
        "invalid physicalProviderRequests",
    )
    require(isinstance(observation.get("timings"), dict), "missing timings")
    for timing in TIMINGS:
        value = observation["timings"].get(timing)
        require(finite_nonnegative(value), f"invalid timing {timing}")
    for field in ("peakRssBytes", "cpuMillis"):
        require(finite_nonnegative(observation.get(field)), f"invalid {field}")


def validate_case(observation: dict[str, Any]) -> None:
    case = observation["case"]
    requests = observation["physicalProviderRequests"]
    outcome = observation.get("outcome")
    terminal = observation.get("terminalObserved") is True
    if outcome in {"succeeded", "terminal"}:
        require(terminal, "terminal outcome lacks terminalObserved")
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
    plan_raw = Path(args.plan).read_bytes()
    evidence_raw = Path(args.evidence).read_bytes()
    thresholds_raw = Path(args.thresholds).read_bytes()
    plan = parse_json(plan_raw, "target plan")
    expected = validate_plan(plan)
    require(plan["candidateSha"] == git("rev-parse", "HEAD"), "checkout does not match target plan")
    require(plan["candidateTree"] == git("rev-parse", "HEAD^{tree}"), "checkout tree does not match target plan")
    thresholds = parse_json(thresholds_raw, "thresholds")
    validate_thresholds(thresholds)
    observations = load_jsonl(Path(args.evidence), evidence_raw)
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
    for metric_name, limits in thresholds["metrics"].items():
        require(metric_name in metrics, f"threshold references unknown metric {metric_name}")
        for percentile_name, ceiling in limits.items():
            require(
                metrics[metric_name][percentile_name] <= ceiling,
                f"{metric_name}.{percentile_name} exceeded {ceiling}",
            )

    receipt = {
        "schema": RECEIPT_SCHEMA,
        "candidateSha": plan["candidateSha"],
        "candidateTree": plan["candidateTree"],
        "profileId": plan["profileId"],
        "planSha256": sha256_bytes(plan_raw),
        "evidenceSha256": sha256_bytes(evidence_raw),
        "thresholdsSha256": sha256_bytes(thresholds_raw),
        "observations": len(observations),
        "metrics": metrics,
        "diagnosticStatus": "INPUT_CONSISTENT",
        "qualificationStatus": "HOLD",
        "limitations": [
            "Only supplied JSON structure, declared matrix completeness, case consistency and metric limits were checked.",
            "Provider/process digest strings and positive assertions were not authenticated or verified against evidence bytes.",
            "No real provider, independent issuer, trusted clock, anti-rollback recovery or target-host execution was established.",
        ],
        "claims": {
            "suppliedInputConsistencyValidated": True,
            "realProviderFaultMatrixValidated": False,
            "targetHostEvidenceValidated": False,
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
