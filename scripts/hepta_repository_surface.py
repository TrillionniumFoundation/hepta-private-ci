#!/usr/bin/env python3
"""Freeze workflow, registry and convergence-policy proliferation."""
from __future__ import annotations

import argparse
import json
import subprocess
import tomllib
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = "docs/modules/registry.toml"
_REQUIRED_DISPOSITIONS = {"absorb", "supersede", "reference", "reject"}


def load_policy(root: Path = ROOT) -> dict[str, Any]:
    path = root / POLICY_PATH
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"invalid convergence policy {path}: {error}") from error

    convergence = document.get("convergence")
    surface = document.get("repositorySurface")
    if not isinstance(convergence, dict) or not isinstance(surface, dict):
        raise ValueError("registry.toml must define [convergence] and [repositorySurface]")
    if convergence.get("maximumActiveConvergencePrsPerCapability") != 1:
        raise ValueError("exactly one active convergence PR per capability is required")
    if convergence.get("supersededDispositionRequired") is not True:
        raise ValueError("superseded PR disposition must remain mandatory")
    dispositions = convergence.get("allowedDispositions")
    if not isinstance(dispositions, list) or set(dispositions) != _REQUIRED_DISPOSITIONS:
        raise ValueError("convergence dispositions must be absorb/supersede/reference/reject")
    required_false = (
        "ordinaryExactSourceMapRequired",
        "ordinaryProseMetricsRequired",
        "ordinaryMergeCandidateRequired",
        "selfIterationMergeAllowed",
        "selfIterationActivationAllowed",
        "selfIterationPromotionAllowed",
        "selfIterationReleaseAllowed",
    )
    if any(convergence.get(key) is not False for key in required_false):
        raise ValueError("ordinary-development or self-iteration authority widened")
    if convergence.get("highRiskMergeCandidateRequired") is not True:
        raise ValueError("high-risk merge-candidate qualification must remain required")
    if convergence.get("selfIterationDraftOnly") is not True:
        raise ValueError("self-iteration must remain draft-only")
    if surface.get("newPullRequestWorkflowFilesAllowed") is not False:
        raise ValueError("new pull-request workflow files must remain frozen")

    allowed_root = surface.get("allowedRootModuleFiles")
    allowed_local = surface.get("allowedModuleLocalMachineFiles")
    if (
        not isinstance(allowed_root, list)
        or not allowed_root
        or any(not isinstance(value, str) or not value for value in allowed_root)
        or len(set(allowed_root)) != len(allowed_root)
    ):
        raise ValueError("invalid allowedRootModuleFiles")
    if (
        not isinstance(allowed_local, list)
        or allowed_local != ["module.toml"]
    ):
        raise ValueError("module.toml must remain the only module-local machine manifest")
    if POLICY_PATH not in allowed_root:
        raise ValueError("the canonical policy must allow its own existing path")

    return {
        "maximumActiveConvergencePrsPerCapability": 1,
        "allowedDispositions": sorted(_REQUIRED_DISPOSITIONS),
        "newPullRequestWorkflowFilesAllowed": False,
        "allowedRootModuleFiles": set(allowed_root),
        "allowedModuleLocalMachineFiles": set(allowed_local),
    }


def added_paths(base: str, head: str, root: Path = ROOT) -> list[str]:
    return subprocess.check_output(
        [
            "git",
            "--no-replace-objects",
            "diff",
            "--diff-filter=A",
            "--name-only",
            "--no-renames",
            base,
            head,
            "--",
            ".github/workflows",
            "docs/modules",
        ],
        cwd=root,
        text=True,
    ).splitlines()


def forbidden_additions(
    paths: Iterable[str], policy: dict[str, Any] | None = None
) -> list[str]:
    policy = load_policy() if policy is None else policy
    allowed_root = policy["allowedRootModuleFiles"]
    allowed_local = policy["allowedModuleLocalMachineFiles"]
    forbid_workflows = not policy["newPullRequestWorkflowFilesAllowed"]

    forbidden: list[str] = []
    for value in paths:
        path = PurePosixPath(value)
        if value.startswith(".github/workflows/"):
            if forbid_workflows:
                forbidden.append(value)
        elif path.parent == PurePosixPath("docs/modules"):
            if value not in allowed_root:
                forbidden.append(value)
        elif (
            len(path.parts) == 4
            and path.parts[:2] == ("docs", "modules")
            and path.name.endswith((".json", ".toml"))
            and path.name not in allowed_local
        ):
            forbidden.append(value)
    return sorted(forbidden)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    args = parser.parse_args()
    policy = load_policy()
    added = added_paths(args.base, args.head)
    forbidden = forbidden_additions(added, policy)
    if forbidden:
        raise SystemExit(
            "new workflow or registry infrastructure is frozen; use the shared "
            "CI tiers and one module.toml: " + ", ".join(forbidden)
        )
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_REPOSITORY_SURFACE",
                "policy": POLICY_PATH,
                "maximumActiveConvergencePrsPerCapability": policy[
                    "maximumActiveConvergencePrsPerCapability"
                ],
                "allowedDispositions": policy["allowedDispositions"],
                "added": len(added),
                "forbidden": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
