#!/usr/bin/env python3
"""Run the objective release verifier from a trusted control checkout.

The candidate checkout is data. This wrapper imports the release-gate
implementation from the control checkout, redirects its repository root to the
separate candidate workspace, and never executes a Python file from that
candidate workspace.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any

CONTROL_ROOT = Path(__file__).resolve().parents[1]
HEX40 = re.compile(r"[0-9a-f]{40}")


class TrustedReleaseError(ValueError):
    pass


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ("git", *args),
        cwd=root,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
        },
    )
    return result.stdout.strip()


def exact_commit(value: str, label: str) -> str:
    if HEX40.fullmatch(value) is None:
        raise TrustedReleaseError(f"{label} must be an exact lowercase commit id")
    return value


def checked_workspace(path: Path, label: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise TrustedReleaseError(f"cannot resolve {label}: {error}") from error
    if resolved == CONTROL_ROOT.resolve():
        raise TrustedReleaseError("candidate and trusted-control workspaces must differ")
    if git(resolved, "status", "--porcelain"):
        raise TrustedReleaseError(f"{label} checkout must be clean")
    return resolved


def load_trusted_gate() -> ModuleType:
    source = CONTROL_ROOT / "scripts/hepta-objective-release-gate.py"
    spec = importlib.util.spec_from_file_location("trusted_objective_release_gate", source)
    if spec is None or spec.loader is None:
        raise TrustedReleaseError("cannot load trusted release gate")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_release(
    candidate_root: Path,
    candidate_commit: str,
    candidate_tree: str,
    receipts: Path,
    output: Path | None,
) -> dict[str, Any]:
    candidate_root = checked_workspace(candidate_root, "candidate")
    candidate_commit = exact_commit(candidate_commit, "candidate commit")
    candidate_tree = exact_commit(candidate_tree, "candidate tree")
    if git(candidate_root, "rev-parse", "HEAD") != candidate_commit:
        raise TrustedReleaseError("candidate checkout does not match expected commit")
    if git(candidate_root, "rev-parse", "HEAD^{tree}") != candidate_tree:
        raise TrustedReleaseError("candidate checkout does not match expected tree")

    control_commit = exact_commit(
        git(CONTROL_ROOT, "rev-parse", "HEAD"), "trusted-control commit"
    )
    control_tree = exact_commit(
        git(CONTROL_ROOT, "rev-parse", "HEAD^{tree}"), "trusted-control tree"
    )
    if git(CONTROL_ROOT, "status", "--porcelain"):
        raise TrustedReleaseError("trusted-control checkout must be clean")

    gate = load_trusted_gate()
    gate.ROOT = candidate_root
    gate.STATE_PATH = candidate_root / "docs/modules/objective.compiler/CURRENT_STATE.json"
    gate.POLICY_PATH = candidate_root / "docs/modules/objective.compiler/RELEASE_POLICY.json"

    state = gate.load_json(gate.STATE_PATH)
    policy = gate.load_json(gate.POLICY_PATH)
    receipt_dir = receipts if receipts.is_absolute() else candidate_root / receipts
    result = gate.release_verify(
        state, policy, receipt_dir, candidate_commit, candidate_tree
    )
    result["trustedControlCommit"] = control_commit
    result["trustedControlTree"] = control_tree
    result["candidateVerifierExecuted"] = False

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify-release",))
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--expected-tree", required=True)
    parser.add_argument(
        "--receipts",
        type=Path,
        default=Path("qualification/objective.compiler/receipts"),
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = verify_release(
            args.candidate_root,
            args.expected_sha,
            args.expected_tree,
            args.receipts,
            args.output,
        )
    except (TrustedReleaseError, subprocess.CalledProcessError, ValueError) as error:
        raise SystemExit(f"FAIL_TRUSTED_OBJECTIVE_RELEASE: {error}") from error
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
