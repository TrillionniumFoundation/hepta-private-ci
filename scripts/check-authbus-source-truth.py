#!/usr/bin/env python3
"""Enforce one commit-neutral and immutable AuthBus source truth.

Static repository files may describe contracts and source mappings. Candidate
SHAs, workflow attempts, bound projections, evidence receipts, and release
decisions are generated artifacts and must never be committed as an alternate
status authority. AuthBus qualification and authoring workflows are read-only:
a workflow may validate source, but it may not format, commit, push, or otherwise
rewrite the candidate it is qualifying.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "docs/modules/auth.authbus/IMPLEMENTATION_MAP.json"
READINESS = ROOT / "docs/modules/auth.authbus/READINESS_CONTRACT.json"
WORKFLOW_ROOT = ROOT / ".github/workflows"
GENERATED_NAME = re.compile(
    r"(?:^|/)(?:"
    r"implementation-map\.bound|current-implementation\.bound|"
    r"qualification-dossier\.bound|release-status\.bound|"
    r"readiness-manifest|source-head|exact-head-evidence|"
    r"target-host-qualification|performance-evidence|"
    r"production-acceptance\.verified"
    r")\.json$"
)
SHA_FIELD = re.compile(
    r"(?:^|_)(?:commit|candidate|head|base|tree|merge|final_merge|workflow)_?sha$",
    re.IGNORECASE,
)
SOURCE_MUTATION = re.compile(
    r"(?im)(?:^\s*contents:\s*write\s*(?:#.*)?$|"
    r"\bgit\s+(?:commit|push)\b|"
    r"^\s*persist-credentials:\s*true\s*(?:#.*)?$)"
)
FORBIDDEN_AUTHORING_WORKFLOWS = {
    ".github/workflows/authbus-bootstrap-api-authoring.yml",
    ".github/workflows/authbus-lockfile-authoring.yml",
    ".github/workflows/authbus-time-floor-authoring.yml",
}


def load(path: Path) -> dict[str, Any]:
    def unique(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in items:
            if key in value:
                raise ValueError(f"{path}: duplicate JSON key {key!r}")
            value[key] = item
        return value

    loaded = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    if not isinstance(loaded, dict):
        raise ValueError(f"{path}: expected object")
    return loaded


def tracked_files() -> list[str]:
    output = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode(
        "utf-8"
    )
    return [path for path in output.split("\0") if path]


def walk(value: Any, path: str = "$") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}"
            if SHA_FIELD.search(key) and item not in (None, "", False):
                errors.append(f"{child}: committed candidate identity is forbidden")
            if key in {
                "workflowRunId",
                "workflowRunAttempt",
                "attemptId",
                "runnerImage",
                "artifactHashes",
                "targetHostIdentity",
            } and item not in (None, "", False, [], {}):
                errors.append(f"{child}: runtime evidence belongs in a bound artifact")
            errors.extend(walk(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            errors.extend(walk(item, f"{path}[{index}]"))
    return errors


def verify_workflow_immutability(tracked: set[str]) -> list[str]:
    errors: list[str] = []
    for path in sorted(FORBIDDEN_AUTHORING_WORKFLOWS & tracked):
        errors.append(f"one-shot source-mutating AuthBus workflow is forbidden: {path}")
    if not WORKFLOW_ROOT.is_dir():
        return errors
    for workflow in sorted(WORKFLOW_ROOT.glob("authbus-*.yml")):
        relative = workflow.relative_to(ROOT).as_posix()
        text = workflow.read_text(encoding="utf-8")
        match = SOURCE_MUTATION.search(text)
        if match:
            token = " ".join(match.group(0).split())
            errors.append(
                f"AuthBus workflow must be read-only: {relative} contains {token!r}"
            )
    return errors


def verify() -> list[str]:
    errors: list[str] = []
    if not MAP.is_file():
        return ["missing AuthBus implementation map"]
    mapping = load(MAP)
    if mapping.get("schema") != "hepta.module-implementation-map.v4":
        errors.append("implementation map must use schema v4")
    identity = mapping.get("sourceIdentity")
    if not isinstance(identity, dict):
        errors.append("implementation map sourceIdentity is missing")
    else:
        if identity.get("mode") != "runtime_exact_head":
            errors.append("implementation map must require runtime exact-head binding")
        if identity.get("committedIdentity") is not None:
            errors.append("implementation map committedIdentity must remain null")
        if identity.get("boundArtifact") != "implementation-map.bound.json":
            errors.append("implementation map bound artifact name drift")
    for decision in ("productionImplementation", "activation", "release"):
        if mapping.get(decision) is not False:
            errors.append(f"static implementation map must keep {decision}=false")
    errors.extend(walk(mapping))

    if not READINESS.is_file():
        errors.append("missing AuthBus readiness contract")
    else:
        contract = load(READINESS)
        if contract.get("schema") != "hepta.authbus.readiness-contract.v1":
            errors.append("readiness contract schema mismatch")
        if contract.get("staticDecision") != {
            "productionQualified": False,
            "mergeReady": False,
            "approvedForCanary": False,
            "productionActivated": False,
            "release": False,
        }:
            errors.append("readiness contract static decision is not fail-closed")

    tracked = set(tracked_files())
    errors.extend(verify_workflow_immutability(tracked))
    for path in sorted(tracked):
        if GENERATED_NAME.search(path):
            errors.append(f"generated AuthBus evidence is committed: {path}")
        if path.startswith("docs/modules/auth.authbus/") and path.endswith(".json"):
            name = Path(path).name
            if name in {
                "CURRENT_STATUS.json",
                "RELEASE_STATUS.json",
                "READINESS_STATUS.json",
            }:
                errors.append(f"manual AuthBus status file is forbidden: {path}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", required=True)
    parser.parse_args()
    try:
        errors = verify()
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"AuthBus source-truth validation failed: {error}") from error
    if errors:
        raise SystemExit("AuthBus source-truth validation failed:\n" + "\n".join(errors))


if __name__ == "__main__":
    main()
