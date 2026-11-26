#!/usr/bin/env python3
"""Build and verify exact-candidate runtime.codex qualification receipts.

The receipt is deliberately repository-controlled evidence only.  The workflow
attests the canonical JSON with GitHub OIDC; this program never upgrades source
tests into target-host identity, real-provider qualification, independent
acceptance, activation, promotion, or release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HEX40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")
VALID_LANES = {"source-head", "base-merge", "target-host"}


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_record(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != 1:
        raise ValueError(f"unsupported command record schema: {path}")
    if value.get("status") != "passed" or value.get("exit_code") != 0:
        raise ValueError(f"command record is not passing: {path}")
    before = value.get("before")
    after = value.get("after")
    if not isinstance(before, dict) or before != after or before.get("dirty"):
        raise ValueError(f"command record did not preserve a clean identity: {path}")
    log_sha = value.get("log_sha256")
    if not isinstance(log_sha, str) or not HEX64.fullmatch(log_sha):
        raise ValueError(f"command record omitted a log digest: {path}")
    return value


def command_summary(path: Path, record: dict[str, Any]) -> dict[str, Any]:
    return {
        "record": path.name,
        "recordSha256": sha256(path),
        "command": record["command"],
        "workingDirectory": record["working_directory"],
        "startedAt": record["started_at"],
        "finishedAt": record["finished_at"],
        "elapsedSeconds": record["elapsed_seconds"],
        "logFile": record["log_file"],
        "logSha256": record["log_sha256"],
        "logBytes": record["log_bytes"],
        "observedPassedTests": record["observed_passed_tests"],
        "observedFailedTests": record["observed_failed_tests"],
        "minimumTests": record["minimum_tests"],
        "status": record["status"],
    }


def read_os_release() -> dict[str, str]:
    path = Path("/etc/os-release")
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key] = value.strip().strip('"')
    return result


def tool_version(command: list[str]) -> str:
    return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT).strip()


def build_receipt(args: argparse.Namespace) -> dict[str, Any]:
    if not HEX40.fullmatch(args.source_sha):
        raise ValueError("source SHA must be an exact 40-character identity")
    if not HEX40.fullmatch(args.tested_sha):
        raise ValueError("tested SHA must be an exact 40-character identity")
    if args.lane not in VALID_LANES:
        raise ValueError("unsupported qualification lane")
    if args.lane == "base-merge" and not HEX40.fullmatch(args.base_sha or ""):
        raise ValueError("base-merge receipts require an exact base SHA")
    if args.lane == "source-head" and args.source_sha != args.tested_sha:
        raise ValueError("source-head receipt must test the source SHA")

    records = sorted(args.records.glob("*.json"))
    if not records:
        raise ValueError("no command records were supplied")
    loaded = [(path, load_record(path)) for path in records]
    identity = loaded[0][1]["before"]
    for path, record in loaded:
        if record.get("source_sha") != args.source_sha:
            raise ValueError(f"source identity mismatch: {path}")
        if record.get("tested_sha") != args.tested_sha:
            raise ValueError(f"tested identity mismatch: {path}")
        if record.get("lane") != args.lane:
            raise ValueError(f"lane mismatch: {path}")
        if record["before"] != identity:
            raise ValueError(f"mixed candidate identities: {path}")
        log_path = path.with_name(record["log_file"])
        if not log_path.is_file() or sha256(log_path) != record["log_sha256"]:
            raise ValueError(f"command log digest mismatch: {path}")

    if identity.get("commit") != args.tested_sha:
        raise ValueError("command records do not identify the tested commit")
    tree = identity.get("tree")
    if not isinstance(tree, str) or not HEX40.fullmatch(tree):
        raise ValueError("command records omitted the exact tree")
    if args.expected_tree and tree != args.expected_tree:
        raise ValueError("tested tree differs from the expected tree")
    if args.lane == "base-merge":
        if identity.get("parents") != [args.base_sha, args.source_sha]:
            raise ValueError("base-merge parent order is not exact")
        expected_tree = git("merge-tree", "--write-tree", args.base_sha, args.source_sha)
        if tree != expected_tree:
            raise ValueError("base-merge tree differs from recomputation")

    observed = sum(int(record["observed_passed_tests"]) for _, record in loaded)
    failed = sum(int(record["observed_failed_tests"]) for _, record in loaded)
    if failed or observed < args.minimum_total_tests:
        raise ValueError("the required observed test floor was not met")

    receipt = {
        "schema": "hepta.runtime-codex-qualification.v1",
        "schemaVersion": 1,
        "module": "runtime.codex",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "lane": args.lane,
        "source": {
            "commit": args.source_sha,
            "tree": git("rev-parse", f"{args.source_sha}^{{tree}}"),
        },
        "candidate": {
            "commit": args.tested_sha,
            "tree": tree,
            "parents": identity.get("parents", []),
            "base": args.base_sha,
            "clean": not identity.get("dirty"),
        },
        "host": {
            "runnerName": os.environ.get("RUNNER_NAME"),
            "runnerEnvironment": os.environ.get("RUNNER_ENVIRONMENT"),
            "architecture": platform.machine(),
            "platform": platform.platform(),
            "osRelease": read_os_release(),
            "rustc": tool_version(["rustc", "--version", "--verbose"]),
            "cargo": tool_version(["cargo", "--version", "--verbose"]),
        },
        "workflow": {
            "repository": os.environ.get("GITHUB_REPOSITORY"),
            "runId": os.environ.get("GITHUB_RUN_ID"),
            "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "job": os.environ.get("GITHUB_JOB"),
            "workflowRef": os.environ.get("GITHUB_WORKFLOW_REF"),
            "actor": os.environ.get("GITHUB_ACTOR"),
        },
        "commands": [command_summary(path, record) for path, record in loaded],
        "observedPassedTests": observed,
        "observedFailedTests": failed,
        "minimumTotalTests": args.minimum_total_tests,
        "claimBoundary": {
            "repositoryControlledSourceQualification": True,
            "exactCandidateExecution": True,
            "targetHostIdentityQualified": args.lane == "target-host",
            "realProviderQualified": args.lane == "target-host" and args.real_provider,
            "independentAcceptance": False,
            "activation": False,
            "promotion": False,
            "release": False,
        },
        "externalGates": [
            "deployed issuer identity and signing-key custody",
            "trusted wall-clock and revocation distribution",
            "target-host Agentd/App Server process and socket identity",
            "real provider terminal stream and acknowledgement-loss behavior",
            "independent quarantine-resolution authority",
            "independent acceptance, activation, promotion and release",
        ],
    }
    if args.metrics:
        metrics = json.loads(args.metrics.read_text(encoding="utf-8"))
        if metrics.get("testedSha") != args.tested_sha:
            raise ValueError("performance metrics identify another candidate")
        receipt["performance"] = metrics
    return receipt


def canonical_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def write_receipt(args: argparse.Namespace) -> None:
    receipt = build_receipt(args)
    encoded = canonical_bytes(receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(encoded)
    digest = hashlib.sha256(encoded).hexdigest()
    args.output.with_suffix(args.output.suffix + ".sha256").write_text(
        f"{digest}  {args.output.name}\n", encoding="utf-8"
    )
    print(json.dumps({"receipt": str(args.output), "sha256": digest}, sort_keys=True))


def verify_receipt(path: Path) -> None:
    raw = path.read_bytes()
    value = json.loads(raw)
    if raw != canonical_bytes(value):
        raise ValueError("receipt is not canonical JSON")
    if value.get("schema") != "hepta.runtime-codex-qualification.v1":
        raise ValueError("unsupported receipt schema")
    if value.get("module") != "runtime.codex":
        raise ValueError("wrong module receipt")
    candidate = value.get("candidate", {})
    if not HEX40.fullmatch(candidate.get("commit", "")):
        raise ValueError("receipt omitted exact candidate commit")
    if not HEX40.fullmatch(candidate.get("tree", "")):
        raise ValueError("receipt omitted exact candidate tree")
    if not candidate.get("clean"):
        raise ValueError("receipt candidate was not clean")
    if value.get("observedFailedTests") != 0:
        raise ValueError("receipt contains failed tests")
    if value.get("observedPassedTests", 0) < value.get("minimumTotalTests", 0):
        raise ValueError("receipt does not meet its declared test floor")
    claims = value.get("claimBoundary", {})
    for forbidden in ("independentAcceptance", "activation", "promotion", "release"):
        if claims.get(forbidden):
            raise ValueError(f"repository receipt illegally claims {forbidden}")
    digest_file = path.with_suffix(path.suffix + ".sha256")
    expected = digest_file.read_text(encoding="utf-8").split()[0]
    actual = hashlib.sha256(raw).hexdigest()
    if expected != actual:
        raise ValueError("receipt digest sidecar mismatch")
    print(json.dumps({"verified": str(path), "sha256": actual}, sort_keys=True))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--source-sha", required=True)
    build.add_argument("--tested-sha", required=True)
    build.add_argument("--expected-tree")
    build.add_argument("--base-sha")
    build.add_argument("--lane", choices=sorted(VALID_LANES), required=True)
    build.add_argument("--records", type=Path, required=True)
    build.add_argument("--metrics", type=Path)
    build.add_argument("--minimum-total-tests", type=int, default=1)
    build.add_argument("--real-provider", action="store_true")
    build.add_argument("--output", type=Path, required=True)
    check = sub.add_parser("verify")
    check.add_argument("receipt", type=Path)
    return root


def main() -> None:
    args = parser().parse_args()
    if args.command == "build":
        write_receipt(args)
    else:
        verify_receipt(args.receipt)


if __name__ == "__main__":
    main()
