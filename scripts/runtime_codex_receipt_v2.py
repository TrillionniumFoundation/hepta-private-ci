#!/usr/bin/env python3
"""Closed-world source qualification; integrity verification is NOT a signature.

Use `verify-bundle` plus GitHub's independently authenticated attestation verifier
for authenticity. Even authentic CI source receipts never authorize deployment.
Missing, skipped, cancelled, timed-out or malformed commands fail qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "hepta.runtime-codex-source-qualification.v2"
HEX40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")
MAX_JSON = 2 * 1024 * 1024
MAX_LOG = 128 * 1024 * 1024
PACKAGES = (
    "codex-hepta-codex-adapter", "codex-hepta-infer-core",
    "codex-hepta-agent-protocol", "codex-hepta-agentd",
    "codex-hepta-infer-worker-host",
)
# The inventory is versioned with the executable candidate. Every entry must
# exist; a high aggregate test count cannot hide a missing product/fault lane.
PLAN = {
    "runtime-binaries": (0, ["cargo", "build", "--locked", "-p", "codex-cli", "--bin", "codex", "-p", "codex-hepta-agentd", "--bin", "codex-hepta-agentd", "-p", "codex-hepta-infer-worker-host", "--bin", "hepta-infer-worker"]),
    "adapter": (1, ["just", "test", "--locked", "-p", PACKAGES[0]]),
    "durable-control": (1, ["just", "test", "--locked", "-p", PACKAGES[1]]),
    "agent-protocol": (1, ["just", "test", "--locked", "-p", PACKAGES[2]]),
    "agent-run-lifecycle": (1, ["just", "test", "--locked", "-p", PACKAGES[3], "--lib", "lane_b_runtime"]),
    "worker-host": (1, ["just", "test", "--locked", "-p", PACKAGES[4]]),
    "product-e2e": (1, ["just", "test", "--locked", "-p", PACKAGES[3], "--test", "runtime_codex_product_e2e"]),
    "model-only": (1, ["just", "test", "--locked", "-p", "codex-core", "hepta_native_inference_client_has_no_model_visible_or_registered_tools"]),
    "strict-lint": (0, ["cargo", "clippy", "--locked", *[arg for package in PACKAGES for arg in ("-p", package)], "--all-targets", "--", "-D", "warnings"]),
    "formatting": (0, ["cargo", "fmt", *[arg for package in PACKAGES for arg in ("--package", package)], "--", "--check"]),
}
FORBIDDEN = (
    "targetHostIdentityQualified", "realProviderQualified",
    "allCrashBoundariesQualified", "independentAcceptance", "activation",
    "promotion", "release",
)


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path: Path) -> Any:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_JSON:
        raise ValueError("unsafe or oversized JSON file")
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    return json.loads(path.read_bytes(), object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def exact_sha(value: Any) -> bool:
    return isinstance(value, str) and HEX40.fullmatch(value) is not None and value != "0" * 40


def integer(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("expected a nonnegative integer, not a boolean")
    return value


def identity(source: str, tested: str, tree: str, base: str | None, lane: str,
             parents: list[str]) -> dict[str, Any]:
    if not all(exact_sha(item) for item in (source, tested, tree, *parents)):
        raise ValueError("candidate identity must use full nonzero commit/tree IDs")
    if lane == "source-head":
        if source != tested or base is not None:
            raise ValueError("source-head identity mismatch")
    elif lane == "base-merge":
        if not exact_sha(base) or parents != [base, source]:
            raise ValueError("synthetic merge requires exact ordered parents")
    else:
        raise ValueError("source receipt cannot certify a target-host lane")
    return dict(source=source, tested=tested, tree=tree, base=base, lane=lane, parents=parents)


def inspect_record(path: Path, name: str, candidate: dict[str, Any]) -> dict[str, Any]:
    floor, command = PLAN[name]
    record = read_json(path)
    if not isinstance(record, dict) or record.get("schema_version") != 1:
        raise ValueError("wrong command schema")
    expected = {"source_sha": candidate["source"], "tested_sha": candidate["tested"], "lane": candidate["lane"]}
    if any(record.get(key) != val for key, val in expected.items()):
        raise ValueError("command belongs to another candidate or lane")
    before, after = record.get("before"), record.get("after")
    if not isinstance(before, dict) or before != after:
        raise ValueError("source changed during the command")
    if before.get("dirty") is not False or before.get("commit") != candidate["tested"] or before.get("tree") != candidate["tree"] or before.get("parents") != candidate["parents"]:
        raise ValueError("unclean or mismatched command identity")
    if record.get("command") != command or integer(record.get("minimum_tests")) != floor:
        raise ValueError("command or test floor differs from the required plan")
    log_name = record.get("log_file")
    if not isinstance(log_name, str) or not log_name or Path(log_name).name != log_name or log_name in (".", "..") or "\\" in log_name:
        raise ValueError("log must be a sibling file, not a path")
    log = path.parent / log_name
    if log.is_symlink() or not log.is_file() or log.stat().st_size > MAX_LOG:
        raise ValueError("unsafe or missing command log")
    if digest(log) != record.get("log_sha256") or log.stat().st_size != integer(record.get("log_bytes")):
        raise ValueError("command log content or length mismatch")
    passed, failed = integer(record.get("observed_passed_tests")), integer(record.get("observed_failed_tests"))
    success = record.get("status") == "passed" and type(record.get("exit_code")) is int and record["exit_code"] == 0 and passed >= floor and failed == 0
    return dict(name=name, status="passed" if success else "failed", record=path.name,
                recordSha256=digest(path), log=log_name, logSha256=digest(log),
                passed=passed, failed=failed)


def evaluate(records: Path, candidate: dict[str, Any]) -> dict[str, Any]:
    commands = []
    for name in PLAN:
        path = records / (name + ".json")
        if not path.exists():
            commands.append(dict(name=name, status="missing"))
            continue
        try:
            commands.append(inspect_record(path, name, candidate))
        except (ValueError, TypeError, KeyError, OSError) as error:
            commands.append(dict(name=name, status="invalid", error=str(error)))
    extra = sorted(path.name for path in records.glob("*.json") if path.name not in {name + ".json" for name in PLAN})
    complete = not extra and all(row["status"] == "passed" for row in commands)
    return dict(schema=SCHEMA, module="runtime.codex", candidate=candidate,
                planSha256=hashlib.sha256(canonical(PLAN)).hexdigest(), commands=commands,
                unexpectedRecords=extra, status="passed" if complete else "failed",
                claims={"sourceQualification": complete, **{key: False for key in FORBIDDEN}})


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def verify_contents(path: Path, records: Path) -> dict[str, Any]:
    value = read_json(path)
    if not isinstance(value, dict) or path.read_bytes() != canonical(value):
        raise ValueError("receipt must be canonical JSON")
    supplied = value.get("candidate", {})
    candidate = identity(**supplied)
    expected = evaluate(records, candidate)
    for key, val in expected.items():
        if value.get(key) != val:
            raise ValueError(f"receipt does not match retained evidence: {key}")
    if set(value) != set(expected) | {"generatedAt", "workflow"}:
        raise ValueError("unknown or missing critical receipt fields")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    build = sub.add_parser("build")
    build.add_argument("--source", required=True)
    build.add_argument("--base")
    build.add_argument("--lane", choices=("source-head", "base-merge"), required=True)
    build.add_argument("--records", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    for name in ("verify-contents", "verify-bundle"):
        check = sub.add_parser(name)
        check.add_argument("receipt", type=Path)
        check.add_argument("--records", type=Path, required=True)
        if name == "verify-bundle":
            check.add_argument("--bundle", type=Path, required=True)
            check.add_argument("--repository", required=True)
            check.add_argument("--signer-workflow", required=True)
    run = sub.add_parser("execute")
    run.add_argument("--records", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "execute":
        args.records.mkdir(parents=True, exist_ok=True)
        failed = False
        for name, (floor, command) in PLAN.items():
            result = subprocess.run(["python3", "../scripts/hepta_ci_exec.py", "--output", str(args.records.resolve() / (name + ".json")), "--minimum-tests", str(floor), "--timeout-seconds", "3600", "--", *command], check=False)
            failed |= result.returncode != 0
        return int(failed)
    if args.mode == "build":
        if git("status", "--porcelain", "--untracked-files=normal"):
            raise ValueError("cannot certify a dirty working tree")
        candidate = identity(args.source, git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}"), args.base, args.lane, git("show", "-s", "--format=%P", "HEAD").split())
        if args.lane == "base-merge" and git("merge-tree", "--write-tree", args.base, args.source) != candidate["tree"]:
            raise ValueError("synthetic merge tree differs from recomputation")
        value = evaluate(args.records, candidate)
        value["generatedAt"] = datetime.now(timezone.utc).isoformat()
        value["workflow"] = {key: os.environ.get(key) for key in ("GITHUB_REPOSITORY", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB", "GITHUB_WORKFLOW_REF", "RUNNER_OS", "RUNNER_ARCH")}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(canonical(value))
        print(json.dumps({"status": value["status"], "sha256": digest(args.output), "authenticity": "not-checked"}))
        return int(value["status"] != "passed")
    if args.mode == "verify-bundle":
        subprocess.run(["gh", "attestation", "verify", str(args.receipt), "--bundle", str(args.bundle), "--repo", args.repository, "--signer-workflow", args.signer_workflow], check=True)
    value = verify_contents(args.receipt, args.records)
    print(json.dumps({"status": value["status"], "authenticity": "attestation-verified" if args.mode == "verify-bundle" else "not-checked"}))
    return int(value["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
