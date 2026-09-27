#!/usr/bin/env python3
"""Execute and verify runtime.agentd target-host qualification scenarios.

The harness runs only inside a marked disposable root. Scenario adapters must
write owner-observed result JSON; process exit alone can never establish a model,
external-effect, durability, or reconciliation outcome.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
from typing import Any

SCHEMA = 1
RESULT_SCHEMA = 1
MARKER = ".hepta-runtime-agentd-disposable-v1"
CONTRACT_PATH = Path("docs/modules/runtime.agentd/QUALIFICATION_CONTRACT.json")
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
MAX_PLAN_BYTES = 1024 * 1024
MAX_RESULT_BYTES = 1024 * 1024
MAX_LOG_BYTES = 64 * 1024 * 1024
MAX_SCENARIO_SECONDS = 6 * 60 * 60


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read_json(path: Path, maximum: int) -> Any:
    require(path.is_file() and not path.is_symlink(), f"JSON path is not a regular file: {path}")
    require(0 < path.stat().st_size <= maximum, f"JSON path is empty or oversized: {path}")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            require(key not in result, f"duplicate JSON key {key!r} in {path}")
            result[key] = value
        return result

    def reject(value: str) -> None:
        raise ValueError(f"non-finite JSON value {value!r} in {path}")

    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=unique,
        parse_constant=reject,
    )


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_value(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def load_contract(workspace: Path) -> dict[str, Any]:
    contract = read_json(workspace / CONTRACT_PATH, MAX_PLAN_BYTES)
    require(type(contract) is dict, "qualification contract must be an object")
    require(
        contract.get("schema") == "hepta.runtime-agentd.qualification-contract.v1"
        and contract.get("schemaVersion") == 1,
        "unsupported runtime.agentd qualification contract",
    )
    scenarios = contract.get("requiredTargetHostScenarios")
    require(type(scenarios) is dict and scenarios, "qualification contract has no target-host scenarios")
    return contract


def validate_marker(target_root: Path, source_sha: str) -> dict[str, Any]:
    require(target_root.is_absolute(), "target root must be absolute")
    target_root = target_root.resolve(strict=True)
    require(target_root != Path(target_root.anchor), "filesystem root cannot be a qualification root")
    require(target_root != Path.home().resolve(), "home directory cannot be a qualification root")
    marker_path = target_root / MARKER
    marker = read_json(marker_path, 16 * 1024)
    require(type(marker) is dict, "disposable-host marker must be an object")
    require(marker.get("schema") == 1, "unsupported disposable-host marker schema")
    require(marker.get("purpose") == "runtime.agentd-target-host", "wrong disposable-host purpose")
    require(marker.get("source_sha") == source_sha, "disposable-host marker source SHA differs")
    nonce = marker.get("nonce")
    require(isinstance(nonce, str) and 16 <= len(nonce) <= 256, "invalid disposable-host nonce")
    return marker


def resolve_artifacts(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    artifacts = plan.get("artifacts")
    require(type(artifacts) is dict and artifacts, "plan must name tested artifacts")
    result: dict[str, dict[str, Any]] = {}
    for name, entry in sorted(artifacts.items()):
        require(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", name), "invalid artifact name")
        require(type(entry) is dict and set(entry) == {"path", "sha256"}, f"invalid artifact entry: {name}")
        path = Path(entry["path"])
        require(path.is_absolute(), f"artifact path must be absolute: {name}")
        require(path.is_file() and not path.is_symlink(), f"artifact is not a regular file: {name}")
        expected = entry["sha256"]
        require(isinstance(expected, str) and SHA256.fullmatch(expected) is not None, f"invalid artifact digest: {name}")
        observed = sha256(path)
        require(observed == expected, f"artifact digest mismatch before execution: {name}")
        result[name] = {"path": str(path), "sha256": observed, "bytes": path.stat().st_size}
    return result


def normalize_command(value: Any) -> list[str]:
    require(type(value) is list and value, "scenario argv must be a non-empty array")
    require(all(isinstance(item, str) and item and "\x00" not in item for item in value), "scenario argv contains invalid values")
    executable = Path(value[0])
    if not executable.is_absolute():
        resolved = shutil.which(value[0])
        require(resolved is not None, f"scenario executable was not found: {value[0]}")
        executable = Path(resolved)
    executable = executable.resolve(strict=True)
    require(executable.is_file() and not executable.is_symlink(), "scenario executable must be a regular file")
    return [str(executable), *value[1:]]


def validate_plan(
    plan: dict[str, Any],
    contract: dict[str, Any],
    expected_sha: str,
    expected_tree: str,
    allow_destructive: bool,
) -> dict[str, dict[str, Any]]:
    require(type(plan) is dict, "target-host plan must be an object")
    require(plan.get("schema") == SCHEMA, "unsupported target-host plan schema")
    require(plan.get("source_sha") == expected_sha, "plan source SHA differs")
    require(plan.get("source_tree") == expected_tree, "plan source tree differs")
    configuration = plan.get("effective_configuration_digest")
    require(isinstance(configuration, str) and SHA256.fullmatch(configuration) is not None, "invalid effective configuration digest")
    scenarios = plan.get("scenarios")
    required = contract["requiredTargetHostScenarios"]
    require(type(scenarios) is dict, "plan scenarios must be an object")
    require(set(scenarios) == set(required), "plan must cover the exact required target-host scenario set")
    normalized: dict[str, dict[str, Any]] = {}
    for name, requirement in required.items():
        entry = scenarios[name]
        require(type(entry) is dict, f"scenario plan must be an object: {name}")
        require(set(entry) == {"argv", "timeout_seconds"}, f"scenario plan has unknown or missing fields: {name}")
        timeout_seconds = entry["timeout_seconds"]
        require(type(timeout_seconds) is int and 1 <= timeout_seconds <= MAX_SCENARIO_SECONDS, f"invalid scenario timeout: {name}")
        destructive = requirement.get("destructive") is True
        if destructive:
            require(allow_destructive, f"destructive scenario requires --allow-destructive: {name}")
        normalized[name] = {
            "argv": normalize_command(entry["argv"]),
            "timeout_seconds": timeout_seconds,
            "destructive": destructive,
        }
    return normalized


def validate_adapter_result(
    value: Any,
    scenario: str,
    required_invariants: list[str],
) -> dict[str, Any]:
    require(type(value) is dict, f"scenario result must be an object: {scenario}")
    required_fields = {
        "schema",
        "scenario",
        "operation_ids",
        "initial_state_digest",
        "final_state_digest",
        "observed_invariants",
        "measurements",
        "notes",
    }
    require(set(value) == required_fields, f"scenario result has unknown or missing fields: {scenario}")
    require(value["schema"] == RESULT_SCHEMA, f"unsupported scenario result schema: {scenario}")
    require(value["scenario"] == scenario, f"scenario result identity differs: {scenario}")
    operation_ids = value["operation_ids"]
    require(
        type(operation_ids) is list
        and operation_ids
        and len(operation_ids) <= 4096
        and all(isinstance(item, str) and 1 <= len(item) <= 512 for item in operation_ids),
        f"invalid operation identities: {scenario}",
    )
    for field in ("initial_state_digest", "final_state_digest"):
        digest = value[field]
        require(isinstance(digest, str) and SHA256.fullmatch(digest) is not None, f"invalid {field}: {scenario}")
    invariants = value["observed_invariants"]
    require(type(invariants) is dict, f"observed invariants must be an object: {scenario}")
    require(set(invariants) == set(required_invariants), f"observed invariant set differs: {scenario}")
    require(all(flag is True for flag in invariants.values()), f"one or more target invariants failed: {scenario}")
    measurements = value["measurements"]
    require(type(measurements) is dict, f"measurements must be an object: {scenario}")
    notes = value["notes"]
    require(type(notes) is list and len(notes) <= 256 and all(isinstance(note, str) and len(note) <= 2048 for note in notes), f"invalid notes: {scenario}")
    return value


def execute_scenario(
    workspace: Path,
    output_root: Path,
    target_root: Path,
    source_sha: str,
    source_tree: str,
    host_identity: str,
    configuration_digest: str,
    artifacts: dict[str, dict[str, Any]],
    name: str,
    entry: dict[str, Any],
    required_invariants: list[str],
) -> dict[str, Any]:
    scenario_root = output_root / name
    scenario_root.mkdir(parents=True, exist_ok=False)
    log = scenario_root / "command.log"
    adapter_result = scenario_root / "adapter-result.json"
    env = dict(os.environ)
    env.update(
        {
            "HEPTA_RUNTIME_AGENTD_TARGET_ROOT": str(target_root),
            "HEPTA_RUNTIME_AGENTD_SCENARIO": name,
            "HEPTA_RUNTIME_AGENTD_RESULT": str(adapter_result),
            "HEPTA_RUNTIME_AGENTD_SOURCE_SHA": source_sha,
            "HEPTA_RUNTIME_AGENTD_SOURCE_TREE": source_tree,
        }
    )
    started_ms = time.time_ns() // 1_000_000
    exit_code = 127
    timed_out = False
    with log.open("wb") as stream:
        try:
            process = subprocess.Popen(
                entry["argv"],
                cwd=workspace,
                env=env,
                stdout=stream,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                exit_code = process.wait(timeout=entry["timeout_seconds"])
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                exit_code = 124
                timed_out = True
                stream.write(b"\nTARGET-HOST: scenario process group timed out and was killed\n")
        except OSError as error:
            stream.write(f"{type(error).__name__}: {error}\n".encode())
    finished_ms = time.time_ns() // 1_000_000
    require(log.stat().st_size <= MAX_LOG_BYTES, f"scenario log exceeded bound: {name}")
    require(not timed_out and exit_code == 0, f"scenario command failed: {name} exit={exit_code}")
    adapter = validate_adapter_result(read_json(adapter_result, MAX_RESULT_BYTES), name, required_invariants)
    for artifact_name, artifact in artifacts.items():
        require(sha256(Path(artifact["path"])) == artifact["sha256"], f"artifact changed during scenario {name}: {artifact_name}")
    receipt = {
        "schema": SCHEMA,
        "source_sha": source_sha,
        "source_tree": source_tree,
        "host_identity": host_identity,
        "kernel_or_platform": platform.platform(),
        "effective_configuration_digest": configuration_digest,
        "artifact_digests": {key: value["sha256"] for key, value in artifacts.items()},
        "scenario": name,
        "destructive": entry["destructive"],
        "started_at_unix_ms": started_ms,
        "finished_at_unix_ms": finished_ms,
        "initial_state_digest": adapter["initial_state_digest"],
        "final_state_digest": adapter["final_state_digest"],
        "operation_ids": adapter["operation_ids"],
        "observed_invariants": adapter["observed_invariants"],
        "measurements": adapter["measurements"],
        "notes": adapter["notes"],
        "command": entry["argv"],
        "exit_code": exit_code,
        "log_sha256": sha256(log),
        "result": "success",
        "production_activation": False,
    }
    atomic_json(scenario_root / "receipt.json", receipt)
    return receipt


def validate_aggregate(
    receipts: list[dict[str, Any]],
    contract: dict[str, Any],
    source_sha: str,
    source_tree: str,
) -> dict[str, Any]:
    required = contract["requiredTargetHostScenarios"]
    by_name: dict[str, dict[str, Any]] = {}
    for receipt in receipts:
        require(type(receipt) is dict, "scenario receipt must be an object")
        name = receipt.get("scenario")
        require(name in required, f"unexpected target-host scenario receipt: {name}")
        require(name not in by_name, f"duplicate target-host scenario receipt: {name}")
        require(receipt.get("source_sha") == source_sha, f"stale source SHA in scenario receipt: {name}")
        require(receipt.get("source_tree") == source_tree, f"stale source tree in scenario receipt: {name}")
        require(receipt.get("result") == "success", f"target-host scenario did not succeed: {name}")
        require(receipt.get("production_activation") is False, f"target-host receipt cannot activate production: {name}")
        observed = receipt.get("observed_invariants")
        expected = required[name]["requiredInvariants"]
        require(type(observed) is dict and set(observed) == set(expected), f"target-host invariant set differs: {name}")
        require(all(value is True for value in observed.values()), f"target-host invariant failed: {name}")
        by_name[name] = receipt
    require(set(by_name) == set(required), "missing required target-host scenario receipts")
    artifact_sets = {json.dumps(receipt["artifact_digests"], sort_keys=True) for receipt in receipts}
    config_sets = {receipt["effective_configuration_digest"] for receipt in receipts}
    host_sets = {receipt["host_identity"] for receipt in receipts}
    require(len(artifact_sets) == 1, "target-host scenarios used different artifacts")
    require(len(config_sets) == 1, "target-host scenarios used different configurations")
    require(len(host_sets) == 1, "target-host scenarios used different host identities")
    return {
        "schema": SCHEMA,
        "module": "runtime.agentd",
        "source_sha": source_sha,
        "source_tree": source_tree,
        "host_identity": next(iter(host_sets)),
        "effective_configuration_digest": next(iter(config_sets)),
        "artifact_digests": json.loads(next(iter(artifact_sets))),
        "scenarios": sorted(by_name),
        "target_host_result": "success",
        "production_activation": False,
        "unproven": [
            "independent-security-acceptance",
            "operator-activation",
            "promotion",
            "release",
        ],
    }


def run(args: argparse.Namespace) -> int:
    workspace = args.workspace.resolve(strict=True)
    require(SHA40.fullmatch(args.expected_sha) is not None, "expected SHA must be exact")
    observed_sha = git_value(workspace, "rev-parse", "HEAD")
    observed_tree = git_value(workspace, "rev-parse", "HEAD^{tree}")
    require(observed_sha == args.expected_sha, "checkout differs from expected SHA")
    require(not git_value(workspace, "status", "--porcelain", "--untracked-files=all"), "checkout is dirty")
    contract = load_contract(workspace)
    plan = read_json(args.plan.resolve(strict=True), MAX_PLAN_BYTES)
    target_root = args.target_root.resolve(strict=True)
    marker = validate_marker(target_root, observed_sha)
    normalized = validate_plan(plan, contract, observed_sha, observed_tree, args.allow_destructive)
    artifacts = resolve_artifacts(plan)
    host_identity = plan.get("host_identity")
    require(isinstance(host_identity, str) and 1 <= len(host_identity) <= 512, "invalid host identity")
    require(marker.get("host_identity") == host_identity, "plan host identity differs from disposable marker")
    output = args.output.resolve()
    require(not output.exists(), "refuse to mix target-host evidence with an existing output")
    output.mkdir(parents=True)
    receipts: list[dict[str, Any]] = []
    for name, entry in normalized.items():
        receipts.append(
            execute_scenario(
                workspace,
                output,
                target_root,
                observed_sha,
                observed_tree,
                host_identity,
                plan["effective_configuration_digest"],
                artifacts,
                name,
                entry,
                contract["requiredTargetHostScenarios"][name]["requiredInvariants"],
            )
        )
    aggregate = validate_aggregate(receipts, contract, observed_sha, observed_tree)
    atomic_json(output / "aggregate.json", aggregate)
    print(json.dumps(aggregate, sort_keys=True))
    return 0


def verify(args: argparse.Namespace) -> int:
    workspace = args.workspace.resolve(strict=True)
    contract = load_contract(workspace)
    evidence = args.evidence.resolve(strict=True)
    require(not evidence.is_symlink(), "evidence root cannot be a symlink")
    require(SHA40.fullmatch(args.expected_sha) is not None, "expected SHA must be exact")
    source_tree = args.expected_tree
    require(SHA40.fullmatch(source_tree) is not None, "expected tree must be exact")
    receipts = [read_json(path, MAX_RESULT_BYTES) for path in sorted(evidence.glob("*/receipt.json"))]
    aggregate = validate_aggregate(receipts, contract, args.expected_sha, source_tree)
    atomic_json(args.output.resolve(), aggregate)
    print(json.dumps(aggregate, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="operation", required=True)

    run_parser = subcommands.add_parser("run")
    run_parser.add_argument("--workspace", type=Path, default=Path.cwd())
    run_parser.add_argument("--expected-sha", required=True)
    run_parser.add_argument("--plan", type=Path, required=True)
    run_parser.add_argument("--target-root", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    run_parser.add_argument("--allow-destructive", action="store_true")

    verify_parser = subcommands.add_parser("verify")
    verify_parser.add_argument("--workspace", type=Path, default=Path.cwd())
    verify_parser.add_argument("--expected-sha", required=True)
    verify_parser.add_argument("--expected-tree", required=True)
    verify_parser.add_argument("--evidence", type=Path, required=True)
    verify_parser.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    try:
        return run(args) if args.operation == "run" else verify(args)
    except (OSError, ValueError, subprocess.SubprocessError, KeyError, TypeError) as error:
        print(f"runtime.agentd target-host qualification rejected: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
