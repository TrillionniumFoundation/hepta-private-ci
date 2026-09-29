#!/usr/bin/env python3
"""Freeze workflow, registry and convergence-policy proliferation."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tomllib
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = "docs/modules/registry.toml"
_REQUIRED_DISPOSITIONS = {"absorb", "supersede", "reference", "reject"}
_REQUIRED_ROOT_MODULE_FILES = {
    "docs/modules/CI_MATRIX.json",
    "docs/modules/COMPILE_GRAPH.json",
    "docs/modules/registry.toml",
}
_REQUIRED_LOCAL_MACHINE_FILES = {"module.toml"}


def load_policy(root: Path = ROOT) -> dict[str, Any]:
    path = root / POLICY_PATH
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"invalid convergence policy {path}: {error}") from error

    convergence = document.get("convergence")
    surface = document.get("repositorySurface")
    if not isinstance(convergence, dict) or not isinstance(surface, dict):
        raise ValueError(
            "registry.toml must define [convergence] and [repositorySurface]"
        )
    if convergence.get("maximumActiveConvergencePrsPerCapability") != 1:
        raise ValueError("exactly one active convergence PR per capability is required")
    if convergence.get("supersededDispositionRequired") is not True:
        raise ValueError("superseded PR disposition must remain mandatory")
    dispositions = convergence.get("allowedDispositions")
    if (
        not isinstance(dispositions, list)
        or set(dispositions) != _REQUIRED_DISPOSITIONS
    ):
        raise ValueError(
            "convergence dispositions must be absorb/supersede/reference/reject"
        )
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
    minute_keys = (
        "ordinaryFeedbackTargetMinutes",
        "ordinaryWorkflowTimeoutMinutes",
        "statefulWorkflowTimeoutMinutes",
        "architectureDeepTimeoutMinutes",
    )
    expected_minutes = {key: convergence.get(key) for key in minute_keys}
    values = list(expected_minutes.values())
    if any(type(value) is not int or not 1 <= value <= 360 for value in values):
        raise ValueError(
            "CI cost budgets must be positive whole minutes within hosted job bounds"
        )
    if values != sorted(values):
        raise ValueError("CI feedback target and tier budgets must be ordered")
    if convergence.get("selfIterationDraftOnly") is not True:
        raise ValueError("self-iteration must remain draft-only")
    if surface.get("newPullRequestWorkflowFilesAllowed") is not False:
        raise ValueError("new pull-request workflow files must remain frozen")

    allowed_root = surface.get("allowedRootModuleFiles")
    allowed_local = surface.get("allowedModuleLocalMachineFiles")
    if (
        not isinstance(allowed_root, list)
        or any(not isinstance(value, str) or not value for value in allowed_root)
        or set(allowed_root) != _REQUIRED_ROOT_MODULE_FILES
        or len(allowed_root) != len(_REQUIRED_ROOT_MODULE_FILES)
    ):
        raise ValueError("allowedRootModuleFiles widened or drifted")
    if (
        not isinstance(allowed_local, list)
        or set(allowed_local) != _REQUIRED_LOCAL_MACHINE_FILES
        or len(allowed_local) != len(_REQUIRED_LOCAL_MACHINE_FILES)
    ):
        raise ValueError(
            "module.toml must remain the only module-local machine manifest"
        )

    return {
        "maximumActiveConvergencePrsPerCapability": 1,
        "allowedDispositions": sorted(_REQUIRED_DISPOSITIONS),
        **expected_minutes,
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


def is_contract_schema(text: str) -> bool:
    """Recognize JSON Schema documents, not a parallel module/status registry.

    The protocol owner still validates its schema and actual wire instances.
    This classification neither grants authority nor claims implementation.
    """

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate schema key")
            result[key] = value
        return result

    try:
        value = json.loads(text, object_pairs_hook=pairs)
    except (ValueError, TypeError):
        return False
    if not isinstance(value, dict):
        return False
    dialect = value.get("$schema", "")
    if not isinstance(dialect, str) or not re.fullmatch(
        r"https?://json-schema\.org/(?:draft-0[467]/schema|draft/(?:2019-09|2020-12)/schema)#?",
        dialect,
    ):
        return False
    registry_fields = {
        "modules",
        "packages",
        "bindings",
        "authorityFlags",
        "production_implementation",
        "source_root_present",
        "planId",
        "convergence",
    }
    shapes = {
        "type",
        "$ref",
        "properties",
        "$defs",
        "definitions",
        "allOf",
        "anyOf",
        "oneOf",
    }
    return not (set(value) & registry_fields) and bool(set(value) & shapes)


def forbidden_additions(
    paths: Iterable[str], policy: dict[str, Any] | None = None, *, root: Path = ROOT
) -> list[str]:
    policy = load_policy(root) if policy is None else policy
    forbidden = []
    for value in paths:
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or str(path) != value
            or ".." in path.parts
            or "\\" in value
            or "\x00" in value
        ):
            raise ValueError("invalid repository path")
        target = root / path
        if not target.resolve().is_relative_to(root.resolve()) or target.is_symlink():
            forbidden.append(value)
            continue
        if value.startswith(".github/workflows/"):
            try:
                from scripts.hepta_workflow_commands import validate_manual_workflow
            except ModuleNotFoundError as error:
                if error.name != "scripts":
                    raise
                from hepta_workflow_commands import validate_manual_workflow
            try:
                if path.suffix not in {".yml", ".yaml"}:
                    raise ValueError("workflow extension")
                validate_manual_workflow(
                    target.read_text(), policy["architectureDeepTimeoutMinutes"]
                )
            except (ValueError, OSError):
                forbidden.append(value)
        elif value.startswith("docs/modules/"):
            if value in policy["allowedRootModuleFiles"] or path.suffix == ".md":
                continue
            if len(path.parts) == 4 and path.name == "module.toml":
                continue
            try:
                schema = path.suffix == ".json" and is_contract_schema(
                    target.read_text()
                )
            except OSError:
                schema = False
            if not schema:
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
            "new automatic/privileged workflow or duplicate registry requires integration review; use the shared "
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
