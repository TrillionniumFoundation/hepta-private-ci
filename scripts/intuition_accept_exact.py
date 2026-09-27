#!/usr/bin/env python3
"""Verify two CI artifact bundles from distinct jobs at one exact source SHA.

Hashes establish bundle integrity, not signer independence. Only artifacts
retrieved by the workflow from its own run may be used. Semantic evaluator,
operator, target-host and promotion acceptance remain separate external gates.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from intuition_qualify_exact import (
    COMMANDS, INDEPENDENT_COMMANDS, SCHEMA, external_directory,
    nonzero_tests, seal, sha256, write_json,
)


def verify_bundle(path: Path, mode: str, source: str, context: dict[str, str]) -> dict:
    manifest = json.loads((path / "artifact-manifest.json").read_text())
    if manifest.get("schema") != "hepta.intuition.artifacts.v1":
        raise ValueError("unsupported artifact manifest")
    hashes = manifest.get("sha256", {})
    required = {"command-record.json", "toolchain.txt", "IMPLEMENTATION_MAP.json", "execution-dossier.md"}
    if not required <= set(hashes):
        raise ValueError("missing mandatory evidence artifacts")
    for name, digest in hashes.items():
        member = path / name
        if Path(name).name != name or member.is_symlink() or not member.is_file():
            raise ValueError("invalid artifact path")
        if sha256(member) != digest:
            raise ValueError(f"artifact digest mismatch: {name}")
    record = json.loads((path / "command-record.json").read_text())
    if record.get("schema") != SCHEMA or record.get("mode") != mode:
        raise ValueError("evidence schema or mode mismatch")
    if record.get("sourceSha") != source or record.get("testedSha") != source or record.get("lane") != "source-head":
        raise ValueError("evidence is not for the exact source head")
    if record.get("status") != "passed" or record.get("worktreeUnchanged") is not True:
        raise ValueError("failed or dirty execution")
    for key in ("runId", "runAttempt", "repository"):
        if not context.get(key) or record.get(key) != context[key]:
            raise ValueError(f"CI provenance mismatch: {key}")
    if not record.get("jobId"):
        raise ValueError("job identity is required")
    if record.get("toolchainLogSha256") != hashes["toolchain.txt"] or not record.get("cargoLockSha256"):
        raise ValueError("toolchain or lockfile evidence is missing")
    commands = COMMANDS if mode == "qualification" else INDEPENDENT_COMMANDS
    rows = record.get("commands", [])
    if len(rows) != len(commands):
        raise ValueError("incomplete command set")
    for row, (name, argv) in zip(rows, commands):
        if row.get("name") != name or row.get("argv") != argv or row.get("cwd") != "codex-rs":
            raise ValueError("command substitution or ordering mismatch")
        if row.get("exitCode") != 0 or row.get("status") != "passed":
            raise ValueError(f"unsuccessful command: {name}")
        log = name + ".log"
        if row.get("log") != log or row.get("logSha256") != hashes.get(log):
            raise ValueError(f"missing or substituted command log: {name}")
        if argv[:2] == ["cargo", "test"] and not nonzero_tests(path / log):
            raise ValueError(f"empty test execution: {name}")
        if name == "release-binaries" and not row.get("binaries"):
            raise ValueError("missing release binary digests")
    return record


def verify_pair(standard: Path, independent: Path, source: str, context: dict[str, str]) -> tuple[dict, dict]:
    first = verify_bundle(standard, "qualification", source, context)
    second = verify_bundle(independent, "independent", source, context)
    if first["jobId"] == second["jobId"]:
        raise ValueError("independent execution must use a different CI job")
    for key in ("testedTree", "cargoLockSha256"):
        if not first.get(key) or first[key] != second.get(key):
            raise ValueError(f"executions disagree on {key}")
    return first, second


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--qualification", required=True, type=Path)
    parser.add_argument("--independent", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    context = {"runId": os.environ.get("GITHUB_RUN_ID", ""),
               "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT", ""),
               "repository": os.environ.get("GITHUB_REPOSITORY", "")}
    try:
        output = external_directory(args.output)
        first, second = verify_pair(args.qualification, args.independent, args.source_commit, context)
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"acceptance rejected: {error}", file=sys.stderr)
        return 1
    acceptance = {
        "schema": "hepta.intuition.independent-execution.v1",
        "sourceSha": args.source_commit, "testedTree": first["testedTree"],
        **context, "jobs": [first["jobId"], second["jobId"]],
        "qualificationReportSha256": sha256(args.qualification / "command-record.json"),
        "independentReportSha256": sha256(args.independent / "command-record.json"),
        "qualificationManifestSha256": sha256(args.qualification / "artifact-manifest.json"),
        "independentManifestSha256": sha256(args.independent / "artifact-manifest.json"),
        "independentExecutionVerified": True,
        "semanticEvaluatorAcceptance": "not_established",
        "targetHostAcceptance": "not_established", "promotion": "not_authorized",
    }
    write_json(output / "independent-execution.json", acceptance)
    mapping = json.loads((args.qualification / "IMPLEMENTATION_MAP.json").read_text())
    mapping["independentExecution"] = acceptance
    mapping["moduleSuitesPassed"] = True
    mapping["productionImplementation"] = False
    # Existing external acceptance predicates are deliberately not promoted.
    write_json(output / "IMPLEMENTATION_MAP.json", mapping)
    (output / "execution-dossier.md").write_text(
        "# intuition.policy independent execution dossier\n\n"
        f"Source: `{args.source_commit}`\n\nTree: `{first['testedTree']}`\n\n"
        f"Workflow: `{context['runId']}`, attempt `{context['runAttempt']}`\n\n"
        f"Distinct jobs: `{first['jobId']}`, `{second['jobId']}`\n\n"
        "Both prescribed command sets passed on an unchanged identical source tree. "
        "See the two input artifacts for commands, exit codes and hash-bound logs. "
        "This is independent execution, not independent semantic evaluator acceptance, "
        "production target-host acceptance, or release authorization.\n", encoding="utf-8")
    seal(output)
    print(json.dumps(acceptance, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
