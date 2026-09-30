#!/usr/bin/env python3
"""Validate runtime.supervisor target-host and production acceptance receipts.

This validator is intentionally unable to manufacture evidence. It consumes
operator-produced, content-addressed receipts and rejects missing scenarios,
stale identities, verifier/signer composition drift, failed SLOs, self-review,
or an activation claim embedded in source-controlled evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

SHA40 = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
NONZERO_DECIMAL = re.compile(r"[1-9][0-9]*")
TARGET_PROFILE = Path("docs/modules/runtime.supervisor/TARGET_HOST_PROFILE.json")
PRODUCTION_PROFILE = Path("docs/modules/runtime.supervisor/PRODUCTION_QUALIFICATION_PROFILE.json")


def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)
    require(isinstance(data, dict), f"{path}: root must be an object")
    return data


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def exact_keys(value: dict[str, Any], required: set[str], optional: set[str] = set()) -> None:
    actual = set(value)
    require(required <= actual, f"missing fields: {sorted(required-actual)}")
    require(actual <= required | optional, f"unknown fields: {sorted(actual-required-optional)}")


def sha40(value: Any, field: str) -> str:
    require(isinstance(value, str) and SHA40.fullmatch(value) is not None, f"{field}: SHA-1")
    require(value != "0" * 40, f"{field}: null SHA")
    return value


def sha256(value: Any, field: str) -> str:
    require(isinstance(value, str) and SHA256.fullmatch(value) is not None, f"{field}: SHA-256")
    require(value != "0" * 64, f"{field}: null SHA-256")
    return value


def receipt_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_target(data: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    required = {
        "schema_version", "kind", "profile_id", "lane", "source_sha", "base_sha",
        "merge_candidate_sha", "tested_sha", "final_merge_sha", "workflow_sha",
        "workflow_run_id", "binary_sha256", "cargo_lock_sha256", "feature_set",
        "target_triple", "runner_image_or_host_fingerprint", "host", "profile_sha256",
        "workload_sha256", "real_processes", "fault_results", "metrics",
        "forbidden_binaries_present", "clean_tree", "completed_at_utc", "activation",
    }
    exact_keys(data, required)
    require(data["schema_version"] == 1, "target receipt schema")
    require(data["kind"] == "runtime-supervisor-target-host", "target receipt kind")
    require(data["profile_id"] == profile["profile_id"], "target profile id")
    require(data["lane"] in ("source-head", "final-merge"), "target lane")
    source = sha40(data["source_sha"], "source_sha")
    sha40(data["base_sha"], "base_sha")
    sha40(data["merge_candidate_sha"], "merge_candidate_sha")
    tested = sha40(data["tested_sha"], "tested_sha")
    final_merge = data["final_merge_sha"]
    if data["lane"] == "source-head":
        require(tested == source, "source-head tested SHA")
        require(final_merge is None, "source-head cannot claim final merge")
    else:
        final_merge = sha40(final_merge, "final_merge_sha")
        require(tested == final_merge, "final-merge tested SHA")
    sha40(data["workflow_sha"], "workflow_sha")
    require(isinstance(data["workflow_run_id"], str)
            and NONZERO_DECIMAL.fullmatch(data["workflow_run_id"]) is not None,
            "workflow_run_id")
    for field in ("binary_sha256", "cargo_lock_sha256", "profile_sha256", "workload_sha256"):
        sha256(data[field], field)
    require(data["profile_sha256"] == hashlib.sha256(
        (json.dumps(profile, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ).hexdigest(), "profile digest must bind canonical target profile")
    require(data["feature_set"] == ["production-verifier"], "verifier-only feature set")
    require(isinstance(data["target_triple"], str) and data["target_triple"], "target triple")
    require(isinstance(data["runner_image_or_host_fingerprint"], str)
            and data["runner_image_or_host_fingerprint"], "host fingerprint")
    host = data["host"]
    exact_keys(host, {"os", "architecture", "kernel", "filesystem"})
    allowed_hosts = {(entry["os"], architecture, filesystem)
                     for entry in profile["hosts"]
                     for architecture in entry["architectures"]
                     for filesystem in entry["filesystems"]}
    require((host["os"], host["architecture"], host["filesystem"]) in allowed_hosts,
            "host is outside the frozen profile")
    require(isinstance(host["kernel"], str) and host["kernel"], "kernel identity")
    require(data["real_processes"] == profile["fleet"]["real_processes_required"],
            "real process count")
    require(data["forbidden_binaries_present"] == [], "offline signer binary in daemon artifact")
    require(data["clean_tree"] is True, "target run must use clean tree")
    require(data["activation"] is False, "target receipt cannot activate production")

    results = data["fault_results"]
    require(isinstance(results, list), "fault results")
    by_scenario: dict[str, dict[str, Any]] = {}
    for result in results:
        exact_keys(result, {
            "scenario", "status", "fault_cut", "raw_log_sha256",
            "durable_snapshot_before_sha256", "durable_snapshot_after_sha256",
        })
        scenario = result["scenario"]
        require(isinstance(scenario, str) and scenario not in by_scenario,
                "unique fault scenario")
        by_scenario[scenario] = result
        require(result["status"] == "passed", f"{scenario}: not passed")
        require(isinstance(result["fault_cut"], str) and result["fault_cut"],
                f"{scenario}: fault cut")
        for field in ("raw_log_sha256", "durable_snapshot_before_sha256",
                      "durable_snapshot_after_sha256"):
            sha256(result[field], f"{scenario}.{field}")
    required_scenarios = set(profile["fault_scenarios"])
    require(set(by_scenario) == required_scenarios,
            f"fault scenario mismatch: missing={sorted(required_scenarios-set(by_scenario))} extra={sorted(set(by_scenario)-required_scenarios)}")

    metrics = data["metrics"]
    require(isinstance(metrics, dict) and set(metrics) == set(profile["slo"]), "metric inventory")
    for name, constraint in profile["slo"].items():
        value = metrics[name]
        require(type(value) in (int, float) and value >= 0, f"{name}: numeric metric")
        require(constraint["operator"] == "lte", f"{name}: unsupported operator")
        require(value <= constraint["value"],
                f"{name}: {value} exceeds {constraint['value']}")
    return {
        "os": host["os"], "lane": data["lane"], "tested_sha": tested,
        "receipt_sha256": None,
    }


def validate_production(
    data: dict[str, Any], profile: dict[str, Any], target_receipts: list[tuple[Path, dict[str, Any]]]
) -> None:
    exact_keys(data, {
        "schema_version", "kind", "profile_id", "source_sha", "base_sha",
        "merge_candidate_sha", "final_merge_sha", "workflow_sha", "workflow_run_id",
        "binary_sha256", "cargo_lock_sha256", "feature_set", "target_receipts",
        "key_custody_receipts", "atomic_recovery_observation_sha256",
        "operator_drill_receipt_sha256", "independent_reviews", "activation",
    })
    require(data["schema_version"] == 1, "production receipt schema")
    require(data["kind"] == "runtime-supervisor-production-acceptance", "production receipt kind")
    require(data["profile_id"] == profile["profile_id"], "production profile id")
    for field in ("source_sha", "base_sha", "merge_candidate_sha", "final_merge_sha", "workflow_sha"):
        sha40(data[field], field)
    require(isinstance(data["workflow_run_id"], str)
            and NONZERO_DECIMAL.fullmatch(data["workflow_run_id"]) is not None,
            "workflow_run_id")
    for field in ("binary_sha256", "cargo_lock_sha256",
                  "atomic_recovery_observation_sha256", "operator_drill_receipt_sha256"):
        sha256(data[field], field)
    require(data["feature_set"] == profile["artifact_boundary"]["daemon_feature_set"],
            "production verifier feature set")
    require(data["activation"] is False,
            "acceptance receipt records eligibility; activation is a separate action")

    expected_refs = data["target_receipts"]
    require(isinstance(expected_refs, list), "target receipt references")
    actual: dict[str, str] = {}
    final_merge = data["final_merge_sha"]
    binary = data["binary_sha256"]
    identity_fields = (
        "source_sha", "base_sha", "merge_candidate_sha",
        "cargo_lock_sha256", "feature_set",
    )
    for path, receipt in target_receipts:
        require(receipt["lane"] == "final-merge", f"{path}: target receipt must be final-merge")
        require(receipt["tested_sha"] == final_merge, f"{path}: wrong final merge")
        require(receipt["binary_sha256"] == binary, f"{path}: binary digest drift")
        for field in identity_fields:
            require(receipt[field] == data[field], f"{path}: {field} drift")
        host = receipt["host"]["os"]
        require(host not in actual, f"duplicate target host receipt: {host}")
        actual[host] = receipt_sha256(path)
    require(set(actual) == set(profile["required_target_hosts"]), "required target hosts")
    reference_map: dict[str, str] = {}
    for entry in expected_refs:
        require(isinstance(entry, dict), "target receipt reference")
        exact_keys(entry, {"os", "receipt_sha256"})
        host = entry["os"]
        require(host in profile["required_target_hosts"] and host not in reference_map,
                "unique target receipt reference")
        reference_map[host] = sha256(entry["receipt_sha256"], f"target_receipts.{host}")
    require(reference_map == actual, "target receipt digest bindings")

    custody = data["key_custody_receipts"]
    require(isinstance(custody, dict), "key custody receipts")
    require(set(custody) == set(profile["key_custody"]["required_receipts"]),
            "key custody receipt inventory")
    for name, digest in custody.items():
        sha256(digest, f"key_custody_receipts.{name}")

    reviews = data["independent_reviews"]
    require(isinstance(reviews, list), "independent reviews")
    roles: dict[str, str] = {}
    reviewers: set[str] = set()
    for review in reviews:
        exact_keys(review, {"role", "reviewer", "decision", "receipt_sha256"})
        role = review["role"]
        reviewer = review["reviewer"]
        require(role in profile["independent_acceptance"]["required_roles"] and role not in roles,
                "independent review role")
        require(isinstance(reviewer, str) and reviewer and reviewer not in reviewers,
                "distinct independent reviewer")
        require(review["decision"] == "accepted", f"{role}: review not accepted")
        sha256(review["receipt_sha256"], f"{role}.receipt_sha256")
        roles[role] = reviewer
        reviewers.add(reviewer)
    require(set(roles) == set(profile["independent_acceptance"]["required_roles"]),
            "missing independent review role")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    target = sub.add_parser("target")
    target.add_argument("receipt", type=Path)
    target.add_argument("--profile", type=Path, default=TARGET_PROFILE)
    production = sub.add_parser("production")
    production.add_argument("receipt", type=Path)
    production.add_argument("--profile", type=Path, default=PRODUCTION_PROFILE)
    production.add_argument("--target-profile", type=Path, default=TARGET_PROFILE)
    production.add_argument("--target-receipt", type=Path, action="append", required=True)
    args = parser.parse_args()
    try:
        if args.operation == "target":
            profile = load(args.profile)
            validate_target(load(args.receipt), profile)
        else:
            target_profile = load(args.target_profile)
            targets = []
            for path in args.target_receipt:
                receipt = load(path)
                validate_target(receipt, target_profile)
                targets.append((path, receipt))
            validate_production(load(args.receipt), load(args.profile), targets)
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(f"runtime.supervisor external receipt rejected: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
