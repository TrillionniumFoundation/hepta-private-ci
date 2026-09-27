#!/usr/bin/env python3
"""Run runtime.codex qualification commands and emit a canonical receipt.

The workflow signs the receipt with GitHub artifact provenance attestation.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import shlex
import subprocess
import sys
import time
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_SOURCES = [
    "codex-rs/app-server/src/request_processors/thread_processor.rs",
    "codex-rs/app-server/src/request_processors/turn_processor.rs",
    "codex-rs/core/src/tools/spec_plan.rs",
    "codex-rs/hepta-codex-adapter/src/lib.rs",
    "codex-rs/hepta-infer-core/src/native_control.rs",
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    "codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs",
    "codex-rs/hepta-agent-protocol/src/lib.rs",
    "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
    "codex-rs/hepta-agentd/src/state_control.rs",
    "docs/modules/runtime.codex/TECHNICAL.md",
    "docs/modules/runtime.codex/FAULT_MATRIX.md",
    "docs/modules/runtime.codex/STATE_MACHINE.md",
    "docs/modules/runtime.codex/QUARANTINE_AND_RELEASE.md",
]


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def atomic_append_jsonl(path: pathlib.Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = canonical_bytes(value) + b"\n"
    with path.open("ab", buffering=0) as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def run_command(args: argparse.Namespace) -> int:
    if not args.command:
        raise SystemExit("run requires a command after --")
    results = pathlib.Path(args.results)
    log_dir = pathlib.Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{args.name}.log"
    started = time.monotonic()
    started_at = dt.datetime.now(dt.timezone.utc).isoformat()
    cwd = ROOT / args.cwd if args.cwd else ROOT
    env = os.environ.copy()
    env.update(item.split("=", 1) for item in args.env)
    with log_path.open("wb") as log:
        process = subprocess.run(
            args.command,
            cwd=cwd,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
        log.flush()
        os.fsync(log.fileno())
    record = {
        "name": args.name,
        "required": not args.optional,
        "cwd": str(cwd.relative_to(ROOT)),
        "argv": args.command,
        "shell": shlex.join(args.command),
        "startedAt": started_at,
        "durationMs": round((time.monotonic() - started) * 1000),
        "exitCode": process.returncode,
        "outcome": "passed" if process.returncode == 0 else "failed",
        "log": str(log_path),
        "logSha256": sha256_file(log_path),
    }
    atomic_append_jsonl(results, record)
    print(json.dumps(record, indent=2, sort_keys=True))
    # Continue the matrix so the receipt records all failures. `gate` decides.
    return 0


def read_results(path: pathlib.Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: result is not an object")
            records.append(value)
    names = [record.get("name") for record in records]
    if len(names) != len(set(names)):
        raise ValueError("duplicate qualification command name")
    return records


def source_objects(paths: list[str]) -> list[dict[str, Any]]:
    objects = []
    for relative in paths:
        path = ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(relative)
        objects.append(
            {
                "path": relative,
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )
    return objects


def receipt(args: argparse.Namespace) -> int:
    output_dir = pathlib.Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    commands = read_results(pathlib.Path(args.results))
    required = [command for command in commands if command.get("required")]
    required_pass = bool(required) and all(
        command.get("outcome") == "passed" for command in required
    )

    head = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    base_ref = os.environ.get("RUNTIME_CODEX_BASE_REF")
    base_head = os.environ.get("RUNTIME_CODEX_BASE_HEAD")
    merge_head = os.environ.get("RUNTIME_CODEX_MERGE_HEAD")
    merge_tree = os.environ.get("RUNTIME_CODEX_MERGE_TREE")
    mode = args.mode

    candidate = {
        "mode": mode,
        "exactHead": head,
        "exactTree": tree,
        "baseRef": base_ref,
        "baseHead": base_head,
        "mergeHead": merge_head,
        "mergeTree": merge_tree,
        "workingTreeClean": not bool(git("status", "--porcelain")),
    }
    if mode == "synthetic-merge" and (not merge_head or not merge_tree):
        raise ValueError("synthetic-merge receipt requires merge head and tree")

    payload = {
        "schema": "hepta.runtime-codex.qualification-receipt.v1",
        "schemaVersion": 1,
        "module": "runtime.codex",
        "candidate": candidate,
        "workflow": {
            "repository": os.environ.get("GITHUB_REPOSITORY"),
            "runId": os.environ.get("GITHUB_RUN_ID"),
            "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "workflow": os.environ.get("GITHUB_WORKFLOW"),
            "job": os.environ.get("GITHUB_JOB"),
            "runnerOs": os.environ.get("RUNNER_OS"),
            "runnerArch": os.environ.get("RUNNER_ARCH"),
        },
        "sourceObjects": source_objects(args.source),
        "commands": commands,
        "repositoryControlledGates": {
            "allRequiredCommandsPassed": required_pass,
            "exactCandidateBound": True,
            "cleanWorktree": candidate["workingTreeClean"],
            "githubArtifactAttestationRequired": True,
            "sourceClosureEligible": (
                required_pass
                and candidate["workingTreeClean"]
                and (
                    mode == "exact-head"
                    or (bool(merge_head) and bool(merge_tree))
                )
            ),
        },
        "externalGates": {
            "targetHostIdentity": False,
            "productionIssuerAndKeyCustody": False,
            "trustedTimeAndRevocationDistribution": False,
            "externalAntiRollback": False,
            "realProviderTerminalStream": False,
            "externalToolTerminality": False,
            "performanceBaselineAccepted": False,
            "canary": False,
            "rollbackRehearsal": False,
            "independentAcceptance": False,
            "activation": False,
            "promotion": False,
            "release": False,
        },
        "claimBoundary": {
            "sourceEvidenceOnly": True,
            "productionImplementation": False,
            "deploymentQualificationComplete": False,
            "independentAcceptanceComplete": False,
            "release": False,
        },
        "generatedAt": os.environ.get(
            "RUNTIME_CODEX_RECEIPT_TIME",
            dt.datetime.now(dt.timezone.utc).isoformat(),
        ),
    }

    receipt_path = output_dir / "runtime-codex-qualification-receipt.json"
    receipt_path.write_bytes(canonical_bytes(payload))
    receipt_sha = sha256_file(receipt_path)
    (output_dir / "runtime-codex-qualification-receipt.sha256").write_text(
        f"{receipt_sha}  {receipt_path.name}\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def gate(args: argparse.Namespace) -> int:
    commands = read_results(pathlib.Path(args.results))
    missing = sorted(set(args.require) - {item.get("name") for item in commands})
    failed = [
        item["name"]
        for item in commands
        if item.get("required") and item.get("outcome") != "passed"
    ]
    if missing or failed:
        print(json.dumps({"missing": missing, "failed": failed}, indent=2))
        return 1
    if not commands:
        print("no qualification commands were recorded", file=sys.stderr)
        return 1
    print("runtime.codex repository-controlled qualification commands passed")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    sub = root.add_subparsers(dest="subcommand", required=True)

    run = sub.add_parser("run")
    run.add_argument("--results", required=True)
    run.add_argument("--log-dir", required=True)
    run.add_argument("--name", required=True)
    run.add_argument("--cwd", default="")
    run.add_argument("--optional", action="store_true")
    run.add_argument("--env", action="append", default=[])
    run.add_argument("command", nargs=argparse.REMAINDER)
    run.set_defaults(func=run_command)

    make = sub.add_parser("receipt")
    make.add_argument("--results", required=True)
    make.add_argument("--output-dir", required=True)
    make.add_argument(
        "--mode", required=True, choices=["exact-head", "synthetic-merge"]
    )
    make.add_argument("--source", action="append", default=DEFAULT_SOURCES)
    make.set_defaults(func=receipt)

    check = sub.add_parser("gate")
    check.add_argument("--results", required=True)
    check.add_argument("--require", action="append", default=[])
    check.set_defaults(func=gate)
    return root


def main() -> int:
    args = parser().parse_args()
    if getattr(args, "command", None) and args.command[0] == "--":
        args.command = args.command[1:]
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
