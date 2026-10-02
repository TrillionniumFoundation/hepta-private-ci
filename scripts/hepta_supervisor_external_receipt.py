#!/usr/bin/env python3
"""Validate runtime.supervisor target-host and production acceptance receipts.

This validator is intentionally unable to manufacture evidence. It consumes
operator-produced, content-addressed receipts and rejects missing scenarios,
stale identities, verifier/signer composition drift, failed SLOs, reused reviewer identifiers,
or an activation claim embedded in source-controlled evidence.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
from typing import Any

if __package__:
    from .hepta_supervisor_evidence import read_regular, strict_json
    from .hepta_supervisor_status import MATRIX_PATH, validate_matrix
else:
    from hepta_supervisor_evidence import read_regular, strict_json
    from hepta_supervisor_status import MATRIX_PATH, validate_matrix

SHA40 = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
NONZERO_DECIMAL = re.compile(r"[1-9][0-9]*")
TARGET_PROFILE = Path("docs/modules/runtime.supervisor/TARGET_HOST_PROFILE.json")
PRODUCTION_PROFILE = Path(
    "docs/modules/runtime.supervisor/PRODUCTION_QUALIFICATION_PROFILE.json"
)
TARGET_TRIPLES = {
    ("linux", "x86_64"): {"x86_64-unknown-linux-gnu", "x86_64-unknown-linux-musl"},
    ("linux", "aarch64"): {"aarch64-unknown-linux-gnu", "aarch64-unknown-linux-musl"},
    ("macos", "arm64"): {"aarch64-apple-darwin"},
}
RUN_BINDINGS = {
    "lane": "LANE",
    "source_sha": "SOURCE_SHA",
    "base_sha": "BASE_SHA",
    "merge_candidate_sha": "MERGE_CANDIDATE_SHA",
    "tested_sha": "TESTED_SHA",
    "workflow_sha": "GITHUB_WORKFLOW_SHA",
    "workflow_run_id": "GITHUB_RUN_ID",
    "workflow_run_attempt": "GITHUB_RUN_ATTEMPT",
    "binary_sha256": "TARGET_BINARY_SHA256",
}


def load(path: Path) -> dict[str, Any]:
    data = strict_json(read_regular(path, 1024 * 1024))
    require(isinstance(data, dict), f"{path}: root must be an object")
    return data


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def exact_keys(
    value: dict[str, Any], required: set[str], optional: set[str] = set()
) -> None:
    require(isinstance(value, dict), "expected JSON object")
    actual = set(value)
    require(required <= actual, f"missing fields: {sorted(required - actual)}")
    require(
        actual <= required | optional,
        f"unknown fields: {sorted(actual - required - optional)}",
    )


def sha40(value: Any, field: str) -> str:
    require(
        isinstance(value, str) and SHA40.fullmatch(value) is not None, f"{field}: SHA-1"
    )
    require(value != "0" * 40, f"{field}: null SHA")
    return value


def sha256(value: Any, field: str) -> str:
    require(
        isinstance(value, str) and SHA256.fullmatch(value) is not None,
        f"{field}: SHA-256",
    )
    require(value != "0" * 64, f"{field}: null SHA-256")
    return value


def receipt_sha256(path: Path, receipt: dict[str, Any]) -> str:
    raw = read_regular(path, 1024 * 1024)
    # Python equality conflates True with 1 and 256.0 with 256; retain JSON
    # type identity when confirming that the hashed contents were validated.
    require(
        json.dumps(strict_json(raw), sort_keys=True, allow_nan=False)
        == json.dumps(receipt, sort_keys=True, allow_nan=False),
        f"{path}: target receipt changed after validation",
    )
    return hashlib.sha256(raw).hexdigest()


def validate_run_binding(
    data: dict[str, Any],
    expected: dict[str, Any],
    binary_digest: str,
    lock_digest: str,
    git_sha: str,
    host_os: str,
    host_architecture: str,
) -> None:
    """Bind operator output to the current invocation, not its own assertions."""
    for field in (*RUN_BINDINGS, "final_merge_sha"):
        require(
            field in expected and data.get(field) == expected[field],
            f"current run {field} drift",
        )
    require(
        data["tested_sha"] == git_sha, "current checkout differs from target receipt"
    )
    require(
        data["binary_sha256"] == binary_digest, "current daemon binary digest drift"
    )
    require(data["cargo_lock_sha256"] == lock_digest, "current Cargo.lock digest drift")
    require(data["host"]["os"] == host_os, "current runner OS drift")
    require(
        data["host"]["architecture"] == host_architecture,
        "current runner architecture drift",
    )


def bind_current_run(data: dict[str, Any], binary: Path) -> None:
    expected: dict[str, Any] = {}
    for field, variable in RUN_BINDINGS.items():
        expected[field] = os.environ.get(variable, "")
        require(expected[field] != "", f"missing current run input: {variable}")
    expected["final_merge_sha"] = os.environ.get("FINAL_MERGE_SHA") or None
    host_os = {"Linux": "linux", "Darwin": "macos"}.get(
        platform.system(), "unsupported"
    )
    require(
        os.environ.get("TARGET_OS") == host_os,
        "target runner label differs from actual OS",
    )
    machine = platform.machine().lower()
    architecture = (
        "arm64"
        if host_os == "macos" and machine in ("arm64", "aarch64")
        else "aarch64"
        if machine in ("arm64", "aarch64")
        else machine
    )
    git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    require(
        not subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            text=True,
        ).strip(),
        "current target checkout is dirty",
    )
    validate_run_binding(
        data,
        expected,
        hashlib.sha256(
            read_regular(
                binary,
                512 * 1024 * 1024,
                allow_hardlinks=True,
            )
        ).hexdigest(),
        hashlib.sha256(
            read_regular(Path("codex-rs/Cargo.lock"), 16 * 1024 * 1024)
        ).hexdigest(),
        git_sha,
        host_os,
        architecture,
    )


def validate_target(data: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    required = {
        "schema_version",
        "kind",
        "profile_id",
        "lane",
        "source_sha",
        "base_sha",
        "merge_candidate_sha",
        "tested_sha",
        "final_merge_sha",
        "workflow_sha",
        "workflow_run_id",
        "binary_sha256",
        "cargo_lock_sha256",
        "feature_set",
        "target_triple",
        "runner_image_or_host_fingerprint",
        "host",
        "profile_sha256",
        "workload_sha256",
        "real_processes",
        "fault_results",
        "metrics",
        "forbidden_binaries_present",
        "clean_tree",
        "completed_at_utc",
        "activation",
    }
    exact_keys(data, required, {"workflow_run_attempt"})
    require(
        type(data["schema_version"]) is int and data["schema_version"] == 1,
        "target receipt schema",
    )
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
    require(
        isinstance(data["workflow_run_id"], str)
        and NONZERO_DECIMAL.fullmatch(data["workflow_run_id"]) is not None,
        "workflow_run_id",
    )
    if "workflow_run_attempt" in data:
        require(
            isinstance(data["workflow_run_attempt"], str)
            and NONZERO_DECIMAL.fullmatch(data["workflow_run_attempt"]) is not None,
            "workflow_run_attempt",
        )
    for field in (
        "binary_sha256",
        "cargo_lock_sha256",
        "profile_sha256",
        "workload_sha256",
    ):
        sha256(data[field], field)
    require(
        data["profile_sha256"]
        == hashlib.sha256(
            (json.dumps(profile, sort_keys=True, separators=(",", ":")) + "\n").encode()
        ).hexdigest(),
        "profile digest must bind canonical target profile",
    )
    require(data["feature_set"] == ["production-verifier"], "verifier-only feature set")
    require(
        isinstance(data["target_triple"], str) and data["target_triple"],
        "target triple",
    )
    require(
        isinstance(data["runner_image_or_host_fingerprint"], str)
        and data["runner_image_or_host_fingerprint"],
        "host fingerprint",
    )
    host = data["host"]
    exact_keys(host, {"os", "architecture", "kernel", "filesystem"})
    allowed_hosts = {
        (entry["os"], architecture, filesystem)
        for entry in profile["hosts"]
        for architecture in entry["architectures"]
        for filesystem in entry["filesystems"]
    }
    require(
        (host["os"], host["architecture"], host["filesystem"]) in allowed_hosts,
        "host is outside the frozen profile",
    )
    require(isinstance(host["kernel"], str) and host["kernel"], "kernel identity")
    require(
        data["target_triple"]
        in TARGET_TRIPLES.get((host["os"], host["architecture"]), set()),
        "target triple differs from host OS/architecture",
    )
    completed = data["completed_at_utc"]
    require(
        isinstance(completed, str)
        and re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z",
            completed,
        )
        is not None,
        "completed_at_utc must be an explicit UTC timestamp",
    )
    datetime.fromisoformat(completed.replace("Z", "+00:00"))
    require(
        type(data["real_processes"]) is int
        and data["real_processes"] == profile["fleet"]["real_processes_required"],
        "real process count",
    )
    require(
        data["forbidden_binaries_present"] == [],
        "offline signer binary in daemon artifact",
    )
    require(data["clean_tree"] is True, "target run must use clean tree")
    require(data["activation"] is False, "target receipt cannot activate production")

    results = data["fault_results"]
    require(isinstance(results, list), "fault results")
    by_scenario: dict[str, dict[str, Any]] = {}
    for result in results:
        exact_keys(
            result,
            {
                "scenario",
                "status",
                "fault_cut",
                "raw_log_sha256",
                "durable_snapshot_before_sha256",
                "durable_snapshot_after_sha256",
            },
        )
        scenario = result["scenario"]
        require(
            isinstance(scenario, str) and scenario not in by_scenario,
            "unique fault scenario",
        )
        by_scenario[scenario] = result
        require(result["status"] == "passed", f"{scenario}: not passed")
        require(
            isinstance(result["fault_cut"], str) and result["fault_cut"],
            f"{scenario}: fault cut",
        )
        for field in (
            "raw_log_sha256",
            "durable_snapshot_before_sha256",
            "durable_snapshot_after_sha256",
        ):
            sha256(result[field], f"{scenario}.{field}")
    required_scenarios = set(profile["fault_scenarios"])
    require(
        set(by_scenario) == required_scenarios,
        f"fault scenario mismatch: missing={sorted(required_scenarios - set(by_scenario))} extra={sorted(set(by_scenario) - required_scenarios)}",
    )

    metrics = data["metrics"]
    require(
        isinstance(metrics, dict) and set(metrics) == set(profile["slo"]),
        "metric inventory",
    )
    for name, constraint in profile["slo"].items():
        value = metrics[name]
        require(
            type(value) in (int, float) and math.isfinite(value) and value >= 0,
            f"{name}: finite numeric metric",
        )
        require(constraint["operator"] == "lte", f"{name}: unsupported operator")
        require(
            value <= constraint["value"],
            f"{name}: {value} exceeds {constraint['value']}",
        )
    return {
        "os": host["os"],
        "lane": data["lane"],
        "tested_sha": tested,
        "receipt_sha256": None,
    }


def validate_production(
    data: dict[str, Any],
    profile: dict[str, Any],
    target_receipts: list[tuple[Path, dict[str, Any]]],
) -> None:
    """Check receipt bindings; the CLI also enforces the checkout's source gate.

    Reviewer identities and raw custody/observation artifacts require external
    authentication. Digest-shaped fields cannot authenticate their producers.
    """
    exact_keys(
        data,
        {
            "schema_version",
            "kind",
            "profile_id",
            "source_sha",
            "base_sha",
            "merge_candidate_sha",
            "final_merge_sha",
            "workflow_sha",
            "workflow_run_id",
            "binary_sha256",
            "cargo_lock_sha256",
            "feature_set",
            "target_receipts",
            "key_custody_receipts",
            "atomic_recovery_observation_sha256",
            "operator_drill_receipt_sha256",
            "independent_reviews",
            "activation",
        },
        {"target_binary_sha256"},
    )
    require(
        type(data["schema_version"]) is int and data["schema_version"] == 1,
        "production receipt schema",
    )
    require(
        data["kind"] == "runtime-supervisor-production-acceptance",
        "production receipt kind",
    )
    require(data["profile_id"] == profile["profile_id"], "production profile id")
    for field in (
        "source_sha",
        "base_sha",
        "merge_candidate_sha",
        "final_merge_sha",
        "workflow_sha",
    ):
        sha40(data[field], field)
    require(
        isinstance(data["workflow_run_id"], str)
        and NONZERO_DECIMAL.fullmatch(data["workflow_run_id"]) is not None,
        "workflow_run_id",
    )
    for field in (
        "binary_sha256",
        "cargo_lock_sha256",
        "atomic_recovery_observation_sha256",
        "operator_drill_receipt_sha256",
    ):
        sha256(data[field], field)
    require(
        data["feature_set"] == profile["artifact_boundary"]["daemon_feature_set"],
        "production verifier feature set",
    )
    require(
        data["activation"] is False,
        "acceptance receipt records eligibility; activation is a separate action",
    )

    expected_refs = data["target_receipts"]
    require(isinstance(expected_refs, list), "target receipt references")
    actual: dict[str, str] = {}
    final_merge = data["final_merge_sha"]
    binary = data["binary_sha256"]
    target_binaries = data.get("target_binary_sha256")
    if target_binaries is not None:
        require(
            isinstance(target_binaries, dict)
            and set(target_binaries) == set(profile["required_target_hosts"]),
            "target binary digest host inventory",
        )
        for host, digest in target_binaries.items():
            sha256(digest, f"target_binary_sha256.{host}")
        require(
            binary == target_binaries[profile["required_target_hosts"][0]],
            "legacy binary digest must identify the primary required target host",
        )
    identity_fields = (
        "source_sha",
        "base_sha",
        "merge_candidate_sha",
        "cargo_lock_sha256",
        "feature_set",
    )
    for path, receipt in target_receipts:
        require(
            receipt["lane"] == "final-merge",
            f"{path}: target receipt must be final-merge",
        )
        require(receipt["tested_sha"] == final_merge, f"{path}: wrong final merge")
        host = receipt["host"]["os"]
        require(
            host in profile["required_target_hosts"], f"{path}: unsupported target host"
        )
        require(
            receipt["binary_sha256"]
            == (target_binaries[host] if target_binaries is not None else binary),
            f"{path}: binary digest drift",
        )
        for field in identity_fields:
            require(receipt[field] == data[field], f"{path}: {field} drift")
        require(host not in actual, f"duplicate target host receipt: {host}")
        actual[host] = receipt_sha256(path, receipt)
    require(
        set(actual) == set(profile["required_target_hosts"]), "required target hosts"
    )
    reference_map: dict[str, str] = {}
    for entry in expected_refs:
        require(isinstance(entry, dict), "target receipt reference")
        exact_keys(entry, {"os", "receipt_sha256"})
        host = entry["os"]
        require(
            host in profile["required_target_hosts"] and host not in reference_map,
            "unique target receipt reference",
        )
        reference_map[host] = sha256(entry["receipt_sha256"], f"target_receipts.{host}")
    require(reference_map == actual, "target receipt digest bindings")

    custody = data["key_custody_receipts"]
    require(isinstance(custody, dict), "key custody receipts")
    require(
        set(custody) == set(profile["key_custody"]["required_receipts"]),
        "key custody receipt inventory",
    )
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
        require(
            role in profile["independent_acceptance"]["required_roles"]
            and role not in roles,
            "independent review role",
        )
        require(
            isinstance(reviewer, str) and reviewer and reviewer not in reviewers,
            "distinct independent reviewer",
        )
        require(review["decision"] == "accepted", f"{role}: review not accepted")
        sha256(review["receipt_sha256"], f"{role}.receipt_sha256")
        roles[role] = reviewer
        reviewers.add(reviewer)
    require(
        set(roles) == set(profile["independent_acceptance"]["required_roles"]),
        "missing independent review role",
    )


def require_production_source(root: Path) -> None:
    """An external digest cannot substitute for the required native observation."""
    matrix = load(root / MATRIX_PATH)
    validate_matrix(root, matrix)
    observation = next(
        (
            capability
            for capability in matrix["capabilities"]
            if capability["id"] == "atomic_recovery_observation_envelope"
        ),
        None,
    )
    require(
        observation is not None
        and observation["source"] == "implemented"
        and observation["test_source"] == "present",
        "production acceptance requires implemented and tested atomic recovery observation source",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    target = sub.add_parser("target")
    target.add_argument("receipt", type=Path)
    target.add_argument("--profile", type=Path, default=TARGET_PROFILE)
    target.add_argument("--bind-current-run", action="store_true")
    target.add_argument("--binary", type=Path)
    production = sub.add_parser("production")
    production.add_argument("receipt", type=Path)
    production.add_argument("--profile", type=Path, default=PRODUCTION_PROFILE)
    production.add_argument("--target-profile", type=Path, default=TARGET_PROFILE)
    production.add_argument(
        "--target-receipt", type=Path, action="append", required=True
    )
    args = parser.parse_args()
    try:
        if args.operation == "target":
            profile = load(args.profile)
            receipt = load(args.receipt)
            validate_target(receipt, profile)
            if args.bind_current_run:
                require(
                    args.binary is not None, "current-run binding requires --binary"
                )
                bind_current_run(receipt, args.binary)
        else:
            require_production_source(Path.cwd())
            target_profile = load(args.target_profile)
            targets = []
            for path in args.target_receipt:
                receipt = load(path)
                validate_target(receipt, target_profile)
                targets.append((path, receipt))
            validate_production(load(args.receipt), load(args.profile), targets)
        return 0
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        OverflowError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as error:
        print(f"runtime.supervisor external receipt rejected: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
