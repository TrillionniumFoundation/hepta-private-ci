#!/usr/bin/env python3
"""Validate repository extensions without duplicating authority or CI cost."""

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


def _unique_strings(value: object, label: str, *, maximum: int = 128) -> list[str]:
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= maximum
        or any(
            not isinstance(item, str) or not item or item.strip() != item
            for item in value
        )
        or len(value) != len(set(value))
    ):
        raise ValueError(f"{label} must be a bounded unique string list")
    return value


def _repository_path(value: str, label: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or str(path) != value
        or ".." in path.parts
        or "\\" in value
        or "\x00" in value
    ):
        raise ValueError(f"invalid {label}: {value!r}")
    return path


def _document_schema(path: Path) -> str:
    try:
        if path.suffix == ".json":

            def pairs(items):
                result = {}
                for key, value in items:
                    if key in result:
                        raise ValueError("duplicate machine document key")
                    result[key] = value
                return result

            document = json.loads(
                path.read_text(encoding="utf-8"), object_pairs_hook=pairs
            )
        elif path.suffix == ".toml":
            document = tomllib.loads(path.read_text(encoding="utf-8"))
        else:
            raise ValueError("canonical machine documents must be JSON or TOML")
    except (OSError, ValueError, tomllib.TOMLDecodeError) as error:
        raise ValueError(
            f"invalid canonical machine document {path}: {error}"
        ) from error
    schema = document.get("schema") if isinstance(document, dict) else None
    if not isinstance(schema, str) or not schema or len(schema) > 256:
        raise ValueError(f"canonical machine document lacks a bounded schema: {path}")
    return schema


def _canonical_root_files(value: object, root: Path) -> set[str]:
    values = _unique_strings(value, "canonicalRootMachineFiles", maximum=64)
    if POLICY_PATH not in values:
        raise ValueError("canonicalRootMachineFiles must retain its policy owner")
    schemas = set()
    for item in values:
        relative = _repository_path(item, "canonical root machine path")
        if relative.parent != PurePosixPath("docs/modules"):
            raise ValueError("canonical root machine files must stay in docs/modules")
        target = root / relative
        if (
            target.is_symlink()
            or not target.is_file()
            or not target.resolve().is_relative_to(root.resolve())
        ):
            raise ValueError(
                f"canonical root machine file is missing or unsafe: {item}"
            )
        schema = _document_schema(target)
        if schema in schemas:
            raise ValueError(f"duplicate canonical machine schema: {schema}")
        schemas.add(schema)
    return set(values)


def _canonical_local_files(value: object) -> set[str]:
    values = _unique_strings(value, "canonicalModuleLocalMachineFiles", maximum=32)
    if "module.toml" not in values:
        raise ValueError("canonicalModuleLocalMachineFiles must retain module.toml")
    for item in values:
        path = _repository_path(item, "module-local machine filename")
        if len(path.parts) != 1 or path.suffix not in {".json", ".toml"}:
            raise ValueError("module-local machine entries must be JSON/TOML filenames")
    return set(values)


def load_policy(root: Path = ROOT) -> dict[str, Any]:
    path = root / POLICY_PATH
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"invalid convergence policy {path}: {error}") from error
    if document.get("schema") != "hepta.module-manifest-registry.v1":
        raise ValueError("unsupported module manifest registry policy")

    convergence = document.get("convergence")
    surface = document.get("repositorySurface")
    if not isinstance(convergence, dict) or not isinstance(surface, dict):
        raise ValueError(
            "registry.toml must define [convergence] and [repositorySurface]"
        )
    maximum_prs = convergence.get("maximumActiveConvergencePrsPerCapability")
    if type(maximum_prs) is not int or not 1 <= maximum_prs <= 16:
        raise ValueError(
            "active convergence PR budget must be a bounded positive integer"
        )
    if convergence.get("supersededDispositionRequired") is not True:
        raise ValueError("superseded PR disposition must remain mandatory")
    dispositions = _unique_strings(
        convergence.get("allowedDispositions"), "allowedDispositions", maximum=16
    )
    if any(
        re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", value) is None for value in dispositions
    ):
        raise ValueError("convergence dispositions must be bounded identifiers")
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
    budgets = {key: convergence.get(key) for key in minute_keys}
    values = list(budgets.values())
    if any(type(value) is not int or not 1 <= value <= 360 for value in values):
        raise ValueError(
            "CI cost budgets must be positive whole minutes within hosted job bounds"
        )
    if values != sorted(values):
        raise ValueError("CI feedback target and tier budgets must be ordered")
    if convergence.get("selfIterationDraftOnly") is not True:
        raise ValueError("self-iteration must remain draft-only")
    if surface.get("newAutomaticOrPrivilegedWorkflowFilesAllowed") is not False:
        raise ValueError(
            "new automatic or privileged workflow files must require integration review"
        )

    allowed_root = _canonical_root_files(surface.get("canonicalRootMachineFiles"), root)
    allowed_local = _canonical_local_files(
        surface.get("canonicalModuleLocalMachineFiles")
    )
    return {
        "maximumActiveConvergencePrsPerCapability": maximum_prs,
        "allowedDispositions": dispositions,
        **budgets,
        "newAutomaticOrPrivilegedWorkflowFilesAllowed": False,
        "canonicalRootMachineFiles": allowed_root,
        "canonicalModuleLocalMachineFiles": allowed_local,
    }


def extension_paths(base: str, head: str, root: Path = ROOT) -> list[str]:
    """Inspect new extensions and continued use of the same narrow admission path.

    Existing integration-owned workflows/registries keep their normal review
    path. Previously admitted manual diagnostics and schemas cannot gain new
    privileges merely by changing an existing file on a subsequent commit.
    """
    raw = subprocess.check_output(
        [
            "git",
            "--no-replace-objects",
            "diff",
            "--diff-filter=ACMT",
            "--name-status",
            "--no-renames",
            "-z",
            base,
            head,
            "--",
            ".github/workflows",
            "docs/modules",
        ],
        cwd=root,
    ).split(b"\0")
    if raw[-1:] == [b""]:
        raw.pop()
    if len(raw) % 2:
        raise ValueError("invalid changed surface inventory")
    selected = []
    for status, path_bytes in zip(raw[::2], raw[1::2]):
        path = path_bytes.decode("utf-8")
        if status in {b"A", b"T"}:
            selected.append(path)
            continue
        previous = subprocess.check_output(
            ["git", "--no-replace-objects", "show", f"{base}:{path}"],
            cwd=root,
        ).decode("utf-8")
        if path.startswith(".github/workflows/"):
            try:
                from scripts.hepta_workflow_commands import validate_manual_workflow
            except ModuleNotFoundError as error:
                if error.name != "scripts":
                    raise
                from hepta_workflow_commands import validate_manual_workflow
            try:
                # Historical recognition must not depend on a newly lowered tier budget.
                validate_manual_workflow(previous, 360)
            except ValueError:
                continue
            selected.append(path)
        elif path.endswith(".json") and is_contract_schema(previous):
            selected.append(path)
    return sorted(selected)


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
            if value in policy["canonicalRootMachineFiles"] or path.suffix == ".md":
                continue
            if (
                len(path.parts) == 4
                and path.name in policy["canonicalModuleLocalMachineFiles"]
            ):
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
    added = extension_paths(args.base, args.head)
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
                "checkedExtensions": len(added),
                "forbidden": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
