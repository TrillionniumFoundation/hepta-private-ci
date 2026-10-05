#!/usr/bin/env python3
"""Run runtime.codex qualification commands and emit a fail-closed receipt.

The receipt binds every command, tracked source object, dependency lock and
candidate tree to one immutable Git object graph. Failed qualification is still
attestable evidence, but it is explicitly marked ``qualified: false`` and the
gate refuses it.
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
    "codex-rs/hepta-agent-protocol",
    "codex-rs/hepta-agentd",
    "codex-rs/hepta-codex-adapter",
    "codex-rs/hepta-infer-core",
    "codex-rs/hepta-infer-worker-host",
    "codex-rs/app-server/src/request_processors/thread_processor.rs",
    "codex-rs/app-server/src/request_processors/turn_processor.rs",
    "codex-rs/core/src/tools/spec_plan.rs",
    "codex-rs/Cargo.lock",
    "rust-toolchain.toml",
    "docs/modules/runtime.codex",
    "scripts/runtime-codex-qualification.py",
    ".github/workflows/runtime-codex-qualification.yml",
]


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


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


def git_bytes(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT, stderr=subprocess.STDOUT)


def git_success(*args: str) -> bool:
    return (
        subprocess.run(
            ["git", *args],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        == 0
    )


def tracked_worktree_clean() -> bool:
    # Qualification logs and receipts are intentionally untracked evidence.
    # Only tracked mutations can alter the candidate object graph.
    return git_success("diff", "--quiet", "HEAD", "--") and git_success(
        "diff", "--cached", "--quiet", "--"
    )


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
    source_head = git("rev-parse", "HEAD")
    source_tree = git("rev-parse", "HEAD^{tree}")
    clean_before = tracked_worktree_clean()
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
    source_head_after = git("rev-parse", "HEAD")
    source_tree_after = git("rev-parse", "HEAD^{tree}")
    clean_after = tracked_worktree_clean()
    record = {
        "name": args.name,
        "required": not args.optional,
        "cwd": str(cwd.relative_to(ROOT)),
        "argv": args.command,
        "shell": shlex.join(args.command),
        "sourceHead": source_head,
        "sourceTree": source_tree,
        "sourceHeadAfter": source_head_after,
        "sourceTreeAfter": source_tree_after,
        "trackedWorktreeCleanBefore": clean_before,
        "trackedWorktreeCleanAfter": clean_after,
        "sourceStable": (
            source_head == source_head_after
            and source_tree == source_tree_after
            and clean_before
            and clean_after
        ),
        "startedAt": started_at,
        "durationMs": round((time.monotonic() - started) * 1000),
        "exitCode": process.returncode,
        "outcome": "passed" if process.returncode == 0 else "failed",
        "log": str(log_path),
        "logSha256": sha256_file(log_path),
    }
    atomic_append_jsonl(results, record)
    print(json.dumps(record, indent=2, sort_keys=True))
    # Continue the matrix so the receipt records every failure. `gate` decides.
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


def expand_tracked_sources(paths: list[str]) -> list[str]:
    expanded: set[str] = set()
    for relative in paths:
        values = git("ls-files", "--", relative).splitlines()
        if not values:
            raise FileNotFoundError(f"no tracked source objects under {relative}")
        expanded.update(value for value in values if value)
    return sorted(expanded)


def source_objects(paths: list[str]) -> tuple[list[dict[str, Any]], bool]:
    objects: list[dict[str, Any]] = []
    all_bound = True
    for relative in expand_tracked_sources(paths):
        path = ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(relative)
        workspace_bytes = path.read_bytes()
        object_bytes = git_bytes("show", f"HEAD:{relative}")
        bound = workspace_bytes == object_bytes
        all_bound = all_bound and bound
        objects.append(
            {
                "path": relative,
                "gitBlobOid": git("rev-parse", f"HEAD:{relative}"),
                "sha256": sha256_bytes(workspace_bytes),
                "gitObjectSha256": sha256_bytes(object_bytes),
                "bytes": len(workspace_bytes),
                "boundToHead": bound,
            }
        )
    return objects, all_bound


def optional_git_ref(ref: str | None) -> str | None:
    if not ref:
        return None
    try:
        return git("rev-parse", ref)
    except subprocess.CalledProcessError:
        return None


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
    current_base_head = os.environ.get("RUNTIME_CODEX_CURRENT_BASE_HEAD")
    source_head = os.environ.get("RUNTIME_CODEX_SOURCE_HEAD")
    merge_head = os.environ.get("RUNTIME_CODEX_MERGE_HEAD")
    merge_tree = os.environ.get("RUNTIME_CODEX_MERGE_TREE")
    expected_head = os.environ.get("RUNTIME_CODEX_EXPECTED_HEAD")
    expected_tree = os.environ.get("RUNTIME_CODEX_EXPECTED_TREE")
    mode = args.mode

    if mode == "synthetic-merge":
        if not merge_head or not merge_tree or not source_head or not base_head:
            raise ValueError(
                "synthetic-merge receipt requires source/base/merge head and tree bindings"
            )
        expected_head = merge_head
        expected_tree = merge_tree
    elif not expected_head or not expected_tree:
        raise ValueError("exact-head receipt requires expected head and tree bindings")

    clean = tracked_worktree_clean()
    objects, objects_bound = source_objects(args.source)
    command_evidence_bound = bool(commands) and all(
        command.get("sourceHead") == head
        and command.get("sourceTree") == tree
        and command.get("sourceHeadAfter") == head
        and command.get("sourceTreeAfter") == tree
        and command.get("sourceStable") is True
        for command in commands
    )
    candidate_bound = head == expected_head and tree == expected_tree
    cargo_lock = next(
        (item for item in objects if item["path"] == "codex-rs/Cargo.lock"), None
    )
    dependency_lock_bound = bool(cargo_lock and cargo_lock.get("boundToHead"))
    target_triple = os.environ.get("RUNTIME_CODEX_TARGET_TRIPLE", "")

    remote_base_ref = f"refs/remotes/origin/{base_ref}" if base_ref else None
    observed_remote_base = optional_git_ref(remote_base_ref)
    current_base_bound = bool(
        base_head
        and current_base_head
        and base_head == current_base_head
        and (observed_remote_base is None or observed_remote_base == base_head)
    )
    parents = git("rev-list", "--parents", "-n", "1", "HEAD").split()
    merge_parents_bound = mode != "synthetic-merge" or (
        len(parents) == 3
        and parents[0] == head
        and parents[1] == source_head
        and parents[2] == base_head
    )
    synthetic_merge_bound = mode != "synthetic-merge" or (
        candidate_bound and current_base_bound and merge_parents_bound
    )
    evidence_artifact_bound = (
        candidate_bound
        and clean
        and objects_bound
        and command_evidence_bound
        and dependency_lock_bound
        and bool(target_triple)
    )
    source_closure_eligible = (
        required_pass and evidence_artifact_bound and synthetic_merge_bound
    )
    qualified = source_closure_eligible

    failures: list[str] = []
    checks = {
        "allRequiredCommandsPassed": required_pass,
        "exactCandidateBound": candidate_bound,
        "cleanTrackedWorktree": clean,
        "sourceObjectsBoundToHead": objects_bound,
        "commandEvidenceBoundToCandidate": command_evidence_bound,
        "dependencyLockBound": dependency_lock_bound,
        "targetTripleBound": bool(target_triple),
        "currentBaseBound": current_base_bound if mode == "synthetic-merge" else True,
        "mergeParentsBound": merge_parents_bound,
        "syntheticMergeBound": synthetic_merge_bound,
        "evidenceArtifactBound": evidence_artifact_bound,
        "sourceClosureEligible": source_closure_eligible,
    }
    failures.extend(name for name, passed in checks.items() if not passed)

    candidate = {
        "mode": mode,
        "exactHead": head,
        "exactTree": tree,
        "expectedHead": expected_head,
        "expectedTree": expected_tree,
        "sourceHead": source_head,
        "baseRef": base_ref,
        "baseHead": base_head,
        "currentBaseHead": current_base_head,
        "observedRemoteBaseHead": observed_remote_base,
        "mergeHead": merge_head,
        "mergeTree": merge_tree,
        "mergeParents": parents[1:],
        "workingTreeClean": clean,
        "targetTriple": target_triple,
        "dependencyLockSha256": cargo_lock["sha256"] if cargo_lock else None,
    }

    payload = {
        "schema": "hepta.runtime-codex.qualification-receipt.v2",
        "schemaVersion": 2,
        "module": "runtime.codex",
        "qualification": {
            "qualified": qualified,
            "failureReasons": failures,
        },
        "candidate": candidate,
        "workflow": {
            "repository": os.environ.get("GITHUB_REPOSITORY"),
            "runId": os.environ.get("GITHUB_RUN_ID"),
            "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "workflow": os.environ.get("GITHUB_WORKFLOW"),
            "workflowRef": os.environ.get("GITHUB_WORKFLOW_REF"),
            "workflowSha": os.environ.get("GITHUB_WORKFLOW_SHA"),
            "job": os.environ.get("GITHUB_JOB"),
            "runnerOs": os.environ.get("RUNNER_OS"),
            "runnerArch": os.environ.get("RUNNER_ARCH"),
        },
        "sourceObjects": objects,
        "commands": commands,
        "repositoryControlledGates": {
            **checks,
            "githubArtifactAttestationRequired": True,
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
    receipt_path = pathlib.Path(args.receipt)
    try:
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"invalid qualification receipt: {error}", file=sys.stderr)
        return 1
    qualified = payload.get("qualification", {}).get("qualified") is True
    receipt_failures = payload.get("qualification", {}).get("failureReasons", [])
    if missing or failed or not commands or not qualified:
        print(
            json.dumps(
                {
                    "missing": missing,
                    "failed": failed,
                    "qualified": qualified,
                    "receiptFailures": receipt_failures,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    print("runtime.codex repository-controlled qualification receipt is qualified")
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
    check.add_argument("--receipt", required=True)
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
