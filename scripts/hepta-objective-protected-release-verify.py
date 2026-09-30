#!/usr/bin/env python3
"""Run the protected objective release gate from trusted verifier bytes."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any

HEX40 = re.compile(r"[0-9a-f]{40}")


class ProtectedReleaseError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ProtectedReleaseError(message)


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ("git", *args),
        cwd=root,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_gate(trusted_root: Path) -> ModuleType:
    path = trusted_root / "scripts/hepta-objective-release-gate.py"
    require(path.is_file(), "trusted release-gate script is missing")
    spec = importlib.util.spec_from_file_location("trusted_objective_release_gate", path)
    require(spec is not None and spec.loader is not None, "cannot load trusted release gate")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify(
    trusted_root: Path,
    candidate_root: Path,
    candidate_sha: str,
    output: Path,
) -> dict[str, Any]:
    trusted_root = trusted_root.resolve()
    candidate_root = candidate_root.resolve()
    require(
        HEX40.fullmatch(candidate_sha) is not None,
        "candidate SHA must be full lowercase hexadecimal",
    )
    require(
        git(candidate_root, "rev-parse", "HEAD") == candidate_sha,
        "candidate checkout does not match the requested SHA",
    )
    candidate_tree = git(candidate_root, "rev-parse", "HEAD^{tree}")
    require(HEX40.fullmatch(candidate_tree) is not None, "candidate tree is invalid")
    require(not git(candidate_root, "status", "--porcelain"), "candidate checkout is dirty")
    trusted_sha = git(trusted_root, "rev-parse", "HEAD")
    trusted_tree = git(trusted_root, "rev-parse", "HEAD^{tree}")
    require(not git(trusted_root, "status", "--porcelain"), "trusted verifier checkout is dirty")

    gate = load_gate(trusted_root)
    trusted_policy_path = (
        trusted_root / "docs/modules/objective.compiler/RELEASE_POLICY.json"
    )
    candidate_policy_path = (
        candidate_root / "docs/modules/objective.compiler/RELEASE_POLICY.json"
    )
    state_path = candidate_root / "docs/modules/objective.compiler/CURRENT_STATE.json"
    receipts = candidate_root / "qualification/objective.compiler/receipts"

    trusted_policy = gate.load_json(trusted_policy_path)
    candidate_policy = gate.load_json(candidate_policy_path)
    require(
        gate.sha256_value(trusted_policy) == gate.sha256_value(candidate_policy),
        "candidate release policy differs from the protected trusted policy",
    )
    state = gate.load_json(state_path)
    readiness = gate.release_verify(
        state,
        trusted_policy,
        receipts,
        candidate_sha,
        candidate_tree,
    )
    envelope = {
        "schema": "hepta.objective-protected-release-readiness.v2",
        "schemaVersion": 2,
        "module": "objective.compiler",
        "candidateCommit": candidate_sha,
        "candidateTree": candidate_tree,
        "trustedVerifierCommit": trusted_sha,
        "trustedVerifierTree": trusted_tree,
        "trustedVerifierDigest": sha256_file(
            trusted_root / "scripts/hepta-objective-release-gate.py"
        ),
        "trustedPolicyDigest": gate.sha256_value(trusted_policy),
        "candidateCodeExecuted": False,
        "releaseReadiness": readiness,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return envelope


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trusted-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify(
            args.trusted_root,
            args.candidate_root,
            args.candidate_sha,
            args.output,
        )
    except (
        ProtectedReleaseError,
        OSError,
        subprocess.CalledProcessError,
        ValueError,
    ) as error:
        raise SystemExit(
            f"FAIL_HEPTA_OBJECTIVE_PROTECTED_RELEASE: {error}"
        ) from error
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
