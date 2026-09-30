#!/usr/bin/env python3
"""Emit and verify immutable learning.operator qualification receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "hepta.learning-operator.qualification.v1"
COMBINED_SCHEMA = "hepta.learning-operator.qualification-set.v1"
MAX_AGE_DAYS = 30
INPUT_PATHS = (
    "codex-rs/hepta-bellman-operator",
    "codex-rs/hepta-agentd/src/shared_terminal_cell.rs",
    "codex-rs/hepta-agentd/tests/terminal_cell_owner.rs",
    "codex-rs/hepta-shadow-qualification/tests/lane_e_api_contract.rs",
    "docs/modules/learning.operator/TECHNICAL.md",
    "docs/modules/learning.operator/IMPLEMENTATION_MAP.json",
    "qualification/lane-e/TEST_TRACEABILITY.json",
    "qualification/module-execution-dossiers/detail/learning.operator.md",
    ".github/workflows/learning-operator-required.yml",
    ".github/workflows/blocking-ci.yml",
    "scripts/hepta-learning-operator-receipt.py",
    "scripts/hepta-learning-operator-mutation.py",
    "codex-rs/Cargo.lock",
)
DIGEST_FILES = {
    "cargoLockSha256": "codex-rs/Cargo.lock",
    "implementationMapSha256": "docs/modules/learning.operator/IMPLEMENTATION_MAP.json",
    "technicalGuideSha256": "docs/modules/learning.operator/TECHNICAL.md",
    "nativeMappingSha256": "codex-rs/hepta-bellman-operator/NATIVE_MAPPING.md",
    "traceabilitySha256": "qualification/lane-e/TEST_TRACEABILITY.json",
    "workflowSha256": ".github/workflows/learning-operator-required.yml",
}


def run(*args: str) -> bytes:
    return subprocess.run(
        args,
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def git_text(*args: str) -> str:
    return run("git", *args).decode("utf-8").strip()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def index_bytes(path: str) -> bytes:
    return run("git", "show", f":{path}")


def tracked_paths() -> list[str]:
    raw = run("git", "ls-files", "-z", "--", *INPUT_PATHS)
    paths = sorted(item.decode("utf-8") for item in raw.split(b"\0") if item)
    if not paths:
        raise ValueError("no tracked learning.operator qualification inputs")
    return paths


def input_digest() -> tuple[str, int]:
    digest = hashlib.sha256()
    paths = tracked_paths()
    for path in paths:
        raw_path = path.encode("utf-8")
        content = index_bytes(path)
        digest.update(len(raw_path).to_bytes(4, "big"))
        digest.update(raw_path)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest(), len(paths)


def file_digest(path: str) -> str:
    return sha256_bytes(index_bytes(path))


def output_digest(path_value: str) -> dict[str, Any]:
    path = (ROOT / path_value).resolve()
    root = ROOT.resolve()
    if path != root and root not in path.parents:
        raise ValueError("qualification output must remain inside the workspace")
    if not path.is_file():
        raise ValueError(f"missing qualification output: {path_value}")
    content = path.read_bytes()
    if not content:
        raise ValueError(f"empty qualification output: {path_value}")
    return {
        "path": str(path.relative_to(root)),
        "sha256": sha256_bytes(content),
        "bytes": len(content),
    }


def command_identity(*args: str) -> dict[str, str]:
    output = run(*args).decode("utf-8")
    return {"text": output.strip(), "sha256": sha256_bytes(output.encode("utf-8"))}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def environment_identity() -> dict[str, str]:
    keys = (
        "GITHUB_REPOSITORY",
        "GITHUB_WORKFLOW",
        "GITHUB_WORKFLOW_REF",
        "GITHUB_WORKFLOW_SHA",
        "GITHUB_RUN_ID",
        "GITHUB_RUN_ATTEMPT",
        "GITHUB_JOB",
        "GITHUB_ACTOR",
        "RUNNER_OS",
        "RUNNER_ARCH",
        "RUNNER_NAME",
        "RUNNER_ENVIRONMENT",
        "ImageOS",
        "ImageVersion",
    )
    return {key: os.environ.get(key, "") for key in keys}


def emit(args: argparse.Namespace) -> dict[str, Any]:
    source_sha = args.source_sha
    candidate_sha = args.candidate_sha
    source_tree = git_text("rev-parse", f"{source_sha}^{{tree}}")
    candidate_tree = git_text("rev-parse", f"{candidate_sha}^{{tree}}")
    index_tree = git_text("write-tree")
    if candidate_tree != args.candidate_tree or index_tree != args.candidate_tree:
        raise ValueError("candidate SHA, supplied tree and checked-out index differ")
    if args.mode == "exact-source":
        if source_sha != candidate_sha:
            raise ValueError("exact-source candidate must equal source")
    elif args.mode == "synthetic-merge":
        if not args.base_sha:
            raise ValueError("synthetic merge requires base SHA")
        if git_text("rev-parse", f"{candidate_sha}^1") != args.base_sha:
            raise ValueError("synthetic merge first parent is not base")
        if git_text("rev-parse", f"{candidate_sha}^2") != source_sha:
            raise ValueError("synthetic merge second parent is not source")
    else:
        raise ValueError("unsupported receipt mode")

    generated = now_utc()
    digest, count = input_digest()
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "mode": args.mode,
        "source": {
            "commit": source_sha,
            "tree": source_tree,
            "baseCommit": args.base_sha or None,
            "candidateCommit": candidate_sha,
            "candidateTree": candidate_tree,
        },
        "inputs": {
            "setSha256": digest,
            "trackedFileCount": count,
            **{key: file_digest(path) for key, path in DIGEST_FILES.items()},
        },
        "testSet": {
            "sha256": sha256_bytes(
                b"operator-unit\nowner-final-use\nagentd-shadow-loop\nrevocation\nrollback\ncoverage\nmutation\nperformance\n"
            ),
            "required": [
                "operator-unit",
                "owner-final-use",
                "agentd-shadow-loop",
                "currentness-revocation",
                "rollback-lineage",
                "coverage",
                "mutation",
                "performance",
            ],
        },
        "toolchain": {
            "rustc": command_identity("rustc", "-Vv"),
            "cargo": command_identity("cargo", "-V"),
            "host": platform.platform(),
            "machine": platform.machine(),
        },
        "runner": environment_identity(),
        "outputs": {},
        "generatedAt": iso(generated),
        "expiresAt": iso(generated + timedelta(days=MAX_AGE_DAYS)),
        "authority": "DENY_ALL",
        "productionActivation": False,
        "independentAcceptance": False,
    }
    for label, value in (
        ("coverage", args.coverage),
        ("mutation", args.mutation),
        ("performance", args.performance),
        ("testLog", args.test_log),
    ):
        if value:
            receipt["outputs"][label] = output_digest(value)
    required_outputs = (
        {"coverage", "mutation", "performance", "testLog"}
        if args.mode == "exact-source"
        else {"testLog"}
    )
    if set(receipt["outputs"]) != required_outputs:
        raise ValueError(
            f"{args.mode} receipt output set differs: {sorted(receipt['outputs'])}"
        )

    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def verify_receipt(path: Path, *, bind_index: bool = True) -> dict[str, Any]:
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if receipt.get("schema") != SCHEMA:
        raise ValueError("unexpected receipt schema")
    mode = receipt.get("mode")
    if mode not in {"exact-source", "synthetic-merge"}:
        raise ValueError("invalid receipt mode")
    source = receipt.get("source")
    if not isinstance(source, dict):
        raise ValueError("missing source identity")
    source_sha = str(source.get("commit", ""))
    candidate_sha = str(source.get("candidateCommit", ""))
    candidate_tree = str(source.get("candidateTree", ""))
    if source.get("tree") != git_text("rev-parse", f"{source_sha}^{{tree}}"):
        raise ValueError("source commit/tree mismatch")
    if candidate_tree != git_text("rev-parse", f"{candidate_sha}^{{tree}}"):
        raise ValueError("candidate commit/tree mismatch")
    if bind_index and candidate_tree != git_text("write-tree"):
        raise ValueError("receipt does not bind checked-out candidate tree")
    if mode == "exact-source":
        if candidate_sha != source_sha:
            raise ValueError("exact-source identity mismatch")
        required_outputs = {"coverage", "mutation", "performance", "testLog"}
    else:
        base = str(source.get("baseCommit", ""))
        if git_text("rev-parse", f"{candidate_sha}^1") != base:
            raise ValueError("synthetic merge first parent mismatch")
        if git_text("rev-parse", f"{candidate_sha}^2") != source_sha:
            raise ValueError("synthetic merge second parent mismatch")
        required_outputs = {"testLog"}

    inputs = receipt.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("missing input identity")
    digest, count = input_digest()
    if inputs.get("setSha256") != digest or inputs.get("trackedFileCount") != count:
        raise ValueError("qualification input set drift")
    for key, source_path in DIGEST_FILES.items():
        if inputs.get(key) != file_digest(source_path):
            raise ValueError(f"stale input digest: {key}")
    outputs = receipt.get("outputs")
    if not isinstance(outputs, dict) or set(outputs) != required_outputs:
        raise ValueError("qualification outputs are incomplete")
    for label, item in outputs.items():
        if not isinstance(item, dict):
            raise ValueError(f"invalid output: {label}")
        if item != output_digest(str(item.get("path", ""))):
            raise ValueError(f"stale output: {label}")
    if receipt.get("authority") != "DENY_ALL" or receipt.get("productionActivation") is not False:
        raise ValueError("qualification receipt may not grant authority")
    generated = parse_time(receipt.get("generatedAt"))
    expires = parse_time(receipt.get("expiresAt"))
    now = now_utc()
    if generated > now + timedelta(minutes=5) or expires <= now or expires - generated > timedelta(days=MAX_AGE_DAYS):
        raise ValueError("receipt timestamp validity failure")
    return receipt


def combine(args: argparse.Namespace) -> dict[str, Any]:
    exact = verify_receipt(ROOT / args.exact, bind_index=False)
    merge = verify_receipt(ROOT / args.synthetic, bind_index=False)
    if exact["mode"] != "exact-source" or merge["mode"] != "synthetic-merge":
        raise ValueError("combined set requires exact-source and synthetic-merge receipts")
    if exact["source"]["commit"] != merge["source"]["commit"]:
        raise ValueError("qualification receipts do not share one source SHA")
    generated = now_utc()
    combined = {
        "schema": COMBINED_SCHEMA,
        "sourceCommit": exact["source"]["commit"],
        "sourceTree": exact["source"]["tree"],
        "baseCommit": merge["source"]["baseCommit"],
        "syntheticMergeCommit": merge["source"]["candidateCommit"],
        "syntheticMergeTree": merge["source"]["candidateTree"],
        "exactReceipt": output_digest(args.exact),
        "syntheticReceipt": output_digest(args.synthetic),
        "qualification": "success",
        "skippedAccepted": False,
        "authority": "DENY_ALL",
        "generatedAt": iso(generated),
        "expiresAt": iso(generated + timedelta(days=MAX_AGE_DAYS)),
    }
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(combined, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return combined


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    emit_parser = sub.add_parser("emit")
    emit_parser.add_argument("--mode", choices=("exact-source", "synthetic-merge"), required=True)
    emit_parser.add_argument("--source-sha", required=True)
    emit_parser.add_argument("--base-sha", default="")
    emit_parser.add_argument("--candidate-sha", required=True)
    emit_parser.add_argument("--candidate-tree", required=True)
    emit_parser.add_argument("--coverage")
    emit_parser.add_argument("--mutation")
    emit_parser.add_argument("--performance")
    emit_parser.add_argument("--test-log", required=True)
    emit_parser.add_argument("--output", required=True)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("path")
    combine_parser = sub.add_parser("combine")
    combine_parser.add_argument("--exact", required=True)
    combine_parser.add_argument("--synthetic", required=True)
    combine_parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        if args.command == "emit":
            result = emit(args)
        elif args.command == "verify":
            result = verify_receipt(ROOT / args.path)
        else:
            result = combine(args)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        print(f"learning.operator receipt failure: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
