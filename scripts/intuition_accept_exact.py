#!/usr/bin/env python3
"""Verify source, independent and synthetic-merge evidence from this CI run.

Hashes bind evidence to Git objects, command logs and retained release binaries.
They are not signatures from an independent evaluator or deployment authority.
The merge tree is recomputed without checking out or changing candidate source.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from intuition_qualify_exact import (
    COMMANDS, INDEPENDENT_COMMANDS, SCHEMA, external_directory,
    git, nonzero_tests, seal, sha256, write_json,
)


def strict_json(path: Path) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    if path.is_symlink() or not path.is_file():
        raise ValueError("invalid JSON artifact")
    result = json.loads(path.read_text(), object_pairs_hook=pairs)
    if not isinstance(result, dict):
        raise ValueError("JSON artifact must be an object")
    return result


def verify_bundle(path: Path, mode: str, source: str, context: dict[str, str],
                  lane: str = "source-head", base: str | None = None) -> dict:
    if path.is_symlink():
        raise ValueError("symlink artifact bundle")
    manifest = strict_json(path / "artifact-manifest.json")
    if manifest.get("schema") != "hepta.intuition.artifacts.v1":
        raise ValueError("unsupported artifact manifest")
    hashes = manifest.get("sha256", {})
    required = {"command-record.json", "toolchain.txt", "IMPLEMENTATION_MAP.json", "execution-dossier.md"}
    if not isinstance(hashes, dict) or not required <= set(hashes):
        raise ValueError("missing mandatory evidence artifacts")
    for name, digest in hashes.items():
        member = path / name
        if Path(name).name != name or member.is_symlink() or not member.is_file():
            raise ValueError("invalid artifact path")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) or sha256(member) != digest:
            raise ValueError(f"artifact digest mismatch: {name}")
    record = strict_json(path / "command-record.json")
    if record.get("schema") != SCHEMA or record.get("mode") != mode:
        raise ValueError("evidence schema or mode mismatch")
    if not re.fullmatch(r"[0-9a-f]{40}", source) or record.get("sourceSha") != source or record.get("lane") != lane:
        raise ValueError("evidence source or lane mismatch")
    if lane == "source-head":
        if record.get("testedSha") != source:
            raise ValueError("evidence is not for the exact source head")
    elif lane == "synthetic-merge":
        if not base or record.get("baseSha") != base:
            raise ValueError("merge base mismatch")
    else:
        raise ValueError("unknown evidence lane")
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
        if type(row.get("exitCode")) is not int or row["exitCode"] != 0 or row.get("status") != "passed":
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


def verify_ci_identity(path: Path, record: dict, context: dict[str, str]) -> None:
    """Verify the actual Git object, not just two copies of a SHA string."""
    raw = base64.b64decode(record.get("testedCommitObjectBase64", ""), validate=True)
    if not raw or len(raw) > 4 * 1024 * 1024:
        raise ValueError("missing or oversized Git commit object")
    actual = hashlib.sha1(b"commit " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if actual != record["testedSha"]:
        raise ValueError("Git commit object does not match tested SHA")
    headers = raw.split(b"\n\n", 1)[0].decode("utf-8").splitlines()
    trees = [line[5:] for line in headers if line.startswith("tree ")]
    parents = [line[7:] for line in headers if line.startswith("parent ")]
    if trees != [record["testedTree"]] or parents != record.get("testedParents"):
        raise ValueError("Git commit tree or parent binding mismatch")
    if not context.get("workflowSha") or record.get("workflowSha") != context["workflowSha"]:
        raise ValueError("workflow SHA mismatch")
    if not record.get("workflowRef") or any(not record.get("runner", {}).get(k) for k in ("RUNNER_OS", "RUNNER_ARCH", "ImageOS", "ImageVersion")):
        raise ValueError("runner image or workflow identity missing")
    from intuition_ci_exact import BUILD_ENV
    if record.get("buildEnvironment") != BUILD_ENV:
        raise ValueError("unqualified CI build environment")
    hashes = strict_json(path / "artifact-manifest.json")["sha256"]
    for name in ("CURRENT_STATE.json", "TECHNICAL_STATUS.md", "ci-resources.json"):
        if name not in hashes:
            raise ValueError(f"missing generated evidence: {name}")
    state = strict_json(path / "CURRENT_STATE.json")
    if (state.get("testedCommit") != record["testedSha"] or state.get("testedTree") != record["testedTree"]
            or state.get("executionStatus") != "passed"):
        raise ValueError("generated state disagrees with execution")
    for row in record["commands"]:
        if row["name"] == "release-binaries":
            for binary in row["binaries"]:
                name = binary.get("artifact")
                if not name or hashes.get(name) != binary.get("sha256"):
                    raise ValueError("release binary not retained in the verified bundle")


def verify_merge(path: Path, source: str, base: str, expected_tree: str, context: dict[str, str]) -> dict:
    record = verify_bundle(path, "qualification", source, context, "synthetic-merge", base)
    verify_ci_identity(path, record, context)
    if len(record["testedParents"]) != 2 or set(record["testedParents"]) != {source, base}:
        raise ValueError("synthetic merge must have exactly the source and base parents")
    if record["testedTree"] != expected_tree:
        raise ValueError("synthetic merge tree differs from independent Git recomputation")
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--qualification", required=True, type=Path)
    parser.add_argument("--independent", required=True, type=Path)
    parser.add_argument("--merge", type=Path)
    parser.add_argument("--base-commit")
    parser.add_argument("--require-merge", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    context = {"runId": os.environ.get("GITHUB_RUN_ID", ""),
               "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT", ""),
               "repository": os.environ.get("GITHUB_REPOSITORY", ""),
               "workflowSha": os.environ.get("GITHUB_WORKFLOW_SHA", "")}
    output = None
    try:
        output = external_directory(args.output)
        if bool(args.merge) != bool(args.base_commit) or (args.require_merge and not args.merge):
            raise ValueError("this acceptance requires both merge evidence and the pinned base SHA")
        first, second = verify_pair(args.qualification, args.independent, args.source_commit, context)
        verify_ci_identity(args.qualification, first, context)
        verify_ci_identity(args.independent, second, context)
        merged = None
        if args.merge:
            # No checkout, index update, source edit, commit, or push.
            expected_tree = git("merge-tree", "--write-tree", args.base_commit, args.source_commit).splitlines()[0]
            merged = verify_merge(args.merge, args.source_commit, args.base_commit, expected_tree, context)
    except (ValueError, OSError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        if output is not None:
            write_json(output / "rejected.json", {"status": "failed", "reason": str(error), **context,
                                                 "sourceSha": args.source_commit, "promotion": "not_authorized"})
            seal(output)
        print(f"acceptance rejected: {error}", file=sys.stderr)
        return 1
    acceptance = {
        "schema": "hepta.intuition.independent-execution.v2", "status": "passed",
        "sourceSha": args.source_commit, "testedTree": first["testedTree"],
        **context, "jobs": [first["jobId"], second["jobId"]],
        "qualificationReportSha256": sha256(args.qualification / "command-record.json"),
        "independentReportSha256": sha256(args.independent / "command-record.json"),
        "qualificationManifestSha256": sha256(args.qualification / "artifact-manifest.json"),
        "independentManifestSha256": sha256(args.independent / "artifact-manifest.json"),
        "independentExecutionVerified": True, "mergeTreeVerified": merged is not None,
        "merge": None if merged is None else {
            "baseSha": args.base_commit, "commit": merged["testedSha"], "tree": merged["testedTree"],
            "reportSha256": sha256(args.merge / "command-record.json"),
            "manifestSha256": sha256(args.merge / "artifact-manifest.json"),
        },
        "semanticEvaluatorAcceptance": "not_established",
        "targetHostAcceptance": "not_established", "promotion": "not_authorized",
    }
    write_json(output / "independent-execution.json", acceptance)
    mapping = strict_json(args.qualification / "IMPLEMENTATION_MAP.json")
    mapping["independentExecution"] = acceptance
    mapping["moduleSuitesPassed"] = True
    mapping["productionImplementation"] = False
    write_json(output / "IMPLEMENTATION_MAP.json", mapping)
    state = {**acceptance, "is_production_implemented": False, "happy_path_verified": False,
             "edge_failures_verified": False, "has_independent_acceptance_proof": False}
    write_json(output / "CURRENT_STATE.json", state)
    text = ("# intuition.policy verified execution dossier\n\n"
            f"Source: `{args.source_commit}`\n\nTree: `{first['testedTree']}`\n\n"
            f"Workflow: `{context['runId']}`, attempt `{context['runAttempt']}`\n\n"
            f"Distinct execution jobs: `{first['jobId']}`, `{second['jobId']}`\n\n"
            f"Synthetic merge independently verified: `{merged is not None}`.\n\n"
            "CURRENT_STATE.json is the canonical state for these projections. "
            "Input manifests bind command sets, exit codes, logs, commit objects, "
            "runner identities and actual release binaries. Independent execution "
            "is not semantic evaluator acceptance, target-host acceptance or release authorization.\n")
    (output / "execution-dossier.md").write_text(text, encoding="utf-8")
    (output / "TECHNICAL_STATUS.md").write_text(text, encoding="utf-8")
    seal(output)
    print(json.dumps(acceptance, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
