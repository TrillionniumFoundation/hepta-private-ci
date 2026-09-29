#!/usr/bin/env python3
"""Verify all six fixed-candidate receipts and log bytes; never promote product state.

This checks evidence consistency, not independent trust in candidate-owned code.
It writes only the requested report outside the source worktree. Resolving a
synthetic merge may add Git objects, but never checks out or edits source files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from command_process import closed_capture
from evidence_inventory import require_files, verify_inventory
from run_qualification import CHECK_PLAN_VERSION, GROUPS, SHA, command_plan, git, resolve_candidate

KINDS = ("exact-head", "synthetic-merge")
SHA256 = re.compile(r"[0-9a-f]{64}")
MAX_RECEIPT_BYTES = 2 * 1024 * 1024


class EvidenceError(ValueError):
    """Missing, inconsistent or incomplete qualification evidence."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def no_nonfinite_number(value: str) -> None:
    raise EvidenceError(f"nonfinite JSON number: {value}")


def regular_file(directory: Path, name: str) -> Path:
    require(Path(name).name == name and name not in ("", ".", ".."), "unsafe evidence filename")
    path = directory / name
    require(not path.is_symlink() and path.is_file(), f"missing or symlinked evidence: {name}")
    return path


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_receipt(directory: Path) -> tuple[dict, str]:
    path = regular_file(directory, "receipt.json")
    require(path.stat().st_size <= MAX_RECEIPT_BYTES, "oversize receipt")
    data = path.read_bytes()
    sidecar = regular_file(directory, "receipt.sha256")
    require(sidecar.stat().st_size <= 128, "oversize receipt digest")
    expected = sidecar.read_text(encoding="ascii").strip()
    digest = hashlib.sha256(data).hexdigest()
    require(SHA256.fullmatch(expected) is not None and expected == digest, "receipt digest mismatch")
    receipt = json.loads(data, object_pairs_hook=no_duplicate_keys, parse_constant=no_nonfinite_number)
    require(isinstance(receipt, dict), "receipt must be a JSON object")
    return receipt, digest


def absolute_recorded_path(value: object, field: str) -> Path:
    require(isinstance(value, str) and bool(value), f"missing {field}")
    path = Path(value)
    require(path.is_absolute() and ".." not in path.parts, f"invalid {field}")
    return path


def verify_receipt(directory: Path, group: str, identity: dict, execution: dict) -> dict:
    receipt, digest = load_receipt(directory)
    require(receipt.get("schema") == "hepta.cognitive-types.readonly-execution.v1", "wrong receipt schema")
    require(type(receipt.get("check_plan_version")) is int
            and receipt["check_plan_version"] == CHECK_PLAN_VERSION, "wrong check plan version")
    require(receipt.get("group") == group, "wrong check group")
    for key, value in {**identity, **execution}.items():
        require(receipt.get(key) == value and type(receipt.get(key)) is type(value), f"identity mismatch: {key}")
    require(receipt.get("qualification_passed") is True, "qualification did not pass")
    for key in ("product_acceptance", "activation", "release"):
        require(receipt.get(key) is False, f"unexpected authority claim: {key}")
    require(receipt.get("error") is None, "receipt has a preparation error")
    require(receipt.get("evidence_error") is None, "receipt has an evidence sealing error")
    image = receipt.get("runner_image")
    require(isinstance(image, dict) and all(isinstance(image.get(key), str) and image[key]
            for key in ("os", "version", "platform")), "missing runner image identity")
    root = absolute_recorded_path(receipt.get("source_worktree"), "source_worktree")
    output = absolute_recorded_path(receipt.get("evidence_directory"), "evidence_directory")
    require(output != root and root not in output.parents and output not in root.parents, "evidence was written inside source")
    require(receipt.get("cargo_target_directory") == str(output.parent / "cognitive-types-cargo-target"),
            "cargo target directory identity mismatch")
    try:
        inventory = verify_inventory(directory, receipt.get("evidence_files"))
        required = [name + ".log" for name, _, _ in command_plan(root, group, output)]
        if group == "native":
            required += ["quality-receipt.json", "mutations/mutation-receipt.json"]
        require_files(inventory, required)
    except (OSError, ValueError) as error:
        raise EvidenceError(str(error)) from error
    python = absolute_recorded_path(receipt.get("python_executable"), "python_executable")
    plan = command_plan(root, group, output)
    checks = receipt.get("checks")
    require(isinstance(checks, list) and all(isinstance(check, dict) for check in checks), "invalid check outcomes")
    expected_names = [name for name, _, _ in plan] + ["clean-tree"]
    require([check.get("name") for check in checks] == expected_names,
            "missing, duplicate, reordered or unexpected command outcomes")
    for check in checks:
        require(check.get("status") == "passed" and type(check.get("exit_code")) is int
                and check["exit_code"] == 0 and check.get("error") is None,
                f"nonpassing outcome: {check.get('name')}")
    log_digests = {}
    for check, (name, argv, cwd) in zip(checks, plan, strict=False):
        # Interpreter locations can differ between runners. Every Python
        # invocation must still use the one explicitly recorded interpreter;
        # script, arguments, package set and cwd are compared exactly.
        if argv[0] == sys.executable:
            argv = [str(python), *argv[1:]]
        require(check.get("argv") == argv and check.get("cwd") == str(cwd), f"command substitution: {name}")
        started, finished = check.get("started_unix_ns"), check.get("finished_unix_ns")
        require(type(started) is int and type(finished) is int and 0 < started <= finished,
                f"invalid command times: {name}")
        require(check.get("log") == name + ".log", f"wrong log identity: {name}")
        require(closed_capture(check), f"incomplete process or log capture: {name}")
        log = regular_file(directory, name + ".log")
        require(check["log_bytes"] == log.stat().st_size, f"log byte count mismatch: {name}")
        actual = file_digest(log)
        require(check.get("log_sha256") == actual, f"log digest mismatch: {name}")
        log_digests[name] = actual
    require(checks[-1].get("porcelain") == "", "candidate worktree was not clean")
    return {"group": group, "candidate_kind": identity["candidate_kind"],
            "candidate_commit": identity["candidate_commit"], "candidate_tree": identity["candidate_tree"],
            "artifact": directory.name, "receipt_sha256": digest, "logs": log_digests,
            "runner_image": image, "evidence_files": inventory}


def verify_matrix(root: Path, evidence: Path, source: str, base: str, execution: dict) -> dict:
    require(SHA.fullmatch(source) is not None and SHA.fullmatch(base) is not None, "full source/base SHAs required")
    require(SHA.fullmatch(execution.get("workflow_sha", "")) is not None, "full workflow SHA required")
    require(isinstance(execution.get("workflow_ref"), str) and bool(execution["workflow_ref"]), "workflow ref required")
    for key in ("run_id", "run_attempt"):
        require(isinstance(execution.get(key), str) and re.fullmatch(r"[1-9][0-9]*", execution[key]) is not None,
                f"invalid {key}")
    require(not evidence.is_symlink() and evidence.is_dir(), "missing evidence directory")
    before = (git(root, "rev-parse", "HEAD"), git(root, "status", "--porcelain", "--untracked-files=all"))
    require(before == (source, ""), "verifier requires the clean exact source checkout")
    identities = {kind: resolve_candidate(root, source, base, kind) for kind in KINDS}
    expected = {f"cognitive-types-{group}-{kind}-{source}-{execution['run_attempt']}": (group, kind)
                for group in GROUPS for kind in KINDS}
    require({item.name for item in evidence.iterdir()} == set(expected), "incomplete or duplicate six-artifact matrix")
    verified = []
    for name, (group, kind) in expected.items():
        directory = evidence / name
        require(not directory.is_symlink() and directory.is_dir(), "invalid artifact directory")
        verified.append(verify_receipt(directory, group, identities[kind], execution))
    after = (git(root, "rev-parse", "HEAD"), git(root, "status", "--porcelain", "--untracked-files=all"))
    require(after == before, "verifier changed the source worktree")
    return {"schema": "hepta.cognitive-types.verified-matrix.v1", "qualification_passed": True,
            "source_commit": source, "base_commit": base, "execution": execution,
            "identities": identities, "receipts": verified, "product_acceptance": False,
            "activation": False, "release": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    if output == root or root in output.parents:
        parser.error("verification report must be outside the source worktree")
    evidence = args.evidence.resolve()
    if output == evidence or evidence in output.parents:
        parser.error("verification report must not overwrite input evidence")
    execution = {key: os.environ.get(env, "") for key, env in (
        ("workflow_sha", "GITHUB_WORKFLOW_SHA"), ("workflow_ref", "GITHUB_WORKFLOW_REF"),
        ("run_id", "GITHUB_RUN_ID"), ("run_attempt", "GITHUB_RUN_ATTEMPT"))}
    try:
        report = verify_matrix(root, args.evidence, args.source, args.base, execution)
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as error:
        report = {"schema": "hepta.cognitive-types.verified-matrix.v1", "qualification_passed": False,
                  "source_commit": args.source, "base_commit": args.base, "execution": execution,
                  "error": f"{type(error).__name__}: {error}", "product_acceptance": False,
                  "activation": False, "release": False}
        print(report["error"], file=sys.stderr)
    output.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
    output.write_bytes(data)
    output.with_suffix(".sha256").write_text(hashlib.sha256(data).hexdigest() + "\n")
    return 0 if report["qualification_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
